"""
HTTP 端到端验证（ASGI 直驱，无需 httpx/TestClient）

覆盖 doc/70 §8.3 / §8.4 全部 9 个 /api/v1 端点冒烟：
  - POST /api/v1/reports            整包接收
  - GET  /api/v1/reports            报告列表检索
  - GET  /api/v1/reports/{id}       报告详情
  - POST /api/v1/events             增量事件接收
  - POST /api/v1/subscriptions      订阅设备
  - GET  /api/v1/subscriptions      订阅设备列表
  - GET  /api/v1/subscriptions/{id} 查询订阅状态
  - DELETE /api/v1/subscriptions/{id} 退订设备
  - POST /api/v1/evidence           抓拍图接收
  - 输入校验：缺必填字段返回 422
  - 退订后重新订阅必须重新激活 active=True
  - 增量先于整包到达，整包补全存根报告

使用最小 ASGI client（不依赖 httpx/starlette.testclient），
直接构造 scope/receive/send 调用 FastAPI 应用。
"""

import os
import json
import asyncio

from conftest import (
    DB, RAW_DIR, EVID_DIR, FULL_PAYLOAD, DELTA_PAYLOAD,
    StubLogger, fresh_env, clone,
)


# ── 最小 ASGI client ────────────────────────────────────────────────────
def _request(app, method, path, *, json_body=None, form_fields=None,
              files=None):
    """
    同步封装：发起一次 ASGI HTTP 请求，返回 (status, body_dict_or_bytes)。

    支持 application/json 和 multipart/form-data（手工构造 boundary）。
    """
    scope = {
        "type": "http",
        "method": method,
        "path": path.split("?")[0],
        "raw_path": path.split("?")[0].encode(),
        "query_string": (path.split("?", 1)[1].encode()
                         if "?" in path else b""),
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "server": ("test", 80),
        "root_path": "",
        "http_version": "1.1",
        "app": app,
        "path_params": {},
    }
    body_bytes = b""
    content_type = ""

    if json_body is not None:
        body_bytes = json.dumps(json_body).encode()
        content_type = "application/json"
    elif form_fields is not None or files is not None:
        boundary = "----asgiTestBoundary126"
        parts = []
        # form 字段
        for k, v in (form_fields or {}).items():
            parts.append(("--" + boundary).encode())
            parts.append(
                b'Content-Disposition: form-data; name="' + k.encode() + b'"')
            parts.append(b"")
            parts.append(str(v).encode())
        # 文件字段
        for field_name, file_tuple in (files or {}).items():
            fname, fbytes, fmime = file_tuple
            parts.append(("--" + boundary).encode())
            parts.append(
                b'Content-Disposition: form-data; name="' +
                field_name.encode() + b'"; filename="' + fname.encode() + b'"')
            parts.append(b"Content-Type: " + fmime.encode())
            parts.append(b"")
            parts.append(fbytes)
        # 组装
        body_bytes = b"\r\n".join(
            [p if isinstance(p, bytes) else p.encode() for p in parts]
        )
        body_bytes += ("\r\n--" + boundary + "--\r\n").encode()
        content_type = "multipart/form-data; boundary=" + boundary

    if content_type:
        scope["headers"] = [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body_bytes)).encode()),
        ]

    # 收集响应
    response = {"status": 0, "headers": [], "body": b""}
    sent_body = {"chunks": [], "index": 0}

    async def receive():
        chunks = sent_body["chunks"]
        idx = sent_body["index"]
        if idx >= len(chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        sent_body["index"] += 1
        return {"type": "http.request", "body": chunks[idx],
                "more_body": idx < len(chunks) - 1}

    async def send(message):
        if message["type"] == "http.response.start":
            response["status"] = message["status"]
            response["headers"] = message.get("headers", [])
        elif message["type"] == "http.response.body":
            response["body"] += message.get("body", b"")

    # 切分 body 为多个 chunk（模拟 more_body）
    chunk_size = 4096
    sent_body["chunks"] = [
        body_bytes[i:i + chunk_size]
        for i in range(0, len(body_bytes), chunk_size)
    ]
    if not sent_body["chunks"]:
        sent_body["chunks"] = [b""]

    # 处理 ASGI 异常（路由不存在返回 404 时框架会抛）
    try:
        asyncio.run(app(scope, receive, send))
    except Exception:
        # 由上层判断 status
        pass

    # 解析响应体
    body = response["body"]
    ct = ""
    for h in response["headers"]:
        if h[0] == b"content-type":
            ct = h[1].decode()
    if "application/json" in ct:
        try:
            return response["status"], json.loads(body)
        except Exception:
            return response["status"], body
    return response["status"], body


def _make_app():
    """构造并激活 FastAPI 应用，返回 (app, plugin)"""
    from fastapi import FastAPI
    fresh_env()
    from app_mgr_object.components.web.report_recv_plugin import ReportRecvPlugin

    class StubNode:
        def get_logger(self):
            return StubLogger()

    plugin = ReportRecvPlugin(
        StubNode(),
        config={
            "db_path": DB,
            "raw_json_dir": RAW_DIR,
            "evidence_dir": EVID_DIR,
        }
    )
    plugin.configure()
    plugin.activate()

    app = FastAPI()
    plugin.register_routes(app, None)
    return app, plugin


# ── 测试用例 ────────────────────────────────────────────────────────────
def test_post_reports_full_receive():
    """POST /api/v1/reports 整包接收"""
    app, _ = _make_app()
    status, body = _request(app, "POST", "/api/v1/reports",
                            json_body=FULL_PAYLOAD)
    assert status == 200, "整包接收状态码错: %s" % status
    assert body["code"] == 0
    assert body["data"]["report_id"] == "Rdev01_1787569113000"


def test_post_events_delta_receive():
    """POST /api/v1/events 增量接收"""
    app, _ = _make_app()
    status, body = _request(app, "POST", "/api/v1/events",
                            json_body=DELTA_PAYLOAD)
    assert status == 200, "增量接收状态码错: %s" % status
    assert body["code"] == 0
    assert body["data"]["delta_events"] == 2, \
        "增量应插 2, 实际 %d" % body["data"]["delta_events"]


def test_subscriptions_full_lifecycle():
    """订阅管理 4 接口冒烟：POST/GET/DELETE/列表"""
    app, _ = _make_app()
    # 订阅
    status, body = _request(app, "POST", "/api/v1/subscriptions",
                            json_body={"device_id": "dev99", "note": "test"})
    assert status == 200 and body["code"] == 0
    # 查询状态
    status, body = _request(app, "GET", "/api/v1/subscriptions/dev99")
    assert status == 200
    assert body["data"]["active"] is True, "新订阅 active 应为 True"
    # 列表
    status, body = _request(app, "GET", "/api/v1/subscriptions")
    assert status == 200 and "devices" in body["data"]
    # 退订
    status, body = _request(app, "DELETE", "/api/v1/subscriptions/dev99")
    assert status == 200 and body["code"] == 0
    # 验证退订后状态
    status, body = _request(app, "GET", "/api/v1/subscriptions/dev99")
    assert body["data"]["active"] is False, "退订后 active 应为 False"


def test_get_reports_list():
    """GET /api/v1/reports 列表检索"""
    app, _ = _make_app()
    _request(app, "POST", "/api/v1/reports", json_body=FULL_PAYLOAD)
    status, body = _request(app, "GET", "/api/v1/reports?device_id=dev01")
    assert status == 200
    assert body["code"] == 0
    assert body["data"]["total"] >= 1, \
        "检索 dev01 应至少 1 条, 实际 %d" % body["data"]["total"]


def test_get_report_detail():
    """GET /api/v1/reports/{id} 报告详情"""
    app, _ = _make_app()
    _request(app, "POST", "/api/v1/reports", json_body=FULL_PAYLOAD)
    status, body = _request(app, "GET",
                            "/api/v1/reports/Rdev01_1787569113000")
    assert status == 200
    assert body["code"] == 0
    assert body["data"]["report"]["report_id"] == "Rdev01_1787569113000"
    assert len(body["data"]["events"]) >= 2, "events 应 >= 2"


def test_post_evidence_receive():
    """POST /api/v1/evidence 抓拍图接收"""
    app, _ = _make_app()
    status, body = _request(
        app, "POST", "/api/v1/evidence",
        files={"file": ("test.jpg", b"\xff\xd8\xff\xe0fake_jpg",
                        "image/jpeg")},
        form_fields={"sub": "1", "ts": "3200", "device_id": "dev01"},
    )
    assert status == 200, "evidence 接收状态码错: %s" % status
    assert body["code"] == 0
    assert os.path.exists(body["data"]["path"]), "evidence 文件不存在"


def test_input_validation_422():
    """输入校验：缺必填字段返回 422"""
    app, _ = _make_app()
    status, body = _request(app, "POST", "/api/v1/reports",
                            json_body={"device_id": "x"})
    assert status == 422, "缺必填字段应返回 422, 实际 %s" % status


def test_resubscribe_reactivates_via_http():
    """HTTP 层验证：退订后重新订阅必须重新激活 active=True"""
    app, _ = _make_app()
    # 订阅 → 退订 → 重新订阅
    _request(app, "POST", "/api/v1/subscriptions",
             json_body={"device_id": "dev77"})
    _request(app, "DELETE", "/api/v1/subscriptions/dev77")
    _request(app, "POST", "/api/v1/subscriptions",
             json_body={"device_id": "dev77"})
    status, body = _request(app, "GET", "/api/v1/subscriptions/dev77")
    assert body["data"]["active"] is True, \
        "HTTP 重新订阅后 active 必须为 True"


def test_reconcile_full_after_delta_via_http():
    """HTTP 层验证：增量先于整包到达，整包补全存根报告"""
    app, _ = _make_app()
    # 先发增量（创建存根）
    delta = {
        "schema_version": "1.1", "type": "event_delta",
        "device_id": "dev88", "edge_node": "touch_ui_plugin",
        "ts_upload_ms": 1788408000000,
        "round_start_ms": 1788407500000, "process_elapsed_ms": 500000,
        "student": {},
        "events": [{"ts": 1000, "kind": 0, "step": 1, "sub": 1}],
        "progress": {"done": 1, "total": 19, "current": "装缓冲",
                     "current_sub_index": 1}
    }
    status, body = _request(app, "POST", "/api/v1/events", json_body=delta)
    assert status == 200
    # 后发整包（补全存根）
    full = {
        "schema_version": "1.0", "device_id": "dev88",
        "edge_node": "touch_ui_plugin", "ts_upload_ms": 1788408100000,
        "student": {"id": "S2024088", "name": "王五", "cls": "三班",
                    "source": "manual"},
        "round": {
            "process_name": "拆装", "process_type": "disass",
            "finish_reason": "completed",
            "start_ms": 1788407500000, "end_ms": 1788408000000,
            "duration_ms": 50000, "process_elapsed_ms": 50000,
            "events": [
                {"ts": 1000, "kind": 0, "step": 1, "sub": 1},  # 与增量重复
                {"ts": 2000, "kind": 1, "step": 1, "sub": 1},  # 整包独有
            ],
            "steps": [], "substeps": [],
            "unexecuted": [], "substep_counts": []
        }
    }
    status, body = _request(app, "POST", "/api/v1/reports", json_body=full)
    assert status == 200
    # 查询详情，验证补全
    status, body = _request(app, "GET",
                            "/api/v1/reports/Rdev88_1788407500000")
    assert status == 200
    assert body["data"]["report"]["is_stub"] == 0, \
        "整包补全后 is_stub 应为 0"
    assert body["data"]["report"]["finish_reason"] == "completed", \
        "整包补全后 finish_reason 应为 completed"
    # 合并后应 2 条事件（1 增量 + 1 整包独有）
    assert len(body["data"]["events"]) == 2, \
        "合并后应 2 条事件, 实际 %d" % len(body["data"]["events"])


def test_get_devices_summary():
    """GET /api/v1/devices 设备汇总 (doc/dev01 §8)"""
    app, _ = _make_app()
    _request(app, "POST", "/api/v1/reports", json_body=FULL_PAYLOAD)
    _request(app, "POST", "/api/v1/events", json_body=DELTA_PAYLOAD)
    _request(app, "POST", "/api/v1/subscriptions",
             json_body={"device_id": "dev01"})
    status, body = _request(app, "GET", "/api/v1/devices")
    assert status == 200 and body["code"] == 0
    devices = body["data"]["devices"]
    assert "dev01" in devices and "dev02" in devices, \
        "设备集合应含 dev01/dev02, 实际 %s" % list(devices)
    d1 = devices["dev01"]
    assert d1["report_count"] >= 1
    assert d1["subscription"]["active"] is True
    assert d1["latest_progress"] is None, "dev01 无增量进度应为 None"
    assert devices["dev02"]["event_count"] >= 2, \
        "dev02 增量事件应入库, 实际 %d" % devices["dev02"]["event_count"]
    assert devices["dev02"]["latest_progress"]["done"] == 2


def test_get_reports_limit_param():
    """GET /api/v1/reports 兼容 dev01 §8 limit 参数"""
    app, _ = _make_app()
    # 制造 3 条报告
    for i in range(3):
        payload = clone(FULL_PAYLOAD)
        payload["round"]["start_ms"] += i + 1
        _request(app, "POST", "/api/v1/reports", json_body=payload)
    status, body = _request(app, "GET", "/api/v1/reports?limit=2")
    assert status == 200 and body["code"] == 0
    assert len(body["data"]["list"]) == 2, \
        "limit=2 应只返回 2 条, 实际 %d" % len(body["data"]["list"])
    assert body["data"]["total"] == 3


def test_debug_training_summary():
    """GET /api/v1/debug/training_summary 联调汇总"""
    app, _ = _make_app()
    _request(app, "POST", "/api/v1/reports", json_body=FULL_PAYLOAD)
    status, body = _request(app, "GET", "/api/v1/debug/training_summary")
    assert status == 200 and body["code"] == 0
    data = body["data"]
    assert data["reports"] >= 1
    assert data["events"] >= 2, "整包 events 应入库"
    assert len(data["recent_reports"]) >= 1
