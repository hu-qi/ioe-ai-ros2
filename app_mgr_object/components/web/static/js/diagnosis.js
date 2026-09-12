/**
 * diagnosis.js — 诊断中心页（P2/P4 初版）
 * 数据源: GET /api/v1/analysis/diagnosis?cls=&process_name=
 * 结果特性: diagnosis_type / metric_value / threshold_value / advice_text / evidence[]
 */
(function () {
    'use strict';

    var TYPE_META = {
        bottleneck:       { label: '全班瓶颈',   icon: 'fa-hourglass-half', cls: 'danger' },
        persistent_error: { label: '顽固错误',   icon: 'fa-times-circle',   cls: 'warning' },
        sequence_chaos:   { label: '顺序混乱',   icon: 'fa-random',         cls: 'warning' },
        interval:         { label: '衔接卡壳',   icon: 'fa-link',           cls: 'info' },
        stddev:           { label: '用时差异大', icon: 'fa-chart-bar',      cls: 'info' },
        student_regression: { label: '学员退步', icon: 'fa-user-slash',     cls: 'danger' }
    };

    function esc(s) {
        return String(s === null || s === undefined ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function runDiagnosis() {
        var cls = ($('#q-cls').val() || '').trim();
        var proc = ($('#q-process').val() || '').trim();
        var params = new URLSearchParams();
        if (cls) { params.set('cls', cls); }
        if (proc) { params.set('process_name', proc); }

        getJson('/api/v1/analysis/diagnosis?' + params.toString()).then(function (d) {
            var payload = d.data || {};
            var list = payload.diagnoses || [];
            var $list = $('#diag-list');
            $('#diag-count').text('（共 ' + list.length + ' 条）');

            if (!list.length) {
                $list.empty();
                $('#diag-result-card').hide();
                $('#diag-empty').show();
                return;
            }
            $('#diag-empty').hide();

            $list.html(list.map(function (r) {
                var meta = TYPE_META[r.diagnosis_type] ||
                    { label: r.diagnosis_type, icon: 'fa-info-circle', cls: 'secondary' };
                var evHtml = '';
                var evs = r.evidence || [];
                if (evs.length) {
                    evHtml = '<div class="mt-2 d-flex flex-wrap gap-2">' + evs.map(function (ev) {
                        if (!ev.id) {
                            return '<span class="badge bg-secondary">证据 sub' + esc(ev.sub) + '（端侧文件）</span>';
                        }
                        return '<a href="/api/v1/evidence/' + ev.id + '/image" target="_blank" title="sub' + esc(ev.sub) + ' t' + esc(ev.ts) + '">' +
                            '<img src="/api/v1/evidence/' + ev.id + '/image?thumb=1" ' +
                            'style="height:72px;border-radius:4px;border:1px solid #ddd;" ' +
                            'onerror="this.style.display=\'none\'"></a>';
                    }).join('') + '</div>';
                }

                return '<div class="border rounded p-2 mb-2">' +
                    '<div class="d-flex justify-content-between align-items-center">' +
                    '<span><i class="fas ' + meta.icon + '"></i> ' +
                    '<span class="badge bg-' + meta.cls + '">' + esc(meta.label) + '</span> ' +
                    esc(r.target_id || '') +
                    (r.process_name ? ' <span class="badge bg-light text-dark">' + esc(r.process_name) + '</span>' : '') +
                    '</span>' +
                    '<span class="small text-muted">' + esc(r.metric_label || '') + '</span>' +
                    '</div>' +
                    '<div class="mt-1"><i class="fas fa-lightbulb text-warning"></i> ' +
                    esc(r.advice_text || '-') + '</div>' +
                    evHtml +
                    '</div>';
            }).join(''));

            $('#diag-result-card').show();
        }).catch(function (err) {
            if (window.AppDialog && AppDialog.alert) {
                AppDialog.alert({ title: '诊断失败', message: err.message, type: 'error' });
            }
        });
    }

    $(function () {
        $('#btn-run').on('click', runDiagnosis);
        $('#q-cls').on('keydown', function (e) {
            if (e.key === 'Enter') { runDiagnosis(); }
        });
    });
})();
