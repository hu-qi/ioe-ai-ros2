# app_mgr_object-0.1.2 前端工业仪表盘 — 分步开发实施指南

> 文档编号：35-IMPL
> 设计依据：[35.app_mgr_object-0.1.2-前端工业仪表盘布局与开发方案.md](./35.app_mgr_object-0.1.2-前端工业仪表盘布局与开发方案v1.md)
> 目标工程：`app_mgr_object-0.1.2(基础版)`
> 代码基线审查日期：2026-08-06
> 预计工期：5 天

---

## 0. 代码基线审查结论

### 0.1 后端：全部就绪（无需改动）

| 模块 | 文件 | 行数 | 状态 |
|---|---|---|---|
| 业务采集器 | `components/web/business_collector.py` | ~230 | ✅ 8 个采集方法完整 |
| 配置管理器 | `components/web/config_manager.py` | ~170 | ✅ 热加载 + 校验完整 |
| 任务控制器 | `components/web/task_controller.py` | ~90 | ✅ 5 种操作完整 |
| 事件桥 | `components/web/event_bridge.py` | ~150 | ✅ 7 个方法完整 |
| 告警管理器 | `components/web/alarm_manager.py` | ~500 | ✅ 已启用 |
| Web 服务器 | `components/web/web_server.py` | ~1800 | ✅ `_setup_business_routes()` 19 端点 |
| Web 监控插件 | `plugins/web_monitor_plugin.py` | ~700 | ✅ 组件组装 + 告警模块 |

**确认的 API 端点（全部已实现）**：
- `GET/PUT /api/config/{all,bay,dest,schedule,pairs,params}` — 11 个
- `GET /api/business/summary`, `/api/{bay,dest,agv}/status` — 4 个
- `GET /api/task/{queue,instances,stats,history}` — 4 个
- `POST /api/task/control` — 1 个
- `GET /api/alarms{/stats}`, `POST /api/alarms/{acknowledge,resolve,clear}` — 5 个

### 0.2 前端：需全部重写

| 文件 | 当前状态 | 目标 |
|---|---|---|
| `custom.css` | 浅色 Bootstrap 主题 (~360行) | 工业深色主题 (~500行) |
| `base.html` | Bootstrap 蓝导航 + WS 基础连接 | 深色导航 + Toast 容器 + WS 事件路由 |
| `index.html` | 传统三列卡片布局 (~800行) | 四行工业仪表盘 (~250行) |
| `monitor.html` | 传统监控页 | 运维详情页 |
| `control.html` | 启停操作（无告警面板） | 启停操作 + 告警管理面板 |
| JS 文件 | 内联在 HTML 中 | 独立 `api.js` / `websocket.js` / `dashboard.js` / `monitor.js` |

### 0.3 前端资源清单

```
static/
├── css/
│   ├── bootstrap.min.css     ← 保留
│   ├── font-awesome.css      ← 保留
│   └── custom.css            ← 🔴 重写
├── js/
│   ├── jquery.min.js         ← 保留
│   ├── popper.min.js         ← 保留
│   ├── bootstrap.bundle.min.js ← 保留
│   ├── chart.umd.js          ← 保留
│   ├── api.js                ← 🟢 新建
│   ├── websocket.js          ← 🟢 新建
│   ├── dashboard.js          ← 🟢 新建
│   ├── monitor.js            ← 🟢 新建
│   └── control.js            ← 🟡 增强
├── fonts/                    ← 保留
└── webfonts/                 ← 保留

templates/
├── base.html                 ← 🔴 重写
├── index.html                ← 🔴 重写
├── monitor.html              ← 🔴 重写
├── control.html              ← 🟡 增强（嵌入告警面板）
├── alarms.html               ← 保留（可选独立页）
├── calibration.html          ← 保留
└── test.html                 ← 可删除
```

---

## Phase 1: CSS 工业深色主题 (Day 1)

### Step 1.1 — 备份现有 custom.css

```bash
cp app_mgr_object-0.1.2(基础版)/app_mgr_object/components/web/static/css/custom.css \
   app_mgr_object-0.1.2(基础版)/app_mgr_object/components/web/static/css/custom.css.bak
```

### Step 1.2 — 完整替换 custom.css

**文件**: `app_mgr_object/components/web/static/css/custom.css`（完整替换）

```css
/* ============================================================
   custom.css — 工业深色高级质感主题 (v3.0)
   目标工程: app_mgr_object-0.1.2
   ============================================================ */

/* ===== 设计令牌 ===== */
:root {
    --bg-primary:    #0f1923;
    --bg-secondary:  #1a2736;
    --bg-tertiary:   #243447;
    --text-primary:  #e8edf2;
    --text-secondary:#8fa3b8;
    --text-muted:    #5a6f85;
    --accent-blue:   #3498db;
    --accent-green:  #27ae60;
    --accent-orange: #f39c12;
    --accent-red:    #e74c3c;
    --accent-purple: #8e44ad;
    --accent-teal:   #16a085;
    --accent-darkred:#c0392b;
    --border:        #2d3f51;
    --card-shadow:   0 2px 8px rgba(0,0,0,0.3);
    --card-radius:   8px;
    --font-family:   'Segoe UI', -apple-system, 'Microsoft YaHei', sans-serif;
}

/* ===== 全局重置 ===== */
body {
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: var(--font-family);
    font-size: 14px;
    line-height: 1.5;
    margin: 0; padding: 0;
}

a { color: var(--accent-blue); text-decoration: none; }
a:hover { color: #5dade2; }

/* ===== 导航栏 ===== */
.navbar {
    background: var(--bg-secondary) !important;
    border-bottom: 1px solid var(--border);
    height: 48px;
    padding: 0 20px;
    box-shadow: none;
}
.navbar-brand {
    font-weight: 700; font-size: 16px; color: var(--text-primary) !important;
    letter-spacing: 0.5px;
}
.navbar-brand i { color: var(--accent-blue); margin-right: 6px; }
.navbar-nav .nav-link {
    color: var(--text-secondary) !important;
    font-size: 13px; padding: 12px 14px; transition: color 0.2s;
}
.navbar-nav .nav-link:hover,
.navbar-nav .nav-link.active { color: var(--text-primary) !important; }
.navbar-nav .nav-link.active { border-bottom: 2px solid var(--accent-blue); }
.navbar-text { color: var(--text-muted); font-size: 12px; }

/* ===== 卡片 ===== */
.card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--card-radius);
    box-shadow: var(--card-shadow);
    margin-bottom: 0;
}
.card-header {
    background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 14px;
}
.card-body { padding: 10px 14px; }

/* ===== 系统状态条 ===== */
.system-bar {
    display: flex; align-items: center; gap: 16px;
    padding: 6px 16px; margin-bottom: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--card-radius);
    font-size: 13px; color: var(--text-secondary);
}
.sys-divider { width: 1px; height: 16px; background: var(--border); }
.sys-spacer { flex: 1; }
.sys-dot {
    display: inline-block; width: 7px; height: 7px;
    border-radius: 50%; margin-right: 5px;
}
.sys-dot.green  { background: var(--accent-green); box-shadow: 0 0 5px var(--accent-green); }
.sys-dot.red    { background: var(--accent-red);   box-shadow: 0 0 5px var(--accent-red); }
.sys-dot.orange { background: var(--accent-orange);box-shadow: 0 0 5px var(--accent-orange); }
.sys-dot.gray   { background: var(--text-muted); }
.alarm-badge {
    display: inline-block; min-width: 18px; height: 18px; line-height: 18px;
    text-align: center; background: var(--accent-red); color: #fff;
    border-radius: 9px; font-size: 10px; padding: 0 5px;
}

/* ===== 仓位网格 ===== */
.bay-row {
    display: flex; gap: 4px; flex-wrap: nowrap;
}
.bay-cell {
    flex: 1; min-width: 44px; height: 42px;
    border-radius: 5px;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    color: #fff; font-size: 10px; font-weight: 700;
    position: relative; cursor: pointer;
    transition: transform 0.12s, opacity 0.2s;
    overflow: hidden;
}
.bay-cell:hover { transform: scale(1.06); z-index: 2; }
.bay-cell.bay-idle    { opacity: 0.35; border: 1px dashed rgba(255,255,255,0.25); }
.bay-cell.bay-bound   { border: 2px solid rgba(255,255,255,0.35); }
.bay-cell.bay-binding { animation: binding-pulse 0.8s infinite; }
.bay-cell.bay-in-task::after {
    content: '';
    position: absolute; bottom: 0; left: 6px; right: 6px;
    height: 3px; background: rgba(255,255,255,0.5);
    border-radius: 0 0 3px 3px;
}
.bay-label { font-size: 10px; }
.bay-dot {
    position: absolute; top: 3px; right: 5px;
    width: 5px; height: 5px; border-radius: 50%;
    background: #fff; box-shadow: 0 0 4px rgba(255,255,255,0.6);
}

/* 仓位区标签 */
.zone-tag {
    display: inline-block; width: 20px; height: 20px; line-height: 20px;
    text-align: center; border-radius: 4px; color: #fff; font-size: 11px;
    font-weight: 700; margin-right: 6px;
}
.zone-tag.tag-a { background: var(--accent-blue); }
.zone-tag.tag-b { background: var(--accent-green); }
.zone-tag.tag-c { background: var(--accent-orange); }
.zone-tag.tag-d { background: var(--accent-purple); }

/* 楼层标签 */
.floor-tag {
    display: inline-block; padding: 1px 8px; border-radius: 3px;
    color: #fff; font-size: 11px; font-weight: 700; margin-right: 6px;
}
.floor-tag:nth-of-type(1) { background: var(--accent-green); }
.floor-tag:nth-of-type(2) { background: var(--accent-blue); }
.floor-tag:nth-of-type(3) { background: var(--accent-orange); }

/* 目的仓格子 */
.dest-cell {
    flex: 1; min-width: 44px; height: 42px;
    border-radius: 5px;
    display: flex; align-items: center; justify-content: center;
    color: #fff; font-size: 10px; font-weight: 700;
    position: relative; cursor: default;
}
.dest-cell.empty     { background: var(--accent-green); opacity: 0.7; }
.dest-cell.occupied  { background: #3a3a4a; }
.dest-cell .dest-cargo {
    position: absolute; bottom: 2px; right: 5px;
    font-size: 9px; opacity: 0.7;
}

/* ===== AGV 卡片 ===== */
.agv-cards { display: flex; gap: 10px; flex-wrap: wrap; }
.agv-card {
    flex: 1; min-width: 150px;
    background: var(--bg-tertiary); border-radius: 8px; padding: 12px 14px;
    border-left: 4px solid var(--accent-blue);
}
.agv-card.status-idle     { border-left-color: var(--accent-green); }
.agv-card.status-charging { border-left-color: var(--accent-orange); }
.agv-card.status-offline  { border-left-color: var(--accent-red); opacity: 0.6; }
.agv-id      { font-size: 14px; font-weight: 700; }
.agv-status  { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.agv-battery { font-size: 16px; font-weight: 600; margin-top: 4px; }
.agv-battery.low { color: var(--accent-red); animation: alarm-blink 2s infinite; }
.agv-task    { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

/* ===== 操作区 ===== */
.op-section { margin-bottom: 10px; }
.op-label {
    font-size: 11px; color: var(--text-muted);
    text-transform: uppercase; margin-bottom: 3px;
    letter-spacing: 0.5px;
}
.op-arrow {
    display: block; text-align: center; color: var(--accent-blue);
    font-size: 16px; margin: 2px 0;
}

/* 按钮（深色主题） */
.btn-accent {
    background: var(--accent-blue); color: #fff; border: none;
    font-size: 12px; padding: 6px 14px; border-radius: 5px;
}
.btn-accent:hover { background: #2980b9; color: #fff; }
.btn-outline {
    background: transparent; color: var(--text-secondary);
    border: 1px solid var(--border); font-size: 12px;
    padding: 6px 14px; border-radius: 5px;
}
.btn-outline:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.btn-danger-sm  { font-size: 11px; padding: 4px 10px; }
.btn-warning-sm { font-size: 11px; padding: 4px 10px; }

/* 表单控件（深色主题） */
.form-select, .form-control {
    background: var(--bg-tertiary); color: var(--text-primary);
    border: 1px solid var(--border); font-size: 12px;
}
.form-select:focus, .form-control:focus {
    background: var(--bg-tertiary); color: var(--text-primary);
    border-color: var(--accent-blue); box-shadow: 0 0 0 2px rgba(52,152,219,0.25);
}
.form-select-sm, .form-control-sm { font-size: 11px; padding: 4px 8px; }

/* ===== 任务面板 ===== */
.task-table-wrap { overflow-x: auto; }
.task-table {
    font-size: 12px; color: var(--text-primary);
    margin-bottom: 0;
}
.task-table thead th {
    background: var(--bg-tertiary); color: var(--text-muted);
    border-bottom: 2px solid var(--border);
    font-weight: 600; text-transform: uppercase;
    font-size: 10px; padding: 8px 10px; white-space: nowrap;
}
.task-table tbody td {
    padding: 7px 10px; border-color: #1e2d3d;
    vertical-align: middle; white-space: nowrap;
}
.task-table tbody tr:hover { background: #1e2d3d; }
.task-table tbody tr:nth-child(even) { background: rgba(255,255,255,0.02); }

/* Tab 栏（内嵌在 card-header） */
.tab-bar-inline {
    display: inline-flex; gap: 0; margin-left: 20px;
    vertical-align: middle;
}
.tab-bar-inline .tab {
    padding: 4px 14px; font-size: 11px; color: var(--text-muted);
    cursor: pointer; border-radius: 4px 4px 0 0;
    transition: all 0.15s;
}
.tab-bar-inline .tab:hover { color: var(--text-secondary); background: rgba(255,255,255,0.03); }
.tab-bar-inline .tab.active {
    color: var(--text-primary); background: var(--bg-tertiary);
    border-bottom: 2px solid var(--accent-blue);
}
.tab-bar-inline .tab b { color: var(--accent-blue); margin-left: 2px; }

/* 状态徽章 */
.status-badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; font-weight: 600;
}
.status-badge.running   { background: #1a3a2a; color: var(--accent-green); }
.status-badge.completed { background: #1a2a3a; color: var(--accent-blue); }
.status-badge.failed    { background: #3a1a1a; color: var(--accent-red); }
.status-badge.pending   { background: #3a2a1a; color: var(--accent-orange); }
.status-badge.idle      { background: #1a2a2a; color: var(--text-secondary); }

/* ===== 告警信息栏 ===== */
.alarm-list { display: flex; flex-direction: column; gap: 4px; }
.alarm-row {
    display: flex; align-items: center; gap: 10px;
    padding: 7px 10px; border-radius: 5px;
    background: var(--bg-tertiary); font-size: 12px;
}
.alarm-row.critical { border-left: 3px solid var(--accent-red); }
.alarm-row.warning  { border-left: 3px solid var(--accent-orange); }
.alarm-row.info     { border-left: 3px solid var(--accent-blue); }
.alarm-dot {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.alarm-row.critical .alarm-dot { background: var(--accent-red); }
.alarm-row.warning  .alarm-dot { background: var(--accent-orange); }
.alarm-row.info     .alarm-dot { background: var(--accent-blue); }
.alarm-msg   { flex: 1; }
.alarm-time  { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.alarm-actions { display: flex; gap: 4px; }
.alarm-actions button { font-size: 10px; padding: 2px 8px; }
.alarm-empty { text-align: center; color: var(--accent-green); padding: 12px; font-size: 13px; }

.view-all-link {
    float: right; font-size: 11px; color: var(--text-muted);
    text-transform: none; font-weight: 400; letter-spacing: 0;
}
.view-all-link:hover { color: var(--accent-blue); }

/* ===== Modal（深色主题） ===== */
.modal-content {
    background: var(--bg-secondary); border: 1px solid var(--border);
    border-radius: var(--card-radius);
}
.modal-header {
    background: var(--bg-tertiary); border-bottom: 1px solid var(--border);
    color: var(--text-primary);
}
.modal-body { color: var(--text-primary); }
.modal-footer { border-top: 1px solid var(--border); }
.btn-close { filter: invert(1); }

/* ===== Toast 容器 ===== */
#toast-container { position: fixed; top: 60px; right: 20px; z-index: 9999; }
.toast-item {
    background: var(--bg-tertiary); color: var(--text-primary);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 10px 16px; margin-bottom: 8px; min-width: 280px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    animation: toast-in 0.3s ease;
    font-size: 13px;
}
.toast-item.success { border-left: 3px solid var(--accent-green); }
.toast-item.error   { border-left: 3px solid var(--accent-red); }
.toast-item.warning { border-left: 3px solid var(--accent-orange); }
.toast-item.info    { border-left: 3px solid var(--accent-blue); }
.toast-close { float: right; cursor: pointer; color: var(--text-muted); font-size: 16px; }
.toast-close:hover { color: var(--text-primary); }

/* ===== WS 状态指示器 ===== */
.ws-status {
    position: fixed; bottom: 16px; right: 16px; z-index: 1000;
    background: rgba(26,39,54,0.9); color: var(--text-muted);
    padding: 6px 14px; border-radius: 16px; font-size: 11px;
    border: 1px solid var(--border);
}
.ws-status.connected { color: var(--accent-green); border-color: var(--accent-green); }
.ws-status.disconnected { color: var(--accent-red); border-color: var(--accent-red); }

/* ===== 动画 ===== */
@keyframes binding-pulse {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.6; }
}
@keyframes alarm-blink {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.5; }
}
@keyframes toast-in {
    from { opacity: 0; transform: translateX(40px); }
    to   { opacity: 1; transform: translateX(0); }
}

/* ===== 响应式 ===== */
@media (max-width: 991px) {
    .bay-cell { min-width: 36px; height: 36px; font-size: 9px; }
    .bay-label { font-size: 8px; }
    .agv-cards { flex-direction: column; }
    .system-bar { flex-wrap: wrap; gap: 8px; font-size: 11px; }
}
```

### Step 1.3 — 验证 CSS 加载

启动服务后访问 `/`，确认：
- 背景变为深色 `#0f1923`
- 导航栏变为深色 `#1a2736`
- 卡片有圆角和细边框
- 文字为浅色 `#e8edf2`

---

## Phase 2: base.html 导航+WS 事件路由 (Day 1 下午)

### Step 2.1 — 完整替换 base.html

**文件**: `app_mgr_object/components/web/templates/base.html`

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}天眼运维监控系统{% endblock %}</title>
    <link rel="stylesheet" href="/static/css/font-awesome.css">
    <link rel="stylesheet" href="/static/css/bootstrap.min.css">
    <link rel="stylesheet" href="/static/css/custom.css">
    {% block extra_css %}{% endblock %}
</head>
<body>

    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="fas fa-satellite"></i> 天眼运维监控
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto">
                    <li class="nav-item"><a class="nav-link" href="/" id="nav-home"><i class="fas fa-chart-pie"></i> 仪表盘</a></li>
                    <li class="nav-item"><a class="nav-link" href="/monitor" id="nav-monitor"><i class="fas fa-broadcast-tower"></i> 状态监控</a></li>
                    <li class="nav-item"><a class="nav-link" href="/control" id="nav-control"><i class="fas fa-sliders-h"></i> 运维控制</a></li>
                </ul>
                <div class="navbar-text">
                    <span id="sys-mode-display"></span>
                    <span class="ms-3" id="current-time"></span>
                </div>
            </div>
        </div>
    </nav>

    <!-- 主内容 -->
    {% block content %}{% endblock %}

    <!-- Toast 容器 -->
    <div id="toast-container"></div>

    <!-- WebSocket 状态 -->
    <div class="ws-status" id="ws-status">
        <i class="fas fa-plug"></i> <span id="ws-text">连接中...</span>
    </div>

    <!-- 脚本 -->
    <script src="/static/js/jquery.min.js"></script>
    <script src="/static/js/popper.min.js"></script>
    <script src="/static/js/bootstrap.bundle.min.js"></script>
    <script src="/static/js/chart.umd.js"></script>
    <script src="/static/js/websocket.js"></script>

    <script>
        // ===== 全局工具函数 =====

        // 实时时钟
        function updateClock() {
            var now = new Date();
            document.getElementById('current-time').textContent =
                now.toLocaleString('zh-CN', {hour12: false});
        }
        updateClock();
        setInterval(updateClock, 1000);

        // Toast 通知
        function showToast(message, type) {
            type = type || 'info';
            var icons = { success: 'fa-check-circle', error: 'fa-times-circle',
                         warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };
            var toast = document.createElement('div');
            toast.className = 'toast-item ' + type;
            toast.innerHTML = '<i class="fas ' + (icons[type] || icons.info) + '"></i> ' + message +
                '<span class="toast-close" onclick="this.parentElement.remove()">&times;</span>';
            document.getElementById('toast-container').appendChild(toast);
            setTimeout(function() { if (toast.parentElement) toast.remove(); }, 5000);
        }

        // 获取系统模式
        function fetchSystemMode() {
            fetch('/api/status')
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    var mode = (d.operation_mode || 'development');
                    document.getElementById('sys-mode-display').textContent =
                        mode === 'development' ? '🔧 开发模式' : '🏭 部署模式';
                })
                .catch(function() {
                    document.getElementById('sys-mode-display').textContent = '🏭 部署模式';
                });
        }

        // ===== 导航激活 =====
        document.addEventListener('DOMContentLoaded', function() {
            fetchSystemMode();
            WS.connect();

            var path = window.location.pathname;
            var map = { '/': 'nav-home', '/monitor': 'nav-monitor', '/control': 'nav-control' };
            var id = map[path];
            if (id) { var el = document.getElementById(id); if (el) el.classList.add('active'); }
        });
    </script>

    {% block extra_js %}{% endblock %}
</body>
</html>
```

### Step 2.2 — 验证

- 导航栏深色背景 + 蓝色品牌文字
- 右上角显示 "🏭 部署模式" + 实时时钟
- 当前页的导航项有蓝色底部边框高亮
- 右下角 WS 状态指示器颜色正确

---

## Phase 3: websocket.js + api.js 公共模块 (Day 2 上午)

### Step 3.1 — 新建 websocket.js

**文件**: `app_mgr_object/components/web/static/js/websocket.js`

```javascript
/**
 * WebSocket 单例管理器
 * 特性：自动重连（指数退避）、事件路由、连接状态回调
 */
var WS = {
    socket: null,
    handlers: {},
    reconnectDelay: 2000,
    maxReconnectDelay: 30000,
    _statusCallbacks: [],

    connect: function() {
        var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        var url = proto + '//' + location.host + '/ws';
        var self = this;

        this.socket = new WebSocket(url);

        this.socket.onopen = function() {
            console.log('WS connected');
            self.reconnectDelay = 2000;
            self._setStatus(true);
            self._emit('connect', {});
        };

        this.socket.onclose = function() {
            console.log('WS closed, reconnecting in ' + (self.reconnectDelay / 1000) + 's');
            self._setStatus(false);
            setTimeout(function() { self.connect(); }, self.reconnectDelay);
            self.reconnectDelay = Math.min(self.reconnectDelay * 2, self.maxReconnectDelay);
        };

        this.socket.onmessage = function(e) {
            try {
                var msg = JSON.parse(e.data);
                self._emit(msg.type, msg);
            } catch (err) {
                console.warn('WS parse error:', err);
            }
        };

        this.socket.onerror = function(e) {
            console.warn('WS error');
        };
    },

    on: function(type, handler) {
        if (!this.handlers[type]) this.handlers[type] = [];
        this.handlers[type].push(handler);
    },

    onStatusChange: function(cb) {
        this._statusCallbacks.push(cb);
    },

    _emit: function(type, data) {
        var list = this.handlers[type] || [];
        for (var i = 0; i < list.length; i++) {
            try { list[i](data); } catch(e) { console.warn('WS handler error:', e); }
        }
    },

    _setStatus: function(connected) {
        var el = document.getElementById('ws-status');
        if (!el) return;
        var textEl = document.getElementById('ws-text');
        if (connected) {
            el.className = 'ws-status connected';
            if (textEl) textEl.textContent = '已连接';
        } else {
            el.className = 'ws-status disconnected';
            if (textEl) textEl.textContent = '断开';
        }
        for (var i = 0; i < this._statusCallbacks.length; i++) {
            try { this._statusCallbacks[i](connected); } catch(e) {}
        }
    }
};
```

### Step 3.2 — 新建 api.js

**文件**: `app_mgr_object/components/web/static/js/api.js`

```javascript
/**
 * API 统一封装
 * 所有方法返回 Promise<object>，失败返回 { success: false, error: string }
 */
var API = {
    base: '',

    _fetch: function(url, options) {
        var self = this;
        options = options || {};
        options.headers = options.headers || {};
        options.headers['Content-Type'] = 'application/json';

        return fetch(self.base + url, options)
            .then(function(resp) {
                if (!resp.ok) {
                    return resp.json().catch(function() { return {}; }).then(function(err) {
                        throw new Error(err.error || 'HTTP ' + resp.status);
                    });
                }
                return resp.json();
            })
            .catch(function(e) {
                console.warn('API ' + url + ' failed:', e.message);
                return { success: false, error: e.message };
            });
    },

    _get:  function(url)          { return this._fetch(url); },
    _put:  function(url, body)    { return this._fetch(url, { method: 'PUT',  body: JSON.stringify(body) }); },
    _post: function(url, body)    { return this._fetch(url, { method: 'POST', body: JSON.stringify(body) }); },

    // 业务数据
    getBusinessSummary:  function() { return this._get('/api/business/summary'); },
    getBayStatus:        function() { return this._get('/api/bay/status'); },
    getDestStatus:       function() { return this._get('/api/dest/status'); },
    getAgvStatus:        function() { return this._get('/api/agv/status'); },
    getTaskQueue:        function() { return this._get('/api/task/queue'); },
    getTaskInstances:    function() { return this._get('/api/task/instances'); },
    getTaskStatistics:   function() { return this._get('/api/task/stats'); },
    getTaskHistory:      function(limit) { return this._get('/api/task/history?limit=' + (limit || 5)); },

    // 配置
    getConfigBay:        function() { return this._get('/api/config/bay'); },
    setConfigBay:        function(m) { return this._put('/api/config/bay', { mappings: m }); },
    getConfigDest:       function() { return this._get('/api/config/dest'); },
    setConfigDest:       function(m) { return this._put('/api/config/dest', { mappings: m }); },
    getConfigAll:        function() { return this._get('/api/config/all'); },

    // 任务操作
    taskControl: function(op, params) {
        params = params || {};
        params.operation = op;
        return this._post('/api/task/control', params);
    },

    // 告警
    getAlarms: function(limit, ack) {
        var url = '/api/alarms?limit=' + (limit || 5);
        if (ack) url += '&acknowledged=true';
        return this._get(url);
    },
    getAlarmStats:       function() { return this._get('/api/alarms/stats'); },
    acknowledgeAlarm:    function(id) { return this._post('/api/alarms/acknowledge', { alarm_id: id }); },
    resolveAlarm:        function(id) { return this._post('/api/alarms/resolve', { alarm_id: id }); },

    // 系统状态
    getStatus:           function() { return this._get('/api/status'); }
};
```

### Step 3.3 — 验证

在浏览器 console 中执行：
```javascript
API.getBayStatus().then(function(d) { console.log('Bay status:', d); });
API.getAlarms(3).then(function(d) { console.log('Alarms:', d); });
```

---

## Phase 4: 首页仪表盘 index.html + dashboard.js (Day 2 下午 ~ Day 3)

### Step 4.1 — 完整替换 index.html

**文件**: `app_mgr_object/components/web/templates/index.html`

```html
{% extends "base.html" %}
{% block title %}仪表盘 - 天眼运维监控{% endblock %}

{% block extra_css %}
<style>
    .bay-zone-card .card-header, .dest-zone-card .card-header {
        padding: 6px 12px; font-size: 11px;
    }
    /* 强制触发 loading */
    #btn-force-trigger.loading { opacity: 0.6; pointer-events: none; }
</style>
{% endblock %}

{% block content %}
<div class="container-fluid px-3 pt-2">

    <!-- ====== ROW 0: 系统状态条 ====== -->
    <div class="system-bar">
        <div class="sys-item"><i class="fas fa-server"></i> <span id="sys-mode">--</span></div>
        <div class="sys-divider"></div>
        <div class="sys-item"><span class="sys-dot green" id="sys-dot-nodes"></span> 节点 <span id="sys-nodes">--</span></div>
        <div class="sys-item"><span class="sys-dot green" id="sys-dot-channels"></span> 通道 <span id="sys-channels">--</span></div>
        <div class="sys-item"><span class="sys-dot green" id="sys-dot-agv"></span> AGV <span id="sys-agv">--</span></div>
        <span class="sys-spacer"></span>
        <div class="sys-item"><i class="fas fa-bell"></i> 告警 <span class="alarm-badge" id="sys-alarm-count">0</span></div>
        <div class="sys-item" id="sys-clock"></div>
    </div>

    <!-- ====== ROW 1: 仓位热力图 (75%) + 任务操作 (25%) ====== -->
    <div class="row g-2 mb-2">

        <!-- 左侧 75% -->
        <div class="col-lg-9">
            <div class="row g-2">

                <!-- 起始仓 A区 + B区 -->
                <div class="col-lg-3">
                    <div class="card bay-zone-card">
                        <div class="card-header"><span class="zone-tag tag-a">A</span> 起始仓 A</div>
                        <div class="card-body p-1"><div class="bay-row" id="bay-zone-a"></div></div>
                    </div>
                </div>
                <div class="col-lg-3">
                    <div class="card bay-zone-card">
                        <div class="card-header"><span class="zone-tag tag-b">B</span> 起始仓 B</div>
                        <div class="card-body p-1"><div class="bay-row" id="bay-zone-b"></div></div>
                    </div>
                </div>

                <!-- 目的仓 2F + 3F + 4F -->
                <div class="col-lg-6">
                    <div class="row g-2">
                        <div class="col-12">
                            <div class="card dest-zone-card">
                                <div class="card-header"><span class="floor-tag">2F</span> 目的仓 2F</div>
                                <div class="card-body p-1"><div class="bay-row" id="dest-zone-2f"></div></div>
                            </div>
                        </div>
                        <div class="col-12">
                            <div class="card dest-zone-card">
                                <div class="card-header"><span class="floor-tag">3F</span> 目的仓 3F</div>
                                <div class="card-body p-1"><div class="bay-row" id="dest-zone-3f"></div></div>
                            </div>
                        </div>
                        <div class="col-12">
                            <div class="card dest-zone-card">
                                <div class="card-header"><span class="floor-tag">4F</span> 目的仓 4F</div>
                                <div class="card-body p-1"><div class="bay-row" id="dest-zone-4f"></div></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 起始仓 C区 + D区 -->
                <div class="col-lg-3">
                    <div class="card bay-zone-card">
                        <div class="card-header"><span class="zone-tag tag-c">C</span> 起始仓 C</div>
                        <div class="card-body p-1"><div class="bay-row" id="bay-zone-c"></div></div>
                    </div>
                </div>
                <div class="col-lg-3">
                    <div class="card bay-zone-card">
                        <div class="card-header"><span class="zone-tag tag-d">D</span> 起始仓 D</div>
                        <div class="card-body p-1"><div class="bay-row" id="bay-zone-d"></div></div>
                    </div>
                </div>

                <!-- 空占位（与目的仓对齐） -->
                <div class="col-lg-6"></div>

                <!-- AGV 卡片 -->
                <div class="col-12">
                    <div class="card">
                        <div class="card-header"><i class="fas fa-robot"></i> AGV 状态</div>
                        <div class="card-body p-2"><div class="agv-cards" id="agv-cards"></div></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 右侧 25%: 任务操作 -->
        <div class="col-lg-3">
            <div class="card h-100">
                <div class="card-header"><i class="fas fa-sliders-h"></i> 任务操作</div>
                <div class="card-body">

                    <div class="op-section">
                        <label class="op-label">强制触发任务</label>
                        <select class="form-select form-select-sm mb-1" id="trigger-src"></select>
                        <span class="op-arrow">→</span>
                        <select class="form-select form-select-sm mb-2" id="trigger-dst"></select>
                        <button class="btn btn-accent btn-sm w-100" id="btn-force-trigger">
                            <i class="fas fa-bolt"></i> 执行触发
                        </button>
                    </div>

                    <hr style="border-color: var(--border);">

                    <div class="op-section">
                        <label class="op-label">查询任务</label>
                        <input type="text" class="form-control form-control-sm mb-2" id="query-task-id" placeholder="输入 task_id">
                        <button class="btn btn-outline btn-sm w-100" id="btn-query-task">
                            <i class="fas fa-search"></i> 查询
                        </button>
                    </div>

                    <hr style="border-color: var(--border);">

                    <div class="op-section">
                        <label class="op-label">取消 / 重试任务</label>
                        <input type="text" class="form-control form-control-sm mb-2" id="ctrl-task-id" placeholder="输入 task_id">
                        <div class="d-flex gap-2">
                            <button class="btn btn-danger btn-danger-sm flex-fill" id="btn-cancel-task">
                                <i class="fas fa-times"></i> 取消
                            </button>
                            <button class="btn btn-warning btn-warning-sm flex-fill" id="btn-retry-task">
                                <i class="fas fa-redo"></i> 重试
                            </button>
                        </div>
                    </div>

                    <hr style="border-color: var(--border);">

                    <button class="btn btn-outline btn-sm w-100" id="btn-refresh-all">
                        <i class="fas fa-sync-alt"></i> 刷新全部状态
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- ====== ROW 2: 任务面板 ====== -->
    <div class="row g-2 mb-2">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <i class="fas fa-tasks"></i> 任务面板
                    <span class="tab-bar-inline">
                        <span class="tab active" data-tab="active">活跃 <b id="tab-active-count">0</b></span>
                        <span class="tab" data-tab="queue">队列 <b id="tab-queue-count">0</b></span>
                        <span class="tab" data-tab="history">最近完成 <b>5</b></span>
                    </span>
                </div>
                <div class="card-body p-0">
                    <div class="task-table-wrap">
                        <table class="table task-table mb-0">
                            <thead><tr>
                                <th>任务ID</th><th>路线</th><th>状态</th><th>AGV</th><th>创建时间</th><th>操作</th>
                            </tr></thead>
                            <tbody id="task-tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- ====== ROW 3: 告警信息栏 ====== -->
    <div class="row g-2">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <i class="fas fa-exclamation-triangle"></i> 告警信息
                    <a href="/control" class="view-all-link">查看全部 →</a>
                </div>
                <div class="card-body p-2">
                    <div class="alarm-list" id="alarm-list">
                        <div class="alarm-empty">✅ 暂无告警</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- 仓位编辑 Modal -->
    <div class="modal fade" id="bayEditModal" tabindex="-1">
        <div class="modal-dialog modal-sm">
            <div class="modal-content">
                <div class="modal-header">
                    <h6 class="modal-title" id="bayEditTitle">编辑仓位类型</h6>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <label class="op-label">cargo_type (1~6)</label>
                    <select class="form-select" id="bayEditCargoType">
                        <option value="1">1 - 蓝色</option>
                        <option value="2">2 - 绿色</option>
                        <option value="3">3 - 橙色</option>
                        <option value="4">4 - 紫色</option>
                        <option value="5">5 - 青色</option>
                        <option value="6">6 - 红色</option>
                    </select>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline btn-sm" data-bs-dismiss="modal">取消</button>
                    <button type="button" class="btn btn-accent btn-sm" id="btn-save-bay">保存</button>
                </div>
            </div>
        </div>
    </div>

</div>

<!-- 图例 -->
<div style="position:fixed;bottom:50px;left:16px;z-index:999;display:flex;gap:12px;align-items:center;font-size:10px;color:var(--text-muted);">
    <span style="display:flex;align-items:center;gap:3px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--accent-green);opacity:0.35;border:1px dashed rgba(255,255,255,0.25);"></span> 空闲</span>
    <span style="display:flex;align-items:center;gap:3px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--accent-blue);border:2px solid rgba(255,255,255,0.35);"></span> 已绑定</span>
    <span style="display:flex;align-items:center;gap:3px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--accent-orange);position:relative;"></span> 执行中</span>
    <span style="color:var(--accent-green);">● 空可用</span>
    <span style="color:#3a3a4a;">● 占用</span>
</div>
{% endblock %}

{% block extra_js %}
<script src="/static/js/api.js"></script>
<script src="/static/js/dashboard.js"></script>
{% endblock %}
```

### Step 4.2 — 新建 dashboard.js

**文件**: `app_mgr_object/components/web/static/js/dashboard.js`

```javascript
/**
 * 仪表盘页面逻辑
 * 数据驱动渲染：API 拉取 → DOM 渲染 → WS 推送局部刷新
 */

// ===== 仓位渲染常量 =====
var CARGO_COLORS = {
    1: '#2980b9', 2: '#27ae60', 3: '#e67e22',
    4: '#8e44ad', 5: '#16a085', 6: '#c0392b'
};

var BAY_GROUP_MAP = {
    'bay-zone-a': ['A1001','A1002','A1003','A1004','A1005','A1006'],
    'bay-zone-b': ['B1001','B1002','B1003','B1004','B1005','B1006'],
    'bay-zone-c': ['C1001','C1002','C1003','C1004','C1005','C1006'],
    'bay-zone-d': ['D1001','D1002','D1003','D1004','D1005','D1006']
};

var DEST_FLOOR_MAP = {
    'dest-zone-2f': ['T2001','T2002','T2003','T2004','T2005','T2006'],
    'dest-zone-3f': ['T3001','T3002','T3003','T3004','T3005','T3006'],
    'dest-zone-4f': ['T4001','T4002','T4003','T4004','T4005','T4006']
};

// 当前 Tab
var currentTaskTab = 'active';

// ===== 页面初始化 =====
document.addEventListener('DOMContentLoaded', function() {
    loadAllData();
    bindEvents();
    bindWebSocket();
    updateClockDashboard();
    setInterval(updateClockDashboard, 1000);
});

function updateClockDashboard() {
    var el = document.getElementById('sys-clock');
    if (el) el.textContent = new Date().toLocaleString('zh-CN', {hour12: false});
}

// ===== 数据加载 =====
function loadAllData() {
    Promise.all([
        API.getBayStatus(),
        API.getDestStatus(),
        API.getAgvStatus(),
        API.getTaskInstances(),
        API.getAlarms(5, false),
        API.getStatus()
    ]).then(function(results) {
        renderBayGrid(results[0]);
        renderDestGrid(results[1]);
        renderAgvCards(results[2]);
        renderTaskTable(currentTaskTab, results[3]);
        renderAlarmList(results[4]);
        updateSystemBar(results[5]);
    }).catch(function(e) {
        console.error('Initial load failed:', e);
    });
}

// ===== 起始仓位渲染 =====
function renderBayGrid(data) {
    var bays = (data && data.bays) ? data.bays : [];
    var bayMap = {};
    bays.forEach(function(b) { bayMap[b.bay_id] = b; });

    Object.keys(BAY_GROUP_MAP).forEach(function(zoneId) {
        var container = document.getElementById(zoneId);
        if (!container) return;
        var ids = BAY_GROUP_MAP[zoneId];
        container.innerHTML = ids.map(function(id) {
            var bay = bayMap[id];
            if (bay) return renderBayCell(bay);
            return '<div class="bay-cell bay-idle" style="background:#333"><span class="bay-label">' + id + '</span></div>';
        }).join('');
    });
}

function renderBayCell(bay) {
    var color = CARGO_COLORS[bay.cargo_type] || '#555';
    var cssClass = 'bay-cell';
    if (bay.bind_status === 1) cssClass += ' bay-bound';
    else if (bay.bind_status === 2) cssClass += ' bay-binding';
    else cssClass += ' bay-idle';
    if (bay.in_task) cssClass += ' bay-in-task';

    return '<div class="' + cssClass + '" style="background:' + color + '"' +
        ' data-bay-id="' + bay.bay_id + '"' +
        ' data-cargo-type="' + bay.cargo_type + '"' +
        ' title="' + bay.bay_id + ' | type:' + bay.cargo_type + ' | ' + (bay.bind_status_label || '') + '">' +
        '<span class="bay-label">' + bay.bay_id + '</span>' +
        (bay.bind_status === 1 ? '<span class="bay-dot"></span>' : '') +
        '</div>';
}

// ===== 目的仓渲染 =====
function renderDestGrid(data) {
    var bays = (data && data.bays) ? data.bays : [];
    var bayMap = {};
    bays.forEach(function(b) { bayMap[b.bay_id] = b; });

    Object.keys(DEST_FLOOR_MAP).forEach(function(zoneId) {
        var container = document.getElementById(zoneId);
        if (!container) return;
        var ids = DEST_FLOOR_MAP[zoneId];
        container.innerHTML = ids.map(function(id) {
            var bay = bayMap[id];
            if (bay) {
                var cssClass = bay.is_empty ? 'dest-cell empty' : 'dest-cell occupied';
                return '<div class="' + cssClass + '">' + id +
                    '<span class="dest-cargo">' + (bay.cargo_type || '') + '</span></div>';
            }
            return '<div class="dest-cell occupied">' + id + '</div>';
        }).join('');
    });
}

// ===== AGV 渲染 =====
function renderAgvCards(data) {
    var robots = (data && data.robots) ? data.robots : [];
    var container = document.getElementById('agv-cards');
    if (robots.length === 0) {
        container.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center;">暂无 AGV 数据</div>';
        return;
    }
    container.innerHTML = robots.map(function(r) {
        var st = (r.status || '').toLowerCase();
        var cssClass = 'agv-card';
        if (st === 'idle') cssClass += ' status-idle';
        else if (st === 'charging') cssClass += ' status-charging';
        else if (st === 'offline') cssClass += ' status-offline';
        var batteryClass = (r.battery < 20) ? ' agv-battery low' : ' agv-battery';
        return '<div class="' + cssClass + '">' +
            '<div class="agv-id">AGV ' + r.robot_id + '</div>' +
            '<div class="agv-status">● ' + (r.status || 'UNKNOWN') + '</div>' +
            '<div class="' + batteryClass + '">🔋 ' + (r.battery || '--') + '%</div>' +
            (r.current_task_id ? '<div class="agv-task">任务: ' + r.current_task_id + '</div>' : '') +
            '</div>';
    }).join('');
}

// ===== 任务面板 =====
var STATUS_BADGE_MAP = {
    'running': 'running', 'calling_rcs': 'running', 'monitoring': 'running',
    'completed': 'completed', 'failed': 'failed', 'idle': 'idle'
};

function renderTaskTable(tab, data) {
    var tbody = document.getElementById('task-tbody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:30px;">加载中...</td></tr>';

    if (tab === 'active') {
        renderActiveTasks(data);
    } else if (tab === 'queue') {
        API.getTaskQueue().then(function(d) { renderQueueTasks(d); });
    } else if (tab === 'history') {
        API.getTaskHistory(5).then(function(d) { renderHistoryTasks(d); });
    }
}

function renderActiveTasks(data) {
    var instances = (data && data.instances) ? data.instances : [];
    var tbody = document.getElementById('task-tbody');
    document.getElementById('tab-active-count').textContent = instances.length;

    if (instances.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:30px;">无活跃任务</td></tr>';
        return;
    }

    tbody.innerHTML = instances.map(function(t) {
        var badgeType = STATUS_BADGE_MAP[t.status] || 'idle';
        return '<tr>' +
            '<td><code style="font-size:11px;color:var(--accent-blue);">' + (t.task_id || '--') + '</code></td>' +
            '<td>' + (t.src_bay || '') + ' → ' + (t.dst_bay || '') + '</td>' +
            '<td><span class="status-badge ' + badgeType + '">' + (t.current_state || t.status || '--') + '</span></td>' +
            '<td>' + (t.robot_id || '--') + '</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">' + (t.created_at || '--') + '</td>' +
            '<td>' +
                '<button class="btn btn-outline btn-sm" style="font-size:10px;padding:1px 6px;" ' +
                    'onclick="queryTask(\'' + (t.task_id || '') + '\')"><i class="fas fa-search"></i></button>' +
            '</td>' +
            '</tr>';
    }).join('');
}

function renderQueueTasks(data) {
    var queue = (data && data.queue) ? data.queue : [];
    var tbody = document.getElementById('task-tbody');
    document.getElementById('tab-queue-count').textContent = queue.length;

    if (queue.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:30px;">队列为空</td></tr>';
        return;
    }

    tbody.innerHTML = queue.map(function(item, i) {
        return '<tr>' +
            '<td><code style="font-size:11px;color:var(--text-muted);">#' + (i + 1) + '</code></td>' +
            '<td>' + (item.src_bay || '') + ' → ' + (item.dst_bay || '') + '</td>' +
            '<td><span class="status-badge pending">待触发</span></td>' +
            '<td>' + (item.robot_id || '--') + '</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">' + (item.created_at || '--') + '</td>' +
            '<td>--</td>' +
            '</tr>';
    }).join('');
}

function renderHistoryTasks(data) {
    var history = (data && data.history) ? data.history : [];
    var tbody = document.getElementById('task-tbody');

    if (history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:30px;">无历史记录</td></tr>';
        return;
    }

    tbody.innerHTML = history.map(function(t) {
        var badgeType = STATUS_BADGE_MAP[t.status] || 'idle';
        return '<tr>' +
            '<td><code style="font-size:11px;color:var(--text-muted);">' + (t.task_id || '--') + '</code></td>' +
            '<td>' + (t.src_bay || '') + ' → ' + (t.dst_bay || '') + '</td>' +
            '<td><span class="status-badge ' + badgeType + '">' + (t.status || '--') + '</span></td>' +
            '<td>--</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">' + (t.created_at || '--') + '</td>' +
            '<td>--</td>' +
            '</tr>';
    }).join('');
}

// ===== 告警 =====
function renderAlarmList(data) {
    var alarms = (data && data.alarms) ? data.alarms : [];
    var container = document.getElementById('alarm-list');
    if (!alarms.length) {
        container.innerHTML = '<div class="alarm-empty">✅ 暂无告警</div>';
        document.getElementById('sys-alarm-count').textContent = '0';
        return;
    }

    var unack = alarms.filter(function(a) { return !a.acknowledged; });
    document.getElementById('sys-alarm-count').textContent = unack.length;

    container.innerHTML = unack.slice(0, 5).map(function(a) {
        var level = (a.level || '').toLowerCase();
        var levelClass = (level === 'critical' || level === 'error') ? 'critical' :
                         (level === 'warning') ? 'warning' : 'info';
        return '<div class="alarm-row ' + levelClass + '">' +
            '<span class="alarm-dot"></span>' +
            '<span class="alarm-msg">' + (a.message || '未知告警') + '</span>' +
            '<span class="alarm-time">' + (a.time_str || '') + '</span>' +
            '<span class="alarm-actions">' +
                '<button class="btn btn-outline btn-sm" onclick="ackAlarm(\'' + (a.id || '') + '\')">确认</button>' +
                '<button class="btn btn-outline btn-sm" onclick="resolveAlarm(\'' + (a.id || '') + '\')">解决</button>' +
            '</span>' +
            '</div>';
    }).join('');
}

function ackAlarm(id) {
    API.acknowledgeAlarm(id).then(function(r) {
        if (r.success) { showToast('告警已确认', 'success'); loadAlarms(); }
        else showToast(r.error || '确认失败', 'error');
    });
}

function resolveAlarm(id) {
    API.resolveAlarm(id).then(function(r) {
        if (r.success) { showToast('告警已解决', 'success'); loadAlarms(); }
        else showToast(r.error || '解决失败', 'error');
    });
}

function loadAlarms() {
    API.getAlarms(5, false).then(renderAlarmList);
}

// ===== 系统状态条 =====
function updateSystemBar(data) {
    if (!data) return;
    var sysInfo = data.system_info || {};
    var nodesOk = (sysInfo.nodes_ok !== undefined ? sysInfo.nodes_ok : 2);
    var nodesTotal = (sysInfo.nodes_total !== undefined ? sysInfo.nodes_total : 2);
    var chOk = (sysInfo.channels_ok !== undefined ? sysInfo.channels_ok : 6);
    var chTotal = (sysInfo.channels_total !== undefined ? sysInfo.channels_total : 6);

    document.getElementById('sys-mode').textContent = data.operation_mode === 'development' ? '🔧 开发模式' : '🏭 部署模式';
    document.getElementById('sys-nodes').textContent = nodesOk + '/' + nodesTotal;
    document.getElementById('sys-dot-nodes').className = (nodesOk >= nodesTotal) ? 'sys-dot green' : 'sys-dot red';
    document.getElementById('sys-channels').textContent = chOk + '/' + chTotal;
    document.getElementById('sys-dot-channels').className = (chOk >= chTotal) ? 'sys-dot green' : 'sys-dot red';
}

// ===== WebSocket 订阅 =====
function bindWebSocket() {
    WS.on('business_update', function(msg) {
        var d = msg.data || {};
        if (d.bay) renderBayGrid(d.bay);
        if (d.dest) renderDestGrid(d.dest);
        if (d.agv) renderAgvCards(d.agv);
        if (d.active_instances) renderTaskTable(currentTaskTab, d.active_instances);
    });

    WS.on('alarm_update', function(msg) {
        loadAlarms();
        var count = msg.count || 0;
        document.getElementById('sys-alarm-count').textContent = count;
        if (count > 0) showToast(count + ' 条新告警', 'warning');
    });

    WS.on('config_updated', function(msg) {
        showToast('配置段 ' + (msg.section || '') + ' 已热加载', 'success');
        loadAllData();
    });

    WS.on('status_periodic', function(msg) {
        updateSystemBar(msg.data || {});
    });
}

// ===== 事件绑定 =====
function bindEvents() {
    // 仓位 click → Modal 编辑 cargo_type
    document.addEventListener('click', function(e) {
        var cell = e.target.closest('.bay-cell');
        if (!cell) return;
        var bayId = cell.getAttribute('data-bay-id');
        var ct = parseInt(cell.getAttribute('data-cargo-type')) || 1;
        if (!bayId) return;

        document.getElementById('bayEditTitle').textContent = '编辑 ' + bayId;
        document.getElementById('bayEditCargoType').value = ct;
        var modal = new bootstrap.Modal(document.getElementById('bayEditModal'));
        modal.show();

        document.getElementById('btn-save-bay').onclick = function() {
            var newCt = parseInt(document.getElementById('bayEditCargoType').value) || 1;
            var mappings = {};
            mappings[bayId] = newCt;
            API.setConfigBay(mappings).then(function(r) {
                if (r.success) {
                    showToast(bayId + ' 已更新为 type ' + newCt, 'success');
                    modal.hide();
                    loadAllData();
                } else {
                    showToast(r.error || '更新失败', 'error');
                }
            });
        };
    });

    // Tab 切换
    document.querySelectorAll('.tab-bar-inline .tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            document.querySelectorAll('.tab-bar-inline .tab').forEach(function(t) { t.classList.remove('active'); });
            this.classList.add('active');
            currentTaskTab = this.getAttribute('data-tab');
            API.getTaskInstances().then(function(d) { renderTaskTable(currentTaskTab, d); });
        });
    });

    // 强制触发
    document.getElementById('btn-force-trigger').addEventListener('click', function() {
        var src = document.getElementById('trigger-src').value;
        var dst = document.getElementById('trigger-dst').value;
        if (!src || !dst) { showToast('请选择起始仓和目的仓', 'warning'); return; }
        if (src === dst) { showToast('起始仓和目的仓不能相同', 'warning'); return; }

        var btn = this;
        btn.classList.add('loading');
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 执行中...';

        API.taskControl('force_trigger', { src_bay: src, dst_bay: dst }).then(function(r) {
            btn.classList.remove('loading');
            btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
            if (r.success) {
                showToast('任务已创建: ' + r.task_id, 'success');
                loadAllData();
            } else {
                showToast(r.error || '触发失败', 'error');
            }
        });
    });

    // 查询任务
    document.getElementById('btn-query-task').addEventListener('click', function() {
        var tid = document.getElementById('query-task-id').value.trim();
        if (!tid) { showToast('请输入 task_id', 'warning'); return; }
        API.taskControl('query', { task_id: tid }).then(function(r) {
            if (r.success) {
                var lines = [];
                for (var k in r) { if (k !== 'success') lines.push('<b>' + k + ':</b> ' + r[k]); }
                showToast('查询结果（见弹窗）', 'info');
                var modal = new bootstrap.Modal(document.getElementById('resultModal'));
                document.getElementById('resultModalTitle').textContent = '任务 ' + tid;
                document.getElementById('resultModalContent').innerHTML = lines.join('<br>');
                modal.show();
            } else {
                showToast(r.error || '未找到', 'error');
            }
        });
    });

    // 取消
    document.getElementById('btn-cancel-task').addEventListener('click', function() {
        var tid = document.getElementById('ctrl-task-id').value.trim();
        if (!tid) { showToast('请输入 task_id', 'warning'); return; }
        API.taskControl('cancel', { task_id: tid }).then(function(r) {
            if (r.success) { showToast('取消指令已发送: ' + tid, 'success'); loadAllData(); }
            else showToast(r.error || '取消失败', 'error');
        });
    });

    // 重试
    document.getElementById('btn-retry-task').addEventListener('click', function() {
        var tid = document.getElementById('ctrl-task-id').value.trim();
        if (!tid) { showToast('请输入 task_id', 'warning'); return; }
        API.taskControl('retry', { task_id: tid }).then(function(r) {
            if (r.success) { showToast('重试指令已发送: ' + tid, 'success'); loadAllData(); }
            else showToast(r.error || '重试失败', 'error');
        });
    });

    // 刷新
    document.getElementById('btn-refresh-all').addEventListener('click', function() {
        var btn = this;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 刷新中...';
        loadAllData();
        setTimeout(function() { btn.innerHTML = '<i class="fas fa-sync-alt"></i> 刷新全部状态'; }, 1000);
    });

    // 下拉选项填充
    populateSelects();
}

function populateSelects() {
    var srcSelect = document.getElementById('trigger-src');
    var dstSelect = document.getElementById('trigger-dst');

    var srcBays = [];
    Object.values(BAY_GROUP_MAP).forEach(function(ids) { srcBays = srcBays.concat(ids); });
    srcBays.forEach(function(id) {
        srcSelect.innerHTML += '<option value="' + id + '">' + id + '</option>';
    });

    var dstBays = [];
    Object.values(DEST_FLOOR_MAP).forEach(function(ids) { dstBays = dstBays.concat(ids); });
    dstBays.forEach(function(id) {
        dstSelect.innerHTML += '<option value="' + id + '">' + id + '</option>';
    });
}

// 外部调用
function queryTask(taskId) {
    document.getElementById('query-task-id').value = taskId;
    document.getElementById('btn-query-task').click();
}
```

### Step 4.3 — 验证

- 页面加载后仓位 24 格正确渲染（4 区 × 6 格横排）
- 目的仓 18 格按楼层分组（2F/3F/4F）
- AGV 卡片正确显示
- 点击仓位格 → Modal 弹窗 → 修改 cargo_type → PUT API → Toast 提示
- 强制触发任务：选择 src→dst → 执行 → Toast "任务已创建"
- WS `business_update` 推送 → 仓位/AGV/任务面板自动刷新

---

## Phase 5: 状态监控页 monitor.html + monitor.js (Day 3 下午)

### Step 5.1 — 替换 monitor.html

**文件**: `app_mgr_object/components/web/templates/monitor.html`

```html
{% extends "base.html" %}
{% block title %}状态监控 - 天眼运维监控{% endblock %}

{% block content %}
<div class="container-fluid px-3 pt-2">

    <!-- KPI 条 -->
    <div class="system-bar" id="monitor-bar">
        <div class="sys-item"><i class="fas fa-heartbeat"></i> 健康度 <b id="kpi-health">--</b>%</div>
        <div class="sys-divider"></div>
        <div class="sys-item"><span class="sys-dot green" id="dot-nodes"></span> 节点 <b id="kpi-nodes">--</b></div>
        <div class="sys-item"><span class="sys-dot green" id="dot-channels"></span> 通道 <b id="kpi-channels">--</b></div>
        <div class="sys-item"><span class="sys-dot green" id="dot-agv"></span> AGV <b id="kpi-agv">--</b></div>
        <span class="sys-spacer"></span>
        <div class="sys-item">WS 连接 <b id="kpi-ws">--</b></div>
    </div>

    <div class="row g-2">
        <!-- 系统健康详情 + Chart.js -->
        <div class="col-lg-6">
            <div class="card">
                <div class="card-header"><i class="fas fa-chart-line"></i> 系统健康趋势</div>
                <div class="card-body"><canvas id="healthChart" height="200"></canvas></div>
            </div>
        </div>

        <!-- 节点/通道详情 -->
        <div class="col-lg-6">
            <div class="card">
                <div class="card-header"><i class="fas fa-server"></i> 节点状态</div>
                <div class="card-body p-0">
                    <div class="task-table-wrap">
                        <table class="table task-table mb-0" id="nodes-table">
                            <thead><tr><th>节点</th><th>别名</th><th>状态</th><th>PID</th></tr></thead>
                            <tbody id="nodes-tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
            <div class="card mt-2">
                <div class="card-header"><i class="fas fa-wave-square"></i> 通道状态</div>
                <div class="card-body p-0">
                    <div class="task-table-wrap">
                        <table class="table task-table mb-0" id="channels-table">
                            <thead><tr><th>通道</th><th>别名</th><th>信号</th><th>状态</th></tr></thead>
                            <tbody id="channels-tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- AGV 详情 -->
        <div class="col-12">
            <div class="card">
                <div class="card-header"><i class="fas fa-robot"></i> AGV 详情</div>
                <div class="card-body p-0">
                    <div class="task-table-wrap">
                        <table class="table task-table mb-0" id="agv-table">
                            <thead><tr><th>ID</th><th>状态</th><th>电量</th><th>位置</th><th>当前任务</th><th>更新时间</th></tr></thead>
                            <tbody id="agv-tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="/static/js/api.js"></script>
<script src="/static/js/monitor.js"></script>
{% endblock %}
```

### Step 5.2 — 新建 monitor.js

**文件**: `app_mgr_object/components/web/static/js/monitor.js`

```javascript
/**
 * 状态监控页逻辑
 */

var healthChart = null;
var healthData = [];

document.addEventListener('DOMContentLoaded', function() {
    loadMonitorData();
    bindMonitorWS();
    setInterval(function() { API.getStatus().then(updateMonitorUI); }, 10000);
});

function loadMonitorData() {
    API.getStatus().then(updateMonitorUI);
    API.getAgvStatus().then(renderAgvTable);
}

function updateMonitorUI(data) {
    if (!data) return;

    // KPI 条
    document.getElementById('kpi-health').textContent = data.health_score || '--';
    var sysInfo = data.system_info || {};
    var nodesOk = sysInfo.nodes_ok || 0;
    var nodesTotal = sysInfo.nodes_total || 0;
    document.getElementById('kpi-nodes').textContent = nodesOk + '/' + nodesTotal;
    document.getElementById('dot-nodes').className = (nodesOk >= nodesTotal) ? 'sys-dot green' : 'sys-dot red';

    var chOk = sysInfo.channels_ok || 0;
    var chTotal = sysInfo.channels_total || 0;
    document.getElementById('kpi-channels').textContent = chOk + '/' + chTotal;
    document.getElementById('dot-channels').className = (chOk >= chTotal) ? 'sys-dot green' : 'sys-dot red';

    document.getElementById('kpi-ws').textContent = (sysInfo.ws_connections || 0);

    // 节点表格
    var nodes = data.nodes || {};
    var nodeKeys = Object.keys(nodes);
    var nodesTbody = document.getElementById('nodes-tbody');
    if (nodeKeys.length === 0) {
        nodesTbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">无节点数据</td></tr>';
    } else {
        nodesTbody.innerHTML = nodeKeys.map(function(k) {
            var n = nodes[k];
            var isOk = n.status === 'normal' || n.status === 'running';
            return '<tr>' +
                '<td><code>' + k + '</code></td>' +
                '<td>' + (n.alias || '--') + '</td>' +
                '<td><span class="sys-dot ' + (isOk ? 'green' : 'red') + '" style="display:inline-block;"></span> ' + (n.status || '--') + '</td>' +
                '<td>' + (n.pid || '--') + '</td>' +
                '</tr>';
        }).join('');
    }

    // 通道表格
    var channels = data.channels || {};
    var chKeys = Object.keys(channels);
    var chTbody = document.getElementById('channels-tbody');
    if (chKeys.length === 0) {
        chTbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">无通道数据</td></tr>';
    } else {
        chTbody.innerHTML = chKeys.map(function(k) {
            var c = channels[k];
            var hasSignal = c.signal_status;
            return '<tr>' +
                '<td><code>' + k + '</code></td>' +
                '<td>' + (c.alias || '--') + '</td>' +
                '<td><span class="sys-dot ' + (hasSignal ? 'green' : 'red') + '" style="display:inline-block;"></span></td>' +
                '<td><span class="status-badge ' + (hasSignal ? 'completed' : 'failed') + '">' + (hasSignal ? '正常' : '异常') + '</span></td>' +
                '</tr>';
        }).join('');
    }

    // 健康度趋势图
    updateHealthChart(data.health_score || 0);
}

function renderAgvTable(data) {
    var robots = (data && data.robots) ? data.robots : [];
    var tbody = document.getElementById('agv-tbody');
    document.getElementById('kpi-agv').textContent = robots.length;

    if (robots.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">无 AGV 数据</td></tr>';
        return;
    }
    tbody.innerHTML = robots.map(function(r) {
        return '<tr>' +
            '<td><b>' + r.robot_id + '</b></td>' +
            '<td><span class="status-badge ' + ((r.status === 'IDLE') ? 'completed' : 'running') + '">' + (r.status || '--') + '</span></td>' +
            '<td>' + (r.battery || '--') + '%</td>' +
            '<td>' + (r.position_code || '--') + '</td>' +
            '<td>' + (r.current_task_id || '--') + '</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">' + (r.update_time || '--') + '</td>' +
            '</tr>';
    }).join('');
}

function updateHealthChart(score) {
    var now = new Date().toLocaleTimeString('zh-CN', {hour12: false});
    healthData.push({ x: now, y: score });
    if (healthData.length > 30) healthData.shift();

    var ctx = document.getElementById('healthChart').getContext('2d');
    if (healthChart) healthChart.destroy();

    var gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, 'rgba(39,174,96,0.3)');
    gradient.addColorStop(1, 'rgba(39,174,96,0)');

    healthChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: '健康度 %',
                data: healthData,
                borderColor: '#27ae60',
                backgroundColor: gradient,
                fill: true,
                tension: 0.3,
                pointRadius: 2,
                pointBackgroundColor: '#27ae60',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { ticks: { color: '#5a6f85', font: { size: 10 } }, grid: { color: '#1e2d3d' } },
                y: { min: 0, max: 100, ticks: { color: '#5a6f85', font: { size: 10 }, callback: function(v) { return v + '%'; } }, grid: { color: '#1e2d3d' } }
            },
            plugins: { legend: { display: false } }
        }
    });
}

function bindMonitorWS() {
    WS.on('status_periodic', function(msg) { updateMonitorUI(msg.data || {}); });
    WS.on('status_update',   function(msg) { updateMonitorUI(msg.data || {}); });
    WS.on('business_update', function(msg) { if (msg.data && msg.data.agv) renderAgvTable(msg.data.agv); });
}
```

---

## Phase 6: 运维控制页告警增强 (Day 4 上午)

### Step 6.1 — 在 control.html 中嵌入告警面板

在 `control.html` 的 `{% block content %}` 末尾（`</div>` 之前），追加以下代码：

```html
<!-- ====== 告警管理面板 ====== -->
<div class="row g-2 mt-3">
    <div class="col-lg-8">
        <div class="card">
            <div class="card-header">
                <i class="fas fa-exclamation-triangle"></i> 告警管理
                <span class="tab-bar-inline">
                    <span class="tab active" data-alarm-tab="all">全部</span>
                    <span class="tab" data-alarm-tab="unack">未确认 <b id="alarm-tab-unack">0</b></span>
                </span>
            </div>
            <div class="card-body p-0">
                <div class="task-table-wrap">
                    <table class="table task-table mb-0" id="alarms-table">
                        <thead><tr><th>级别</th><th>消息</th><th>时间</th><th>状态</th><th>操作</th></tr></thead>
                        <tbody id="alarms-tbody"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div class="col-lg-4">
        <div class="card">
            <div class="card-header"><i class="fas fa-chart-bar"></i> 告警统计</div>
            <div class="card-body" id="alarm-stats">
                <div style="color:var(--text-muted);text-align:center;padding:20px;">加载中...</div>
            </div>
        </div>
        <div class="mt-2">
            <button class="btn btn-outline btn-sm w-100" id="btn-clear-alarms">
                <i class="fas fa-check-double"></i> 一键清除已解决告警
            </button>
        </div>
    </div>
</div>
```

### Step 6.2 — 新建 or 增强 control.js

在 `control.html` 的 `{% block extra_js %}` 中已有内联或外部 JS 的区域，追加告警逻辑：

```javascript
// ===== 告警管理逻辑（追加到 control.js 或 control.html 的 script 标签中） =====
var currentAlarmFilter = 'all';

function loadAlarmPanel() {
    API.getAlarms(100, true).then(function(d) {
        renderAlarmTable(d.alarms || []);
    });
    API.getAlarmStats().then(renderAlarmStats);
}

function renderAlarmTable(alarms) {
    var unackCount = alarms.filter(function(a) { return !a.acknowledged; }).length;
    document.getElementById('alarm-tab-unack').textContent = unackCount;

    var filtered = currentAlarmFilter === 'unack'
        ? alarms.filter(function(a) { return !a.acknowledged; })
        : alarms;

    var tbody = document.getElementById('alarms-tbody');
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:20px;">暂无告警</td></tr>';
        return;
    }
    tbody.innerHTML = filtered.map(function(a) {
        var levelClass = (a.level === 'critical') ? 'failed' : (a.level === 'warning') ? 'pending' : 'info';
        return '<tr>' +
            '<td><span class="status-badge ' + levelClass + '">' + (a.level || 'info') + '</span></td>' +
            '<td>' + (a.message || '--') + '</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">' + (a.time_str || '') + '</td>' +
            '<td>' + (a.acknowledged ? '已确认' : '<span style="color:var(--accent-orange);">未确认</span>') + '</td>' +
            '<td>' +
                (!a.acknowledged ? '<button class="btn btn-outline btn-sm" style="font-size:10px;padding:2px 8px;" onclick="ctrlAckAlarm(\'' + a.id + '\')">确认</button> ' : '') +
                (!a.resolved ? '<button class="btn btn-outline btn-sm" style="font-size:10px;padding:2px 8px;" onclick="ctrlResolveAlarm(\'' + a.id + '\')">解决</button>' : '') +
            '</td>' +
            '</tr>';
    }).join('');
}

function renderAlarmStats(stats) {
    var container = document.getElementById('alarm-stats');
    container.innerHTML = '<p style="margin:0;"><b>总告警数:</b> ' + (stats.total_alarms || 0) + '</p>' +
        '<p style="margin:0;color:var(--accent-orange);"><b>未确认:</b> ' + (stats.unacknowledged_alarms || 0) + '</p>' +
        '<p style="margin:0;color:var(--accent-red);"><b>未解决:</b> ' + (stats.unresolved_alarms || 0) + '</p>';
}

function ctrlAckAlarm(id) {
    API.acknowledgeAlarm(id).then(function(r) {
        if (r.success) { showToast('告警已确认', 'success'); loadAlarmPanel(); }
        else showToast(r.error || '确认失败', 'error');
    });
}

function ctrlResolveAlarm(id) {
    API.resolveAlarm(id).then(function(r) {
        if (r.success) { showToast('告警已解决', 'success'); loadAlarmPanel(); }
        else showToast(r.error || '解决失败', 'error');
    });
}

// Tab 切换
document.addEventListener('DOMContentLoaded', function() {
    // 告警 Tab
    document.querySelectorAll('[data-alarm-tab]').forEach(function(tab) {
        tab.addEventListener('click', function() {
            document.querySelectorAll('[data-alarm-tab]').forEach(function(t) { t.classList.remove('active'); });
            this.classList.add('active');
            currentAlarmFilter = this.getAttribute('data-alarm-tab');
            loadAlarmPanel();
        });
    });
    // 清除
    var clearBtn = document.getElementById('btn-clear-alarms');
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            API._post('/api/alarms/clear', {}).then(function(r) {
                if (r.success) { showToast('已清除 ' + (r.cleared || 0) + ' 条告警', 'success'); loadAlarmPanel(); }
                else showToast(r.error || '清除失败', 'error');
            });
        });
    }
    // 页面加载
    if (document.getElementById('alarms-table')) {
        loadAlarmPanel();
        WS.on('alarm_update', function() { loadAlarmPanel(); });
    }
});
```

**注意**：需在 `control.html` 的 `{% block extra_js %}` 中确保引入了 `api.js`：
```html
<script src="/static/js/api.js"></script>
```

---

## Phase 7: 联调验证 (Day 4 下午 ~ Day 5)

### Step 7.1 — 响应式适配检查

| 检查项 | 视口宽度 | 期望 |
|---|---|---|
| 仓位热力图 | < 992px | 四区上下堆叠，每区 6 格横排不变 |
| 任务操作区 | < 992px | 从右侧移到仓位区下方（全宽） |
| 系统状态条 | < 768px | 元素换行，字体缩小 |
| AGV 卡片 | < 576px | 纵向堆叠 |

### Step 7.2 — 端到端功能验证清单

| # | 场景 | 操作 | 期望 |
|---|---|---|---|
| 1 | 首页加载 | 访问 `/` | 四行布局渲染，仓位 24 格 + 目的仓 18 格 + AGV + 任务 + 告警 |
| 2 | 仓位编辑 | 点击仓位格 → 修改 type → 保存 | Toast "已更新"，仓位颜色变化 |
| 3 | 强制触发 | 选 src/dst → 执行触发 | Toast "任务已创建: WEB_..."，任务面板出现新行 |
| 4 | 查询任务 | 输入 task_id → 查询 | Modal 弹窗显示任务详情 |
| 5 | 取消任务 | 输入 task_id → 取消 | Toast "取消指令已发送" |
| 6 | 重试任务 | 输入 task_id → 重试 | Toast "重试指令已发送" |
| 7 | WS 推送 | 触发业务事件 | 仓位/AGV/任务面板自动刷新（不刷新页面） |
| 8 | 告警确认 | 首页 → 告警栏 [确认] | 告警行消失/变灰 |
| 9 | 告警管理 | /control → 告警面板 | 列表渲染 + 确认/解决/清除 |
| 10 | 状态监控 | /monitor | KPI 条 + Chart.js 趋势图 + 节点/通道表格 + AGV 表格 |
| 11 | WS 断线 | 关闭服务 | 右下角变红 "断开"，重启后自动重连变绿 |
| 12 | API 失败降级 | 服务未就绪 | 页面显示 "加载中..." 或 "暂无数据"，不崩溃 |

### Step 7.3 — 浏览器兼容

- Chrome 90+ ✅
- Edge 90+ ✅
- Firefox 90+ ✅（检查 CSS 变量兼容性）

---

## 8. 完整文件变更清单

| # | 文件 | 操作 | 预估行数 |
|---|---|---|---|
| 1 | `static/css/custom.css` | 🔴 完整替换 | ~350 → ~450 |
| 2 | `static/js/api.js` | 🟢 新建 | ~70 |
| 3 | `static/js/websocket.js` | 🟢 新建 | ~60 |
| 4 | `static/js/dashboard.js` | 🟢 新建 | ~380 |
| 5 | `static/js/monitor.js` | 🟢 新建 | ~150 |
| 6 | `templates/base.html` | 🔴 完整替换 | ~130 |
| 7 | `templates/index.html` | 🔴 完整替换 | ~250 |
| 8 | `templates/monitor.html` | 🔴 完整替换 | ~80 |
| 9 | `templates/control.html` | 🟡 追加告警面板 HTML + JS | +120 |
| **后端** | — | **无需改动** | **0** |

---

## 9. 注意事项

1. **Bootstrap `.table-dark`**：在 custom.css 中，表格使用 `var(--bg-secondary)` 背景和 `--text-primary` 文字色，不使用 Bootstrap 的 `.table-dark` 类，避免样式冲突。

2. **Chart.js 深色适配**：在 monitor.js 中，Chart.js 的 scale ticks 和 grid 颜色使用 `--text-muted` 和 `--border` 对应的硬编码色值（`#5a6f85` / `#1e2d3d`），因为 Chart.js 不读 CSS 变量。

3. **jQuery 未使用**：本方案全程使用原生 JS（`fetch` / `document.querySelector` / `addEventListener`），不依赖 jQuery。base.html 中仍加载 jQuery 是为兼容现有 control.html 中的旧代码。

4. **index.html 中 Modal HTML**：index.html 底部包含一个 `#bayEditModal` Modal 和一个 `#resultModal`（继承自 base.html），用于仓位编辑和查询结果显示。

5. **control.html 改动范围最小**：只追加告警面板 HTML 块 + 告警 JS 逻辑，不动现有启停操作代码。

6. **alarms.html 保留**：作为独立告警页面的备选项保留，不做改动。

---

> **文档结束** — 严格按照上述 7 个 Phase 顺序执行，每个 Phase 完成后验证一次。后端零改动，前端 9 个文件变更，总工期 5 天。
