import json
import time
from typing import Dict, Optional, List, Tuple
from src.core.redis_manager import RedisManager
from src.core.redis_transaction import RedisTransaction
from src.core.exceptions import QueueFullError, QueueEmptyError
from src.monitoring.metrics import track_latency
from dataclasses import dataclass
from prometheus_client import Histogram, Gauge, Counter
import asyncio
import logging
from src.utils.backpressure import BackpressureManager
from src.utils.priority_queue import AdaptivePriorityQueue
from datetime import datetime
from src.metrics import METRICS

logger = logging.getLogger(__name__)

@dataclass
class QueuePriority:
    HIGH = 0
    NORMAL = 1
    LOW = 2

@dataclass
class QueueItem:
    media_id: str
    requester_id: str
    timestamp: datetime
    priority: int = 0

class QueueManager:
    """
    Manages the media queue using Redis.
    """
    def __init__(self, max_length: int, redis_manager: RedisManager) -> None:
        self.max_length = max_length
        self.redis_manager = redis_manager
        self.queue_key = "media_queue"
        self.stats_key = "queue_stats"
        self.priority_queues = {
            QueuePriority.HIGH: f"{self.queue_key}:high",
            QueuePriority.NORMAL: f"{self.queue_key}:normal",
            QueuePriority.LOW: f"{self.queue_key}:low"
        }
        self.transaction_manager = RedisTransaction(redis_manager)
        self._queue_metrics = {
            'enqueue_latency': Histogram('queue_enqueue_latency_seconds', 
                                       'Time taken to enqueue items'),
            'dequeue_latency': Histogram('queue_dequeue_latency_seconds', 
                                       'Time taken to dequeue items')
        }
        self._queue_size = Gauge('queue_size', 'Current queue size', ['priority'])
        self._dropped_items = Counter('queue_dropped_items', 'Number of dropped items')
        self._cleanup_task: Optional[asyncio.Task] = None
        self._backpressure = BackpressureManager(
            max_load=0.8,
            window_size=60
        )
        self._priority_queue = AdaptivePriorityQueue(
            max_size=max_length,
            priorities=[QueuePriority.HIGH, QueuePriority.NORMAL, QueuePriority.LOW]
        )
        self._batch_size = 10
        self._flush_interval = 1.0
        self._batch_processor = BatchProcessor(
            max_size=100,
            flush_interval=1.0,
            max_retries=3
        )
        self._priority_scheduler = PriorityScheduler(
            levels={
                QueuePriority.HIGH: 0.5,    # 50% of resources
                QueuePriority.NORMAL: 0.3,  # 30% of resources
                QueuePriority.LOW: 0.2      # 20% of resources
            }
        )
        self.queue: List[QueueItem] = []
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
        self.current_item: Optional[QueueItem] = None

    async def start(self) -> None:
        """Start background tasks."""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        while True:
            try:
                await self._clean_expired_items()
                await self._update_metrics()
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")
            await asyncio.sleep(300)  # Run every 5 minutes

    async def _update_metrics(self) -> None:
        for priority, queue in self.priority_queues.items():
            length = await self.redis_manager.execute('LLEN', queue)
            self._queue_size.labels(priority=priority).set(length)

    @track_latency("queue_add")
    async def add(self, media_info: dict, priority: int = QueuePriority.NORMAL) -> None:
        if not await self._backpressure.can_accept():
            raise QueueFullError("System under high load")

        async with self._batch_operation() as batch:
            batch.append((priority, media_info))
            if len(batch) >= self._batch_size:
                await self._flush_batch(batch)

    async def _flush_batch(self, items: List[tuple]) -> None:
        async with self.redis_manager.pipeline() as pipe:
            for priority, item in items:
                queue_key = self.priority_queues[priority]
                pipe.rpush(queue_key, json.dumps(item))
            await pipe.execute()

    async def add_batch(self, items: List[dict], priority: int = QueuePriority.NORMAL) -> None:
        async with self._batch_processor.batch() as batch:
            for item in items:
                item['added_at'] = time.time()
                batch.add_item(priority, item)

    @track_latency("queue_get")
    async def get_next(self) -> Optional[dict]:
        priority = await self._priority_scheduler.get_next_priority()
        for _ in range(len(self.priority_queues)):
            try:
                return await self._pop_from_queue(priority)
            except QueueEmptyError:
                priority = self._priority_scheduler.get_fallback_priority(priority)
        raise QueueEmptyError("All queues empty")

    async def get_queue_stats(self) -> Dict[str, int]:
        stats = await self.redis_manager.execute('HGETALL', self.stats_key)
        return {
            'total_items': int(stats.get('total_items', 0)),
            'processed_items': int(stats.get('processed_items', 0)),
            'current_length': await self.redis_manager.execute('LLEN', self.queue_key)
        }

    async def get_queue_status(self) -> Dict[str, Tuple[int, float]]:
        """Get queue lengths and oldest item timestamp for each priority."""
        async with self.transaction_manager.transaction() as tr:
            for queue in self.priority_queues.values():
                tr.llen(queue)
                tr.lindex(queue, 0)  # Get oldest item
            results = await tr.execute()
            
        status = {}
        for i, priority in enumerate(self.priority_queues.keys()):
            length = results[i * 2]
            oldest_item = json.loads(results[i * 2 + 1]) if results[i * 2 + 1] else None
            status[priority] = (length, oldest_item['added_at'] if oldest_item else 0)
        return status

    async def _update_stats(self, operation: str) -> None:
        pipe = self.redis_manager.redis.pipeline()
        pipe.hincrby(self.stats_key, 'total_items', 1 if operation == 'add' else 0)
        pipe.hincrby(self.stats_key, 'processed_items', 1 if operation == 'remove' else 0)
        await pipe.execute()

    async def _clean_expired_items(self) -> None:
        """Remove items that have been in the queue too long."""
        current_time = time.time()
        for priority_queue in self.priority_queues.values():
            async with self.transaction_manager.transaction() as tr:
                tr.lrange(priority_queue, 0, -1)
                items = await tr.execute()
                for item in items[0]:
                    data = json.loads(item)
                    if current_time - data['added_at'] > 3600:  # 1 hour timeout
                        tr.lrem(priority_queue, 0, item)
                await tr.execute()

    async def add(self, item: QueueItem) -> bool:
        async with self._lock:
            if len(self.queue) >= self.max_length:
                METRICS.increment('queue_rejections')
                return False
                
            # Insert with priority sorting
            insert_idx = 0
            for idx, queued in enumerate(self.queue):
                if item.priority > queued.priority:
                    break
                insert_idx = idx + 1
                
            self.queue.insert(insert_idx, item)
            METRICS.set_value('queue_length', len(self.queue))
            self._event.set()
            return True

    async def get(self) -> Optional[QueueItem]:
        async with self._lock:
            if not self.queue:
                self._event.clear()
                return None
            
            item = self.queue.pop(0)
            self.current_item = item
            METRICS.set_value('queue_length', len(self.queue))
            return item

    async def wait_for_item(self) -> QueueItem:
        await self._event.wait()
        return await self.get()

    async def clear(self) -> None:
        async with self._lock:
            self.queue.clear()
            self.current_item = None
            METRICS.set_value('queue_length', 0)