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

class Settings(BaseSettings):
    # Bot Configuration
    BOT_TOKEN: str
    STREAMING_BOT_TOKEN: str
    
    # Service URLs
    PLEX_URL: AnyUrl  # validated URL
    PLEX_TOKEN: str
    REDIS_URL: str
    
    # Optional Vault Configuration
    VAULT_ADDR: Optional[AnyUrl] = None
    VAULT_TOKEN: Optional[str] = None
    
    # Performance Settings
    REDIS_POOL_MIN_SIZE: int = 5
    REDIS_POOL_MAX_SIZE: int = 20
    REDIS_POOL_TIMEOUT: int = 30
    REDIS_POOL_SIZE: int = 30  # added for Redis connection pool setting
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

    # Additional Settings
    MAX_QUEUE_LENGTH: int = 100
    VIRTUAL_CAM_DEVICE: str = "/dev/video0"
    VIDEO_WIDTH: int = 1280
    VIDEO_HEIGHT: int = 720
    FFMPEG_LOGLEVEL: str = "error"
    RATE_LIMIT_REQUESTS: int = 5
    RATE_LIMIT_PERIOD: int = 60
    DEFAULT_QUALITY: QualityPreset = QualityPreset.MEDIUM
    CIRCUIT_BREAKER_TIMEOUT: int = 60
    ENV: Environment = Environment.DEVELOPMENT

    # New field for active stream limit
    MAX_CONCURRENT_STREAMS: int = 100

    @validator('SERVICE_TIMEOUTS')
    def validate_timeouts(cls, v):
        for service, timeout in v.items():
            if timeout <= 0:
                raise ValueError(f"Timeout for {service} must be positive")
        return v

    # New computed property to get a default alert service instance
    @property
    def alert_service(self):
        from src.monitoring.alerts import AlertService  # Import here to avoid circular dependencies
        # Using BOT_TOKEN as a placeholder for auth_token and a default URL and environment
        alert_config = {
            "alert_url": "https://alert.example.com",
            "auth_token": self.BOT_TOKEN,
            "environment": "production"
        }
        return AlertService(alert_config)

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()