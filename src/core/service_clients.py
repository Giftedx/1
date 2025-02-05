import aiohttp
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class BaseServiceClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = aiohttp.ClientSession()
        
    async def _api_call(self, endpoint: str, method: str = 'GET', **kwargs) -> Dict:
        headers = {'X-Api-Key': self.api_key}
        async with self.session.request(
            method, 
            f"{self.base_url}/{endpoint}", 
            headers=headers,
            **kwargs
        ) as resp:
            if resp.status != 200:
                logger.error(f"API error: {resp.status} - {await resp.text()}")
                return {}
            return await resp.json()

class SonarrClient(BaseServiceClient):
    async def get_queue_stats(self) -> Dict:
        return await self._api_call('queue/status')
        
    async def get_calendar(self) -> List[Dict]:
        return await self._api_call('calendar')

class RadarrClient(BaseServiceClient):
    async def get_queue_stats(self) -> Dict:
        return await self._api_call('queue/status')
        
    async def get_movies(self) -> List[Dict]:
        return await self._api_call('movie')

class OverseerrClient(BaseServiceClient):
    async def get_request_stats(self) -> Dict:
        return await self._api_call('request/count')
        
    async def get_requests(self) -> List[Dict]:
        return await self._api_call('request')

class DiscordStatsClient(BaseServiceClient):
    async def get_server_stats(self, server_id: str) -> Dict:
        return await self._api_call(f'guilds/{server_id}/stats')
