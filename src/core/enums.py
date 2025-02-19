from enum import Enum


class QualityPreset(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PROD = "production"
    PRODUCTION = "production"


class ServiceMode(str, Enum):
    BOT = "bot"
    SELFBOT = "selfbot"
    COMBINED = "combined"
    STREAMING = "streaming"


class FFmpegPreset(str, Enum):
    LIBX264 = "libx264"
    LIBX265 = "libx265"
    COPY = "copy"
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"

    FAST = "fast"
    MEDIUM = "medium"