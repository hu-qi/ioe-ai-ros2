"""
仓储层 ReportRepo 端到端验证

覆盖 doc/70 §8.3 验收项 V-01..V-12，验证：
  - 六表建表（reports/steps/substeps/events/progress/subscriptions）
  - 整包入库 + 去重幂等（doc/38 §7.6）
  - 增量入库 + 去重幂等（doc/45 §1）
  - 多设备同时订阅管理（doc/45 §4）
  - 退订后重新订阅（关键：必须重新激活 active=1）
  - 未绑定学员归档（student={} → student_bound=0）
  - 增量先于整包到达（存根报告 is_stub=1）
  - report_progress 实时进度快照
  - raw_json 落盘 / evidence 抓拍图存储
  - 统一计时字段入库（doc/58 v1.1）
"""

import os
import json
import sqlite3

from conftest import (
    DB, RAW_DIR, EVID_DIR, FULL_PAYLOAD, DELTA_PAYLOAD,
    fresh_env, make_repo, clone, StubLogger,
)
from app_mgr_object.components.web.report_repo import ReportRepo


def test_six_tables_created():
    """V-01 六表建表成功"""
    repo = make_repo()
    conn = sqlite3.connect(DB)
    tables = sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    conn.close()
    expected = sorted(["report_events", "report_progress", "report_steps",
                       "report_substeps", "reports", "subscriptions"])
    assert tables == expected, "六表不符: %s" % tables


def test_full_report_insert_and_dedup():
    """V-01/V-02 整包入库 + 去重幂等"""
    repo = make_repo()
    rid, dup = repo.insert_full_report(FULL_PAYLOAD)
    assert rid == "Rdev01_1787569113000", "report_id 错: %s" % rid
    assert not dup, "首次入库不应是重复"
    # 重复整包
    _, dup2 = repo.insert_full_report(FULL_PAYLOAD)
    assert dup2, "重复整包应命中去重"


def test_delta_events_insert_and_dedup():
    """V-03 增量事件入库 + 去重"""
    repo = make_repo()
    ins1 = repo.insert_delta_events(DELTA_PAYLOAD)
    assert ins1 == 2, "增量应插 2, 实际 %d" % ins1
    ins2 = repo.insert_delta_events(DELTA_PAYLOAD)
    assert ins2 == 0, "重复增量应插 0, 实际 %d" % ins2


def test_multi_device_subscription():
    """V-07 多设备同时订阅"""
    repo = make_repo()
    ra = repo.upsert_subscription("dev01", "1号机")
    rb = repo.upsert_subscription("dev02", "2号机")
    assert ra["active"] and rb["active"], "多设备订阅应都 active=true"


def test_subscription_query_deactivate_reactivate():
    """V-06 订阅管理四接口：查询/退订/重新订阅"""
    repo = make_repo()
    repo.upsert_subscription("dev01", "1号机")
    # 查询
    s = repo.get_subscription("dev01")
    assert s and s["active"] == 1, "新订阅 active 应为 1"
    # 退订
    d = repo.deactivate_subscription("dev01")
    assert not d["active"], "退订后 active 应为 False"
    # 重新订阅（关键：必须重新激活 active=1）
    repo.upsert_subscription("dev01", "1号机-重订")
    s2 = repo.get_subscription("dev01")
    assert s2["active"] == 1, "重新订阅后 active 必须为 1, 实际 %s" % s2["active"]


def test_report_list_and_detail():
    """V-08 报告检索 + 详情"""
    repo = make_repo()
    rid, _ = repo.insert_full_report(FULL_PAYLOAD)
    lst = repo.list_reports({"device_id": "dev01"}, 1, 10)
    assert lst["total"] >= 1, "检索 dev01 应至少 1 条"
    det = repo.get_report_detail(rid)
    assert det and det["report"]["report_id"] == rid
    assert len(det["events"]) >= 2, "events 应 >= 2"
    assert len(det["steps"]) >= 1, "steps 应 >= 1"
    assert len(det["substeps"]) >= 1, "substeps 应 >= 1"


def test_unbound_student_archive():
    """V-09 未绑定学员归档（student={}）"""
    repo = make_repo()
    unbound = clone(FULL_PAYLOAD)
    unbound["student"] = {}
    unbound["device_id"] = "dev03"
    unbound["round"]["start_ms"] = 1787569999000
    rid, _ = repo.insert_full_report(unbound)
    det = repo.get_report_detail(rid)
    assert det["report"]["student_id"] is None, "未绑定 student_id 应为 NULL"
    assert det["report"]["student_bound"] == 0, "未绑定 student_bound 应为 0"


def test_delta_before_full_stub_report():
    """V-04 增量先于整包到达，创建存根报告"""
    repo = make_repo()
    delta_stub = {
        "schema_version": "1.1", "type": "event_delta",
        "device_id": "dev04", "edge_node": "touch_ui_plugin",
        "ts_upload_ms": 1788408000000,
        "round_start_ms": 1788407500000, "process_elapsed_ms": 500000,
        "student": {},
        "events": [{"ts": 1000, "kind": 0, "step": 1, "sub": 1}],
        "progress": {"done": 1, "total": 19, "current": "装缓冲",
                     "current_sub_index": 1}
    }
    ins = repo.insert_delta_events(delta_stub)
    assert ins == 1, "增量应插 1, 实际 %d" % ins
    conn = sqlite3.connect(DB)
    stub = conn.execute(
        "SELECT is_stub, process_elapsed_ms FROM reports WHERE report_id=?",
        ("Rdev04_1788407500000",)).fetchone()
    conn.close()
    assert stub, "存根报告应存在"
    assert stub[0] == 1, "is_stub 应为 1, 实际 %s" % stub[0]
    assert stub[1] == 500000, "process_elapsed_ms 应为 500000"


def test_report_progress_snapshot():
    """V-15 report_progress 实时进度快照"""
    repo = make_repo()
    repo.insert_delta_events(DELTA_PAYLOAD)
    conn = sqlite3.connect(DB)
    prog = conn.execute(
        "SELECT done, total, current, current_sub_index, process_elapsed_ms "
        "FROM report_progress WHERE device_id=?", ("dev02",)).fetchone()
    conn.close()
    assert prog, "report_progress 应有 dev02 记录"
    assert prog[0] == 2 and prog[1] == 19, "done/total 错"
    assert prog[2] == "装扣机", "current 错"
    assert prog[3] == 5, "current_sub_index 错"
    assert prog[4] == 910000, "process_elapsed_ms 错"


def test_raw_json_persistence():
    """V-16 原始 JSON 落盘"""
    repo = make_repo()
    rid, _ = repo.insert_full_report(FULL_PAYLOAD)
    raw_path = repo.save_raw_json("dev01", rid, FULL_PAYLOAD, RAW_DIR)
    assert os.path.exists(raw_path), "raw_json 文件不存在"
    with open(raw_path, "r", encoding="utf-8") as f:
        assert json.load(f)["device_id"] == "dev01"


def test_evidence_storage():
    """V-14 evidence 抓拍图存储"""
    repo = make_repo()
    ev_path = repo.save_evidence(
        "dev01", 1787569113000, 1, 3200,
        b"\xff\xd8\xff\xe0fake_jpg_data", EVID_DIR)
    assert os.path.exists(ev_path), "evidence 文件不存在"
    with open(ev_path, "rb") as f:
        assert f.read().startswith(b"\xff\xd8"), "JPEG SOI 标记缺失"


def test_unified_timing_fields():
    """V-17 统一计时字段入库（doc/58 v1.1）"""
    repo = make_repo()
    rid, _ = repo.insert_full_report(FULL_PAYLOAD)
    conn = sqlite3.connect(DB)
    tim = conn.execute(
        "SELECT process_elapsed_ms FROM reports WHERE report_id=?",
        (rid,)).fetchone()
    assert tim and tim[0] == 87000, "process_elapsed_ms 错"
    stp = conn.execute(
        "SELECT start_ms, end_ms, interval_ms FROM report_steps "
        "WHERE report_id=? AND idx=1", (rid,)).fetchone()
    assert stp, "report_steps 记录缺失"
    assert stp[0] == 3200 and stp[1] == 11400 and stp[2] == 0, \
        "steps.start_ms/end_ms/interval_ms 错"
    sub = conn.execute(
        "SELECT start_ms, end_ms FROM report_substeps "
        "WHERE report_id=? AND idx=1", (rid,)).fetchone()
    assert sub, "report_substeps 记录缺失"
    assert sub[0] == 3200 and sub[1] == 11400, "substeps.start_ms/end_ms 错"
    conn.close()
