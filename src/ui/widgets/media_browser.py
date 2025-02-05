from typing import List, Dict
from dataclasses import dataclass

@dataclass
class MediaItem:
    id: str
    title: str
    type: str
    year: int
    poster: str
    rating: float
    duration: int
    progress: float = 0
    tags: List[str] = None

class MediaBrowserWidget:
    template = """
    <div class="media-browser">
        <div class="browser-header">
            <div class="search-bar">
                <input type="text" class="form-control" placeholder="Search media...">
                <div class="advanced-filters">
                    <button class="btn btn-outline-primary btn-sm" data-bs-toggle="modal" data-bs-target="#filterModal">
                        <i class="bi bi-funnel"></i> Filters
                    </button>
                </div>
            </div>
            <div class="view-controls">
                <div class="btn-group">
                    <button class="btn btn-sm btn-outline-secondary active" data-view="grid">
                        <i class="bi bi-grid"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" data-view="list">
                        <i class="bi bi-list"></i>
                    </button>
                </div>
                <select class="form-select form-select-sm" id="sortOrder">
                    <option value="recent">Recently Added</option>
                    <option value="rating">Highest Rated</option>
                    <option value="title">Title</option>
                    <option value="year">Release Year</option>
                </select>
            </div>
        </div>
        <div id="virtualScroller" class="media-grid">
            <!-- Virtual scrolling content -->
        </div>
        <div class="loading-indicator">
            <div class="spinner-border text-primary"></div>
        </div>
    </div>
    """

    @staticmethod
    def get_javascript() -> str:
        return """
        class MediaBrowser {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.scroller = this.container.querySelector('#virtualScroller');
                this.pageSize = 20;
                this.items = [];
                this.filteredItems = [];
                this.currentView = 'grid';
                
                this.setupVirtualScroller();
                this.setupSearch();
                this.setupFilters();
                this.setupViewControls();
            }

            setupVirtualScroller() {
                this.virtualScroller = new VirtualScroller({
                    element: this.scroller,
                    height: '800px',
                    rowHeight: this.currentView === 'grid' ? 300 : 100,
                    renderItem: (item) => this.renderMediaItem(item),
                    loadMore: () => this.loadMoreItems()
                });
            }

            async loadMoreItems() {
                const startIndex = this.items.length;
                const response = await fetch(`/api/media?start=${startIndex}&limit=${this.pageSize}`);
                const newItems = await response.json();
                
                this.items.push(...newItems);
                this.applyFilters();
                this.virtualScroller.updateItems(this.filteredItems);
            }

            renderMediaItem(item) {
                return this.currentView === 'grid' 
                    ? this.renderGridItem(item)
                    : this.renderListItem(item);
            }

            renderGridItem(item) {
                return `
                    <div class="media-card" data-id="${item.id}">
                        <div class="poster-wrapper">
                            <img src="${item.poster}" alt="${item.title}" loading="lazy">
                            <div class="overlay">
                                <div class="progress-bar">
                                    <div class="progress" style="width: ${item.progress}%"></div>
                                </div>
                                <div class="actions">
                                    <button class="btn btn-play">
                                        <i class="bi bi-play-fill"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                        <div class="media-info">
                            <h5 class="title">${item.title}</h5>
                            <div class="meta">
                                <span class="year">${item.year}</span>
                                <span class="rating">${item.rating}</span>
                                <span class="duration">${this.formatDuration(item.duration)}</span>
                            </div>
                        </div>
                    </div>
                `;
            }
        }
        """
