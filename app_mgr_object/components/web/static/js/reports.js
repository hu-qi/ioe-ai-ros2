/**
 * reports.js - 报告管理页逻辑（列表多条件筛选 + 详情查看）
 *
 * 数据源：
 *   GET /api/v1/reports          报告列表（多条件过滤 + 分页）
 *   GET /api/v1/reports/{id}     报告详情（reports + steps + substeps + events）
 */
(function () {
    'use strict';

    // ---------------- 状态 ----------------
    var state = {
        page: 1,
        pageSize: 20,
        totalPages: 1,
        stepIndex: -1  // 下钻步骤过滤（doc/72 V-03），-1 = 不过滤
    };

    // ---------------- 工具 ----------------
    function fmtTs(ms) {
        if (!ms) return '-';
        var d = new Date(Number(ms));
        if (isNaN(d.getTime())) return '-';
        function p(n) { return n < 10 ? '0' + n : n; }
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
            ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }

    function fmtDuration(ms) {
        if (ms === null || ms === undefined) return '-';
        var s = Math.round(Number(ms) / 1000);
        if (s < 60) return s + 's';
        var m = Math.floor(s / 60);
        return m + 'm' + (s % 60) + 's';
    }

    function esc(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    var FINISH_LABELS = {
        completed: '<span class="text-success">已完成</span>',
        interrupted: '<span class="text-warning">中断</span>',
        timeout: '<span class="text-danger">超时</span>'
    };

    var STEP_STATE_LABELS = {
        0: '<span class="text-muted">未执行</span>',
        1: '<span class="text-success">完成</span>',
        2: '<span class="text-warning">进行中</span>',
        3: '<span class="text-danger">遗漏</span>'
    };

    function getJson(url) {
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (body) {
            if (body.code !== 0) throw new Error(body.message || '接口错误');
            return body.data;
        });
    }

    // ---------------- 列表 ----------------
    function buildQuery() {
        var q = [];
        var student = $('#search-student').val().trim();
        var device = $('#search-device').val().trim();
        var finish = $('#search-finish').val();
        var start = $('#search-start').val();
        var end = $('#search-end').val();
        if (student) q.push('student_id=' + encodeURIComponent(student));
        if (device) q.push('device_id=' + encodeURIComponent(device));
        if (finish) q.push('finish_reason=' + encodeURIComponent(finish));
        if (start) q.push('start_ms=' + new Date(start + 'T00:00:00').getTime());
        if (end) q.push('end_ms=' + new Date(end + 'T23:59:59').getTime());
        if (state.stepIndex >= 0) q.push('step_index=' + state.stepIndex);
        q.push('page=' + state.page);
        q.push('page_size=' + state.pageSize);
        return q.join('&');
    }

    function loadList() {
        getJson('/api/v1/reports?' + buildQuery()).then(function (data) {
            var total = data.total || 0;
            state.totalPages = Math.max(1, Math.ceil(total / state.pageSize));
            $('#list-count').text('共 ' + total + ' 条');
            $('#page-info').text('第 ' + state.page + '/' + state.totalPages + ' 页');
            $('#btn-prev').prop('disabled', state.page <= 1);
            $('#btn-next').prop('disabled', state.page >= state.totalPages);

            var rows = data.list || [];
            if (!rows.length) {
                $('#reports-tbody').html(
                    '<tr><td colspan="9" class="text-center text-muted py-3">暂无报告数据</td></tr>');
                return;
            }
            var html = rows.map(function (r) {
                var student = r.student_id
                    ? esc(r.student_name || r.student_id) + ' (' + esc(r.student_id) + ')'
                    : '<span class="text-muted">未绑定</span>';
                var stubBadge = r.is_stub
                    ? ' <span class="badge bg-warning text-dark">接收中</span>' : '';
                return '<tr>' +
                    '<td><code>' + esc(r.report_id) + '</code>' + stubBadge + '</td>' +
                    '<td>' + student + '</td>' +
                    '<td>' + esc(r.device_id) + '</td>' +
                    '<td>' + esc(r.process_name || r.process_type || '-') + '</td>' +
                    '<td>' + (FINISH_LABELS[r.finish_reason] || esc(r.finish_reason || '-')) + '</td>' +
                    '<td>' + (r.total_score !== null && r.total_score !== undefined ? r.total_score : '-') + '</td>' +
                    '<td>' + fmtDuration(r.duration_ms) + '</td>' +
                    '<td>' + fmtTs(r.ts_upload_ms) + '</td>' +
                    '<td><button class="btn btn-outline btn-sm" onclick="window.__showReportDetail(\'' +
                        esc(r.report_id) + '\')"><i class="fas fa-eye"></i> 详情</button></td>' +
                    '</tr>';
            }).join('');
            $('#reports-tbody').html(html);
        }).catch(function (err) {
            console.error('加载报告列表失败:', err);
            $('#reports-tbody').html(
                '<tr><td colspan="9" class="text-center text-danger py-3">加载失败: ' +
                esc(err.message) + '</td></tr>');
        });
    }

    // ---------------- 详情 ----------------
    function showDetail(reportId) {
        getJson('/api/v1/reports/' + encodeURIComponent(reportId)).then(function (d) {
            var r = d.report || {};
            $('#d-report-id').text(r.report_id || reportId);
            $('#d-student').text(
                r.student_id ? (r.student_name || '') + ' (' + r.student_id + ')' : '未绑定');
            $('#d-device').text(r.device_id || '-');
            $('#d-process').text(r.process_name || r.process_type || '-');
            $('#d-finish').html(FINISH_LABELS[r.finish_reason] || esc(r.finish_reason || '-'));
            $('#d-score').text(r.total_score !== null && r.total_score !== undefined ? r.total_score : '-');
            $('#d-duration').text(fmtDuration(r.duration_ms));
            $('#d-upload').text(fmtTs(r.ts_upload_ms));
            $('#d-stub').html(r.is_stub
                ? '<span class="text-warning">存根（待整包补全）</span>'
                : '<span class="text-success">完整</span>');

            // 步骤明细
            var steps = d.steps || [];
            if (steps.length) {
                $('#d-steps-tbody').html(steps.map(function (s) {
                    return '<tr>' +
                        '<td>' + esc(s.idx) + '</td>' +
                        '<td>' + esc(s.name || '-') + '</td>' +
                        '<td>' + (STEP_STATE_LABELS[s.state] || esc(s.state)) + '</td>' +
                        '<td>' + (s.duration_ms !== null && s.duration_ms !== undefined ? s.duration_ms : '-') + '</td>' +
                        '<td>' + (s.interval_ms !== null && s.interval_ms !== undefined ? s.interval_ms : '-') + '</td>' +
                        '</tr>';
                }).join(''));
            } else {
                $('#d-steps-tbody').html('<tr><td colspan="5" class="text-center text-muted py-2">无数据</td></tr>');
            }

            // 子步骤明细
            var substeps = d.substeps || [];
            if (substeps.length) {
                $('#d-substeps-tbody').html(substeps.map(function (s) {
                    return '<tr>' +
                        '<td>' + esc(s.idx) + '</td>' +
                        '<td>' + esc(s.name || '-') + '</td>' +
                        '<td>' + (s.count !== null && s.count !== undefined ? s.count : '-') + '</td>' +
                        '<td>' + (s.total_duration_ms !== null && s.total_duration_ms !== undefined ? s.total_duration_ms : '-') + '</td>' +
                        '<td>' + (s.timeout ? '<span class="text-danger">是</span>' : '否') + '</td>' +
                        '</tr>';
                }).join(''));
            } else {
                $('#d-substeps-tbody').html('<tr><td colspan="5" class="text-center text-muted py-2">无数据</td></tr>');
            }

            // 事件流
            var events = d.events || [];
            if (events.length) {
                $('#d-events-tbody').html(events.map(function (e) {
                    return '<tr>' +
                        '<td>' + esc(e.ts) + '</td>' +
                        '<td>' + esc(e.kind) + '</td>' +
                        '<td>' + (e.step !== null && e.step !== undefined ? esc(e.step) : '-') + '</td>' +
                        '<td>' + (e.sub !== null && e.sub !== undefined ? esc(e.sub) : '-') + '</td>' +
                        '<td>' + esc(e.source || '-') + '</td>' +
                        '</tr>';
                }).join(''));
            } else {
                $('#d-events-tbody').html('<tr><td colspan="5" class="text-center text-muted py-2">无数据</td></tr>');
            }

            $('#detail-card').slideDown(150);
        }).catch(function (err) {
            console.error('加载报告详情失败:', err);
            if (window.AppDialog && AppDialog.alert) {
                AppDialog.alert({ title: '加载失败', message: err.message, type: 'error' });
            }
        });
    }

    // 详情按钮暴露给表格内联 onclick
    window.__showReportDetail = showDetail;

    // ---------------- 事件绑定 ----------------
    $(function () {
        $('#btn-search').on('click', function () {
            state.page = 1;
            loadList();
        });
        $('#search-student, #search-device').on('keydown', function (e) {
            if (e.key === 'Enter') { state.page = 1; loadList(); }
        });
        $('#btn-prev').on('click', function () {
            if (state.page > 1) { state.page--; loadList(); }
        });
        $('#btn-next').on('click', function () {
            if (state.page < state.totalPages) { state.page++; loadList(); }
        });
        $('#btn-close-detail').on('click', function () {
            $('#detail-card').slideUp(150);
        });

        // 支持 URL 参数直达: /reports?student_id=S001 /reports?step_index=1
        var params = new URLSearchParams(window.location.search);
        var sid = params.get('student_id');
        if (sid) $('#search-student').val(sid);
        var did = params.get('device_id');
        if (did) $('#search-device').val(did);
        var stepIdx = params.get('step_index');
        if (stepIdx !== null && stepIdx !== '' && !isNaN(Number(stepIdx))) {
            state.stepIndex = Number(stepIdx);
        }

        loadList();
    });
})();
