"""
test_diagnosis_engine.py — 诊断规则引擎单元测试

工程基线: app_mgr_object-0.2.1
关联文档: doc/71 统计分析插件开发方案 §4.3、需求说明.docx §3.3.3

测试覆盖 4 类诊断阈值规则：
  1. 全班性瓶颈（bottleneck）：全班平均用时 > SOP标准×1.5
  2. 顽固性错误（persistent_error）：遗漏率 > 30%
  3. 顺序混乱（sequence_chaos）：顺序错误率 > 20%（与 ScoringEngine.sequence_error 同源）
  4. 学员退步预警（student_regression）：最近3次平均分 < 前5次×0.85
"""

import os
import sys
import sqlite3
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app_mgr_object.components.web.analysis_repo import AnalysisRepo
from app_mgr_object.components.web.diagnosis_engine import DiagnosisEngine


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def engine_and_db(tmp_path):
    """构建临时 db + 仓储 + 诊断引擎"""
    db_path = str(tmp_path / "test_diag.db")

    analysis_schema_path = str(tmp_path / "analysis_schema.sql")
    with open(os.path.join(PROJECT_ROOT, "config", "analysis_schema.sql"), "r") as f:
        analysis_schema_sql = f.read()
    with open(analysis_schema_path, "w") as f:
        f.write(analysis_schema_sql)

    reports_schema_path = os.path.join(
        PROJECT_ROOT, "app_mgr_object", "components", "web", "reports_schema.sql"
    )

    class FakeLogger:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def error(self, *a, **k): pass
        def warning(self, *a, **k): pass

    conn = sqlite3.connect(db_path)
    with open(reports_schema_path, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

    repo = AnalysisRepo(db_path, logger=FakeLogger(), schema_path=analysis_schema_path)
    repo.init_schema()

    thresholds = {
        "bottleneck_multiplier": 1.5,
        "persistent_error_rate": 0.30,
        "sequence_chaos_rate": 0.20,
        "regression_window_recent": 3,
        "regression_window_history": 5,
        "regression_threshold": 0.85,
    }
    # SOP 标准：步骤1=8000ms, 步骤2=6000ms
    sop_standards = {"disass": {1: 8000.0, 2: 6000.0}}

    engine = DiagnosisEngine(
        repo=repo, thresholds=thresholds,
        sop_standards=sop_standards, logger=FakeLogger()
    )

    return db_path, repo, engine


def _insert_report(conn, report_id, student_id="S001", student_cls="一班",
                   total_score=80.0, ts_upload=1000000, is_stub=0,
                   finish_reason="completed", device_id="dev01"):
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
    conn.execute(
        """INSERT OR REPLACE INTO report_steps
           (report_id, idx, name, state, start_ms, end_ms, duration_ms, interval_ms)
           VALUES (?, ?, ?, ?, 0, 0, ?, 0)""",
        (report_id, idx, name, state, duration_ms)
    )


# ============================================================
# 1. 全班性瓶颈诊断
# ============================================================

class TestBottleneck:
    def test_bottleneck_triggered(self, engine_and_db):
        """全班平均用时 > SOP×1.5 → 触发瓶颈诊断"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 步骤1 SOP=8000, 阈值=12000, 实际=13000 → 触发
        for i in range(3):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "装缓冲", duration_ms=13000)
        conn.commit()
        conn.close()

        results = engine.diagnose_class_bottleneck()
        assert len(results) == 1
        assert results[0]["diagnosis_type"] == "bottleneck"
        assert results[0]["target_id"] == "step_1"
        assert results[0]["metric_value"] == 13000.0
        assert results[0]["threshold_value"] == 12000.0
        assert "重点讲解" in results[0]["advice_text"]

    def test_bottleneck_not_triggered(self, engine_and_db):
        """全班平均用时 <= SOP×1.5 → 不触发"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 步骤1 SOP=8000, 阈值=12000, 实际=10000 → 不触发
        for i in range(3):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "装缓冲", duration_ms=10000)
        conn.commit()
        conn.close()

        results = engine.diagnose_class_bottleneck()
        assert len(results) == 0

    def test_bottleneck_no_sop_standard_skipped(self, engine_and_db):
        """无 SOP 标准用时的步骤 → 跳过瓶颈诊断"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 步骤3 无 SOP 标准
        for i in range(3):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 3, "未知步骤", duration_ms=99999)
        conn.commit()
        conn.close()

        results = engine.diagnose_class_bottleneck()
        assert len(results) == 0


# ============================================================
# 2. 顽固性错误诊断
# ============================================================

class TestPersistentError:
    def test_persistent_error_triggered(self, engine_and_db):
        """遗漏率 > 30% → 触发"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 4 份报告，步骤1：3 份遗漏(state=0), 1 份完成 → 75% > 30%
        for i in range(4):
            _insert_report(conn, f"R{i}")
            state = 0 if i < 3 else 2
            _insert_step(conn, f"R{i}", 1, "步骤1", state=state)
        conn.commit()
        conn.close()

        results = engine.diagnose_persistent_error()
        assert len(results) == 1
        assert results[0]["diagnosis_type"] == "persistent_error"
        assert results[0]["metric_value"] == 0.75
        assert results[0]["threshold_value"] == 0.30
        assert "专项训练" in results[0]["advice_text"]

    def test_persistent_error_not_triggered(self, engine_and_db):
        """遗漏率 <= 30% → 不触发"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 10 份报告，步骤1：2 份遗漏 → 20% < 30%
        for i in range(10):
            _insert_report(conn, f"R{i}")
            state = 0 if i < 2 else 2
            _insert_step(conn, f"R{i}", 1, "步骤1", state=state)
        conn.commit()
        conn.close()

        results = engine.diagnose_persistent_error()
        assert len(results) == 0

    def test_persistent_error_skipped_state(self, engine_and_db):
        """state=3（跳过）也算遗漏"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 3 份报告，步骤1：全部 state=3（跳过）→ 100% > 30%
        for i in range(3):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "步骤1", state=3)
        conn.commit()
        conn.close()

        results = engine.diagnose_persistent_error()
        assert len(results) == 1


# ============================================================
# 3. 顺序混乱诊断
# ============================================================

class TestSequenceChaos:
    def test_sequence_chaos_triggered(self, engine_and_db):
        """顺序错误率 > 20% → 触发"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 5 份报告，步骤1 全部顺序错误（sequence_error=1）
        for i in range(5):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "步骤1")
            conn.execute(
                """INSERT OR REPLACE INTO report_substeps
                   (report_id, idx, name, state, start_ms, end_ms,
                    duration_ms, count, total_duration_ms, timeout, sequence_error)
                   VALUES (?, 1, '子1', 2, 0, 0, 0, 1, 0, 0, 1)""",
                (f"R{i}",)
            )
        conn.commit()
        conn.close()

        results = engine.diagnose_sequence_chaos()
        assert len(results) == 1
        assert results[0]["diagnosis_type"] == "sequence_chaos"
        assert results[0]["metric_value"] == 1.0  # 5/5
        assert "依赖关系" in results[0]["advice_text"]

    def test_sequence_chaos_not_triggered(self, engine_and_db):
        """顺序错误率 <= 20% → 不触发"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 10 份报告，步骤1 仅 1 份顺序错误 → 10% < 20%
        for i in range(10):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "步骤1")
            seq_err = 1 if i == 0 else 0
            conn.execute(
                """INSERT OR REPLACE INTO report_substeps
                   (report_id, idx, name, state, start_ms, end_ms,
                    duration_ms, count, total_duration_ms, timeout, sequence_error)
                   VALUES (?, 1, '子1', 2, 0, 0, 0, 1, 0, 0, ?)""",
                (f"R{i}", seq_err)
            )
        conn.commit()
        conn.close()

        results = engine.diagnose_sequence_chaos()
        assert len(results) == 0


# ============================================================
# 4. 学员退步预警诊断
# ============================================================

class TestStudentRegression:
    def test_regression_triggered(self, engine_and_db):
        """最近3次平均分 < 前5次×0.85 → 触发"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 前5次：80, 80, 80, 80, 80 → 平均80
        # 最近3次：50, 50, 50 → 平均50
        # 阈值：80×0.85=68，50<68 → 触发
        scores = [80, 80, 80, 80, 80, 50, 50, 50]
        for i, score in enumerate(scores):
            _insert_report(conn, f"R{i}", student_id="S001",
                           total_score=score, ts_upload=1000 + i * 100)
        conn.commit()
        conn.close()

        results = engine.diagnose_student_regression("S001")
        assert len(results) == 1
        assert results[0]["diagnosis_type"] == "student_regression"
        assert results[0]["metric_value"] == 50.0  # 最近3次平均
        assert "个别辅导" in results[0]["advice_text"]

    def test_regression_not_triggered(self, engine_and_db):
        """最近3次平均分 >= 前5次×0.85 → 不触发"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 前5次平均80，最近3次平均75 → 阈值68，75>=68 → 不触发
        scores = [80, 80, 80, 80, 80, 75, 75, 75]
        for i, score in enumerate(scores):
            _insert_report(conn, f"R{i}", student_id="S001",
                           total_score=score, ts_upload=1000 + i * 100)
        conn.commit()
        conn.close()

        results = engine.diagnose_student_regression("S001")
        assert len(results) == 0

    def test_regression_insufficient_data(self, engine_and_db):
        """考试次数不足8次 → 不诊断"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 仅 5 次考试
        for i in range(5):
            _insert_report(conn, f"R{i}", student_id="S001",
                           total_score=80, ts_upload=1000 + i * 100)
        conn.commit()
        conn.close()

        results = engine.diagnose_student_regression("S001")
        assert len(results) == 0


# ============================================================
# 综合诊断
# ============================================================

class TestDiagnoseAll:
    def test_diagnose_all_combines_results(self, engine_and_db):
        """diagnose_all 组合多类诊断结果"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        # 3 份报告，步骤1 超时且遗漏且顺序错误
        for i in range(3):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "步骤1", state=0, duration_ms=13000)
            conn.execute(
                """INSERT OR REPLACE INTO report_substeps
                   (report_id, idx, name, state, start_ms, end_ms,
                    duration_ms, count, total_duration_ms, timeout, sequence_error)
                   VALUES (?, 1, '子1', 2, 0, 0, 0, 1, 0, 1, 1)""",
                (f"R{i}",)
            )
        conn.commit()
        conn.close()

        results = engine.diagnose_all()
        # 应同时触发 bottleneck + persistent_error + sequence_chaos
        types = {r["diagnosis_type"] for r in results}
        assert "bottleneck" in types
        assert "persistent_error" in types
        assert "sequence_chaos" in types

    def test_diagnose_all_empty(self, engine_and_db):
        """无数据时 diagnose_all 返回空列表"""
        _, _, engine = engine_and_db
        results = engine.diagnose_all()
        assert results == []

    def test_each_diagnosis_has_required_fields(self, engine_and_db):
        """每条诊断结果含 metric_value + threshold_value + advice_text"""
        db_path, repo, engine = engine_and_db
        conn = sqlite3.connect(db_path)
        for i in range(3):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "步骤1", state=0, duration_ms=13000)
        conn.commit()
        conn.close()

        results = engine.diagnose_all()
        for r in results:
            assert "metric_value" in r
            assert "threshold_value" in r
            assert "advice_text" in r
            assert r["advice_text"]  # 非空
