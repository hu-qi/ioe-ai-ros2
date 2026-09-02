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
    getScheduleConfig:   function() { return this._get('/api/config/schedule'); },
    setWorkSchedule:     function(ws) { return this._put('/api/config/schedule', ws); },
    getPairingPolicy:    function() { return this._get('/api/config/policy'); },
    setPairingPolicy:    function(p) { return this._put('/api/config/policy', { policy: p }); },

    // 仓位编排（P4 代理：OPS 透传优先，失败 image_manager ros2 param set 降级）
    getCalibrationParam: function(name) { return this._get('/api/calibration/inference_param/' + encodeURIComponent(name)); },
    setCalibrationParam: function(name, value) { return this._post('/api/calibration/set_param', { name: name, value: value }); },

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