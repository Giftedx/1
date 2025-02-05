from typing import List, Dict, Any
from dataclasses import dataclass
import elasticsearch

@dataclass
class SearchFilter:
    field: str
    operator: str
    value: Any
    boost: float = 1.0

class AdvancedSearchWidget:
    template = """
    <div class="search-interface" data-widget-id="{id}">
        <div class="search-header">
            <div class="main-search">
                <div class="input-group">
                    <input type="text" class="form-control" placeholder="Search...">
                    <button class="btn btn-primary">
                        <i class="bi bi-search"></i>
                    </button>
                </div>
                <button class="btn btn-link" data-bs-toggle="collapse" data-bs-target="#advancedSearch">
                    Advanced Search
                </button>
            </div>
            
            <div id="advancedSearch" class="collapse">
                <div class="filter-builder">
                    <!-- Dynamic filter interface -->
                </div>
                <div class="saved-searches">
                    <!-- Saved search templates -->
                </div>
            </div>
        </div>

        <div class="search-results" id="searchResults">
            <div class="results-header">
                <div class="results-count"></div>
                <div class="results-sorting">
                    <select class="form-select form-select-sm">
                        <option value="relevance">Relevance</option>
                        <option value="date">Date</option>
                        <option value="title">Title</option>
                    </select>
                </div>
            </div>
            <div class="results-grid">
                <!-- Results will be dynamically added here -->
            </div>
            <div class="results-pagination"></div>
        </div>
    </div>
    """

    @staticmethod
    def get_javascript() -> str:
        return """
        class AdvancedSearch {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.searchInput = this.container.querySelector('input[type="text"]');
                this.filterBuilder = this.container.querySelector('.filter-builder');
                this.resultsGrid = this.container.querySelector('.results-grid');
                
                this.setupEventListeners();
                this.initializeFilterBuilder();
            }

            async search(query, filters = []) {
                const searchQuery = this.buildElasticsearchQuery(query, filters);
                const results = await this.executeSearch(searchQuery);
                this.renderResults(results);
            }

            buildElasticsearchQuery(query, filters) {
                return {
                    bool: {
                        must: [{
                            multi_match: {
                                query: query,
                                fields: ['title^2', 'description', 'tags']
                            }
                        }],
                        filter: filters.map(f => ({
                            term: { [f.field]: f.value }
                        }))
                    }
                };
            }

            renderResults(results) {
                // Clear existing results
                this.resultsGrid.innerHTML = '';
                
                // Add results with smooth animations
                results.forEach((result, index) => {
                    const element = this.createResultElement(result);
                    element.style.opacity = '0';
                    element.style.transform = 'translateY(20px)';
                    this.resultsGrid.appendChild(element);
                    
                    // Stagger animations
                    setTimeout(() => {
                        element.style.opacity = '1';
                        element.style.transform = 'translateY(0)';
                    }, index * 50);
                });
            }

            initializeFilterBuilder() {
                const filterTypes = {
                    text: {
                        operators: ['contains', 'equals', 'starts_with', 'ends_with'],
                        component: 'input'
                    },
                    number: {
                        operators: ['equals', 'greater_than', 'less_than', 'between'],
                        component: 'number-input'
                    },
                    date: {
                        operators: ['equals', 'after', 'before', 'between'],
                        component: 'date-picker'
                    },
                    enum: {
                        operators: ['equals', 'in'],
                        component: 'select'
                    }
                };

                // Create filter builder interface
                this.filterBuilder.innerHTML = this.createFilterBuilderHTML(filterTypes);
            }
        }
        """
