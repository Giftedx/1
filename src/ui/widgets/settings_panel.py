from dataclasses import dataclass
from typing import Dict, Any, List
import json

@dataclass
class SettingsCategory:
    id: str
    name: str
    icon: str
    settings: List[Dict[str, Any]]

@dataclass
class SettingsPreset:
    id: str
    name: str
    description: str
    settings: Dict[str, Any]
    tags: List[str]
    created: datetime
    last_modified: datetime

class SettingsPanelWidget:
    template = """
    <div class="settings-panel" data-widget-id="{id}">
        <div class="settings-sidebar">
            <div class="settings-nav">
                {category_buttons}
            </div>
        </div>
        <div class="settings-content">
            <div class="settings-header">
                <h5 id="categoryTitle">General Settings</h5>
                <div class="preview-toggle">
                    <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" id="previewMode">
                        <label class="form-check-label" for="previewMode">Live Preview</label>
                    </div>
                </div>
            </div>
            <div class="settings-form">
                <!-- Dynamic settings form -->
            </div>
            <div class="settings-preview" style="display: none;">
                <!-- Live preview area -->
            </div>
            <div class="settings-actions">
                <button class="btn btn-secondary" id="resetSettings">Reset</button>
                <button class="btn btn-primary" id="saveSettings">Save Changes</button>
            </div>
        </div>
    </div>
    """

    def detect_conflicts(self, settings: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect potential conflicts between settings"""
        conflicts = []
        
        # Check for known conflict patterns
        for pattern in self.conflict_patterns:
            if pattern.check(settings):
                conflicts.append({
                    'type': pattern.type,
                    'settings': pattern.affected_settings,
                    'message': pattern.message,
                    'severity': pattern.severity,
                    'resolution': pattern.get_resolution(settings)
                })
        
        return conflicts

    @staticmethod
    def get_javascript() -> str:
        return """
        class SettingsPanel {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.currentCategory = 'general';
                this.originalSettings = {};
                this.changedSettings = new Map();
                this.previewTimeouts = new Map();
                
                this.setupEventListeners();
                this.loadSettings();
            }

            async loadSettings() {
                const response = await fetch('/api/settings');
                this.originalSettings = await response.json();
                this.renderSettings(this.currentCategory);
            }

            renderSettings(categoryId) {
                const category = this.originalSettings[categoryId];
                const form = this.container.querySelector('.settings-form');
                
                form.innerHTML = category.settings.map(setting => 
                    this.createSettingControl(setting)
                ).join('');
                
                // Initialize controls
                this.initializeControls(category.settings);
            }

            createSettingControl(setting) {
                switch (setting.type) {
                    case 'toggle':
                        return this.createToggle(setting);
                    case 'select':
                        return this.createSelect(setting);
                    case 'range':
                        return this.createRange(setting);
                    case 'color':
                        return this.createColorPicker(setting);
                    case 'text':
                        return this.createTextInput(setting);
                    // Add more control types as needed
                }
            }

            async previewChanges(setting, value) {
                // Clear existing preview timeout
                if (this.previewTimeouts.has(setting.id)) {
                    clearTimeout(this.previewTimeouts.get(setting.id));
                }
                
                // Set new timeout for preview
                this.previewTimeouts.set(setting.id, setTimeout(async () => {
                    try {
                        const preview = await this.getPreview({
                            ...this.getChangedSettings(),
                            [setting.id]: value
                        });
                        
                        this.updatePreview(preview);
                    } catch (error) {
                        console.error('Preview failed:', error);
                    }
                }, 200));
            }

            async saveSettings() {
                const changes = Object.fromEntries(this.changedSettings);
                
                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(changes)
                    });
                    
                    if (response.ok) {
                        // Update original settings
                        Object.assign(this.originalSettings, changes);
                        this.changedSettings.clear();
                        
                        // Show success message
                        this.showNotification('Settings saved successfully', 'success');
                    }
                } catch (error) {
                    this.showNotification('Failed to save settings', 'error');
                }
            }

            initializeSearch() {
                const searchInput = this.container.querySelector('#settingsSearch');
                searchInput.addEventListener('input', () => {
                    this.filterSettings(searchInput.value);
                });
            }

            filterSettings(query) {
                const settings = this.container.querySelectorAll('.setting-item');
                const terms = query.toLowerCase().split(' ');
                
                settings.forEach(setting => {
                    const text = setting.textContent.toLowerCase();
                    const matches = terms.every(term => text.includes(term));
                    setting.style.display = matches ? '' : 'none';
                });
            }

            async importSettings(file) {
                try {
                    const content = await file.text();
                    const settings = JSON.parse(content);
                    
                    // Validate imported settings
                    const validation = await this.validateSettings(settings);
                    if (!validation.valid) {
                        throw new Error(`Invalid settings: ${validation.errors.join(', ')}`);
                    }
                    
                    // Check for conflicts
                    const conflicts = await this.detectConflicts(settings);
                    if (conflicts.length > 0) {
                        await this.showConflictResolution(conflicts);
                    }
                    
                    await this.applySettings(settings);
                    this.showNotification('Settings imported successfully', 'success');
                } catch (error) {
                    this.showNotification('Failed to import settings', 'error');
                }
            }

            exportSettings() {
                const settings = this.getAllSettings();
                const blob = new Blob([JSON.stringify(settings, null, 2)], {
                    type: 'application/json'
                });
                const url = URL.createObjectURL(blob);
                
                const a = document.createElement('a');
                a.href = url;
                a.download = `settings_backup_${new Date().toISOString()}.json`;
                a.click();
                
                URL.revokeObjectURL(url);
            }

            async savePreset() {
                const name = await this.promptPresetName();
                if (!name) return;
                
                const preset = {
                    name,
                    settings: this.getChangedSettings(),
                    created: new Date().toISOString()
                };
                
                await this.savePresetToServer(preset);
                this.updatePresetList();
            }

            async detectConflicts(settings) {
                const response = await fetch('/api/settings/conflicts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });
                
                return await response.json();
            }

            async showConflictResolution(conflicts) {
                const modal = document.createElement('div');
                modal.className = 'modal fade';
                modal.innerHTML = `
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Settings Conflicts Detected</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                ${conflicts.map(conflict => `
                                    <div class="conflict-item">
                                        <div class="conflict-header">
                                            <span class="badge bg-${conflict.severity}">
                                                ${conflict.type}
                                            </span>
                                            <h6>${conflict.message}</h6>
                                        </div>
                                        <div class="conflict-resolution">
                                            <select class="form-select resolution-select">
                                                ${conflict.resolution.options.map(option => `
                                                    <option value="${option.value}">
                                                        ${option.label}
                                                    </option>
                                                `).join('')}
                                            </select>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                    Cancel
                                </button>
                                <button type="button" class="btn btn-primary" id="resolveConflicts">
                                    Apply Resolution
                                </button>
                            </div>
                        </div>
                    </div>
                `;
                
                document.body.appendChild(modal);
                const modalInstance = new bootstrap.Modal(modal);
                modalInstance.show();
                
                return new Promise(resolve => {
                    modal.querySelector('#resolveConflicts').onclick = () => {
                        const resolutions = Array.from(
                            modal.querySelectorAll('.resolution-select')
                        ).map(select => ({
                            conflictId: select.closest('.conflict-item').dataset.conflictId,
                            resolution: select.value
                        }));
                        
                        modalInstance.hide();
                        resolve(resolutions);
                    };
                });
            }
        }
        """

    async def apply_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        # Apply settings and return new state
        result = {}
        
        # Process each setting
        for key, value in settings.items():
            try:
                # Apply the setting
                result[key] = await self._apply_setting(key, value)
            except Exception as e:
                result[key] = {"error": str(e)}
        
        return result

    async def get_preview(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        # Generate preview without applying changes
        preview = {}
        
        # Process each setting for preview
        for key, value in settings.items():
            try:
                preview[key] = await self._generate_preview(key, value)
            except Exception as e:
                preview[key] = {"error": str(e)}
        
        return preview
