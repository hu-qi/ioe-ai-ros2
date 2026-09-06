"""
事件流合并器 EventMerge 端到端验证

覆盖 doc/70 §8.3 验收项 V-05 + 合并器独立维度：
  - 增量事件流合并（INSERT OR IGNORE 天然去重）
  - 重复增量合并去重
  - 整包到达时与增量事件对账（reconcile_full_report）
  - 整包对账去重
  - 存根报告补全后 is_stub=0 / finish_reason / duration_ms
"""

from conftest import (
    DB, FULL_PAYLOAD, DELTA_PAYLOAD, make_repo, clone, StubLogger,
)
from app_mgr_object.components.web.event_merge import EventMerge


def test_delta_merge_insert_and_dedup():
    """增量事件流合并 + 去重"""
    repo = make_repo()
    merger = EventMerge(repo, StubLogger())
    delta = clone(DELTA_PAYLOAD)
    delta["device_id"] = "dev05"
    delta["round_start_ms"] = 1788500000000
    delta["events"] = [
        {"ts": 100, "kind": 0, "step": 1, "sub": 1},
        {"ts": 200, "kind": 1, "step": 1, "sub": 1},
        {"ts": 300, "kind": 2, "step": 2, "sub": 1},
    ]
    ins1 = merger.merge_delta_into_report(delta)
    assert ins1 == 3, "增量应插 3, 实际 %d" % ins1
    ins2 = merger.merge_delta_into_report(delta)
    assert ins2 == 0, "重复增量应插 0, 实际 %d" % ins2


def test_reconcile_full_report_merges_with_delta():
    """V-05 整包到达时与增量事件对账，事件流去重合并"""
    repo = make_repo()
    merger = EventMerge(repo, StubLogger())

    # 先发增量（3 条事件）
    delta = clone(DELTA_PAYLOAD)
    delta["device_id"] = "dev05"
    delta["round_start_ms"] = 1788500000000
    delta["events"] = [
        {"ts": 100, "kind": 0, "step": 1, "sub": 1},
        {"ts": 200, "kind": 1, "step": 1, "sub": 1},
        {"ts": 300, "kind": 2, "step": 2, "sub": 1},
    ]
    merger.merge_delta_into_report(delta)

    # 后发整包（含 3 条重复 + 1 条独有）
    full = clone(FULL_PAYLOAD)
    full["device_id"] = "dev05"
    full["round"]["start_ms"] = 1788500000000
    full["round"]["events"] = [
        {"ts": 100, "kind": 0, "step": 1, "sub": 1},  # 与增量重复
        {"ts": 200, "kind": 1, "step": 1, "sub": 1},  # 与增量重复
        {"ts": 300, "kind": 2, "step": 2, "sub": 1},  # 与增量重复
        {"ts": 400, "kind": 1, "step": 3, "sub": 1},  # 整包独有
    ]
    rid = merger.reconcile_full_report(full)
    assert rid == "Rdev05_1788500000000"

    stream = merger.get_merged_event_stream(rid)
    assert len(stream) == 4, "合并后应 4 条事件, 实际 %d" % len(stream)
    ts_list = [e["ts"] for e in stream]
    assert ts_list == sorted(ts_list), "事件流未按 ts 升序"


def test_reconcile_dedup_on_repeat_full():
    """整包对账去重：重复整包不应产生重复事件"""
    repo = make_repo()
    merger = EventMerge(repo, StubLogger())

    full = clone(FULL_PAYLOAD)
    full["device_id"] = "dev05"
    full["round"]["start_ms"] = 1788500000000
    merger.reconcile_full_report(full)
    merger.reconcile_full_report(full)  # 重复整包

    stream = merger.get_merged_event_stream("Rdev05_1788500000000")
    assert len(stream) == 2, "重复整包后事件数应不变, 实际 %d" % len(stream)


def test_stub_report_completed_after_reconcile():
    """存根报告补全后 is_stub=0 / finish_reason / duration_ms 正确"""
    import sqlite3
    repo = make_repo()
    merger = EventMerge(repo, StubLogger())

    # 先发增量（创建存根）
    delta = clone(DELTA_PAYLOAD)
    delta["device_id"] = "dev05"
    delta["round_start_ms"] = 1788500000000
    merger.merge_delta_into_report(delta)

    # 后发整包（补全存根）
    full = clone(FULL_PAYLOAD)
    full["device_id"] = "dev05"
    full["round"]["start_ms"] = 1788500000000
    merger.reconcile_full_report(full)

    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT is_stub, finish_reason, duration_ms FROM reports "
        "WHERE report_id=?", ("Rdev05_1788500000000",)).fetchone()
    conn.close()
    assert row, "报告不存在"
    assert row[0] == 0, "存根补全后 is_stub 应为 0, 实际 %s" % row[0]
    assert row[1] == "completed", "finish_reason 补全失败: %s" % row[1]
    assert row[2] == 87000, "duration_ms 补全失败: %s" % row[2]
