#!/usr/bin/env python3
"""
shutdown.py – Handles graceful shutdown.
"""
import asyncio
import signal
import logging
import weakref
from typing import Set, Dict, Callable, Awaitable, Optional, List, NamedTuple, Any, DefaultDict, TypeVar, Protocol, Type, ClassVar, Tuple, cast
from collections import defaultdict
from contextlib import suppress, asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from prometheus_client import Counter, Gauge, Histogram, Summary
from datetime import datetime, timedelta
import time
from types import TracebackType

logger = logging.getLogger(__name__)

class ShutdownPriority(Enum):
    HIGH = 0
    MEDIUM = 1
    LOW = 2

class TaskPriority(Enum):
    CRITICAL = auto()
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()

class TrackedTask(NamedTuple):
    task: asyncio.Task
    priority: TaskPriority
    name: str

class ShutdownPhase(Enum):
    """Phases of the shutdown process for better control."""
    INITIALIZE = auto()
    STOP_ACCEPTING = auto()
    DRAIN_REQUESTS = auto()
    CANCEL_TASKS = auto()
    CLEANUP_RESOURCES = auto()
    FINALIZE = auto()

class ResourceLifecycle(Protocol):
    """Protocol for resources that need lifecycle management."""
    async def acquire(self) -> None: ...
    async def release(self) -> None: ...
    async def cleanup(self) -> None: ...

class DeadlockState(Enum):
    """States for deadlock detection."""
    NONE = auto()
    POTENTIAL = auto()
    DETECTED = auto()

@dataclass
class ResourceLock:
    """Track resource locking for deadlock detection."""
    resource: str
    acquired_by: Optional[str] = None
    waiting_tasks: Set[str] = field(default_factory=set)
    acquired_time: Optional[datetime] = None

class DeadlockDetector:
    """Detect and resolve deadlocks during shutdown."""
    def __init__(self):
        self._resource_locks: Dict[str, ResourceLock] = {}
        self._task_dependencies: Dict[str, Set[str]] = defaultdict(set)
        self._state = DeadlockState.NONE
        self._last_check = datetime.now()
        self._check_interval = 1.0

    def add_resource(self, resource: str) -> None:
        if resource not in self._resource_locks:
            self._resource_locks[resource] = ResourceLock(resource=resource)

    async def check_deadlocks(self) -> bool:
        """Check for deadlocks in resource dependencies."""
        if (datetime.now() - self._last_check).total_seconds() < self._check_interval:
            return False

        self._last_check = datetime.now()
        visited = set()
        path = []

        def has_cycle(task: str) -> bool:
            if task in path:
                self._state = DeadlockState.DETECTED
                return True
            if task in visited:
                return False

            visited.add(task)
            path.append(task)

            for dep in self._task_dependencies[task]:
                if has_cycle(dep):
                    return True

            path.pop()
            return False

        for task in self._task_dependencies:
            if has_cycle(task):
                return True

        self._state = DeadlockState.NONE
        return False

@dataclass
class CleanupHandler:
    name: str
    handler: Callable[[], Awaitable[None]]
    priority: ShutdownPriority = ShutdownPriority.MEDIUM
    timeout: float = 10.0

@dataclass
class ResourceUsage:
    allocated: int = 0
    freed: int = 0
    pending: int = 0
    errors: int = 0

@dataclass
class ShutdownMetrics:
    duration: Histogram = field(default_factory=lambda: Histogram(
        'shutdown_duration_seconds',
        'Time taken for shutdown process',
        ['phase']
    ))
    errors: Counter = field(default_factory=lambda: Counter(
        'shutdown_errors_total',
        'Number of errors during shutdown',
        ['type', 'severity']
    ))
    active_tasks: Gauge = field(default_factory=lambda: Gauge(
        'shutdown_active_tasks',
        'Number of active tasks',
        ['priority', 'status']
    ))
    task_duration: Summary = field(default_factory=lambda: Summary(
        'shutdown_task_duration_seconds',
        'Duration of task cleanup',
        ['priority']
    ))
    task_batches: Histogram = field(default_factory=lambda: Histogram(
        'shutdown_task_batch_size',
        'Size of task cancellation batches',
        ['priority']
    ))
    recovery_attempts: Counter = field(default_factory=lambda: Counter(
        'shutdown_recovery_attempts_total',
        'Number of recovery attempts during shutdown',
        ['type']
    ))
    task_queue_time: Histogram = field(default_factory=lambda: Histogram(
        'shutdown_task_queue_time_seconds',
        'Time tasks spent in cancellation queue',
        ['priority']
    ))
    resource_usage: Dict[str, ResourceUsage] = field(
        default_factory=lambda: defaultdict(ResourceUsage)
    )
    cleanup_success_rate: Gauge = field(default_factory=lambda: Gauge(
        'shutdown_cleanup_success_rate',
        'Success rate of cleanup operations',
        ['type']
    ))
    resource_cleanup_time: Histogram = field(default_factory=lambda: Histogram(
        'shutdown_resource_cleanup_seconds',
        'Time taken to cleanup resources',
        ['resource_type']
    ))

@dataclass
class HealthStatus:
    healthy: bool
    message: str
    last_check: datetime
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ShutdownContext:
    """Context for tracking shutdown progress."""
    phase: ShutdownPhase
    start_time: datetime
    deadlines: Dict[ShutdownPhase, datetime]
    errors: List[Exception] = field(default_factory=list)
    completed_phases: Set[ShutdownPhase] = field(default_factory=set)

class ResourceState(Enum):
    """Resource lifecycle states."""
    AVAILABLE = auto()
    IN_USE = auto()
    CLEANING = auto()
    FAILED = auto()
    CLEANED = auto()

class ResourceStateMachine:
    """Manages resource state transitions with validation."""
    VALID_TRANSITIONS = {
        ResourceState.AVAILABLE: {ResourceState.IN_USE, ResourceState.CLEANING},
        ResourceState.IN_USE: {ResourceState.AVAILABLE, ResourceState.CLEANING},
        ResourceState.CLEANING: {ResourceState.CLEANED, ResourceState.FAILED},
        ResourceState.FAILED: {ResourceState.CLEANING},
        ResourceState.CLEANED: set()
    }

    def __init__(self):
        self._states: Dict[str, ResourceState] = {}
        self._transitions = Counter(
            'resource_state_transitions_total',
            'Number of resource state transitions',
            ['resource', 'from_state', 'to_state']
        )
        self._state_durations = Histogram(
            'resource_state_duration_seconds',
            'Time spent in each state',
            ['resource', 'state']
        )
        self._last_transition_time: Dict[str, float] = {}

    def validate_transition(self, resource: str, new_state: ResourceState) -> bool:
        """Validate if state transition is allowed."""
        current = self._states.get(resource, ResourceState.AVAILABLE)
        return new_state in self.VALID_TRANSITIONS[current]

    async def transition(self, resource: str, new_state: ResourceState) -> None:
        """Perform state transition with validation and metrics."""
        current = self._states.get(resource, ResourceState.AVAILABLE)
        
        if not self.validate_transition(resource, new_state):
            raise ValueError(
                f"Invalid transition for {resource}: {current.name} -> {new_state.name}"
            )

        now = time.monotonic()
        if resource in self._last_transition_time:
            duration = now - self._last_transition_time[resource]
            self._state_durations.labels(
                resource=resource,
                state=current.name
            ).observe(duration)

        self._states[resource] = new_state
        self._last_transition_time[resource] = now
        self._transitions.labels(
            resource=resource,
            from_state=current.name,
            to_state=new_state.name
        ).inc()

class ResourceMonitor:
    """Monitors resource usage and cleanup progress."""
    def __init__(self):
        self._resource_usage = Gauge(
            'resource_usage',
            'Current resource usage metrics',
            ['resource', 'metric']
        )
        self._cleanup_progress = Gauge(
            'cleanup_progress_percent',
            'Cleanup progress as percentage',
            ['resource']
        )
        self._resource_errors = Counter(
            'resource_errors_total',
            'Number of resource-related errors',
            ['resource', 'error_type']
        )
        self._last_error_time = Summary(
            'last_error_timestamp',
            'Timestamp of last error',
            ['resource']
        )

    async def update_usage(self, resource: str, metrics: Dict[str, float]) -> None:
        """Update resource usage metrics."""
        for metric, value in metrics.items():
            self._resource_usage.labels(
                resource=resource,
                metric=metric
            ).set(value)

    async def update_progress(self, resource: str, progress: float) -> None:
        """Update cleanup progress."""
        self._cleanup_progress.labels(resource=resource).set(progress)

    async def record_error(self, resource: str, error_type: str) -> None:
        """Record resource error with timing."""
        self._resource_errors.labels(
            resource=resource,
            error_type=error_type
        ).inc()
        self._last_error_time.labels(resource=resource).observe(time.time())

class ShutdownCoordinator:
    """Coordinates shutdown across multiple resources."""
    def __init__(self):
        self._resource_states: Dict[str, ResourceState] = {}
        self._cleanup_semaphore = asyncio.Semaphore(5)  # Limit concurrent cleanups
        self._state_changes = Counter(
            'shutdown_resource_state_changes',
            'Number of resource state transitions',
            ['from_state', 'to_state']
        )
        self._cleanup_durations = Histogram(
            'shutdown_cleanup_duration_seconds',
            'Time taken for resource cleanup',
            ['resource', 'status']
        )

    async def change_resource_state(
        self, 
        resource: str, 
        new_state: ResourceState,
        old_state: Optional[ResourceState] = None
    ) -> None:
        """Track resource state changes with metrics."""
        current = self._resource_states.get(resource)
        if old_state is not None and current != old_state:
            raise ValueError(f"Resource {resource} in unexpected state {current}")
        
        self._resource_states[resource] = new_state
        if current:
            self._state_changes.labels(
                from_state=current.name,
                to_state=new_state.name
            ).inc()

class TimeoutManager:
    """Manages timeouts with exponential backoff."""
    def __init__(self, base_timeout: float = 1.0, max_timeout: float = 30.0):
        self._base = base_timeout
        self._max = max_timeout
        self._timeouts: Dict[str, float] = {}

    def get_timeout(self, key: str, attempt: int = 0) -> float:
        """Get timeout with exponential backoff."""
        if attempt == 0:
            return self._base
        
        timeout = min(self._base * (2 ** attempt), self._max)
        self._timeouts[key] = timeout
        return timeout

    @asynccontextmanager
    async def timeout(self, duration: float):
        """Context manager for timeout with metrics."""
        start = time.monotonic()
        try:
            async with asyncio.timeout(duration):
                yield
        finally:
            elapsed = time.monotonic() - start
            if elapsed >= duration:
                logger.warning(f"Operation took {elapsed:.2f}s (timeout: {duration:.2f}s)")

class TaskGraph:
    """Manages task dependencies and ordering."""
    def __init__(self):
        self._dependencies: Dict[str, Set[str]] = defaultdict(set)
        self._reverse_deps: Dict[str, Set[str]] = defaultdict(set)
        self._weights: Dict[str, int] = {}

    def add_dependency(self, task: str, depends_on: str, weight: int = 1) -> None:
        """Add task dependency with weight."""
        self._dependencies[task].add(depends_on)
        self._reverse_deps[depends_on].add(task)
        self._weights[(task, depends_on)] = weight

    def get_cleanup_order(self) -> List[str]:
        """Get optimal cleanup order considering weights."""
        visited = set()
        order = []

        def visit(task: str, path: Set[str]) -> None:
            if task in path:
                cycle = " -> ".join(list(path) + [task])
                raise ValueError(f"Circular dependency detected: {cycle}")
            if task in visited:
                return

            path.add(task)
            # Sort dependencies by weight
            deps = sorted(
                self._dependencies[task],
                key=lambda d: self._weights.get((task, d), 1),
                reverse=True
            )
            for dep in deps:
                visit(dep, path)
            path.remove(task)
            visited.add(task)
            order.append(task)

        tasks = set(self._dependencies.keys()) | set(self._reverse_deps.keys())
        for task in sorted(tasks):  # Ensure deterministic ordering
            if task not in visited:
                visit(task, set())

        return order

class DeadlockError(Exception):
    """Raised when a deadlock is detected."""
    pass

class ResourceAcquisitionError(Exception):
    """Raised when resource acquisition fails."""
    pass

class ResourceContextManager:
    """Context manager for resource acquisition."""
    def __init__(self, lock: asyncio.Lock):
        self._lock = lock

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException]],
        traceback: Optional[TracebackType],
    ) -> None:
        self._lock.release()

class ShutdownStatus(Enum):
    """Detailed shutdown status tracking."""
    NOT_STARTED = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    FAILED = auto()
    TIMED_OUT = auto()

class ResourcePriority(Enum):
    """Resource cleanup priorities."""
    CRITICAL = 0  # Must be cleaned up first (e.g., database connections)
    HIGH = 1      # Should be cleaned up early (e.g., file handles)
    MEDIUM = 2    # Standard cleanup priority
    LOW = 3       # Can be cleaned up last

@dataclass
class MetricsConfig:
    """Configuration for metrics collection."""
    enabled: bool = True
    detailed_tracing: bool = False
    sample_rate: float = 1.0
    histogram_buckets: ClassVar[Tuple[float, ...]] = (
        .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0
    )

class EnhancedResourceLock(ResourceLock):
    """Enhanced resource locking with deadlock prevention."""
    def __init__(self, resource: str):
        super().__init__(resource)
        self.lock_time: Optional[float] = None
        self.lock_count: int = 0
        self.max_wait_time: float = 5.0
        self.last_holder: Optional[str] = None
        self.contention_count: int = 0

    async def acquire(self, holder: str) -> bool:
        """Acquire lock with timeout and contention tracking."""
        try:
            async with asyncio.timeout(self.max_wait_time):
                if self.acquired_by:
                    self.contention_count += 1
                self.acquired_by = holder
                self.lock_time = time.monotonic()
                self.lock_count += 1
                return True
        except asyncio.TimeoutError:
            return False

    def release(self) -> None:
        """Release lock and update metrics."""
        if self.lock_time:
            duration = time.monotonic() - self.lock_time
            self.last_holder = self.acquired_by
        self.acquired_by = None
        self.lock_time = None

class ShutdownMonitor:
    """Monitors shutdown progress and performance."""
    def __init__(self):
        self._durations = Histogram(
            'shutdown_operation_duration_seconds',
            'Duration of shutdown operations',
            ['operation', 'status'],
            buckets=[.01, .05, .1, .5, 1, 5, 10, 30, 60]
        )
        self._counts = Counter(
            'shutdown_operation_total',
            'Count of shutdown operations',
            ['operation', 'result']
        )
        self._resources = Gauge(
            'shutdown_resources_current',
            'Current resource states',
            ['resource', 'state']
        )
        self._last_operation = Summary(
            'shutdown_last_operation_timestamp',
            'Timestamp of last operation',
            ['operation']
        )

    async def record_operation(self, operation: str, duration: float, status: str) -> None:
        """Record operation metrics."""
        self._durations.labels(operation=operation, status=status).observe(duration)
        self._counts.labels(operation=operation, result=status).inc()
        self._last_operation.labels(operation=operation).observe(time.time())

    async def update_resource_state(self, resource: str, state: str, count: int) -> None:
        """Update resource state metrics."""
        self._resources.labels(resource=resource, state=state).set(count)

class ShutdownStats:
    """Collects detailed shutdown statistics."""
    def __init__(self):
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.operations: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.resource_states: Dict[str, str] = {}
        self.performance_metrics: Dict[str, float] = {}
        self.cleanup_durations: Dict[str, float] = {}

    def add_operation(self, name: str, duration: float, result: str) -> None:
        self.operations.append({
            "name": name,
            "duration": duration,
            "result": result,
            "timestamp": datetime.now().isoformat()
        })

    def add_error(self, error: Exception, context: Dict[str, Any]) -> None:
        self.errors.append({
            "type": type(error).__name__,
            "message": str(error),
            "context": context,
            "timestamp": datetime.now().isoformat()
        })

@dataclass 
class ShutdownConfig:
    """Configuration for shutdown behavior."""
    max_concurrent_cleanups: int = 5
    default_timeout: float = 30.0
    max_retries: int = 3
    batch_size: int = 10
    histogram_buckets: ClassVar[Tuple[float, ...]] = (
        .005, .01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0, 10.0, 30.0
    )
    phase_timeouts: Dict[str, float] = field(default_factory=lambda: {
        "initialize": 2.0,
        "stop_accepting": 3.0,
        "drain_requests": 10.0,
        "cancel_tasks": 10.0,
        "cleanup_resources": 10.0,
        "finalize": 5.0
    })

class ShutdownError(Exception):
    """Base exception for shutdown errors."""
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.context = context or {}
        self.timestamp = datetime.now()

class ResourceCleanupError(ShutdownError):
    """Raised when resource cleanup fails."""
    pass

class DeadlockTimeoutError(ShutdownError):
    """Raised when deadlock detection times out."""
    pass 

class GracefulShutdown:
    def __init__(self, config: Optional[ShutdownConfig] = None):
        self._config = config or ShutdownConfig()
        self.shutdown_event = asyncio.Event()
        self._tasks: Set[TrackedTask] = set()
        self._cleanup_handlers: Dict[str, CleanupHandler] = {}
        self._shutdown_timeout = self._config.default_timeout
        self._metrics = ShutdownMetrics()
        self._shutdown_in_progress = False
        self._task_timeouts: Dict[TaskPriority, float] = {
            TaskPriority.CRITICAL: 30.0,
            TaskPriority.HIGH: 20.0,
            TaskPriority.MEDIUM: 10.0,
            TaskPriority.LOW: 5.0
        }
        self._health_checks: Dict[str, Callable[[], Awaitable[HealthStatus]]] = {}
        self._last_health_status: Optional[HealthStatus] = None
        self._shutdown_start: Optional[datetime] = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=60.0,
            name="shutdown"
        )
        self._task_stats: Dict[str, Dict[str, float]] = {}
        self._batch_size = self._config.batch_size
        self._task_queues: DefaultDict[TaskPriority, List[TrackedTask]] = defaultdict(list)
        self._recovery_handlers: Dict[str, Callable[[], Awaitable[None]]] = {}
        self._performance_stats: Dict[str, List[float]] = defaultdict(list)
        self._resource_tracking: DefaultDict[str, ResourceUsage] = defaultdict(ResourceUsage)
        self._cleanup_order: List[str] = []
        self._dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self._max_retry_attempts = self._config.max_retries
        self._retry_delay = 1.0
        self._phase_timeouts = {
            ShutdownPhase.INITIALIZE: self._config.phase_timeouts["initialize"],
            ShutdownPhase.STOP_ACCEPTING: self._config.phase_timeouts["stop_accepting"],
            ShutdownPhase.DRAIN_REQUESTS: self._config.phase_timeouts["drain_requests"],
            ShutdownPhase.CANCEL_TASKS: self._config.phase_timeouts["cancel_tasks"],
            ShutdownPhase.CLEANUP_RESOURCES: self._config.phase_timeouts["cleanup_resources"],
            ShutdownPhase.FINALIZE: self._config.phase_timeouts["finalize"]
        }
        self._resource_pools: Dict[str, weakref.WeakSet] = defaultdict(weakref.WeakSet)
        self._phase_handlers: Dict[ShutdownPhase, List[Callable]] = defaultdict(list)
        self._deadlock_detector = DeadlockDetector()
        self._context: Optional[ShutdownContext] = None
        self._resource_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._task_graph = TaskGraph()
        self._timeout_manager = TimeoutManager()
        self._coordinator = ShutdownCoordinator()
        self._cleanup_rate_limiter = asyncio.Semaphore(3)  # Limit concurrent cleanups
        self._state_machine = ResourceStateMachine()
        self._resource_monitor = ResourceMonitor()
        self._cleanup_progress: Dict[str, float] = {}
        self._error_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._resource_timeouts: Dict[str, float] = defaultdict(lambda: 30.0)
        self._metrics_config = MetricsConfig()
        self._shutdown_status = ShutdownStatus.NOT_STARTED
        self._resource_priorities: Dict[str, ResourcePriority] = {}
        self._enhanced_locks: Dict[str, EnhancedResourceLock] = {}
        self._monitor = ShutdownMonitor()
        self._stats = ShutdownStats()
        self._operation_timeouts: Dict[str, float] = {
            "resource_cleanup": 30.0,
            "task_cancellation": 20.0,
            "state_transition": 5.0,
            "health_check": 3.0
        }
        
        # Add new optimized resource tracking
        self._resource_refs = weakref.WeakValueDictionary()
        self._resource_usage_times = defaultdict(list)
        
        # Add adaptive timeout management
        self._timeout_history: DefaultDict[str, List[float]] = defaultdict(list)
        self._adaptive_timeouts = AdaptiveTimeoutManager(
            min_timeout=0.1,
            max_timeout=self._config.default_timeout,
            history_size=10
        )

    async def register_cleanup(
        self, 
        name: str, 
        handler: Callable[[], Awaitable[None]], 
        priority: ShutdownPriority = ShutdownPriority.MEDIUM,
        timeout: float = 10.0
    ) -> None:
        self._cleanup_handlers[name] = CleanupHandler(
            name=name,
            handler=handler,
            priority=priority,
            timeout=timeout
        )

    async def register_health_check(
        self,
        name: str,
        check: Callable[[], Awaitable[HealthStatus]]
    ) -> None:
        self._health_checks[name] = check

    async def register_recovery_handler(
        self,
        name: str,
        handler: Callable[[], Awaitable[None]]
    ) -> None:
        """Register handlers for recovery from failed shutdown operations."""
        self._recovery_handlers[name] = handler

    async def register_resource_dependency(
        self, 
        resource: str, 
        depends_on: List[str]
    ) -> None:
        """Register resource cleanup dependencies."""
        self._dependency_graph[resource].update(depends_on)
        self._update_cleanup_order()

    async def register_phase_handler(
        self, 
        phase: ShutdownPhase, 
        handler: Callable[[], Awaitable[None]]
    ) -> None:
        """Register a handler for a specific shutdown phase."""
        self._phase_handlers[phase].append(handler)

    def _update_cleanup_order(self) -> None:
        """Update cleanup order based on dependencies."""
        visited = set()
        temp = set()
        order = []

        def visit(resource: str) -> None:
            if resource in temp:
                raise ValueError(f"Circular dependency detected for {resource}")
            if resource in visited:
                return
            
            temp.add(resource)
            for dep in self._dependency_graph[resource]:
                visit(dep)
            temp.remove(resource)
            visited.add(resource)
            order.append(resource)

        for resource in self._dependency_graph:
            if resource not in visited:
                visit(resource)

        self._cleanup_order = order

    async def get_health_status(self) -> HealthStatus:
        """Run health checks and return aggregated status."""
        results = []
        details = {}

        for name, check in self._health_checks.items():
            try:
                status = await check()
                results.append(status.healthy)
                details[name] = {
                    "healthy": status.healthy,
                    "message": status.message,
                    "last_check": status.last_check.isoformat()
                }
            except Exception as e:
                logger.error(f"Health check {name} failed: {e}")
                results.append(False)
                details[name] = {"error": str(e)}

        healthy = all(results) if results else True
        message = "All systems operational" if healthy else "Some systems are degraded"
        
        self._last_health_status = HealthStatus(
            healthy=healthy,
            message=message,
            last_check=datetime.now(),
            details=details
        )
        return self._last_health_status

    @asynccontextmanager
    async def register_task(self, 
                          task: asyncio.Task, 
                          priority: TaskPriority = TaskPriority.MEDIUM,
                          name: Optional[str] = None) -> None:
        tracked = TrackedTask(
            task=task,
            priority=priority,
            name=name or task.get_name()
        )
        self._tasks.add(tracked)
        self._metrics.active_tasks.labels(priority=priority.name).inc()
        try:
            yield
        finally:
            self._tasks.remove(tracked)
            self._metrics.active_tasks.labels(priority=priority.name).dec()

    def _get_ordered_handlers(self) -> List[CleanupHandler]:
        return sorted(
            self._cleanup_handlers.values(),
            key=lambda h: h.priority.value
        )

    async def _run_phase(self, phase: ShutdownPhase, context: ShutdownContext) -> None:
        """Run all handlers for a specific phase with timeout."""
        logger.info(f"Entering shutdown phase: {phase.name}")
        timeout = self._phase_timeouts[phase]
        
        try:
            async with asyncio.timeout(timeout):
                handlers = self._phase_handlers[phase]
                await asyncio.gather(*(h() for h in handlers))
                context.completed_phases.add(phase)
        except asyncio.TimeoutError:
            logger.error(f"Phase {phase.name} timed out after {timeout}s")
            self._metrics.errors.labels(
                type='phase_timeout',
                severity='high'
            ).inc()
        except Exception as e:
            logger.error(f"Error in phase {phase.name}: {e}")
            context.errors.append(e)
            self._metrics.errors.labels(
                type='phase_error',
                severity='critical'
            ).inc()

    async def shutdown(self, signal_name: str) -> None:
        if self._shutdown_in_progress:
            logger.warning("Shutdown already in progress")
            return

        self._shutdown_in_progress = True
        self._shutdown_start = datetime.now()
        context = ShutdownContext(
            phase=ShutdownPhase.INITIALIZE,
            start_time=self._shutdown_start,
            deadlines={
                phase: self._shutdown_start + timedelta(seconds=timeout)
                for phase, timeout in self._phase_timeouts.items()
            }
        )
        self._context = context

        logger.info(f"Initiating shutdown due to {signal_name}")
        self.shutdown_event.set()

        try:
            for phase in ShutdownPhase:
                context.phase = phase
                await self._run_phase(phase, context)
                
                if phase == ShutdownPhase.CANCEL_TASKS:
                    await self._cancel_tasks_by_priority()
                elif phase == ShutdownPhase.CLEANUP_RESOURCES:
                    await self._run_cleanup_handlers()

        except Exception as e:
            logger.error(f"Critical error during shutdown: {e}", exc_info=True)
            self._metrics.errors.labels(
                type='shutdown_error',
                severity='critical'
            ).inc()
        finally:
            await self._finalize_shutdown(context)

    async def _finalize_shutdown(self, context: ShutdownContext) -> None:
        """Perform final cleanup and logging."""
        duration = (datetime.now() - context.start_time).total_seconds()
        
        # Log shutdown summary
        logger.info(
            "Shutdown completed",
            extra={
                "duration": duration,
                "completed_phases": [p.name for p in context.completed_phases],
                "error_count": len(context.errors),
                "resource_stats": self.get_resource_stats()
            }
        )

        # Update final metrics
        if context.errors:
            self._metrics.errors.labels(
                type='total_errors',
                severity='info'
            ).inc(len(context.errors))

    def _log_remaining_tasks(self) -> None:
        active_tasks = [t.task for t in self._tasks if not t.task.done()]
        if active_tasks:
            logger.warning(f"Tasks remaining: {len(active_tasks)}")
            for task in active_tasks:
                logger.warning(f"Remaining task: {task.get_name()}")

    async def _cancel_tasks_by_priority(self) -> None:
        start_time = datetime.now()
        
        for priority in TaskPriority:
            tasks = [t for t in self._tasks if t.priority == priority]
            self._metrics.task_batches.labels(priority=priority.name).observe(len(tasks))
            
            # Process tasks in batches
            for i in range(0, len(tasks), self._batch_size):
                batch = tasks[i:i + self._batch_size]
                try:
                    async with asyncio.timeout(self._task_timeouts[priority]):
                        results = await asyncio.gather(
                            *[self._cancel_single_task(t) for t in batch],
                            return_exceptions=True
                        )
                        await self._handle_batch_results(results, priority)
                except Exception as e:
                    await self._handle_batch_error(e, priority)

        self._task_stats["total_duration"] = (
            datetime.now() - start_time
        ).total_seconds()

    async def _handle_batch_results(
        self,
        results: List[Any],
        priority: TaskPriority
    ) -> None:
        """Handle results from a batch of task cancellations."""
        failures = [r for r in results if isinstance(r, Exception)]
        if failures:
            logger.error(f"Batch had {len(failures)} failures for {priority.name}")
            self._metrics.errors.labels(
                type='batch_failure',
                severity='medium'
            ).inc(len(failures))
            
            # Attempt recovery if handlers exist
            for handler in self._recovery_handlers.values():
                try:
                    await handler()
                    self._metrics.recovery_attempts.labels(
                        type='success'
                    ).inc()
                except Exception as e:
                    logger.error(f"Recovery handler failed: {e}")
                    self._metrics.recovery_attempts.labels(
                        type='failure'
                    ).inc()

    async def _handle_batch_error(self, error: Exception, priority: TaskPriority) -> None:
        """Handle errors during batch processing."""
        logger.error(f"Batch processing failed for {priority.name}: {error}")
        self._metrics.errors.labels(
            type='batch_processing',
            severity='high'
        ).inc()
        
        # Record performance impact
        self._performance_stats[f"batch_errors_{priority.name}"].append(
            asyncio.get_event_loop().time()
        )

    async def _cancel_priority_group(self, priority: TaskPriority) -> None:
        tasks = [t for t in self._tasks if t.priority == priority]
        if not tasks:
            return

        logger.info(f"Cancelling {len(tasks)} {priority.name} priority tasks")
        
        try:
            async with asyncio.timeout(self._task_timeouts[priority]):
                await asyncio.gather(
                    *[self._cancel_single_task(t) for t in tasks],
                    return_exceptions=True
                )
        except asyncio.TimeoutError:
            msg = f"Timeout cancelling {priority.name} tasks"
            logger.error(msg)
            self._metrics.errors.labels(
                type='timeout',
                severity='critical'
            ).inc()
            raise RuntimeError(msg)

    async def _cancel_single_task(self, tracked: TrackedTask) -> None:
        if tracked.task.done():
            return

        task_start = datetime.now()
        tracked.task.cancel()
        
        try:
            await tracked.task
        except asyncio.CancelledError:
            logger.debug(f"Task {tracked.name} cancelled successfully")
        except Exception as e:
            logger.error(f"Error cancelling task {tracked.name}: {e}")
            self._metrics.errors.labels(
                type='task_error',
                severity='medium'
            ).inc()
        finally:
            duration = (datetime.now() - task_start).total_seconds()
            self._task_stats[tracked.name] = {"duration": duration}

    async def _acquire_resource(self, resource: str, task_name: str) -> ResourceContextManager:
        """Enhanced resource acquisition with better deadlock prevention."""
        lock = self._enhanced_locks.get(resource) or self._enhanced_locks.setdefault(
            resource, 
            EnhancedResourceLock(resource)
        )
        
        try:
            acquired = await lock.acquire(task_name)
            if not acquired:
                raise ResourceAcquisitionError(
                    f"Failed to acquire {resource} after {lock.max_wait_time}s"
                )
            
            self._deadlock_detector.add_resource(resource)
            if await self._deadlock_detector.check_deadlocks():
                lock.release()
                raise DeadlockError(f"Deadlock detected for {task_name} on {resource}")
                
            return ResourceContextManager(lock)
            
        except Exception as e:
            if lock.acquired_by == task_name:
                lock.release()
            raise ResourceAcquisitionError(f"Error acquiring {resource}: {e}")

    async def _run_cleanup_handlers(self) -> None:
        """Enhanced cleanup with adaptive concurrency."""
        ordered_resources = self._task_graph.get_cleanup_order()
        total_resources = len(ordered_resources)
        completed = 0

        # Group by priority and dependencies
        groups = self._group_resources_for_cleanup(ordered_resources)
        
        # Track cleanup timing for adaptive timeouts
        timings: DefaultDict[str, List[float]] = defaultdict(list)

        for group in groups:
            # Determine optimal concurrency based on resource types
            concurrency = self._calculate_optimal_concurrency(group)
            
            async with asyncio.Semaphore(concurrency) as sem:
                tasks = []
                for resource in group:
                    if handler := self._cleanup_handlers.get(resource):
                        tasks.append(
                            self._cleanup_single_resource_with_semaphore(
                                sem, resource, handler, completed, total_resources
                            )
                        )

                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Update timing statistics
                for resource, result in zip(group, results):
                    if isinstance(result, Exception):
                        continue
                    duration = cast(float, result)
                    timings[resource].append(duration)
                
                completed += sum(1 for r in results if not isinstance(r, Exception))

        # Update adaptive timeouts based on timing data
        self._update_timeout_statistics(timings)

    def _group_resources_for_cleanup(self, resources: List[str]) -> List[List[str]]:
        """Group resources for optimal parallel cleanup."""
        # Group by dependencies and resource type
        groups: List[List[str]] = []
        current_group: List[str] = []
        
        for resource in resources:
            if self._can_cleanup_concurrently(resource, current_group):
                current_group.append(resource)
            else:
                if current_group:
                    groups.append(current_group)
                current_group = [resource]
                
        if current_group:
            groups.append(current_group)
            
        return groups

    def _calculate_optimal_concurrency(self, resources: List[str]) -> int:
        """Calculate optimal concurrency based on resource types and system load."""
        base_concurrency = min(len(resources), self._config.max_concurrent_cleanups)
        
        # Adjust based on resource type
        resource_weights = {
            "database": 0.5,  # Database connections need more care
            "network": 0.7,   # Network resources can be more parallel
            "file": 0.8,     # File handles can be quite parallel
            "memory": 1.0    # Memory resources can be most parallel
        }
        
        # Get minimum weight for resource group
        min_weight = min(
            resource_weights.get(self._get_resource_type(r), 1.0)
            for r in resources
        )
        
        return max(1, int(base_concurrency * min_weight))

    async def _cleanup_single_resource_with_semaphore(
        self,
        sem: asyncio.Semaphore,
        resource: str,
        handler: CleanupHandler,
        completed: int,
        total: int
    ) -> float:
        """Cleanup single resource with semaphore and timing."""
        async with sem:
            start_time = time.monotonic()
            try:
                await self._cleanup_single_resource(
                    resource, handler, completed, total
                )
                return time.monotonic() - start_time
            except Exception as e:
                self._stats.add_error(e, {
                    "resource": resource,
                    "phase": "cleanup",
                    "duration": time.monotonic() - start_time
                })
                raise

    def _get_resource_type(self, resource: str) -> str:
        """Determine resource type for optimization."""
        if resource.startswith(("db_", "sql_", "redis_")):
            return "database"
        if resource.startswith(("http_", "api_", "net_")):
            return "network"
        if resource.startswith(("file_", "fs_")):
            return "file"
        return "memory"

    def _update_timeout_statistics(self, timings: Dict[str, List[float]]) -> None:
        """Update adaptive timeouts based on cleanup timing data."""
        for resource, durations in timings.items():
            if not durations:
                continue
            
            # Calculate statistics
            avg_duration = sum(durations) / len(durations)
            max_duration = max(durations)
            
            # Update adaptive timeout manager
            self._adaptive_timeouts.update_timeout(
                resource,
                avg_duration,
                max_duration
            )

    async def _run_single_cleanup(
        self, 
        resource: str, 
        handler: CleanupHandler
    ) -> None:
        """Run a single cleanup handler with enhanced error recovery."""
        for attempt in range(self._max_retry_attempts):
            try:
                async with self._timeout_manager.timeout(handler.timeout):
                    start_time = time.monotonic()
                    await handler.handler()
                    duration = time.monotonic() - start_time
                    
                    self._metrics.resource_cleanup_time.labels(
                        resource_type=resource
                    ).observe(duration)
                    
                    self._resource_tracking[resource].freed += 1
                    await self._update_cleanup_metrics(resource, True)
                    break
                    
            except Exception as e:
                await self._handle_cleanup_error(resource, e, attempt)
                if attempt == self._max_retry_attempts - 1:
                    await self._handle_cleanup_failure(resource, e)

    async def _handle_cleanup_error(
        self,
        resource: str,
        error: Exception,
        attempt: int = 0
    ) -> None:
        """Enhanced error handling with monitoring."""
        error_type = type(error).__name__
        await self._resource_monitor.record_error(resource, error_type)
        
        logger.error(
            f"Cleanup error for {resource} (attempt {attempt + 1}): {error}",
            exc_info=error
        )

        for handler in self._error_handlers[resource]:
            try:
                await handler(error)
            except Exception as e:
                logger.error(f"Error handler failed for {resource}: {e}")

    def is_shutting_down(self) -> bool:
        return self.shutdown_event.is_set()

    async def wait_for_shutdown(self) -> None:
        await self.shutdown_event.wait()

    def get_metrics(self) -> Dict[str, float]:
        """Return current shutdown metrics for monitoring."""
        return {
            'active_tasks': sum(self._metrics.active_tasks.collect()[0].samples),
            'errors': sum(self._metrics.errors.collect()[0].samples),
            'last_shutdown_duration': self._metrics.duration.collect()[0].samples[-1].value
            if self._metrics.duration.collect()[0].samples else 0
        }

    def get_shutdown_stats(self) -> Dict[str, Any]:
        """Return detailed shutdown statistics."""
        return {
            "metrics": self.get_metrics(),
            "task_stats": self._task_stats,
            "health_status": self._last_health_status,
            "shutdown_duration": (
                datetime.now() - self._shutdown_start
            ).total_seconds() if self._shutdown_start else None
        }

    def get_resource_stats(self) -> Dict[str, Dict[str, int]]:
        """Get detailed resource cleanup statistics."""
        return {
            resource: {
                'allocated': usage.allocated,
                'freed': usage.freed,
                'pending': usage.pending,
                'errors': usage.errors
            }
            for resource, usage in self._resource_tracking.items()
        }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get enhanced performance metrics."""
        stats = self.get_shutdown_stats()
        stats.update({
            "resources": self.get_resource_stats(),
            "cleanup_order": self._cleanup_order,
            "dependencies": {
                resource: list(deps)
                for resource, deps in self._dependency_graph.items()
            }
        })
        return stats

    def get_shutdown_progress(self) -> Dict[str, Any]:
        """Enhanced progress reporting."""
        if not self._context:
            return {"status": "not_started"}

        progress = {
            "current_phase": self._context.phase.name,
            "start_time": self._context.start_time.isoformat(),
            "completed_phases": [p.name for p in self._context.completed_phases],
            "error_count": len(self._context.errors),
            "deadlines": {
                p.name: d.isoformat()
                for p, d in self._context.deadlines.items()
            },
            "resource_stats": self.get_resource_stats(),
            "metrics": self.get_metrics(),
            "deadlock_state": self._deadlock_detector._state.name,
            "resource_locks": {
                name: {
                    "acquired_by": lock.acquired_by,
                    "waiting_tasks": list(lock.waiting_tasks),
                    "acquired_time": lock.acquired_time.isoformat() if lock.acquired_time else None
                }
                for name, lock in self._deadlock_detector._resource_locks.items()
            },
            "resource_states": {
                name: state.name
                for name, state in self._state_machine._states.items()
            },
            "cleanup_progress": self._cleanup_progress,
            "resource_errors": {
                name: list(self._resource_monitor._resource_errors.collect())
                for name in self._cleanup_handlers
            }
        }
        
        return progress

    def get_resource_metrics(self) -> Dict[str, Any]:
        """Get detailed resource metrics."""
        metrics = {}
        for name, lock in self._enhanced_locks.items():
            metrics[name] = {
                "contention_count": lock.contention_count,
                "lock_count": lock.lock_count,
                "current_holder": lock.acquired_by,
                "last_holder": lock.last_holder,
                "locked_duration": (
                    time.monotonic() - lock.lock_time
                    if lock.lock_time else 0
                )
            }
        return metrics

    def export_shutdown_stats(self) -> Dict[str, Any]:
        """Export detailed shutdown statistics."""
        return {
            "duration": {
                "start": self._stats.start_time.isoformat() if self._stats.start_time else None,
                "end": self._stats.end_time.isoformat() if self._stats.end_time else None,
                "total_seconds": (self._stats.end_time - self._stats.start_time).total_seconds()
                if self._stats.start_time and self._stats.end_time else None
            },
            "operations": self._stats.operations,
            "errors": self._stats.errors,
            "resources": {
                "states": self._stats.resource_states,
                "cleanup_durations": self._stats.cleanup_durations
            },
            "performance": self._stats.performance_metrics,
            "phases": {
                phase.name: {
                    "completed": phase in (self._context.completed_phases if self._context else set()),
                    "duration": self._stats.cleanup_durations.get(phase.name)
                }
                for phase in ShutdownPhase
            }
        }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop = asyncio.get_event_loop()
    shutdown_handler = GracefulShutdown()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda sig=sig: asyncio.create_task(shutdown_handler.shutdown(sig.name)))
    try:
        loop.run_forever()
    finally:
        loop.close()
