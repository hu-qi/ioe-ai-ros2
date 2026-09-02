class CalibrationTool {
    constructor() {        
        
        this.channelCount = 2;  // 默认双路
        this.currentChannel = 0;
        this.viewMode = 'dual'; // 'dual' | 'single'
        this.fullscreenChannel = 0;
        
        // ChannelCanvas 实例数组
        this.channelCanvases = [];
        
        // 保存相关的状态管理
        this.isSaving = false;
        this.saveDebounceTimer = null;
        this.lastSavedAreas = null;
        this.hasUnsavedChanges = false;
        this.SAVE_DEBOUNCE_DELAY = 500;
        this.saveRetryCount = 0;
        this.MAX_SAVE_RETRY = 2;
        this.DOUBLE_CONFIRM_ENABLED = true;
        
        // DOM 元素引用
        this.canvasContainer = document.getElementById('canvasContainer');
        this.closeFullscreenBtn = document.getElementById('closeFullscreen');
        this.fullscreenHint = document.getElementById('fullscreenHint');
        this.channelSelect = document.getElementById('channelSelect');
        this.drawModeSelect = document.getElementById('drawMode');
        this.statusSpan = document.getElementById('status');
        this.areaListEl = document.getElementById('areaList');
        this.panModeBtn = document.getElementById('panModeBtn');
        
        this.debugToggleCheckbox = document.getElementById('debugToggleCheckbox');        
        
        this.panMode = true;   // 默认查看模式
        this.debugImageEnabled = false;       // 当前调试图像发布状态

        this.wsStatus = {};                     // 记录各通道 WS 连接状态
        // for (let i = 0; i < 2; i++) this.wsStatus[i] = false;
        this.wsStatusDisplay = document.getElementById('wsStatusDisplay');

        this.init();
    }
    
    async init() {
        this.panMode = true;
        await this.loadChannelCount();
        this.wsStatus = {};
        for (let i = 0; i < this.channelCount; i++) this.wsStatus[i] = false;
        this.setupCanvas();
        this.setupEventListeners();
        await this.updateChannelSelectOptions();
        await this.loadDebugImageStatus();
        
        // 加载各通道区域
        // for (let i = 0; i < this.channelCount; i++) {
        //     await this.channelCanvases[i].loadAreas();
        // }
        this.lastSavedAreas = this.areasToString();
        this.clearUnsavedChanges();
        
        // 连接 WebSocket
        this.channelCanvases.forEach(ch => ch.connectWebSocket());
        
        // 开始帧循环        
        // this.startFrameRefresh();
        this.updatePanModeUI();
        this.updateDebugToggleUI();
    }

    refreshFrames() {
        const btn = document.getElementById('refreshBtn');
        if (btn) {
            btn.textContent = '⏳ 刷新中...';
            btn.disabled = true;
        }
    
        this.channelCanvases.forEach(ch => {
            ch.frameImage = new Image();
            const ctx = ch.ctx;
            ctx.clearRect(0, 0, ch.canvas.width, ch.canvas.height);
            ctx.fillStyle = '#111';
            ctx.fillRect(0, 0, ch.canvas.width, ch.canvas.height);
            ctx.fillStyle = '#888';
            ctx.font = '20px Arial';
            ctx.textAlign = 'center';
            ctx.fillText('正在等待新帧...', ch.canvas.width / 2, ch.canvas.height / 2);
        });
    
        this.setStatus('画面已刷新，等待新帧...', 'blue');
    
        // 1.5 秒后恢复按钮状态
        setTimeout(() => {
            if (btn) {
                btn.textContent = '🔄 刷新画面';
                btn.disabled = false;
                console.log('refreshBtn restored');
            }
        }, 1500);
    }

    setWsStatus(channelId, connected) {
        if (this.wsStatus[channelId] === connected) return;
        this.wsStatus[channelId] = connected;
        this.updateWsStatusDisplay();
    }
    
    updateWsStatusDisplay() {
        if (!this.wsStatusDisplay) return;
        let html = '';
        for (let i = 0; i < this.channelCount; i++) {
            const status = this.wsStatus[i] ? '🟢' : '🔴';
            html += `通道${i}:${status} `;
        }
        this.wsStatusDisplay.innerHTML = html;
    }


    updateDelayDisplay(delayMs) {
        const elem = document.getElementById('delayDisplay');
        if (!elem) return;
        elem.textContent = `延迟: ${delayMs.toFixed(0)} ms`;
        if (delayMs < 200) {
            elem.style.color = '#10b981';
        } else if (delayMs < 500) {
            elem.style.color = '#f59e0b';
        } else {
            elem.style.color = '#ef4444';
        }
    }


    async loadDebugImageStatus() {
        try {
            const resp = await fetch('/api/calibration/inference_param/publish_debug_image_enabled');
            if (!resp.ok) {
                throw new Error('Failed to fetch status');
            }
            const data = await resp.json();
            // 将字符串 "true"/"false" 或布尔值统一转换为布尔值
            this.debugImageEnabled = (data.value === true || data.value === 'true');
            console.log('Debug image status loaded:', this.debugImageEnabled);
        } catch (e) {
            console.warn('Failed to load debug image status, retrying...', e);
            // 失败后等待 2 秒重试一次
            setTimeout(() => this.loadDebugImageStatus(), 2000);
            return;
        }
        this.updateDebugToggleUI();
    }


    updateDebugToggleUI() {
        const checkbox = this.debugToggleCheckbox;
        if (!checkbox) return;
        checkbox.checked = this.debugImageEnabled;
        if (!this.debugImageEnabled) {
            this.setStatus('提示：视频流未发布，请开启“视频发布”开关以显示画面', 'orange');
        }
    }

    applyVideoPublishState() {
        this.channelCanvases.forEach(ch => {
            if (!this.debugImageEnabled) {
                // 视频已关闭：清空画布并显示提示
                const ctx = ch.ctx;
                ctx.clearRect(0, 0, ch.canvas.width, ch.canvas.height);
                ctx.fillStyle = '#111';
                ctx.fillRect(0, 0, ch.canvas.width, ch.canvas.height);
                ctx.fillStyle = '#888';
                ctx.font = '20px Arial';
                ctx.textAlign = 'center';
                ctx.fillText('视频流已关闭', ch.canvas.width / 2, ch.canvas.height / 2);
            } else {
                // 视频已开启：请求重绘（等待 WebSocket 新帧）
                ch.redirectDraw();
            }
        });
    }


    async toggleDebugPublish() {
        const newVal = !this.debugImageEnabled;
        try {
            const resp = await fetch('/api/calibration/set_param', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: 'publish_debug_image_enabled', value: newVal })
            });
            const result = await resp.json();
            if (result.status === 'success') {
                this.debugImageEnabled = newVal;
                this.updateDebugToggleUI();
                this.applyVideoPublishState();       // 新增：根据状态控制画布
                this.setStatus(newVal ? '视频发布已开启' : '视频发布已关闭', 'green');
            } else {
                // 失败时恢复开关状态
                this.debugToggleCheckbox.checked = this.debugImageEnabled;
                this.setStatus('切换失败: ' + (result.error || ''), 'red');
            }
        } catch (e) {
            this.debugToggleCheckbox.checked = this.debugImageEnabled;
            this.setStatus('切换失败: 网络错误', 'red');
        }
    }
    
    async loadChannelCount() {
        try {
            const resp = await fetch('/api/calibration/channel_count');
            const data = await resp.json();
            this.channelCount = data.count || 2;      // 不再限制最大为2
        } catch (e) {
            console.warn('Failed to get channel count, using default 2');
        }
    }
    
    setupCanvas() {
        // 清空容器
        this.canvasContainer.innerHTML = '';
        this.channelCanvases = [];
    
        // 根据通道数确定列数
        let cols = 2;
        if (this.channelCount <= 2) cols = 2;
        else if (this.channelCount <= 4) cols = 2;
        else if (this.channelCount <= 6) cols = 3;
        else cols = 4;
    
        this.gridCols = cols;   // 保存列数，用于全屏恢复
    
        // 设置 Grid 布局
        this.canvasContainer.style.display = 'grid';
        this.canvasContainer.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
        this.canvasContainer.style.gap = '4px';
    
        for (let i = 0; i < this.channelCount; i++) {
            const wrapper = document.createElement('div');
            wrapper.className = 'canvas-wrapper';
            wrapper.style.position = 'relative';
            wrapper.style.display = '';          // 由 Grid 控制显示
            wrapper.style.width = '100%';        // 撑满格子
    
            const canvas = document.createElement('canvas');
            canvas.className = 'channel-canvas';
            canvas.id = 'canvas' + i;
            canvas.dataset.channel = i;
            canvas.width = 1280;
            canvas.height = 720;
            wrapper.appendChild(canvas);
    
            // 右下角放大按钮
            const btn = document.createElement('button');
            btn.className = 'toggle-fullscreen-btn';
            btn.id = 'toggleBtn' + i;
            btn.textContent = '🔍';
            btn.title = '放大画面';
            btn.addEventListener('click', (e) => {
                if (this.viewMode === 'dual') {
                    this.enterFullscreen(i);
                } else if (this.viewMode === 'single' && this.fullscreenChannel === i) {
                    this.exitFullscreen();
                }
            });
            wrapper.appendChild(btn);
    
            this.canvasContainer.appendChild(wrapper);
    
            const chCanvas = new ChannelCanvas(i, canvas, this);
            this.channelCanvases.push(chCanvas);
        }
    
        // 重新绑定关闭按钮
        this.closeFullscreenBtn = document.getElementById('closeFullscreen');
        if (this.closeFullscreenBtn) {
            this.closeFullscreenBtn.addEventListener('click', () => this.exitFullscreen());
        }
        this.fullscreenHint = document.getElementById('fullscreenHint');
    }
    
    enterFullscreen(channelId) {
        if (this.viewMode === 'single') return;
        this.viewMode = 'single';
        this.fullscreenChannel = channelId;
        this.currentChannel = channelId;
        this.updateChannelSelect();
    
        // 保存当前的 grid 列数，并临时改为单列
        this._savedGridCols = this.gridCols;
        this.canvasContainer.style.gridTemplateColumns = '1fr';
    
        this.canvasContainer.classList.add('fullscreen-single');
        document.querySelectorAll('.canvas-wrapper').forEach((w, idx) => {
            w.classList.toggle('hidden', idx !== channelId);
        });
    
        if (this.closeFullscreenBtn) this.closeFullscreenBtn.style.display = 'block';
        if (this.fullscreenHint) this.fullscreenHint.style.display = 'block';
    
        // 更新按钮图标
        const btn = document.getElementById('toggleBtn' + channelId);
        if (btn) {
            btn.textContent = '🔎';
            btn.title = '退出全屏';
        }
    
        this.channelCanvases[channelId].redirectDraw();
        this.updateAreaListForChannel(channelId);
    }
    
    exitFullscreen() {
        if (this.viewMode === 'dual') return;
    
        // 恢复全屏通道按钮图标
        const btn = document.getElementById('toggleBtn' + this.fullscreenChannel);
        if (btn) {
            btn.textContent = '🔍';
            btn.title = '放大画面';
        }
    
        this.viewMode = 'dual';
        this.canvasContainer.classList.remove('fullscreen-single');
        document.querySelectorAll('.canvas-wrapper').forEach(w => w.classList.remove('hidden'));
        if (this.closeFullscreenBtn) this.closeFullscreenBtn.style.display = 'none';
        if (this.fullscreenHint) this.fullscreenHint.style.display = 'none';
    
        // 恢复 grid 列数
        this.canvasContainer.style.gridTemplateColumns = `repeat(${this._savedGridCols || 2}, 1fr)`;
    
        this.currentChannel = parseInt(this.channelSelect.value);
        this.updateAreaListForChannel(this.currentChannel);
    }
    
    updateChannelSelectOptions() {
        this.channelSelect.innerHTML = '';
        for (let i = 0; i < this.channelCount; i++) {
            const option = document.createElement('option');
            option.value = i;
            option.textContent = `通道 ${i}`;
            this.channelSelect.appendChild(option);
        }
        this.channelSelect.value = this.currentChannel;
    }
    
    updateChannelSelect() {
        this.channelSelect.value = this.currentChannel;
    }
    
    // 获取当前编辑通道的区域数据（来自对应 ChannelCanvas）
    getCurrentAreas() {
        return this.channelCanvases[this.currentChannel].areas;
    }
    
    setCurrentAreas(areas) {
        this.channelCanvases[this.currentChannel].areas = areas;
    }
    
    // 将当前所有区域转为字符串（用于比较变化）
    areasToString() {
        return JSON.stringify(this.channelCanvases.map(ch => ch.areas));
    }
    
    // 标记未保存变化
    markUnsavedChanges() {
        if (!this.hasUnsavedChanges) {
            this.hasUnsavedChanges = true;
            this.updateSaveButtonState();
        }
    }
    
    clearUnsavedChanges() {
        if (this.hasUnsavedChanges) {
            this.hasUnsavedChanges = false;
            this.updateSaveButtonState();
        }
    }
    
    updateSaveButtonState() {
        const saveBtn = document.getElementById('saveBtn');
        if (saveBtn) {
            if (this.hasUnsavedChanges) {
                saveBtn.style.background = '#4caf50';
                saveBtn.textContent = '保存配置 *';
            } else {
                saveBtn.style.background = '#2d2d2d';
                saveBtn.textContent = '保存配置';
            }
        }
    }
    
    // 缩略图刷新定时器（不再需要推送，WebSocket 直接更新帧）
    // startFrameRefresh() {
    //     setInterval(() => {
    //         this.channelCanvases.forEach(ch => {
    //             if (ch.frameImage.complete) {
    //                 ch.drawCanvas();
    //             }
    //         });
    //     }, 100);
    // }

    startFrameRefresh() {
        // 已废弃，由 WebSocket 消息驱动绘制
    }
    
    // ==================== 多边形保存逻辑（复用原有双重确认） ====================
    async doSingleSave() {
        const data = {
            channel_id: this.currentChannel,
            areas: this.getCurrentAreas()
        };
        
        try {
            const resp = await fetch('/api/calibration/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await resp.json();
            return result.status === 'success';
        } catch (e) {
            console.error('Save request failed:', e);
            return false;
        }
    }
    
    async saveCalibrationWithDoubleConfirm(immediate = true) {
        if (!immediate) {
            if (this.saveDebounceTimer) clearTimeout(this.saveDebounceTimer);
            this.saveDebounceTimer = setTimeout(() => this.saveCalibrationWithDoubleConfirm(true), this.SAVE_DEBOUNCE_DELAY);
            this.setStatus('修改已记录，稍后自动保存...', 'orange');
            return;
        }
    
        if (this.isSaving) return;
    
        const currentAreasStr = JSON.stringify(this.getCurrentAreas());
        const lastSavedStr = JSON.stringify(this.lastSavedAreas?.[this.currentChannel]);
        if (currentAreasStr === lastSavedStr) {
            this.setStatus('配置未变化', 'blue');
            this.clearUnsavedChanges();
            return;
        }
    
        this.isSaving = true;
        this.saveRetryCount = 0;
        let success = false;
    
        while (this.saveRetryCount <= this.MAX_SAVE_RETRY && !success) {
            this.setStatus(`正在保存... (${this.saveRetryCount + 1})`, 'orange');
            success = await this.doSingleSave();
            if (success) break;
            this.saveRetryCount++;
            if (this.saveRetryCount <= this.MAX_SAVE_RETRY) await this.sleep(500);
        }
    
        if (success && this.DOUBLE_CONFIRM_ENABLED) {
            this.setStatus('保存成功，正在确认...', 'orange');
            await this.sleep(300);
            await this.doSingleSave();
            await this.sleep(200);
        }
    
        if (success) {
            // ======= 关键修改：从推理节点重新加载最新区域 =======
            try {
                const resp = await fetch(`/api/calibration/areas/${this.currentChannel}`);
                const data = await resp.json();
                if (data.areas && Array.isArray(data.areas)) {
                    const ch = this.channelCanvases[this.currentChannel];
                    // 深拷贝新区域，避免引用问题
                    ch.areas = JSON.parse(JSON.stringify(data.areas));
                    ch.selectedAreaIndex = -1;
                    this.updateAreaListForChannel(this.currentChannel);
                    // 强制重绘两次，确保边界清除
                    ch.redirectDraw();
                    // 使用 requestAnimationFrame 确保在当前帧结束前再次绘制
                    requestAnimationFrame(() => {
                        ch.redirectDraw();
                        console.log('Areas updated and redrawn:', ch.areas);
                    });
                } else {
                    console.warn('Loaded areas is empty or invalid', data);
                }
            } catch (e) {
                console.error('重新加载区域失败:', e);
                this.setStatus('区域刷新失败', 'red');
            }
    
            this.lastSavedAreas = this.areasToString();
            this.clearUnsavedChanges();
            this.setStatus('保存成功，推理节点已更新', 'green');
        } else {
            this.setStatus('保存失败，请重试', 'red');
        }
        this.isSaving = false;
    }
    
    async forceSave() {
        // 清除防抖定时器，立即执行保存
        if (this.saveDebounceTimer) {
            clearTimeout(this.saveDebounceTimer);
            this.saveDebounceTimer = null;
        }
        // 直接调用统一保存入口，forceSave 不再重复实现
        await this.saveCalibrationWithDoubleConfirm(true);
    }

    _shouldShowAreaList() {
        // 只在单路全屏、编辑模式开启、且非查看模式时显示区域列表
        return this.viewMode === 'single' && !this.readOnly && !this.panMode;
    }
    
    // 区域列表更新（显示当前通道）
    updateAreaListForChannel(channelId) {
        if (!this.areaListEl) return;

        // 不满足显示条件时清空列表并返回
        if (!this._shouldShowAreaList()) {
            this.areaListEl.innerHTML = '';
            return;
        }

        const areas = this.channelCanvases[channelId].areas;
        this.areaListEl.innerHTML = '';
        areas.forEach((area, idx) => {
            const li = document.createElement('li');
            li.style.background = idx === this.channelCanvases[channelId].selectedAreaIndex ? '#3a3a5a' : 'transparent';
            li.innerHTML = `
                <span class="area-name">${area.name} (${area.type})</span>
                <div>
                    <button data-idx="${idx}" class="selectArea">选中</button>
                    <button data-idx="${idx}" class="deleteArea">删除</button>
                </div>
            `;
            this.areaListEl.appendChild(li);
        });
        
        // 绑定按钮事件
        document.querySelectorAll('.selectArea').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(e.target.dataset.idx);
                this.channelCanvases[channelId].selectedAreaIndex = idx;
                this.updateAreaListForChannel(channelId);
                this.channelCanvases[channelId].drawCanvas();
            });
        });
        document.querySelectorAll('.deleteArea').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(e.target.dataset.idx);
                this.deleteArea(channelId, idx);
            });
        });
    }
    
    deleteArea(channelId, index) {
        const ch = this.channelCanvases[channelId];
        if (index >= 0 && index < ch.areas.length) {
            ch.areas.splice(index, 1);
            if (ch.selectedAreaIndex === index) ch.selectedAreaIndex = -1;
            else if (ch.selectedAreaIndex > index) ch.selectedAreaIndex--;
            this.updateAreaListForChannel(channelId);
            ch.drawCanvas();
            this.markUnsavedChanges();
            this.forceSave();
        }
    }
    
    setStatus(text, color) {
        if (this.statusSpan) {
            this.statusSpan.textContent = text;
            this.statusSpan.style.color = color;
            if (color === 'green' || color === 'blue') {
                setTimeout(() => { if (this.statusSpan.textContent === text) this.statusSpan.textContent = ''; }, 3000);
            }
        }
    }
    
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
    
    // ==================== 事件监听设置 ====================
    setupEventListeners() {
        // 通道下拉框
        this.channelSelect.addEventListener('change', (e) => {
            this.currentChannel = parseInt(e.target.value);
            this.updateAreaListForChannel(this.currentChannel);
        });
        
        // 绘制模式选择
        this.drawModeSelect.addEventListener('change', (e) => {
            if (this.panMode && e.target.value !== 'select') {
                this.drawModeSelect.value = 'select';
                this.setStatus('查看模式下只能使用“选择”模式', 'orange');
            }
            // 将绘制模式传递给当前编辑通道
            this.channelCanvases[this.currentChannel].drawMode = this.drawModeSelect.value;
        });


        this.debugToggleCheckbox.addEventListener('change', () => {
            // 防止在更新UI时循环触发
            if (this.debugToggleCheckbox.checked !== this.debugImageEnabled) {
                this.toggleDebugPublish();
            }
        });
        
        // 查看/绘制按钮
        this.panModeBtn.addEventListener('click', () => {
            this.panMode = !this.panMode;
            this.updatePanModeUI();
            // 更新当前通道的查看模式
            this.channelCanvases[this.currentChannel].setPanMode(this.panMode);
        });
        
        // 清空按钮
        document.getElementById('clearBtn').addEventListener('click', () => {
            const ch = this.channelCanvases[this.currentChannel];
            if (ch.areas.length > 0 && confirm('确定清空当前通道的所有区域？')) {
                ch.areas = [];
                ch.selectedAreaIndex = -1;
                ch.clearDrawingState();
                this.updateAreaListForChannel(this.currentChannel);
                ch.drawCanvas();
                this.markUnsavedChanges();
                this.forceSave();
            }
        });
        
        // 保存按钮
        document.getElementById('saveBtn').addEventListener('click', () => this.forceSave());

        
        // 刷新按钮
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.refreshFrames();
            });
        } else {
            console.warn('refreshBtn not found in DOM');
        }
        
        // 加载按钮
        document.getElementById('loadBtn').addEventListener('click', async () => {
            if (this.hasUnsavedChanges && !confirm('当前有未保存的修改，重新加载将丢失修改。是否继续？')) return;
            // 改为从推理节点获取最新区域
            const ch = this.channelCanvases[this.currentChannel];
            try {
                // 调用 ChannelCanvas 的统一加载方法（内部调用 redirectDraw）
                await ch.loadAreas();
            } catch (e) {
                console.error('Failed to load areas from inference node', e);
                this.setStatus('加载区域失败', 'red');
                return;
            }
            this.lastSavedAreas = this.areasToString();
            this.clearUnsavedChanges();
            this.updateAreaListForChannel(this.currentChannel);
            // this.channelCanvases[this.currentChannel].drawCanvas();
            this.setStatus('已从推理节点加载配置', 'blue');
        });
        
        // 关闭全屏按钮已在 setupCanvas 中绑定
        // 键盘快捷键
        window.addEventListener('keydown', (e) => {
            const ch = this.channelCanvases[this.currentChannel];
            if (e.key === 'Escape') {
                if (this.viewMode === 'single') {
                    this.exitFullscreen();
                } else {
                    ch.clearDrawingState();
                    ch.drawCanvas();
                    this.setStatus('绘制已取消', 'gray');
                }
            } else if (e.key === 'Delete' && ch.selectedAreaIndex >= 0) {
                this.deleteArea(this.currentChannel, ch.selectedAreaIndex);
            } else if (e.ctrlKey && e.key === 's') {
                e.preventDefault();
                this.forceSave();
            }
        });
        
        window.addEventListener('beforeunload', (e) => {
            if (this.hasUnsavedChanges) {
                e.preventDefault();
                e.returnValue = '您有未保存的修改，确定要离开吗？';
            }
        });
    }
    
    updatePanModeUI() {
        if (this.panModeBtn) {
            this.panModeBtn.innerHTML = this.panMode ? '➡️ 绘制' : '🖐️ 查看';
            this.panModeBtn.title = this.panMode ? '切换到绘制模式' : '切换到查看握模式（仅选择/拖动）';
        }
        if (this.panMode && this.drawModeSelect.value !== 'select') {
            this.drawModeSelect.value = 'select';
        }
        // 同步所有通道的 panMode
        this.channelCanvases.forEach(ch => ch.setPanMode(this.panMode));

        this.updateAreaListForChannel(this.currentChannel);   // 刷新区域列表
    }
}

// ==================== ChannelCanvas 类 ====================
class ChannelCanvas {
    constructor(channelId, canvas, tool) {
        this.channelId = channelId;
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.tool = tool; // CalibrationTool 引用
        
        this.ws = null;
        this.frameImage = new Image();
        this.areas = [];
        this.videoWidth = 1280;
        this.videoHeight = 720;
        
        // 绘制与交互状态
        this.drawMode = 'polygon';
        this.panMode = false;
        this.isDrawing = false;
        this.currentPolygon = [];
        this.tempPoint = null;
        this.rectStart = null;
        this.rectEnd = null;
        this.selectedAreaIndex = -1;
        this.draggedPoint = null;
        this.isDragging = false;
        this.hoveredPoint = null;
        this.dragOffset = { x: 0, y: 0 };
        this.POINT_RADIUS = 8;
        this.CLOSE_THRESHOLD = 15;
        this.ADSORB_THRESHOLD = 12;  // 吸附阈值

        this._latestFrameTs = null; 
        
        this.bindEvents();
    }

    // 统一绘制分流
    redirectDraw() {
        if (this.panMode) {
            this.drawFrameOnly();
        } else {
            this.drawCanvas();
        }
    }
    
    bindEvents() {
        this.canvas.addEventListener('mousedown', this.onMouseDown.bind(this));
        this.canvas.addEventListener('mousemove', this.onMouseMove.bind(this));
        this.canvas.addEventListener('mouseup', this.onMouseUp.bind(this));
        this.canvas.addEventListener('dblclick', this.onDoubleClick.bind(this));
        this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    }
    
    // 设置查看模式
    setPanMode(pan) {
        this.panMode = pan;
        if (pan && this.drawMode !== 'select') {
            this.drawMode = 'select';
        }
        this.clearDrawingState();
        // 如果切换到箭头模式（绘制），且尚未加载过区域，则自动加载
        if (!this.panMode && this.areas.length === 0) {
            this.loadAreas();
        } else {
            this.redirectDraw();
        }
    }
    
     // 加载区域，但不直接绘制，使用 redirectDraw
    async loadAreas() {
        try {
            const resp = await fetch(`/api/calibration/areas/${this.channelId}`);
            const data = await resp.json();
            this.areas = data.areas || [];
            this.redirectDraw();   // 根据当前模式绘制
        } catch (e) {
            console.error('Failed to load areas', e);
        }
    }
   


    // 纯图像绘制（查看模式）
    drawFrameOnly() {
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        if (this.frameImage.complete && this.frameImage.naturalWidth > 0) {
            ctx.drawImage(this.frameImage, 0, 0, this.canvas.width, this.canvas.height);
        }
    }
    
    connectWebSocket() {
        if (this.ws) {
            this.ws.onclose = null;
            this.ws.close();
        }
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/calibration/${this.channelId}`;
        this.ws = new WebSocket(wsUrl);
        
        // 设置为blob以直接处理JPEG数据（与原有保持一致）
        this.ws.binaryType = 'blob';
        
        // 接收消息处理
        this.ws.onmessage = (event) => {
            // 区分文本和二进制消息
            if (typeof event.data === 'string') {
                try {
                    const meta = JSON.parse(event.data);                    

                    // ----------  frame_meta 处理 ----------
                    if (meta.type === 'frame_meta') {
                        this._latestFrameTs = meta.ts;   // 存储图像原始时间戳
                        if (meta.original_width && meta.original_height) {
                            this.originalWidth = meta.original_width;
                            this.originalHeight = meta.original_height;
                        }
                        // 根据图像源头时间戳和客户端当前时间计算延迟                        
                        const now = Date.now() / 1000;
                        const delayMs = Math.max(0, (now - meta.ts) * 1000);
                        this.tool.updateDelayDisplay(delayMs);
                    }
                } catch (e) {
                    console.warn('Invalid JSON from WebSocket:', e);
                }
            } else if (event.data instanceof Blob) {
                if (!this.tool.debugImageEnabled) return;

                const url = URL.createObjectURL(event.data);
                this.frameImage.onload = () => {
                    this.videoWidth = this.frameImage.width;
                    this.videoHeight = this.frameImage.height;
                    this.canvas.width = this.videoWidth;
                    this.canvas.height = this.videoHeight;
                    requestAnimationFrame(() => this.redirectDraw());
                    URL.revokeObjectURL(url);
                };
                this.frameImage.onerror = () => URL.revokeObjectURL(url);
                this.frameImage.src = url;
            }
        };
    
        this.ws.onopen = () => {
            console.log(`Channel ${this.channelId} WebSocket connected`);
            if (this.tool) this.tool.setWsStatus(this.channelId, true);
        };
        this.ws.onclose = (event) => {
            if (this.tool) this.tool.setWsStatus(this.channelId, false);
            if (event.code !== 1000) {
                console.log(`Channel ${this.channelId} WebSocket closed unexpectedly, reconnecting...`);
                setTimeout(() => this.connectWebSocket(), 3000);
            }
        };
        this.ws.onerror = (err) => {
            console.error(`Channel ${this.channelId} WebSocket error`, err);
            if (this.tool) this.tool.setWsStatus(this.channelId, false);
        };
    }


    getDisplayChannelId() {
        // 返回当前正在显示的通道 ID（全屏或所选）
        return this.viewMode === 'single' ? this.fullscreenChannel : this.currentChannel;
    }
    
    
    
    // 完整绘制（绘制模式），使用原始坐标
    drawCanvas() {
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;
        ctx.clearRect(0, 0, w, h);
        // 确保图像存在且尺寸匹配
        if (this.frameImage.complete && this.frameImage.naturalWidth > 0) {
            ctx.drawImage(this.frameImage, 0, 0, w, h);
        } else {
            ctx.fillStyle = '#111';
            ctx.fillRect(0, 0, w, h);
        }
        // 绘制多边形
        this.areas.forEach((area, idx) => this.drawArea(area, idx));
        this.drawCurrentShape();
        this.drawHoveredPoint();
    }


    
    
    drawArea(area, idx) {
        const ctx = this.ctx;
        const isSelected = idx === this.selectedAreaIndex;
        const color = this.getAreaColor(idx);
        ctx.strokeStyle = isSelected ? '#ffffff' : color;
        ctx.fillStyle = color + '30';
        ctx.lineWidth = isSelected ? 3 : 2;
        
        if (area.type === 'polygon' || area.type === 'rectangle') {
            // 绘制轮廓
            ctx.beginPath();
            area.points.forEach((pt, i) => {
                if (i === 0) ctx.moveTo(pt[0], pt[1]);
                else ctx.lineTo(pt[0], pt[1]);
            });
            ctx.closePath();
            ctx.fill();
            ctx.stroke();
            
            // 绘制顶点
            area.points.forEach(pt => {
                ctx.fillStyle = isSelected ? '#ffff00' : color;   // 选中时黄色
                ctx.beginPath();
                ctx.arc(pt[0], pt[1], isSelected ? 6 : 4, 0, 2*Math.PI); // 半径加大
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 1;
                ctx.stroke();
            });
        } else if (area.type === 'line' && area.points.length >= 2) {
            ctx.beginPath();
            ctx.moveTo(area.points[0][0], area.points[0][1]);
            ctx.lineTo(area.points[1][0], area.points[1][1]);
            ctx.strokeStyle = isSelected ? '#ffffff' : color;
            ctx.lineWidth = isSelected ? 4 : 3;
            ctx.stroke();
            area.points.forEach(pt => {
                ctx.fillStyle = isSelected ? '#ffff00' : color;
                ctx.beginPath();
                ctx.arc(pt[0], pt[1], isSelected ? 6 : 5, 0, 2*Math.PI);
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 1;
                ctx.stroke();
            });
        }
    }


       


    drawCurrentShape() {
        const ctx = this.ctx;
        if (this.drawMode === 'polygon' && this.isDrawing) {
            ctx.strokeStyle = '#ffaa00';
            ctx.fillStyle = '#ffaa0020';
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 5]);
            ctx.beginPath();
            this.currentPolygon.forEach((pt, i) => {
                if (i === 0) ctx.moveTo(pt.x, pt.y);
                else ctx.lineTo(pt.x, pt.y);
            });
            if (this.tempPoint) ctx.lineTo(this.tempPoint.x, this.tempPoint.y);
            ctx.stroke();
            ctx.setLineDash([]);
            this.currentPolygon.forEach((pt, i) => {
                ctx.fillStyle = i === 0 ? '#00ff00' : '#ffaa00';
                ctx.beginPath();
                ctx.arc(pt.x, pt.y, 5, 0, 2*Math.PI);
                ctx.fill();
                ctx.strokeStyle = '#000';
                ctx.lineWidth = 1;
                ctx.stroke();
            });
        } else if (this.drawMode === 'rectangle' && this.isDrawing && this.rectStart && this.rectEnd) {
            ctx.strokeStyle = '#00ff00';
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 5]);
            ctx.strokeRect(this.rectStart.x, this.rectStart.y, this.rectEnd.x - this.rectStart.x, this.rectEnd.y - this.rectStart.y);
            ctx.setLineDash([]);
        } else if (this.drawMode === 'line' && this.isDrawing && this.currentPolygon.length === 1) {
            ctx.strokeStyle = '#ffaa00';
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 5]);
            ctx.beginPath();
            ctx.moveTo(this.currentPolygon[0].x, this.currentPolygon[0].y);
            if (this.tempPoint) ctx.lineTo(this.tempPoint.x, this.tempPoint.y);
            ctx.stroke();
            ctx.setLineDash([]);
        }
    }
    
    drawHoveredPoint() {
        if (this.hoveredPoint && !this.isDragging) {
            const ctx = this.ctx;
            ctx.fillStyle = '#ffff00';
            ctx.beginPath();
            ctx.arc(this.hoveredPoint.x, this.hoveredPoint.y, this.POINT_RADIUS, 0, 2*Math.PI);
            ctx.fill();
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 1;
            ctx.stroke();
        }
    }
    
    getAreaColor(idx) { return '#ffffff'; }
    
    // ==================== 鼠标交互 ====================
    mouseToCanvas(e) {
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        return {
            x: (e.clientX - rect.left) * scaleX,
            y: (e.clientY - rect.top) * scaleY
        };
    }
    
    findNearbyPoint(canvasPoint) {
        for (let aIdx = 0; aIdx < this.areas.length; aIdx++) {
            const area = this.areas[aIdx];
            for (let pIdx = 0; pIdx < area.points.length; pIdx++) {
                const pt = area.points[pIdx];
                const dx = canvasPoint.x - pt[0];
                const dy = canvasPoint.y - pt[1];
                if (Math.sqrt(dx*dx + dy*dy) <= this.POINT_RADIUS) {
                    return { areaIdx: aIdx, pointIdx: pIdx, x: pt[0], y: pt[1] };
                }
            }
        }
        return null;
    }
    
    findAreaAtPoint(canvasPoint) {
        for (let i = 0; i < this.areas.length; i++) {
            const area = this.areas[i];
            if (area.type === 'polygon' || area.type === 'rectangle') {
                if (this.isPointInPolygon(canvasPoint, area.points)) return i;
            } else if (area.type === 'line' && area.points.length >= 2) {
                const dist = this.pointToLineDistance(canvasPoint, area.points[0], area.points[1]);
                if (dist < 10) return i;
            }
        }
        return null;
    }
    
    isPointInPolygon(p, polygon) {
        let inside = false;
        for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
            const xi = polygon[i][0], yi = polygon[i][1];
            const xj = polygon[j][0], yj = polygon[j][1];
            const intersect = ((yi > p.y) !== (yj > p.y)) && (p.x < (xj - xi) * (p.y - yi) / (yj - yi) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }
    
    pointToLineDistance(p, a, b) {
        const dx = b[0] - a[0], dy = b[1] - a[1];
        const len = Math.sqrt(dx*dx + dy*dy);
        if (len === 0) return Math.sqrt((p.x - a[0])**2 + (p.y - a[1])**2);
        const t = ((p.x - a[0]) * dx + (p.y - a[1]) * dy) / (len * len);
        if (t < 0) return Math.sqrt((p.x - a[0])**2 + (p.y - a[1])**2);
        if (t > 1) return Math.sqrt((p.x - b[0])**2 + (p.y - b[1])**2);
        const proj = { x: a[0] + t * dx, y: a[1] + t * dy };
        return Math.sqrt((p.x - proj.x)**2 + (p.y - proj.y)**2);
    }
    
    onMouseDown(e) {
        const pt = this.mouseToCanvas(e);
        // 更新绘制模式（可能从 tool 的全局 select 来）
        this.drawMode = this.tool.drawModeSelect.value;
        
        const nearby = this.findNearbyPoint(pt);
        if (nearby) {
            this.draggedPoint = nearby;
            this.isDragging = true;
            this.dragOffset = { x: pt.x - nearby.x, y: pt.y - nearby.y };
            this.selectedAreaIndex = nearby.areaIdx;
            this.tool.updateAreaListForChannel(this.channelId);
            this.redirectDraw();
            return;
        }
        
        const areaIdx = this.findAreaAtPoint(pt);
        if (areaIdx !== null) {
            this.selectedAreaIndex = areaIdx;
            this.tool.updateAreaListForChannel(this.channelId);
            this.redirectDraw();
            if (this.panMode || this.drawMode === 'select') return;
        }
        
        if (this.panMode || this.drawMode === 'select') return;
        
        switch (this.drawMode) {
            case 'polygon':
                if (!this.isDrawing) {
                    this.isDrawing = true;
                    this.currentPolygon = [pt];
                    this.tempPoint = pt;
                } else {
                    const start = this.currentPolygon[0];
                    const dist = Math.hypot(pt.x - start.x, pt.y - start.y);
                    if (dist < this.CLOSE_THRESHOLD && this.currentPolygon.length >= 3) {
                        this.finishPolygon();
                    } else {
                        this.currentPolygon.push(pt);
                        this.tempPoint = pt;
                    }
                }
                break;
            case 'rectangle':
                this.isDrawing = true;
                this.rectStart = pt;
                this.rectEnd = pt;
                break;
            case 'line':
                if (!this.isDrawing) {
                    this.isDrawing = true;
                    this.currentPolygon = [pt];
                    this.tempPoint = pt;
                } else {
                    this.currentPolygon.push(pt);
                    this.finishLine();
                }
                break;
        }
        // this.drawCanvas();
        this.redirectDraw();
    }
    
    onMouseMove(e) {
        const pt = this.mouseToCanvas(e);
        
        if (this.isDragging && this.draggedPoint) {
            const area = this.areas[this.draggedPoint.areaIdx];
            area.points[this.draggedPoint.pointIdx] = [
                Math.round(pt.x - this.dragOffset.x),
                Math.round(pt.y - this.dragOffset.y)
            ];
            this.redirectDraw();
            this.tool.updateAreaListForChannel(this.channelId);
            return;
        }
        
        this.hoveredPoint = this.findNearbyPoint(pt);
        
        if (this.drawMode === 'polygon' && this.isDrawing) {
            this.tempPoint = pt;
        } else if (this.drawMode === 'rectangle' && this.isDrawing) {
            this.rectEnd = pt;
        } else if (this.drawMode === 'line' && this.isDrawing) {
            this.tempPoint = pt;
        }
        this.redirectDraw();
    }
    
    onMouseUp(e) {
        if (this.isDragging) {
            this.isDragging = false;
            // ---------- 新增吸附 ----------
            const dragged = this.draggedPoint;
            if (dragged) {
                const pt = this.areas[dragged.areaIdx].points[dragged.pointIdx];
                let bestDist = this.ADSORB_THRESHOLD;
                let bestTarget = null;
                // 遍历所有区域，排除自身
                for (let aIdx = 0; aIdx < this.areas.length; aIdx++) {
                    if (aIdx === dragged.areaIdx) continue;
                    const area = this.areas[aIdx];
                    for (let pIdx = 0; pIdx < area.points.length; pIdx++) {
                        const targetPt = area.points[pIdx];
                        const dx = pt[0] - targetPt[0];
                        const dy = pt[1] - targetPt[1];
                        const dist = Math.sqrt(dx*dx + dy*dy);
                        if (dist < bestDist) {
                            bestDist = dist;
                            bestTarget = { areaIdx: aIdx, pointIdx: pIdx, pt: targetPt };
                        }
                    }
                }
                if (bestTarget) {
                    // 吸附到目标顶点
                    this.areas[dragged.areaIdx].points[dragged.pointIdx] = [bestTarget.pt[0], bestTarget.pt[1]];
                }
            }
            this.draggedPoint = null;
            // --------------------------
            this.redirectDraw();
            this.tool.markUnsavedChanges();
            this.tool.saveCalibrationWithDoubleConfirm(false);
            return;
        }
        if (this.drawMode === 'rectangle' && this.isDrawing) {
            this.finishRectangle();
        }

        this.redirectDraw();
    }
    
    onDoubleClick(e) {
        // 双路模式：双击放大画面，不处理多边形闭合
        if (this.tool.viewMode === 'dual') {
            this.tool.enterFullscreen(this.channelId);
            return;
        }
        
        // 如果正在绘制多边形，双击也闭合多边形
        if (this.drawMode === 'polygon' && this.isDrawing && this.currentPolygon.length >= 3) {
            this.finishPolygon();
        }
    }
    
    finishPolygon() {
        if (this.currentPolygon.length >= 3) {
            // const points = this.currentPolygon.map(p => [p.x, p.y]);
            const points = this.currentPolygon.map(p => [Math.round(p.x), Math.round(p.y)]);
            this.areas.push({ name: `area_${this.areas.length}`, type: 'polygon', points });
            this.clearDrawingState();
            this.tool.updateAreaListForChannel(this.channelId);
            this.redirectDraw();
            this.tool.markUnsavedChanges();
            this.tool.saveCalibrationWithDoubleConfirm(false);
        }
    }
    
    finishRectangle() {
        if (this.rectStart && this.rectEnd) {
            const x1 = Math.min(this.rectStart.x, this.rectEnd.x);
            const y1 = Math.min(this.rectStart.y, this.rectEnd.y);
            const x2 = Math.max(this.rectStart.x, this.rectEnd.x);
            const y2 = Math.max(this.rectStart.y, this.rectEnd.y);
            // const points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
            const points = [
                [Math.round(x1), Math.round(y1)],
                [Math.round(x2), Math.round(y1)],
                [Math.round(x2), Math.round(y2)],
                [Math.round(x1), Math.round(y2)]
            ];
            this.areas.push({ name: `rect_${this.areas.length}`, type: 'rectangle', points });
        }
        this.clearDrawingState();
        this.tool.updateAreaListForChannel(this.channelId);
        this.redirectDraw();
        this.tool.markUnsavedChanges();
        this.tool.saveCalibrationWithDoubleConfirm(false);
    }
    
    finishLine() {
        if (this.currentPolygon.length === 2) {
            const points = this.currentPolygon.map(p => [p.x, p.y]);
            this.areas.push({ name: `line_${this.areas.length}`, type: 'line', points });
        }
        this.clearDrawingState();
        this.tool.updateAreaListForChannel(this.channelId);
        this.redirectDraw();
        this.tool.markUnsavedChanges();
        this.tool.saveCalibrationWithDoubleConfirm(false);
    }
    
    clearDrawingState() {
        this.isDrawing = false;
        this.currentPolygon = [];
        this.tempPoint = null;
        this.rectStart = null;
        this.rectEnd = null;
        this.draggedPoint = null;
        this.isDragging = false;
    }
}

// 页面启动
document.addEventListener('DOMContentLoaded', () => {
    window.calibTool = new CalibrationTool();
});
