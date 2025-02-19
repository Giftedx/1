import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import pytest
import asyncio
from unittest.mock import patch, Mock
from src.core.ffmpeg_manager import FFmpegManager, FFmpegConfig
from src.core.plex_manager import PlexManager  # Keep this import for conftest.py
from src.core.exceptions import StreamingError

@pytest.fixture
def ffmpeg_manager():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        yield FFmpegManager()

@pytest.fixture
def mock_process():
    process = Mock()
    process.returncode = 0
    process.communicate = Mock(return_value=(b"", b""))
    process.wait = Mock()
    return process
