from typing import Optional, Dict, Any
from pydantic import AnyUrl, validator
from pydantic import model_validator
from src.core.config import ServiceMode, FFmpegPreset
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Service Configuration
    SERVICE_MODE: ServiceMode = ServiceMode.STREAMING
    # type: ignore
    LOG_LEVEL: str = "INFO"
    # type: ignore

    # Bot Configuration
    BOT_TOKEN: str
    # type: ignore
    STREAMING_BOT_TOKEN: Optional[str] = None
    # Corrected
    VOICE_CHANNEL_ID: Optional[str] = None
    COMMAND_PREFIX: str = "!"
    # type: ignore

    # Media Configuration
    PLEX_URL: AnyUrl
    # type: ignore
    PLEX_TOKEN: str
    # type: ignore
    VIDEO_WIDTH: int = 1280
    VIDEO_HEIGHT: int = 720

    # FFmpeg Settings
    FFMPEG_THREAD_QUEUE_SIZE: int = 512
    FFMPEG_HWACCEL: str = "auto"
    FFMPEG_PRESET: FFmpegPreset = FFmpegPreset.LIBX264
    # type: ignore

    # Redis Configuration
    REDIS_URL: str
    # type: ignore
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_POOL_MIN_SIZE: int = 5
    REDIS_POOL_MAX_SIZE: int = 20
    REDIS_POOL_TIMEOUT: int = 30

    # Performance Settings
    WORKER_PROCESSES: int = 2
    MAX_CONCURRENT_STREAMS: int = 100
    CIRCUIT_BREAKER_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RESET_TIME: int = 30

    # Monitoring Configuration
    # Fixed indentation
    ENABLE_METRICS: bool = True
    METRICS_PORT: int = 9090
    OTEL_TRACE_SAMPLING_RATE: float = 0.1
    CIRCUIT_BREAKER_TIMEOUT: int = 30

    # Added blank line
    @validator('FFMPEG_PRESET')
    # Added type annotation
    # Added type annotation
    def validate_ffmpeg_preset(cls, v: str) -> str:
        # Added type annotation
        if v not in FFmpegPreset.__members__.values():
            raise ValueError(f"Invalid FFmpeg preset. Choose from: {list(FFmpegPreset.__members__.keys())}")
        return v

    @model_validator(mode='before')  # Added indentation
    # Corrected
    # Added type annotation
    # Added type annotation
    def validate_selfbot_token(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        # Added indentation
        # Added indentation
        # Added indentation
        service_mode = values.get('SERVICE_MODE')
        streaming_bot_token = values.get('STREAMING_BOT_TOKEN')

        if service_mode == ServiceMode.SELFBOT and not streaming_bot_token:
            raise ValueError("STREAMING_BOT_TOKEN must be set when SERVICE_MODE is selfbot")
        elif service_mode != ServiceMode.SELFBOT and streaming_bot_token:
            print("Warning: STREAMING_BOT_TOKEN is set but SERVICE_MODE is not selfbot. This token will be ignored.")
        return values

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()