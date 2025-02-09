import asyncio
from datetime import datetime
import pytest
from src.core.queue_manager import QueueManager, QueueItem, QueuePriority
from src.core.redis_manager import RedisManager  # You might need a mock RedisManager

@pytest.fixture
def redis_manager_mock():
    # Replace with a mock RedisManager if you're not using Redis
    class MockRedisManager:
        async def execute(self, *args, **kwargs):
            return None  # Or return appropriate mock data
    return MockRedisManager()

@pytest.fixture
def queue_manager(redis_manager_mock):
    return QueueManager(max_length=3, redis_manager=redis_manager_mock)

@pytest.mark.asyncio
async def test_add_and_get(queue_manager):
    item1 = QueueItem(media_id="1", requester_id="user1", timestamp=datetime.now(), priority=QueuePriority.HIGH)
    item2 = QueueItem(media_id="2", requester_id="user2", timestamp=datetime.now(), priority=QueuePriority.MEDIUM)
    item3 = QueueItem(media_id="3", requester_id="user3", timestamp=datetime.now(), priority=QueuePriority.LOW)

    await queue_manager.add(item1)
    await queue_manager.add(item2)
    await queue_manager.add(item3)

    assert len(queue_manager.queue) == 3
    assert (await queue_manager.get()).media_id == "1"
    assert (await queue_manager.get()).media_id == "2"
    assert (await queue_manager.get()).media_id == "3"
    assert (await queue_manager.get()) is None  # Queue is empty

@pytest.mark.asyncio
async def test_priority_ordering(queue_manager):
    item1 = QueueItem(media_id="1", requester_id="user1", timestamp=datetime.now(), priority=QueuePriority.LOW)
    item2 = QueueItem(media_id="2", requester_id="user2", timestamp=datetime.now(), priority=QueuePriority.HIGH)
    item3 = QueueItem(media_id="3", requester_id="user3", timestamp=datetime.now(), priority=QueuePriority.MEDIUM)

    await queue_manager.add(item1)
    await queue_manager.add(item2)
    await queue_manager.add(item3)

    assert (await queue_manager.get()).media_id == "2"
    assert (await queue_manager.get()).media_id == "3"
    assert (await queue_manager.get()).media_id == "1"

@pytest.mark.asyncio
async def test_clear(queue_manager):
    item1 = QueueItem(media_id="1", requester_id="user1", timestamp=datetime.now(), priority=QueuePriority.HIGH)
    await queue_manager.add(item1)
    assert len(queue_manager.queue) == 1

    await queue_manager.clear()
    assert len(queue_manager.queue) == 0
    assert queue_manager.current_item is None