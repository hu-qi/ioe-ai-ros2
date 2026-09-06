#!/usr/bin/env python3
"""报告接收插件 126 端到端验证脚本"""
import os, sys, json, sqlite3

sys.path.insert(0, os.path.join("app_mgr_object", "components", "web"))
from report_repo import ReportRepo

print("[OK] 1. 导入 ReportRepo 成功")

# 临时测试库
db = "/tmp/verify_report_recv_126.db"
if os.path.exists(db):
    os.remove(db)

class L:
    def info(self, m): pass
    def debug(self, m): pass
    def warning(self, m): pass
    def error(self, m): pass

repo = ReportRepo(db, L())
repo.init_schema()

# 验证六表
conn = sqlite3.connect(db)
tables = sorted([r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
)])
expected = sorted(["report_events", "report_progress", "report_steps",
                   "report_substeps", "reports", "subscriptions"])
assert tables == expected, "六表不符: %s" % tables
print("[OK] 2. 六表建表成功")
conn.close()

# 整包入库 (doc/38 §6)
full = {
    "schema_version": "1.0", "device_id": "dev01",
    "edge_node": "touch_ui_plugin", "ts_upload_ms": 1787569200000,
    "student": {"id": "S2024001", "name": "张明", "cls": "机修一班", "source": "manual"},
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
        "unexecuted": [13, 14], "substep_counts": [1, 2, 2, 1, 2, 4, 2, 2]
    }
}
rid, dup = repo.insert_full_report(full)
assert rid == "Rdev01_1787569113000", "report_id 错: %s" % rid
assert not dup
print("[OK] 3. 整包入库成功 report_id=%s" % rid)

# 整包去重
_, dup4 = repo.insert_full_report(full)
assert dup4
print("[OK] 4. 整包去重命中")

# 增量入库 (doc/45 §2)
delta = {
    "schema_version": "1.1", "type": "event_delta",
    "device_id": "dev02", "edge_node": "touch_ui_plugin",
    "ts_upload_ms": 1788407910000,
    "round_start_ms": 1788407000000, "process_elapsed_ms": 910000,
    "student": {"id": "S2024002", "name": "李华", "cls": "二班", "source": "manual"},
    "events": [
        {"ts": 12000, "kind": 0, "step": 1, "sub": 2},
        {"ts": 18500, "kind": 1, "step": 1, "sub": 2}
    ],
    "progress": {"done": 2, "total": 19, "current": "装扣机", "current_sub_index": 5}
}
ins5 = repo.insert_delta_events(delta)
assert ins5 == 2, "增量应插 2, 实际 %d" % ins5
print("[OK] 5. 增量入库成功 inserted=2")

# 增量去重
ins6 = repo.insert_delta_events(delta)
assert ins6 == 0
print("[OK] 6. 增量去重命中 inserted=0")

# 多设备同时订阅 (doc/45 §4)
ra = repo.upsert_subscription("dev01", "1号机")
rb = repo.upsert_subscription("dev02", "2号机")
assert ra["active"] and rb["active"]
print("[OK] 7. 多设备同时订阅成功 dev01+dev02 active=true")

# 查询订阅状态
s8 = repo.get_subscription("dev01")
assert s8 and s8["active"] == 1
print("[OK] 8. 查询订阅状态 active=1")

# 退订
d9 = repo.deactivate_subscription("dev01")
assert not d9["active"]
print("[OK] 9. 退订成功 active=0")

# 报告检索
lst10 = repo.list_reports({"device_id": "dev01"}, 1, 10)
assert lst10["total"] >= 1
print("[OK] 10. 报告检索成功 total=%d" % lst10["total"])

# 报告详情
det11 = repo.get_report_detail(rid)
assert det11 and det11["report"]["report_id"] == rid
assert len(det11["events"]) >= 2
assert len(det11["steps"]) >= 1
assert len(det11["substeps"]) >= 1
print("[OK] 11. 报告详情成功 events=%d steps=%d substeps=%d" % (
    len(det11["events"]), len(det11["steps"]), len(det11["substeps"])
))

# 未绑定学员
unbound = json.loads(json.dumps(full))
unbound["student"] = {}
unbound["device_id"] = "dev03"
unbound["round"]["start_ms"] = 1787569999000
rid12, _ = repo.insert_full_report(unbound)
det12 = repo.get_report_detail(rid12)
assert det12["report"]["student_id"] is None
assert det12["report"]["student_bound"] == 0
print("[OK] 12. 未绑定学员入库成功 student_bound=0")

# 增量先于整包到达 (存根报告)
delta_stub = {
    "schema_version": "1.1", "type": "event_delta",
    "device_id": "dev04", "edge_node": "touch_ui_plugin",
    "ts_upload_ms": 1788408000000,
    "round_start_ms": 1788407500000, "process_elapsed_ms": 500000,
    "student": {},
    "events": [{"ts": 1000, "kind": 0, "step": 1, "sub": 1}],
    "progress": {"done": 1, "total": 19, "current": "装缓冲", "current_sub_index": 1}
}
ins13 = repo.insert_delta_events(delta_stub)
assert ins13 == 1
conn = sqlite3.connect(db)
stub = conn.execute(
    "SELECT is_stub, process_elapsed_ms FROM reports WHERE report_id=?",
    ("Rdev04_1788407500000",)
).fetchone()
assert stub and stub[0] == 1, "is_stub 应为 1"
assert stub[1] == 500000
conn.close()
print("[OK] 13. 增量先于整包到达：存根报告创建成功 is_stub=1 process_elapsed_ms=500000")

# report_progress 实时进度快照
conn = sqlite3.connect(db)
prog = conn.execute(
    "SELECT done, total, current, current_sub_index, process_elapsed_ms, last_delta_ts "
    "FROM report_progress WHERE device_id=?", ("dev02",)
).fetchone()
assert prog and prog[0] == 2 and prog[1] == 19
assert prog[2] == "装扣机" and prog[3] == 5
assert prog[4] == 910000
conn.close()
print("[OK] 14. report_progress 快照正确 done=2 total=19 current=装扣机 current_sub_index=5")

# raw_json 落盘
raw_path = repo.save_raw_json("dev01", rid, full, "/tmp/raw_json_126")
assert os.path.exists(raw_path)
with open(raw_path, "r", encoding="utf-8") as f:
    raw_data = json.load(f)
assert raw_data["device_id"] == "dev01"
print("[OK] 15. raw_json 落盘成功: %s" % raw_path)

# evidence 抓拍图存储
ev_path = repo.save_evidence(
    "dev01", 1787569113000, 1, 3200,
    b"\xff\xd8\xff\xe0fake_jpg_data", "/tmp/evidence_126"
)
assert os.path.exists(ev_path)
with open(ev_path, "rb") as f:
    ev_data = f.read()
assert ev_data.startswith(b"\xff\xd8")
print("[OK] 16. evidence 存储成功: %s" % ev_path)

# 统一计时字段入库 (doc/58)
conn = sqlite3.connect(db)
tim = conn.execute(
    "SELECT process_elapsed_ms FROM reports WHERE report_id=?", (rid,)
).fetchone()
assert tim and tim[0] == 87000
stp = conn.execute(
    "SELECT start_ms, end_ms, interval_ms FROM report_steps "
    "WHERE report_id=? AND idx=1", (rid,)
).fetchone()
assert stp and stp[0] == 3200 and stp[1] == 11400 and stp[2] == 0
sub = conn.execute(
    "SELECT start_ms, end_ms FROM report_substeps "
    "WHERE report_id=? AND idx=1", (rid,)
).fetchone()
assert sub and sub[0] == 3200 and sub[1] == 11400
conn.close()
print("[OK] 17. 统一计时字段入库正确 process_elapsed_ms=87000 "
      "steps.start_ms=3200 substeps.end_ms=11400")

print()
print("=" * 50)
print("  17 项测试全部通过")
print("=" * 50)
