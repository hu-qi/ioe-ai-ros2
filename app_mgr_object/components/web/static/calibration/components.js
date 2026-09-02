// components.js

// 状态徽章组件
class StatusBadge extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }
    
    static get observedAttributes() {
        return ['status', 'pulse'];
    }
    
    connectedCallback() {
        this.render();
    }
    
    attributeChangedCallback() {
        this.render();
    }
    
    render() {
        const status = this.getAttribute('status') || 'unknown';
        const pulse = this.hasAttribute('pulse');
        const statusMap = {
            running: { text: '● 运行中', class: 'running' },
            stopped: { text: '○ 已停止', class: 'stopped' },
            error: { text: '⚠ 错误', class: 'error' },
        };
        const { text, class: className } = statusMap[status] || { text: status, class: '' };
        
        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: inline-block;
                }
                .badge {
                    display: inline-flex;
                    align-items: center;
                    padding: 4px 12px;
                    border-radius: 9999px;
                    font-size: 0.875rem;
                    font-weight: 500;
                    background: rgba(255,255,255,0.05);
                    backdrop-filter: blur(8px);
                    border: 1px solid rgba(255,255,255,0.1);
                    transition: all 150ms;
                }
                .badge.running {
                    color: #10b981;
                    border-color: rgba(16, 185, 129, 0.3);
                    background: rgba(16, 185, 129, 0.1);
                }
                .badge.stopped {
                    color: #a0a0b0;
                }
                .badge.error {
                    color: #ef4444;
                    border-color: rgba(239, 68, 68, 0.3);
                }
                .pulse {
                    animation: pulse 2s infinite;
                }
                @keyframes pulse {
                    0% { opacity: 1; }
                    50% { opacity: 0.6; }
                    100% { opacity: 1; }
                }
            </style>
            <span class="badge ${className} ${pulse ? 'pulse' : ''}">${text}</span>
        `;
    }
}

// 应用头部组件
class AppHeader extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }
    
    connectedCallback() {
        const title = this.getAttribute('title') || '推理节点管理系统';
        const showNav = this.hasAttribute('show-nav');
        const activePage = this.getAttribute('active') || 'canvas';
        
        this.shadowRoot.innerHTML = `
            <style>
                .header-inner {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 16px 24px;
                    background: rgba(30, 30, 40, 0.7);
                    backdrop-filter: blur(12px);
                    border-radius: 16px;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    box-shadow: 0 4px 8px rgba(0,0,0,0.4);
                }
                h1 {
                    font-size: 1.5rem;
                    font-weight: 600;
                    margin: 0;
                    background: linear-gradient(135deg, #fff, #a0a0b0);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                }
                .nav-links {
                    display: flex;
                    gap: 16px;
                }
                .nav-link {
                    color: #a0a0b0;
                    text-decoration: none;
                    padding: 8px 16px;
                    border-radius: 8px;
                    transition: all 150ms;
                    font-weight: 500;
                }
                .nav-link:hover {
                    color: #fff;
                    background: rgba(255,255,255,0.05);
                }
                .nav-link.active {
                    color: #3b82f6;
                    background: rgba(59,130,246,0.1);
                    border-bottom: 2px solid #3b82f6;
                }
                .logout-btn {
                    background: #ef4444;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 8px;
                    border: none;
                    cursor: pointer;
                    font-weight: 500;
                    transition: all 150ms;
                    display: inline-flex;
                    align-items: center;
                    gap: 4px;
                }
                .logout-btn:hover {
                    background: #dc2626;
                    transform: translateY(-1px);
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                }
            </style>
            <div class="header-inner">
                <h1>${title}</h1>
                <div style="display: flex; align-items: center; gap: 20px;">
                    ${showNav ? `
                        <div class="nav-links">
                            <a href="/canvas" class="nav-link ${activePage === 'canvas' ? 'active' : ''}">区域标定</a>
                           
                            <!-- <a href="/params" class="nav-link ${activePage === 'params' ? 'active' : ''}">参数配置</a> -->
                        </div>
                    ` : ''}
                    <button id="logoutBtn" class="logout-btn">🚪 登出</button>
                </div>
            </div>
        `;
        
        // 绑定登出事件
        const logoutBtn = this.shadowRoot.getElementById('logoutBtn');
        logoutBtn.addEventListener('click', async () => {
            await fetch('/api/logout', { method: 'POST' });
            sessionStorage.removeItem('authenticated');
            window.location.href = '/login';
        });
    }
}

customElements.define('status-badge', StatusBadge);
customElements.define('app-header', AppHeader);