import asyncio
import logging
import aiohttp
from plexapi.server import PlexServer as PlexServerSync
from src.utils.config import Config
from src.core.exceptions import MediaNotFoundError
from src.core.caching import cached
from tenacity import retry, stop_after_attempt, wait_exponential
from prometheus_client import Counter, Histogram
from functools import lru_cache
from contextlib import asynccontextmanager

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
            raise
        self._metrics = {
            'search_latency': Histogram('plex_search_latency_seconds', 
                                      'Time taken for Plex searches'),
            'errors': Counter('plex_errors_total', 'Number of Plex errors',
                            ['type'])
        }
        self._connection_pool = None  # Replace with your async pool if needed.
        self._request_semaphore = asyncio.Semaphore(5)
        self._media_cache = {}  # Replace with a TTLCache implementation.

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
                    return resp.status == 200
        except Exception:
            logger.exception("Plex ping failed")
            return False

    def get_media(self, media_path: str):
        # Plex media retrieval logic
        media = self.server.library.search(media_path)
        if not media:
            raise MediaNotFoundError(f"Media not found: {media_path}")
        return media

    @cached(ttl=300)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    @lru_cache(maxsize=100)
    async def get_media_info(self, media_path: str):
        try:
            with self._metrics['search_latency'].time():
                return await asyncio.to_thread(self.server.library.search, media_path)
        except Exception as e:
            logger.error(f"Error fetching media info for {media_path}: {e}", exc_info=True)
            raise

    async def search_media(self, query: str):
        logger.info(f"Searching Plex for media: {query}")
        media = await asyncio.to_thread(self.server.library.search, query)
        if not media:
            raise MediaNotFoundError(f"Media not found for query: {query}")
        item = media[0]
        return {"title": item.title, "media_path": item.media[0].file, "quality": "medium"}

    async def search_and_validate(self, query: str) -> dict:
        return await self.search_media(query)

    def get_active_streams_count(self) -> int:
        return 0