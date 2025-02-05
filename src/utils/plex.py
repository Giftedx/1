import aiohttp
import logging
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class PlexClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self._cache = TTLCache(maxsize=1000, ttl=300)
        self._session = None
        self._request_semaphore = asyncio.Semaphore(10)

    async def get_media_url(self, title: str) -> str:
        cache_key = f"media_url:{title}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        async with self._request_semaphore:
            try:
                if not self._session:
                    self._session = aiohttp.ClientSession()
                
                headers = {
                    'X-Plex-Token': self.token,
                    'Accept': 'application/json'
                }
                
                async with self._session.get(
                    f"{self.base_url}/library/sections/all/search",
                    params={'query': title},
                    headers=headers
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    
                results = data.get('MediaContainer', {}).get('Metadata', [])
                if not results:
                    return None
                    
                media_key = results[0]['key']
                url = f"{self.base_url}{media_key}?X-Plex-Token={self.token}"
                self._cache[cache_key] = url
                return url
                
            except Exception as e:
                logger.error(f"Plex API error: {e}", exc_info=True)
                return None
