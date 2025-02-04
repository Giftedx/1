import os
from enum import Enum
from typing import Dict, Optional
from pydantic import BaseSettings, AnyUrl, validator, Field

class QualityPreset(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class Environment(str, Enum):
    DEV = "development"
    STAGING = "staging"
    PROD = "production"

class Settings(BaseSettings):
    # Bot Configuration
    BOT_TOKEN: str
    STREAMING_BOT_TOKEN: str
    
    # Service URLs
    PLEX_URL: str
    PLEX_TOKEN: str
    REDIS_URL: str
    
    # Optional Vault Configuration
    VAULT_ADDR: Optional[str] = None
    VAULT_TOKEN: Optional[str] = None
    
    # Performance Settings
    REDIS_POOL_MIN_SIZE: int = 5
    REDIS_POOL_MAX_SIZE: int = 20
    REDIS_POOL_TIMEOUT: int = 30
    WORKER_PROCESSES: int = 2
    
    # Monitoring
    METRICS_PORT: int = 9090
    OTEL_TRACE_SAMPLING_RATE: float = 0.1
    
    # Service timeouts
    SERVICE_TIMEOUTS: Dict[str, float] = Field(
        default_factory=lambda: {
            'redis': 5.0,
            'discord': 10.0,
            'plex': 15.0
        }
    )
    
    # Retry configuration
    MAX_RETRIES: int = Field(default=3, ge=1, le=10)
    RETRY_BACKOFF_MIN: float = Field(default=1.0, ge=0.1)
    RETRY_BACKOFF_MAX: float = Field(default=30.0, ge=1.0)
    
    # Health check configuration
    HEALTH_CHECK_INTERVAL: int = Field(default=30, ge=10)
    HEALTH_CHECK_TIMEOUT: float = Field(default=5.0, ge=1.0)
    
    # Circuit breaker configuration
    CIRCUIT_BREAKER_THRESHOLD: int = Field(default=5, ge=1)
    CIRCUIT_BREAKER_RESET_TIME: int = Field(default=30, ge=5)

    @validator('SERVICE_TIMEOUTS')
    def validate_timeouts(cls, v):
        for service, timeout in v.items():
            if timeout <= 0:
                raise ValueError(f"Timeout for {service} must be positive")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

class Config(BaseSettings):
    BOT_TOKEN: str
    STREAMING_BOT_TOKEN: str
    METRICS_PORT: int = 9090
    MAX_QUEUE_LENGTH: int = 20
    VIRTUAL_CAM_DEVICE: str = '/dev/video0'
    VIDEO_WIDTH: int = 1280
    VIDEO_HEIGHT: int = 720
    FFMPEG_LOGLEVEL: str = 'warning'
    REDIS_URL: AnyUrl = 'redis://localhost:6379'
    PLEX_URL: AnyUrl
    PLEX_TOKEN: str
    CIRCUIT_BREAKER_THRESHOLD: int = 5
    CIRCUIT_BREAKER_TIMEOUT: int = 60
    HEALTH_CHECK_INTERVAL: int = 30
    DEFAULT_QUALITY: QualityPreset = QualityPreset.MEDIUM
    API_TIMEOUT: int = 30
    REDIS_POOL_SIZE: int = 20
    RATE_LIMIT_REQUESTS: int = 5
    RATE_LIMIT_PERIOD: int = 60
    LOG_LEVEL: str = 'INFO'
    MAX_CONCURRENT_STREAMS: int = 10  # Maximum number of concurrent streams allowed
    ENVIRONMENT: Environment = Environment.DEV
    SENTRY_DSN: Optional[str] = None
    PROMETHEUS_PUSHGATEWAY: Optional[str] = None
    GRACEFUL_SHUTDOWN_TIMEOUT: int = Field(default=30, ge=1, le=300)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @validator('REDIS_POOL_SIZE')
    def validate_pool_size(cls: type[BaseSettings], v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("Redis pool size must be between 1 and 100")
        return v

    @validator('ENVIRONMENT')
    def set_environment_configs(cls, v: Environment, values: Dict) -> Environment:
        if v == Environment.PROD:
            values['LOG_LEVEL'] = 'WARNING'
            values['HEALTH_CHECK_INTERVAL'] = 15
        return v