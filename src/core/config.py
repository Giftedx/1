from enum import Enum
from typing import Optional

from pydantic import BaseSettings, validator


class Environment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class ServiceMode(str, Enum):
    STREAMING = "streaming"
    SELFBOT = "selfbot"


class QualityPreset(str, Enum):
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"


class FFmpegPreset(str, Enum):
    LIBX264 = "libx264"
    LIBX265 = "libx265"
    COPY = "copy"


class Settings(BaseSettings):
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    SERVICE_MODE: ServiceMode = ServiceMode.STREAMING
    BOT_PREFIX: str = "!"
    DISCORD_BOT_TOKEN: str
    STREAMING_BOT_TOKEN: Optional[str] = None
    APPLICATION_ID: str
    GUILD_ID: int
    FFMPEG_PRESET: FFmpegPreset = FFmpegPreset.LIBX264
    QUALITY_PRESET: QualityPreset = QualityPreset.ULTRAFAST
    CIRCUIT_BREAKER_TIMEOUT: int = 30
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    class Config:
        case_sensitive = True

    @validator("STREAMING_BOT_TOKEN")
    def validate_streaming_bot_token(cls, v, values):
        if values.get("SERVICE_MODE") == ServiceMode.SELFBOT and not v:
            raise ValueError(
                "STREAMING_BOT_TOKEN is required when SERVICE_MODE is set to selfbot"
            )
        return v
