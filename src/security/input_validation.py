import re
from typing import Pattern, Optional
from pathlib import Path

class SecurityValidator:
    SAFE_PATH_PATTERN: Pattern = re.compile(r'^[a-zA-Z0-9\-_./]+$')
    MAX_PATH_LENGTH: int = 255
    
    @classmethod
    def validate_media_path(cls, path: str) -> bool:
        # Reject empty, too long, or path containing directory traversal references.
        if not path or len(path) > cls.MAX_PATH_LENGTH or ".." in path:
            return False
        return bool(cls.SAFE_PATH_PATTERN.fullmatch(path))

    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        return Path(filename).name

    @classmethod
    def is_safe_url(cls, url: str) -> bool:
        return url.startswith(('http://', 'https://'))
