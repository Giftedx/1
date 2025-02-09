from typing import Optional

class MediaBotError(Exception):
    """Base exception for all bot errors."""
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)

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
    """Raised when there is an error during media streaming."""
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message, code)

class CircuitBreakerError(Exception):
    pass

class CircuitBreakerOpenError(CircuitBreakerError):
    pass

class CircuitBreakerHalfOpenError(CircuitBreakerError):
    pass

class InvalidCommandError(MediaBotError):
    pass

class AuthenticationError(MediaBotError):
    pass

class PermissionDeniedError(MediaBotError):
    pass

class RateLimitExceededError(Exception):
    pass

class MediaNotFoundError(Exception):
    pass

class ResourceExhaustedError(MediaBotError):
    pass