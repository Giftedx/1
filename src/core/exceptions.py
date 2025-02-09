from typing import Optional

class MediaBotError(Exception):
    """Base exception for all bot errors."""
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code or "GENERIC_ERROR"

class QueueError(MediaBotError):
    """Base class for queue-related errors."""
    pass

class QueueFullError(Exception):
    pass

class QueueEmptyError(QueueError):
    """Raised when attempting to access an empty queue."""
    def __init__(self, message: str = "Queue is empty"):
        super().__init__(message, "QUEUE_EMPTY")

class StreamingError(MediaBotError):
    """Raised for streaming-related errors."""
    pass

class CircuitBreakerError(Exception):
    """Base class for circuit breaker exceptions."""
    pass

class CircuitBreakerOpenError(CircuitBreakerError):
    """Raised when the circuit breaker is open."""
    pass

class CircuitBreakerHalfOpenError(CircuitBreakerError):
    """Raised when the circuit breaker is half-open."""
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

class RateLimitExceededError(Exception):
    pass

class MediaNotFoundError(Exception):
    pass

class ResourceExhaustedError(MediaBotError):
    """Raised when system resources are exhausted."""
    def __init__(self, resource: str):
        super().__init__(f"{resource} resources exhausted", "RESOURCE_EXHAUSTED")