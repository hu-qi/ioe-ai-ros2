/**
 * students.js — 学员管理前端交互
 *
 * 工程基线: app_mgr_object-0.2.1
 * 关联文档: doc/69 学员管理插件开发方案
 *
 * 职责:
 *   1. 列表加载 + 分页
 *   2. 多条件检索（keyword / cls / status）
 *   3. 新增 / 编辑 / 删除（CRUD）
 *   4. CSV 批量导入 + 导出
 *   5. 学员详情展示（档案 + 历史考试记录占位）
 */

(function () {
    'use strict';

    // ========== 状态 ==========
    var state = {
        page: 1,
        pageSize: 20,
        total: 0,
        keyword: '',
        cls: '',
        status: 'active'
    };

    // ========== API ==========
    function apiGet(url) {
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    function apiPost(url, body, isJson) {
        var opts = { method: 'POST' };
        if (isJson) {
            opts.headers = { 'Content-Type': 'application/json' };
            opts.body = JSON.stringify(body);
        } else {
            opts.body = body; // FormData
        }
        return fetch(url, opts).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    function apiPut(url, body) {
        return fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    function apiDelete(url) {
        return fetch(url, { method: 'DELETE' }).then(function (r) {
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

    function statusLabel(status) {
        var map = {
            'active': '<span class="badge bg-success">在训</span>',
            'graduated': '<span class="badge bg-info">结业</span>',
            'dropped': '<span class="badge bg-warning">退学</span>',
            'deleted': '<span class="badge bg-danger">已删除</span>'
        };
        return map[status] || status;
    }

    function fmtDate(ms) {
        if (!ms) return '-';
        var d = new Date(ms);
        return d.toLocaleString('zh-CN', { hour12: false });
    }

    // ========== 列表加载 ==========
    function loadList() {
        var params = new URLSearchParams();
        if (state.keyword) params.set('keyword', state.keyword);
        if (state.cls) params.set('cls', state.cls);
        params.set('status', state.status);
        params.set('page', state.page);
        params.set('page_size', state.pageSize);

        var tbody = document.getElementById('students-tbody');
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">加载中...</td></tr>';

        apiGet('/api/v1/students?' + params.toString()).then(function (res) {
            if (res.code !== 0) {
                toast(res.message || '加载失败', 'error');
                return;
            }
            var data = res.data || {};
            state.total = data.total || 0;
            var list = data.list || [];

            if (list.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">暂无学员数据</td></tr>';
            } else {
                tbody.innerHTML = list.map(function (s) {
                    return '<tr>' +
                        '<td>' + escapeHtml(s.id) + '</td>' +
                        '<td>' + escapeHtml(s.name) + '</td>' +
                        '<td>' + escapeHtml(s.cls || '') + '</td>' +
                        '<td>' + escapeHtml(s.trade || '') + '</td>' +
                        '<td>' + escapeHtml(s.enroll_date || '') + '</td>' +
                        '<td>' + statusLabel(s.status) + '</td>' +
                        '<td>' +
                            '<button class="btn btn-outline btn-sm me-1 btn-detail" data-id="' + escapeHtml(s.id) + '">详情</button>' +
                            '<button class="btn btn-outline btn-sm me-1 btn-edit" data-id="' + escapeHtml(s.id) + '">编辑</button>' +
                            '<button class="btn btn-outline btn-sm btn-del" data-id="' + escapeHtml(s.id) + '" data-name="' + escapeHtml(s.name) + '">删除</button>' +
                        '</td>' +
                        '</tr>';
                }).join('');
            }

            // 更新计数与分页
            document.getElementById('list-count').textContent = '共 ' + state.total + ' 条';
            var totalPages = Math.ceil(state.total / state.pageSize) || 1;
            document.getElementById('page-info').textContent =
                '第 ' + state.page + '/' + totalPages + ' 页';
            document.getElementById('btn-prev').disabled = (state.page <= 1);
            document.getElementById('btn-next').disabled = (state.page >= totalPages);
        }).catch(function (err) {
            toast('加载列表失败: ' + err.message, 'error');
        });
    }

    // ========== 搜索 ==========
    function doSearch() {
        state.keyword = document.getElementById('search-keyword').value.trim();
        state.cls = document.getElementById('search-cls').value.trim();
        state.status = document.getElementById('search-status').value;
        state.page = 1;
        loadList();
    }

    // ========== 新增/编辑 ==========
    function openAddModal() {
        document.getElementById('form-mode').value = 'add';
        document.getElementById('modal-title').textContent = '新增学员';
        document.getElementById('form-id').value = '';
        document.getElementById('form-id').disabled = false;
        document.getElementById('form-name').value = '';
        document.getElementById('form-cls').value = '';
        document.getElementById('form-trade').value = '';
        document.getElementById('form-enroll').value = '';
        document.getElementById('form-remark').value = '';
        new bootstrap.Modal(document.getElementById('student-modal')).show();
    }

    function openEditModal(studentId) {
        apiGet('/api/v1/students/' + encodeURIComponent(studentId)).then(function (res) {
            if (res.code !== 0 || !res.data || !res.data.student) {
                toast('获取学员信息失败', 'error');
                return;
            }
            var s = res.data.student;
            document.getElementById('form-mode').value = 'edit';
            document.getElementById('modal-title').textContent = '编辑学员';
            document.getElementById('form-id').value = s.id;
            document.getElementById('form-id').disabled = true; // 工号不可改
            document.getElementById('form-name').value = s.name || '';
            document.getElementById('form-cls').value = s.cls || '';
            document.getElementById('form-trade').value = s.trade || '';
            document.getElementById('form-enroll').value = s.enroll_date || '';
            document.getElementById('form-remark').value = s.remark || '';
            new bootstrap.Modal(document.getElementById('student-modal')).show();
        }).catch(function (err) {
            toast('获取学员信息失败: ' + err.message, 'error');
        });
    }

    function saveStudent() {
        var mode = document.getElementById('form-mode').value;
        var data = {
            id: document.getElementById('form-id').value.trim(),
            name: document.getElementById('form-name').value.trim(),
            cls: document.getElementById('form-cls').value.trim(),
            trade: document.getElementById('form-trade').value.trim(),
            enroll_date: document.getElementById('form-enroll').value.trim(),
            remark: document.getElementById('form-remark').value.trim()
        };

        if (!data.id || !data.name) {
            toast('工号和姓名不能为空', 'warning');
            return;
        }

        var promise;
        if (mode === 'add') {
            promise = apiPost('/api/v1/students', data, true);
        } else {
            promise = apiPut('/api/v1/students/' + encodeURIComponent(data.id), data);
        }

        promise.then(function (res) {
            if (res.code === 0) {
                toast(mode === 'add' ? '新增成功' : '修改成功', 'success');
                bootstrap.Modal.getInstance(document.getElementById('student-modal')).hide();
                loadList();
            } else {
                toast(res.message || '操作失败', 'error');
            }
        }).catch(function (err) {
            toast('保存失败: ' + err.message, 'error');
        });
    }

    // ========== 删除 ==========
    function deleteStudent(studentId, studentName) {
        if (typeof AppDialog !== 'undefined') {
            AppDialog.confirm({
                title: '确认删除',
                message: '确定要删除学员 "' + studentName + '" 吗？\n（软删除，数据保留）',
                danger: true,
                confirmText: '删除',
                cancelText: '取消'
            }).then(function (ok) {
                if (ok) doDelete(studentId);
            });
        } else {
            if (confirm('确定要删除学员 "' + studentName + '" 吗？')) {
                doDelete(studentId);
            }
        }
    }

    function doDelete(studentId) {
        apiDelete('/api/v1/students/' + encodeURIComponent(studentId)).then(function (res) {
            if (res.code === 0) {
                toast('删除成功', 'success');
                loadList();
            } else {
                toast(res.message || '删除失败', 'error');
            }
        }).catch(function (err) {
            toast('删除失败: ' + err.message, 'error');
        });
    }

    // ========== 详情 ==========
    function showDetail(studentId) {
        apiGet('/api/v1/students/' + encodeURIComponent(studentId)).then(function (res) {
            if (res.code !== 0 || !res.data || !res.data.student) {
                toast('获取学员详情失败', 'error');
                return;
            }
            var s = res.data.student;
            document.getElementById('d-id').textContent = s.id || '-';
            document.getElementById('d-name').textContent = s.name || '-';
            document.getElementById('d-cls').textContent = s.cls || '-';
            document.getElementById('d-trade').textContent = s.trade || '-';
            document.getElementById('d-enroll').textContent = s.enroll_date || '-';
            document.getElementById('d-status').innerHTML = statusLabel(s.status);
            document.getElementById('d-remark').textContent = s.remark || '-';
            document.getElementById('d-created').textContent = fmtDate(s.created_at);

            // 历史考试记录占位
            var reportsArea = document.getElementById('reports-area');
            var recent = res.data.recent_reports || [];
            if (recent.length === 0) {
                reportsArea.innerHTML = '<div class="text-center text-muted py-3">暂无考试记录</div>';
            } else {
                reportsArea.innerHTML = '<table class="table table-sm"><thead><tr>' +
                    '<th>报告ID</th><th>设备</th><th>用时</th><th>得分</th><th>上报时间</th><th>操作</th>' +
                    '</tr></thead><tbody>' +
                    recent.map(function (r) {
                        return '<tr><td>' + escapeHtml(r.report_id || '') + '</td>' +
                            '<td>' + escapeHtml(r.device_id || '') + '</td>' +
                            '<td>' + escapeHtml(r.duration_ms || '') + '</td>' +
                            '<td>' + escapeHtml(r.total_score || '') + '</td>' +
                            '<td>' + fmtDate(r.ts_upload_ms) + '</td>' +
                            '<td><a href="/reports?student_id=' + encodeURIComponent(s.id) + '">查看全部</a></td></tr>';
                    }).join('') +
                    '</tbody></table>';
            }

            document.getElementById('detail-card').style.display = '';
        }).catch(function (err) {
            toast('获取详情失败: ' + err.message, 'error');
        });
    }

    // ========== 导入 ==========
    function doImport() {
        var fileInput = document.getElementById('import-file');
        if (!fileInput.files || fileInput.files.length === 0) {
            toast('请先选择 CSV 文件', 'warning');
            return;
        }
        var formData = new FormData();
        formData.append('file', fileInput.files[0]);

        apiPost('/api/v1/students/import', formData, false).then(function (res) {
            if (res.code === 0) {
                var data = res.data || {};
                var html = '<div class="alert alert-success">导入完成：成功 ' +
                    (data.success || 0) + ' 条，失败 ' + (data.failed || 0) + ' 条</div>';
                if (data.errors && data.errors.length > 0) {
                    html += '<div class="alert alert-warning"><b>错误明细：</b><ul class="mb-0">';
                    data.errors.forEach(function (e) {
                        html += '<li>第 ' + e.row + ' 行: ' + escapeHtml(e.reason) + '</li>';
                    });
                    html += '</ul></div>';
                }
                document.getElementById('import-result').innerHTML = html;
                document.getElementById('import-result').style.display = '';
                toast('导入完成', 'success');
                loadList();
            } else {
                toast(res.message || '导入失败', 'error');
            }
        }).catch(function (err) {
            toast('导入失败: ' + err.message, 'error');
        });
    }

    // ========== 导出 ==========
    function doExport() {
        var params = new URLSearchParams();
        if (state.keyword) params.set('keyword', state.keyword);
        if (state.cls) params.set('cls', state.cls);
        params.set('status', state.status);

        window.location.href = '/api/v1/students/export?' + params.toString();
    }

    // ========== 事件绑定 ==========
    function bindEvents() {
        // 搜索
        document.getElementById('btn-search').addEventListener('click', doSearch);
        document.getElementById('search-keyword').addEventListener('keypress', function (e) {
            if (e.key === 'Enter') doSearch();
        });

        // 新增
        document.getElementById('btn-add').addEventListener('click', openAddModal);

        // 保存
        document.getElementById('btn-save-student').addEventListener('click', saveStudent);

        // 导入
        document.getElementById('btn-import').addEventListener('click', function () {
            document.getElementById('import-result').style.display = 'none';
            document.getElementById('import-result').innerHTML = '';
            document.getElementById('import-file').value = '';
            new bootstrap.Modal(document.getElementById('import-modal')).show();
        });
        document.getElementById('btn-do-import').addEventListener('click', doImport);

        // 导出
        document.getElementById('btn-export').addEventListener('click', doExport);

        // 分页
        document.getElementById('btn-prev').addEventListener('click', function () {
            if (state.page > 1) { state.page--; loadList(); }
        });
        document.getElementById('btn-next').addEventListener('click', function () {
            var totalPages = Math.ceil(state.total / state.pageSize) || 1;
            if (state.page < totalPages) { state.page++; loadList(); }
        });

        // 列表按钮（事件委托）
        document.getElementById('students-tbody').addEventListener('click', function (e) {
            var btn = e.target.closest('button');
            if (!btn) return;
            var id = btn.getAttribute('data-id');
            if (btn.classList.contains('btn-detail')) {
                showDetail(id);
            } else if (btn.classList.contains('btn-edit')) {
                openEditModal(id);
            } else if (btn.classList.contains('btn-del')) {
                deleteStudent(id, btn.getAttribute('data-name'));
            }
        });

        // 关闭详情
        document.getElementById('btn-close-detail').addEventListener('click', function () {
            document.getElementById('detail-card').style.display = 'none';
        });
    }

    // ========== 初始化 ==========
    document.addEventListener('DOMContentLoaded', function () {
        bindEvents();
        loadList();
        if (typeof window !== 'undefined' && typeof window.pageLoaded === 'function') {
            window.pageLoaded();
        }
    });

})();
