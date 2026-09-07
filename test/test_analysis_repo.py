"""
test_analysis_repo.py — 统计分析仓储层单元测试

工程基线: app_mgr_object-0.2.1
关联文档: doc/71 统计分析插件开发方案

测试覆盖:
  - analysis_cache / diagnosis_results 建表幂等
  - 缓存读写 + TTL 过期
  - 诊断结果持久化 + 列表查询
  - 步骤用时分布统计
  - 学员累计统计
  - 班级汇总
  - 步骤平均用时 / 遗漏率 / 超时率
  - 学员成绩趋势
"""

import os
import sys
import json
import tempfile
import sqlite3
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app_mgr_object.components.web.analysis_repo import AnalysisRepo


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_and_repo(tmp_path):
    """构建临时 db + 仓储，并建好 analysis_schema 和 reports_schema"""
    db_path = str(tmp_path / "test_analysis.db")

    # analysis_schema
    analysis_schema_path = str(tmp_path / "analysis_schema.sql")
    with open(os.path.join(PROJECT_ROOT, "config", "analysis_schema.sql"), "r") as f:
        analysis_schema_sql = f.read()
    with open(analysis_schema_path, "w") as f:
        f.write(analysis_schema_sql)

    # reports_schema（reports 系列表，统计仓储要读）
    reports_schema_path = os.path.join(
        PROJECT_ROOT, "app_mgr_object", "components", "web", "reports_schema.sql"
    )

    class FakeLogger:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def error(self, *a, **k): pass
        def warning(self, *a, **k): pass

    # 先建 reports 系列表
    conn = sqlite3.connect(db_path)
    with open(reports_schema_path, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

    repo = AnalysisRepo(db_path, logger=FakeLogger(), schema_path=analysis_schema_path)
    repo.init_schema()

    return db_path, repo


def _insert_report(conn, report_id, device_id="dev01", student_id="S001",
                   student_cls="一班", total_score=80.0, ts_upload=1000000,
                   is_stub=0, finish_reason="completed"):
    """插入一条 reports 记录"""
    conn.execute(
        """INSERT OR REPLACE INTO reports
           (report_id, device_id, student_id, student_name, student_cls,
            student_bound, process_name, process_type, finish_reason,
            is_stub, start_ms, end_ms, duration_ms, process_elapsed_ms,
            total_score, raw_json_path, ts_upload_ms, created_at)
           VALUES (?, ?, ?, ?, ?, 0, NULL, 'disass', ?, ?, 0, 0, 0, 0, ?, NULL, ?, ?)""",
        (report_id, device_id, student_id, "测试学员", student_cls,
         finish_reason, is_stub, total_score, ts_upload, ts_upload)
    )


def _insert_step(conn, report_id, idx, name, state=2, duration_ms=5000):
    """插入一条 report_steps 记录"""
    conn.execute(
        """INSERT OR REPLACE INTO report_steps
           (report_id, idx, name, state, start_ms, end_ms, duration_ms, interval_ms)
           VALUES (?, ?, ?, ?, 0, 0, ?, 0)""",
        (report_id, idx, name, state, duration_ms)
    )


def _insert_substep(conn, report_id, idx, name, timeout=0):
    """插入一条 report_substeps 记录"""
    conn.execute(
        """INSERT OR REPLACE INTO report_substeps
           (report_id, idx, name, state, start_ms, end_ms,
            duration_ms, count, total_duration_ms, timeout)
           VALUES (?, ?, ?, 2, 0, 0, 0, 1, 0, ?)""",
        (report_id, idx, name, timeout)
    )


# ============================================================
# 建表幂等
# ============================================================

class TestInitSchema:
    def test_init_schema_idempotent(self, db_and_repo):
        db_path, repo = db_and_repo
        # 二次初始化不报错
        repo.init_schema()
        # 表存在
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "analysis_cache" in tables
        assert "diagnosis_results" in tables


# ============================================================
# 缓存读写 + TTL
# ============================================================

class TestCache:
    def test_save_and_get_cached(self, db_and_repo):
        _, repo = db_and_repo
        repo.save_cached_result("key1", "step_duration", {"cls": "一班"},
                                {"steps": []}, 0)
        result = repo.get_cached_result("key1", ttl_sec=300)
        assert result is not None
        assert result == {"steps": []}

    def test_get_nonexistent_returns_none(self, db_and_repo):
        _, repo = db_and_repo
        assert repo.get_cached_result("nonexistent", ttl_sec=300) is None

    def test_expired_cache_returns_none(self, db_and_repo):
        _, repo = db_and_repo
        # 手动插入一条已过期的缓存
        conn = repo._connect()
        try:
            conn.execute(
                """INSERT INTO analysis_cache
                   (cache_key, dimension, filters_json, result_json,
                    computed_at, report_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("expired_key", "step_duration", "{}",
                 json.dumps({"old": True}), 1, 0)
            )
            # computed_at 设为 10 分钟前
            old_time = repo._now_ms() - 600 * 1000
            conn.execute(
                "UPDATE analysis_cache SET computed_at = ? WHERE cache_key = ?",
                (old_time, "expired_key")
            )
            conn.commit()
        finally:
            conn.close()

        # TTL=300s，缓存已过期 600s
        result = repo.get_cached_result("expired_key", ttl_sec=300)
        assert result is None


# ============================================================
# 诊断结果持久化
# ============================================================

class TestDiagnosisPersistence:
    def test_save_and_list_diagnosis(self, db_and_repo):
        _, repo = db_and_repo
        did = repo.save_diagnosis({
            "diagnosis_type": "bottleneck",
            "scope": "class",
            "target_id": "step_3",
            "metric_value": 12500,
            "threshold_value": 12000,
            "advice_text": "该步骤需在下次课重点讲解"
        })
        assert did.startswith("D")

        results = repo.list_diagnoses(diagnosis_type="bottleneck")
        assert len(results) == 1
        assert results[0]["target_id"] == "step_3"
        assert results[0]["advice_text"] == "该步骤需在下次课重点讲解"

    def test_list_diagnoses_by_target(self, db_and_repo):
        _, repo = db_and_repo
        repo.save_diagnosis({
            "diagnosis_type": "bottleneck", "scope": "class",
            "target_id": "step_1", "metric_value": 100,
            "threshold_value": 80, "advice_text": "a"
        })
        repo.save_diagnosis({
            "diagnosis_type": "persistent_error", "scope": "class",
            "target_id": "step_2", "metric_value": 0.35,
            "threshold_value": 0.30, "advice_text": "b"
        })

        r1 = repo.list_diagnoses(target_id="step_1")
        assert len(r1) == 1
        r2 = repo.list_diagnoses(diagnosis_type="persistent_error")
        assert len(r2) == 1


# ============================================================
# 步骤用时分布统计
# ============================================================

class TestStepDurationStats:
    def test_empty_returns_zero(self, db_and_repo):
        _, repo = db_and_repo
        result = repo.get_step_duration_stats({})
        assert result["report_count"] == 0
        assert result["steps"] == []

    def test_stats_with_data(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 2 份报告，各 2 个步骤
        _insert_report(conn, "R001", total_score=80, ts_upload=1000)
        _insert_report(conn, "R002", total_score=90, ts_upload=2000)
        _insert_step(conn, "R001", 1, "装缓冲", duration_ms=5000)
        _insert_step(conn, "R001", 2, "装击针", duration_ms=8000)
        _insert_step(conn, "R002", 1, "装缓冲", duration_ms=6000)
        _insert_step(conn, "R002", 2, "装击针", duration_ms=7000)
        conn.commit()
        conn.close()

        result = repo.get_step_duration_stats({})
        assert result["report_count"] == 2
        steps = {s["idx"]: s for s in result["steps"]}
        assert len(steps) == 2
        # 步骤1平均 (5000+6000)/2 = 5500
        assert steps[1]["avg_duration_ms"] == 5500.0
        # 步骤2平均 (8000+7000)/2 = 7500
        assert steps[2]["avg_duration_ms"] == 7500.0

    def test_stats_exclude_stub_reports(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        _insert_report(conn, "R001", is_stub=0)
        _insert_report(conn, "R002", is_stub=1)  # 存根报告
        _insert_step(conn, "R001", 1, "步骤1", duration_ms=5000)
        _insert_step(conn, "R002", 1, "步骤1", duration_ms=9999)
        conn.commit()
        conn.close()

        result = repo.get_step_duration_stats({})
        # 只统计非存根报告
        assert result["report_count"] == 1
        assert len(result["steps"]) == 1
        assert result["steps"][0]["avg_duration_ms"] == 5000.0


# ============================================================
# 学员累计统计
# ============================================================

class TestStudentCumulative:
    def test_empty_student(self, db_and_repo):
        _, repo = db_and_repo
        result = repo.get_student_cumulative_stats("NOPE")
        assert result["exam_count"] == 0

    def test_cumulative_with_scores(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 3 次考试，成绩 60, 70, 80
        for i, score in enumerate([60, 70, 80]):
            rid = f"R_S001_{i}"
            _insert_report(conn, rid, student_id="S001",
                           total_score=score, ts_upload=1000 + i)
            _insert_step(conn, rid, 1, "步骤1", duration_ms=5000 + i * 100)
            _insert_step(conn, rid, 2, "步骤2", duration_ms=9000)
        conn.commit()
        conn.close()

        result = repo.get_student_cumulative_stats("S001")
        assert result["exam_count"] == 3
        assert result["avg_score"] == 70.0  # (60+70+80)/3
        assert result["min_score"] == 60
        assert result["max_score"] == 80
        assert len(result["scores"]) == 3
        # 薄弱步骤 TOP3：步骤2平均用时最高
        assert len(result["weak_steps"]) <= 3


# ============================================================
# 班级汇总
# ============================================================

class TestClassSummary:
    def test_empty_class(self, db_and_repo):
        _, repo = db_and_repo
        result = repo.get_class_summary("不存在班")
        assert result["total"] == 0

    def test_class_summary(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 3 份报告，一班，成绩 50, 60, 70
        for i, score in enumerate([50, 60, 70]):
            _insert_report(conn, f"R_{i}", student_cls="一班",
                           total_score=score, ts_upload=1000 + i)
            _insert_step(conn, f"R_{i}", 1, "步骤1", state=0)  # 遗漏
            _insert_step(conn, f"R_{i}", 2, "步骤2", state=2)  # 完成
        conn.commit()
        conn.close()

        result = repo.get_class_summary("一班")
        assert result["total"] == 3
        assert result["avg_score"] == 60.0  # (50+60+70)/3
        # 通过率：60 和 70 通过（>=60），50 不通过 → 2/3
        assert result["pass_rate"] == pytest.approx(2 / 3, rel=0.01)


# ============================================================
# 步骤平均用时 / 遗漏率 / 超时率
# ============================================================

class TestStepMetrics:
    def test_step_avg_duration(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        _insert_report(conn, "R001")
        _insert_report(conn, "R002")
        _insert_step(conn, "R001", 1, "步骤1", duration_ms=4000)
        _insert_step(conn, "R002", 1, "步骤1", duration_ms=6000)
        conn.commit()
        conn.close()

        avg = repo.get_step_avg_duration(1, {})
        assert avg == 5000.0  # (4000+6000)/2

    def test_step_omission_rate(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 4 份报告，步骤1：2 份遗漏(state=0)，2 份完成(state=2)
        for i in range(4):
            _insert_report(conn, f"R{i}")
            state = 0 if i < 2 else 2
            _insert_step(conn, f"R{i}", 1, "步骤1", state=state)
        conn.commit()
        conn.close()

        rate = repo.get_step_omission_rate(1, {})
        assert rate == 0.5  # 2/4

    def test_step_timeout_rate(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 2 份报告
        _insert_report(conn, "R001")
        _insert_report(conn, "R002")
        _insert_step(conn, "R001", 1, "步骤1")
        _insert_step(conn, "R002", 1, "步骤1")
        # R001 的子步骤1 有超时标记
        _insert_substep(conn, "R001", 1, "子步骤1", timeout=1)
        _insert_substep(conn, "R002", 1, "子步骤1", timeout=0)
        conn.commit()
        conn.close()

        rate = repo.get_step_timeout_rate(1, {})
        assert rate == 0.5  # 1/2


# ============================================================
# 学员成绩趋势
# ============================================================

class TestScoreTrend:
    def test_trend_ascending(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        for i, score in enumerate([60, 70, 80, 85, 90]):
            _insert_report(conn, f"R{i}", student_id="S001",
                           total_score=score, ts_upload=1000 + i * 100)
        conn.commit()
        conn.close()

        trend = repo.get_student_score_trend("S001", window=5)
        assert len(trend) == 5
        # 最旧→最新
        assert trend[0]["score"] == 60
        assert trend[-1]["score"] == 90

    def test_trend_limited_window(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        for i in range(10):
            _insert_report(conn, f"R{i}", student_id="S001",
                           total_score=50 + i, ts_upload=1000 + i * 100)
        conn.commit()
        conn.close()

        trend = repo.get_student_score_trend("S001", window=3)
        assert len(trend) == 3
        # 取最近3次（59, 60, 61... 实际是 score=57,58,59）
        # trend 返回升序（最旧→最新）
        assert trend[-1]["score"] == 59
