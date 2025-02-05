import aiohttp
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class StreamInfo:
    session_id: str
    title: str
    user: str
    platform: str
    player: str
    quality_profile: str
    bandwidth: int
    started: datetime
    state: str
    progress: float
    duration: int
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    container: Optional[str] = None

class TautulliClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = aiohttp.ClientSession()

    async def close(self):
        await self.session.close()

    async def _api_call(self, cmd: str, **params) -> Dict:
        params = {
            'apikey': self.api_key,
            'cmd': cmd,
            **params
        }
        
        async with self.session.get(f"{self.base_url}/api/v2", params=params) as resp:
            if resp.status != 200:
                logger.error(f"Tautulli API error: {resp.status} - {await resp.text()}")
                return {}
            data = await resp.json()
            return data.get('response', {}).get('data', {})

    async def get_activity(self) -> List[StreamInfo]:
        data = await self._api_call('get_activity')
        sessions = data.get('sessions', [])
        
        return [
            StreamInfo(
                session_id=session.get('session_id'),
                title=session.get('full_title'),
                user=session.get('friendly_name'),
                platform=session.get('platform'),
                player=session.get('player'),
                quality_profile=session.get('quality_profile'),
                bandwidth=session.get('bandwidth', 0),
                started=datetime.fromtimestamp(session.get('started', 0)),
                state=session.get('state'),
                progress=session.get('progress_percent', 0),
                duration=session.get('duration', 0),
                video_codec=session.get('video_codec'),
                audio_codec=session.get('audio_codec'),
                resolution=session.get('video_resolution'),
                container=session.get('container')
            )
            for session in sessions
        ]

    async def get_history(self, length: int = 10) -> List[Dict]:
        return await self._api_call('get_history', length=length)

    async def get_libraries(self) -> List[Dict]:
        return await self._api_call('get_libraries')

    async def get_server_stats(self) -> Dict:
        return await self._api_call('get_server_stats')

    async def get_stream_data(self) -> Dict:
        """Get detailed stream statistics for visualization"""
        activity = await self.get_activity()
        stats = await self.get_server_stats()
        
        return {
            'current_streams': [
                {
                    'id': s.session_id,
                    'title': s.title,
                    'quality': s.quality_profile,
                    'bandwidth': s.bandwidth,
                    'progress': s.progress,
                    'duration': s.duration,
                    'codecs': {
                        'video': s.video_codec,
                        'audio': s.audio_codec
                    },
                    'resolution': s.resolution,
                    'state': s.state
                }
                for s in activity
            ],
            'bandwidth_history': stats.get('bandwidth_history', []),
            'stream_count_history': stats.get('stream_count_history', []),
            'total_bandwidth': sum(s.bandwidth for s in activity),
            'platform_breakdown': self._count_platforms(activity),
            'quality_breakdown': self._count_quality_profiles(activity)
        }

    def _count_platforms(self, streams: List[StreamInfo]) -> Dict[str, int]:
        platforms = {}
        for stream in streams:
            platforms[stream.platform] = platforms.get(stream.platform, 0) + 1
        return platforms

    def _count_quality_profiles(self, streams: List[StreamInfo]) -> Dict[str, int]:
        profiles = {}
        for stream in streams:
            profiles[stream.quality_profile] = profiles.get(stream.quality_profile, 0) + 1
        return profiles
