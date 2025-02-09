class MediaController {
  constructor() {
    this.seekBar = document.getElementById('seekBar');
    this.currentTime = document.getElementById('currentTime');
    this.totalTime = document.getElementById('totalTime');
    this.playPauseButton = document.getElementById('playPause');
    this.currentlyPlaying = null; // Add this line
    this.volumeSlider = document.getElementById('volume');
    this.muteButton = document.getElementById('mute');
    this.isMuted = false;

    this.setupEventListeners();
  }

  setupEventListeners() {
    this.seekBar.addEventListener('input', () => {
      if (this.currentlyPlaying) {
        const time = (this.seekBar.value * this.currentlyPlaying.duration) / 100;
        this.currentTime.textContent = this.formatTime(time);
      }
    });

    this.seekBar.addEventListener('change', async () => {
      await this.seek(this.seekBar.value);
    });

    document.getElementById('playPause').addEventListener('click', async () => {
      if (this.currentlyPlaying) {
        await this.controlMedia('toggle_play', this.currentlyPlaying.id);
      }
    });

    this.volumeSlider.addEventListener('input', () => {
      this.setVolume(this.volumeSlider.value);
    });

    this.muteButton.addEventListener('click', () => {
      this.toggleMute();
    });
  }

  async seek(percent) {
    if (this.currentlyPlaying) {
      await this.controlMedia('seek', this.currentlyPlaying.id, {
        position: percent,
      });
    }
  }

  formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h ? h + ':' : ''}${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  async controlMedia(action, streamId, data = {}) {
    const response = await fetch('/api/media/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, streamId, ...data }),
    });
    return response.json();
  }

  async setVolume(volume) {
    if (this.currentlyPlaying) {
      await this.controlMedia('volume', this.currentlyPlaying.id, {
        volume: volume,
      });
    }
  }

  async toggleMute() {
    this.isMuted = !this.isMuted;
    if (this.currentlyPlaying) {
      await this.controlMedia('mute', this.currentlyPlaying.id, {
        mute: this.isMuted,
      });
      this.muteButton.innerHTML = this.isMuted ? '<i class="bi bi-volume-mute-fill"></i>' : '<i class="bi bi-volume-up-fill"></i>';
    }
  }

  updateMediaInfo(stream) {
    this.currentlyPlaying = stream;
    document.getElementById('currentTime').textContent = this.formatTime(
      (stream.progress * stream.duration) / 100,
    );
    document.getElementById('totalTime').textContent = this.formatTime(stream.duration);
    document.getElementById('seekBar').value = stream.progress;
    document.getElementById('playPause').innerHTML =
      stream.state === 'playing' ? '<i class="bi bi-pause-fill"></i>' : '<i class="bi bi-play-fill"></i>';
  }
}

const mediaController = new MediaController();
