import pytest
import asyncio
from unittest.mock import patch, Mock, AsyncMock
from src.core.ffmpeg_manager import FFmpegManager, FFmpegConfig
from src.core.exceptions import StreamingError

@pytest.fixture
def ffmpeg_manager():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        yield FFmpegManager()

@pytest.fixture
def mock_process():
    process = AsyncMock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"", b""))
    process.wait = AsyncMock()
    return process

def test_find_ffmpeg_success():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        manager = FFmpegManager()
        assert manager.ffmpeg_path is not None

def test_find_ffmpeg_failure():
    with patch('subprocess.run', side_effect=FileNotFoundError):
        with pytest.raises(StreamingError):
            FFmpegManager()

def test_verify_ffmpeg_success(ffmpeg_manager):
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        ffmpeg_manager._verify_ffmpeg()

def test_verify_ffmpeg_failure(ffmpeg_manager):
    with patch('subprocess.run', side_effect=subprocess.SubprocessError):
        with pytest.raises(StreamingError):
            ffmpeg_manager._verify_ffmpeg()

def test_get_stream_options(ffmpeg_manager):
    options = ffmpeg_manager.get_stream_options(
        width=1280,
        height=720,
        preset="veryfast",
        hwaccel="auto"
    )
    
    assert isinstance(options, dict)
    assert "before_options" in options
    assert "options" in options
    assert "-vf scale=1280:720" in options["options"]
    assert "-preset veryfast" in options["options"]

def test_transcode_media_success(ffmpeg_manager):
    with patch('subprocess.Popen') as mock_popen:
        process = mock_popen.return_value
        process.communicate.return_value = ("", "")
        process.returncode = 0

        ffmpeg_manager.transcode_media("input.mp4", "output.mp4")
        mock_popen.assert_called_once()

def test_transcode_media_failure(ffmpeg_manager):
    with patch('subprocess.Popen') as mock_popen:
        process = mock_popen.return_value
        process.communicate.return_value = ("", "FFmpeg error")
        process.returncode = 1

        with pytest.raises(StreamingError):
            ffmpeg_manager.transcode_media("input.mp4", "output.mp4")

@pytest.mark.asyncio
async def test_stream_media_success(ffmpeg_manager, mock_process):
    with patch('asyncio.create_subprocess_exec', return_value=mock_process):
        async with ffmpeg_manager.stream_session("test.mp4", "medium") as process:
            assert process == mock_process
            assert "test.mp4" in ffmpeg_manager._active_processes

@pytest.mark.asyncio
async def test_stream_media_failure(ffmpeg_manager, mock_process):
    mock_process.returncode = 1
    mock_process.communicate.return_value = (b"", b"FFmpeg error")

    with patch('asyncio.create_subprocess_exec', return_value=mock_process):
        with pytest.raises(StreamingError):
            async with ffmpeg_manager.stream_session("test.mp4", "medium"):
                pass

@pytest.mark.asyncio
async def test_cleanup(ffmpeg_manager, mock_process):
    with patch('asyncio.create_subprocess_exec', return_value=mock_process):
        async with ffmpeg_manager.stream_session("test.mp4", "medium"):
            pass
        
        await ffmpeg_manager.cleanup()
        assert len(ffmpeg_manager._active_processes) == 0
        mock_process.terminate.assert_called_once()

@pytest.mark.asyncio
async def test_concurrent_streams(ffmpeg_manager):
    # Test handling multiple concurrent streams
    mock_processes = [AsyncMock() for _ in range(3)]
    for proc in mock_processes:
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")

    with patch('asyncio.create_subprocess_exec', side_effect=mock_processes):
        tasks = []
        for i in range(3):
            tasks.append(ffmpeg_manager.stream_session(f"test{i}.mp4", "medium"))
            
        async with asyncio.TaskGroup() as tg:
            for task in tasks:
                tg.create_task(task.__aenter__())

        assert len(ffmpeg_manager._active_processes) == 3

@pytest.mark.asyncio
async def test_resource_monitoring(ffmpeg_manager):
    with patch('psutil.Process') as mock_process:
        mock_process.return_value.cpu_percent.return_value = 50.0
        mock_process.return_value.memory_info.return_value.rss = 1024 * 1024 * 100
        
        stats = await ffmpeg_manager._collect_process_stats()
        assert isinstance(stats, dict)
        assert "cpu_total" in stats
        assert "memory_total" in stats
        assert "process_count" in stats

def test_adaptive_bitrate(ffmpeg_manager):
    low = ffmpeg_manager._get_adaptive_bitrate("low")
    medium = ffmpeg_manager._get_adaptive_bitrate("medium")
    high = ffmpeg_manager._get_adaptive_bitrate("high")
    
    assert low == "1500k"
    assert medium == "3000k"
    assert high == "5000k"
