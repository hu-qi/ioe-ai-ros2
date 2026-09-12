#!/usr/bin/env python3
"""
simulate_session.py — 统一边缘侧模拟器（整合版）

整合 scripts/simulate_edge_device.py 的"订阅→平台全推→上报"链路，
增加训练场景编排：多学员、多轮次、异常场景（超时/中断重入/未执行步骤），
一键给 /reports、/dashboard 造端到端演示数据。

单轮闭环（复用已验证的方案 A 链路）:
  ① 教官在平台订阅设备（edge_ips 指向本模拟器监听端口）
  ② 模拟器收到平台推送，拿到 platform_ip/port
  ③ 按场景生成事件流: 增量上报 POST /api/v1/events
  ④ 整包上报 POST /api/v1/reports
  ⑤ 验证入库 GET /api/v1/reports/{report_id}

场景:
  completed   正常完成: 全步骤完成, finish_reason=completed
  timeout     超时: 部分子步骤超时, 有未执行步骤, finish_reason=timeout
  interrupted 中断重入: 子步骤重复操作(count>1), finish_reason=manual
  mixed       混合: 各轮次轮流使用以上三种场景

用法:
  python3 scripts/simulate_session.py                          # 默认 2 学员 × 2 轮 mixed
  python3 scripts/simulate_session.py --scenario timeout       # 全部超时场景
  python3 scripts/simulate_session.py --students SIM001,SIM002,SIM003 --rounds 3
  python3 scripts/simulate_session.py --platform-host 192.168.31.126 --device dev_sim01
"""

import argparse
import json
import random
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# 8 标准步骤名（模拟数据，与真实工艺无关）
PROCESS_STEPS = ["装缓冲", "装垫片", "装配电箱", "接线", "装外壳", "紧固", "自检", "清理现场"]

DEFAULT_STUDENTS = [
    {"id": "SIM001", "name": "张三", "cls": "电气一班"},
    {"id": "SIM002", "name": "李四", "cls": "电气一班"},
]

# ====================================================================
# HTTP 工具
# ====================================================================

def http_call(method: str, url: str, body: dict = None, timeout: float = 10.0):
    """HTTP 调用，返回 (status_code, json_or_text)"""
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
# 订阅推送接收（复用 simulate_edge_device 的监听模式，单实例）
# ====================================================================

class PushState:
    def __init__(self, edge_ip: str, port: int):
        self.edge_ip = edge_ip
        self.port = port
        self.platform_ip = None
        self.platform_port = None
        self.device_id = None
        self.received = False


def make_notify_handler(state: PushState):
    class NotifyHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/api/notify_subscribe":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode())
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            state.platform_ip = payload.get("platform_ip")
            state.platform_port = payload.get("platform_port", 9183)
            state.device_id = payload.get("device_id")
            state.received = True
            print(f"  📨 收到平台推送: platform={state.platform_ip}:{state.platform_port} device={state.device_id}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"code": 0, "message": "ok"}).encode())

        def log_message(self, *args):
            pass

    return NotifyHandler


def start_listener(state: PushState):
    server = HTTPServer(("0.0.0.0", state.port), make_notify_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  模拟边缘端监听: {state.edge_ip}:{state.port}")
    return server


# ====================================================================
# 场景数据生成
# ====================================================================

def gen_events(steps: list) -> list:
    """由子步骤序列生成事件流: kind=0 开始 / kind=1 完成（未执行步骤无事件）."""
    events = []
    for s in steps:
        if s["start_ms"] is None:
            continue
        events.append({"ts": s["start_ms"], "kind": 0, "step": s["idx"], "sub": s["idx"]})
        if s["state"] == 2:  # 已完成才有结束事件
            events.append({"ts": s["end_ms"], "kind": 1, "step": s["idx"], "sub": s["idx"]})
    return events


def build_round(scenario: str, round_start_ms: int, rng: random.Random) -> dict:
    """按场景生成一轮训练的整包 round 数据（doc/38 schema 1.0）。"""
    n_steps = len(PROCESS_STEPS)
    steps, substeps, unexecuted = [], [], []
    ts = round_start_ms

    if scenario == "completed":
        n_done = n_steps
        finish_reason = "completed"
    elif scenario == "timeout":
        n_done = rng.randint(3, 5)
        finish_reason = "timeout"
    else:  # interrupted
        n_done = rng.randint(5, 7)
        finish_reason = "manual"

    for idx in range(1, n_steps + 1):
        name = PROCESS_STEPS[idx - 1]
        if idx > n_done:
            unexecuted.append({"idx": idx, "name": name, "reason": "未执行"})
            steps.append({"idx": idx, "name": name, "state": 0, "duration_ms": 0,
                          "start_ms": None, "end_ms": None, "interval_ms": 0})
            continue

        duration = rng.randint(5000, 20000)
        end = ts + duration
        timeout_flag = 1 if (scenario == "timeout" and idx == n_done) else 0
        state = 2
        steps.append({"idx": idx, "name": name, "state": state, "duration_ms": duration,
                      "start_ms": ts, "end_ms": end, "interval_ms": 0})

        # 中断场景: 部分子步骤重复操作（count>1 = 中断重入）
        if scenario == "interrupted" and idx in (2, 4):
            count = 2
            total_duration = int(duration * 1.6)
            end = ts + total_duration
            steps[-1]["duration_ms"] = total_duration
            steps[-1]["end_ms"] = end
        else:
            count = 1
            total_duration = duration

        substeps.append({"idx": idx, "name": name, "state": 2, "duration_ms": duration,
                         "count": count, "total_duration_ms": total_duration,
                         "timeout": bool(timeout_flag),
                         "start_ms": ts, "end_ms": end})
        ts = end + rng.randint(300, 1500)

    end_ms = ts
    duration_ms = end_ms - round_start_ms
    return {
        "process_name": "组装自动机监测",
        "process_type": "assembly",
        "finish_reason": finish_reason,
        "start_ms": round_start_ms,
        "end_ms": end_ms,
        "duration_ms": duration_ms,
        "process_elapsed_ms": duration_ms,
        "events": gen_events(steps),
        "steps": steps,
        "substeps": substeps,
        "unexecuted": unexecuted,
        "substep_counts": [s["count"] for s in substeps],
    }


def build_delta(round_data: dict, round_start_ms: int, device_id: str, student: dict, now_ms: int) -> dict:
    """由整包数据导出一份增量事件上报（doc/38 schema 1.1）。"""
    done = sum(1 for s in round_data["substeps"] if s["state"] == 2)
    total = len(PROCESS_STEPS)
    current = round_data["substeps"][-1]["name"] if round_data["substeps"] else ""
    return {
        "schema_version": "1.1",
        "type": "event_delta",
        "device_id": device_id,
        "edge_node": "sim_session",
        "ts_upload_ms": now_ms,
        "round_start_ms": round_start_ms,
        "process_elapsed_ms": round_data["duration_ms"],
        "student": student,
        "events": round_data["events"],
        "progress": {"done": done, "total": total, "current": current,
                     "current_sub_index": done},
    }


# ====================================================================
# 主流程
# ====================================================================

def main():
    parser = argparse.ArgumentParser(description="统一边缘侧模拟器: 训练轮次场景编排 + 报告上报")
    parser.add_argument("--platform-host", default="127.0.0.1", help="平台 IP（默认 127.0.0.1）")
    parser.add_argument("--platform-port", type=int, default=9183, help="平台端口（默认 9183）")
    parser.add_argument("--device", default="dev_sim01", help="模拟设备 ID")
    parser.add_argument("--students", default="SIM001:张三:电气一班,SIM002:李四:电气一班",
                        help="学员列表, 格式 id:name:cls, 逗号分隔")
    parser.add_argument("--rounds", type=int, default=2, help="每个学员的轮次数")
    parser.add_argument("--scenario", default="mixed",
                        choices=["completed", "timeout", "interrupted", "mixed"],
                        help="训练场景")
    parser.add_argument("--edge-port", type=int, default=9184, help="模拟边缘端监听端口")
    parser.add_argument("--no-subscribe", action="store_true", help="跳过订阅推送, 直接用 --platform 参数上报")
    args = parser.parse_args()

    platform_base = f"http://{args.platform_host}:{args.platform_port}"
    students = []
    for item in args.students.split(","):
        parts = item.strip().split(":")
        students.append({"id": parts[0],
                         "name": parts[1] if len(parts) > 1 else parts[0],
                         "cls": parts[2] if len(parts) > 2 else "模拟班",
                         "source": "manual"})
    rng = random.Random()

    print("=" * 60)
    print("统一边缘侧模拟器 — 训练轮次场景编排")
    print("=" * 60)
    print(f"平台: {platform_base}  设备: {args.device}")
    print(f"学员: {[s['name'] for s in students]}  每人轮次: {args.rounds}  场景: {args.scenario}")

    state = PushState("127.0.0.1", args.edge_port)

    # ① 订阅 + 等推送（拿平台真实可达地址）
    if not args.no_subscribe:
        server = start_listener(state)
        body = {"device_id": args.device, "note": "统一模拟器",
                "edge_ips": [state.edge_ip], "edge_port": state.port}
        code, _ = http_call("POST", f"{platform_base}/api/v1/subscriptions", body=body)
        print(f"  ① 订阅设备: HTTP {code}")
        deadline = time.time() + 5
        while time.time() < deadline and not state.received:
            time.sleep(0.1)
        if not state.received:
            print("  ⚠️ 未收到推送，回退使用 --platform 参数上报")
        server.shutdown()
    if state.platform_ip:
        platform_base = f"http://{state.platform_ip}:{state.platform_port}"
    print(f"  上报地址: {platform_base}")

    # ② 逐学员逐轮次上报
    now_ms = int(time.time() * 1000)
    ok, fail = 0, 0
    scenario_cycle = ["completed", "timeout", "interrupted"]
    for si, student in enumerate(students):
        for r in range(1, args.rounds + 1):
            scenario = scenario_cycle[(si + r) % 3] if args.scenario == "mixed" else args.scenario
            round_start_ms = now_ms - (si * args.rounds + r) * 600_000  # 轮次时间错开
            round_data = build_round(scenario, round_start_ms, rng)
            report_id = f"R{args.device}_{round_start_ms}"

            # 增量
            delta = build_delta(round_data, round_start_ms, args.device, student, now_ms)
            dcode, _ = http_call("POST", f"{platform_base}/api/v1/events", body=delta)
            delta_ok = dcode == 200
            # 整包
            full = {"schema_version": "1.0", "device_id": args.device,
                    "edge_node": "sim_session", "ts_upload_ms": now_ms,
                    "student": student, "round": round_data}
            code, resp = http_call("POST", f"{platform_base}/api/v1/reports", body=full)
            full_ok = code == 200
            if delta_ok and full_ok:
                ok += 1
                mark = "✅"
            else:
                fail += 1
                mark = "❌"
            print(f"  {mark} [{student['name']}] 第{r}轮 {scenario}: "
                  f"delta={'OK' if delta_ok else code} full={'OK' if full_ok else code} "
                  f"report_id={report_id} 步骤{len(round_data['substeps'])}/{len(PROCESS_STEPS)} "
                  f"未执行{len(round_data['unexecuted'])}")
            time.sleep(0.2)

    # ③ 验证入库
    print("\n验证入库 ...")
    code, resp = http_call("GET", f"{platform_base}/api/v1/reports?device_id={args.device}&page=1&page_size=5")
    total = resp.get("data", {}).get("total") if isinstance(resp, dict) else None
    print(f"  GET /api/v1/reports  HTTP {code}  设备报告总数: {total}")

    print("\n" + "=" * 60)
    print(f"完成: 成功 {ok} 轮, 失败 {fail} 轮")
    print(f"查看: {platform_base}/reports  |  看板: {platform_base}/dashboard")
    print("=" * 60)


if __name__ == "__main__":
    main()
