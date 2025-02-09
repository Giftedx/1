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
from datetime import datetime, timedelta
from src.metrics import METRICS
from enum import Enum

logger = logging.getLogger(__name__)

class QueuePriority(Enum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3

@dataclass
class QueueItem:
    media_id: str
    requester_id: str
    timestamp: datetime
    priority: QueuePriority = QueuePriority.MEDIUM  # Use the Enum, default to medium

class QueueManager:
    """
    Manages the media queue using an in-memory queue.
    """
    def __init__(self, max_length: int, redis_manager: RedisManager) -> None:
        self.max_length = max_length
        self.redis_manager = redis_manager  # You might not need this if not using Redis
        self.queue_key = "media_queue"  # You might not need this if not using Redis
        self.stats_key = "queue_stats"  # You might not need this if not using Redis
        self.priority_queues = {
            QueuePriority.HIGH: f"{self.queue_key}:high",
            QueuePriority.MEDIUM: f"{self.queue_key}:medium",
            QueuePriority.LOW: f"{self.queue_key}:low"
        } # You might not need this if not using Redis
        self.transaction_manager = RedisTransaction(redis_manager) # You might not need this if not using Redis
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
            priorities=[QueuePriority.HIGH, QueuePriority.MEDIUM, QueuePriority.LOW]
        )
        self._batch_size = 10
        self._flush_interval = 1.0
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
        high_count = len([item for item in self.queue if item.priority == QueuePriority.HIGH])
        medium_count = len([item for item in self.queue if item.priority == QueuePriority.MEDIUM])
        low_count = len([item for item in self.queue if item.priority == QueuePriority.LOW])

        self._queue_size.labels(priority=QueuePriority.HIGH.name).set(high_count)
        self._queue_size.labels(priority=QueuePriority.MEDIUM.name).set(medium_count)
        self._queue_size.labels(priority=QueuePriority.LOW.name).set(low_count)

    async def _clean_expired_items(self) -> None:
        now = datetime.now()
        expired_items = [item for item in self.queue if (now - item.timestamp) > timedelta(hours=1)]
        async with self._lock:
            for item in expired_items:
                self.queue.remove(item)
                self._dropped_items.inc()

    @track_latency("queue_add")
    async def add(self, item: QueueItem) -> bool:  # Changed to QueueItem
        async with self._lock:
            if len(self.queue) >= self.max_length:
                METRICS.increment('queue_rejections')
                return False

            # Insert with priority sorting
            insert_idx = 0
            for idx, queued in enumerate(self.queue):
                if item.priority.value > queued.priority.value:  # Compare enum values
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