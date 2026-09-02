#!/usr/bin/env python3
"""
OpsControlProxy — OPS 统一节点控制代理（P2，doc/P2-统一节点服务控制-技术详细规划.md v2）

职责：app_mgr 节点/服务控制（start/stop/restart）统一委托 OPS（device_ops_center :1818）执行，
      OPS 内部自动协调看门狗（stop→pause 防拉起 / restart→reset / start→resume）。

API:
  - list_nodes():  权威节点源（OPS /api/nodes），display_map 覆盖展示名，逐节点 service 状态
  - node_status(): OPS /api/nodes/{name}/service
  - execute():     OPS /api/nodes/{name}/restart|stop|start
  - ops_status():  OPS /api/status（P3 状态统一复用）

通用性：
  - base_url 注入（同机 127.0.0.1 / 跨机 IP / 多设备集群扩展），接口与地址解耦；
  - OPS 离线 5s 短缓存快速失败（参考 OPS doc/78 离线降级思路），恢复自动清除。
"""
import time
import logging

import requests


class OpsControlProxy:
    """OPS 统一控制代理（HTTP 客户端）"""

    def __init__(self, base_url=None, timeout_s=10, display_map=None, logger=None):
        self.base_url = (base_url or "http://127.0.0.1:1818").rstrip("/")
        self.timeout = float(timeout_s or 10)
        self.display_map = dict(display_map or {})
        self.logger = logger or logging.getLogger("ops_proxy")
        # 离线窗口（5s 内快速失败）
        self._offline_until = 0.0
        self._offline_reason = ""
        # 加载优化：状态类响应 TTL 缓存（doc/前端页面加载优化）——path -> (ts, data)
        self._cache = {}

    # ---------------- 内部 ----------------

    def _call(self, method, path, timeout=None, raw=False, **kw):
        """统一 HTTP 调用；OPS 不可达/超时 → 降级返回 {success: False, error}"""
        if time.time() < self._offline_until:
            return {"success": False, "error": self._offline_reason, "offline": True}
        try:
            r = requests.request(
                method, self.base_url + path,
                timeout=timeout or self.timeout, **kw)
            if r.status_code >= 400:
                return {"success": False,
                        "error": "OPS HTTP %d: %s" % (r.status_code, r.text[:200])}
            if raw:
                return r.content   # 二进制（如 JPEG 帧）
            try:
                return r.json()
            except Exception:
                return {"success": True, "raw": r.text}
        except requests.exceptions.Timeout:
            self._mark_offline("OPS 请求超时")
            return {"success": False, "error": "OPS 请求超时", "offline": True}
        except Exception as e:
            self._mark_offline("OPS 不可达: %s" % e)
            return {"success": False, "error": "OPS 不可达: %s" % e, "offline": True}

    def _mark_offline(self, reason):
        self._offline_until = time.time() + 5
        self._offline_reason = reason
        if self.logger:
            self.logger.warning("[OpsProxy] %s" % reason)

    def _recover(self):
        self._offline_until = 0.0

    def _cached(self, key, fn, ttl=5.0):
        """TTL 缓存（5s）：页面/轮询复用，减少 OPS HTTP 往返；执行操作后需 clear_cache"""
        now = time.time()
        hit = self._cache.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1]
        data = fn()
        self._cache[key] = (now, data)
        return data

    def clear_cache(self):
        """操作后清缓存（节点状态变化）"""
        self._cache = {}

    @staticmethod
    def _display(node, display_map):
        """展示名：display_map[OPS 节点名] 覆盖；缺省用 OPS 节点名"""
        name = node.get("name", "")
        return display_map.get(name, name)

    # ---------------- 对外 API ----------------

    def list_nodes(self):
        """权威节点源：OPS /api/nodes + 逐节点 service 状态（5s TTL 缓存）"""
        resp = self._cached("nodes", lambda: self._call("GET", "/api/nodes"))
        if not resp.get("success", False):
            return {"success": False, "error": resp.get("error", "获取节点失败"),
                    "nodes": [], "offline": resp.get("offline", False)}
        items = []
        for n in resp.get("nodes", []):
            items.append({
                "name": n.get("name", ""),                       # OPS 注册名（控制用）
                "display": self._display(n, self.display_map),   # UI 展示名
                "watchdog_status": n.get("watchdog_status", "unknown"),
                "health_type": (n.get("health") or {}).get("type", "unknown"),
                "node_name": n.get("node_name", ""),
                "has_restart": bool(n.get("restart")),
            })
        return {"success": True, "nodes": items, "offline": False}

    def node_status(self, name):
        """单节点服务/进程状态：OPS /api/nodes/{name}/service"""
        return self._call("GET", "/api/nodes/%s/service" % name)

    def execute(self, name, action):
        """节点控制：POST /api/nodes/{name}/restart|stop|start（OPS 协调看门狗）"""
        if action not in ("start", "stop", "restart"):
            return {"success": False, "error": "不支持的操作: %s" % action}
        resp = self._call("POST", "/api/nodes/%s/%s" % (name, action))
        if not resp.get("success", False):
            return {"success": False, "error": resp.get("error", "操作失败"),
                    "offline": resp.get("offline", False)}
        self.clear_cache()   # 节点状态变化，清缓存使下次刷新即时生效
        return {"success": True, "error": resp.get("error", ""),
                "paused": resp.get("auto_recovery_paused", False)}

    def ops_status(self):
        """OPS 系统状态（P3 复用）：GET /api/status（5s TTL 缓存）"""
        return self._cached("status", lambda: self._call("GET", "/api/status"))

    def channels_status(self):
        """P3 v2：权威通道状态（OPS /api/rtsp/channels，帧新鲜度，doc/P3 v2；5s TTL 缓存）"""
        return self._cached("channels", lambda: self._call("GET", "/api/rtsp/channels"))

    def calibration(self, method, path, body=None, raw=False):
        """P4：标定 REST 通用转发（OPS /api/calibration/*，doc/P4）
        - body 非空 → JSON POST/PUT；raw=True → 返回二进制内容（JPEG 帧）
        - OPS 不可达/失败时返回 {success:False, error}（调用方降级本地）
        """
        if body is not None:
            return self._call(method, path, json=body, raw=raw)
        return self._call(method, path, raw=raw)
