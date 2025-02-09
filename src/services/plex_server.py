from functools import lru_cache
from cachetools import TTLCache
from typing import Optional

class PlexServer:
    _instance: Optional['PlexServer'] = None
    
    def __init__(self, plex_url: str, token: str) -> None:
        self._url = plex_url
        self._token = token
        self._cache = TTLCache(maxsize=100, ttl=300)  # 5 minute TTL
        
    @classmethod
    def get_instance(cls) -> "PlexServer":
        """Get or create singleton instance."""
        if cls._instance is None:
            config = Config()
            cls._instance = cls(
                plex_url=str(config.PLEX_URL),
                token=config.PLEX_TOKEN
            )
        return cls._instance

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def ping(self) -> bool:
        """Check server connectivity with retries."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._url}/",
                    headers={"X-Plex-Token": self._token}
                ) as resp:
                    if resp.status == 401:
                        raise UnauthorizedError("Invalid Plex token")
                    resp.raise_for_status()
                    return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.exception("Plex ping failed")
            return False

    # ...existing code...
