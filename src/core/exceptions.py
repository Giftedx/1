from typing import Optional

class MediaBotError(Exception):
    """Base exception for all bot errors."""
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code or "GENERIC_ERROR"

class QueueError(MediaBotError):
    """Base class for queue-related errors."""
    pass

class QueueFullError(QueueError):
    """Raised when the media queue is full."""
    def __init__(self, message: str = "Queue is full"):
        super().__init__(message, "QUEUE_FULL")

class QueueEmptyError(QueueError):
    """Raised when attempting to access an empty queue."""
    def __init__(self, message: str = "Queue is empty"):
        super().__init__(message, "QUEUE_EMPTY")

class StreamingError(MediaBotError):
    """Raised for streaming-related errors."""
    pass

class CircuitBreakerOpenError(MediaBotError):
    """Raised when the circuit breaker is open."""
    pass

class InvalidCommandError(MediaBotError):
    """Raised when an invalid command is issued."""
    pass

class AuthenticationError(MediaBotError):
    """Raised when there is an authentication error."""
    pass

class PermissionDeniedError(MediaBotError):
    """Raised when permission is denied."""
    pass

class RateLimitExceededError(MediaBotError):
    """Raised when a rate limit is exceeded."""
    pass

class MediaNotFoundError(MediaBotError):
    """Raised when the requested media is not found."""
    pass

class ResourceExhaustedError(MediaBotError):
    """Raised when system resources are exhausted."""
    def __init__(self, resource: str):
        super().__init__(f"{resource} resources exhausted", "RESOURCE_EXHAUSTED")