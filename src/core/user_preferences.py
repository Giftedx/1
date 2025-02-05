from typing import Dict, Any
import json
import redis.asyncio as redis
from dataclasses import dataclass, asdict

@dataclass
class UserPreferences:
    user_id: str
    theme: str = 'default'
    layout: Dict[str, Any] = None
    widgets: Dict[str, bool] = None
    notifications: Dict[str, bool] = None
    playback: Dict[str, Any] = None

class PreferencesManager:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
        self.cache = {}

    async def get_preferences(self, user_id: str) -> UserPreferences:
        if user_id in self.cache:
            return self.cache[user_id]

        data = await self.redis.get(f"prefs:{user_id}")
        if data:
            prefs_dict = json.loads(data)
            prefs = UserPreferences(**prefs_dict)
        else:
            prefs = UserPreferences(user_id=user_id)
        
        self.cache[user_id] = prefs
        return prefs

    async def save_preferences(self, prefs: UserPreferences):
        await self.redis.set(
            f"prefs:{prefs.user_id}",
            json.dumps(asdict(prefs))
        )
        self.cache[prefs.user_id] = prefs

    async def update_preferences(self, user_id: str, updates: Dict[str, Any]):
        prefs = await self.get_preferences(user_id)
        for key, value in updates.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        await self.save_preferences(prefs)
