#!/usr/bin/env python3
"""
scoring_plugin.py — 单轮评分插件（P1，doc/01 §八 / doc/02 §4.1）

职责:
  1. 订阅 report.received 事件（整包入库后发布）；
  2. 调用 ScoringEngine 对该轮评分（四系数模型，规则来自 config/scoring_rules.yaml）；
  3. 通过 ReportRepo.save_scoring_result 回写 reports.total_score/grade_level
     与 report_substeps.score/sequence_error/std_duration_ms。

设计:
  - 无自有路由、无前端页面（评分结果在报告详情/看板侧展示）；
  - 评分失败不阻塞接收链路（事件回调内兜底，异常只记日志）；
  - 热重载: POST /api/v1/config/reload 时由 web 层调用 reload_rules()。
"""

import os
from typing import Dict, Any, Optional

from .base_plugin import BasePlugin
from ..components.web.report_repo import ReportRepo
from ..components.web.scoring_engine import ScoringEngine, load_scoring_rules


class ScoringPlugin(BasePlugin):
    """单轮评分插件"""

    PLUGIN_NAME = "scoring"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        self._db_path: str = self.config.get(
            "db_path",
            os.path.join(os.path.dirname(__file__), "..", "components", "web", "..", "..", "config", "app.db")
        )
        self._rules_path: str = self.config.get("scoring_rules_path") or None

        self._repo: Optional[ReportRepo] = None
        self._engine: Optional[ScoringEngine] = None

    def _configure_impl(self) -> bool:
        try:
            self._repo = ReportRepo(self._db_path, self.logger)
            self._repo.init_schema()
            self._engine = ScoringEngine(load_scoring_rules(self._rules_path))
            self.logger.info(
                f"ScoringPlugin 配置完成: db={self._db_path} "
                f"processes={list(self._engine._rules.get('processes', {}).keys())}"
            )
            return True
        except Exception as e:
            self.logger.error(f"ScoringPlugin 配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        """激活: 订阅整包到达事件"""
        try:
            if self.event_bus:
                self.event_bus.subscribe('report.received', self._on_report_received)
                self.logger.info("ScoringPlugin 已订阅 report.received")
            else:
                self.logger.warning("ScoringPlugin 无 event_bus 可用，评分钩子未挂载（非致命）")
            return True
        except Exception as e:
            self.logger.warning(f"ScoringPlugin 订阅失败（非致命）: {e}")
            return True

    def _deactivate_impl(self) -> bool:
        self.logger.info("ScoringPlugin 停用")
        return True

    def _cleanup_impl(self) -> bool:
        self.logger.info("ScoringPlugin 清理完成")
        return True

    # ------------------------------------------------------------------
    # 事件回调
    # ------------------------------------------------------------------
    def _on_report_received(self, data: dict) -> None:
        """整包入库后评分。data: {report_id, device_id, student_id, is_duplicate}"""
        try:
            report_id = data.get("report_id")
            if not report_id:
                return
            detail = self._repo.get_report_detail(report_id)
            if not detail:
                self.logger.warning(f"评分跳过: 报告不存在 {report_id}")
                return

            report = detail.get("report") or {}
            substeps = detail.get("substeps") or []
            events = detail.get("events") or []

            # 组装引擎输入（report_id 语义: R{device}_{start_ms}）
            round_data = {
                "process_name": report.get("process_name") or "",
                "finish_reason": report.get("finish_reason") or "",
                "substeps": [
                    {
                        "idx": s.get("idx"),
                        "state": s.get("state"),
                        "duration_ms": s.get("duration_ms"),
                        "total_duration_ms": s.get("total_duration_ms"),
                        "count": s.get("count"),
                        "timeout": s.get("timeout"),
                    } for s in substeps
                ],
                "events": events,
            }

            result = self._engine.score_report(round_data)
            seq_errors = self._engine.detect_sequence_errors(events)
            std_map = {
                idx: self._engine._resolve_substep_rule(
                    round_data["process_name"], idx
                ).get("std_duration_ms")
                for idx in result["substep_scores"]
            }

            ok = self._repo.save_scoring_result(
                report_id,
                result["total_score"],
                result["grade_level"],
                result["substep_scores"],
                sequence_errors=seq_errors,
                std_durations=std_map,
            )
            if ok:
                self.logger.info(
                    f"评分完成 {report_id}: total={result['total_score']} "
                    f"grade={result['grade_level']} subs={result['substep_scores']}"
                )
                # 发布评分完成事件（供看板/统计刷新）
                self._publish_event("report.scored", {
                    "report_id": report_id,
                    "device_id": data.get("device_id"),
                    "total_score": result["total_score"],
                    "grade_level": result["grade_level"],
                })
            else:
                self.logger.warning(f"评分回写未命中报告: {report_id}")
        except Exception as e:
            self.logger.error(f"评分失败 {data.get('report_id')}: {e}")

    # ------------------------------------------------------------------
    # 热重载（POST /api/v1/config/reload 调用）
    # ------------------------------------------------------------------
    def reload_rules(self) -> bool:
        try:
            self._engine.reload(load_scoring_rules(self._rules_path))
            self.logger.info("ScoringPlugin 评分规则已热重载")
            return True
        except Exception as e:
            self.logger.error(f"评分规则热重载失败: {e}")
            return False
