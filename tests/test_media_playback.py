import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from src.core.media_player import MediaPlayer
from src.core.ffmpeg_manager import FFmpegManager
from src.core.exceptions import StreamingError

@pytest.fixture
def mock_voice_channel():
    channel = AsyncMock()
    channel.bitrate = 64000
    return channel

@pytest.fixture
def media_player():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        ffmpeg = FFmpegManager()
        yield MediaPlayer(ffmpeg)

@pytest.mark.asyncio
async def test_play_media_success(media_player, mock_voice_channel):
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        process = AsyncMock()
        process.returncode = 0
        mock_exec.return_value = process

        await media_player.play("test.mp4", mock_voice_channel)
        assert media_player._current_process is not None

@pytest.mark.asyncio
async def test_play_media_failure(media_player, mock_voice_channel):
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        process = AsyncMock()
        process.returncode = 1
        mock_exec.return_value = process

        with pytest.raises(StreamingError):
            await media_player.play("test.mp4", mock_voice_channel)

@pytest.mark.asyncio
async def test_stop_playback(media_player, mock_voice_channel):
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        process = AsyncMock()
        process.returncode = 0
        mock_exec.return_value = process

        await media_player.play("test.mp4", mock_voice_channel)
        assert media_player._current_process is not None

        await media_player.stop()
        assert media_player._current_process is None
        process.terminate.assert_called_once()

@pytest.mark.asyncio
async def test_concurrent_playback(media_player, mock_voice_channel):
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        process1 = AsyncMock()
        process2 = AsyncMock()
        mock_exec.side_effect = [process1, process2]

        # Start first playback
        await media_player.play("test1.mp4", mock_voice_channel)
        assert media_player._current_process == process1

        # Start second playback (should stop first)
        await media_player.play("test2.mp4", mock_voice_channel)
        process1.terminate.assert_called_once()
        assert media_player._current_process == process2
