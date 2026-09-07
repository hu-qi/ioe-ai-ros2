#!/usr/bin/env python3
"""
simulate_edge_device.py — 模拟多个边缘侧设备进行联调（v3: 多 IP 全推）

完整闭环（方案 A：订阅时填多个边缘端 IP，平台全推）：
  ① 每个 edge_ip 对应一个边缘端，各自启动 HTTP 监听（端口 9184+）
  ② 平台订阅设备，请求体带 edge_ips 列表 + edge_port
  ③ 平台遍历 edge_ips 逐个 POST http://{ip}:{port}/api/notify_subscribe（全推）
  ④ 每个边缘端收到推送，从 payload 拿到 platform_ip + platform_port
  ⑤ 每个边缘端用拿到的平台地址上报增量 + 整包
  ⑥ 验证入库结果 + 平台侧 notify_status（sent/partial/failed）

用法:
  python3 scripts/simulate_edge_device.py                    # 默认 127.0.0.1:9183, dev_sim03, 2 个边缘端
  python3 scripts/simulate_edge_device.py --edges 127.0.0.1,127.0.0.1 --ports 9184,9185
  python3 scripts/simulate_edge_device.py --platform 192.168.31.249 --device dev02
"""

import argparse
import json
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler


# ====================================================================
# HTTP 工具
# ====================================================================

def http_call(method: str, url: str, body: dict = None, timeout: float = 10.0):
    """简单 HTTP 调用，返回 (status_code, json_or_text)"""
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:
        return -1, str(e)


# ====================================================================
# 边缘端（多实例，每个一个监听端口）
# ====================================================================

class EdgeState:
    """单个边缘端的状态。"""
    def __init__(self, ip: str, port: int, index: int):
        self.ip = ip
        self.port = port
        self.index = index  # 第几个边缘端（用于日志区分）
        self.platform_ip = None
        self.platform_port = None
        self.device_id = None
        self.received = False
        self.received_at = None


def make_notify_handler(state: EdgeState):
    """构造一个 HTTP handler，处理平台的 /api/notify_subscribe 推送。"""
    class NotifyHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/api/notify_subscribe":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode()
            try:
                payload = json.loads(raw)
            except Exception:
                self.send_response(400)
                self.end_headers()
                return

            state.platform_ip = payload.get("platform_ip")
            state.platform_port = payload.get("platform_port", 9183)
            state.device_id = payload.get("device_id")
            state.received = True
            state.received_at = time.time()

            print(f"\n    📨 [边缘端 #{state.index} @ {state.ip}:{state.port}] 收到平台推送!")
            print(f"       platform_ip   = {state.platform_ip}")
            print(f"       platform_port = {state.platform_port}")
            print(f"       device_id     = {state.device_id}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"code": 0, "message": "ok"}).encode())

        def log_message(self, *args):
            pass

    return NotifyHandler


def start_edge_listener(state: EdgeState) -> threading.Thread:
    """启动单个边缘端 HTTP 监听线程。"""
    server = HTTPServer(("0.0.0.0", state.port), make_notify_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.server = server
    print(f"[边缘端 #{state.index}] HTTP 监听已启动: 0.0.0.0:{state.port} (对外: {state.ip}:{state.port})")
    return thread


def wait_all_notify(states: list, timeout: float = 10.0) -> int:
    """等待所有边缘端都收到推送，返回成功收到的数量。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(s.received for s in states):
            break
        time.sleep(0.1)
    return sum(1 for s in states if s.received)


# ====================================================================
# 联调步骤
# ====================================================================

def step1_subscribe_with_multi_ip(platform_base: str, device_id: str, edge_ips: list, edge_port: int):
    """① 教官在平台订阅设备，请求体带 edge_ips 列表。"""
    print("\n[①] 教官在平台订阅设备（填多个边缘端 IP）...")
    body = {
        "device_id": device_id,
        "note": "多IP联调",
        "edge_ips": edge_ips,
        "edge_port": edge_port,
    }
    code, resp = http_call("POST", f"{platform_base}/api/v1/subscriptions", body=body)
    print(f"    POST /api/v1/subscriptions  HTTP {code}")
    print(f"    Response: {json.dumps(resp, ensure_ascii=False, indent=2)}")
    return code == 200


def step2_wait_all_push(states: list) -> int:
    """② 等待所有边缘端都收到平台推送。"""
    print("\n[②] 等待所有边缘端收到平台推送 ...")
    received = wait_all_notify(states, timeout=10.0)
    print(f"    收到推送的边缘端数: {received}/{len(states)}")
    return received


def step3_all_edges_report(states: list, device_id: str, round_start_ms: int) -> bool:
    """③ 每个边缘端用拿到的平台地址上报增量 + 整包。"""
    print("\n[③] 每个边缘端用拿到的平台地址上报 ...")
    all_ok = True
    for state in states:
        if not state.received:
            print(f"    [边缘端 #{state.index}] 未收到推送，跳过")
            all_ok = False
            continue

        platform_base = f"http://{state.platform_ip}:{state.platform_port}"
        print(f"    [边缘端 #{state.index}] 平台地址: {platform_base}")

        # 3a. 轮询订阅状态
        code, resp = http_call("GET", f"{platform_base}/api/v1/subscriptions/{device_id}")
        active = (resp or {}).get("data", {}).get("active") if isinstance(resp, dict) else None
        print(f"       3a. GET /subscriptions/{device_id}  HTTP {code}  active={active}")
        if active is not True:
            all_ok = False
            continue

        # 3b. 上报增量事件
        body = {
            "schema_version": "1.1",
            "type": "event_delta",
            "device_id": device_id,
            "edge_node": f"sim_edge_{state.index}",
            "ts_upload_ms": int(time.time() * 1000),
            "round_start_ms": round_start_ms,
            "process_elapsed_ms": 12000,
            "student": {"id": "SIM001", "name": "模拟学员", "cls": "测试班", "source": "manual"},
            "events": [
                {"ts": 1000, "kind": 0, "step": 1, "sub": state.index},
                {"ts": 8000, "kind": 1, "step": 1, "sub": state.index},
            ],
            "progress": {"done": 1, "total": 5, "current": "装缓冲", "current_sub_index": 1},
        }
        code, resp = http_call("POST", f"{platform_base}/api/v1/events", body=body)
        print(f"       3b. POST /api/v1/events  HTTP {code}  delta_events={resp.get('data', {}).get('delta_events') if isinstance(resp, dict) else '?'}")
        if code != 200:
            all_ok = False
            continue

        # 3c. 上报整包报告
        end_ms = round_start_ms + 87000
        body = {
            "schema_version": "1.0",
            "device_id": device_id,
            "edge_node": f"sim_edge_{state.index}",
            "ts_upload_ms": int(time.time() * 1000),
            "student": {"id": "SIM001", "name": "模拟学员", "cls": "测试班", "source": "manual"},
            "round": {
                "process_name": "组装自动机监测",
                "process_type": "assembly",
                "finish_reason": "completed",
                "start_ms": round_start_ms,
                "end_ms": end_ms,
                "duration_ms": 87000,
                "process_elapsed_ms": 87000,
                "events": [
                    {"ts": 3200, "kind": 0, "step": 1, "sub": 1},
                    {"ts": 11400, "kind": 1, "step": 1, "sub": 1},
                ],
                "steps": [
                    {"idx": 1, "name": "装缓冲", "state": 2, "duration_ms": 8200,
                     "start_ms": 3200, "end_ms": 11400, "interval_ms": 0}
                ],
                "substeps": [
                    {"idx": 1, "name": "装缓冲", "state": 2, "duration_ms": 8200,
                     "count": 1, "total_duration_ms": 8200, "timeout": False,
                     "start_ms": 3200, "end_ms": 11400}
                ],
                "unexecuted": [],
                "substep_counts": [1],
            },
        }
        code, resp = http_call("POST", f"{platform_base}/api/v1/reports", body=body)
        print(f"       3c. POST /api/v1/reports  HTTP {code}  report_id={resp.get('data', {}).get('report_id') if isinstance(resp, dict) else '?'}")
        if code != 200:
            all_ok = False
    return all_ok


def step4_verify(states: list, device_id: str, round_start_ms: int) -> bool:
    """④ 验证入库结果。"""
    print("\n[④] 验证入库结果 ...")
    if not states or not states[0].platform_ip:
        return False
    platform_base = f"http://{states[0].platform_ip}:{states[0].platform_port}"
    report_id = f"R{device_id}_{round_start_ms}"

    code, resp = http_call("GET", f"{platform_base}/api/v1/reports?device_id={device_id}&page=1&page_size=10")
    print(f"    GET /api/v1/reports  HTTP {code}")
    total = (resp or {}).get("data", {}).get("total") if isinstance(resp, dict) else None
    print(f"    total = {total}")

    code, resp = http_call("GET", f"{platform_base}/api/v1/reports/{report_id}")
    print(f"    GET /api/v1/reports/{report_id}  HTTP {code}")
    if code == 200 and isinstance(resp, dict):
        events = resp.get("data", {}).get("events", [])
        print(f"    events count = {len(events)}")
        return True
    return False


def step5_check_notify_detail(platform_base: str, device_id: str) -> bool:
    """⑤ 查询平台侧的 notify_status + notify_detail（验证多 IP 推送明细）。"""
    print("\n[⑤] 查询订阅详情，确认 notify_status + notify_detail ...")
    code, resp = http_call("GET", f"{platform_base}/api/v1/subscriptions")
    print(f"    GET /api/v1/subscriptions  HTTP {code}")
    if isinstance(resp, dict):
        devices = resp.get("data", {}).get("devices", {})
        sub = devices.get(device_id, {})
        print(f"    subscriptions[{device_id}] = {json.dumps(sub, ensure_ascii=False, indent=2)}")
        # 只要状态是 sent/partial/failed 之一就算通过
        return sub.get("notify_status") in ("sent", "partial", "failed")
    return False


# ====================================================================
# 主流程
# ====================================================================

def main():
    parser = argparse.ArgumentParser(description="模拟多个边缘端联调（方案A: 平台全推多 IP）")
    parser.add_argument("--platform-host", default="127.0.0.1", help="平台 IP（默认 127.0.0.1）")
    parser.add_argument("--platform-port", type=int, default=9183, help="平台端口（默认 9183）")
    parser.add_argument("--device", default="dev_sim03", help="模拟设备 ID")
    parser.add_argument(
        "--edges",
        default="127.0.0.1,127.0.0.1",
        help="边缘端 IP 列表（逗号分隔，每个 IP 对应一个边缘端实例）",
    )
    parser.add_argument(
        "--ports",
        default="9184,9185",
        help="边缘端 HTTP 监听端口列表（逗号分隔，对应 --edges 顺序）",
    )
    args = parser.parse_args()

    platform_base = f"http://{args.platform_host}:{args.platform_port}"
    edge_ips = [s.strip() for s in args.edges.split(",") if s.strip()]
    edge_ports = [int(s.strip()) for s in args.ports.split(",") if s.strip()]
    if len(edge_ports) < len(edge_ips):
        # 端口不够时自动从 9184 递增补齐
        start = edge_ports[-1] + 1 if edge_ports else 9184
        edge_ports.extend(range(start, start + len(edge_ips) - len(edge_ports)))

    print("=" * 60)
    print("模拟多边缘端联调（方案A: 订阅填多 IP → 平台全推 → 各边缘端拿平台地址）")
    print("=" * 60)
    print(f"平台地址:       {platform_base}")
    print(f"模拟设备:       {args.device}")
    print(f"边缘端数量:     {len(edge_ips)}")
    for i, (ip, port) in enumerate(zip(edge_ips, edge_ports)):
        print(f"  边缘端 #{i}: {ip}:{port}")

    # ── 启动所有边缘端 HTTP 监听 ──
    states = []
    threads = []
    for i, (ip, port) in enumerate(zip(edge_ips, edge_ports)):
        state = EdgeState(ip=ip, port=port, index=i)
        thread = start_edge_listener(state)
        states.append(state)
        threads.append(thread)

    round_start_ms = int(time.time() * 1000)

    results = []
    results.append(("① 教官订阅填多 IP", step1_subscribe_with_multi_ip(
        platform_base, args.device, edge_ips, edge_ports[0])))
    received = step2_wait_all_push(states)
    results.append(("② 所有边缘端收到推送", received == len(states)))
    results.append(("③ 各边缘端用平台地址上报", step3_all_edges_report(
        states, args.device, round_start_ms)))
    results.append(("④ 验证入库结果", step4_verify(
        states, args.device, round_start_ms)))
    results.append(("⑤ 平台侧 notify 明细", step5_check_notify_detail(
        platform_base, args.device)))

    print("\n" + "=" * 60)
    print("结果汇总")
    print("=" * 60)
    all_ok = True
    for name, ok in results:
        mark = "✅" if ok else "❌"
        if not ok:
            all_ok = False
        print(f"  {mark} {name}")

    print(f"\n{'🎉 多IP联调成功' if all_ok else '⚠️  部分失败，看上面日志'}")
    print(f"\nreport_id = R{args.device}_{round_start_ms}")
    print(f"关键链路: 教官订阅填 edge_ips={edge_ips} → 平台遍历全推 → 各边缘端拿 platform_ip → 各自上报")

    # 清理监听线程
    for state in states:
        if hasattr(state, "server"):
            state.server.shutdown()


if __name__ == "__main__":
    main()
