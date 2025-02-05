import logging
from typing import Optional, Dict, Any
from plexapi.server import PlexServer
from plexapi.video import Video
from src.core.exceptions import MediaNotFoundError
from src.core.cache_manager import CacheManager
from src.metrics import PLEX_REQUESTS, PLEX_ERRORS

logger = logging.getLogger(__name__)

class PlexManager:
    def __init__(self, base_url: str, token: str, cache_manager: CacheManager):
        self.plex = PlexServer(base_url, token)
        self.cache = cache_manager
        self.search_cache: Dict[str, Any] = {}

    async def get_media(self, query: str) -> Video:
        cache_key = f"plex:search:{query}"
        cached = await self.cache.get(cache_key)
        
        if cached:
            return cached

        try:
            PLEX_REQUESTS.inc()
            results = self.plex.library.search(query)
            if not results:
                raise MediaNotFoundError(f"No media found for query: {query}")
            
            media = results[0]
            await self.cache.set(cache_key, media, expire=3600)
            return media

        except Exception as e:
            PLEX_ERRORS.inc()
            logger.error(f"Plex search failed: {e}")
            raise

    async def get_stream_url(self, media_id: str) -> str:
        cache_key = f"plex:stream:{media_id}"
        cached = await self.cache.get(cache_key)
        
        if cached:
            return cached

        try:
            media = self.plex.fetchItem(media_id)
            stream_url = media.getStreamURL()
            await self.cache.set(cache_key, stream_url, expire=1800)
            return stream_url
        except Exception as e:
            PLEX_ERRORS.inc()
            logger.error(f"Failed to get stream URL: {e}")
            raise
