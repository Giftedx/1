from fastapi import APIRouter, Depends, HTTPException, WebSocket
from typing import Dict, Any, List
from ..core.user_preferences import PreferencesManager, UserPreferences
from ..ui.themes import ThemeManager
import os
from ..core.notifications import NotificationCenter, Notification
from ..core.settings import SettingsManager
from uuid import uuid4
from datetime import datetime
import logging
import io
import json
from fastapi.responses import StreamingResponse

router = APIRouter()
prefs_manager = PreferencesManager(os.getenv('REDIS_URL'))
notification_center = NotificationCenter()
settings_manager = SettingsManager()
logger = logging.getLogger(__name__)

@router.get("/api/preferences")
async def get_preferences(user_id: str = Depends(get_current_user)):
    return await prefs_manager.get_preferences(user_id)

@router.post("/api/preferences")
async def update_preferences(
    updates: Dict[str, Any],
    user_id: str = Depends(get_current_user)
):
    await prefs_manager.update_preferences(user_id, updates)
    return {"status": "success"}

@router.get("/api/themes/{theme_name}")
async def get_theme(theme_name: str):
    theme = ThemeManager.get_theme(theme_name)
    return ThemeManager.get_theme_css(theme)

@router.post("/api/media/control")
async def control_media(command: Dict[str, Any]):
    # Handle media control commands
    return {"status": "success"}

@router.websocket("/ws/notifications")
async def notifications_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        # Register client
        notification_center.add_client(websocket)
        
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_json()
            if data.get('type') == 'ack':
                await notification_center.mark_as_read(data['notification_id'])
    except Exception as e:
        logger.error(f"Notification WebSocket error: {e}")
    finally:
        notification_center.remove_client(websocket)
        await websocket.close()

@router.get("/api/settings/{category}")
async def get_settings(category: str):
    return await settings_manager.get_category(category)

@router.post("/api/settings")
async def update_settings(settings: Dict[str, Any]):
    result = await settings_manager.apply_settings(settings)
    
    # Notify clients of settings changes
    await notification_center.broadcast_notification(
        Notification(
            id=str(uuid4()),
            type="info",
            title="Settings Updated",
            message="Settings have been updated successfully",
            timestamp=datetime.now(),
            source="settings",
            icon="gear",
            priority=0
        )
    )
    
    return result

@router.post("/api/settings/preview")
async def preview_settings(settings: Dict[str, Any]):
    return await settings_manager.get_preview(settings)

@router.post("/api/settings/conflicts")
async def check_settings_conflicts(settings: Dict[str, Any]):
    """Check for potential conflicts in settings"""
    return await settings_manager.detect_conflicts(settings)

@router.post("/api/settings/import")
async def import_settings(settings: Dict[str, Any]):
    """Import settings with validation and conflict detection"""
    validation = await settings_manager.validate_settings(settings)
    if not validation['valid']:
        raise HTTPException(400, validation['errors'])
        
    conflicts = await settings_manager.detect_conflicts(settings)
    return {
        'conflicts': conflicts,
        'requires_resolution': bool(conflicts)
    }

@router.get("/api/settings/presets")
async def get_setting_presets():
    """Get all available setting presets"""
    return await settings_manager.get_presets()

@router.post("/api/settings/presets")
async def save_setting_preset(preset: Dict[str, Any]):
    """Save a new settings preset"""
    return await settings_manager.save_preset(preset)

@router.get("/api/settings/backup")
async def backup_settings():
    """Create a full settings backup"""
    backup = await settings_manager.create_backup()
    return StreamingResponse(
        io.BytesIO(json.dumps(backup).encode()),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=settings_backup.json"}
    )

@router.post("/api/settings/restore")
async def restore_settings(backup: Dict[str, Any]):
    """Restore settings from backup"""
    return await settings_manager.restore_backup(backup)

@router.post("/api/settings/validate")
async def validate_settings(settings: Dict[str, Any]):
    """Validate settings before applying"""
    validation = await settings_manager.validate_settings(settings)
    if validation['conflicts']:
        return {
            'valid': False,
            'conflicts': validation['conflicts'],
            'suggestions': await settings_manager.generate_suggestions(settings)
        }
    return {'valid': True}

@router.post("/api/notifications/thread/{thread_id}")
async def update_thread(thread_id: str, action: str):
    """Update notification thread state"""
    if action == "collapse":
        await notification_manager.collapse_thread(thread_id)
    elif action == "expand":
        await notification_manager.expand_thread(thread_id)
    return {"status": "success"}

@router.get("/api/settings/search")
async def search_settings(query: str):
    """Search settings with fuzzy matching"""
    return await settings_manager.search_settings(query)

@router.post("/api/settings/export")
async def export_settings(categories: List[str]):
    """Export selected settings categories"""
    settings = await settings_manager.export_settings(categories)
    return StreamingResponse(
        io.BytesIO(json.dumps(settings).encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=settings_export_{datetime.now():%Y%m%d}.json"}
    )
