from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime
import asyncio
import json

@dataclass
class Notification:
    id: str
    type: str  # info, warning, error, success
    title: str
    message: str
    timestamp: datetime
    source: str
    icon: str
    actions: Optional[List[Dict]] = None
    read: bool = False
    priority: int = 0

@dataclass
class NotificationGroup:
    id: str
    title: str
    notifications: List[Notification]
    collapsed: bool = True
    last_update: datetime = None

    def __post_init__(self):
        self.last_update = max(n.timestamp for n in self.notifications)

class NotificationCenterWidget:
    template = """
    <div class="notification-center" data-widget-id="{id}">
        <div class="notification-header">
            <h5 class="mb-0">
                <i class="bi bi-bell"></i> Notifications
                <span class="badge bg-danger" id="unread-count">0</span>
            </h5>
            <div class="notification-actions">
                <button class="btn btn-sm btn-outline-secondary" id="markAllRead">
                    <i class="bi bi-check-all"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" id="clearAll">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>
        <div class="notification-filters">
            <div class="btn-group btn-group-sm">
                <button class="btn btn-outline-primary active" data-filter="all">All</button>
                <button class="btn btn-outline-primary" data-filter="unread">Unread</button>
                <button class="btn btn-outline-primary" data-filter="important">Important</button>
            </div>
        </div>
        <div class="notification-list" id="notificationList"></div>
    </div>
    """

    def group_notifications(self, notifications: List[Notification]) -> List[NotificationGroup]:
        groups = {}
        
        for notification in notifications:
            # Group by source and thread ID if available
            group_key = f"{notification.source}:{notification.get('thread_id', '')}"
            
            if group_key not in groups:
                groups[group_key] = NotificationGroup(
                    id=str(uuid4()),
                    title=self.get_group_title(notification),
                    notifications=[]
                )
            
            groups[group_key].notifications.append(notification)

        # Sort groups by last update
        return sorted(groups.values(), key=lambda g: g.last_update, reverse=True)

    @staticmethod
    def get_javascript() -> str:
        return """
        class NotificationCenter {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.ws = null;
                this.notifications = new Map();
                this.unreadCount = 0;
                this.filter = 'all';
                
                this.setupWebSocket();
                this.setupEventListeners();
                this.initializeAnimations();
                this.setupGroupHandling();
            }

            setupWebSocket() {
                this.ws = new WebSocket(`ws://${window.location.host}/ws/notifications`);
                
                this.ws.onmessage = (event) => {
                    const notification = JSON.parse(event.data);
                    this.addNotification(notification);
                };

                this.ws.onclose = () => {
                    setTimeout(() => this.setupWebSocket(), 5000);
                };
            }

            addNotification(notification) {
                this.notifications.set(notification.id, notification);
                
                const element = this.createNotificationElement(notification);
                const list = this.container.querySelector('#notificationList');
                
                // Add with animation
                element.style.opacity = '0';
                element.style.transform = 'translateX(-20px)';
                list.insertBefore(element, list.firstChild);
                
                requestAnimationFrame(() => {
                    element.style.opacity = '1';
                    element.style.transform = 'translateX(0)';
                });

                // Update unread count
                if (!notification.read) {
                    this.updateUnreadCount(1);
                }

                // Show desktop notification if important
                if (notification.priority > 0) {
                    this.showDesktopNotification(notification);
                }

                // Automatic cleanup of old notifications
                if (this.notifications.size > 100) {
                    const oldest = Array.from(this.notifications.keys())[0];
                    this.removeNotification(oldest);
                }
            }

            createNotificationElement(notification) {
                const element = document.createElement('div');
                element.className = `notification-item ${notification.type} ${notification.read ? 'read' : 'unread'}`;
                element.dataset.id = notification.id;
                
                element.innerHTML = `
                    <div class="notification-icon">
                        <i class="bi bi-${notification.icon}"></i>
                    </div>
                    <div class="notification-content">
                        <div class="notification-header">
                            <h6 class="notification-title">${notification.title}</h6>
                            <span class="notification-time">${this.formatTime(notification.timestamp)}</span>
                        </div>
                        <div class="notification-message">${notification.message}</div>
                        ${this.renderActions(notification.actions)}
                    </div>
                `;

                return element;
            }

            async handleNotificationAction(actionId, notificationId) {
                try {
                    const response = await fetch('/api/notifications/action', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ actionId, notificationId })
                    });
                    
                    if (response.ok) {
                        this.removeNotification(notificationId);
                    }
                } catch (error) {
                    console.error('Action failed:', error);
                }
            }

            setupGroupHandling() {
                this.container.addEventListener('click', e => {
                    const groupHeader = e.target.closest('.notification-group-header');
                    if (groupHeader) {
                        const groupId = groupHeader.dataset.groupId;
                        this.toggleGroup(groupId);
                    }
                });
            }

            toggleGroup(groupId) {
                const group = this.container.querySelector(`[data-group-id="${groupId}"]`);
                const content = group.querySelector('.notification-group-content');
                const isCollapsed = content.classList.contains('collapsed');
                
                content.style.height = isCollapsed ? `${content.scrollHeight}px` : '0';
                content.classList.toggle('collapsed');
                
                // Update group state
                this.notificationGroups.get(groupId).collapsed = !isCollapsed;
                this.saveGroupStates();
            }

            renderGroup(group) {
                return `
                    <div class="notification-group" data-group-id="${group.id}">
                        <div class="notification-group-header">
                            <div class="group-title">
                                <i class="bi bi-chevron-right"></i>
                                ${group.title}
                                <span class="badge bg-secondary">${group.notifications.length}</span>
                            </div>
                            <div class="group-actions">
                                <button class="btn btn-sm btn-link" onclick="markGroupRead('${group.id}')">
                                    Mark All Read
                                </button>
                            </div>
                        </div>
                        <div class="notification-group-content ${group.collapsed ? 'collapsed' : ''}">
                            ${group.notifications.map(n => this.renderNotification(n)).join('')}
                        </div>
                    </div>
                `;
            }

            async markGroupRead(groupId) {
                const group = this.notificationGroups.get(groupId);
                if (!group) return;

                const notificationIds = group.notifications
                    .filter(n => !n.read)
                    .map(n => n.id);

                await this.markNotificationsRead(notificationIds);
                this.updateUnreadCount();
            }
        }
        """

    async def broadcast_notification(self, notification: Notification):
        # Broadcast to all connected clients
        message = json.dumps({
            "id": notification.id,
            "type": notification.type,
            "title": notification.title,
            "message": notification.message,
            "timestamp": notification.timestamp.isoformat(),
            "source": notification.source,
            "icon": notification.icon,
            "actions": notification.actions,
            "priority": notification.priority
        })
        
        # Send to all connected WebSocket clients
        for client in self.connected_clients:
            await client.send_text(message)

    async def get_notification_updates(self) -> Dict[str, Any]:
        """Get real-time notification updates"""
        updates = {
            'new': [],
            'modified': [],
            'deleted': []
        }
        
        # Check for new notifications
        for notification in await self.fetch_new_notifications():
            group = self.find_or_create_group(notification)
            updates['new'].append({
                'notification': notification,
                'groupId': group.id
            })
        
        return updates

    async def broadcast_group_update(self, group_id: str):
        """Broadcast group state changes to all clients"""
        group = self.notification_groups.get(group_id)
        if not group:
            return
            
        await self.broadcast_to_clients({
            'type': 'group_update',
            'groupId': group_id,
            'data': {
                'collapsed': group.collapsed,
                'notificationCount': len(group.notifications),
                'lastUpdate': group.last_update.isoformat()
            }
        })
