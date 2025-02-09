from datetime import datetime
from typing import List, Dict
import asyncio
from dataclasses import dataclass

@dataclass
class ActivityItem:
    id: str
    type: str
    title: str
    timestamp: datetime
    details: Dict
    icon: str
    color: str

class ActivityFeedWidget:
    template = """
    <div class="activity-feed widget">
        <div class="feed-header">
            <div class="feed-filters">
                <div class="btn-group" role="group" aria-label="Activity Filters">
                    {filter_buttons}
                </div>
                <div class="input-group">
                    <input type="text" class="form-control form-control-sm" placeholder="Search activities..." aria-label="Search" aria-describedby="search-addon">
                    <button class="btn btn-outline-secondary btn-sm" type="button" id="search-addon">
                        <i class="bi bi-search"></i>
                    </button>
                </div>
            </div>
            <div class="feed-stats">
                {stats_display}
            </div>
        </div>
        <div class="feed-timeline">
            <ul class="list-group list-group-flush" id="timeline-{id}">
                {activity_items}
            </ul>
        </div>
        <div class="feed-footer">
            <button class="btn btn-primary btn-sm load-more">Load More</button>
        </div>
    </div>
    """

    def __init__(self):
        self.filters = {
            "all": "All Activities",
            "media": "Media",
            "system": "System",
            "users": "Users",
            "errors": "Errors"
        }
        self.current_filter = "all"
        self.activities: List[ActivityItem] = []

    async def fetch_activities(self, filter_type: str = None, page: int = 1) -> List[ActivityItem]:
        # Fetch activities from various sources
        activities = []
        
        # Fetch Plex activities
        plex_activities = await self.fetch_plex_activities()
        activities.extend(plex_activities)
        
        # Fetch system activities
        system_activities = await self.fetch_system_activities()
        activities.extend(system_activities)
        
        # Fetch user activities
        user_activities = await self.fetch_user_activities()
        activities.extend(user_activities)
        
        # Apply filters
        if filter_type and filter_type != "all":
            activities = [a for a in activities if a.type == filter_type]
            
        # Sort by timestamp
        activities.sort(key=lambda x: x.timestamp, reverse=True)
        
        return activities

    def render_activity_item(self, item: ActivityItem) -> str:
        return f"""
        <div class="activity-item {item.type}" data-id="{item.id}">
            <div class="activity-icon" style="background-color: {item.color}">
                <i class="bi bi-{item.icon}"></i>
            </div>
            <div class="activity-content">
                <div class="activity-header">
                    <span class="activity-title">{item.title}</span>
                    <span class="activity-time">{self.format_time(item.timestamp)}</span>
                </div>
                <div class="activity-details">
                    {self.render_details(item.details)}
                </div>
            </div>
        </div>
        """

    @staticmethod
    def format_time(timestamp: datetime) -> str:
        now = datetime.now()
        delta = now - timestamp
        
        if delta.days == 0:
            if delta.seconds < 60:
                return "just now"
            if delta.seconds < 3600:
                return f"{delta.seconds // 60}m ago"
            return f"{delta.seconds // 3600}h ago"
        if delta.days == 1:
            return "yesterday"
        if delta.days < 7:
            return f"{delta.days}d ago"
        return timestamp.strftime("%Y-%m-%d")

    @staticmethod
    def get_javascript() -> str:
        return """
        class ActivityFeed {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.setupFilters();
                this.setupSearch();
                this.setupInfiniteScroll();
            }

            async loadActivities(filter = 'all', page = 1) {
                const response = await fetch(`/api/activities?filter=${filter}&page=${page}`);
                const activities = await response.json();
                this.renderActivities(activities);
            }

            setupInfiniteScroll() {
                const observer = new IntersectionObserver(
                    (entries) => {
                        if (entries[0].isIntersecting) {
                            this.loadMore();
                        }
                    },
                    { threshold: 0.5 }
                );
                observer.observe(this.container.querySelector('.load-more'));
            }

            renderActivities(activities) {
                // Render with smooth animations
                activities.forEach(activity => {
                    const element = this.createActivityElement(activity);
                    element.style.opacity = '0';
                    element.style.transform = 'translateY(20px)';
                    this.container.querySelector('.timeline-items').appendChild(element);
                    
                    requestAnimationFrame(() => {
                        element.style.opacity = '1';
                        element.style.transform = 'translateY(0)';
                    });
                });
            }
        }
        """
