"""
报告接收插件端到端验证夹具

按 doc/70 §8.3 / §8.4 全部验收项 (V-01..V-18) 验证四层：
  1. 仓储层 ReportRepo    — test_report_repo.py
  2. 合并器 EventMerge     — test_event_merge.py
  3. 插件层 ReportRecvPlugin — test_plugin_lifecycle.py
  4. HTTP 端到端 (FastAPI TestClient) — test_http_endpoints.py

本目录可独立运行，不依赖 ROS2 节点（插件层用 stub node）。
"""

import os
import sys
import json
import shutil

# ── 路径设置 ──────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app_mgr_object.components.web.report_repo import ReportRepo

# ── 测试夹具常量 ──────────────────────────────────────────────────────────
WORK = "/tmp/verify_report_recv_126"
DB = os.path.join(WORK, "test.db")
RAW_DIR = os.path.join(WORK, "raw_json")
EVID_DIR = os.path.join(WORK, "evidence")

FULL_PAYLOAD = {
    "schema_version": "1.0", "device_id": "dev01",
    "edge_node": "touch_ui_plugin", "ts_upload_ms": 1787569200000,
    "student": {"id": "S2024001", "name": "张明", "cls": "机修一班",
                "source": "manual"},
    "round": {
        "process_name": "组装自动机监测", "process_type": "assembly",
        "finish_reason": "completed",
        "start_ms": 1787569113000, "end_ms": 1787569200000,
        "duration_ms": 87000, "process_elapsed_ms": 87000,
        "events": [
            {"ts": 3200, "kind": 0, "step": 1, "sub": 1},
            {"ts": 11400, "kind": 1, "step": 1, "sub": 1}
        ],
        "steps": [{"idx": 1, "name": "装缓冲", "state": 2, "duration_ms": 8200,
                   "start_ms": 3200, "end_ms": 11400, "interval_ms": 0}],
        "substeps": [{"idx": 1, "name": "装缓冲", "state": 2, "duration_ms": 8200,
                      "count": 1, "total_duration_ms": 8200, "timeout": False,
                      "start_ms": 3200, "end_ms": 11400}],
        "unexecuted": [13, 14],
        "substep_counts": [1, 2, 2, 1, 2, 4, 2, 2]
    }
}

DELTA_PAYLOAD = {
    "schema_version": "1.1", "type": "event_delta",
    "device_id": "dev02", "edge_node": "touch_ui_plugin",
    "ts_upload_ms": 1788407910000,
    "round_start_ms": 1788407000000, "process_elapsed_ms": 910000,
    "student": {"id": "S2024002", "name": "李华", "cls": "二班",
                "source": "manual"},
    "events": [
        {"ts": 12000, "kind": 0, "step": 1, "sub": 2},
        {"ts": 18500, "kind": 1, "step": 1, "sub": 2}
    ],
    "progress": {"done": 2, "total": 19, "current": "装扣机",
                 "current_sub_index": 5}
}


class StubLogger:
    """轻量日志器"""
    def info(self, m): pass
    def debug(self, m): pass
    def warning(self, m): pass
    def error(self, m): pass


def fresh_env():
    """重置测试环境"""
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK, exist_ok=True)


def make_repo():
    """创建全新 ReportRepo（自动初始化 schema）"""
    fresh_env()
    repo = ReportRepo(DB, StubLogger())
    repo.init_schema()
    return repo


def clone(payload):
    """深拷贝 payload"""
    return json.loads(json.dumps(payload))
