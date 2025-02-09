import redis.asyncio as redis
from typing import Optional, AsyncIterator, List
import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class RedisKeys:
    """
    Keys definition class to handle, build the name of Redis objects, hashes.
    It defines keys structure as <ROOT>:<CATEGORY>:<SUBCATEGORY>, where all values should be defined as strings.

    Attributes:
        queue_key: main str key for operations.
        prefix: name for main module to generate metric keys.
    """

    queue_key: str = "media_queue"
    stats_key: str = "queue_stats"

class RedisManager:
    def __init__(self, host: str = "localhost", port: int = 6379):
        self.host = host
        self.port = port
        self.redis = None  # Initialize redis connection to None
        self.keys = RedisKeys()

    async def connect(self):
        """Connects to the Redis server."""
        try:
            self.redis = redis.Redis(host=self.host, port=self.port)
            await self.redis.ping()  # Check connection
            logger.info("Connected to Redis server")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Could not connect to Redis: {e}")
            raise

    async def add_to_queue(self, item: str):
        """Adds an item to the Redis queue."""
        try:
            await self.redis.rpush(self.keys.queue_key, item)
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error adding to queue: {e}")
            raise

    async def get_queue_length(self) -> int:
        """Gets the length of the Redis queue."""
        try:
            return await self.redis.llen(self.keys.queue_key)
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error getting queue length: {e}")
            return 0

    async def get_from_queue(self, timeout: int = 0) -> Optional[str]:
        """Gets an item from the Redis queue with an optional timeout."""
        try:
            result = await self.redis.blpop(self.keys.queue_key, timeout=timeout)
            if result:
                _, value = result
                return value.decode("utf-8")
            return None
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error getting from queue: {e}")
            return None

    async def queue_iterator(self, batch_size: int = 10) -> AsyncIterator[List[str]]:
        """
        Asynchronously yields batches of items from the Redis queue.

        Args:
            batch_size: The number of items to yield in each batch.

        Yields:
            A list of strings representing a batch of items from the queue.
        """
        while True:
            items = []
            for _ in range(batch_size):
                item = await self.get_from_queue()
                if item:
                    items.append(item)
                else:
                    break  # Queue is empty

            if items:
                yield items
            else:
                break  # No more items in the queue

    async def clear_queue(self):
        """Clears the Redis queue."""
        try:
            await self.redis.delete(self.keys.queue_key)
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error clearing queue: {e}")

    async def get_all_items(self) -> List[str]:
        """Retrieves all items from the Redis queue."""
        try:
            queue_length = await self.get_queue_length()
            items = await self.redis.lrange(self.keys.queue_key, 0, queue_length - 1)
            return [item.decode("utf-8") for item in items]
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error getting all items: {e}")
            return []

    async def close(self):
        """Closes the Redis connection."""
        if self.redis:
            try:
                await self.redis.close()
                logger.info("Redis connection closed")
            except redis.exceptions.RedisError as e:
                logger.error(f"Error closing Redis connection: {e}")
