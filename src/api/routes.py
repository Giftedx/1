from fastapi import APIRouter, Depends, HTTPException, WebSocket
from typing import Dict, Any, List, Optional
from ..core.user_preferences import PreferencesManager, UserPreferences
from ..ui.themes import ThemeManager
import os
import logging
import io
import json
from fastapi.responses import StreamingResponse
from ..core.notifications import notification_center as notification_manager
from pydantic import BaseModel, validator
from src.security.input_validation import SecurityValidator

router = APIRouter()
prefs_manager = PreferencesManager(os.getenv('REDIS_URL'))
notification_center = NotificationCenter()
settings_manager = SettingsManager()
logger = logging.getLogger(__name__)

# Example dependency for getting the current user
async def get_current_user(token: str) -> Optional[str]:  # Replace str with your user model
    """
    This is a placeholder. Replace with your actual authentication logic.
    """
    if token == "valid_token":
        return "example_user"  # Replace with your user object
    return None

class PreferencesUpdate(BaseModel):
    theme: Optional[str] = None
    layout: Optional[Dict[str, Any]] = None
    widgets: Optional[Dict[str, bool]] = None
    notifications: Optional[Dict[str, bool]] = None
    playback: Optional[Dict[str, Any]] = None

    @validator("*", pre=True)
    def sanitize_values(cls, value):
        if isinstance(value, str):
            return SecurityValidator.sanitize_html(value)
        return value

class MediaControl(BaseModel):
    action: str
    media_id: str
    timestamp: datetime

    @validator("*", pre=True)
    def sanitize_values(cls, value):
        if isinstance(value, str):
            return SecurityValidator.sanitize_html(value)
        return value

class NotificationUpdate(BaseModel):
    thread_id: str
    read: bool

    @validator("*", pre=True)
    def sanitize_values(cls, value):
        if isinstance(value, str):
            return SecurityValidator.sanitize_html(value)
        return value

class SettingsUpdate(BaseModel):
    category: str
    settings: Dict[str, Any]

    @validator("*", pre=True)
    def sanitize_values(cls, value):
        if isinstance(value, str):
            return SecurityValidator.sanitize_html(value)
        return value

class SettingsPreset(BaseModel):
    name: str
    description: str
    settings: Dict[str, Any]
    tags: List[str]

    @validator("*", pre=True)
    def sanitize_values(cls, value):
        if isinstance(value, str):
            return SecurityValidator.sanitize_html(value)
        return value

class ItemCreate(BaseModel):
    name: str
    description: str

    @validator("*", pre=True)
    def sanitize_values(cls, value):
        if isinstance(value, str):
            return SecurityValidator.sanitize_html(value)
        return value

@router.get("/api/preferences")
async def get_preferences(user_id: str = Depends(get_current_user)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    prefs = await prefs_manager.get_preferences(user_id)
    return prefs

@router.post("/api/preferences")
async def update_preferences(
    prefs_update: PreferencesUpdate,
    user_id: str = Depends(get_current_user)
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        await prefs_manager.update_preferences(user_id, prefs_update.dict(exclude_unset=True))
        return {"message": "Preferences updated successfully"}
    except Exception as e:
        logger.error(f"Failed to update preferences: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update preferences")

@router.get("/api/themes/{theme_name}")
async def get_theme(theme_name: str):
    theme = ThemeManager.get_theme(theme_name)
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")
    return theme

@router.post("/api/media/control")
async def control_media(media_control: MediaControl):
    # Handle media control commands
    return {"status": "success"}

@router.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
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
async def update_settings(settings_update: SettingsUpdate):
    result = await settings_manager.apply_settings(settings_update.settings)
    
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
async def preview_settings(settings_update: SettingsUpdate):
    return await settings_manager.get_preview(settings_update.settings)

@router.post("/api/settings/conflicts")
async def check_settings_conflicts(settings_update: SettingsUpdate):
    """Check for potential conflicts in settings"""
    return await settings_manager.detect_conflicts(settings_update.settings)

@router.post("/api/settings/import")
async def import_settings(settings_update: SettingsUpdate):
    """Import settings with validation and conflict detection"""
    validation = await settings_manager.validate_settings(settings_update.settings)
    if not validation['valid']:
        raise HTTPException(400, validation['errors'])
        
    conflicts = await settings_manager.detect_conflicts(settings_update.settings)
    return {
        'conflicts': conflicts,
        'requires_resolution': bool(conflicts)
    }

@router.get("/api/settings/presets")
async def get_settings_presets():
    """Get all available setting presets"""
    return await settings_manager.get_presets()

@router.post("/api/settings/presets")
async def create_settings_preset(settings_preset: SettingsPreset):
    """Save a new settings preset"""
    return await settings_manager.save_preset(settings_preset.dict())

@router.get("/api/settings/backup")
async def get_settings_backup():
    """Create a full settings backup"""
    backup = await settings_manager.create_backup()
    return StreamingResponse(
        io.BytesIO(json.dumps(backup).encode()),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=settings_backup.json"}
    )

@router.post("/api/settings/restore")
async def restore_settings(settings_update: SettingsUpdate):
    """Restore settings from backup"""
    return await settings_manager.restore_backup(settings_update.settings)

@router.post("/api/settings/validate")
async def validate_settings(settings_update: SettingsUpdate):
    """Validate settings before applying"""
    validation = await settings_manager.validate_settings(settings_update.settings)
    if validation['conflicts']:
        return {
            'valid': False,
            'conflicts': validation['conflicts'],
            'suggestions': await settings_manager.generate_suggestions(settings_update.settings)
        }
    return {'valid': True}

@router.post("/api/notifications/thread/{thread_id}")
async def update_notification_thread(thread_id: str, notification_update: NotificationUpdate):
    """Update notification thread state"""
    if notification_update.read:
        await notification_manager.collapse_thread(thread_id)
    else:
        await notification_manager.expand_thread(thread_id)
    return {"status": "success"}

@router.get("/api/settings/search")
async def search_settings(query: str):
    """Search settings with fuzzy matching"""
    return await settings_manager.search_settings(query)

@router.post("/api/settings/export")
async def export_settings(settings_update: SettingsUpdate):
    """Export selected settings categories"""
    settings = await settings_manager.export_settings(settings_update.settings)
    return StreamingResponse(
        io.BytesIO(json.dumps(settings).encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=settings_export_{datetime.now():%Y%m%d}.json"}
    )

@router.get("/items/{item_id}")
async def get_item(item_id: int, q: Optional[str] = None, current_user: str = Depends(get_current_user)):
    """
    Example route handler.
    """
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"item_id": item_id, "q": q, "current_user": current_user}

@router.post("/items/")
async def create_item(item_create: ItemCreate, current_user: str = Depends(get_current_user)):
    """
    Example route handler.
    """
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"name": item_create.name, "description": item_create.description, "owner": current_user}
