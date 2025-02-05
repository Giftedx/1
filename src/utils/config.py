import os
from enum import Enum
from typing import Dict, Optional
from pydantic import BaseSettings, AnyUrl, validator, Field

class QualityPreset(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PROD = "production"
    PRODUCTION = "production"

class ServiceMode(str, Enum):
    BOT = "bot"
    SELFBOT = "selfbot"
    COMBINED = "combined"

class FFmpegPreset(str, Enum):
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"

class Settings(BaseSettings):
    # Service Configuration
    SERVICE_MODE: ServiceMode = ServiceMode.BOT
    LOG_LEVEL: str = "INFO"
    
    # Bot Configuration
    BOT_TOKEN: str
    STREAMING_BOT_TOKEN: Optional[str] = None
    VOICE_CHANNEL_ID: Optional[str] = None
    COMMAND_PREFIX: str = "!"
    
    # Media Configuration
    PLEX_URL: AnyUrl
    PLEX_TOKEN: str
    VIDEO_WIDTH: int = 1280
    VIDEO_HEIGHT: int = 720
    
    # FFmpeg Settings
    FFMPEG_THREAD_QUEUE_SIZE: int = 512
    FFMPEG_HWACCEL: str = "auto"
    FFMPEG_PRESET: FFmpegPreset = FFmpegPreset.VERYFAST
    
    # Redis Configuration
    REDIS_URL: str
    REDIS_POOL_MIN_SIZE: int = 5
    REDIS_POOL_MAX_SIZE: int = 20
    REDIS_POOL_TIMEOUT: int = 30
    
    # Performance Settings
    WORKER_PROCESSES: int = 2
    MAX_CONCURRENT_STREAMS: int = 100
    CIRCUIT_BREAKER_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RESET_TIME: int = 30
    
    # Monitoring Configuration
    ENABLE_METRICS: bool = True
    METRICS_PORT: int = 9090
    OTEL_TRACE_SAMPLING_RATE: float = 0.1

    @validator('FFMPEG_PRESET')
    def validate_ffmpeg_preset(cls, v):
        if v not in FFmpegPreset.__members__.values():
            raise ValueError(f"Invalid FFmpeg preset. Choose from: {list(FFmpegPreset.__members__.keys())}")
        return v

    @validator('SERVICE_MODE')
    def validate_service_mode(cls, v, values):
        if v == ServiceMode.SELFBOT and not values.get('STREAMING_BOT_TOKEN'):
            raise ValueError("STREAMING_BOT_TOKEN required for selfbot mode")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()