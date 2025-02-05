from typing import Dict, Any, List
from .base_widget import BaseWidget, WidgetConfig
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np

@dataclass
class ActivityPoint:
    timestamp: datetime
    user_id: str
    action: str
    value: float
    coordinates: tuple[float, float] = None

class ActivityHeatmapWidget(BaseWidget):
    VERTEX_SHADER = """
    precision highp float;
    attribute vec3 position;
    attribute float intensity;
    uniform mat4 modelViewMatrix;
    uniform mat4 projectionMatrix;
    varying float vIntensity;
    
    void main() {
        vIntensity = intensity;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        gl_PointSize = 10.0;
    }
    """

    FRAGMENT_SHADER = """
    precision highp float;
    varying float vIntensity;
    uniform vec3 colorLow;
    uniform vec3 colorHigh;
    
    void main() {
        vec2 cxy = 2.0 * gl_PointCoord - 1.0;
        float r = dot(cxy, cxy);
        if (r > 1.0) discard;
        
        vec3 color = mix(colorLow, colorHigh, vIntensity);
        float alpha = smoothstep(1.0, 0.0, r) * 0.8;
        gl_FragColor = vec4(color, alpha);
    }
    """

    def __init__(self, config: WidgetConfig):
        super().__init__(config)
        self.points = []

    def render(self) -> str:
        return """
        <div class="activity-heatmap-widget" data-widget-id="{{ widget.id }}">
            <div class="heatmap-controls">
                <div class="btn-group time-scale">
                    <button class="btn btn-sm btn-primary" data-scale="hour">Hour</button>
                    <button class="btn btn-sm btn-outline-primary" data-scale="day">Day</button>
                    <button class="btn btn-sm btn-outline-primary" data-scale="week">Week</button>
                </div>
                <div class="view-controls">
                    <button class="btn btn-sm btn-outline-secondary toggle-3d">
                        <i class="bi bi-cube"></i> 3D View
                    </button>
                </div>
            </div>
            <canvas id="heatmap-{{ widget.id }}" class="heatmap-canvas"></canvas>
            <div class="heatmap-legend"></div>
        </div>
        """

    def get_client_js(self) -> str:
        return """
        class ActivityHeatmap {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.canvas = this.container.querySelector('canvas');
                this.gl = this.canvas.getContext('webgl2');
                this.points = [];
                this.is3D = false;
                
                this.initGL();
                this.initControls();
                this.startAnimation();
            }

            initGL() {
                // Initialize shaders and buffers
                const program = this.createProgram();
                this.gl.useProgram(program);
                
                // Set up attributes and uniforms
                this.positionBuffer = this.gl.createBuffer();
                this.intensityBuffer = this.gl.createBuffer();
                
                // Create transform feedback
                this.transformFeedback = this.gl.createTransformFeedback();
                this.gl.bindTransformFeedback(this.gl.TRANSFORM_FEEDBACK, this.transformFeedback);
            }

            updateData(activities) {
                const positions = new Float32Array(activities.length * 3);
                const intensities = new Float32Array(activities.length);
                
                activities.forEach((activity, i) => {
                    const idx = i * 3;
                    positions[idx] = activity.x;
                    positions[idx + 1] = activity.y;
                    positions[idx + 2] = this.is3D ? activity.value * 0.1 : 0;
                    intensities[i] = activity.intensity;
                });

                // Update buffers
                this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.positionBuffer);
                this.gl.bufferData(this.gl.ARRAY_BUFFER, positions, this.gl.DYNAMIC_DRAW);
                
                this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.intensityBuffer);
                this.gl.bufferData(this.gl.ARRAY_BUFFER, intensities, this.gl.DYNAMIC_DRAW);
            }

            render() {
                this.gl.clear(this.gl.COLOR_BUFFER_BIT | this.gl.DEPTH_BUFFER_BIT);
                
                // Apply view transformations
                if (this.is3D) {
                    const now = Date.now() * 0.001;
                    const rotation = now * 0.5;
                    this.updateViewMatrix(rotation);
                }
                
                // Draw points
                this.gl.drawArrays(this.gl.POINTS, 0, this.points.length);
                
                // Request next frame
                requestAnimationFrame(() => this.render());
            }

            toggle3DView() {
                this.is3D = !this.is3D;
                this.updateProjection();
            }
        }
        """

    async def update(self) -> Dict[str, Any]:
        """Get real-time activity data"""
        return {
            'activities': await self._get_activity_data()
        }

    async def _get_activity_data(self) -> List[ActivityPoint]:
        """Fetch activity data from various sources"""
        # Implementation details...
        pass
