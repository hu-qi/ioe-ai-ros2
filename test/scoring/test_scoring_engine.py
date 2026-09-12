#!/usr/bin/env python3
"""
test/scoring/test_scoring_engine.py — P1 单轮评分引擎单元测试

覆盖（doc/01 §八、doc/02 §4.1、doc/03 §2.5）:
  - 四系数模型: 用时系数 / 正确性系数 / 顺序系数 / 超时惩罚
  - 工序规则回退链: 工序专属 → default
  - 整轮扣分: 未执行 / 重复 / 轮次超时
  - 等级划分
  - 顺序错误检测（首个 START 时序比对）
  - 规则加载降级（文件缺失）
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app_mgr_object", "components", "web"))

from scoring_engine import ScoringEngine, load_scoring_rules  # noqa: E402


def make_engine():
    return ScoringEngine(load_scoring_rules())


class TestRuleLoading(unittest.TestCase):
    def test_load_yaml_processes(self):
        rules = load_scoring_rules()
        self.assertIn("拆解", rules["processes"])
        self.assertIn("组装", rules["processes"])
        self.assertEqual(rules["default"]["max_score"], 10.0)
        self.assertEqual(rules["global_penalties"]["timeout_total_multiplier"], 0.9)

    def test_load_missing_file_falls_back(self):
        rules = load_scoring_rules("/nonexistent/scoring.yaml")
        self.assertEqual(rules["default"]["max_score"], 10.0)
        self.assertEqual(rules["processes"], {})
        self.assertEqual(rules["default"]["grade_levels"][-1]["level"], "不合格")


class TestSubstepScoring(unittest.TestCase):
    def test_full_score_within_std(self):
        eng = make_engine()
        rule = {"std_duration_ms": 12000, "max_score": 10.0}
        r = eng.score_substep({"state": 2, "duration_ms": 10000, "timeout": 0}, rule, False)
        self.assertEqual(r["score"], 10.0)
        self.assertEqual(r["factors"]["time"], 1.0)

    def test_time_factor_proportional(self):
        eng = make_engine()
        rule = {"std_duration_ms": 8000, "max_score": 10.0}
        r = eng.score_substep({"state": 2, "duration_ms": 16000, "timeout": 0}, rule, False)
        self.assertAlmostEqual(r["score"], 5.0, places=2)
        self.assertAlmostEqual(r["factors"]["time"], 0.5, places=4)

    def test_timeout_penalty(self):
        eng = make_engine()
        rule = {"std_duration_ms": 8000, "max_score": 10.0}
        r = eng.score_substep({"state": 2, "duration_ms": 16000, "timeout": 1}, rule, False)
        # 10 * 0.5(用时) * 1.0 * 1.0 * 0.5(超时) = 2.5
        self.assertAlmostEqual(r["score"], 2.5, places=2)

    def test_sequence_error_factor(self):
        eng = make_engine()
        rule = {"std_duration_ms": 12000, "max_score": 10.0}
        r = eng.score_substep({"state": 2, "duration_ms": 6000, "timeout": 0}, rule, True)
        self.assertAlmostEqual(r["score"], 7.0, places=2)

    def test_interrupt_state_half(self):
        eng = make_engine()
        rule = {"std_duration_ms": 12000, "max_score": 10.0}
        r = eng.score_substep({"state": 3, "duration_ms": 6000, "timeout": 0}, rule, False)
        self.assertAlmostEqual(r["score"], 5.0, places=2)

    def test_unexecuted_zero(self):
        eng = make_engine()
        rule = {"std_duration_ms": 12000, "max_score": 10.0}
        r = eng.score_substep({"state": 0, "count": 0}, rule, False)
        self.assertEqual(r["score"], 0.0)
        self.assertTrue(r["unexecuted"])

    def test_no_std_rule_time_factor_neutral(self):
        """无 SOP 标准用时（回退 default 且无 std）→ 用时系数不扣分。"""
        eng = make_engine()
        r = eng.score_substep({"state": 2, "duration_ms": 999999, "timeout": 0},
                              {"std_duration_ms": None, "max_score": 10.0}, False)
        self.assertEqual(r["score"], 10.0)


class TestProcessFallback(unittest.TestCase):
    def test_process_specific_rule_wins(self):
        eng = make_engine()
        # 拆解 index=1 std=12000
        rule = eng._resolve_substep_rule("拆解", 1)
        self.assertEqual(rule["std_duration_ms"], 12000)
        # 组装 index=1 std=15000, max 12
        rule = eng._resolve_substep_rule("组装", 1)
        self.assertEqual(rule["std_duration_ms"], 15000)
        self.assertEqual(rule["max_score"], 12)

    def test_unknown_process_falls_to_default(self):
        eng = make_engine()
        rule = eng._resolve_substep_rule("未知工序", 1)
        self.assertIsNone(rule["std_duration_ms"])
        self.assertEqual(rule["max_score"], 10.0)


class TestSequenceDetection(unittest.TestCase):
    def test_in_order_no_error(self):
        eng = make_engine()
        events = [{"ts": 100, "kind": 0, "sub": 1}, {"ts": 200, "kind": 0, "sub": 2}]
        self.assertEqual(eng.detect_sequence_errors(events), set())

    def test_out_of_order_detected(self):
        eng = make_engine()
        events = [{"ts": 100, "kind": 0, "sub": 1},
                  {"ts": 200, "kind": 0, "sub": 3},
                  {"ts": 300, "kind": 0, "sub": 2}]
        errors = eng.detect_sequence_errors(events)
        self.assertIn(2, errors)
        self.assertNotIn(1, errors)
        self.assertNotIn(3, errors)

    def test_ignores_non_start_events(self):
        eng = make_engine()
        events = [{"ts": 100, "kind": 1, "sub": 3}, {"ts": 200, "kind": 0, "sub": 1}]
        self.assertEqual(eng.detect_sequence_errors(events), set())


class TestReportScoring(unittest.TestCase):
    def test_full_round_completed(self):
        eng = make_engine()
        round_data = {
            "process_name": "拆解", "finish_reason": "completed",
            "events": [{"ts": 100, "kind": 0, "sub": 1}],
            "substeps": [
                {"idx": 1, "state": 2, "duration_ms": 10000, "count": 1, "timeout": 0},
                {"idx": 2, "state": 2, "duration_ms": 8000, "count": 1, "timeout": 0},
            ],
        }
        r = eng.score_report(round_data)
        # 10 + 10 = 20, 无扣分
        self.assertAlmostEqual(r["total_score"], 20.0, places=2)
        self.assertEqual(r["grade_level"], "不合格")  # 20 < 60
        self.assertEqual(r["deductions"]["unexecuted_count"], 0)

    def test_unexecuted_and_repeat_deduction(self):
        eng = make_engine()
        round_data = {
            "process_name": "拆解", "finish_reason": "completed",
            "events": [],
            "substeps": [
                {"idx": 1, "state": 2, "duration_ms": 10000, "count": 3, "timeout": 0},
                {"idx": 2, "state": 0, "count": 0},
            ],
        }
        r = eng.score_report(round_data)
        # 10 - 2(未执行) - 2(重复 count-1=2) = 6
        self.assertAlmostEqual(r["total_score"], 6.0, places=2)
        self.assertEqual(r["deductions"]["unexecuted_deduct"], 2.0)
        self.assertEqual(r["deductions"]["repeat_deduct"], 2.0)

    def test_round_timeout_multiplier(self):
        eng = make_engine()
        round_data = {
            "process_name": "拆解", "finish_reason": "timeout",
            "events": [],
            "substeps": [{"idx": 1, "state": 2, "duration_ms": 10000, "count": 1, "timeout": 0}],
        }
        r = eng.score_report(round_data)
        # 10 * 0.9 = 9
        self.assertAlmostEqual(r["total_score"], 9.0, places=2)
        self.assertTrue(r["deductions"]["timeout_multiplier_applied"])

    def test_total_never_negative(self):
        eng = make_engine()
        round_data = {
            "process_name": "拆解", "finish_reason": "timeout",
            "events": [],
            "substeps": [{"idx": i, "state": 0, "count": 0} for i in range(1, 6)],
        }
        r = eng.score_report(round_data)
        self.assertEqual(r["total_score"], 0.0)

    def test_grade_levels(self):
        eng = make_engine()
        self.assertEqual(eng.get_grade_level(95), "优秀")
        self.assertEqual(eng.get_grade_level(80), "良好")
        self.assertEqual(eng.get_grade_level(65), "合格")
        self.assertEqual(eng.get_grade_level(30), "不合格")


if __name__ == "__main__":
    unittest.main()
