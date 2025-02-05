import asyncio
from typing import Any, Optional, Callable, TypeVar
from functools import wraps
import time
import functools

T = TypeVar('T')

class Cache:
    def __init__(self, ttl: int = 300):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    return value
                del self._cache[key]
        return None

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._cache[key] = (value, time.time() + self._ttl)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._cache.pop(key, None)

def cached(ttl: int = 300):
    cache = Cache(ttl)
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            result = await cache.get(key)
            if result is None:
                result = await func(*args, **kwargs)
                await cache.set(key, result)
            return result
        return wrapper
    return decorator

def simple_cache(func):
    # Renamed duplicate decorator to simple_cache
    cache_store = {}
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        key = (args, frozenset(kwargs.items()))
        if key in cache_store:
            return cache_store[key]
        result = await func(*args, **kwargs)
        cache_store[key] = result
        return result
    return wrapper
