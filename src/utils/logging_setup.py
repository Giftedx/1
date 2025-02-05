import logging
import logging.config
import platform
import time
from logging.handlers import RotatingFileHandler
from functools import wraps
from typing import Callable, Any
from pythonjsonlogger import jsonlogger

def setup_logging() -> None:
    """
    Configures JSON logging with hostname and rotates file logs.
    """
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        handlers=[
            logging.StreamHandler(),
            logging.handlers.RotatingFileHandler(
                'bot.log',
                maxBytes=10_000_000,
                backupCount=5
            )
        ]
    )

    class HostnameFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                record.hostname = platform.node()
            except Exception:
                record.hostname = "unknown"
            return True

    for handler in logging.getLogger().handlers:
        handler.addFilter(HostnameFilter())

def set_log_level(level: str) -> None:
    """
    Dynamically sets the log level.
    
    :param level: The log level to set (e.g., 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
    """
    logging.getLogger().setLevel(level)
    logger = logging.getLogger(__name__)
    logger.info(f"Log level set to {level}")

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
