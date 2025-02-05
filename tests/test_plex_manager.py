import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from plexapi.video import Video
from plexapi.exceptions import Unauthorized, NotFound
from src.core.plex_manager import PlexManager
from src.core.exceptions import MediaNotFoundError, StreamingError

@pytest.fixture
def mock_plex_server():
    with patch('plexapi.server.PlexServer') as mock:
        server = mock.return_value
        server.friendlyName = "Test Plex Server"
        yield server

@pytest.fixture
def plex_manager(mock_plex_server):
    return PlexManager(url="http://fake-plex:32400", token="fake-token")

def create_mock_video():
    video = Mock(spec=Video)
    video.title = "Test Video"
    video.duration = 3600000  # 1 hour in milliseconds
    video.bitrate = 2000
    video.width = 1920
    video.height = 1080
    video.videoCodec = "h264"
    video.container = "mp4"
    return video

def test_connect_success(mock_plex_server):
    manager = PlexManager(url="http://fake-plex:32400", token="fake-token")
    assert manager.server is not None
    assert mock_plex_server.called

def test_connect_failure():
    with patch('plexapi.server.PlexServer', side_effect=Exception("Connection failed")):
        with pytest.raises(StreamingError):
            PlexManager(url="http://fake-plex:32400", token="fake-token")

def test_server_property_reconnect(mock_plex_server):
    manager = PlexManager(url="http://fake-plex:32400", token="fake-token")
    manager._server = None  # Simulate disconnected state
    assert manager.server is not None
    assert mock_plex_server.call_count == 2

def test_search_media_success(plex_manager, mock_plex_server):
    mock_video = create_mock_video()
    mock_plex_server.library.search.return_value = [mock_video]

    results = plex_manager.search_media("test query")
    assert len(results) == 1
    assert results[0].title == "Test Video"
    mock_plex_server.library.search.assert_called_once_with("test query")

def test_search_media_not_found(plex_manager, mock_plex_server):
    mock_plex_server.library.search.return_value = []

    with pytest.raises(MediaNotFoundError):
        plex_manager.search_media("nonexistent")

def test_get_stream_url_success(plex_manager):
    mock_video = create_mock_video()
    mock_video.getStreamURL.return_value = "http://stream-url"

    url = plex_manager.get_stream_url(mock_video)
    assert url == "http://stream-url"

def test_get_stream_url_failure(plex_manager):
    mock_video = create_mock_video()
    mock_video.getStreamURL.side_effect = Exception("Stream URL generation failed")

    with pytest.raises(StreamingError):
        plex_manager.get_stream_url(mock_video)

def test_video_info(plex_manager):
    mock_video = create_mock_video()
    info = plex_manager.get_video_info(mock_video)
    
    assert info == {
        "title": "Test Video",
        "duration": 3600000,
        "bitrate": 2000,
        "resolution": "1920x1080",
        "codec": "h264",
        "container": "mp4"
    }

def test_invalidate_cache(plex_manager):
    plex_manager.search_media.cache_clear = Mock()
    plex_manager.invalidate_cache()
    plex_manager.search_media.cache_clear.assert_called_once()

@pytest.mark.asyncio
async def test_search_media_network_retry(plex_manager, mock_plex_server):
    """Test that network errors trigger retries."""
    mock_video = create_mock_video()
    mock_plex_server.library.search.side_effect = [
        ConnectionError("Network error"),
        [mock_video]
    ]

    results = await plex_manager.search_media("test query")
    assert len(results) == 1
    assert mock_plex_server.library.search.call_count == 2

@pytest.mark.asyncio
async def test_search_media_unauthorized(plex_manager, mock_plex_server):
    """Test unauthorized access handling."""
    mock_plex_server.library.search.side_effect = Unauthorized("Invalid token")
    
    with pytest.raises(StreamingError) as exc_info:
        await plex_manager.search_media("test")
    assert "Invalid Plex credentials" in str(exc_info.value)

@pytest.mark.asyncio
async def test_connection_backoff(mock_plex_server):
    """Test exponential backoff on connection failures."""
    mock_plex_server.side_effect = [
        ConnectionError("Network error"),
        ConnectionError("Network error"),
        Mock()  # Success on third try
    ]
    
    manager = PlexManager(url="http://fake-plex:32400", token="fake-token")
    await asyncio.sleep(0.1)  # Allow for retry attempts
    
    assert mock_plex_server.call_count == 3
    assert manager._retry_delay > 1.0  # Verify backoff increased

@pytest.mark.asyncio
async def test_cache_invalidation(plex_manager, mock_plex_server):
    """Test cache invalidation behavior."""
    mock_video = create_mock_video()
    mock_plex_server.library.search.return_value = [mock_video]
    
    # First call should hit the server
    await plex_manager.search_media("test")
    
    # Second call should use cache
    await plex_manager.search_media("test")
    
    assert mock_plex_server.library.search.call_count == 1
    
    # Invalidate cache
    plex_manager.invalidate_cache()
    
    # Should hit server again
    await plex_manager.search_media("test")
    assert mock_plex_server.library.search.call_count == 2

@pytest.mark.asyncio
async def test_concurrent_searches(plex_manager, mock_plex_server):
    """Test concurrent search handling."""
    mock_video = create_mock_video()
    mock_plex_server.library.search.return_value = [mock_video]
    
    async def search():
        return await plex_manager.search_media("test")
    
    # Run multiple searches concurrently
    results = await asyncio.gather(*[search() for _ in range(5)])
    assert all(len(r) == 1 for r in results)
    
    # Should only hit server once due to caching
    assert mock_plex_server.library.search.call_count == 1

@pytest.mark.asyncio
async def test_graceful_shutdown(plex_manager):
    """Test graceful shutdown behavior."""
    await plex_manager.search_media("test")  # Establish connection
    await plex_manager.close()
    
    # Verify connection is closed
    assert plex_manager._server is None
    
    # Subsequent calls should reconnect
    mock_video = create_mock_video()
    with patch('plexapi.server.PlexServer') as mock_server:
        mock_server.return_value.library.search.return_value = [mock_video]
        results = await plex_manager.search_media("test")
        assert len(results) == 1
