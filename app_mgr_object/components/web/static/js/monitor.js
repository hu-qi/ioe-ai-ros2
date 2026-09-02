/**
 * 状态监控页逻辑
 */

var healthChart = null;
var healthData = [];

document.addEventListener('DOMContentLoaded', function() {
    // 骨架屏：tbody 先显骨架行，数据就绪自动替换（doc/页面切换组件逐步加载-体验优化）
    if (window.Skeleton) {
        window.Skeleton.fillTable(document.getElementById('nodes-tbody'), 4);
        window.Skeleton.fillTable(document.getElementById('channels-tbody'), 4);
        window.Skeleton.fillTable(document.getElementById('agv-tbody'), 3);
    }
    loadMonitorData();
    loadNodesStatus();
    loadChannelsStatus();
    loadHealthScore();
    bindMonitorWS();
    // 主数据就绪（节点+通道）→ 隐藏顶部加载条；5s 兜底（doc/页面切换组件逐步加载-体验优化）
    var done = false;
    Promise.all([
        fetch('/api/ops/nodes').then(function(r) { return r.json(); }).catch(function() { return null; }),
        fetch('/api/ops/channels').then(function(r) { return r.json(); }).catch(function() { return null; })
    ]).then(function() { if (!done) { done = true; if (window.pageLoaded) window.pageLoaded(); } });
    setTimeout(function() { if (!done) { done = true; if (window.pageLoaded) window.pageLoaded(); } }, 5000);
    setInterval(function() {
        API.getStatus().then(updateMonitorUI);
        loadNodesStatus();
        loadChannelsStatus();
        loadHealthScore();
    }, 10000);
});

function loadMonitorData() {
    API.getStatus().then(updateMonitorUI);
    API.getAgvStatus().then(renderAgvTable);
}

function updateMonitorUI(data) {
    if (!data) return;
    // KPI 健康度/节点/通道由 loadHealthScore/loadNodesStatus/loadChannelsStatus 设置
    var sysInfo = data.system_info || {};
    document.getElementById('kpi-ws').textContent = (sysInfo.ws_connections || 0);
}

// ===== P3 v3：工具函数（doc/P3 v3） =====
// 标准时间格式化（update_time 为 Unix 秒；>1e12 视为毫秒）
function fmtTime(ts) {
    if (!ts) return '--';
    var ms = (typeof ts === 'number' && ts > 1e12) ? ts : ts * 1000;
    var d = new Date(ms);
    if (isNaN(d.getTime())) return '--';
    var p = function(n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
        ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}

// OPS watchdog 状态 → 中文 + 颜色类（枚举 online/degraded/offline/unknown）
function wdStatusMap(st) {
    st = st || 'unknown';
    if (st === 'online')   return { text: '在线', cls: 'green' };
    if (st === 'degraded') return { text: '降级', cls: 'orange' };
    if (st === 'offline')  return { text: '离线', cls: 'red' };
    return { text: '未知', cls: '' };
}

// ===== P3：节点状态统一数据源（OPS 优先 + 本地降级，doc/P3） =====
function loadNodesStatus() {
    fetch('/api/ops/nodes')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data && data.success && !data.offline && data.nodes && data.nodes.length > 0) {
                renderNodesOps(data.nodes);     // OPS 权威源
            } else {
                renderNodesLocal();             // 本地降级（自探测）
            }
        })
        .catch(function() { renderNodesLocal(); });
}

function renderNodesOps(nodes) {
    var badge = document.getElementById('nodes-source-badge');
    if (badge) { badge.textContent = 'OPS 权威源'; badge.className = 'source-badge ops'; }
    var thead = document.getElementById('nodes-thead');
    if (thead) thead.innerHTML = '<tr><th>节点</th><th>OPS 注册名</th><th>看门狗状态</th><th>健康类型</th></tr>';
    var tbody = document.getElementById('nodes-tbody');
    if (!tbody) return;
    if (!nodes.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">无节点数据</td></tr>';
        return;
    }
    tbody.innerHTML = nodes.map(function(n) {
        var st = n.watchdog_status || 'unknown';
        var m = wdStatusMap(st);                       // v3：OPS 枚举 → 中文 + 色
        return '<tr>' +
            '<td><b>' + (n.display || n.name || '--') + '</b></td>' +
            '<td><code>' + (n.name || '--') + '</code></td>' +
            '<td>' + (m.cls ? '<span class="sys-dot ' + m.cls + '" style="display:inline-block;"></span> ' : '') + m.text + '</td>' +
            '<td><span class="text-dim">' + (n.health_type || '--') + '</span></td>' +
            '</tr>';
    }).join('');
    // KPI 节点数（v3：OPS 枚举 online）
    var online = nodes.filter(function(n) { return n.watchdog_status === 'online'; }).length;
    document.getElementById('kpi-nodes').textContent = online + '/' + nodes.length;
    document.getElementById('dot-nodes').className = (online >= nodes.length && nodes.length > 0) ? 'sys-dot green' : 'sys-dot red';
}

function renderNodesLocal() {
    var badge = document.getElementById('nodes-source-badge');
    if (badge) { badge.textContent = '本地降级'; badge.className = 'source-badge local'; }
    var thead = document.getElementById('nodes-thead');
    if (thead) thead.innerHTML = '<tr><th>节点</th><th>别名</th><th>状态</th><th>PID</th></tr>';
    API.getStatus().then(function(data) {
        var tbody = document.getElementById('nodes-tbody');
        if (!tbody) return;
        // 修复：正确解析 monitored_nodes（P3 doc；原遍历 data.nodes 为 bug）
        var sysInfo = (data && data.system_info) || {};
        var monitored = (data && data.nodes && data.nodes.monitored_nodes) || {};
        var keys = Object.keys(monitored);
        if (keys.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">无节点数据</td></tr>';
        } else {
            tbody.innerHTML = keys.map(function(k) {
                var n = monitored[k] || {};
                var isOk = n.status === 'normal' || n.status === 'running';
                return '<tr>' +
                    '<td><code>' + k + '</code></td>' +
                    '<td><span class="text-dim">' + (n.alias || '--') + '</span></td>' +
                    '<td><span class="sys-dot ' + (isOk ? 'green' : 'red') + '" style="display:inline-block;"></span> ' + (isOk ? '在线' : '离线') + '</td>' +
                    '<td><span class="text-dim">' + (n.pid || '--') + '</span></td>' +
                    '</tr>';
            }).join('');
        }
        // KPI 节点数（本地）
        var nodesOk = sysInfo.nodes_ok || 0;
        var nodesTotal = sysInfo.nodes_total || 0;
        document.getElementById('kpi-nodes').textContent = nodesOk + '/' + nodesTotal;
        document.getElementById('dot-nodes').className = (nodesOk >= nodesTotal) ? 'sys-dot green' : 'sys-dot red';
    }).catch(function() {
        var tbody = document.getElementById('nodes-tbody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">本地状态不可用</td></tr>';
    });
}

// ===== P3 v2：通道状态（OPS 帧龄优先 + 本地降级，doc/P3 v2） =====
function loadChannelsStatus() {
    fetch('/api/ops/channels')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data && data.success && !data.offline && data.channels) {
                renderChannelsOps(data);
            } else {
                renderChannelsLocal();
            }
        })
        .catch(function() { renderChannelsLocal(); });
}

function renderChannelsOps(data) {
    var channels = data.channels || [];
    var total = data.total || channels.length;
    var online = data.online_count || 0;
    // 角标：通道状态数据源
    var srcEl = document.createElement('span');
    srcEl.className = 'source-badge ops';
    srcEl.textContent = 'OPS';
    var hdr = document.querySelector('#channels-card .card-header');
    if (hdr) { hdr.querySelectorAll('.source-badge').forEach(function(s) { s.remove(); }); hdr.appendChild(srcEl); }
    var tbody = document.getElementById('channels-tbody');
    if (!tbody) return;
    if (!channels.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">无通道数据</td></tr>';
        return;
    }
    tbody.innerHTML = channels.map(function(c) {
        var online2 = !!c.online;
        var age = (c.frame_age_ms == null) ? '--' : Math.round(c.frame_age_ms) + 'ms';
        return '<tr>' +
            '<td><code>CH' + c.ch + '</code></td>' +
            '<td>OPS 通道 ' + c.ch + '</td>' +
            '<td><span class="sys-dot ' + (online2 ? 'green' : 'red') + '" style="display:inline-block;"></span></td>' +
            '<td><span class="status-badge ' + (online2 ? 'completed' : 'failed') + '">' + (online2 ? '在线' : '离线') + '</span> <span class="text-dim" style="font-size:10px;">帧龄 ' + age + '</span></td>' +
            '</tr>';
    }).join('');
    // KPI 通道数
    document.getElementById('kpi-channels').textContent = online + '/' + total;
    document.getElementById('dot-channels').className = (online >= total && total > 0) ? 'sys-dot green' : 'sys-dot red';
}

function renderChannelsLocal() {
    var hdr = document.querySelector('#channels-card .card-header');
    if (hdr) { hdr.querySelectorAll('.source-badge').forEach(function(s) { s.remove(); }); }
    API.getStatus().then(function(data) {
        var tbody = document.getElementById('channels-tbody');
        if (!tbody) return;
        var sysInfo = (data && data.system_info) || {};
        var channels = (data && data.channels) || {};
        var chKeys = Object.keys(channels);
        var chOk = sysInfo.channels_ok || 0;
        var chTotal = sysInfo.channels_total || 0;
        if (chKeys.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">无通道数据</td></tr>';
        } else {
            tbody.innerHTML = chKeys.map(function(k) {
                var c = channels[k] || {};
                var hasSignal = c.signal_status;
                return '<tr>' +
                    '<td><code>' + k + '</code></td>' +
                    '<td>' + (c.alias || '--') + '</td>' +
                    '<td><span class="sys-dot ' + (hasSignal ? 'green' : 'red') + '" style="display:inline-block;"></span></td>' +
                    '<td><span class="status-badge ' + (hasSignal ? 'completed' : 'failed') + '">' + (hasSignal ? '正常' : '异常') + '</span></td>' +
                    '</tr>';
            }).join('');
        }
        document.getElementById('kpi-channels').textContent = chOk + '/' + chTotal;
        document.getElementById('dot-channels').className = (chOk >= chTotal && chTotal > 0) ? 'sys-dot green' : 'sys-dot red';
    }).catch(function() {
        var tbody = document.getElementById('channels-tbody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">本地通道状态不可用</td></tr>';
    });
}

// ===== P3 v2：健康度计分（OPS 节点/通道 + 本地服务；OPS 不可用回退本地，doc/P3 v2） =====
function loadHealthScore() {
    var scoreLocal = function(score) {
        document.getElementById('kpi-health').textContent = score == null ? '--' : score;
        updateHealthChart(score || 0);
    };
    // 加载优化：OPS 节点/通道先算（不等待本地 status），本地服务健康异步修正（doc/前端页面加载优化）
    Promise.all([
        fetch('/api/ops/nodes').then(function(r) { return r.json(); }).catch(function() { return null; }),
        fetch('/api/ops/channels').then(function(r) { return r.json(); }).catch(function() { return null; })
    ]).then(function(results) {
        var nodesData = results[0];
        var chData = results[1];
        var opsOk = !!(nodesData && nodesData.success && !nodesData.offline &&
                       chData && chData.success && !chData.offline);
        if (!opsOk) {
            // OPS 不可用：用本地 health_score（异步获取，不阻塞其他渲染）
            API.getStatus().then(function(local) {
                scoreLocal(local && local.health_score != null ? local.health_score : 0);
            }).catch(function() { scoreLocal(0); });
            return;
        }
        // 节点健康：OPS watchdog online / total（v3：OPS 枚举为 online/degraded/offline）
        var nodes = nodesData.nodes || [];
        var nOnline = nodes.filter(function(n) { return n.watchdog_status === 'online'; }).length;
        var nodeHealth = nodes.length ? (nOnline / nodes.length * 100) : 100;
        // 通道健康：OPS 帧龄在线 / total
        var channels = chData.channels || [];
        var cOnline = channels.filter(function(c) { return c.online; }).length;
        var chHealth = channels.length ? (cOnline / channels.length * 100) : 100;
        // 服务健康：先默认 100（本地 services 异步修正）
        var score = Math.round(nodeHealth * 0.4 + chHealth * 0.4 + 100 * 0.2);
        scoreLocal(score);
        // 本地服务健康异步修正（不阻塞首算）
        API.getStatus().then(function(local) {
            var services = (local && local.services) || {};
            var svcKeys = Object.keys(services);
            if (svcKeys.length) {
                var svcRunning = svcKeys.filter(function(k) { return services[k].is_running; }).length;
                var svcHealth = svcRunning / svcKeys.length * 100;
                scoreLocal(Math.round(nodeHealth * 0.4 + chHealth * 0.4 + svcHealth * 0.2));
            }
        }).catch(function() {});
    });
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
        var isIdle = (r.status || '').toUpperCase() === 'IDLE';
        return '<tr>' +
            '<td><b>' + r.robot_id + '</b></td>' +
            '<td><span class="status-badge ' + (isIdle ? 'completed' : 'running') + '">' + (r.status || '--') + '</span></td>' +
            '<td>' + (r.battery || '--') + '%</td>' +
            '<td><span class="text-dim">' + (r.position_code || '--') + '</span></td>' +
            '<td><span class="text-dim">' + (r.current_task_id || '--') + '</span></td>' +
            '<td><span class="text-dim">' + fmtTime(r.update_time) + '</span></td>' +
            '</tr>';
    }).join('');
}

function getChartColors() {
    var isLight = document.documentElement.getAttribute('data-theme') === 'light';
    return {
        lineColor: '#27ae60',
        gridColor:   isLight ? '#e0e4e8' : '#1e2d3d',
        tickColor:   isLight ? '#8896a6' : '#5a6f85',
        fillStart:   isLight ? 'rgba(39,174,96,0.08)' : 'rgba(39,174,96,0.3)',
        fillEnd:     isLight ? 'rgba(39,174,96,0)'     : 'rgba(39,174,96,0)',
    };
}

function updateHealthChart(score) {
    var colors = getChartColors();
    var now = new Date().toLocaleTimeString('zh-CN', {hour12: false});
    healthData.push({ x: now, y: score });
    if (healthData.length > 30) healthData.shift();

    var ctx = document.getElementById('healthChart').getContext('2d');
    if (healthChart) healthChart.destroy();

    var gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, colors.fillStart);
    gradient.addColorStop(1, colors.fillEnd);

    healthChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: '健康度 %',
                data: healthData,
                borderColor: colors.lineColor,
                backgroundColor: gradient,
                fill: true,
                tension: 0.3,
                pointRadius: 2,
                pointBackgroundColor: colors.lineColor,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { ticks: { color: colors.tickColor, font: { size: 10 } }, grid: { color: colors.gridColor } },
                y: { min: 0, max: 100, ticks: { color: colors.tickColor, font: { size: 10 }, callback: function(v) { return v + '%'; } }, grid: { color: colors.gridColor } }
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