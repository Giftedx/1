from typing import Dict, Any, List
from .base_widget import BaseWidget, WidgetConfig
import numpy as np
from dataclasses import dataclass

@dataclass
class NetworkNode:
    id: str
    type: str
    connections: List[str]
    data_rate: float
    coordinates: tuple[float, float, float]

class NetworkFlowWidget(BaseWidget):
    VERTEX_SHADER = """
    precision highp float;
    attribute vec3 position;
    attribute vec3 color;
    uniform mat4 modelViewMatrix;
    uniform mat4 projectionMatrix;
    varying vec3 vColor;
    varying float vAlpha;
    
    void main() {
        vColor = color;
        vAlpha = position.z * 0.5 + 0.5;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = 10.0;
    }
    """

    FRAGMENT_SHADER = """
    precision highp float;
    varying vec3 vColor;
    varying float vAlpha;
    
    void main() {
        vec2 coord = gl_PointCoord - vec2(0.5);
        float r = length(coord) * 2.0;
        float a = 1.0 - smoothstep(0.8, 1.0, r);
        gl_FragColor = vec4(vColor, a * vAlpha);
    }
    """

    PARTICLE_VERTEX_SHADER = """
    precision highp float;
    attribute vec3 position;
    attribute float age;
    uniform float time;
    uniform mat4 modelViewMatrix;
    uniform mat4 projectionMatrix;
    varying float vAge;
    
    void main() {
        vAge = age;
        vec3 pos = position;
        // Add sine wave motion
        pos.y += sin(time * 2.0 + position.x) * 0.1;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
        gl_PointSize = mix(4.0, 1.0, age);
    }
    """

    FLOW_LINE_VERTEX_SHADER = """
    precision highp float;
    attribute vec3 position;
    attribute vec3 normal;
    uniform float time;
    uniform mat4 modelViewMatrix;
    uniform mat4 projectionMatrix;
    varying vec3 vNormal;
    
    void main() {
        vNormal = normal;
        vec3 pos = position;
        // Add flow effect
        pos += normal * sin(time * 3.0 + position.x * 2.0) * 0.05;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
    }
    """

    def __init__(self, config: WidgetConfig):
        super().__init__(config)
        self.nodes = []
        self.connections = []
        self.flow_particles = []

    def render(self) -> str:
        return """
        <div class="network-flow-widget" data-widget-id="{{ widget.id }}">
            <canvas id="flowCanvas-{{ widget.id }}" class="flow-canvas"></canvas>
            <div class="flow-controls">
                <div class="view-options btn-group">
                    <button class="btn btn-sm btn-outline-primary active" data-view="3d">3D</button>
                    <button class="btn btn-sm btn-outline-primary" data-view="2d">2D</button>
                </div>
                <div class="flow-legend"></div>
            </div>
            <div class="flow-stats">
                <div class="stat-group">
                    <span class="stat-label">Total Bandwidth</span>
                    <span class="stat-value" id="totalBandwidth">0 Mbps</span>
                </div>
            </div>
        </div>
        """

    def get_client_js(self) -> str:
        return """
        class NetworkFlow {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.canvas = this.container.querySelector('canvas');
                this.gl = this.canvas.getContext('webgl2');
                this.scene = new THREE.Scene();
                this.camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
                this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, alpha: true });
                
                this.setupScene();
                this.initializeShaders();
                this.createGeometry();
                this.animate();
            }
            
            setupScene() {
                this.scene.background = new THREE.Color(0x000919);
                this.camera.position.z = 5;
                
                // Add ambient and directional light
                const ambientLight = new THREE.AmbientLight(0x404040);
                const directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
                this.scene.add(ambientLight);
                this.scene.add(directionalLight);
                
                // Add grid helper
                const grid = new THREE.GridHelper(10, 10);
                grid.material.opacity = 0.2;
                grid.material.transparent = true;
                this.scene.add(grid);
            }

            updateFlows(data) {
                this.updateNodes(data.nodes);
                this.updateConnections(data.connections);
                this.updateParticles(data.flows);
            }

            updateNodes(nodes) {
                nodes.forEach(node => {
                    const nodeObj = this.nodes.get(node.id);
                    if (nodeObj) {
                        this.updateNodePosition(nodeObj, node);
                    } else {
                        this.createNode(node);
                    }
                });
            }

            createParticleSystem(connection) {
                const geometry = new THREE.BufferGeometry();
                const material = new THREE.ShaderMaterial({
                    uniforms: {
                        time: { value: 0 },
                        speed: { value: 1 },
                        color: { value: new THREE.Color(0x00ff00) }
                    },
                    vertexShader: this.PARTICLE_VERTEX_SHADER,
                    fragmentShader: this.PARTICLE_FRAGMENT_SHADER,
                    transparent: true,
                    blending: THREE.AdditiveBlending
                });
                
                return new THREE.Points(geometry, material);
            }

            animate() {
                requestAnimationFrame(() => this.animate());
                
                // Update particle positions
                this.updateParticlePositions();
                
                // Rotate camera slightly
                this.camera.position.x = Math.sin(Date.now() * 0.0001) * 5;
                this.camera.position.z = Math.cos(Date.now() * 0.0001) * 5;
                this.camera.lookAt(0, 0, 0);
                
                this.renderer.render(this.scene, this.camera);
            }

            setupEffects() {
                // Add bloom effect
                const bloomPass = new THREE.UnrealBloomPass(
                    new THREE.Vector2(window.innerWidth, window.innerHeight),
                    1.5, 0.4, 0.85
                );
                this.composer.addPass(bloomPass);

                // Add flow lines
                this.flowLines = this.createFlowLines();
                this.scene.add(this.flowLines);

                // Add particle systems
                this.particleSystems = new Map();
                this.setupParticleSystems();
            }

            createFlowLines() {
                const geometry = new THREE.BufferGeometry();
                const material = new THREE.ShaderMaterial({
                    uniforms: {
                        time: { value: 0 },
                        color: { value: new THREE.Color(0x00ff99) }
                    },
                    vertexShader: this.FLOW_LINE_VERTEX_SHADER,
                    fragmentShader: this.FLOW_LINE_FRAGMENT_SHADER,
                    transparent: true,
                    blending: THREE.AdditiveBlending
                });
                return new THREE.LineSegments(geometry, material);
            }

            updateFlowData(data) {
                this.updateNodes(data.nodes);
                this.updateConnections(data.connections);
                this.updateMetrics(data.metrics);
                this.updateTopology(data.topology);
                
                // Update particle systems
                data.flows.forEach(flow => {
                    this.updateParticleSystem(flow);
                });
                
                // Update flow lines
                this.updateFlowLines(data.topology.edges);
            }

            updateParticleSystem(flow) {
                const system = this.particleSystems.get(flow.id) || 
                    this.createParticleSystem(flow);
                
                const positions = this.calculateParticlePositions(flow);
                system.geometry.setAttribute(
                    'position',
                    new THREE.Float32BufferAttribute(positions, 3)
                );
                
                system.material.uniforms.speed.value = flow.rate / this.maxRate;
            }
        }
        """

    async def update(self) -> Dict[str, Any]:
        """Get real-time network flow data with enhanced metrics"""
        network_data = await self._get_network_data()
        return {
            'nodes': self._get_network_nodes(),
            'connections': self._get_connections(),
            'flows': await self._get_flow_data(),
            'metrics': {
                'bandwidth': network_data.get('bandwidth', 0),
                'latency': network_data.get('latency', 0),
                'packet_loss': network_data.get('packet_loss', 0),
                'jitter': network_data.get('jitter', 0)
            },
            'topology': {
                'nodes': self._format_topology_nodes(network_data.get('nodes', [])),
                'edges': self._format_topology_edges(network_data.get('edges', []))
            }
        }

    def _get_network_nodes(self) -> List[Dict[str, Any]]:
        """Get current network nodes and their states"""
        # Implementation details...
        pass

    def _format_topology_nodes(self, nodes: List[Dict]) -> List[Dict[str, Any]]:
        """Format topology nodes with enhanced metadata"""
        return [{
            'id': node['id'],
            'type': node['type'],
            'position': node.get('position', [0, 0, 0]),
            'load': node.get('load', 0),
            'status': node.get('status', 'active'),
            'metrics': {
                'cpu': node.get('cpu_usage', 0),
                'memory': node.get('memory_usage', 0),
                'connections': node.get('connection_count', 0)
            }
        } for node in nodes]
