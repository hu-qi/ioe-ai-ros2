"""
test_dashboard_repo.py — 教学看板仓储层单元测试

工程基线: app_mgr_object-0.2.1
关联文档: doc/72 教学看板插件开发方案

测试覆盖（doc/72 §8.2 V-01~V-10）：
  V-01 今日概览 4 指标计算正确
  V-02 高频错误点 TOP5 排序正确
  V-04 需关注学员列表正确（退步预警触发）
  V-06 实时进度展示
  V-08 教学改进验证两时间窗对比正确
  V-09 今日无数据时各模块返回空值不报错
"""

import os
import sys
import sqlite3
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app_mgr_object.components.web.dashboard_repo import DashboardRepo


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_and_repo(tmp_path):
    """构建临时 db + 仓储，并建好 analysis_schema 和 reports_schema"""
    db_path = str(tmp_path / "test_dashboard.db")

    # analysis_schema（复用 P2 的，含 diagnosis_results 表）
    analysis_schema_path = str(tmp_path / "analysis_schema.sql")
    with open(os.path.join(PROJECT_ROOT, "config", "analysis_schema.sql"), "r") as f:
        analysis_schema_sql = f.read()
    with open(analysis_schema_path, "w") as f:
        f.write(analysis_schema_sql)

    # reports_schema（reports 系列表，看板要读）
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

    repo = DashboardRepo(db_path, logger=FakeLogger(), schema_path=analysis_schema_path)
    repo.init_schema()

    return db_path, repo


def _insert_report(conn, report_id, device_id="dev01", student_id="S001",
                   student_name="张明", student_cls="一班", total_score=80.0,
                   ts_upload=1000000, is_stub=0, finish_reason="completed"):
    """插入一条 reports 记录（仅必要列，其余靠默认值）"""
    conn.execute(
        "INSERT INTO reports (report_id, device_id, student_id, student_name, "
        "student_cls, process_type, finish_reason, is_stub, start_ms, "
        "total_score, ts_upload_ms, created_at) "
        "VALUES (?,?,?,?,?,'disass',?,?,?,?,?,?)",
        (report_id, device_id, student_id, student_name, student_cls,
         finish_reason, is_stub, 0, total_score, ts_upload, ts_upload)
    )


def _insert_step(conn, report_id, idx, name, state=2, duration_ms=5000):
    conn.execute(
        "INSERT INTO report_steps (report_id,idx,name,state,start_ms,end_ms,duration_ms,interval_ms) "
        "VALUES (?,?,?,?,0,0,?,0)",
        (report_id, idx, name, state, duration_ms)
    )


# ============================================================
# V-09: 今日无数据时各模块返回空值不报错
# ============================================================

class TestEmptyData:
    def test_today_summary_empty(self, db_and_repo):
        _, repo = db_and_repo
        result = repo.get_today_summary(60.0)
        assert result["exam_count"] == 0
        assert result["avg_score"] == 0
        assert result["pass_rate"] == 0
        assert result["pending_tutor_count"] == 0

    def test_top_error_points_empty(self, db_and_repo):
        _, repo = db_and_repo
        points = repo.get_top_error_points(limit=5)
        assert points == []

    def test_attention_students_empty(self, db_and_repo):
        _, repo = db_and_repo
        students = repo.get_attention_students(limit=20)
        assert students == []

    def test_realtime_progress_empty(self, db_and_repo):
        _, repo = db_and_repo
        devices = repo.get_realtime_progress()
        assert devices == []


# ============================================================
# V-01: 今日概览 4 指标
# ============================================================

class TestTodaySummary:
    def test_today_summary_with_data(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 今日 3 份报告：60, 70, 80 → avg=70, pass=2/3 (>=60)
        today_ts = int(__import__('time').time() * 1000)
        for i, score in enumerate([60, 70, 80]):
            _insert_report(conn, f"R{i}", total_score=score,
                           ts_upload=today_ts + i * 100)
        conn.commit()
        conn.close()

        result = repo.get_today_summary(60.0)
        assert result["exam_count"] == 1  # DISTINCT student_id（都是 S001）
        assert result["avg_score"] == 70.0
        # 3 份报告 60/70/80 全部 >=60 → pass_rate=1.0
        assert result["pass_rate"] == 1.0

    def test_today_summary_with_diagnosis(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 插入一条退步预警诊断
        conn.execute(
            "INSERT INTO diagnosis_results (diagnosis_id,diagnosis_type,scope,target_id,"
            "metric_value,threshold_value,advice_text,computed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("D1", "student_regression", "student", "S002", 50.0, 68.0, "建议个别辅导", 1000)
        )
        conn.commit()
        conn.close()

        result = repo.get_today_summary(60.0)
        assert result["pending_tutor_count"] == 1


# ============================================================
# V-02: 高频错误点 TOP5 排序
# ============================================================

class TestTopErrorPoints:
    def test_top_error_points_ordering(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 4 份报告，步骤1全遗漏(state=0)，步骤2全完成(state=2)
        for i in range(4):
            _insert_report(conn, f"R{i}")
            _insert_step(conn, f"R{i}", 1, "步骤1", state=0, duration_ms=8000)
            _insert_step(conn, f"R{i}", 2, "步骤2", state=2, duration_ms=4000)
        conn.commit()
        conn.close()

        points = repo.get_top_error_points(limit=5)
        assert len(points) >= 2
        # 步骤1遗漏率1.0 > 步骤2遗漏率0.0
        p1 = next((p for p in points if p["idx"] == 1), None)
        p2 = next((p for p in points if p["idx"] == 2), None)
        assert p1 is not None and p2 is not None
        assert p1["composite_score"] > p2["composite_score"]

    def test_top_error_points_limit(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 3 份报告，3 个步骤
        for i in range(3):
            _insert_report(conn, f"R{i}")
            for idx in range(1, 4):
                _insert_step(conn, f"R{i}", idx, f"步骤{idx}", state=0)
        conn.commit()
        conn.close()

        points = repo.get_top_error_points(limit=2)
        assert len(points) == 2


# ============================================================
# V-04: 需关注学员（退步预警）
# ============================================================

class TestAttentionStudents:
    def test_attention_with_regression(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 插入退步预警诊断
        conn.execute(
            "INSERT INTO diagnosis_results (diagnosis_id,diagnosis_type,scope,target_id,"
            "metric_value,threshold_value,advice_text,computed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("D1", "student_regression", "student", "S001", 50.0, 68.0, "建议个别辅导", 1000)
        )
        # 插入对应的报告数据（供查学员姓名）
        _insert_report(conn, "R1", student_id="S001", student_name="张明", total_score=50)
        conn.commit()
        conn.close()

        students = repo.get_attention_students(limit=20)
        assert len(students) >= 1
        regression = next((s for s in students if s["reason"] == "student_regression"), None)
        assert regression is not None
        assert regression["student_id"] == "S001"

    def test_attention_with_volatility(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 插入 5 份报告，成绩波动极大（50, 90, 50, 90, 50）
        for i, score in enumerate([50, 90, 50, 90, 50]):
            _insert_report(conn, f"R{i}", student_id="S002",
                           student_name="李华", total_score=score,
                           ts_upload=1000000 + i * 100)
        conn.commit()
        conn.close()

        students = repo.get_attention_students(limit=20, volatility_threshold=15.0)
        volatility = next((s for s in students if s["reason"] == "volatility"), None)
        assert volatility is not None


# ============================================================
# V-06: 实时进度展示
# ============================================================

class TestRealtimeProgress:
    def test_realtime_progress_with_data(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 插入实时进度数据
        conn.execute(
            "INSERT INTO report_progress (report_id,device_id,round_start_ms,done,total,"
            "current,current_sub_index,process_elapsed_ms,last_delta_ts,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("R1", "dev01", 1000, 12, 19, "装击针", 13, 91000, 5000, 2000000)
        )
        conn.commit()
        conn.close()

        devices = repo.get_realtime_progress()
        assert len(devices) == 1
        d = devices[0]
        assert d["device_id"] == "dev01"
        assert d["done"] == 12
        assert d["total"] == 19
        assert d["current"] == "装击针"


# ============================================================
# V-08: 教学改进验证
# ============================================================

class TestImprovementValidation:
    def test_improvement_validation_improved(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 调整前：2 份报告，成绩 50, 55 → avg=52.5
        for i, score in enumerate([50, 55]):
            _insert_report(conn, f"Rb{i}", student_id="S001",
                           student_cls="一班", student_name="张明",
                           total_score=score, ts_upload=1000000 + i)
        # 调整后：2 份报告，成绩 80, 85 → avg=82.5
        for i, score in enumerate([80, 85]):
            _insert_report(conn, f"Ra{i}", student_id="S001",
                           student_cls="一班", student_name="张明",
                           total_score=score, ts_upload=2000000 + i)
        conn.commit()
        conn.close()

        result = repo.get_improvement_validation(
            cls="一班",
            before_range={"date_start": 900000, "date_end": 1500000},
            after_range={"date_start": 1900000, "date_end": 2500000},
            pass_threshold=60.0
        )

        assert result["trend"] == "improved"
        assert result["before"]["avg_score"] == 52.5
        assert result["after"]["avg_score"] == 82.5
        assert result["delta"]["avg_score"] == 30.0

    def test_improvement_validation_no_data(self, db_and_repo):
        _, repo = db_and_repo
        result = repo.get_improvement_validation(
            cls="不存在班",
            before_range={"date_start": 0, "date_end": 1000},
            after_range={"date_start": 1001, "date_end": 2000},
            pass_threshold=60.0
        )
        assert result["trend"] == "no_data"
        assert result["before"] is None
        assert result["after"] is None

    def test_improvement_validation_declined(self, db_and_repo):
        db_path, repo = db_and_repo
        conn = sqlite3.connect(db_path)
        # 调整前：成绩 80, 85 → avg=82.5
        for i, score in enumerate([80, 85]):
            _insert_report(conn, f"Rb{i}", student_id="S001",
                           student_cls="一班", student_name="张明",
                           total_score=score, ts_upload=1000000 + i)
        # 调整后：成绩 50, 55 → avg=52.5
        for i, score in enumerate([50, 55]):
            _insert_report(conn, f"Ra{i}", student_id="S001",
                           student_cls="一班", student_name="张明",
                           total_score=score, ts_upload=2000000 + i)
        conn.commit()
        conn.close()

        result = repo.get_improvement_validation(
            cls="一班",
            before_range={"date_start": 900000, "date_end": 1500000},
            after_range={"date_start": 1900000, "date_end": 2500000},
            pass_threshold=60.0
        )

        assert result["trend"] == "declined"
        assert result["delta"]["avg_score"] < 0
