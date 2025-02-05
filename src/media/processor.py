import ffmpeg
import logging
from typing import Dict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from src.utils.config import settings

logger = logging.getLogger(__name__)

class MediaProcessor:
    def __init__(self):
        self.thread_pool = ThreadPoolExecutor(
            max_workers=settings.MEDIA_WORKER_THREADS,
            thread_name_prefix="media_worker"
        )
        self.cache_dir = Path("/var/cache/media")
        self.cache_dir.mkdir(exist_ok=True)

    async def process_stream(self, input_url: str, quality: str = "720p") -> Dict:
        try:
            stream = ffmpeg.input(input_url)
            stream = self._apply_filters(stream, quality)
            
            output_path = self.cache_dir / f"{hash(input_url)}.mp4"
            stream = ffmpeg.output(
                stream,
                str(output_path),
                acodec='aac',
                vcodec='h264',
                preset=settings.FFMPEG_PRESET,
                **self._get_codec_options()
            )

            await self.thread_pool.submit(
                ffmpeg.run,
                stream,
                capture_stdout=True,
                capture_stderr=True
            )

            return {
                "path": str(output_path),
                "quality": quality,
                "success": True
            }

        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error: {e.stderr.decode()}")
            return {"success": False, "error": str(e)}

    def _apply_filters(self, stream, quality: str):
        filters = {
            "720p": ["-vf", "scale=-2:720"],
            "1080p": ["-vf", "scale=-2:1080"],
            "adaptive": ["-vf", "scale=w=trunc(oh*a/2)*2:h=720"]
        }
        return ffmpeg.filter(stream, *filters.get(quality, filters["adaptive"]))

    def _get_codec_options(self) -> Dict:
        return {
            "threads": settings.FFMPEG_THREADS,
            "hwaccel": settings.FFMPEG_HWACCEL,
            "movflags": "+faststart",
            "bf": 2,
            "g": 30,
            "crf": 23
        }
