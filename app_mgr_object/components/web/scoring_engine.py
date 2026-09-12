#!/usr/bin/env python3
"""
scoring_engine.py — 单轮评分引擎（P1，doc/01 §八 / doc/02 §4.1 / doc/03 §2.5）

评分模型（纯四系数，得分直接累加——规避 02 §4.1 双重计权矛盾，见评估报告决策 2）:
  子步骤得分 = max_score × 用时系数 × 正确性系数 × 顺序系数
    用时系数   = min(1.0, std_duration_ms / actual_duration_ms)
    正确性系数 = state: 0未执行=0.0 / 1进行中=0.5 / 2完成=1.0 / 3中断=0.5
    顺序系数   = 顺序正确=1.0 / 顺序错误=0.7
  超时子步骤再乘 timeout_penalty
  整轮: 总分 - 未执行数×unexecuted_deduct - 重复次数×repeat_deduct
        finish_reason=timeout 时总分×timeout_total_multiplier
  等级: grade_levels 从高到低匹配 min

规则来源: config/scoring_rules.yaml（完全 YAML 驱动，见评估报告决策 3）。
按工序回退链: processes[name].substeps[idx] → default → 跳过该子步骤。

纯函数设计: 引擎不直接读写数据库，输入 round dict + 规则，输出评分明细，
由调用方（scoring_plugin）负责入库与触发。
"""

import os
from typing import Dict, List, Optional, Any

import yaml

# state → 正确性系数（doc/38 v1.1: 0未执行 1进行中 2完成 3中断）
ACC_FACTOR = {0: 0.0, 1: 0.5, 2: 1.0, 3: 0.5}

SEQ_OK = 1.0
SEQ_ERROR = 0.7

# 轮次超时判定双口径兼容：
#   平台库内为字符串（completed/manual/timeout/reset，reports_schema.sql）；
#   doc/02 §2.1 设计为整数（3=超时），端侧若按整数上报同样命中。
FINISH_REASON_TIMEOUT = ("timeout", 3, "3")

DEFAULT_RULES_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "config", "scoring_rules.yaml"
)


def _candidate_rules_paths() -> List[str]:
    """候选配置路径：仓库根 config/（运行时 CWD）与包相对路径（app_mgr_object/config/）。"""
    pkg_rel = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "config", "scoring_rules.yaml"
    )
    return [os.path.abspath(os.path.join("config", "scoring_rules.yaml")), os.path.abspath(pkg_rel)]


def load_scoring_rules(path: str = None) -> Dict[str, Any]:
    """加载评分规则 YAML。文件缺失/损坏时返回内置最小默认值（不抛异常，降级可用）。"""
    candidates = [path] if path else _candidate_rules_paths()
    data = {}
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            break
        except (IOError, yaml.YAMLError):
            continue

    default = data.get("default") or {}
    return {
        "version": data.get("version", "0"),
        "default": {
            "max_score": float(default.get("max_score", 10.0)),
            "timeout_penalty": float(default.get("timeout_penalty", 0.5)),
            "grade_levels": default.get("grade_levels") or [
                {"min": 90, "level": "优秀"},
                {"min": 75, "level": "良好"},
                {"min": 60, "level": "合格"},
                {"min": 0, "level": "不合格"},
            ],
        },
        "global_penalties": {
            "unexecuted_deduct": float((data.get("global_penalties") or {}).get("unexecuted_deduct", 2)),
            "repeat_deduct": float((data.get("global_penalties") or {}).get("repeat_deduct", 1)),
            "timeout_total_multiplier": float((data.get("global_penalties") or {}).get("timeout_total_multiplier", 0.9)),
        },
        "processes": {
            p.get("name", ""): {int(s["index"]): s for s in (p.get("substeps") or []) if s.get("index") is not None}
            for p in (data.get("processes") or [])
        },
    }


class ScoringEngine:
    """单轮评分引擎：规则驱动的四系数评分。"""

    def __init__(self, rules: Dict[str, Any]):
        self._rules = rules

    def reload(self, rules: Dict[str, Any]) -> None:
        self._rules = rules

    # ------------------------------------------------------------------
    # 规则解析：工序专属 → 通用 default
    # ------------------------------------------------------------------
    def _resolve_substep_rule(self, process_name: str, substep_index: int) -> Dict[str, Any]:
        """返回该子步骤生效的规则 dict（std_duration_ms/max_score），无规则返回 {}。"""
        proc = self._rules.get("processes", {}).get(process_name or "", {})
        rule = proc.get(substep_index)
        if rule:
            return rule
        default = self._rules.get("default", {})
        return {
            "std_duration_ms": None,   # 无标准用时 → 用时系数按 1.0（不扣）
            "max_score": default.get("max_score", 10.0),
        }

    # ------------------------------------------------------------------
    # 顺序错误检测：events 中各子步骤首次 START 的先后与 idx 顺序比对
    # ------------------------------------------------------------------
    @staticmethod
    def detect_sequence_errors(events: List[dict]) -> set:
        """返回顺序错误的子步骤全局序号集合（1..M）。

        事件口径（doc/45 §4）: kind=0 START, ts 为相对 round_start_ms 偏移。
        判定: 若子步骤 A 的首个 START 晚于子步骤 B（B 的 idx 更大）的首个 START，
        则 A 顺序错误（出现了先做后面步骤再做前面步骤的情况）。
        """
        first_start: Dict[int, int] = {}
        for ev in events or []:
            if ev.get("kind") != 0:
                continue
            sub = ev.get("sub")
            ts = ev.get("ts")
            if sub is None or ts is None:
                continue
            sub = int(sub)
            if sub not in first_start or ts < first_start[sub]:
                first_start[sub] = int(ts)

        ordered = sorted(first_start.items(), key=lambda kv: kv[1])
        errors: set = set()
        for pos, (sub, _ts) in enumerate(ordered):
            # 前面出现过 idx 更大的子步骤先开始 → 本子步骤顺序错乱
            if any(prev_sub > sub for prev_sub, _ in ordered[:pos]):
                errors.add(sub)
        return errors

    # ------------------------------------------------------------------
    # 单子步骤评分
    # ------------------------------------------------------------------
    def score_substep(self, sub: dict, rule: dict, sequence_error: bool) -> Optional[dict]:
        """计算单个子步骤得分。返回 {score, factors:{...}}；无规则/无用时返回 None。"""
        state = sub.get("state")
        if state is None:
            return None
        state = int(state)
        if state == 0:
            # 未执行子步骤不产生得分，走整轮 unexecuted_deduct 扣分
            return {"score": 0.0, "unexecuted": True, "factors": {"acc": 0.0}}

        max_score = float(rule.get("max_score", self._rules["default"]["max_score"]))
        duration = sub.get("duration_ms") or sub.get("total_duration_ms")
        std = rule.get("std_duration_ms")

        time_factor = 1.0
        if std and duration:
            time_factor = min(1.0, float(std) / max(float(duration), 1.0))

        acc_factor = ACC_FACTOR.get(state, 0.0)
        seq_factor = SEQ_ERROR if sequence_error else SEQ_OK

        score = max_score * time_factor * acc_factor * seq_factor
        if sub.get("timeout"):
            score *= float(self._rules["default"].get("timeout_penalty", 0.5))

        return {
            "score": round(score, 2),
            "unexecuted": False,
            "factors": {
                "time": round(time_factor, 4),
                "acc": acc_factor,
                "seq": seq_factor,
                "timeout": bool(sub.get("timeout")),
            },
        }

    # ------------------------------------------------------------------
    # 整轮评分
    # ------------------------------------------------------------------
    def score_report(self, round_data: dict) -> dict:
        """对整包 round 评分。返回:
        {
          "total_score": float, "grade_level": str,
          "substep_scores": {idx: score},
          "details": {idx: {score, factors}},
          "deductions": {unexecuted, repeat, timeout_multiplier_applied}
        }
        """
        process_name = round_data.get("process_name") or ""
        substeps = round_data.get("substeps") or []
        events = round_data.get("events") or []
        seq_errors = self.detect_sequence_errors(events)

        penalties = self._rules["global_penalties"]
        total = 0.0
        sub_scores: Dict[int, float] = {}
        details: Dict[int, dict] = {}
        unexecuted_count = 0
        repeat_count = 0

        for sub in substeps:
            idx = sub.get("idx") or sub.get("index")
            if idx is None:
                continue
            idx = int(idx)
            if int(sub.get("state") or 0) == 0:
                unexecuted_count += 1
            cnt = int(sub.get("count") or 1)
            if cnt > 1:
                repeat_count += cnt - 1

            rule = self._resolve_substep_rule(process_name, idx)
            result = self.score_substep(sub, rule, idx in seq_errors)
            if result is None:
                continue
            sub_scores[idx] = result["score"]
            details[idx] = result
            total += result["score"]

        unexecuted_deduct = unexecuted_count * penalties["unexecuted_deduct"]
        repeat_deduct = repeat_count * penalties["repeat_deduct"]
        total = total - unexecuted_deduct - repeat_deduct

        timeout_applied = False
        if round_data.get("finish_reason") in FINISH_REASON_TIMEOUT:
            total *= penalties["timeout_total_multiplier"]
            timeout_applied = True

        total = max(0.0, round(total, 2))
        return {
            "total_score": total,
            "grade_level": self.get_grade_level(total),
            "substep_scores": sub_scores,
            "details": details,
            "deductions": {
                "unexecuted_count": unexecuted_count,
                "unexecuted_deduct": unexecuted_deduct,
                "repeat_count": repeat_count,
                "repeat_deduct": repeat_deduct,
                "timeout_multiplier_applied": timeout_applied,
            },
        }

    # ------------------------------------------------------------------
    # 等级划分
    # ------------------------------------------------------------------
    def get_grade_level(self, total_score: float) -> str:
        for lv in self._rules["default"].get("grade_levels", []):
            try:
                if total_score >= float(lv.get("min", 0)):
                    return lv.get("level", "不合格")
            except (TypeError, ValueError):
                continue
        return "不合格"
