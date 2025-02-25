import asyncio
import logging
import aiohttp
from plexapi.server import PlexServer as PlexServerSync
from src.utils.config import Config
from src.core.exceptions import MediaNotFoundError
from src.core.caching import cached
from tenacity import retry, stop_after_attempt, wait_exponential
from prometheus_client import Counter, Histogram, Gauge  # Import Gauge
from functools import lru_cache
from contextlib import asynccontextmanager
from cachetools import TTLCache
from src.metrics import METRICS

logger = logging.getLogger(__name__)

class PlexServer:
    _instance = None

    @classmethod
    def get_instance(cls) -> "PlexServer":
        if cls._instance is None:
            config = Config()
            cls._instance = cls(plex_url=str(config.PLEX_URL), token=config.PLEX_TOKEN)
        return cls._instance

    def __init__(self, plex_url: str, token: str):
        self.plex_url = plex_url.rstrip("/")
        self.token = token
        try:
            self.server = PlexServerSync(self.plex_url, self.token)
        except Exception as e:
            logger.error(f"Plex initialization error: {e}", exc_info=True)
            METRICS.record_error("PlexInitializationError", "critical")
            raise
        self._metrics = {
            'search_latency': Histogram('plex_search_latency_seconds', 
                                      'Time taken for Plex searches'),
            'errors': Counter('plex_errors_total', 'Number of Plex errors',
                            ['type']),
            'api_requests': Counter('plex_api_requests_total',
                                    'Total number of Plex API requests'),
            'active_streams': Gauge('plex_active_streams',  # Use Gauge
                                    'Number of active Plex streams')
        }
        self._connection_pool = None  # Replace with your async pool if needed.
        self._request_semaphore = asyncio.Semaphore(5)
        self._media_cache = TTLCache(maxsize=1000, ttl=300)  # 5 minutes TTL
        self._connection_semaphore = asyncio.Semaphore(10)
        self._reconnect_delay = 1.0

    def invalidate_media_cache(self, media_path: str):
        """Invalidate the cache entry for a specific media path."""
        try:
            del self._media_cache[media_path]
        except KeyError:
            pass  # Key not in cache

    @asynccontextmanager
    async def _plex_session(self):
        async with self._request_semaphore:
            # ...acquire async connection
            yield

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def ping(self) -> bool:
        """
        Ping the Plex server with retries.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.plex_url}/", headers={"X-Plex-Token": self.token}) as resp:
                    self._metrics['api_requests'].inc()
                    return resp.status == 200
        except Exception as e:
            logger.exception("Plex ping failed")
            METRICS.record_error("PlexPingError", "error")
            return False

    async def get_media(self, media_path: str):
        # Plex media retrieval logic
        try:
            async with aiohttp.ClientSession() as session:
                media = await asyncio.to_thread(self.server.library.search, media_path)
                if not media:
                    raise MediaNotFoundError(f"Media not found: {media_path}")
                return media
        except Exception as e:
            logger.error(f"Error getting media: {e}", exc_info=True)
            METRICS.record_error("PlexGetMediaError", "error")
            raise

    @cached(ttl=300)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def get_media_info(self, media_path: str):
        try:
            with METRICS.timer("plex_get_media_info"):
                self._metrics['api_requests'].inc()
                return await asyncio.to_thread(self.server.library.search, media_path)
        except Exception as e:
            logger.error(f"Error fetching media info for {media_path}: {e}", exc_info=True)
            METRICS.record_error("PlexGetMediaInfoError", "error")
            raise

    async def search_media(self, query: str):
        cache_key = f"search:{query}"
        if cache_key in self._media_cache:
            return self._media_cache[cache_key]

        async with self._connection_semaphore:
            try:
                with METRICS.timer("plex_search_media"):
                    self._metrics['api_requests'].inc()
                    result = await self._search_with_retry(query)
                    self._media_cache[cache_key] = result
                    self._reconnect_delay = max(1.0, self._reconnect_delay * 0.9)
                    return result
            except Exception as e:
                self._reconnect_delay = min(60.0, self._reconnect_delay * 2)
                logger.error(f"Plex search error: {e}", exc_info=True)
                METRICS.record_error("PlexSearchError", "error")
                raise

    async def _search_with_retry(self, query: str):
        """Helper method to encapsulate the actual search logic with retry."""
        try:
            self._metrics['api_requests'].inc()
            return await asyncio.to_thread(self.server.library.search, query)
        except Exception as e:
            logger.error(f"Error during search attempt: {e}", exc_info=True)
            raise

    async def search_and_validate(self, query: str) -> dict:
        try:
            return await self.search_media(query)
        except Exception as e:
            logger.error(f"Search and validate failed: {e}", exc_info=True)
            METRICS.record_error("PlexSearchValidateError", "error")
            raise

    def get_active_streams_count(self) -> int:
        return 0