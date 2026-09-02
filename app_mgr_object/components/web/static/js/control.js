/**
 * control.js — 运维控制页告警管理逻辑
 * 独立于原有内联脚本，负责告警面板的渲染、交互和实时更新
 */



// ===== 告警管理逻辑 =====
var currentAlarmFilter = 'all';

function loadAlarmPanel() {
    API.getAlarms(100, true).then(function(d) {
        renderAlarmTable(d.alarms || []);
    });
    API.getAlarmStats().then(renderAlarmStats);
}


// HTML 转义（防止 XSS）
function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function renderAlarmTable(alarms) {
    // 按时间降序
    alarms.sort(function(a, b) { return b.timestamp - a.timestamp; });

    // ===== 前端去重：同一 (type+message+source) 保留最新一条 =====
    var seen = {};
    alarms = alarms.filter(function(a) {
        var key = (a.type || '') + '|' + (a.message || '') + '|' + (a.source || '');
        if (seen[key]) return false;
        seen[key] = true;
        return true;
    });
    // ===== 去重结束 =====

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
            '<td>' + escapeHtml(a.message || '--') + '</td>' +
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
    if (!container) return;
    container.innerHTML = '<p style="margin:0;"><b>总告警数:</b> ' + (stats.total_alarms || 0) + '</p>' +
        '<p style="margin:0;color:var(--accent-orange);"><b>未确认:</b> ' + (stats.unacknowledged_alarms || 0) + '</p>' +
        '<p style="margin:0;color:var(--accent-red);"><b>未解决:</b> ' + (stats.unresolved_alarms || 0) + '</p>';
}

function ctrlAckAlarm(id) {
    API.acknowledgeAlarm(id).then(function(r) {
        if (r.success) {
            showToast('告警已确认', 'success');
            loadAlarmPanel();
        } else {
            showToast(r.error || '确认失败', 'error');
        }
    });
}

function ctrlResolveAlarm(id) {
    API.resolveAlarm(id).then(function(r) {
        if (r.success) {
            showToast('告警已解决', 'success');
            loadAlarmPanel();
        } else {
            showToast(r.error || '解决失败', 'error');
        }
    });
}

// DOM 初始化（等待页面加载完成后绑定事件）
document.addEventListener('DOMContentLoaded', function() {
    // 告警 Tab 切换
    document.querySelectorAll('[data-alarm-tab]').forEach(function(tab) {
        tab.addEventListener('click', function() {
            document.querySelectorAll('[data-alarm-tab]').forEach(function(t) { t.classList.remove('active'); });
            this.classList.add('active');
            currentAlarmFilter = this.getAttribute('data-alarm-tab');
            loadAlarmPanel();
        });
    });

    // 一键清除
    var clearBtn = document.getElementById('btn-clear-alarms');
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            API._post('/api/alarms/clear', {}).then(function(r) {
                if (r.success) {
                    showToast('已清除 ' + (r.cleared || 0) + ' 条告警', 'success');
                    loadAlarmPanel();
                } else {
                    showToast(r.error || '清除失败', 'error');
                }
            });
        });
    }

    // 如果页面中存在告警表格，则初始加载
    if (document.getElementById('alarms-table')) {
        loadAlarmPanel();
        // 订阅 WebSocket 告警更新
        if (typeof WS !== 'undefined' && WS.on) {
            WS.on('alarm_update', function() { loadAlarmPanel(); });
        }
    }
});


// ===== 顶部系统状态条（与首页统一） =====
function initControlSystemBar() {
    // 时钟
    function tick() {
        var el = document.getElementById('sys-clock-ctl');
        if (el) el.textContent = new Date().toLocaleString('zh-CN', {hour12: false});
    }
    tick();
    setInterval(tick, 1000);

    // 模式 + 告警数
    fetch('/api/status')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var mode = d.operation_mode || 'development';
            var el = document.getElementById('sys-mode-ctl');
            if (el) el.textContent = mode === 'development' ? '🔧 开发模式' : '🏭 部署模式';
        })
        .catch(function() {});
    API.getAlarms(100, false).then(function(d) {
        var unack = (d && d.alarms || []).filter(function(a) { return !a.acknowledged; }).length;
        var el = document.getElementById('sys-alarm-count-ctl');
        if (el) el.textContent = unack;
    });
}
document.addEventListener('DOMContentLoaded', initControlSystemBar);