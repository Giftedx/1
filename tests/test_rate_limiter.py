import asyncio
import pytest
from unittest.mock import AsyncMock
from src.core.rate_limiter import RateLimiter

@pytest.fixture
def redis_manager_mock():
    redis_manager = AsyncMock()
    redis_manager.redis = AsyncMock()
    redis_manager.redis.pipeline = AsyncMock()
    return redis_manager

@pytest.mark.asyncio
async def test_is_rate_limited(redis_manager_mock):
    rate_limiter = RateLimiter(max_requests=10, window_seconds=60, redis_manager=redis_manager_mock)
    redis_manager_mock.redis.pipeline.return_value.__aenter__.return_value.execute.return_value = [0, 0, 5, 60]
    is_limited = await rate_limiter.is_rate_limited("user1")
    assert not is_limited

@pytest.mark.asyncio
async def test_is_rate_limited_exceeded(redis_manager_mock):
    rate_limiter = RateLimiter(max_requests=10, window_seconds=60, redis_manager=redis_manager_mock)
    redis_manager_mock.redis.pipeline.return_value.__aenter__.return_value.execute.return_value = [0, 0, 20, 60]
    is_limited = await rate_limiter.is_rate_limited("user1")
    assert is_limited

@pytest.mark.asyncio
async def test_reset_rate_limit(redis_manager_mock):
    rate_limiter = RateLimiter(max_requests=10, window_seconds=60, redis_manager=redis_manager_mock)
    await rate_limiter.reset_rate_limit("user1")
    redis_manager_mock.redis.delete.assert_called_once_with("rl:user1")