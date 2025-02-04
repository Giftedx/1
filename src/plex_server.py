import asyncio
import logging
from plexapi.server import PlexServer as PlexServerSync
from src.utils.config import Config
from src.core.exceptions import MediaNotFoundError
from src.metrics import ACTIVE_STREAMS
from src.core.caching import cached
from src.monitoring.metrics import track_latency
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
        self.plex_url = plex_url
        self.token = token
        self.server = PlexServerSync(plex_url, token)
        self._metrics = {
            'search_latency': Histogram('plex_search_latency_seconds', 
                                      'Time taken for Plex searches'),
            'errors': Counter('plex_errors_total', 'Number of Plex errors',
                            ['type'])
        }
        self._connection_pool = AsyncConnectionPool(max_size=10)
        self._request_semaphore = asyncio.Semaphore(5)
        self._media_cache = TTLCache(maxsize=1000, ttl=300)

    @asynccontextmanager
    async def _plex_session(self):
        async with self._request_semaphore:
            try:
                conn = await self._connection_pool.acquire()
                yield conn
            finally:
                await self._connection_pool.release(conn)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def ping(self) -> None:
        """
        Ping the Plex server with retries.
        """
        await asyncio.to_thread(self.server.system)

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
        async with self._plex_session() as session:
            try:
                with self._metrics['search_latency'].time():
                    return await self._fetch_media_with_retry(session, media_path)
            except Exception as e:
                self._handle_media_error(e, media_path)
                raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    @cached(ttl=60)
    @track_latency("plex_search")
    async def search_media(self, query: str):
        """Search for media with caching and retries."""
        return await asyncio.to_thread(self.server.library.search, query)

    def get_active_streams_count(self) -> int:
        return ACTIVE_STREAMS.get_current_value()