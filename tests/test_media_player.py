import pytest
import asyncio
from unittest.mock import Mock, patch
from src.core.media_player import MediaPlayer
from src.core.ffmpeg_manager import FFmpegManager

@pytest.fixture
async def media_player():
    ffmpeg_manager = Mock(spec=FFmpegManager)
    return MediaPlayer(ffmpeg_manager)

@pytest.mark.asyncio
async def test_play_media(media_player):
    mock_voice_channel = Mock()
    mock_voice_channel.bitrate = 64000
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = Mock()
        mock_exec.return_value = mock_process
        
        await media_player.play("http://test/stream", mock_voice_channel)
        assert media_player._current_process is not None
        assert media_player._stream_task is not None

@pytest.mark.asyncio
async def test_stop_media(media_player):
    mock_process = Mock()
    media_player._current_process = mock_process
    
    await media_player.stop()
    assert media_player._current_process is None
    mock_process.terminate.assert_called_once()

@pytest.mark.asyncio
async def test_error_handling(media_player):
    mock_voice_channel = Mock()
    mock_voice_channel.bitrate = 64000
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_exec.side_effect = Exception("Test error")
        
        with pytest.raises(Exception):
            await media_player.play("http://test/stream", mock_voice_channel)
