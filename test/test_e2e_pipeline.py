"""端到端集成验证：P0 学员管理 → P1 报告接收 → P2 统计分析 → P3 教学看板。

工程基线: app_mgr_object-0.2.1
验证目标: 数据流闭环
  P0 StudentRepo.create → 学员档案入库
  P1 ReportRepo.insert_full_report → 报告 + 明细 + 事件入库，student_bound=1
  P2 AnalysisRepo.get_step_duration_stats / get_student_cumulative_stats → 步骤用时 + 学员累计统计
  P2 DiagnosisEngine.diagnose_all → 4 类诊断规则
  P3 DashboardRepo.get_today_summary / get_top_error_points / get_attention_students → 看板聚合

运行:
  pytest test/test_e2e_pipeline.py -q
"""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_mgr_object.components.web.student_repo import StudentRepo
from app_mgr_object.components.web.report_repo import ReportRepo
from app_mgr_object.components.web.analysis_repo import AnalysisRepo
from app_mgr_object.components.web.diagnosis_engine import DiagnosisEngine
from app_mgr_object.components.web.dashboard_repo import DashboardRepo

STUDENTS_SCHEMA = PROJECT_ROOT / 'config' / 'students_schema.sql'
REPORTS_SCHEMA = PROJECT_ROOT / 'app_mgr_object' / 'components' / 'web' / 'reports_schema.sql'
ANALYSIS_SCHEMA = PROJECT_ROOT / 'config' / 'analysis_schema.sql'


def _build_full_report(student_id: str, device_id: str, step_durations: list,
                       score: float, omission_steps: list = None,
                       timeout_steps: list = None) -> dict:
    """构造一份 doc/38 整包报告 payload。

    真实结构（对齐 ReportRepo.insert_full_report）:
      payload.student = {id, name, cls}
      payload.round = {start_ms, end_ms, finish_reason, total_score, steps[], substeps[], events[]}
      payload.device_id, payload.ts_upload_ms
    """
    now_ms = int(time.time() * 1000)
    steps = []
    events = []
    for idx, dur_ms in enumerate(step_durations):
        is_omitted = idx in (omission_steps or [])
        is_timeout = idx in (timeout_steps or [])
        steps.append({
            'idx': idx,
            'name': f'step_{idx}',
            'state': 3 if is_omitted else 1,  # 3=omitted, 1=completed
            'start_ms': now_ms + idx * 10000,
            'end_ms': now_ms + idx * 10000 + dur_ms,
            'duration_ms': dur_ms,
            'interval_ms': 0,
        })
        if is_timeout:
            events.append({
                'ts': now_ms + idx * 10000 + dur_ms,
                'kind': 2,  # INTERRUPT
                'step': idx,
                'sub': 0,
            })
    return {
        'device_id': device_id,
        'ts_upload_ms': now_ms,
        'student': {
            'id': student_id or '',
            'name': f'学员_{student_id}' if student_id else '',
            'cls': '一班',
        },
        'round': {
            'start_ms': now_ms,
            'end_ms': now_ms + sum(step_durations),
            'finish_reason': 'completed',
            'total_score': score,
            'duration_ms': sum(step_durations),
            'steps': steps,
            'substeps': [],
            'events': events,
        },
    }


class TestE2EPipeline:
    """端到端数据流闭环验证。"""

    @classmethod
    def setup_class(cls):
        cls.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db_path = os.path.join(cls.tmpdir.name, 'e2e.db')

        # 初始化 schema（单库多表）
        conn = sqlite3.connect(cls.db_path)
        for schema_path in [STUDENTS_SCHEMA, REPORTS_SCHEMA, ANALYSIS_SCHEMA]:
            with open(schema_path, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())
        conn.close()

        # 实例化四个仓储 + 诊断引擎
        cls.student_repo = StudentRepo(cls.db_path)
        cls.report_repo = ReportRepo(cls.db_path)
        cls.analysis_repo = AnalysisRepo(cls.db_path)
        cls.dashboard_repo = DashboardRepo(cls.db_path)
        cls.thresholds = {
            'bottleneck_multiplier': 1.5,
            'persistent_error_rate': 0.30,
            'sequence_chaos_rate': 0.20,
            'regression_window_recent': 3,
            'regression_window_history': 5,
            'regression_threshold': 0.85,
        }
        cls.sop_standards = {
            'assembly': {0: 10000, 1: 10000, 2: 10000, 3: 10000, 4: 10000},
        }
        cls.diagnosis_engine = DiagnosisEngine(
            cls.analysis_repo,
            thresholds=cls.thresholds,
            sop_standards=cls.sop_standards,
        )

    @classmethod
    def teardown_class(cls):
        cls.tmpdir.cleanup()

    def test_01_p0_student_create(self):
        """P0：创建学员档案。"""
        sid = self.student_repo.create({
            'id': 'S001',
            'name': '张三',
            'cls': '一班',
            'enroll_date': '2026-09-01',
        })
        assert sid == 'S001'
        stu = self.student_repo.get('S001')
        assert stu['name'] == '张三'
        assert stu['cls'] == '一班'
        assert stu['status'] == 'active'

    def test_02_p0_student_soft_delete(self):
        """P0：软删除学员。"""
        self.student_repo.create({
            'id': 'S002',
            'name': '李四',
            'cls': '一班',
            'enroll_date': '2026-09-01',
        })
        assert self.student_repo.soft_delete('S002') is True
        stu = self.student_repo.get('S002')
        assert stu['status'] == 'deleted'

    def test_03_p1_full_report_insert(self):
        """P1：整包报告入库，验证 student_bound=1。"""
        payload = _build_full_report(
            student_id='S001', device_id='DEV01',
            step_durations=[8000, 15000, 9000, 12000], score=75.0,
        )
        report_id, is_dup = self.report_repo.insert_full_report(payload)
        assert is_dup is False
        assert report_id is not None

        detail = self.report_repo.get_report_detail(report_id)
        assert detail is not None
        assert detail['report']['student_id'] == 'S001'
        assert detail['report']['student_bound'] == 1
        assert detail['report']['total_score'] == 75.0

    def test_04_p1_multiple_reports_for_trend(self):
        """P1：为同一学员插入多份报告，验证 P2 学员累计统计趋势。"""
        for score in (82.0, 90.0):
            payload = _build_full_report(
                student_id='S001', device_id='DEV01',
                step_durations=[7000, 13000, 8500, 11000], score=score,
            )
            # 每份报告 start_ms 需唯一以保证 report_id 不重复
            payload['round']['start_ms'] = int(time.time() * 1000) + int(score)
            rid, is_dup = self.report_repo.insert_full_report(payload)
            assert is_dup is False
            assert rid is not None

    def test_05_p1_report_without_student(self):
        """P1：未绑定学员的报告入库，验证 student_bound=0。"""
        payload = _build_full_report(
            student_id=None, device_id='DEV02',
            step_durations=[8000, 15000, 9000, 12000], score=65.0,
        )
        report_id, is_dup = self.report_repo.insert_full_report(payload)
        assert is_dup is False
        detail = self.report_repo.get_report_detail(report_id)
        assert detail['report']['student_bound'] == 0

    def test_06_p2_step_duration_stats(self):
        """P2：步骤用时分布统计。"""
        stats = self.analysis_repo.get_step_duration_stats({})
        assert 'steps' in stats
        assert len(stats['steps']) > 0

    def test_07_p2_student_cumulative_stats(self):
        """P2：学员累计统计（考试次数/平均得分/完成率趋势）。"""
        stats = self.analysis_repo.get_student_cumulative_stats('S001')
        assert stats['student_id'] == 'S001'
        assert stats['exam_count'] >= 3
        assert stats['avg_score'] >= 75.0
        assert 'scores' in stats
        assert len(stats['scores']) >= 3

    def test_08_p2_diagnosis_bottleneck(self):
        """P2：诊断规则 - 全班性瓶颈（avg > SOP×1.5）。

        用独立班级 '诊断A班'，插入 5 份 step_1=18000ms 的报告，
        使该班 step_1 均值 > SOP 10000×1.5=15000ms，稳定触发瓶颈。
        独立班级避免与其他测试累积数据相互稀释。
        """
        base_ms = int(time.time() * 1000) + 7777
        for i in range(5):
            payload = _build_full_report(
                student_id=f'DA{i}', device_id='DEV_DA',
                step_durations=[5000, 18000, 7000, 9000], score=70.0,
            )
            payload['student']['cls'] = '诊断A班'
            payload['round']['start_ms'] = base_ms + i * 1000
            self.report_repo.insert_full_report(payload)

        result = self.diagnosis_engine.diagnose_all(cls='诊断A班')
        bottlenecks = [d for d in result if d['diagnosis_type'] == 'bottleneck']
        assert len(bottlenecks) >= 1

    def test_09_p2_diagnosis_persistent_error(self):
        """P2：诊断规则 - 顽固性错误（遗漏率 > 30%）。

        用独立班级 '诊断B班'，插入 10 份报告，其中 step_2 被遗漏 5 次（50% > 30%），
        独立班级避免累积数据稀释遗漏率。
        """
        base_ms = int(time.time() * 1000) + 9000
        for i in range(10):
            payload = _build_full_report(
                student_id=f'DB{i}', device_id='DEV_DB',
                step_durations=[6000, 8000, 7000, 9000], score=80.0,
                omission_steps=[2] if i < 5 else [],
            )
            payload['student']['cls'] = '诊断B班'
            payload['round']['start_ms'] = base_ms + i * 1000
            self.report_repo.insert_full_report(payload)

        result = self.diagnosis_engine.diagnose_all(cls='诊断B班')
        omission_diagnoses = [d for d in result if d['diagnosis_type'] == 'persistent_error']
        assert len(omission_diagnoses) >= 1

    def test_10_p3_today_summary(self):
        """P3：今日概览（考试人数/平均得分/通过率/待辅导学员数）。"""
        summary = self.dashboard_repo.get_today_summary(pass_threshold=60.0)
        assert 'exam_count' in summary
        assert 'avg_score' in summary
        assert 'pass_rate' in summary
        assert 'pending_tutor_count' in summary
        # 今天插入过多份报告，至少应有报告
        assert summary['exam_count'] >= 1

    def test_11_p3_top_error_points(self):
        """P3：高频错误点 TOP5。"""
        points = self.dashboard_repo.get_top_error_points(limit=5)
        assert isinstance(points, list)
        assert len(points) <= 5

    def test_12_p3_attention_students(self):
        """P3：需关注的学员（退步预警/波动较大/薄弱突出）。"""
        students = self.dashboard_repo.get_attention_students(limit=20)
        assert isinstance(students, list)
        assert len(students) >= 0

    def test_13_p3_improvement_validation(self):
        """P3：教学改进验证（两时间窗对比）。"""
        now_ms = int(time.time() * 1000)
        day_ms = 86400000
        result = self.dashboard_repo.get_improvement_validation(
            cls='一班',
            before_range={'date_start': now_ms - day_ms, 'date_end': now_ms},
            after_range={'date_start': now_ms - day_ms, 'date_end': now_ms},
        )
        assert isinstance(result, dict)
        assert 'trend' in result
        assert result['trend'] in ('improved', 'declined', 'mixed', 'no_data')

    def test_14_p0_p1_student_report_association(self):
        """P0+P1 联动：学员详情页历史考试记录挂载点（验证报告可按 student_id 检索）。"""
        reports = self.report_repo.list_reports(
            {'student_id': 'S001'}, page=1, page_size=10,
        )
        assert reports['total'] >= 3
        assert len(reports['list']) >= 3

    def test_15_e2e_full_pipeline(self):
        """完整闭环：P0 建档 → P1 上报 → P2 统计 → P3 看板。"""
        # 1. P0 创建新学员
        self.student_repo.create({
            'id': 'S003',
            'name': '王五',
            'cls': '二班',
            'enroll_date': '2026-09-01',
        })

        # 2. P1 该学员上报报告
        payload = _build_full_report(
            student_id='S003', device_id='DEV03',
            step_durations=[9000, 14000, 11000, 8000], score=78.0,
        )
        payload['round']['start_ms'] = int(time.time() * 1000) + 33333
        report_id, is_dup = self.report_repo.insert_full_report(payload)
        assert is_dup is False
        assert report_id is not None

        # 3. P2 统计分析
        step_stats = self.analysis_repo.get_step_duration_stats({})
        assert len(step_stats['steps']) > 0

        student_stats = self.analysis_repo.get_student_cumulative_stats('S003')
        assert student_stats['exam_count'] >= 1

        # 4. P3 教学看板
        summary = self.dashboard_repo.get_today_summary()
        assert summary['exam_count'] >= 1

        # 验证完整数据流闭环
        assert self.student_repo.get('S003') is not None
        assert self.report_repo.get_report_detail(report_id)['report']['student_bound'] == 1
