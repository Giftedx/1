from dataclasses import dataclass
from typing import Dict, Any
import aiohttp

@dataclass
class MediaControls:
    seekbar: bool = True
    volume: bool = True
    quality: bool = True
    subtitles: bool = True
    audio_tracks: bool = True
    playback_speed: bool = True

class MediaPlayerWidget:
    template = """
    <div class="media-player-widget">
        <div class="video-container">
            <div id="player-{id}" class="player-wrapper"></div>
            <div class="overlay-controls">
                <div class="playback-info">
                    <span class="title"></span>
                    <span class="quality-badge"></span>
                </div>
            </div>
        </div>
        <div class="advanced-controls">
            <div class="audio-tracks"></div>
            <div class="subtitle-tracks"></div>
            <div class="quality-options"></div>
            <div class="playback-speed">
                <input type="range" min="0.5" max="2" step="0.25" value="1">
                <span class="speed-value">1x</span>
            </div>
        </div>
        <div class="stream-stats">
            <div class="bandwidth"></div>
            <div class="buffer-health"></div>
            <div class="dropped-frames"></div>
        </div>
    </div>
    """

    def __init__(self, session_id: str, controls: MediaControls = None):
        self.session_id = session_id
        self.controls = controls or MediaControls()
        
    async def get_stream_status(self) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"/api/stream/{self.session_id}/status") as resp:
                return await resp.json()

    async def update_stream_quality(self, quality: str):
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"/api/stream/{self.session_id}/quality",
                json={"quality": quality}
            )

    @staticmethod
    def get_javascript() -> str:
        return """
        class MediaPlayer {
            constructor(containerId, stream) {
                this.container = document.getElementById(containerId);
                this.stream = stream;
                this.initializePlayer();
            }

            initializePlayer() {
                // Initialize video.js or other player library
                this.player = videojs(this.container);
                this.setupControls();
                this.startStreamMetrics();
            }

            setupControls() {
                // Add custom control handlers
            }

            startStreamMetrics() {
                setInterval(() => {
                    this.updateMetrics();
                }, 1000);
            }

            updateMetrics() {
                const stats = this.player.getStats();
                // Update UI with stats
            }
        }
        """
