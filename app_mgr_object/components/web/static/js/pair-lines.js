/**
 * P1 任务配对仓位连线（v2 背景空间曲线路由）
 * 规范: doc/P1-任务配对仓位连线-技术开发规范.md（v2）
 * 数据源: business_update WS（task_queue.queue → pending 虚线 / active_instances → active 实线流光）
 * 设计: 端点取卡片边缘（src 右缘 / dst 左缘），路径走两列间背景带（gutter + 卡片外侧），
 *       轨道 lane 按 src.cy 排序分配 → 垂直段平行不交叉；三次贝塞尔 S 弯平滑。
 */
(function () {
    'use strict';

    var LANE_GAP = 6;      // 轨道间距 px
    var MAX_LANES = 8;     // 轨道上限（超出后 gap 自适应缩小，保底 3px）
    var BAND_MAX = 48;     // 背景带最大可用宽度 px（用于 gap 自适应）

    function PairLineRenderer() {
        this.svg = document.getElementById('pair-lines');
        if (!this.svg) { this._disabled = true; return; }
        this._disabled = false;
        this._lines = {};   // key: 'src→dst' -> { state, pathEl, nodeSEl, nodeDEl }
        this._keys = [];    // 当前 key 有序列表（lane 分配依据）
        var self = this;
        window.addEventListener('resize', function () { self.refresh(); });
    }

    /* ---------- 坐标 ---------- */

    // 卡片矩形（相对 svg 坐标系）
    PairLineRenderer.prototype._cellRect = function (bayId) {
        if (!bayId || !this.svg) return null;
        var el = document.querySelector('[data-bay-id="' + bayId + '"]');
        if (!el) return null;
        var r = el.getBoundingClientRect();
        var s = this.svg.getBoundingClientRect();
        return {
            left: r.left - s.left, top: r.top - s.top,
            right: r.right - s.left, bottom: r.bottom - s.top,
            cx: (r.left + r.right) / 2 - s.left,
            cy: (r.top + r.bottom) / 2 - s.top
        };
    };

    // 轨道水平偏移：dx = (laneIdx - (n-1)/2) * gap；n 超限时 gap 自适应
    PairLineRenderer.prototype._laneDx = function (laneIdx, n) {
        var gap = LANE_GAP;
        if (n > MAX_LANES) gap = Math.max(3, Math.floor(BAND_MAX / n));
        return (laneIdx - (n - 1) / 2) * gap;
    };

    // 贝塞尔 path d（规范 4.4 v5：单段三次贝塞尔全曲线，无直线段）
    // M sx,sy C mx,sy mx,dy dx,dy —— 起点水平引出、背景带内平滑转折、终点水平引入
    PairLineRenderer.prototype._pathD = function (srcR, dstR, laneDx) {
        var sx = srcR.right, sy = srcR.cy;       // src 右边缘中点
        var dx = dstR.left, dy = dstR.cy;        // dst 左边缘中点
        var mx = (sx + dx) / 2 + laneDx;          // 背景带中心 + 轨道偏移
        var f = function (v) { return v.toFixed(1); };
        return 'M ' + f(sx) + ',' + f(sy) +
               ' C ' + f(mx) + ',' + f(sy) +
               ' ' + f(mx) + ',' + f(dy) +
               ' ' + f(dx) + ',' + f(dy);
    };

    /* ---------- 状态辅助（v5 三态：pending/active/error） ---------- */

    PairLineRenderer.prototype._normState = function (s) {
        return (s === 'active' || s === 'error') ? s : 'pending';
    };
    PairLineRenderer.prototype._stateRank = function (s) {
        return s === 'error' ? 3 : (s === 'active' ? 2 : 1);
    };

    /* ---------- 元素管理 ---------- */

    PairLineRenderer.prototype._makeEl = function (tag, cls) {
        var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        el.setAttribute('class', cls);
        return el;
    };

    // 创建一条线的 SVG 元素（path + 两端圆点；r 必须显式设置，默认 0 不可见——v3 修复）
    PairLineRenderer.prototype._create = function (key, state) {
        var path = this._makeEl('path', 'pair-line pair-line-' + state);
        var nS = this._makeEl('circle', 'pair-node');
        var nD = this._makeEl('circle', 'pair-node');
        nS.setAttribute('r', '4');
        nD.setAttribute('r', '4');
        this.svg.appendChild(path);
        this.svg.appendChild(nS);
        this.svg.appendChild(nD);
        this._lines[key] = { state: state, pathEl: path, nodeSEl: nS, nodeDEl: nD };
    };

    // 更新一条线的几何（path d + 端点圆点位置）
    PairLineRenderer.prototype._updateGeometry = function (key, laneDx) {
        var line = this._lines[key];
        if (!line) return;
        var parts = key.split('→');
        var srcR = this._cellRect(parts[0]);
        var dstR = this._cellRect(parts[1]);
        if (!srcR || !dstR) return;   // 卡片未渲染 → 跳过（健壮）
        line.pathEl.setAttribute('d', this._pathD(srcR, dstR, laneDx));
        line.nodeSEl.setAttribute('cx', (srcR.right + 2).toFixed(1));
        line.nodeSEl.setAttribute('cy', srcR.cy.toFixed(1));
        line.nodeDEl.setAttribute('cx', (dstR.left - 2).toFixed(1));
        line.nodeDEl.setAttribute('cy', dstR.cy.toFixed(1));
    };

    /* ---------- 公开 API ---------- */

    // 入参: [{ src, dst, state: 'pending'|'active', robot_id? }]
    PairLineRenderer.prototype.update = function (pairs) {
        if (this._disabled) return;
        pairs = pairs || [];
        if (pairs.length > 0) console.log('[P1] pair lines:', pairs.length, pairs.map(function(p){ return p.src + '→' + p.dst + ':' + p.state; }).join(' '));
        var wanted = {};
        var i, p, key, line;

        // 1. upsert
        for (i = 0; i < pairs.length; i++) {
            p = pairs[i];
            if (!p || !p.src || !p.dst) continue;
            key = p.src + '→' + p.dst;
            wanted[key] = true;
            line = this._lines[key];
            if (!line) {
                this._create(key, this._normState(p.state));
            } else if (line.state !== this._normState(p.state)) {
                // 多状态同 key：error > active > pending 覆盖
                if (this._stateRank(p.state) >= this._stateRank(line.state)) {
                    line.state = this._normState(p.state);
                    line.pathEl.setAttribute('class', 'pair-line pair-line-' + line.state);
                }
            }
        }

        // 2. 清理：不在输入集合的旧线（淡出后移除）
        var stale = [];
        for (key in this._lines) {
            if (!wanted[key]) stale.push(key);
        }
        for (i = 0; i < stale.length; i++) this.remove(stale[i]);

        // 3. 轨道重分配 + 几何刷新
        this.refresh();
    };

    PairLineRenderer.prototype.remove = function (key) {
        var line = this._lines[key];
        if (!line) return;
        var self = this;
        var els = [line.pathEl, line.nodeSEl, line.nodeDEl];
        els.forEach(function (el) {
            el.classList.add('pair-removing');
        });
        setTimeout(function () {
            els.forEach(function (el) { if (el.parentNode) el.parentNode.removeChild(el); });
        }, 650);   // 与 CSS transition .6s 对齐
        delete this._lines[key];
    };

    // 重算所有线坐标（lane 按 src.cy 排序分配）
    PairLineRenderer.prototype.refresh = function () {
        if (this._disabled) return;
        var keys = Object.keys(this._lines);
        var n = keys.length;
        if (n === 0) return;

        // 排序：按 src.cy 升序（同 cy 按 dst.cy 次排序）→ lane 分配稳定
        var self = this;
        keys.sort(function (a, b) {
            var ra = self._cellRect(a.split('→')[0]);
            var rb = self._cellRect(b.split('→')[0]);
            if (!ra || !rb) return 0;
            if (ra.cy !== rb.cy) return ra.cy - rb.cy;
            var da = self._cellRect(a.split('→')[1]);
            var db = self._cellRect(b.split('→')[1]);
            return (da && db && da.cy !== db.cy) ? da.cy - db.cy : 0;
        });
        var self2 = this;
        keys.forEach(function (key, idx) {
            self2._updateGeometry(key, self2._laneDx(idx, n));
        });
    };

    // 暴露单例
    window.PairLines = new PairLineRenderer();
})();
