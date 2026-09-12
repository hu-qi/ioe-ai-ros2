#!/usr/bin/env python3
"""
diagnosis_engine.py — 诊断规则引擎（P2 规则对象驱动改造）

工程基线: app_mgr_object-0.2.1+
关联文档: doc/71 §4.3（规则来源基线）、doc/02 §4.2/§5.1、doc/03 §二（YAML 配置驱动）

六类诊断规则（五维 + 退步预警）：
  1. bottleneck  全班性瓶颈：步骤平均用时 > SOP标准×threshold
  2. error       顽固性错误：遗漏率 > threshold
  3. sequence    顺序混乱：顺序错误率 > threshold（简化算法：含超时报告占比）
  4. interval    步骤间隔：与下一步平均间隔 > threshold(ms)
  5. stddev      用时标准差：标准差 > 平均值×threshold
  6. regression  学员退步预警：最近N次平均分 < 前M次×threshold

规则来源（P2）: config/diagnosis_rules.yaml（diagnosis_rules_loader 加载），
回退链: 工序专属 → common 通用 → 内置默认。
向后兼容: 旧签名 DiagnosisEngine(repo, thresholds, sop_standards) 仍可用——
未传 rules 时自动加载 YAML；规则缺失时回退 thresholds 旧配置。

每条诊断结果同时输出：
  - metric_value（判断依据数值）
  - threshold_value（阈值）
  - advice_text（教官行动建议文本）
"""

from typing import Dict, Any, List, Optional

from .analysis_repo import AnalysisRepo
from .diagnosis_rules_loader import load_diagnosis_rules, DiagnosisRule


class DiagnosisEngine:
    """诊断规则引擎：规则对象驱动的六类阈值规则计算"""

    # 默认建议文本（对齐 doc/71 §4.3；YAML suggestion 缺失时使用）
    ADVICE_BOTTLENECK = "该步骤需在下次课重点讲解"
    ADVICE_PERSISTENT_ERROR = "需增加该步骤的专项训练"
    ADVICE_SEQUENCE_CHAOS = "需强调步骤间的依赖关系"
    ADVICE_REGRESSION = "建议安排个别辅导"

    DEFAULT_ADVICE = {
        "bottleneck": ADVICE_BOTTLENECK,
        "error": ADVICE_PERSISTENT_ERROR,
        "sequence": ADVICE_SEQUENCE_CHAOS,
        "interval": "该步骤与下一步衔接卡壳，需明确操作逻辑",
        "stddev": "该步骤学员用时差异大，建议分享经验统一手法",
        "regression": ADVICE_REGRESSION,
    }

    def __init__(self, repo: AnalysisRepo, thresholds: dict,
                 sop_standards: dict, logger=None, rules: dict = None):
        """
        Args:
            repo: AnalysisRepo 实例
            thresholds: 旧版诊断阈值配置（向后兼容；规则缺失时回退）
            sop_standards: {process_type: {step_idx: standard_duration_ms}}
            logger: 日志器
            rules: 规则映射（load_diagnosis_rules 产出）；None 时自动加载 YAML
        """
        self._repo = repo
        self._thresholds = thresholds
        self._sop_standards = sop_standards or {}
        self._logger = logger
        self._rules = rules if rules is not None else load_diagnosis_rules()

    def reload_rules(self, rules: dict = None) -> None:
        """热重载规则（POST /api/v1/config/reload 调用）。None=从 YAML 重新加载。"""
        self._rules = rules if rules is not None else load_diagnosis_rules()

    # ------------------------------------------------------------------
    # 规则解析：工序专属 → common 通用 → None（回退旧 thresholds 由调用方处理）
    # ------------------------------------------------------------------
    def _resolve_rule(self, process_name: str, rule_type: str) -> Optional[DiagnosisRule]:
        processes = self._rules.get("processes", {})
        proc = processes.get(process_name or "", {})
        rule = proc.get(rule_type)
        if rule and rule.enabled:
            return rule
        common = self._rules.get("common", {}).get(rule_type)
        if common and common.enabled:
            return common
        return None

    @staticmethod
    def _apply_substep_filter(rule: DiagnosisRule, step_idx: int) -> bool:
        """规则是否作用于该步骤（substep_index=None 表示全部步骤）。"""
        return rule.substep_index is None or rule.substep_index == step_idx

    # ------------------------------------------------------------------
    # 1. 全班性瓶颈诊断
    # ------------------------------------------------------------------
    def diagnose_class_bottleneck(self, cls: str = '',
                                  date_range: Optional[dict] = None,
                                  process_name: str = '') -> List[dict]:
        """全班性瓶颈：某步骤全班平均用时 > SOP标准×threshold"""
        filters = self._build_filters(cls, date_range, process_name)

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        results: List[dict] = []
        for idx in step_indices:
            rule = self._resolve_rule(process_name, "bottleneck")
            if rule is None:
                multiplier = self._thresholds.get("bottleneck_multiplier", 1.5)
                rule = DiagnosisRule("bottleneck", multiplier,
                                     suggestion=self.ADVICE_BOTTLENECK, source="legacy")
            if not self._apply_substep_filter(rule, idx):
                continue

            avg_ms = self._repo.get_step_avg_duration(idx, filters)
            if avg_ms <= 0:
                continue

            # 查 SOP 标准用时
            standard_ms = self._get_sop_standard(idx)
            if standard_ms is None:
                # 降级：无 SOP 标准时跳过瓶颈诊断（doc/71 §6 降级策略）
                continue

            threshold = standard_ms * rule.threshold
            if avg_ms > threshold:
                results.append({
                    "diagnosis_type": "bottleneck",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "process_name": process_name,
                    "metric_value": avg_ms,
                    "threshold_value": threshold,
                    "advice_text": rule.suggestion or self.ADVICE_BOTTLENECK,
                    "metric_label": f"全班平均用时 {avg_ms:.0f}ms > SOP标准 {standard_ms:.0f}ms × {rule.threshold} = {threshold:.0f}ms"
                })

        return results

    # ------------------------------------------------------------------
    # 2. 顽固性错误诊断
    # ------------------------------------------------------------------
    def diagnose_persistent_error(self, cls: str = '',
                                  date_range: Optional[dict] = None,
                                  process_name: str = '') -> List[dict]:
        """顽固性错误：某步骤遗漏率 > threshold
        遗漏率 = COUNT(report WHERE step.state IN (0,3)) / COUNT(report)"""
        filters = self._build_filters(cls, date_range, process_name)

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        results: List[dict] = []
        for idx in step_indices:
            rule = self._resolve_rule(process_name, "error")
            if rule is None:
                rule = DiagnosisRule("error", self._thresholds.get("persistent_error_rate", 0.30),
                                     suggestion=self.ADVICE_PERSISTENT_ERROR, source="legacy")
            if not self._apply_substep_filter(rule, idx):
                continue

            omission_rate = self._repo.get_step_omission_rate(idx, filters)
            if omission_rate > rule.threshold:
                results.append({
                    "diagnosis_type": "persistent_error",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "process_name": process_name,
                    "metric_value": round(omission_rate, 4),
                    "threshold_value": rule.threshold,
                    "advice_text": rule.suggestion or self.ADVICE_PERSISTENT_ERROR,
                    "metric_label": f"步骤{idx}遗漏率 {omission_rate:.1%} > 阈值 {rule.threshold:.0%}"
                })

        return results

    # ------------------------------------------------------------------
    # 3. 顺序混乱诊断
    # ------------------------------------------------------------------
    def diagnose_sequence_chaos(self, cls: str = '',
                                date_range: Optional[dict] = None,
                                process_name: str = '') -> List[dict]:
        """顺序混乱：某步骤顺序错误率 > threshold

        顺序错误率（与 ScoringEngine.detect_sequence_errors 同源）：
        基于评分回写的 report_substeps.sequence_error 标记统计，
        顺序错误率 = 含顺序错误子步骤的报告数 / 总报告数。
        """
        filters = self._build_filters(cls, date_range, process_name)

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        results: List[dict] = []
        for idx in step_indices:
            rule = self._resolve_rule(process_name, "sequence")
            if rule is None:
                rule = DiagnosisRule("sequence", self._thresholds.get("sequence_chaos_rate", 0.20),
                                     suggestion=self.ADVICE_SEQUENCE_CHAOS, source="legacy")
            if not self._apply_substep_filter(rule, idx):
                continue

            seq_err_rate = self._repo.get_step_sequence_error_rate(idx, filters)
            if seq_err_rate > rule.threshold:
                results.append({
                    "diagnosis_type": "sequence_chaos",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "process_name": process_name,
                    "metric_value": round(seq_err_rate, 4),
                    "threshold_value": rule.threshold,
                    "advice_text": rule.suggestion or self.ADVICE_SEQUENCE_CHAOS,
                    "metric_label": f"步骤{idx}顺序错误率 {seq_err_rate:.1%} > 阈值 {rule.threshold:.0%}"
                })

        return results

    # ------------------------------------------------------------------
    # 4. 步骤间隔诊断（P2 新增第 4 维）
    # ------------------------------------------------------------------
    def diagnose_interval(self, cls: str = '',
                          date_range: Optional[dict] = None,
                          process_name: str = '') -> List[dict]:
        """步骤间隔：与下一步平均间隔 > threshold(ms) → 衔接卡壳"""
        filters = self._build_filters(cls, date_range, process_name)

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        results: List[dict] = []
        for idx in step_indices:
            rule = self._resolve_rule(process_name, "interval")
            if rule is None:
                continue
            if not self._apply_substep_filter(rule, idx):
                continue

            avg_interval = self._repo.get_step_interval_stats(idx, filters)
            if avg_interval <= 0:
                continue

            if avg_interval > rule.threshold:
                results.append({
                    "diagnosis_type": "interval",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "process_name": process_name,
                    "metric_value": avg_interval,
                    "threshold_value": rule.threshold,
                    "advice_text": rule.suggestion or self.DEFAULT_ADVICE["interval"],
                    "metric_label": f"步骤{idx}平均间隔 {avg_interval:.0f}ms > 阈值 {rule.threshold:.0f}ms"
                })

        return results

    # ------------------------------------------------------------------
    # 5. 用时标准差诊断（P2 新增第 5 维）
    # ------------------------------------------------------------------
    def diagnose_stddev(self, cls: str = '',
                        date_range: Optional[dict] = None,
                        process_name: str = '') -> List[dict]:
        """用时标准差：步骤标准差 > 平均值×threshold → 学员差异大"""
        filters = self._build_filters(cls, date_range, process_name)

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        results: List[dict] = []
        for idx in step_indices:
            rule = self._resolve_rule(process_name, "stddev")
            if rule is None:
                continue
            if not self._apply_substep_filter(rule, idx):
                continue

            stats = self._repo.get_step_duration_stddev_stats(idx, filters)
            avg_ms, stddev_ms = stats.get("avg_ms", 0.0), stats.get("stddev_ms", 0.0)
            if avg_ms <= 0 or stddev_ms <= 0:
                continue

            threshold_value = avg_ms * rule.threshold
            if stddev_ms > threshold_value:
                results.append({
                    "diagnosis_type": "stddev",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "process_name": process_name,
                    "metric_value": stddev_ms,
                    "threshold_value": round(threshold_value, 1),
                    "advice_text": rule.suggestion or self.DEFAULT_ADVICE["stddev"],
                    "metric_label": f"步骤{idx}用时标准差 {stddev_ms:.0f}ms > 平均值 {avg_ms:.0f}ms × {rule.threshold}"
                })

        return results

    # ------------------------------------------------------------------
    # 6. 学员退步预警诊断
    # ------------------------------------------------------------------
    def diagnose_student_regression(self, student_id: str) -> List[dict]:
        """学员退步预警：最近N次平均分 < 前M次×threshold。需至少 N+M 次考试记录。"""
        rule = self._resolve_rule("", "regression")
        if rule is None:
            window_recent = int(self._thresholds.get("regression_window_recent", 3))
            window_history = int(self._thresholds.get("regression_window_history", 5))
            rule = DiagnosisRule("regression", self._thresholds.get("regression_threshold", 0.85),
                                 suggestion=self.ADVICE_REGRESSION,
                                 window_recent=window_recent, window_history=window_history,
                                 source="legacy")

        window_recent = rule.window_recent
        window_history = rule.window_history

        # 取足够多的成绩记录（window_recent + window_history）
        trend = self._repo.get_student_score_trend(
            student_id, window=window_recent + window_history
        )

        if len(trend) < window_recent + window_history:
            # 数据不足，无法诊断
            return []

        # 拆分：最近 window_recent 次 vs 前 window_history 次
        recent_scores = [t["score"] for t in trend[-window_recent:] if t["score"] is not None]
        history_scores = [t["score"] for t in trend[:window_history] if t["score"] is not None]

        if len(recent_scores) < window_recent or len(history_scores) < window_history:
            return []

        avg_recent = sum(recent_scores) / len(recent_scores)
        avg_history = sum(history_scores) / len(history_scores)
        threshold_value = avg_history * rule.threshold

        results: List[dict] = []
        if avg_recent < threshold_value:
            results.append({
                "diagnosis_type": "student_regression",
                "scope": "student",
                "target_id": student_id,
                "process_name": "",
                "metric_value": round(avg_recent, 2),
                "threshold_value": round(threshold_value, 2),
                "advice_text": rule.suggestion or self.ADVICE_REGRESSION,
                "metric_label": (
                    f"最近{window_recent}次平均分 {avg_recent:.1f} < "
                    f"前{window_history}次平均分 {avg_history:.1f} × {rule.threshold} = {threshold_value:.1f}"
                )
            })

        return results

    # ------------------------------------------------------------------
    # 综合诊断入口
    # ------------------------------------------------------------------
    def diagnose_all(self, cls: str = '', student_id: str = '',
                     date_range: Optional[dict] = None,
                     process_name: str = '') -> List[dict]:
        """
        综合诊断：执行所有适用的诊断规则（五维 + 退步预警）

        Args:
            cls: 班级名（全班诊断时传入）
            student_id: 学员工号（学员退步诊断时传入）
            date_range: 时间范围
            process_name: 工序名（空=全部工序）

        Returns:
            诊断结果列表
        """
        results: List[dict] = []

        # 1. 全班性瓶颈
        results.extend(self.diagnose_class_bottleneck(cls, date_range, process_name))

        # 2. 顽固性错误
        results.extend(self.diagnose_persistent_error(cls, date_range, process_name))

        # 3. 顺序混乱
        results.extend(self.diagnose_sequence_chaos(cls, date_range, process_name))

        # 4. 步骤间隔
        results.extend(self.diagnose_interval(cls, date_range, process_name))

        # 5. 用时标准差
        results.extend(self.diagnose_stddev(cls, date_range, process_name))

        # 6. 学员退步预警
        if student_id:
            results.extend(self.diagnose_student_regression(student_id))

        # P4: 诊断结果关联证据图（doc/01 §7.3，class 级结果按步骤序号取最近证据）
        self._attach_evidence(results, cls, date_range, process_name)

        return results

    def _attach_evidence(self, results: List[dict], cls: str = '',
                         date_range: Optional[dict] = None,
                         process_name: str = '') -> None:
        """为 step 级诊断结果关联该步骤的抓拍证据（最多 3 张）。"""
        filters = self._build_filters(cls, date_range, process_name)
        for r in results:
            target = r.get("target_id") or ""
            if not target.startswith("step_"):
                continue
            try:
                step_idx = int(target[len("step_"):])
            except ValueError:
                continue
            try:
                r["evidence"] = self._repo.get_evidence_for_sub(step_idx, filters, limit=3)
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"证据关联失败 step={step_idx}: {e}")
                r["evidence"] = []

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _build_filters(cls: str, date_range: Optional[dict], process_name: str = '') -> dict:
        filters: dict = {"cls": cls} if cls else {}
        if date_range:
            if date_range.get("date_start"):
                filters["date_start"] = date_range["date_start"]
            if date_range.get("date_end"):
                filters["date_end"] = date_range["date_end"]
        if process_name:
            filters["process_name"] = process_name
        return filters

    def _get_sop_standard(self, step_idx: int) -> Optional[float]:
        """
        从 sop_standards 获取步骤标准用时（毫秒）。
        sop_standards 结构: {process_type: {step_idx: standard_duration_ms}}
        本期简化：取第一个 process_type 的标准。
        """
        for _process_type, steps in self._sop_standards.items():
            if step_idx in steps:
                return float(steps[step_idx])
        return None
