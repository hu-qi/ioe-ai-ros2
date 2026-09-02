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