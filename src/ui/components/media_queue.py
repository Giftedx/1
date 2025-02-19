from typing import Dict, Any, List
from .base_widget import BaseWidget, WidgetConfig
from ...core.ffmpeg_manager import FFmpegManager
from ...core.plex_manager import PlexManager as PlexClient
import asyncio

class MediaQueueWidget(BaseWidget):
    def __init__(self, config: WidgetConfig, ffmpeg: FFmpegManager, plex: PlexClient):
        super().__init__(config)
        self.ffmpeg = ffmpeg
        self.plex = plex
        self._processing_tasks = {}

    async def update(self) -> Dict[str, Any]:
        active_jobs = await self.ffmpeg.get_active_jobs()
        queue = await self.ffmpeg.get_queue()
        
        return {
            'active_jobs': [self._format_job(job) for job in active_jobs],
            'queued_items': [self._format_queue_item(item) for item in queue],
            'resources': {
                'cpu_usage': await self.ffmpeg.get_cpu_usage(),
                'memory_usage': await self.ffmpeg.get_memory_usage(),
                'gpu_usage': await self.ffmpeg.get_gpu_usage()
            }
        }

    def render(self) -> str:
        return """
        <div class="media-queue-widget" data-widget-id="{{ widget.id }}">
            <div class="active-jobs">
                <h6>Active Transcoding Jobs</h6>
                <div class="job-cards" id="activeJobs"></div>
            </div>
            
            <div class="queue-status">
                <div class="progress-ring"></div>
                <div class="queue-stats">
                    <div class="stat">
                        <span class="label">Waiting</span>
                        <span class="value" id="queuedCount">0</span>
                    </div>
                    <div class="stat">
                        <span class="label">Processing</span>
                        <span class="value" id="processingCount">0</span>
                    </div>
                </div>
            </div>
            
            <div class="queue-items" id="queueItems"></div>
        </div>
        """

    def get_client_js(self) -> str:
        return """
        class MediaQueueWidget {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.activeJobs = this.container.querySelector('#activeJobs');
                this.queueItems = this.container.querySelector('#queueItems');
                
                this.setupDragAndDrop();
                this.initializeProgressRing();
            }

            update(data) {
                this.updateActiveJobs(data.active_jobs);
                this.updateQueueItems(data.queued_items);
                this.updateResourceMetrics(data.resources);
            }

            updateActiveJobs(jobs) {
                // Smooth transition for job cards
                const currentCards = new Set(
                    Array.from(this.activeJobs.children).map(el => el.dataset.jobId)
                );
                
                jobs.forEach(job => {
                    if (!currentCards.has(job.id)) {
                        this.addJobCard(job);
                    } else {
                        this.updateJobCard(job);
                    }
                    currentCards.delete(job.id);
                });

                // Remove completed jobs with animation
                currentCards.forEach(jobId => {
                    const card = this.activeJobs.querySelector(`[data-job-id="${jobId}"]`);
                    card.style.animation = 'slideOutRight 0.3s ease-out';
                    setTimeout(() => card.remove(), 300);
                });
            }

            addJobCard(job) {
                const card = document.createElement('div');
                card.className = 'job-card';
                card.dataset.jobId = job.id;
                card.innerHTML = this.renderJobCard(job);
                
                // Add with animation
                card.style.opacity = '0';
                card.style.transform = 'translateX(-20px)';
                this.activeJobs.appendChild(card);
                
                requestAnimationFrame(() => {
                    card.style.opacity = '1';
                    card.style.transform = 'translateX(0)';
                });
            }

            renderJobCard(job) {
                return `
                    <div class="job-info">
                        <div class="title">${job.title}</div>
                        <div class="details">
                            <span class="codec">${job.codec}</span>
                            <span class="quality">${job.quality}</span>
                        </div>
                    </div>
                    <div class="progress-bar">
                        <div class="progress" style="width: ${job.progress}%"></div>
                    </div>
                    <div class="actions">
                        <button class="btn-icon" onclick="cancelJob('${job.id}')">
                            <i class="bi bi-x-circle"></i>
                        </button>
                    </div>
                `;
            }
        }
        """

    def _format_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'id': job['id'],
            'title': job['title'],
            'progress': job['progress'],
            'codec': job['video_codec'],
            'quality': job['quality_profile'],
            'eta': job['estimated_completion'],
            'resources': {
                'cpu': job['cpu_usage'],
                'memory': job['memory_usage'],
                'gpu': job.get('gpu_usage', 0)
            }
        }
