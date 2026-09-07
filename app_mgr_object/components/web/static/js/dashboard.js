/**
 * dashboard.js — 教学看板前端交互
 *
 * 工程基线: app_mgr_object-0.2.1
 * 关联文档: doc/72 教学看板插件开发方案
 *
 * 职责:
 *   1. 今日概览（4 指标卡片，30s 轮询刷新）
 *   2. 高频错误点 TOP5（综合得分排序，点击下钻）
 *   3. 需关注的学员（退步预警/波动大/薄弱突出，点击跳转学员详情页）
 *   4. 实时进度展示（订阅中设备，WebSocket 推送 + 30s 轮询兜底）
 *   5. 教学改进验证（对比调整前后的班级平均分/完成率变化）
 */

(function () {
    'use strict';

    // ========== 配置 ==========
    var REFRESH_INTERVAL_SEC = 30;
    var TOP_ERROR_REFRESH_SEC = 60;
    var ATTENTION_REFRESH_SEC = 60;

    // ========== API ==========
    function apiGet(url) {
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    // ========== Toast ==========
    function toast(msg, type) {
        if (typeof showToast === 'function') {
            showToast(msg, type || 'info');
        } else {
            console.log('[' + (type || 'info') + '] ' + msg);
        }
    }

    // ========== 工具 ==========
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function fmtPercent(val) {
        if (val === null || val === undefined) return '--';
        return (val * 100).toFixed(1) + '%';
    }

    function fmtMs(ms) {
        if (ms === null || ms === undefined) return '--';
        var sec = Math.floor(ms / 1000);
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        return m + '分' + s + '秒';
    }

    function fmtTime(ms) {
        if (!ms) return '--';
        var d = new Date(ms);
        return d.toLocaleTimeString('zh-CN', { hour12: false });
    }

    // ========== 1. 今日概览 ==========
    function loadTodaySummary() {
        apiGet('/api/v1/dashboard/today_summary').then(function (res) {
            if (res.code !== 0) return;
            var d = res.data || {};
            document.getElementById('kpi-exam-count').textContent = d.exam_count || 0;
            document.getElementById('kpi-avg-score').textContent = d.avg_score || 0;
            document.getElementById('kpi-pass-rate').textContent = fmtPercent(d.pass_rate);
            document.getElementById('kpi-pending-tutor').textContent = d.pending_tutor_count || 0;
        }).catch(function (err) {
            console.error('今日概览加载失败: ' + err.message);
        });
    }

    // ========== 2. 高频错误点 TOP5 ==========
    function loadTopErrorPoints() {
        apiGet('/api/v1/dashboard/top_error_points').then(function (res) {
            if (res.code !== 0) return;
            var points = (res.data || {}).points || [];
            var tbody = document.getElementById('error-points-tbody');

            if (points.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">暂无数据</td></tr>';
                return;
            }

            tbody.innerHTML = points.map(function (p, i) {
                return '<tr>' +
                    '<td>' + (i + 1) + '</td>' +
                    '<td>' + escapeHtml(p.name) + ' <small class="text-muted">(步骤' + p.idx + ')</small></td>' +
                    '<td>' + fmtPercent(p.omission_rate) + '</td>' +
                    '<td>' + fmtPercent(p.timeout_rate) + '</td>' +
                    '<td><span class="badge bg-warning">' + p.composite_score.toFixed(3) + '</span></td>' +
                    '</tr>';
            }).join('');
        }).catch(function (err) {
            console.error('高频错误点加载失败: ' + err.message);
        });
    }

    // ========== 3. 需关注的学员 ==========
    function loadAttentionStudents() {
        apiGet('/api/v1/dashboard/attention_students').then(function (res) {
            if (res.code !== 0) return;
            var students = (res.data || {}).students || [];
            var tbody = document.getElementById('attention-students-tbody');

            if (students.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">暂无数据</td></tr>';
                return;
            }

            tbody.innerHTML = students.map(function (s) {
                var reasonLabel = '';
                if (s.reason === 'student_regression') reasonLabel = '<span class="badge bg-danger">退步预警</span>';
                else if (s.reason === 'volatility') reasonLabel = '<span class="badge bg-warning">波动大</span>';
                else reasonLabel = '<span class="badge bg-info">' + escapeHtml(s.reason) + '</span>';

                return '<tr>' +
                    '<td>' + escapeHtml(s.student_name || s.student_id) + '</td>' +
                    '<td>' + reasonLabel + '</td>' +
                    '<td><small class="text-muted">' + escapeHtml(s.detail || '') + '</small></td>' +
                    '</tr>';
            }).join('');
        }).catch(function (err) {
            console.error('需关注学员加载失败: ' + err.message);
        });
    }

    // ========== 4. 实时进度展示 ==========
    function loadRealtimeProgress() {
        apiGet('/api/v1/dashboard/realtime_progress').then(function (res) {
            if (res.code !== 0) return;
            var devices = (res.data || {}).devices || [];
            var tbody = document.getElementById('realtime-progress-tbody');

            document.getElementById('realtime-count').textContent = devices.length + ' 台';

            if (devices.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-3">暂无订阅设备</td></tr>';
                return;
            }

            tbody.innerHTML = devices.map(function (d) {
                var progress = (d.done || 0) + '/' + (d.total || 0);
                var current = d.current || '(空闲)';
                var elapsed = d.process_elapsed_ms ? fmtMs(d.process_elapsed_ms) : '--';

                return '<tr>' +
                    '<td>' + escapeHtml(d.device_id) + '</td>' +
                    '<td>' + escapeHtml(d.student_name || '') + '</td>' +
                    '<td>' + progress + '</td>' +
                    '<td>' + escapeHtml(current) + '</td>' +
                    '<td>' + elapsed + '</td>' +
                    '<td>' + fmtTime(d.updated_at) + '</td>' +
                    '</tr>';
            }).join('');
        }).catch(function (err) {
            console.error('实时进度加载失败: ' + err.message);
        });
    }

    // ========== 5. 教学改进验证 ==========
    function queryImprovementValidation() {
        var cls = document.getElementById('iv-cls').value.trim();
        var bs = parseInt(document.getElementById('iv-before-start').value, 10);
        var be = parseInt(document.getElementById('iv-before-end').value, 10);
        var as = parseInt(document.getElementById('iv-after-start').value, 10);
        var ae = parseInt(document.getElementById('iv-after-end').value, 10);

        if (!cls || !bs || !be || !as || !ae) {
            toast('请填写所有参数', 'warning');
            return;
        }

        var url = '/api/v1/dashboard/improvement_validation?cls=' + encodeURIComponent(cls) +
                  '&before_start=' + bs + '&before_end=' + be +
                  '&after_start=' + as + '&after_end=' + ae;

        apiGet(url).then(function (res) {
            if (res.code !== 0) {
                toast(res.message || '查询失败', 'error');
                return;
            }
            renderImprovementValidation(res.data);
        }).catch(function (err) {
            toast('查询失败: ' + err.message, 'error');
        });
    }

    function renderImprovementValidation(data) {
        var el = document.getElementById('iv-result');
        el.style.display = '';

        var before = data.before;
        var after = data.after;
        var delta = data.delta || {};
        var trend = data.trend;

        var trendLabel = '';
        var trendClass = '';
        if (trend === 'improved') { trendLabel = '↑ 改善'; trendClass = 'text-success'; }
        else if (trend === 'declined') { trendLabel = '↓ 退步'; trendClass = 'text-danger'; }
        else if (trend === 'mixed') { trendLabel = '→ 混合'; trendClass = 'text-warning'; }
        else { trendLabel = '无数据'; trendClass = 'text-muted'; }

        function fmtBlock(b) {
            if (!b) return '<td class="text-muted">无数据</td>';
            return '<td>' +
                '<div>平均分: <b>' + (b.avg_score || 0) + '</b></div>' +
                '<div>完成率: <b>' + fmtPercent(b.completion_rate) + '</b></div>' +
                '<div>通过率: <b>' + fmtPercent(b.pass_rate) + '</b></div>' +
                '<div>报告数: <b>' + (b.report_count || 0) + '</b></div>' +
                '</td>';
        }

        el.innerHTML = '<table class="table table-bordered"><thead><tr>' +
            '<th>班级</th><th>调整前</th><th>调整后</th><th>变化</th><th>趋势</th>' +
            '</tr></thead><tbody><tr>' +
            '<td>' + escapeHtml(data.cls) + '</td>' +
            fmtBlock(before) +
            fmtBlock(after) +
            '<td>' +
                '<div>平均分: <b>' + (delta.avg_score || 0).toFixed(1) + '</b></div>' +
                '<div>完成率: <b>' + (delta.completion_rate || 0).toFixed(4) + '</b></div>' +
            '</td>' +
            '<td class="' + trendClass + '"><b>' + trendLabel + '</b></td>' +
            '</tr></tbody></table>';
    }

    // ========== 轮询刷新 ==========
    function startPolling() {
        // 今日概览：30s
        loadTodaySummary();
        setInterval(loadTodaySummary, REFRESH_INTERVAL_SEC * 1000);

        // 高频错误点 TOP5：60s
        loadTopErrorPoints();
        setInterval(loadTopErrorPoints, TOP_ERROR_REFRESH_SEC * 1000);

        // 需关注的学员：60s
        loadAttentionStudents();
        setInterval(loadAttentionStudents, ATTENTION_REFRESH_SEC * 1000);

        // 实时进度：30s 轮询兜底（WebSocket 推送为主）
        loadRealtimeProgress();
        setInterval(loadRealtimeProgress, REFRESH_INTERVAL_SEC * 1000);
    }

    // ========== 事件绑定 ==========
    function bindEvents() {
        document.getElementById('btn-iv-query').addEventListener('click', queryImprovementValidation);
    }

    // ========== 初始化 ==========
    document.addEventListener('DOMContentLoaded', function () {
        bindEvents();
        startPolling();
        if (typeof window !== 'undefined' && typeof window.pageLoaded === 'function') {
            window.pageLoaded();
        }
    });

})();
