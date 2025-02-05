from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import json
import asyncio
from datetime import datetime

@dataclass
class SettingConflict:
    type: str
    affected_settings: List[str]
    message: str
    severity: str
    resolution_options: List[Dict[str, Any]]

@dataclass
class SettingPreset:
    id: str
    name: str
    description: str
    settings: Dict[str, Any]
    tags: List[str]
    created: datetime
    last_modified: datetime

class SettingsManager:
    def __init__(self):
        self.conflict_patterns = [
            {
                'pattern': lambda s: s.get('ffmpeg_preset') == 'ultrafast' and s.get('quality') == 'highest',
                'message': 'High quality with ultrafast preset may impact performance',
                'affected': ['ffmpeg_preset', 'quality'],
                'severity': 'warning',
                'resolutions': [
                    {'value': {'ffmpeg_preset': 'veryfast'}, 'label': 'Lower preset speed'},
                    {'value': {'quality': 'high'}, 'label': 'Lower quality'}
                ]
            }
        ]

    async def detect_conflicts(self, settings: Dict[str, Any]) -> List[SettingConflict]:
        conflicts = []
        for pattern in self.conflict_patterns:
            if pattern['pattern'](settings):
                conflicts.append(SettingConflict(
                    type='performance',
                    affected_settings=pattern['affected'],
                    message=pattern['message'],
                    severity=pattern['severity'],
                    resolution_options=pattern['resolutions']
                ))
        return conflicts

    async def validate_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        errors = []
        for key, value in settings.items():
            try:
                await self._validate_setting(key, value)
            except ValueError as e:
                errors.append(str(e))
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }

    async def create_backup(self) -> Dict[str, Any]:
        return {
            'settings': await self.get_all_settings(),
            'presets': await self.get_presets(),
            'metadata': {
                'version': '1.0',
                'timestamp': datetime.utcnow().isoformat(),
                'checksum': self._calculate_checksum(self.settings)
            }
        }

    async def restore_backup(self, backup: Dict[str, Any]) -> bool:
        if not self._verify_backup(backup):
            raise ValueError("Invalid backup file")

        try:
            await self._apply_backup(backup)
            return True
        except Exception as e:
            raise ValueError(f"Restore failed: {str(e)}")

    async def save_preset(self, preset: Dict[str, Any]) -> str:
        preset_id = str(uuid4())
        preset['id'] = preset_id
        preset['created'] = datetime.utcnow().isoformat()
        await self._store_preset(preset)
        return preset_id

    def _calculate_checksum(self, data: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _verify_backup(self, backup: Dict[str, Any]) -> bool:
        required_keys = ['settings', 'metadata']
        return all(key in backup for key in required_keys)
