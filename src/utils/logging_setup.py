import logging
import logging.handlers
import os
import socket
import time
from typing import Callable, Any
from functools import wraps

from pythonjsonlogger import jsonlogger

def setup_logging(log_level=logging.INFO):
    """
    Sets up logging for the application.
    """
    logger = logging.getLogger()
    logger.setLevel(log_level)

    log_format = jsonlogger.JsonFormatter(
        "%(asctime)s %(hostname)s %(name)s %(levelname)s %(message)s"
    )

    # Add hostname to log records
    hostname = socket.gethostname()
    logging.getLogger().handlers = []
    class HostnameFilter(logging.Filter):
        def filter(self, record):
            record.hostname = hostname
            return True

    # Create a rotating file handler
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, "app.log")
    rotating_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1024 * 1024, backupCount=5
    )
    rotating_handler.setFormatter(log_format)
    rotating_handler.addFilter(HostnameFilter())
    logger.addHandler(rotating_handler)

    # Create a stream handler for console output
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_format)
    stream_handler.addFilter(HostnameFilter())
    logger.addHandler(stream_handler)

def set_log_level(log_level):
    """
    Sets the log level for all handlers.
    """
    logger = logging.getLogger()
    logger.setLevel(log_level)
    for handler in logger.handlers:
        handler.setLevel(log_level)

def log_performance(logger: logging.Logger) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration = time.perf_counter() - start_time
                logger.info(f"{func.__name__} completed", extra={'duration': duration, 'function': func.__name__})
                return result
            except Exception as e:
                duration = time.perf_counter() - start_time
                logger.error(f"{func.__name__} failed", extra={'duration': duration, 'function': func.__name__, 'error': str(e)})
                raise
        return wrapper
    return decorator


# Example usage (you should call setup_logging in your main application)
# setup_logging(log_level=logging.DEBUG)
