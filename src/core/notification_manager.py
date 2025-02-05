from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
import re
from uuid import uuid4

@dataclass
class NotificationThread:
    id: str
    title: str
    notifications: List['Notification']
    last_update: datetime
    source: str
    context: Dict[str, Any]

@dataclass
class ThreadContext:
    error_count: int = 0
    warning_count: int = 0
    last_success: Optional[datetime] = None
    priority_level: int = 0
    related_threads: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

class NotificationManager:
    def __init__(self):
        self.threads: Dict[str, NotificationThread] = {}
        self._pattern_matchers = [
            (re.compile(r'Error in (\w+)'), self._group_by_error),
            (re.compile(r'Stream (\w+)'), self._group_by_stream),
            (re.compile(r'User (\w+)'), self._group_by_user)
        ]

    async def process_notification(self, notification: 'Notification'):
        thread = await self._find_or_create_thread(notification)
        thread.notifications.append(notification)
        thread.last_update = notification.timestamp
        await self._update_thread_context(thread)
        return thread

    async def _find_or_create_thread(self, notification: 'Notification') -> NotificationThread:
        thread_id = await self._determine_thread_id(notification)
        
        if thread_id not in self.threads:
            self.threads[thread_id] = NotificationThread(
                id=thread_id,
                title=self._generate_thread_title(notification),
                notifications=[],
                last_update=notification.timestamp,
                source=notification.source,
                context={}
            )
        
        return self.threads[thread_id]

    async def _determine_thread_id(self, notification: 'Notification') -> str:
        # Try to match existing patterns
        for pattern, matcher in self._pattern_matchers:
            if match := pattern.search(notification.message):
                return await matcher(match, notification)

        # Fallback to source-based grouping
        return f"{notification.source}_{notification.type}"

    async def _update_thread_context(self, thread: NotificationThread):
        # Update thread context based on notifications
        context = {}
        for notification in thread.notifications[-10:]:  # Look at last 10
            if notification.type == 'error':
                context.setdefault('error_count', 0)
                context['error_count'] += 1
            elif notification.type == 'success':
                context['last_success'] = notification.timestamp

        thread.context.update(context)

    def _generate_thread_title(self, notification: 'Notification') -> str:
        # Generate meaningful thread title based on content
        if notification.type == 'error':
            return f"Error Reports: {notification.source}"
        elif notification.type == 'stream':
            return f"Stream Activity: {notification.source}"
        return f"Notifications: {notification.source}"

    async def cleanup_old_threads(self, max_age_hours: int = 24):
        now = datetime.utcnow()
        old_threads = [
            thread_id for thread_id, thread in self.threads.items()
            if (now - thread.last_update).total_seconds() > max_age_hours * 3600
        ]
        for thread_id in old_threads:
            await self.archive_thread(thread_id)

    async def _group_by_error(self, match, notification):
        return f"error_{match.group(1)}_{notification.source}"

    async def _group_by_stream(self, match, notification):
        return f"stream_{match.group(1)}"

    async def _group_by_user(self, match, notification):
        return f"user_{match.group(1)}"

    async def analyze_pattern(self, notification: Notification) -> Dict[str, Any]:
        """Analyze notification content for smart threading"""
        patterns = {
            'error_stack': r'Error\: (.+)\n\s*at\s(.+)',
            'media_event': r'(play|pause|stop|seek)\s(.+)',
            'user_action': r'User\s(\w+)\s(requested|completed)\s(.+)',
            'system_alert': r'System\s(warning|error|info)\:\s(.+)',
        }

        matches = {}
        for key, pattern in patterns.items():
            if match := re.search(pattern, notification.message):
                matches[key] = match.groups()
        
        return matches

    async def find_related_threads(self, notification: Notification) -> List[str]:
        """Find threads related to this notification"""
        related = []
        for thread_id, thread in self.threads.items():
            if await self._check_thread_relation(thread, notification):
                related.append(thread_id)
        return related

    async def update_thread_context(self, thread: NotificationThread, notification: Notification):
        """Update thread context with new notification data"""
        context = thread.context
        
        # Update error tracking
        if notification.type == 'error':
            context.error_count += 1
            if context.error_count >= 3:
                await self._escalate_thread(thread)
        
        # Update success tracking
        elif notification.type == 'success':
            context.last_success = notification.timestamp
            if context.error_count > 0:
                await self._resolve_thread_errors(thread)

        # Dynamic priority adjustment
        thread.priority = await self._calculate_thread_priority(context)

    async def _escalate_thread(self, thread: NotificationThread):
        """Handle thread escalation for repeated errors"""
        await self.broadcast_notification(
            Notification(
                id=str(uuid4()),
                type='warning',
                title=f'Thread Escalated: {thread.title}',
                message=f'Multiple errors detected in thread',
                source='system',
                priority=2
            )
        )

    async def _resolve_thread_errors(self, thread: NotificationThread):
        """Handle error resolution in thread"""
        thread.context.error_count = 0
        await self.broadcast_notification(
            Notification(
                id=str(uuid4()),
                type='success',
                title=f'Thread Recovered: {thread.title}',
                message='Issues in thread have been resolved',
                source='system',
                priority=1
            )
        )

    async def _calculate_thread_priority(self, context: ThreadContext) -> int:
        """Calculate thread priority based on context"""
        priority = 0
        if context.error_count > 0:
            priority += min(context.error_count * 2, 10)
        if context.warning_count > 0:
            priority += min(context.warning_count, 5)
        if context.last_success:
            time_since_success = datetime.now() - context.last_success
            if time_since_success > timedelta(hours=1):
                priority += 2
        return min(priority, 10)
