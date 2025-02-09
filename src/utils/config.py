import os
from enum import Enum
from typing import Dict, Optional
from pydantic import BaseSettings, AnyUrl, validator, Field, root_validator

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

    @root_validator
    def validate_selfbot_token(cls, values):
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