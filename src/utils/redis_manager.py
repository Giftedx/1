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
        self.redis = redis.Redis(host=host, port=port)
        self.keys = RedisKeys()

    async def add_to_queue(self, item: str):
        """Adds an item to the Redis queue."""
        await self.redis.rpush(self.keys.queue_key, item)

    async def get_queue_length(self) -> int:
        """Gets the length of the Redis queue."""
        return await self.redis.llen(self.keys.queue_key)

    async def get_from_queue(self, timeout: int = 0) -> Optional[str]:
        """Gets an item from the Redis queue with an optional timeout."""
        result = await self.redis.blpop(self.keys.queue_key, timeout=timeout)
        if result:
            _, value = result
            return value.decode("utf-8")
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
        await self.redis.delete(self.keys.queue_key)

    async def get_all_items(self) -> List[str]:
        """Retrieves all items from the Redis queue."""
        queue_length = await self.get_queue_length()
        items = await self.redis.lrange(self.keys.queue_key, 0, queue_length - 1)
        return [item.decode("utf-8") for item in items]

    async def close(self):
        """Closes the Redis connection."""
        await self.redis.close()
