from typing import Dict, Any, List
from .base_widget import BaseWidget, WidgetConfig
from ...core.plex_manager import PlexManager as PlexClient
import asyncio
from datetime import datetime

class MediaBrowserWidget(BaseWidget):
    def __init__(self, config: WidgetConfig, plex: PlexClient):
        super().__init__(config)
        self.plex = plex
        self.page_size = 50
        self._cache = {}

    def render(self) -> str:
        return """
        <div class="media-browser-widget" data-widget-id="{{ widget.id }}">
            <div class="browser-header">
                <div class="view-controls btn-group">
                    <button class="btn btn-sm btn-outline-primary active" data-view="grid">
                        <i class="bi bi-grid"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-primary" data-view="list">
                        <i class="bi bi-list"></i>
                    </button>
                </div>
                <div class="filter-controls">
                    <select class="form-select form-select-sm" id="librarySelect">
                        <option value="all">All Libraries</option>
                        <!-- Libraries populated dynamically -->
                    </select>
                    <select class="form-select form-select-sm" id="sortOrder">
                        <option value="recent">Recently Added</option>
                        <option value="name">Name</option>
                        <option value="rating">Rating</option>
                    </select>
                </div>
            </div>
            <div id="mediaGrid" class="media-grid"></div>
            <div id="virtualScroller" class="virtual-scroll-container"></div>
        </div>
        """

    def get_client_js(self) -> str:
        return """
        class MediaBrowser {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.scroller = new VirtualScroller({
                    element: '#virtualScroller',
                    rowHeight: 300,
                    pageSize: 50,
                    buffer: 10,
                    renderItem: this.renderMediaItem.bind(this),
                    loadMore: this.loadMoreItems.bind(this)
                });
                
                this.setupVirtualScroll();
                this.setupLazyLoading();
                this.setupFilters();
                this.setupSearch();
                this.setupKeyboardNavigation();
            }

            setupVirtualScroll() {
                this.virtualScroller = new VirtualScroller({
                    element: this.container.querySelector('.media-grid'),
                    itemHeight: this.getItemHeight(),
                    renderItem: this.renderItem.bind(this),
                    loadMore: this.loadMoreItems.bind(this),
                    estimateHeight: true,
                    overscan: 5,
                    batchSize: 10
                });
            }

            setupLazyLoading() {
                this.imageObserver = new IntersectionObserver(
                    (entries) => {
                        entries.forEach(entry => {
                            if (entry.isIntersecting) {
                                this.loadImage(entry.target);
                            }
                        });
                    },
                    {
                        root: this.container,
                        rootMargin: '50px',
                        threshold: 0.1
                    }
                );
            }

            async loadMoreItems(startIndex, count) {
                if (this.loading) return;
                this.loading = true;
                
                try {
                    const response = await fetch(
                        `/api/media/items?start=${startIndex}&count=${count}&filters=${this.getFilters()}`
                    );
                    const data = await response.json();
                    
                    // Process and cache items
                    this.cacheItems(data.items);
                    
                    // Update virtual scroller
                    this.virtualScroller.updateItems(startIndex, data.items);
                    
                    return {
                        items: data.items,
                        total: data.total
                    };
                } finally {
                    this.loading = false;
                }
            }

            renderItem(item) {
                const element = document.createElement('div');
                element.className = 'media-item';
                element.innerHTML = `
                    <div class="media-card" data-id="${item.id}">
                        <div class="poster-wrapper">
                            <img 
                                data-src="${item.thumb}"
                                alt="${item.title}"
                                class="lazy-image"
                            >
                            <div class="media-overlay">
                                <div class="media-info">
                                    <h5>${item.title}</h5>
                                    <div class="meta">
                                        <span class="year">${item.year}</span>
                                        <span class="rating">${this.formatRating(item.rating)}</span>
                                        <span class="duration">${this.formatDuration(item.duration)}</span>
                                    </div>
                                </div>
                                <div class="media-actions">
                                    ${this.renderActions(item)}
                                </div>
                            </div>
                        </div>
                        <div class="media-details">
                            ${this.renderDetails(item)}
                        </div>
                    </div>
                `;

                // Observe image for lazy loading
                const img = element.querySelector('.lazy-image');
                if (img) this.imageObserver.observe(img);

                return element;
            }

            setupKeyboardNavigation() {
                this.container.addEventListener('keydown', (e) => {
                    const focused = this.container.querySelector('.media-card:focus');
                    if (!focused) return;

                    switch(e.key) {
                        case 'ArrowRight':
                            this.focusNext(focused);
                            break;
                        case 'ArrowLeft':
                            this.focusPrevious(focused);
                            break;
                        case 'Enter':
                            this.playMedia(focused.dataset.id);
                            break;
                    }
                });
            }
        }
        """

    async def update(self) -> Dict[str, Any]:
        """Get paginated media items"""
        return {
            'items': await self._get_media_items(),
            'total_count': await self._get_total_count(),
            'libraries': await self._get_libraries()
        }

    async def _get_media_items(self, start: int = 0, count: int = 50) -> List[Dict[str, Any]]:
        """Get a page of media items"""
        items = await self.plex.get_items(start, count)
        return [self._format_media_item(item) for item in items]

    def _format_media_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'id': item['id'],
            'title': item['title'],
            'year': item.get('year'),
            'thumb': item.get('thumb'),
            'rating': item.get('rating'),
            'duration': self._format_duration(item.get('duration', 0)),
            'type': item.get('type'),
            'added_at': datetime.fromtimestamp(item.get('addedAt', 0))
        }
