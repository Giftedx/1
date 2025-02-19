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
from src.monitoring.metrics import plex_metrics

logger = logging.getLogger(__name__)

class PlexManager:
    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        self._url = url or settings.PLEX_URL
        self._token = token or settings.PLEX_TOKEN
        self._server = None
        self._lock = asyncio.Lock()
        self._session = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    async def _connect(self) -> None:
        """Connects to the Plex server."""
        try:
            self._server = PlexServer(self._url, self._token)
            logger.info("Connected to Plex server.")
        except Unauthorized:
            logger.error("Plex authentication failed.")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Plex: {e}")
            raise

    @property
    async def server(self) -> PlexServer:
        """Returns the Plex server instance, reconnecting if necessary."""
        if not self._server:
            async with self._lock:
                if not self._server:
                    await self._connect()
        return self._server

    @lru_cache(maxsize=100)
    @plex_metrics.request_duration.time()
    async def search_media(self, title: str) -> List[Video]:
        """Searches for media items in the Plex library."""
        try:
            plex_server = await self.server
            media = plex_server.search(title)
            if not media:
                raise MediaNotFoundError(f"Media '{title}' not found in Plex.")
            return media
        except NotFound:
            raise MediaNotFoundError(f"Media '{title}' not found in Plex.")
        except Exception as e:
            logger.error(f"Plex search failed: {e}", exc_info=True)
            raise

    @plex_metrics.request_duration.time()
    async def get_stream_url(self, media_item: Video) -> str:
        """Gets the stream URL for a media item."""
        try:
            plex_server = await self.server
            stream = media_item.getStream()
            if not stream:
                raise StreamingError("No stream found for this media.")
            return plex_server.url + stream.url + '?X-Plex-Token=' + plex_server._token
        except Exception as e:
            logger.error(f"Could not get stream URL: {e}", exc_info=True)
            raise StreamingError(f"Could not get stream URL: {e}")

    async def _reconnect(self) -> None:
        """Reconnects to the Plex server."""
        async with self._lock:
            self._server = None
            await self._connect()

    async def close(self) -> None:
        """Closes the session."""
        if self._session:
            await self._session.close()
            self._session = None

    def invalidate_cache(self) -> None:
        """Invalidates the cache."""
        self.search_media.cache_clear()
