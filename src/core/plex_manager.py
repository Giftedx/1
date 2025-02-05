import logging
import asyncio
from typing import List, Optional
from functools import lru_cache
from plexapi.server import PlexServer
from plexapi.video import Video
from plexapi.exceptions import NotFound, Unauthorized
from tenacity import retry, stop_after_attempt, wait_exponential
from src.core.exceptions import MediaNotFoundError, StreamingError
from src.utils.config import settings
from src.monitoring.metrics import PLEX_REQUEST_DURATION, plex_metrics

logger = logging.getLogger(__name__)

class PlexManager:
    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        self.url = url or settings.PLEX_URL
        self.token = token or settings.PLEX_TOKEN
        self._server: Optional[PlexServer] = None
        self._lock = asyncio.Lock()
        self._connection_retries = 0
        self._max_retries = 3
        self._retry_delay = 1.0
        self._connect()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def _connect(self) -> None:
        """Connect to the Plex server instance with retries."""
        try:
            self._server = PlexServer(self.url, self.token)
            logger.info(f"Connected to Plex server: {self._server.friendlyName}")
            plex_metrics.server_connection.inc()
            self._connection_retries = 0
            self._retry_delay = 1.0
        except Unauthorized:
            logger.error("Invalid Plex credentials")
            plex_metrics.connection_errors.inc()
            raise StreamingError("Invalid Plex credentials")
        except Exception as e:
            self._connection_retries += 1
            self._retry_delay = min(30, self._retry_delay * 2)
            logger.error(f"Failed to connect to Plex server: {e}")
            plex_metrics.connection_errors.inc()
            raise StreamingError(f"Plex connection failed: {str(e)}")

    @property
    async def server(self) -> PlexServer:
        """Get Plex server instance with auto-reconnect and thread safety."""
        async with self._lock:
            if not self._server:
                self._connect()
            return self._server

    @PLEX_REQUEST_DURATION.time()
    @lru_cache(maxsize=100)
    async def search_media(self, query: str, media_type: Optional[str] = None) -> List[Video]:
        """Search for media with caching, metrics, and improved error handling."""
        try:
            server = await self.server
            filters = {"mediatype": media_type} if media_type else {}

            results = await asyncio.to_thread(
                server.library.search,
                query,
                **filters
            )
            
            if not results:
                plex_metrics.search_misses.inc()
                raise MediaNotFoundError(f"No media found for query: {query}")
            
            videos = [r for r in results if isinstance(r, Video)]
            if not videos:
                plex_metrics.search_misses.inc()
                raise MediaNotFoundError(f"No video content found for query: {query}")
            
            plex_metrics.search_hits.inc()
            return videos

        except NotFound:
            plex_metrics.search_misses.inc()
            raise MediaNotFoundError(f"No media found for query: {query}")
        except Exception as e:
            plex_metrics.search_errors.inc()
            logger.error(f"Plex search failed: {e}", exc_info=True)
            if "Unauthorized" in str(e):
                await self._reconnect()
                raise StreamingError("Session expired, please try again")
            raise StreamingError(f"Plex search failed: {str(e)}")

    @PLEX_REQUEST_DURATION.time()
    async def get_stream_url(self, video: Video) -> str:
        """Get direct stream URL with proper error handling."""
        try:
            stream_url = await asyncio.to_thread(video.getStreamURL)
            if not stream_url:
                raise StreamingError("Failed to get stream URL")

            plex_metrics.stream_urls_generated.inc()
            return stream_url

        except Exception as e:
            plex_metrics.stream_errors.inc()
            logger.error(f"Failed to get stream URL: {e}", exc_info=True)
            if "Unauthorized" in str(e):
                await self._reconnect()
                raise StreamingError("Session expired, please try again")
            raise StreamingError(f"Stream URL generation failed: {str(e)}")

    async def _reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        if self._connection_retries >= self._max_retries:
            raise StreamingError("Max reconnection attempts reached")
        
        await asyncio.sleep(self._retry_delay)
        async with self._lock:
            self._server = None
            await self.server

    async def close(self) -> None:
        """Clean up resources."""
        if self._server:
            try:
                await asyncio.to_thread(self._server.close)
            except Exception as e:
                logger.error(f"Error closing Plex connection: {e}")
            finally:
                self._server = None

    def invalidate_cache(self) -> None:
        """Clear the search cache."""
        self.search_media.cache_clear()
