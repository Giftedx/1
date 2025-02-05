
    varying vec3 vColor;
    void main() {
        vColor = color;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
    """

    FRAGMENT_SHADER = """
    precision mediump float;
    varying vec3 vColor;
    void main() {
        gl_FragColor = vec4(vColor, 1.0);
    }
    """

    @staticmethod
    def get_javascript() -> str:
        return """
        class NetworkFlow {
            constructor(containerId) {
                this.container = document.getElementById(containerId);
                this.scene = new THREE.Scene();
                this.camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
                this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
                this.nodes = new Map();
                this.edges = new Map();
                this.flowParticles = new Map();
                
                this.initRenderer();
                this.setupLights();
                this.setupControls();
                this.animate();
            }

            initRenderer() {
                this.renderer.setPixelRatio(window.devicePixelRatio);
                this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
                this.container.appendChild(this.renderer.domElement);
            }

            createNode(data) {
                const geometry = new THREE.SphereGeometry(0.5, 32, 32);
                const material = new THREE.MeshPhongMaterial({
                    color: this.getNodeColor(data.type),
                    emissive: this.getNodeColor(data.type),
                    emissiveIntensity: 0.2,
                    transparent: true,
                    opacity: 0.9
                });
                const node = new THREE.Mesh(geometry, material);
                node.position.set(data.x, data.y, data.z);
                this.scene.add(node);
                this.nodes.set(data.id, { mesh: node, data });
            }

            createFlowParticles(edge) {
                const points = new Float32Array(1000 * 3);
                const colors = new Float32Array(1000 * 3);
                const sizes = new Float32Array(1000);
                
                for (let i = 0; i < 1000; i++) {
                    const t = i / 1000;
                    points[i * 3] = edge.start.x * (1 - t) + edge.end.x * t;
                    points[i * 3 + 1] = edge.start.y * (1 - t) + edge.end.y * t;
                    points[i * 3 + 2] = edge.start.z * (1 - t) + edge.end.z * t;
                    
                    const color = this.getFlowColor(edge.data.type);
                    colors[i * 3] = color.r;
                    colors[i * 3 + 1] = color.g;
                    colors[i * 3 + 2] = color.b;
                    
                    sizes[i] = Math.random() * 2 + 1;
                }
                
                const geometry = new THREE.BufferGeometry();
                geometry.setAttribute('position', new THREE.BufferAttribute(points, 3));
                geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
                geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));
                
                const material = new THREE.ShaderMaterial({
                    uniforms: {
                        time: { value: 0 },
                        speed: { value: edge.data.throughput }
                    },
                    vertexShader: this.PARTICLE_VERTEX_SHADER,
                    fragmentShader: this.PARTICLE_FRAGMENT_SHADER,
                    transparent: true,
                    blending: THREE.AdditiveBlending
                });
                
                const particles = new THREE.Points(geometry, material);
                this.scene.add(particles);
                this.flowParticles.set(edge.id, particles);
            }

            updateFlow(data) {
                data.nodes.forEach(node => {
                    const nodeObj = this.nodes.get(node.id);
                    if (nodeObj) {
                        nodeObj.mesh.material.emissiveIntensity = 
                            0.2 + (node.throughput / 100) * 0.8;
                    }
                });

                data.edges.forEach(edge => {
                    const particles = this.flowParticles.get(edge.id);
                    if (particles) {
                        particles.material.uniforms.speed.value = edge.throughput;
                    }
                });
            }
        }
        """

    template = """
    <div class="network-flow-widget">
        <div class="flow-controls">
            <div class="btn-group">
                <button class="btn btn-sm btn-outline-primary" data-view="3d">3D View</button>
                <button class="btn btn-sm btn-outline-primary" data-view="top">Top View</button>
            </div>
            <div class="flow-legend"></div>
        </div>
        <div id="flow-container-{id}" class="flow-container"></div>
        <div class="flow-stats">
            <div class="stat-item">
                <span class="stat-label">Total Throughput</span>
                <span class="stat-value" id="total-throughput">0 Mbps</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Active Connections</span>
                <span class="stat-value" id="active-connections">0</span>
            </div>
        </div>
    </div>
    """