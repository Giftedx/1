import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from src.core.media_player import MediaPlayer, StreamConfig
from src.core.exceptions import StreamingError

@pytest.fixture
def mock_ffmpeg():
    with patch('src.core.ffmpeg_manager.FFmpegManager') as mock:
        mock.create_stream_process = AsyncMock()
        yield mock

@pytest.fixture
def media_player(mock_ffmpeg):
    return MediaPlayer(mock_ffmpeg)

@pytest.fixture
def mock_voice_channel():
    channel = Mock()
    channel.bitrate = 64000
    return channel

@pytest.mark.asyncio
async def test_play_media_success(media_player, mock_voice_channel):
    """Test successful media playback."""
    process = AsyncMock()
    process.returncode = 0
    media_player.ffmpeg.create_stream_process.return_value = process
    
    await media_player.play("test.mp4", mock_voice_channel)
    assert media_player._current_process == process
    assert len(media_player._active_streams) == 1

@pytest.mark.asyncio
async def test_play_media_failure(media_player, mock_voice_channel):
    """Test media playback failure handling."""
    media_player.ffmpeg.create_stream_process.side_effect = Exception("FFmpeg error")
    
    with pytest.raises(StreamingError):
        await media_player.play("test.mp4", mock_voice_channel)
    
    assert media_player._current_process is None
    assert len(media_player._active_streams) == 0

@pytest.mark.asyncio
async def test_stop_playback(media_player, mock_voice_channel):
    """Test stopping playback."""
    process = AsyncMock()
    media_player.ffmpeg.create_stream_process.return_value = process
    
    await media_player.play("test.mp4", mock_voice_channel)
    await media_player.stop()
    
    process.terminate.assert_called_once()
    assert media_player._current_process is None
    assert len(media_player._active_streams) == 0

@pytest.mark.asyncio
async def test_stream_monitor_success(media_player, mock_voice_channel):
    """Test stream monitoring with successful completion."""
    process = AsyncMock()
    process.returncode = 0
    config = StreamConfig(max_retries=3)
    
    await media_player._monitor_stream("test.mp4", process, config)
    process.wait.assert_called_once()

@pytest.mark.asyncio
async def test_stream_monitor_retry(media_player, mock_voice_channel):
    """Test stream monitoring with retries."""
    process = AsyncMock()
    process.wait.side_effect = [
        asyncio.TimeoutError(),
        None  # Success on second try
    ]
    process.returncode = 0
    config = StreamConfig(max_retries=3, retry_delay=0.1)
    
    await media_player._monitor_stream("test.mp4", process, config)
    assert process.wait.call_count == 2

@pytest.mark.asyncio
async def test_concurrent_streams(media_player, mock_voice_channel):
    """Test handling multiple concurrent streams."""
    process1 = AsyncMock()
    process2 = AsyncMock()
    media_player.ffmpeg.create_stream_process.side_effect = [process1, process2]
    
    # Start two streams
    await media_player.play("test1.mp4", mock_voice_channel)
    await media_player.play("test2.mp4", mock_voice_channel)
    
    # First stream should be stopped
    process1.terminate.assert_called_once()
    assert media_player._current_process == process2

@pytest.mark.asyncio
async def test_stream_quality_config(media_player, mock_voice_channel):
    """Test stream quality configuration."""
    await media_player.play(
        "test.mp4",
        mock_voice_channel,
        config=StreamConfig(quality="high")
    )
    
    create_call = media_player.ffmpeg.create_stream_process.call_args[0]
    assert mock_voice_channel.bitrate in create_call
