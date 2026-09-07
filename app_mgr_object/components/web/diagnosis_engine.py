"""
diagnosis_engine.py — 诊断规则引擎

工程基线: app_mgr_object-0.2.1
关联文档: doc/71 统计分析插件开发方案 §4.3、需求说明.docx §3.3.3

4 类诊断阈值规则（对齐需求说明.docx §3.3.3）：
  1. 全班性瓶颈（bottleneck）：某步骤全班平均用时 > SOP标准×1.5
  2. 顽固性错误（persistent_error）：某步骤遗漏率 > 30%
  3. 顺序混乱（sequence_chaos）：某步骤顺序错误率 > 20%
  4. 学员退步预警（student_regression）：最近3次平均分 < 前5次×0.85

每条诊断结果同时输出：
  - metric_value（判断依据数值）
  - threshold_value（阈值）
  - advice_text（教官行动建议文本）
"""

import time
from typing import Dict, Any, List, Optional

from .analysis_repo import AnalysisRepo


class DiagnosisEngine:
    """诊断规则引擎：4 类阈值规则计算"""

    # 默认建议文本（对齐 doc/71 §4.3）
    ADVICE_BOTTLENECK = "该步骤需在下次课重点讲解"
    ADVICE_PERSISTENT_ERROR = "需增加该步骤的专项训练"
    ADVICE_SEQUENCE_CHAOS = "需强调步骤间的依赖关系"
    ADVICE_REGRESSION = "建议安排个别辅导"

    def __init__(self, repo: AnalysisRepo, thresholds: dict,
                 sop_standards: dict, logger=None):
        """
        Args:
            repo: AnalysisRepo 实例
            thresholds: 诊断阈值配置
            sop_standards: {process_type: {step_idx: standard_duration_ms}}
            logger: 日志器
        """
        self._repo = repo
        self._thresholds = thresholds
        self._sop_standards = sop_standards or {}
        self._logger = logger

    # ------------------------------------------------------------------
    # 1. 全班性瓶颈诊断
    # ------------------------------------------------------------------
    def diagnose_class_bottleneck(self, cls: str = '',
                                  date_range: Optional[dict] = None) -> List[dict]:
        """
        全班性瓶颈：某步骤全班平均用时 > SOP标准×1.5

        Returns:
            诊断结果列表，每条含 diagnosis_type / target_id / metric_value /
            threshold_value / advice_text
        """
        filters: dict = {"cls": cls} if cls else {}
        if date_range:
            if date_range.get("date_start"):
                filters["date_start"] = date_range["date_start"]
            if date_range.get("date_end"):
                filters["date_end"] = date_range["date_end"]

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        multiplier = self._thresholds.get("bottleneck_multiplier", 1.5)
        # 默认 SOP 标准用时（若 model JSON 未提供，用全班平均作为基线）
        sop_defaults: Dict[int, float] = {}

        results: List[dict] = []
        for idx in step_indices:
            avg_ms = self._repo.get_step_avg_duration(idx, filters)
            if avg_ms <= 0:
                continue

            # 查 SOP 标准用时
            standard_ms = self._get_sop_standard(idx)
            if standard_ms is None:
                # 降级：无 SOP 标准时跳过瓶颈诊断（doc/71 §6 降级策略）
                continue

            threshold = standard_ms * multiplier
            if avg_ms > threshold:
                results.append({
                    "diagnosis_type": "bottleneck",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "metric_value": avg_ms,
                    "threshold_value": threshold,
                    "advice_text": self.ADVICE_BOTTLENECK,
                    "metric_label": f"全班平均用时 {avg_ms:.0f}ms > SOP标准 {standard_ms:.0f}ms × {multiplier} = {threshold:.0f}ms"
                })

        return results

    # ------------------------------------------------------------------
    # 2. 顽固性错误诊断
    # ------------------------------------------------------------------
    def diagnose_persistent_error(self, cls: str = '',
                                  date_range: Optional[dict] = None) -> List[dict]:
        """
        顽固性错误：某步骤遗漏率 > 30%
        遗漏率 = COUNT(report WHERE step.state IN (0,3)) / COUNT(report)
        """
        filters: dict = {"cls": cls} if cls else {}
        if date_range:
            if date_range.get("date_start"):
                filters["date_start"] = date_range["date_start"]
            if date_range.get("date_end"):
                filters["date_end"] = date_range["date_end"]

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        threshold = self._thresholds.get("persistent_error_rate", 0.30)

        results: List[dict] = []
        for idx in step_indices:
            omission_rate = self._repo.get_step_omission_rate(idx, filters)
            if omission_rate > threshold:
                results.append({
                    "diagnosis_type": "persistent_error",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "metric_value": round(omission_rate, 4),
                    "threshold_value": threshold,
                    "advice_text": self.ADVICE_PERSISTENT_ERROR,
                    "metric_label": f"步骤{idx}遗漏率 {omission_rate:.1%} > 阈值 {threshold:.0%}"
                })

        return results

    # ------------------------------------------------------------------
    # 3. 顺序混乱诊断
    # ------------------------------------------------------------------
    def diagnose_sequence_chaos(self, cls: str = '',
                                date_range: Optional[dict] = None) -> List[dict]:
        """
        顺序混乱：某步骤顺序错误率 > 20%

        顺序错误率简化算法（doc/71 §6.2）：
        基于 report_events 表的 INTERRUPT（kind=2）事件统计，
        顺序错误率 = 含 INTERRUPT 事件的报告数 / 总报告数

        本期为简化算法，后续可细化。
        """
        filters: dict = {"cls": cls} if cls else {}
        if date_range:
            if date_range.get("date_start"):
                filters["date_start"] = date_range["date_start"]
            if date_range.get("date_end"):
                filters["date_end"] = date_range["date_end"]

        step_indices = self._repo.get_all_step_indices(filters)
        if not step_indices:
            return []

        threshold = self._thresholds.get("sequence_chaos_rate", 0.20)

        results: List[dict] = []
        for idx in step_indices:
            chaos_rate = self._repo.get_step_timeout_rate(idx, filters)
            if chaos_rate > threshold:
                results.append({
                    "diagnosis_type": "sequence_chaos",
                    "scope": "class" if cls else "all",
                    "target_id": f"step_{idx}",
                    "metric_value": round(chaos_rate, 4),
                    "threshold_value": threshold,
                    "advice_text": self.ADVICE_SEQUENCE_CHAOS,
                    "metric_label": f"步骤{idx}超时率 {chaos_rate:.1%} > 阈值 {threshold:.0%}"
                })

        return results

    # ------------------------------------------------------------------
    # 4. 学员退步预警诊断
    # ------------------------------------------------------------------
    def diagnose_student_regression(self, student_id: str) -> List[dict]:
        """
        学员退步预警：最近3次平均分 < 前5次×0.85

        需至少 8 次考试记录（3 + 5）才能判断。
        """
        window_recent = int(self._thresholds.get("regression_window_recent", 3))
        window_history = int(self._thresholds.get("regression_window_history", 5))
        regression_threshold = self._thresholds.get("regression_threshold", 0.85)

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
        threshold_value = avg_history * regression_threshold

        results: List[dict] = []
        if avg_recent < threshold_value:
            results.append({
                "diagnosis_type": "student_regression",
                "scope": "student",
                "target_id": student_id,
                "metric_value": round(avg_recent, 2),
                "threshold_value": round(threshold_value, 2),
                "advice_text": self.ADVICE_REGRESSION,
                "metric_label": (
                    f"最近{window_recent}次平均分 {avg_recent:.1f} < "
                    f"前{window_history}次平均分 {avg_history:.1f} × {regression_threshold} = {threshold_value:.1f}"
                )
            })

        return results

    # ------------------------------------------------------------------
    # 综合诊断入口
    # ------------------------------------------------------------------
    def diagnose_all(self, cls: str = '', student_id: str = '',
                     date_range: Optional[dict] = None) -> List[dict]:
        """
        综合诊断：执行所有适用的诊断规则

        Args:
            cls: 班级名（全班诊断时传入）
            student_id: 学员工号（学员退步诊断时传入）
            date_range: 时间范围

        Returns:
            诊断结果列表
        """
        results: List[dict] = []

        # 1. 全班性瓶颈
        results.extend(self.diagnose_class_bottleneck(cls, date_range))

        # 2. 顽固性错误
        results.extend(self.diagnose_persistent_error(cls, date_range))

        # 3. 顺序混乱
        results.extend(self.diagnose_sequence_chaos(cls, date_range))

        # 4. 学员退步预警
        if student_id:
            results.extend(self.diagnose_student_regression(student_id))

        return results

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
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
