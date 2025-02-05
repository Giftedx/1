import pytest
import asyncio
from unittest.mock import Mock
from src.core.ffmpeg_manager import FFmpegManager
from src.core.plex_manager import PlexManager
from src.utils.config import settings

@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_settings():
    """Mock application settings."""
    settings_mock = Mock()
    settings_mock.FFMPEG_THREAD_QUEUE_SIZE = 512
    settings_mock.FFMPEG_HWACCEL = "auto"
    settings_mock.FFMPEG_PRESET = "veryfast"
    settings_mock.VIDEO_WIDTH = 1280
    settings_mock.VIDEO_HEIGHT = 720
    settings_mock.MAX_CONCURRENT_STREAMS = 3
    return settings_mock

@pytest.fixture
def mock_process():
    """Create a mock async process."""
    process = Mock()
    process.returncode = 0
    process.wait = asyncio.Future
    process.terminate = Mock()
    return process

@pytest.fixture
def async_return(event_loop):
    """Helper to convert synchronous return values to async."""
    def _async_return(result):
        f = asyncio.Future(loop=event_loop)
        f.set_result(result)
        return f
    return _async_return
