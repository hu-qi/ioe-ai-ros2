/**
 * 仪表盘页面逻辑
 * 数据驱动渲染：API 拉取 → DOM 渲染 → WS 推送局部刷新
 */

// ===== 仓位编排：区域别名渲染（localStorage UI 展示名，doc/仓位名称类型编排） =====
function applyZoneNames() {
    try {
        var map = JSON.parse(localStorage.getItem('zone_names') || '{}');
        Object.keys(map).forEach(function(zone) {
            var el = document.querySelector('.zone-title[data-zone="' + zone + '"]');
            if (el && map[zone]) el.textContent = map[zone];
        });
    } catch (e) {}
}

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
    // 骨架屏：容器先显骨架，API 完成自动替换（doc/页面切换组件逐步加载-体验优化）
    if (window.Skeleton) {
        ['bay-zone-a', 'bay-zone-b', 'bay-zone-c', 'bay-zone-d',
         'dest-zone-2f', 'dest-zone-3f', 'dest-zone-4f'].forEach(function(id) {
            window.Skeleton.fill(document.getElementById(id), 2);
        });
        window.Skeleton.fill(document.getElementById('agv-cards'), 2);
        window.Skeleton.fillTable(document.getElementById('task-tbody'), 4);
        window.Skeleton.fill(document.getElementById('alarm-list'), 3);
    }
    loadAllData();
    bindEvents();
    bindWebSocket();
    bindPairPanel();   // P1 v6：浮动匹配面板交互（折叠 + 拖动）
    updateClockDashboard();
    setInterval(updateClockDashboard, 1000);
});

function updateClockDashboard() {
    var el = document.getElementById('sys-clock');
    if (el) el.textContent = new Date().toLocaleString('zh-CN', {hour12: false});
}

// ===== 数据加载 =====
function loadAllData() {
    // 仓位编排：加载显示定义类型（bay_configs，仅显示对比用；AI 话题为准）+ 应用区域别名
    API.getConfigBay().then(function(r) {
        window.definedBayTypes = (r && r.mappings) || {};
        // 类型变化后重渲染仓位（badge）
        API.getBayStatus().then(function(d) { if (d && d.bays) renderBayGrid(d); });
    }).catch(function() {});
    applyZoneNames();
    // 加载优化：业务快接口先渲染（首屏秒开），/api/status 与告警异步填充（doc/前端页面加载优化）
    Promise.all([
        API.getBayStatus(),
        API.getDestStatus(),
        API.getAgvStatus(),
        API.getTaskInstances(),
        API.getTaskQueue(),
        API.getTaskStatistics()       // 独立统计接口（doc/触发机制 §10.3.2，替代依赖 business summary）
    ]).then(function(results) {
        renderBayGrid(results[0]);
        renderDestGrid(results[1]);
        renderAgvCards(results[2]);
        renderTaskTable(currentTaskTab, results[3]);
        renderQueuePreview(results[4]);
        renderTaskStats(results[5]);   // 任务信息栏统计（今日完成/执行中/异常/已锁定目的仓）
        // P1 配对连线：初始加载已有队列/活跃实例（doc/P1 规范 §7.2）
        if (window.PairLines) {
            window.PairLines.update(buildPairLines({
                task_queue: results[4] || {},
                active_instances: results[3] || {},
                recent_failures: []
            }));
        }
        // P1 v5：浮动匹配信息面板初始渲染
        renderPairPanel({
            task_queue: results[4] || {},
            active_instances: results[3] || {},
            recent_failures: []
        });
        // 主业务就绪 → 隐藏顶部加载条（doc/页面切换组件逐步加载-体验优化）
        if (window.pageLoaded) window.pageLoaded();
    }).catch(function(e) {
        console.error('Initial business load failed:', e);
        if (window.pageLoaded) window.pageLoaded();
    });
    // 告警 + 系统状态异步填充（不阻塞业务首屏）
    API.getAlarms(5, false).then(function(d) { renderAlarmList(d); renderSystemInfoPanel(d); })
        .catch(function(e) { console.error('Alarm load failed:', e); });
    API.getStatus().then(updateSystemBar)
        .catch(function(e) { console.error('Status load failed:', e); });
}

// ===== 起始仓位渲染 =====
function renderBayGrid(data) {
    var bays = (data && data.bays) ? data.bays : [];
    // 渲染防御（doc/仓位名称类型编排 §十一）：话题仓位数量异常（>24）提示，防 rtsp 配置异常新增
    if (bays.length > 24 && !window._bayCountWarned) {
        window._bayCountWarned = true;
        console.warn('[仓位编排] 话题仓位数量异常: ' + bays.length + '（预期 ≤24），检查 rtsp polygon_chX_names 配置');
        if (window.showToast) showToast('话题仓位数量异常（' + bays.length + '），可能 rtsp 名称配置有误', 'warning');
    }
    // 仓位编排：以话题 bay_id 为权威动态渲染（doc/仓位名称类型编排 §十）——前缀 A/B/C/D 分区，无法匹配依序补位
    var zoneOrder = ['bay-zone-a', 'bay-zone-b', 'bay-zone-c', 'bay-zone-d'];
    var zoneByPrefix = { A: 'bay-zone-a', B: 'bay-zone-b', C: 'bay-zone-c', D: 'bay-zone-d' };
    var groups = {};
    zoneOrder.forEach(function(z) { groups[z] = []; });
    var leftover = [];
    bays.forEach(function(b) {
        var p = (b.bay_id || '')[0];
        if (zoneByPrefix[p]) groups[zoneByPrefix[p]].push(b);
        else leftover.push(b);
    });
    zoneOrder.forEach(function(zoneId) {
        var container = document.getElementById(zoneId);
        if (!container) return;
        // 无法匹配前缀的依序补入未满区（每区 6 格布局）
        while (leftover.length && groups[zoneId].length < 6) groups[zoneId].push(leftover.shift());
        // 仓位编排：组内按编号数字升序（改名后新名不落末尾，doc/仓位改名缓存无缝承接 §九）
        groups[zoneId].sort(baySortByNum);
        if (groups[zoneId].length) {
            container.innerHTML = groups[zoneId].map(renderBayCell).join('');
        } else {
            // 空态回退默认 ids 占位
            container.innerHTML = (BAY_GROUP_MAP[zoneId] || []).map(function(id) {
                return '<div class="bay-cell bay-idle" style="background:#333"><span class="bay-label">' + id + '</span></div>';
            }).join('');
        }
    });
    // P1 配对连线：仓位重渲染后重算坐标
    if (window.PairLines) window.PairLines.refresh();
}

// 仓位编排：按编号数字部分升序排序（A1000 < A1002 < A1003...；T2001 < T2002...），同数字字典序兜底
function baySortByNum(a, b) {
    var na = parseInt(String(a.bay_id || '').replace(/[^0-9]/g, '')) || 0;
    var nb = parseInt(String(b.bay_id || '').replace(/[^0-9]/g, '')) || 0;
    if (na !== nb) return na - nb;
    return String(a.bay_id || '').localeCompare(String(b.bay_id || ''));
}

function renderBayCell(bay) {
    var color = CARGO_COLORS[bay.cargo_type] || '#555';
    var cssClass = 'bay-cell';
    if (bay.bind_status === 1) cssClass += ' bay-bound';
    else if (bay.bind_status === 2) cssClass += ' bay-binding';
    else cssClass += ' bay-idle';
    if (bay.in_task) cssClass += ' bay-in-task';

    // 仓位编排：AI 检测类型与显示定义类型不一致 → badge 标识（仅显示，不影响业务，doc/仓位名称类型编排）
    var mismatch = '';
    var defType = (window.definedBayTypes || {})[bay.bay_id];
    if (defType && bay.cargo_type && Number(defType) !== Number(bay.cargo_type)) {
        mismatch = '<span class="bay-type-mismatch" title="AI 检测类型 ' + bay.cargo_type + ' ≠ 显示定义 ' + defType + '">!</span>';
    }
    return '<div class="' + cssClass + '" style="background:' + color + '"' +
        ' data-bay-id="' + bay.bay_id + '"' +
        ' data-cargo-type="' + bay.cargo_type + '"' +
        ' title="' + bay.bay_id + ' | AI类型:' + bay.cargo_type + (defType ? ' | 显示定义:' + defType : '') + ' | ' + (bay.bind_status_label || '') + '">' +
        '<span class="bay-label">' + bay.bay_id + '</span>' + mismatch +
        (bay.bind_status === 1 ? '<span class="bay-dot"></span>' : '') +
        '</div>';
}

// ===== 目的仓渲染 =====
function renderDestGrid(data) {
    var bays = (data && data.bays) ? data.bays : [];
    // 渲染防御（doc/仓位名称类型编排 §十一）：话题目的仓数量异常（>18）提示
    if (bays.length > 18 && !window._destCountWarned) {
        window._destCountWarned = true;
        console.warn('[仓位编排] 话题目的仓数量异常: ' + bays.length + '（预期 ≤18）');
        if (window.showToast) showToast('话题目的仓数量异常（' + bays.length + '）', 'warning');
    }
    // 仓位编排：以话题 bay_id 为权威动态渲染（doc/仓位名称类型编排 §十）——T2/T3/T4 楼层前缀分组，无法匹配依序补位
    var zoneOrder = ['dest-zone-2f', 'dest-zone-3f', 'dest-zone-4f'];
    var groups = {};
    zoneOrder.forEach(function(z) { groups[z] = []; });
    var leftover = [];
    bays.forEach(function(b) {
        var m = /^T([234])/.exec(b.bay_id || '');
        if (m && m[1] === '2') groups['dest-zone-2f'].push(b);
        else if (m && m[1] === '3') groups['dest-zone-3f'].push(b);
        else if (m && m[1] === '4') groups['dest-zone-4f'].push(b);
        else leftover.push(b);
    });
    zoneOrder.forEach(function(zoneId) {
        var container = document.getElementById(zoneId);
        if (!container) return;
        while (leftover.length && groups[zoneId].length < 6) groups[zoneId].push(leftover.shift());
        groups[zoneId].sort(baySortByNum);
        var cells = groups[zoneId].map(function(bay) {
            // 四色状态（doc/触发机制 §九）：empty 空·绿 / occupied 有货占用·灰黑 /
            // reserved 已匹对锁定·橙 / unbind 解绑释放·蓝
            var st = bay.status || (bay.is_empty ? 'empty' : 'occupied');
            var cssClass = 'dest-cell ' + st;
            // data-bay-id：P1 配对连线定位用（doc/P1 规范）
            return '<div class="' + cssClass + '" data-bay-id="' + bay.bay_id + '" title="' +
                ({ empty: '空（可用）', occupied: '有货占用', reserved: '已匹对锁定', unbind: '解绑释放（可再匹配）' }[st] || st) + '">' +
                bay.bay_id +
                '<span class="dest-cargo">' + (bay.cargo_type || '') + '</span></div>';
        });
        if (cells.length) {
            container.innerHTML = cells.join('');
        } else {
            // 空态回退默认 ids 占位
            container.innerHTML = (DEST_FLOOR_MAP[zoneId] || []).map(function(id) {
                return '<div class="dest-cell occupied" data-bay-id="' + id + '">' + id + '</div>';
            }).join('');
        }
    });
    // P1 配对连线：目标仓重渲染后重算坐标
    if (window.PairLines) window.PairLines.refresh();
}

// ===== AGV 渲染（doc/AGV状态卡改造 §3.1：顶部两台 AGV 简单状态） =====
function renderAgvCards(data) {
    var robots = (data && data.robots) ? data.robots : [];
    var summary = document.getElementById('sys-agv');
    var detail = document.getElementById('sys-agv-detail');
    if (!summary) return;
    if (robots.length === 0) {
        summary.textContent = '--';
        if (detail) detail.style.display = 'none';
        return;
    }
    summary.textContent = robots.length + '台';
    if (detail) {
        var parts = robots.slice(0, 2).map(function(r) {
            var st = (r.status || '').toUpperCase();
            var busy = !!r.current_task_id;
            var label, cls;
            if (st === 'AVAILABLE' && !busy) { label = '可用'; cls = 'agv-mini available'; }
            else if (st === 'OFFLINE' || st === 'DISCONNECTED') { label = '离线'; cls = 'agv-mini offline'; }
            else { label = '任务中'; cls = 'agv-mini busy'; }
            return '<span class="' + cls + '">AGV' + r.robot_id + '·' + label + '</span>';
        });
        detail.innerHTML = parts.join('<span style="opacity:.5;margin:0 4px;">|</span>');
        detail.style.display = '';
    }
}

// ===== 任务信息栏统计（doc/AGV状态卡改造 §3.2 / doc/58 三态渲染） =====
function renderTaskStats(data) {
    var el = document.getElementById('task-stats');
    if (!el) return;
    var stats = (data && data.task_stats) ? data.task_stats : data;
    if (!stats || typeof stats !== 'object') return;
    // doc/58 R-01：数据源未就绪（workflow_engine 未加载/未激活/统计异常）
    if (stats.ready === false) {
        el.innerHTML = '<div class="ts-empty">统计初始化中…（数据源未就绪）</div>';
        return;
    }
    // 接口异常（API 层返回 {success:false, error}）
    if (stats.error) {
        el.innerHTML = '<div class="ts-empty">暂无任务统计</div>';
        return;
    }
    function _num(v) { return (v == null) ? 0 : v; }
    var items = [
        { label: '今日完成', value: _num(stats.today_completed), cls: '' },
        { label: '执行中', value: _num(stats.executing), cls: 'pulse' },
        { label: '异常', value: _num(stats.failed), cls: 'error' },
        { label: '已锁定目的仓', value: _num(stats.locked_dest), cls: 'locked' },
    ];
    el.innerHTML = items.map(function(it) {
        return '<div class="ts-item"><div class="ts-value ' + it.cls + '">' + it.value + '</div>' +
            '<div class="ts-label">' + it.label + '</div></div>';
    }).join('');
}

// ===== 任务面板 =====
var STATUS_BADGE_MAP = {
    'running': 'running', 'calling_rcs': 'running', 'monitoring': 'running',
    'compensating_query': 'running', 'releasing': 'running', 'releasing_and_done': 'running',
    'auto_recovery': 'running', 'warn_pause': 'pending', 'manual_intervention': 'pending',
    'completed': 'completed', 'failed': 'failed', 'idle': 'idle', 'cancelled': 'idle',
    'SUCCESS': 'completed', 'FAILED': 'failed', 'RUNNING': 'running',
    'MANUAL': 'pending', 'DISPATCHING': 'running', 'PENDING': 'pending', 'CANCELLED': 'idle'
};

// 活跃实例 current_state → 中文（doc/62）
var STATE_CN = {
    'calling_rcs':         '下发中',
    'monitoring':          '执行中',
    'compensating_query':  '补偿查询',
    'warn_pause':          '警告暂停',
    'releasing':           '释放中',
    'releasing_and_done':  '释放中',
    'manual_intervention': '人工介入',
    'auto_recovery':       '自动恢复',
    'completed':           '已完成',
    'failed':              '失败',
    'cancelled':           '已取消'
};

// 历史/DB status → 中文（doc/62）
var STATUS_CN = {
    'SUCCESS':     '已完成',
    'FAILED':      '失败',
    'RUNNING':     '执行中',
    'DISPATCHING': '下发中',
    'MANUAL':      '人工介入',
    'PENDING':     '待处理',
    'CANCELLED':   '已取消'
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

// 终态任务集合：完成后不应停留在“活跃”栏
var TERMINAL_TASK_STATUS = { 'completed': true, 'failed': true, 'cancelled': true };

function renderActiveTasks(data) {
    var instances = (data && data.instances) ? data.instances : [];
    // 过滤终态（防御：即使后端推送时序未修复，也不在活跃栏残留）
    instances = instances.filter(function(t) {
        return !TERMINAL_TASK_STATUS[(t.status || '').toLowerCase()];
    });
    var tbody = document.getElementById('task-tbody');
    document.getElementById('tab-active-count').textContent = instances.length;

    if (instances.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:30px;">无活跃任务</td></tr>';
        return;
    }


    var tbody = document.getElementById('task-tbody');
    document.getElementById('tab-active-count').textContent = instances.length;

    if (instances.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:30px;">无活跃任务</td></tr>';
        return;
    }

    tbody.innerHTML = instances.map(function(t) {
        var badgeType = STATUS_BADGE_MAP[t.status] || 'idle';
        var tid = (t.task_id || '');
        // 状态中文显示（doc/62）
        var stateText = STATE_CN[t.current_state] || STATE_CN[t.status] || t.status || '--';
        // 操作栏：查询 + 继续 + 取消（doc/62：任务产生后即可继续/取消，无 RCS 任务号时由后端提示）
        var op = '<button class="btn btn-outline btn-sm" style="font-size:10px;padding:1px 6px;" ' +
                 'onclick="queryTask(\'' + tid + '\')" title="查询"><i class="fas fa-search"></i></button>';
        op += '<button class="btn btn-outline btn-sm" style="font-size:10px;padding:1px 6px;color:var(--accent-green);" ' +
              'onclick="continueTaskInline(\'' + tid + '\')" title="继续执行（RCS continueTask）"><i class="fas fa-play"></i></button>';
        op += '<button class="btn btn-outline btn-sm" style="font-size:10px;padding:1px 6px;color:var(--accent-red);" ' +
              'onclick="cancelTaskInline(\'' + tid + '\')" title="取消任务（释放资源）"><i class="fas fa-times"></i></button>';
        return '<tr>' +
            '<td><code style="font-size:11px;color:var(--accent-blue);">' + tid + '</code></td>' +
            '<td>' + (t.src_bay || '') + ' → ' + (t.dst_bay || '') + '</td>' +
            '<td><span class="status-badge ' + badgeType + '">' + stateText + '</span></td>' +
            '<td>' + (t.robot_id || '--') + '</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">' + (t.created_at || '--') + '</td>' +
            '<td>' + op + '</td>' +
            '</tr>';
    }).join('');
}


// 仅更新队列计数（不切换 Tab 内容）
function renderQueuePreview(data) {
    var queue = (data && data.queue) ? data.queue : [];
    var el = document.getElementById('tab-queue-count');
    if (el) el.textContent = queue.length;
}

function renderQueueTasks(data) {
    var queue = (data && data.queue) ? data.queue : [];
    var stats = (data && data.stats) ? data.stats : {};
    var lastDequeued = (data && data.last_dequeued) ? data.last_dequeued : [];
    var tbody = document.getElementById('task-tbody');
    document.getElementById('tab-queue-count').textContent = queue.length;

    if (queue.length === 0) {
        // 空态显示累计统计 + 最近出队，证明队列机制在运转
        var lines = [
            '队列为空',
            '累计入队 ' + (stats.enqueue_count || 0) +
            ' | 出队 ' + (stats.dequeue_count || 0) +
            ' | 老化 ' + (stats.aged_out_count || 0) +
            ' | 去重 ' + (stats.skip_duplicate_count || 0) +
            ' | 溢出 ' + (stats.skip_full_count || 0)
        ];
        if (lastDequeued.length) {
            lines.push('最近出队: ' + lastDequeued.map(function(d) {
                return d.src_bay + '→' + d.dst_bay + '(AGV ' + d.robot_id + ')';
            }).join('，'));
        }
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;' +
            'color:var(--text-muted);padding:20px;">' + lines.join('<br>') + '</td></tr>';
        return;
    }

    var nowTs = Math.floor(Date.now() / 1000);
    tbody.innerHTML = queue.map(function(item, i) {
        var waitSec = item.enqueue_time ? (nowTs - item.enqueue_time) : 0;
        var waitStr = waitSec > 0 ? (waitSec < 60 ? waitSec + 's' :
                     Math.floor(waitSec / 60) + 'm' + (waitSec % 60) + 's') : '--';
        return '<tr>' +
            '<td><code style="font-size:11px;color:var(--text-muted);">#' + (i + 1) + '</code></td>' +
            '<td>' + (item.src_bay || '') + ' → ' + (item.dst_bay || '') +
                '<span class="text-muted" style="font-size:10px;"> (类型' + (item.cargo_type || '-') + ')</span></td>' +
            '<td><span class="status-badge pending">待触发</span></td>' +
            '<td>--</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">等待 ' + waitStr + '</td>' +
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
            '<td><span class="status-badge ' + badgeType + '">' + (STATUS_CN[t.status] || t.status || '--') + '</span></td>' +
            '<td>--</td>' +
            '<td style="font-size:11px;color:var(--text-muted);">' + (t.created_at || '--') + '</td>' +
            '<td>--</td>' +
            '</tr>';
    }).join('');
}

// ===== 告警 =====

// 缓存当前告警列表用于去重判断
var _alarmCache = {};
function renderAlarmList(data) {
    var alarms = (data && data.alarms) ? data.alarms : [];
    var container = document.getElementById('alarm-list');
    if (!container) return;

    if (!alarms.length) {
        container.innerHTML = '<div class="alarm-empty">✅ 暂无告警</div>';
        document.getElementById('sys-alarm-count').textContent = '0';
        _alarmCache = {};
        return;
    }

    var unack = alarms.filter(function(a) { return !a.acknowledged; });
    document.getElementById('sys-alarm-count').textContent = unack.length;

    // 按时间降序排列
    unack.sort(function(a, b) { return b.timestamp - a.timestamp; });

    container.innerHTML = unack.slice(0, 5).map(function(a) {
        var level = (a.level || '').toLowerCase();
        var levelClass = (level === 'critical' || level === 'error') ? 'critical' :
                         (level === 'warning') ? 'warning' : 'info';
        var timeStr = a.time_str || formatRelativeTime(a.timestamp);
        return '<div class="alarm-row ' + levelClass + '" data-alarm-id="' + (a.id || '') + '">' +
            '<span class="alarm-dot"></span>' +
            '<span class="alarm-msg">' + escapeHtml(a.message || '未知告警') + '</span>' +
            '<span class="alarm-time">' + timeStr + '</span>' +
            '<span class="alarm-actions">' +
                '<button class="btn btn-outline btn-sm" onclick="ackAlarm(\'' + (a.id || '') + '\')">确认</button>' +
                '<button class="btn btn-outline btn-sm" onclick="resolveAlarm(\'' + (a.id || '') + '\')">解决</button>' +
            '</span>' +
            '</div>';
    }).join('');
}

/** HTML 转义 */
function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/** 相对时间格式化 */
function formatRelativeTime(ts) {
    if (!ts) return '';
    var diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
    return Math.floor(diff / 86400) + ' 天前';
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

// ===== 系统信息面板渲染 =====
function renderSystemInfoPanel(data) {
    var container = document.getElementById('system-info-panel');
    if (!container) return;
    if (!data) {
        container.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px;">无数据</div>';
        return;
    }

    var sysInfo = data.system_info || {};
    var hoursUp = 0;
    if (data.uptime) hoursUp = Math.floor(data.uptime / 3600);
    var daysUp = Math.floor(hoursUp / 24);
    var uptimeStr = daysUp > 0 ? daysUp + '天 ' + (hoursUp % 24) + '小时' : (hoursUp || '--') + '小时';

    var rows = [
        { label: '运行模式',  value: data.operation_mode === 'development' ? '开发' : '部署', cls: 'blue' },
        { label: '运行时长',  value: uptimeStr },
        { label: 'WS 连接数', value: sysInfo.ws_connections || '0' },
        { label: 'HTTP 端口', value: sysInfo.http_port || '9183' },
        { label: '节点总数',  value: (sysInfo.nodes_total || '--') },
        { label: '通道总数',  value: (sysInfo.channels_total || '--') },
        { label: '健康度',    value: (data.health_score || '--') + '%',
          cls: (data.health_score >= 80 ? 'green' : (data.health_score >= 50 ? '' : 'red')) },
    ];

    container.innerHTML = rows.map(function(r) {
        return '<div class="sys-info-row">' +
            '<span class="sys-info-label">' + r.label + '</span>' +
            '<span class="sys-info-value' + (r.cls ? ' ' + r.cls : '') + '">' + r.value + '</span>' +
            '</div>';
    }).join('');
}

// ===== P1 配对连线：业务快照 → 连线输入（doc/P1 规范 §7.1 v5） =====
function buildPairLines(d) {
    var out = [];
    var now = Date.now() / 1000;
    var tq = (d.task_queue && d.task_queue.queue) || [];
    tq.forEach(function(q) {
        if (q.src_bay && q.dst_bay) out.push({ src: q.src_bay, dst: q.dst_bay, state: 'pending' });
    });
    var inst = (d.active_instances && d.active_instances.instances) || [];
    inst.forEach(function(t) {
        if (TERMINAL_TASK_STATUS[(t.status || '').toLowerCase()]) return;   // completed/cancelled 终态不画
        if (t.src_bay && t.dst_bay) out.push({ src: t.src_bay, dst: t.dst_bay, state: 'active', robot_id: t.robot_id });
    });
    // v5：最近失败任务（event_bridge 缓存，60s 窗口）→ error 红色线
    var rf = (d.recent_failures || []).filter(function(x) {
        return x.src_bay && x.dst_bay && (now - (x.failed_at || 0)) < 60;
    });
    rf.forEach(function(x) {
        out.push({ src: x.src_bay, dst: x.dst_bay, state: 'error', robot_id: x.robot_id });
    });
    return out;
}

// ===== P1 v5：浮动匹配信息面板（doc/P1 规范 §13.5） =====
// ===== P1 v6：浮动匹配信息面板（半透明 + 默认折叠 + 可拖动） =====
// 只填充 body 列表 + 更新标题栏数量汇总（不重置折叠状态）
function renderPairPanel(d) {
    var panel = document.getElementById('pair-panel');
    if (!panel) return;
    var now = Date.now() / 1000;
    var rows = [];
    // 候选匹配（pending）
    var tq = (d.task_queue && d.task_queue.queue) || [];
    rows.push('<div class="pp-row"><span class="pp-dot pp-dot-pending"></span><b>候选匹配</b> (' + tq.length + ')</div>');
    if (tq.length === 0) rows.push('<div class="pp-row pp-empty">暂无排队候选</div>');
    tq.forEach(function(q) {
        rows.push('<div class="pp-row" style="padding-left:14px;">' + q.src_bay + ' → ' + q.dst_bay + '</div>');
    });
    // 进行中（active）
    var inst = (d.active_instances && d.active_instances.instances) || [];
    var active = inst.filter(function(t) { return !TERMINAL_TASK_STATUS[(t.status || '').toLowerCase()]; });
    rows.push('<div class="pp-row"><span class="pp-dot pp-dot-active"></span><b>进行中</b> (' + active.length + ')</div>');
    if (active.length === 0) rows.push('<div class="pp-row pp-empty">暂无进行中任务</div>');
    active.forEach(function(t) {
        rows.push('<div class="pp-row" style="padding-left:14px;">' + (t.src_bay || '?') + ' → ' + (t.dst_bay || '?') +
            (t.robot_id ? ' <span style="color:#7a93b5">AGV' + t.robot_id + '</span>' : '') + '</div>');
    });
    // 异常（error，60s 窗口）
    var rf = (d.recent_failures || []).filter(function(x) { return (now - (x.failed_at || 0)) < 60; });
    rows.push('<div class="pp-row"><span class="pp-dot pp-dot-error"></span><b>异常</b> (' + rf.length + ')</div>');
    if (rf.length === 0) rows.push('<div class="pp-row pp-empty">暂无异常任务</div>');
    rf.forEach(function(x) {
        rows.push('<div class="pp-row" style="padding-left:14px;">' + (x.src_bay || '?') + ' → ' + (x.dst_bay || '?') +
            ' <span style="color:#f87171">失败</span></div>');
    });
    // 内容区 + 标题栏数量汇总
    var body = document.getElementById('pair-panel-body');
    if (body) body.innerHTML = rows.join('');
    var setCnt = function(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
    setCnt('pp-cnt-pending', tq.length);
    setCnt('pp-cnt-active', active.length);
    setCnt('pp-cnt-error', rf.length);
}

// ===== P1 v6：面板交互（折叠 toggle + 拖动），一次性绑定 =====
function bindPairPanel() {
    var panel = document.getElementById('pair-panel');
    if (!panel || panel.dataset.bound) return;
    panel.dataset.bound = '1';

    // 折叠/展开：点击标题栏切换
    var header = document.getElementById('pair-panel-header');
    if (header) {
        header.addEventListener('click', function() {
            panel.classList.toggle('collapsed');
        });
    }

    // 拖动：仅标题栏 mousedown
    if (!header) return;
    header.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return;
        e.preventDefault();
        var rect = panel.getBoundingClientRect();
        var offX = e.clientX - rect.left;
        var offY = e.clientY - rect.top;
        var host = panel.parentElement;   // card-body（position:relative）
        var hostRect = host ? host.getBoundingClientRect() : null;

        function onMove(ev) {
            var x = ev.clientX - (hostRect ? hostRect.left : 0) - offX;
            var y = ev.clientY - (hostRect ? hostRect.top : 0) - offY;
            // clamp 在 card-body 内
            if (hostRect) {
                x = Math.max(0, Math.min(x, hostRect.width - rect.width));
                y = Math.max(0, Math.min(y, hostRect.height - rect.height));
            }
            panel.style.right = 'auto';
            panel.style.left = Math.max(0, x) + 'px';
            panel.style.top = Math.max(0, y) + 'px';
        }
        function onUp() {
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
        }
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
    });
}

// ===== WebSocket 订阅 =====
function bindWebSocket() {
    // 始发仓解绑提示（doc/触发机制 §8.1：人工移走货物 → 解绑 + 移出队列）
    WS.on('bay_unbound', function(msg) {
        var d = msg.data || {};
        if (d.bay_id && window.showToast) {
            showToast('仓位 ' + d.bay_id + ' 已解绑（货物移走）', 'warning');
        }
    });
    WS.on('business_update', function(msg) {
        var d = msg.data || {};
        if (d.bay) renderBayGrid(d.bay);
        if (d.dest) renderDestGrid(d.dest);
        if (d.agv) renderAgvCards(d.agv);
        if (d.task_stats) renderTaskStats(d.task_stats);   // 任务信息栏统计
        // 即使 active_instances 为空也要刷新（任务完成后清空）
        renderTaskTable(currentTaskTab, d.active_instances || { instances: [] });
        // P1 配对连线：queue → 虚线（触发前），active_instances 非终态 → 实线流光（触发后），recent_failures → 红色（异常）
        if (window.PairLines) window.PairLines.update(buildPairLines(d));
        // P1 v5：浮动匹配信息面板实时更新
        renderPairPanel(d);
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
        renderSystemInfoPanel(msg.data || {});
    });
}





// ===== 事件绑定 =====
function bindEvents() {
    // 仓位 click → Modal 编辑显示类型（仓位编排：名称由 MES/规划固定，运行中不改名，doc/取消仓位名称修改功能）
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
            // 类型：写入 app_mgr yaml（bay_configs，显示定义权威，热加载）；实际货物类型以 AI 检测为准
            var _m = {};
            _m[bayId] = newCt;
            API.setConfigBay(_m).then(function(r) {
                if (r && r.success === false) {
                    showToast('更新失败: ' + (r.error || '未知'), 'error');
                    return;
                }
                showToast(bayId + ' 显示类型已更新为 ' + newCt + '（app_mgr yaml，热加载）', 'success');
                modal.hide();
                loadAllData();
            }).catch(function() {
                showToast('更新失败（网络错误）', 'error');
            });
        };
    });

    // 仓位编排：区域标题点击改名（localStorage UI 展示名，doc/仓位名称类型编排）
    document.querySelectorAll('.zone-title').forEach(function(el) {
        el.addEventListener('click', function(ev) {
            ev.stopPropagation();
            var zone = el.getAttribute('data-zone');
            var map = {};
            try { map = JSON.parse(localStorage.getItem('zone_names') || '{}'); } catch (e) {}
            AppDialog.prompt({
                title: '修改区域名称',
                message: '当前: ' + (map[zone] || el.textContent),
                defaultValue: map[zone] || el.textContent,
                confirmText: '保存'
            }).then(function(v) {
                if (v === null || v === false || !String(v).trim()) return;
                map[zone] = String(v).trim();
                localStorage.setItem('zone_names', JSON.stringify(map));
                el.textContent = map[zone];
                showToast('区域名称已更新（本地显示）', 'success');
            });
        });
    });

    // 仓位编排：目的仓编排（yaml 权威 dest_bay_configs，热加载，doc/仓位名称类型编排）
    var arrangeDestBtn = document.getElementById('btn-arrange-dest');
    if (arrangeDestBtn) {
        arrangeDestBtn.addEventListener('click', function() {
            API.getConfigDest().then(function(r) {
                var mappings = (r && r.mappings) || {};
                var keys = Object.keys(mappings);
                var tbody = document.getElementById('dest-arrange-tbody');
                var laneOpts = (window._policyLaneIds || []).length
                    ? ['<option value="">未分配</option>'].concat((window._policyLaneIds || []).map(function(l) { return '<option value="' + l + '">' + l + '</option>'; })).join('')
                    : '<option value="">未分配</option>';
                tbody.innerHTML = (keys.length ? keys : ['']).map(function(k) {
                    var m = mappings[k] || {};
                    return '<tr>' +
                        '<td><input class="form-control form-control-sm" data-f="name" value="' + k + '"></td>' +
                        '<td><input class="form-control form-control-sm" data-f="floor" type="number" min="1" value="' + (m.floor || 2) + '"></td>' +
                        '<td><select class="form-select form-select-sm" data-f="lane">' + laneOpts + '</select></td>' +
                        '<td><input class="form-control form-control-sm" data-f="type" type="number" min="1" max="6" value="' + (m.cargo_type || 1) + '"></td>' +
                        '<td><button class="btn btn-outline btn-sm" data-f="del"><i class="fas fa-trash"></i></button></td></tr>';
                }).join('');
                // 回填已选巷道
                document.querySelectorAll('#dest-arrange-tbody tr').forEach(function(tr) {
                    var sel = tr.querySelector('[data-f="lane"]');
                    var name = (tr.querySelector('[data-f="name"]') || {}).value;
                    var m2 = mappings[name] || {};
                    if (sel && m2.lane) sel.value = m2.lane;
                });
                new bootstrap.Modal(document.getElementById('destArrangeModal')).show();
                // 配对策略：加载当前策略 + 始发仓下拉数据源（doc/目的仓位巷道FIFO策略 §19）
                API.getConfigBay().then(function(cr) {
                    window._policySrcBays = Object.keys((cr && cr.mappings) || {});
                    loadPairingPolicy();
                }).catch(function() { window._policySrcBays = []; loadPairingPolicy(); });
            });
        });
    }
    var addDestRow = document.getElementById('btn-add-dest-row');
    if (addDestRow) {
        addDestRow.addEventListener('click', function() {
            var laneOpts2 = (window._policyLaneIds || []).length
                ? ['<option value="">未分配</option>'].concat((window._policyLaneIds || []).map(function(l) { return '<option value="' + l + '">' + l + '</option>'; })).join('')
                : '<option value="">未分配</option>';
            document.getElementById('dest-arrange-tbody').insertAdjacentHTML('beforeend',
                '<tr><td><input class="form-control form-control-sm" data-f="name" placeholder="T2xxx"></td>' +
                '<td><input class="form-control form-control-sm" data-f="floor" type="number" min="1" value="2"></td>' +
                '<td><select class="form-select form-select-sm" data-f="lane">' + laneOpts2 + '</select></td>' +
                '<td><input class="form-control form-control-sm" data-f="type" type="number" min="1" max="6" value="1"></td>' +
                '<td><button class="btn btn-outline btn-sm" data-f="del"><i class="fas fa-trash"></i></button></td></tr>');
        });
    }
    // 批量添加目的仓位（doc/放置策略弹窗增强 §3.1）
    var batchDestBtn = document.getElementById('btn-batch-dest');
    if (batchDestBtn) {
        batchDestBtn.addEventListener('click', function() {
            document.getElementById('batch-dest-input').value = '';
            new bootstrap.Modal(document.getElementById('batchDestModal')).show();
        });
    }
    var batchDestOk = document.getElementById('btn-batch-dest-ok');
    if (batchDestOk) {
        batchDestOk.addEventListener('click', function() {
            var text = document.getElementById('batch-dest-input').value || '';
            var rows = [];
            var failed = 0;
            text.split(/\r?\n/).forEach(function(line) {
                line = (line || '').trim();
                if (!line) return;
                // 支持范围：T2001~T2010,2,2F-L1,1
                var m = /^([A-Za-z]+)(\d+)\s*~\s*\2?([A-Za-z]+)?(\d+),([^,]*),([^,]*),([^,]*)$/.exec(line);
                if (m) {
                    var prefix = m[1], from = parseInt(m[5]) || 0;
                    var to = parseInt(m[4]) || 0;
                    if (from <= 0 || to < from) { failed++; return; }
                    for (var i = from; i <= to; i++) {
                        var num = String(i).padStart(String(to).length, '0');
                        rows.push({ name: prefix + num, floor: (m[2] || '').trim() || 2, lane: (m[3] || '').trim(), type: (m[4] || '').trim() || 1 });
                    }
                    return;
                }
                var parts = line.split(',');
                if (parts.length >= 1) {
                    rows.push({ name: parts[0].trim(), floor: (parts[1] || '').trim() || 2, lane: (parts[2] || '').trim(), type: (parts[3] || '').trim() || 1 });
                } else { failed++; }
            });
            if (failed) showToast(failed + ' 行无法解析（格式：编号,楼层,巷道,类型）', 'warning');
            if (!rows.length) { showToast('未解析到有效仓位', 'error'); return; }
            var laneOptsB = (window._policyLaneIds || []).length
                ? ['<option value="">未分配</option>'].concat((window._policyLaneIds || []).map(function(l) { return '<option value="' + l + '">' + l + '</option>'; })).join('')
                : '<option value="">未分配</option>';
            rows.forEach(function(rw) {
                var laneSel = '<select class="form-select form-select-sm" data-f="lane">' + laneOptsB + '</select>';
                document.getElementById('dest-arrange-tbody').insertAdjacentHTML('beforeend',
                    '<tr><td><input class="form-control form-control-sm" data-f="name" value="' + rw.name + '"></td>' +
                    '<td><input class="form-control form-control-sm" data-f="floor" type="number" min="1" value="' + rw.floor + '"></td>' +
                    '<td>' + laneSel + '</td>' +
                    '<td><input class="form-control form-control-sm" data-f="type" type="number" min="1" max="6" value="' + rw.type + '"></td>' +
                    '<td><button class="btn btn-outline btn-sm" data-f="del"><i class="fas fa-trash"></i></button></td></tr>');
                var lastSel = document.querySelector('#dest-arrange-tbody tr:last-child [data-f="lane"]');
                if (lastSel && rw.lane) lastSel.value = rw.lane;
            });
            var mm = bootstrap.Modal.getInstance(document.getElementById('batchDestModal'));
            if (mm) mm.hide();
            showToast('已批量添加 ' + rows.length + ' 个仓位（保存后生效）', 'success');
        });
    }
    var destTbody = document.getElementById('dest-arrange-tbody');
    if (destTbody) {
        destTbody.addEventListener('click', function(e) {
            if (e.target.closest('[data-f="del"]')) e.target.closest('tr').remove();
        });
    }
    var saveDest = document.getElementById('btn-save-dest');
    if (saveDest) {
        saveDest.addEventListener('click', function() {
            var mappings = {};
            document.querySelectorAll('#dest-arrange-tbody tr').forEach(function(tr) {
                var name = tr.querySelector('[data-f="name"]').value.trim();
                var type = parseInt(tr.querySelector('[data-f="type"]').value) || 1;
                var floor = parseInt(tr.querySelector('[data-f="floor"]').value) || 2;
                var lane = (tr.querySelector('[data-f="lane"]') || {}).value || '';
                if (name) {
                    mappings[name] = { cargo_type: type, floor: floor };
                    if (lane) mappings[name].lane = lane;
                }
            });
            API.setConfigDest(mappings).then(function(r) {
                if (r.success !== false) {
                    showToast('目的仓位已保存（yaml + 热加载）', 'success');
                    var m = bootstrap.Modal.getInstance(document.getElementById('destArrangeModal'));
                    if (m) m.hide();
                    loadAllData();
                } else {
                    showToast(r.error || '保存失败', 'error');
                }
            });
        });
    }

    // ===== 配对策略（doc/目的仓位巷道FIFO策略 §19：查看/编辑/保存）=====
    var _policyState = { lanes: [], typeRules: [], bayRules: [] };

    function stratOptions(sel) {
        var opts = [['', '继承默认'], ['fifo', 'fifo'], ['filo', 'filo'], ['any', 'any']];
        return opts.map(function(o) {
            return '<option value="' + o[0] + '"' + (String(sel === undefined ? '' : sel) === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
        }).join('');
    }

    function loadPairingPolicy() {
        API.getPairingPolicy().then(function(r) {
            var policy = (r && r.policy) || {};
            window._policyLaneIds = (policy.lanes || []).map(function(l) { return l.id; }).filter(Boolean);
            renderPairingPolicySummary(policy);
            fillPairingPolicyForm(policy);
            // 预置模板下拉（doc/触发机制审查 §3.5）
            var ps = document.getElementById('policy-preset');
            if (ps) {
                var presets = policy.presets || [];
                ps.innerHTML = '<option value="">- 选择预置模板 -</option>' +
                    presets.map(function(p) { return '<option value="' + p.id + '">' + (p.name || p.id) + '</option>'; }).join('');
            }
        }).catch(function() {});
    }
    var applyPreset = document.getElementById('btn-apply-preset');
    if (applyPreset) {
        applyPreset.addEventListener('click', function() {
            var ps = document.getElementById('policy-preset');
            if (!ps || !ps.value) { showToast('请先选择预置模板', 'warning'); return; }
            API.getPairingPolicy().then(function(r) {
                var policy = (r && r.policy) || {};
                var presets = policy.presets || [];
                var tpl = null;
                presets.forEach(function(p) { if (p.id === ps.value) tpl = p; });
                if (!tpl) { showToast('未找到模板 ' + ps.value, 'error'); return; }
                fillPairingPolicyForm(tpl);   // 回填表单（保存后生效）
                showToast('已应用模板「' + (tpl.name || tpl.id) + '」，请点保存策略生效', 'info');
            });
        });
    }

    function renderPairingPolicySummary(policy) {
        var el = document.getElementById('pairing-policy-summary');
        if (!el) return;
        var lanes = policy.lanes || [];
        var typeRules = policy.type_rules || {};
        var bayRules = policy.bay_rules || {};
        var def = policy.default_strategy || 'any';
        var html = '<div class="mb-1"><b>默认策略：</b><span class="badge ' + (def === 'fifo' ? 'bg-info' : def === 'filo' ? 'bg-warning' : 'bg-secondary') + '">' + def + '</span></div>';
        if (!lanes.length && !Object.keys(typeRules).length && !Object.keys(bayRules).length) {
            html += '<small class="text-dim">未配置配对策略（当前为任意空位兼容行为），可展开下方编辑。</small>';
        } else {
            if (lanes.length) {
                html += '<div class="mb-1"><b>巷道</b></div><table class="table task-table table-sm mb-1"><thead><tr><th>巷道</th><th>楼层</th><th>策略</th><th>仓位序列(入口→深处)</th></tr></thead><tbody>';
                lanes.forEach(function(l) {
                    html += '<tr><td>' + (l.id || '') + '</td><td>' + (l.floor || '') + '</td><td>' + (l.strategy || def) + '</td><td>' + (l.bays || []).join(' → ') + '</td></tr>';
                });
                html += '</tbody></table>';
            }
            var tk = Object.keys(typeRules);
            if (tk.length) {
                html += '<div class="mb-1"><b>类型规则</b></div><table class="table task-table table-sm mb-1"><tbody>';
                tk.forEach(function(k) {
                    html += '<tr><td>类型 ' + k + '</td><td>→ 巷道 ' + ((typeRules[k].lanes || []).join(', ') || '-') + '</td><td>' + (typeRules[k].strategy || def) + '</td></tr>';
                });
                html += '</tbody></table>';
            }
            var bk = Object.keys(bayRules);
            if (bk.length) {
                html += '<div class="mb-1"><b>始发规则（始发仓位→目的巷道）</b></div><table class="table task-table table-sm mb-1"><tbody>';
                bk.forEach(function(k) {
                    html += '<tr><td>' + k + '</td><td>→ 巷道 ' + ((bayRules[k].lanes || []).join(', ') || '-') + '</td><td>' + (bayRules[k].strategy || def) + '</td></tr>';
                });
                html += '</tbody></table>';
            }
        }
        el.innerHTML = html;
    }

    function fillPairingPolicyForm(policy) {
        document.getElementById('policy-default-strategy').value = policy.default_strategy || 'any';
        _policyState.lanes = (policy.lanes || []).map(function(l) {
            return { id: l.id || '', floor: l.floor || '', strategy: l.strategy || '', bays: (l.bays || []).join(',') };
        });
        _policyState.typeRules = Object.keys(policy.type_rules || {}).map(function(k) {
            var r = policy.type_rules[k];
            return { type: k, lanes: (r.lanes || []).join(','), strategy: r.strategy || '' };
        });
        _policyState.bayRules = Object.keys(policy.bay_rules || {}).map(function(k) {
            var r = policy.bay_rules[k];
            return { bay: k, lanes: (r.lanes || []).join(','), strategy: r.strategy || '' };
        });
        renderPolicyRows();
    }

    function renderPolicyRows() {
        var srcOpts = ['<option value="">-</option>'];
        var usedBays = {};
        _policyState.bayRules.forEach(function(r) { if (r.bay) usedBays[r.bay] = true; });
        (window._policySrcBays || []).forEach(function(b) {
            if (!usedBays[b]) srcOpts.push('<option value="' + b + '">' + b + '</option>');
        });
        var lt = document.getElementById('policy-lane-tbody');
        if (lt) {
            lt.innerHTML = _policyState.lanes.map(function(l, i) {
                return '<tr>' +
                    '<td><input class="form-control form-control-sm" data-p="lane-id" value="' + (l.id || '') + '" placeholder="如 2F-L1"></td>' +
                    '<td><input class="form-control form-control-sm" data-p="lane-floor" type="number" min="1" value="' + (l.floor || '') + '"></td>' +
                    '<td><select class="form-select form-select-sm" data-p="lane-strategy">' + stratOptions(l.strategy) + '</select></td>' +
                    '<td><input class="form-control form-control-sm" data-p="lane-bays" value="' + (l.bays || '') + '" placeholder="T2001,T2002,T2003"></td>' +
                    '<td><button class="btn btn-outline btn-sm" data-p="del-lane"><i class="fas fa-trash"></i></button></td></tr>';
            }).join('') || '<tr><td colspan="5" class="text-dim">暂无巷道</td></tr>';
        }
        var tt = document.getElementById('policy-type-tbody');
        if (tt) {
            tt.innerHTML = _policyState.typeRules.map(function(r, i) {
                return '<tr>' +
                    '<td><input class="form-control form-control-sm" data-p="tr-type" type="number" min="1" max="6" value="' + (r.type || '') + '"></td>' +
                    '<td><input class="form-control form-control-sm" data-p="tr-lanes" value="' + (r.lanes || '') + '" placeholder="2F-L1,2F-L2"></td>' +
                    '<td><select class="form-select form-select-sm" data-p="tr-strategy">' + stratOptions(r.strategy) + '</select></td>' +
                    '<td><button class="btn btn-outline btn-sm" data-p="del-tr"><i class="fas fa-trash"></i></button></td></tr>';
            }).join('') || '<tr><td colspan="4" class="text-dim">暂无类型规则</td></tr>';
        }
        var bt = document.getElementById('policy-bay-tbody');
        if (bt) {
            bt.innerHTML = _policyState.bayRules.map(function(r, i) {
                return '<tr>' +
                    '<td><select class="form-select form-select-sm" data-p="br-bay">' + srcOpts.join('') + '</select></td>' +
                    '<td><input class="form-control form-control-sm" data-p="br-lanes" value="' + (r.lanes || '') + '" placeholder="2F-L1"></td>' +
                    '<td><select class="form-select form-select-sm" data-p="br-strategy">' + stratOptions(r.strategy) + '</select></td>' +
                    '<td><button class="btn btn-outline btn-sm" data-p="del-br"><i class="fas fa-trash"></i></button></td></tr>';
            }).join('') || '<tr><td colspan="4" class="text-dim">暂无始发规则</td></tr>';
        }
        // 回填已选始发仓（下拉重建后按 bay 选中）
        document.querySelectorAll('#policy-bay-tbody tr').forEach(function(tr, i) {
            var sel = tr.querySelector('[data-p="br-bay"]');
            var rule = _policyState.bayRules[i];
            if (sel && rule && rule.bay) sel.value = rule.bay;
        });
    }

    function collectPairingPolicy() {
        var lanes = [];
        document.querySelectorAll('#policy-lane-tbody tr').forEach(function(tr) {
            var id = (tr.querySelector('[data-p="lane-id"]') || {}).value || '';
            var floor = parseInt((tr.querySelector('[data-p="lane-floor"]') || {}).value) || 0;
            var strat = (tr.querySelector('[data-p="lane-strategy"]') || {}).value || '';
            var bays = ((tr.querySelector('[data-p="lane-bays"]') || {}).value || '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
            if (id.trim() && bays.length) lanes.push({ id: id.trim(), floor: floor, bays: bays, strategy: strat || undefined });
        });
        var typeRules = {};
        document.querySelectorAll('#policy-type-tbody tr').forEach(function(tr) {
            var type = parseInt((tr.querySelector('[data-p="tr-type"]') || {}).value) || 0;
            var lanesStr = ((tr.querySelector('[data-p="tr-lanes"]') || {}).value || '').trim();
            var strat = (tr.querySelector('[data-p="tr-strategy"]') || {}).value || '';
            if (type >= 1 && type <= 6 && lanesStr) {
                typeRules[type] = { lanes: lanesStr.split(',').map(function(s) { return s.trim(); }).filter(Boolean), strategy: strat || undefined };
            }
        });
        var bayRules = {};
        document.querySelectorAll('#policy-bay-tbody tr').forEach(function(tr) {
            var bay = (tr.querySelector('[data-p="br-bay"]') || {}).value || '';
            var lanesStr = ((tr.querySelector('[data-p="br-lanes"]') || {}).value || '').trim();
            var strat = (tr.querySelector('[data-p="br-strategy"]') || {}).value || '';
            if (bay && lanesStr) {
                bayRules[bay] = { lanes: lanesStr.split(',').map(function(s) { return s.trim(); }).filter(Boolean), strategy: strat || undefined };
            }
        });
        var policy = { default_strategy: document.getElementById('policy-default-strategy').value || 'any' };
        if (lanes.length) policy.lanes = lanes;
        if (Object.keys(typeRules).length) policy.type_rules = typeRules;
        if (Object.keys(bayRules).length) policy.bay_rules = bayRules;
        return policy;
    }

    // 弹窗内 Tab 切换（目的仓位 / 配对策略）
    document.querySelectorAll('#destArrangeModal .tab-bar-inline .tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            document.querySelectorAll('#destArrangeModal .tab-bar-inline .tab').forEach(function(t) { t.classList.remove('active'); });
            this.classList.add('active');
            var target = this.getAttribute('data-dest-tab');
            document.getElementById('dest-tab').style.display = target === 'dest-tab' ? '' : 'none';
            document.getElementById('policy-tab').style.display = target === 'policy-tab' ? '' : 'none';
        });
    });

    // 新增巷道 / 类型规则 / 始发规则
    var addLane = document.getElementById('btn-add-lane');
    if (addLane) addLane.addEventListener('click', function() { _policyState.lanes.push({ id: '', floor: '', strategy: '', bays: '' }); renderPolicyRows(); });
    var addTr = document.getElementById('btn-add-type-rule');
    if (addTr) addTr.addEventListener('click', function() { _policyState.typeRules.push({ type: '', lanes: '', strategy: '' }); renderPolicyRows(); });
    var addBr = document.getElementById('btn-add-bay-rule');
    if (addBr) addBr.addEventListener('click', function() { _policyState.bayRules.push({ bay: '', lanes: '', strategy: '' }); renderPolicyRows(); });

    // 删除行（事件委托）
    ['policy-lane-tbody', 'policy-type-tbody', 'policy-bay-tbody'].forEach(function(tid) {
        var tb = document.getElementById(tid);
        if (!tb) return;
        tb.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-p^="del-"]');
            if (!btn) return;
            var tr = btn.closest('tr');
            var idx = Array.prototype.indexOf.call(tb.children, tr);
            if (idx < 0) return;
            if (btn.getAttribute('data-p') === 'del-lane') _policyState.lanes.splice(idx, 1);
            else if (btn.getAttribute('data-p') === 'del-tr') _policyState.typeRules.splice(idx, 1);
            else _policyState.bayRules.splice(idx, 1);
            renderPolicyRows();
        });
    });

    // 保存策略
    var savePolicy = document.getElementById('btn-save-policy');
    if (savePolicy) {
        savePolicy.addEventListener('click', function() {
            var policy = collectPairingPolicy();
            // 前端预校验：巷道 id 唯一 / bays 非空 / lanes 引用存在
            var laneIds = {};
            (policy.lanes || []).forEach(function(l) {
                if (laneIds[l.id]) { showToast('巷道 id 重复: ' + l.id, 'error'); return; }
                laneIds[l.id] = true;
            });
            var known = {};
            (policy.lanes || []).forEach(function(l) { known[l.id] = true; });
            var badRef = null;
            (policy.type_rules || {}).forEach(function(v) {
                (v.lanes || []).forEach(function(li) { if (!known[li]) badRef = li; });
            });
            (policy.bay_rules || {}).forEach(function(v) {
                (v.lanes || []).forEach(function(li) { if (!known[li]) badRef = li; });
            });
            if (badRef) { showToast('引用了未定义的巷道: ' + badRef, 'error'); return; }
            API.setPairingPolicy(policy).then(function(r) {
                if (r.success !== false) {
                    showToast('配对策略已保存（yaml + 热加载）', 'success');
                    loadPairingPolicy();
                    loadAllData();
                    // 保存成功 → 切回展示模式
                    document.getElementById('pairing-policy-edit').style.display = 'none';
                    document.getElementById('pairing-policy-summary').style.display = '';
                    var ep = document.getElementById('btn-edit-policy');
                    if (ep) ep.style.display = '';
                } else {
                    showToast(r.error || '保存失败', 'error');
                }
            });
        });
    }
    // 恢复默认（重载当前已保存配置）
    var resetPolicy = document.getElementById('btn-reset-policy');
    if (resetPolicy) {
        resetPolicy.addEventListener('click', function() {
            loadPairingPolicy();
            showToast('已恢复当前已保存策略', 'info');
        });
    }
    // 策略双模式：编辑模式 / 展示模式（doc/放置策略弹窗增强 §3.3）
    var editPolicyBtn = document.getElementById('btn-edit-policy');
    if (editPolicyBtn) {
        editPolicyBtn.addEventListener('click', function() {
            document.getElementById('pairing-policy-summary').style.display = 'none';
            editPolicyBtn.style.display = 'none';
            document.getElementById('pairing-policy-edit').style.display = '';
        });
    }
    var donePolicyBtn = document.getElementById('btn-done-policy');
    if (donePolicyBtn) {
        donePolicyBtn.addEventListener('click', function() {
            var editShown = document.getElementById('pairing-policy-edit').style.display !== 'none';
            if (editShown) {
                // 未保存修改提示（简化：直接提示返回展示模式并重载）
                loadPairingPolicy();
            }
            document.getElementById('pairing-policy-edit').style.display = 'none';
            document.getElementById('pairing-policy-summary').style.display = '';
            var ep = document.getElementById('btn-edit-policy');
            if (ep) ep.style.display = '';
        });
    }

    // ===== 工作时间与节假日设置（doc/AGV状态卡改造 §4.4） =====
    window._wsHolidays = [];
    window._wsDays = [];
    var WS_DAY_MAP = [
        { key: 'mon', label: '周一' }, { key: 'tue', label: '周二' }, { key: 'wed', label: '周三' },
        { key: 'thu', label: '周四' }, { key: 'fri', label: '周五' }, { key: 'sat', label: '周六' },
        { key: 'sun', label: '周日' }
    ];

    function openWorkSchedule() {
        API.getScheduleConfig().then(function(r) {
            var ws = (r && r.work_schedule) || {};
            document.getElementById('ws-enabled').checked = ws.enabled !== false;
            window._wsHolidays = (ws.holidays || []).slice();
            var scheds = ws.schedules || [];
            window._wsDays = WS_DAY_MAP.map(function(d) {
                var found = null;
                scheds.forEach(function(s) { if (s.day_of_week === d.key) found = s; });
                return found ? { day: d.key, start: found.start_time || '', end: found.end_time || '', enabled: found.enabled !== false }
                             : { day: d.key, start: '', end: '', enabled: false };
            });
            renderWsCalendar();
            renderWsDays();
            new bootstrap.Modal(document.getElementById('workScheduleModal')).show();
        }).catch(function() {
            showToast('加载工作时间配置失败', 'error');
        });
    }

    function renderWsCalendar() {
        var el = document.getElementById('ws-calendar');
        if (!el) return;
        var now = new Date();
        var y = now.getFullYear(), m = now.getMonth();
        var daysInMonth = new Date(y, m + 1, 0).getDate();
        var todayStr = now.toISOString().slice(0, 10);
        var prefix = y + '-' + String(m + 1).padStart(2, '0') + '-';
        var html = '<div class="ws-cal-head">' + y + '年' + (m + 1) + '月</div><div class="ws-cal-grid">';
        for (var d = 1; d <= daysInMonth; d++) {
            var ds = prefix + String(d).padStart(2, '0');
            var isHoliday = window._wsHolidays.indexOf(ds) >= 0;
            var isToday = ds === todayStr;
            html += '<div class="ws-cal-cell' + (isHoliday ? ' holiday' : '') + (isToday ? ' today' : '') + '" data-date="' + ds + '">' + d + '</div>';
        }
        html += '</div>';
        el.innerHTML = html;
        el.querySelectorAll('.ws-cal-cell').forEach(function(cell) {
            cell.addEventListener('click', function() {
                var ds = cell.getAttribute('data-date');
                var idx = window._wsHolidays.indexOf(ds);
                if (idx >= 0) window._wsHolidays.splice(idx, 1);
                else window._wsHolidays.push(ds);
                renderWsCalendar();
            });
        });
    }

    function renderWsDays() {
        var el = document.getElementById('ws-days');
        if (!el) return;
        el.innerHTML = window._wsDays.map(function(d, i) {
            return '<div class="ws-day-row">' +
                '<span class="ws-day-label">' + WS_DAY_MAP[i].label + '</span>' +
                '<input type="checkbox" class="form-check-input ws-day-en" data-i="' + i + '"' + (d.enabled ? ' checked' : '') + ' title="启用">' +
                '<input type="time" class="form-control form-control-sm ws-day-start" data-i="' + i + '" value="' + (d.start || '') + '">' +
                '<span class="ws-day-sep">—</span>' +
                '<input type="time" class="form-control form-control-sm ws-day-end" data-i="' + i + '" value="' + (d.end || '') + '">' +
                '<small class="text-dim">（取消勾选 = 当天休息）</small></div>';
        }).join('');
    }

    var wsBtn = document.getElementById('btn-work-schedule');
    if (wsBtn) wsBtn.addEventListener('click', openWorkSchedule);

    var saveWs = document.getElementById('btn-save-ws');
    if (saveWs) {
        saveWs.addEventListener('click', function() {
            var enabled = document.getElementById('ws-enabled').checked;
            var schedules = [];
            document.querySelectorAll('.ws-day-row').forEach(function(row) {
                var i = parseInt(row.querySelector('.ws-day-en').getAttribute('data-i'));
                var on = row.querySelector('.ws-day-en').checked;
                var start = row.querySelector('.ws-day-start').value;
                var end = row.querySelector('.ws-day-end').value;
                if (on && start && end) {
                    schedules.push({ day_of_week: WS_DAY_MAP[i].key, start_time: start, end_time: end, enabled: true });
                }
            });
            API.setWorkSchedule({ enabled: enabled, holidays: window._wsHolidays, schedules: schedules }).then(function(r) {
                if (r.success !== false) {
                    showToast('工作时间设置已保存（热加载生效）', 'success');
                    var mm = bootstrap.Modal.getInstance(document.getElementById('workScheduleModal'));
                    if (mm) mm.hide();
                } else {
                    showToast(r.error || '保存失败', 'error');
                }
            });
        });
    }

    // Tab 切换（任务面板；弹窗内 data-dest-tab 由配对策略区单独处理）
    document.querySelectorAll('.tab-bar-inline .tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            var dt = this.getAttribute('data-tab');
            if (!dt) return; // 弹窗内 tab 无 data-tab，跳过
            document.querySelectorAll('.tab-bar-inline .tab').forEach(function(t) { t.classList.remove('active'); });
            this.classList.add('active');
            currentTaskTab = dt;
            API.getTaskInstances().then(function(d) { renderTaskTable(currentTaskTab, d); });
        });
    });




    // 强制触发
    document.getElementById('btn-force-trigger').addEventListener('click', function() {
        var src = document.getElementById('trigger-src').value;
        var dst = document.getElementById('trigger-dst').value;
        var robotId = parseInt(document.getElementById('trigger-robot').value) || 0;
        var cargoType = parseInt(document.getElementById('trigger-cargo').value) || 1;
        var btn = this;
    
        // 1. 基本校验
        if (!src || !dst) {
            showToast('请选择起始仓和目的仓', 'warning');
            return;
        }
        if (src === dst) {
            showToast('起始仓和目的仓不能相同', 'warning');
            return;
        }
    
        // 禁用按钮防止重复点击
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 检查中...';
    
        // 2. 异步检查仓位状态和 AGV
        Promise.all([
            API.getBayStatus(),
            API.getDestStatus(),
            API.getAgvStatus()
        ]).then(function(results) {
            var bayData = results[0];
            var destData = results[1];
            var agvData = results[2];
    
            // 检查起始仓位是否已绑定有货
            var bays = (bayData && bayData.bays) ? bayData.bays : [];
            var srcBay = bays.find(function(b) { return b.bay_id === src; });
            if (!srcBay || srcBay.bind_status !== 1) {
                showToast('起始仓位 ' + src + ' 未绑定或无货，无法触发', 'warning');
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
                return;
            }
    
            // 检查目的仓位是否空闲
            var dests = (destData && destData.bays) ? destData.bays : [];
            var dstBay = dests.find(function(b) { return b.bay_id === dst; });
            if (!dstBay || dstBay.is_empty !== true) {
                showToast('目的仓位 ' + dst + ' 已被占用，请选择空闲仓位', 'warning');
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
                return;
            }
    
            // 检查 AGV 是否可用
            var robots = (agvData && agvData.robots) ? agvData.robots : [];
            if (robotId === 0) {
                // 若未选，尝试自动分配
                var available = robots.filter(function(r) { return r.status === 'AVAILABLE'; });
                if (available.length === 0) {
                    showToast('无可用 AGV，无法下发强制任务', 'warning');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
                    return;
                }
                robotId = available[0].robot_id;
                // 自动选中下拉框（可选）
                document.getElementById('trigger-robot').value = robotId;
            } else {
                // 验证指定的 AGV 是否可用
                var selected = robots.find(function(r) { return r.robot_id === robotId; });
                if (!selected || selected.status !== 'AVAILABLE') {
                    showToast('AGV ' + robotId + ' 当前不可用，请重新选择', 'warning');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
                    return;
                }
            }
    
            // 3. 二次确认（统一弹窗，doc/前端统一弹窗方案）
            var confirmMsg = '确定强制触发任务？\n' +
                '起始仓: ' + src + '\n' +
                '目的仓: ' + dst + '\n' +
                'AGV: ' + robotId + '\n' +
                '货物类型: ' + cargoType;
            AppDialog.confirm({ title: '强制触发任务', message: confirmMsg, confirmText: '确认触发', danger: true })
            .then(function(ok) {
                if (!ok) {
                    showToast('操作已取消', 'info');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
                    return;
                }
                // 4. 执行下发
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 下发中...';
                return API.taskControl('force_trigger', {
                    src_bay: src,
                    dst_bay: dst,
                    robot_id: robotId,
                    cargo_type: cargoType
                }).then(function(r) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
                    if (r.success) {
                        showToast('强制任务下发成功，任务ID: ' + (r.task_id || ''), 'success');
                        loadAllData();
                    } else {
                        showToast(r.error || '任务下发失败', 'error');
                    }
                }).catch(function(e) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
                    showToast('请求异常: ' + (e.message || e), 'error');
                });
            });
    
        }).catch(function(e) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-bolt"></i> 执行触发';
            showToast('检查仓位状态失败: ' + (e.message || e), 'error');
        });
    });

    // 查询任务
    document.getElementById('btn-query-task').addEventListener('click', function() {
        var tid = document.getElementById('query-task-id').value.trim();
        if (!tid) {
            showToast('请输入 task_id', 'warning');
            return;
        }
        API.taskControl('query', { task_id: tid }).then(function(r) {
            if (r.success) {
                var lines = [];
                for (var k in r) {
                    if (k !== 'success') lines.push('<b>' + k + ':</b> ' + r[k]);
                }
                // 统一弹窗显示结果（doc/前端统一弹窗方案）
                AppDialog.alert({ title: '任务查询结果', message: lines.join('<br>'), type: 'info' });
            } else {
                showToast(r.error || '未找到任务', 'error');
            }
        }).catch(function(e) {
            showToast('查询异常: ' + (e.message || e), 'error');
        });
    });

    // 取消
    document.getElementById('btn-cancel-task').addEventListener('click', function() {
        var tid = document.getElementById('ctrl-task-id').value.trim();
        if (!tid) {
            showToast('请输入 task_id', 'warning');
            return;
        }
        confirmTaskControl('cancel', { task_id: tid },
            '确定取消任务 ' + tid + ' 吗？\n取消后将释放该任务占用的资源。');
    });

    // 重试
    document.getElementById('btn-retry-task').addEventListener('click', function() {
        var tid = document.getElementById('ctrl-task-id').value.trim();
        if (!tid) {
            showToast('请输入 task_id', 'warning');
            return;
        }
        confirmTaskControl('retry', { task_id: tid },
            '确定重试任务 ' + tid + ' 吗？\n将从 calling_rcs 状态重新下发。');
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


function confirmTaskControl(action, params, confirmText) {
    AppDialog.confirm({ title: '任务操作确认', message: confirmText, confirmText: '确认', danger: (action === 'cancel') })
    .then(function(ok) {
        if (!ok) {
            showToast('操作已取消', 'info');
            return;
        }
        API.taskControl(action, params).then(function(r) {
            if (r.success) {
                showToast(r.message || '操作成功: ' + action, 'success');
                loadAllData();  // 刷新任务面板、仓位、AGV等
            } else {
                showToast(r.error || '操作失败', 'error');
            }
        }).catch(function(e) {
            showToast('请求异常: ' + (e.message || e), 'error');
        });
    });
}

// 任务面板行内操作（doc/62）：取消 / 继续
window.cancelTaskInline = function(tid) {
    confirmTaskControl('cancel', { task_id: tid },
        '确定取消任务 ' + tid + ' 吗？\n取消后将释放该任务占用的资源。');
};
window.continueTaskInline = function(tid) {
    confirmTaskControl('continue', { task_id: tid },
        '确定继续执行任务 ' + tid + ' 吗？\n将调用 RCS continueTask 继续该任务。');
};

function populateSelects() {
    var srcSelect = document.getElementById('trigger-src');
    var dstSelect = document.getElementById('trigger-dst');
    var robotSelect = document.getElementById('trigger-robot');

    // 起始仓
    var srcBays = [];
    Object.values(BAY_GROUP_MAP).forEach(function(ids) { srcBays = srcBays.concat(ids); });
    srcBays.forEach(function(id) {
        srcSelect.innerHTML += '<option value="' + id + '">' + id + '</option>';
    });

    // 目的仓
    var dstBays = [];
    Object.values(DEST_FLOOR_MAP).forEach(function(ids) { dstBays = dstBays.concat(ids); });
    dstBays.forEach(function(id) {
        dstSelect.innerHTML += '<option value="' + id + '">' + id + '</option>';
    });

    // AGV 下拉（仅 AVAILABLE）
    if (robotSelect) {
        API.getAgvStatus().then(function(data) {
            var robots = (data && data.robots) ? data.robots : [];
            var available = robots.filter(function(r) {
                return (r.status || '').toUpperCase() === 'AVAILABLE';
            });
            robotSelect.innerHTML = '<option value="">-- 选择 AGV --</option>';
            available.forEach(function(r) {
                robotSelect.innerHTML += '<option value="' + r.robot_id + '">' +
                    'AGV ' + r.robot_id + '（电量 ' + (r.battery || '--') + '%）</option>';
            });
            if (available.length === 0) {
                robotSelect.innerHTML += '<option value="">暂无可用 AGV</option>';
            }
        }).catch(function() {
            robotSelect.innerHTML = '<option value="">AGV 状态加载失败</option>';
        });
    }
}

// 外部调用
function queryTask(taskId) {
    document.getElementById('query-task-id').value = taskId;
    document.getElementById('btn-query-task').click();
}