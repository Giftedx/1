import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from src.utils.redis_manager import RedisManager, RedisKeys
from asynctest import IsolatedAsyncioTestCase

@pytest.fixture
async def redis_manager():
    """
    Fixture for creating a RedisManager instance with a mock Redis client.
    """
    with patch("src.utils.redis_manager.redis.Redis") as MockRedis:
        mock_redis = AsyncMock()
        MockRedis.return_value = mock_redis
        manager = RedisManager(host="localhost", port=6379)
        yield manager
        await manager.close()

class TestRedisManager(IsolatedAsyncioTestCase):
    """
    Tests for the RedisManager class.
    """
    async def test_add_to_queue(self, redis_manager):
        """
        Test adding an item to the queue.
        """
        item = "test_item"
        await redis_manager.add_to_queue(item)
        redis_manager.redis.rpush.assert_called_once_with(redis_manager.keys.queue_key, item)

    async def test_get_queue_length(self, redis_manager):
        """
        Test getting the queue length.
        """
        redis_manager.redis.llen.return_value = 5
        length = await redis_manager.get_queue_length()
        self.assertEqual(length, 5)
        redis_manager.redis.llen.assert_called_once_with(redis_manager.keys.queue_key)

    async def test_get_from_queue(self, redis_manager):
        """
        Test getting an item from the queue.
        """
        redis_manager.redis.blpop.return_value = [b'queue', b'test_item']
        item = await redis_manager.get_from_queue()
        self.assertEqual(item, "test_item")
        redis_manager.redis.blpop.assert_called_once_with(redis_manager.keys.queue_key, timeout=0)

    async def test_get_from_queue_timeout(self, redis_manager):
        """
        Test getting an item from the queue with a timeout.
        """
        redis_manager.redis.blpop.return_value = None
        item = await redis_manager.get_from_queue(timeout=10)
        self.assertIsNone(item)
        redis_manager.redis.blpop.assert_called_once_with(redis_manager.keys.queue_key, timeout=10)

    async def test_queue_iterator(self, redis_manager):
        """
        Test the queue iterator.
        """
        redis_manager.redis.blpop.side_effect = [
            [b'queue', b'item1'],
            [b'queue', b'item2'],
            None
        ]
        items = []
        async for batch in redis_manager.queue_iterator(batch_size=1):
            items.extend(batch)
        self.assertEqual(items, ["item1", "item2"])

    async def test_clear_queue(self, redis_manager):
        """
        Test clearing the queue.
        """
        await redis_manager.clear_queue()
        redis_manager.redis.delete.assert_called_once_with(redis_manager.keys.queue_key)

    async def test_get_all_items(self, redis_manager):
        """
        Test getting all items from the queue.
        """
        redis_manager.redis.llen.return_value = 2
        redis_manager.redis.lrange.return_value = [b'item1', b'item2']
        items = await redis_manager.get_all_items()
        self.assertEqual(items, ["item1", "item2"])
        redis_manager.redis.llen.assert_called_once_with(redis_manager.keys.queue_key)
        redis_manager.redis.lrange.assert_called_once_with(redis_manager.keys.queue_key, 0, 1)

    async def test_close(self, redis_manager):
        """
        Test closing the Redis connection.
        """
        await redis_manager.close()
        redis_manager.redis.close.assert_called_once()