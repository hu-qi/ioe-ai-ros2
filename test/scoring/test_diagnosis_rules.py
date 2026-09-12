#!/usr/bin/env python3
"""
test/scoring/test_diagnosis_rules.py — P2 诊断规则 YAML 化测试

覆盖（doc/02 §5.1、doc/03 §二）:
  - 规则加载: 工序分组 / common 回退 / 文件缺失降级 / 非法项过滤
  - 回退链: 工序专属优先 → common → 内置默认
  - 引擎规则对象驱动: threshold/enabled/suggestion 生效
  - substep_index 定向规则
  - 热重载幂等
  - interval / stddev 新维度
"""

import os
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app_mgr_object.components.web.diagnosis_rules_loader import (  # noqa: E402
    load_diagnosis_rules, DiagnosisRule,
)
from app_mgr_object.components.web.diagnosis_engine import DiagnosisEngine  # noqa: E402


class TestRuleLoading(unittest.TestCase):
    def test_load_real_yaml(self):
        rules = load_diagnosis_rules()
        self.assertIn("拆解", rules["processes"])
        self.assertIn("组装", rules["processes"])
        for rt in ("bottleneck", "error", "sequence", "interval", "stddev"):
            self.assertIn(rt, rules["processes"]["拆解"], rt)
            self.assertIn(rt, rules["common"], rt)
        self.assertIn("regression", rules["common"])

    def test_missing_file_builtin_fallback(self):
        rules = load_diagnosis_rules("/nonexistent/diagnosis.yaml")
        self.assertEqual(rules["processes"], {})
        for rt in ("bottleneck", "error", "sequence", "interval", "stddev", "regression"):
            self.assertIn(rt, rules["common"])
            self.assertEqual(rules["common"][rt].source, "builtin")

    def test_invalid_rules_skipped(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "d.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump({
                "processes": [{"name": "X", "rules": [
                    {"type": "unknown_type", "threshold": 1},      # 非法类型 → 丢弃
                    {"type": "bottleneck", "threshold": "abc"},    # 非法阈值 → 丢弃
                    {"type": "error", "threshold": 0.4, "enabled": True},
                ]}],
            }, f, allow_unicode=True)
        rules = load_diagnosis_rules(path)
        self.assertEqual(set(rules["processes"]["X"].keys()), {"error"})
        self.assertEqual(rules["processes"]["X"]["error"].threshold, 0.4)


class TestFallbackChain(unittest.TestCase):
    def setUp(self):
        self.engine = DiagnosisEngine(None, {}, {}, rules=load_diagnosis_rules())

    def test_process_specific_wins(self):
        r = self.engine._resolve_rule("组装", "bottleneck")
        self.assertEqual(r.threshold, 1.3)
        self.assertEqual(r.source, "组装")

    def test_common_fallback(self):
        r = self.engine._resolve_rule("未知工序", "error")
        self.assertEqual(r.threshold, 0.30)
        self.assertEqual(r.source, "common")

    def test_disabled_rule_falls_through(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "d.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump({
                "processes": [{"name": "X", "rules": [
                    {"type": "error", "threshold": 0.9, "enabled": False}]}],
                "common_rules": [{"type": "error", "threshold": 0.30}],
            }, f, allow_unicode=True)
        eng = DiagnosisEngine(None, {}, {}, rules=load_diagnosis_rules(path))
        r = eng._resolve_rule("X", "error")
        self.assertEqual(r.source, "common")


class TestEngineRuleDriven(unittest.TestCase):
    def _engine_with_data(self, rules):
        from app_mgr_object.components.web.analysis_repo import AnalysisRepo
        from app_mgr_object.components.web.report_repo import ReportRepo
        import time

        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "t.db")
        ReportRepo(db).init_schema()
        repo = AnalysisRepo(db)
        repo.init_schema()

        now = int(time.time() * 1000)
        conn = repo._connect()
        for i in range(3):
            rid = f"R{i}"
            conn.execute(
                "INSERT INTO reports (report_id, device_id, student_cls, process_name, is_stub,"
                " start_ms, ts_upload_ms, created_at) VALUES (?,?,?,?,0,?,?,?)",
                (rid, "dev01", "一班", "拆解", 1000, now, now))
            # 步骤1: 平均 20000ms, 间隔 8000ms
            conn.execute(
                "INSERT INTO report_steps (report_id, idx, name, state, start_ms, end_ms,"
                " duration_ms, interval_ms) VALUES (?,?,?,2,?,?,?,?)",
                (rid, 1, "步骤1", 100, 9000, 20000.0, 8000.0))
        conn.commit()
        conn.close()
        return DiagnosisEngine(repo, {}, {"拆解": {1: 12000.0}}, rules=rules)

    def test_yaml_suggestion_used(self):
        eng = self._engine_with_data(load_diagnosis_rules())
        results = eng.diagnose_class_bottleneck(process_name="拆解")
        self.assertTrue(results)
        self.assertEqual(results[0]["advice_text"], "拆解该步骤平均用时过长，建议下次课重点讲解")

    def test_process_filter_scopes_results(self):
        eng = self._engine_with_data(load_diagnosis_rules())
        results = eng.diagnose_class_bottleneck(process_name="组装")  # 组装无数据
        self.assertEqual(results, [])

    def test_substep_index_targeting(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "d.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump({
                "common_rules": [{"type": "bottleneck", "substep_index": 2, "threshold": 1.5}],
            }, f)
        eng = self._engine_with_data(load_diagnosis_rules(path))
        # 规则只针对步骤2，数据只有步骤1 → 不触发
        self.assertEqual(eng.diagnose_class_bottleneck(process_name="拆解"), [])

    def test_interval_dimension(self):
        eng = self._engine_with_data(load_diagnosis_rules())
        results = eng.diagnose_interval(process_name="拆解")
        # 间隔 8000 > 5000 → 触发
        self.assertTrue(any(r["target_id"] == "step_1" for r in results))

    def test_reload_idempotent(self):
        eng = self._engine_with_data(load_diagnosis_rules())
        t1 = eng._rules["processes"]["拆解"]["bottleneck"].threshold
        eng.reload_rules()
        t2 = eng._rules["processes"]["拆解"]["bottleneck"].threshold
        self.assertEqual(t1, t2)

    def test_diagnose_all_includes_new_dimensions(self):
        eng = self._engine_with_data(load_diagnosis_rules())
        results = eng.diagnose_all(process_name="拆解")
        types = {r["diagnosis_type"] for r in results}
        self.assertIn("bottleneck", types)
        self.assertIn("interval", types)
        # 输出契约向后兼容
        self.assertNotIn("error", types)          # 旧名 persistent_error
        self.assertNotIn("sequence", types)       # 旧名 sequence_chaos


if __name__ == "__main__":
    unittest.main()
