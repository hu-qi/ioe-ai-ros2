"""
dashboard_repo.py — 教学看板插件仓储层

工程基线: app_mgr_object-0.2.1
关联文档: doc/72 教学看板插件开发方案

职责:
  1. 今日概览（考试人数/平均得分/通过率/待辅导学员数）
  2. 高频错误点 TOP5（综合得分排序，遗漏率/超时率/顺序错误率）
  3. 需关注的学员（退步预警/波动较大/薄弱环节突出）
  4. 实时进度展示（订阅中设备的当前操作进度）
  5. 教学改进验证（对比调整前后的班级平均分/完成率变化）

跨插件读库合法性: 既有 smart_trigger_plugin 跨插件读 task_cache，
本插件跨插件读 reports / report_progress / diagnosis_results 表做看板展示，
符合既有"同库跨插件读"的惯例。
"""

import os
import json
import sqlite3
import time
from typing import Dict, Any, List, Optional


class DashboardRepo:
    """教学看板 SQLite 仓储：直连 reports/progress/diagnosis 表读聚合"""

    SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "analysis_schema.sql")

    def __init__(self, db_path: str, logger=None, schema_path: Optional[str] = None):
        self.db_path = db_path
        self.logger = logger
        if schema_path:
            self.SCHEMA_FILE = schema_path
        self._ensure_parent_dir()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _ensure_parent_dir(self):
        parent = os.path.dirname(self.db_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

    def init_schema(self) -> None:
        """
        执行建表 DDL（幂等）。
        本插件复用 P2 的 analysis_schema.sql（analysis_cache + diagnosis_results 两表）。
        若 schema 文件不存在则跳过（诊断表可能由 P2 创建）。
        """
        if not os.path.exists(self.SCHEMA_FILE):
            if self.logger:
                self.logger.info("DashboardRepo: schema 文件不存在，跳过建表")
            return
        with open(self.SCHEMA_FILE, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = self._connect()
        try:
            conn.executescript(schema_sql)
            conn.commit()
            if self.logger:
                self.logger.info("DashboardRepo: schema 初始化完成")
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    # ------------------------------------------------------------------
    # 1. 今日概览
    # ------------------------------------------------------------------
    def get_today_summary(self, pass_threshold: float = 60.0) -> dict:
        """
        今日概览：考试人数 / 平均得分 / 通过率 / 待辅导学员数
        对应 doc/72 §3.1

        "今日"判定：DATE(ts_upload_ms) = today（按 UTC 日期）
        """
        conn = self._connect()
        try:
            # 今日考试人数（DISTINCT student_id，排除存根）
            row = conn.execute(
                """SELECT COUNT(DISTINCT student_id) AS exam_count,
                          AVG(total_score) AS avg_score,
                          COUNT(*) AS total_reports,
                          SUM(CASE WHEN total_score >= ? THEN 1 ELSE 0 END) AS pass_count
                   FROM reports
                   WHERE is_stub = 0
                     AND student_id IS NOT NULL
                     AND DATE(ts_upload_ms / 1000, 'unixepoch') = DATE('now')""",
                (pass_threshold,)
            ).fetchone()

            exam_count = row["exam_count"] if row else 0
            total_reports = row["total_reports"] if row else 0
            avg_score = round(row["avg_score"], 1) if row and row["avg_score"] is not None else 0
            pass_count = row["pass_count"] if row else 0
            pass_rate = round(pass_count / total_reports, 4) if total_reports > 0 else 0

            # 待辅导学员数：diagnosis_results 表中 student_regression 类型的去重学员数
            tutor_row = conn.execute(
                """SELECT COUNT(DISTINCT target_id) AS cnt
                   FROM diagnosis_results
                   WHERE diagnosis_type = 'student_regression'"""
            ).fetchone()
            pending_tutor_count = tutor_row["cnt"] if tutor_row else 0

            return {
                "exam_count": exam_count,
                "avg_score": avg_score,
                "pass_rate": pass_rate,
                "pending_tutor_count": pending_tutor_count,
                "date": time.strftime("%Y-%m-%d", time.localtime())
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 2. 高频错误点 TOP5
    # ------------------------------------------------------------------
    def get_top_error_points(self, limit: int = 5,
                             weights: Optional[dict] = None) -> List[dict]:
        """
        高频错误点 TOP5：综合错误得分排序
        对应 doc/72 §3.2

        综合得分 = 遗漏率 × 0.4 + 超时率 × 0.4 + 顺序错误率 × 0.2
        """
        if weights is None:
            weights = {"omission": 0.4, "timeout": 0.4, "sequence_chaos": 0.2}

        conn = self._connect()
        try:
            # 按步骤 idx 聚合：遗漏率（state IN (0,3)）+ 超时率（基于子步骤 timeout）
            rows = conn.execute(
                """SELECT rs.idx,
                          rs.name,
                          COUNT(*) AS sample_count,
                          SUM(CASE WHEN rs.state IN (0, 3) THEN 1 ELSE 0 END) AS omission_count,
                          AVG(rs.duration_ms) AS avg_duration
                   FROM report_steps rs
                   INNER JOIN reports r ON r.report_id = rs.report_id
                   WHERE r.is_stub = 0
                   GROUP BY rs.idx, rs.name
                   ORDER BY rs.idx"""
            ).fetchall()

            if not rows:
                return []

            # 收集所有 report_id 用于超时率计算
            all_report_ids = {r["report_id"] for r in conn.execute(
                "SELECT report_id FROM reports WHERE is_stub = 0"
            ).fetchall()}
            total_reports = len(all_report_ids) if all_report_ids else 1

            points = []
            for row in rows:
                sc = row["sample_count"] or 1
                omission_rate = (row["omission_count"] or 0) / sc if sc > 0 else 0

                # 超时率：该步骤的子步骤有 timeout=1 的报告占比
                step_report_ids = {r["report_id"] for r in conn.execute(
                    "SELECT DISTINCT report_id FROM report_steps WHERE idx = ?",
                    (row["idx"],)
                ).fetchall()}
                timeout_count = 0
                if step_report_ids:
                    placeholders = ",".join("?" * len(step_report_ids))
                    timeout_row = conn.execute(
                        f"""SELECT COUNT(DISTINCT report_id) AS cnt
                            FROM report_substeps
                            WHERE report_id IN ({placeholders})
                              AND timeout = 1""",
                        list(step_report_ids)
                    ).fetchone()
                    timeout_count = timeout_row["cnt"] if timeout_row else 0
                timeout_rate = timeout_count / total_reports if total_reports > 0 else 0

                # 顺序错误率：本期简化为 0（doc/71 §6.2 算法后续细化）
                sequence_error_rate = 0.0

                # 综合得分
                composite = (
                    omission_rate * weights.get("omission", 0.4)
                    + timeout_rate * weights.get("timeout", 0.4)
                    + sequence_error_rate * weights.get("sequence_chaos", 0.2)
                )

                points.append({
                    "idx": row["idx"],
                    "name": row["name"] or f"步骤{row['idx']}",
                    "omission_rate": round(omission_rate, 4),
                    "timeout_rate": round(timeout_rate, 4),
                    "sequence_error_rate": round(sequence_error_rate, 4),
                    "composite_score": round(composite, 4),
                    "sample_count": row["sample_count"]
                })

            # 按综合得分降序，取 TOP N
            points.sort(key=lambda x: x["composite_score"], reverse=True)
            return points[:limit]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 3. 需关注的学员
    # ------------------------------------------------------------------
    def get_attention_students(self, limit: int = 20,
                               volatility_threshold: float = 15.0) -> List[dict]:
        """
        需关注的学员：退步预警 / 波动较大 / 薄弱环节突出
        对应 doc/72 §3.3

        数据来源：
          - diagnosis_results 表（student_regression 类型）
          - reports 表（成绩波动计算）
        """
        conn = self._connect()
        try:
            # 1. 从诊断结果表取退步预警学员
            regression_rows = conn.execute(
                """SELECT DISTINCT target_id AS student_id,
                          metric_value, threshold_value, advice_text
                   FROM diagnosis_results
                   WHERE diagnosis_type = 'student_regression'
                     AND target_id IS NOT NULL"""
            ).fetchall()

            regression_students = {}
            for r in regression_rows:
                regression_students[r["student_id"]] = {
                    "student_id": r["student_id"],
                    "reason": "student_regression",
                    "detail": f"最近平均分 {r['metric_value']:.1f} < 阈值 {r['threshold_value']:.1f}",
                    "advice": r["advice_text"] or ""
                }

            # 2. 波动较大：该学员最近 N 次报告 total_score 标准差 > 阈值
            # 先取所有有报告的学员
            student_rows = conn.execute(
                """SELECT DISTINCT student_id FROM reports
                   WHERE is_stub = 0 AND student_id IS NOT NULL"""
            ).fetchall()

            volatility_students = {}
            for sr in student_rows:
                sid = sr["student_id"]
                # 取最近 10 次成绩
                score_rows = conn.execute(
                    """SELECT total_score FROM reports
                       WHERE is_stub = 0 AND student_id = ?
                       ORDER BY ts_upload_ms DESC LIMIT 10""",
                    (sid,)
                ).fetchall()
                scores = [r["total_score"] for r in score_rows if r["total_score"] is not None]
                if len(scores) >= 3:
                    avg = sum(scores) / len(scores)
                    variance = sum((s - avg) ** 2 for s in scores) / len(scores)
                    stddev = variance ** 0.5
                    if stddev > volatility_threshold:
                        volatility_students[sid] = {
                            "student_id": sid,
                            "reason": "volatility",
                            "detail": f"成绩标准差 {stddev:.1f} > 阈值 {volatility_threshold}",
                            "stddev": round(stddev, 2)
                        }

            # 3. 合并结果（退步预警优先，波动次之）
            results = []
            seen_ids = set()

            # 退步预警学员
            for sid, info in regression_students.items():
                if sid not in seen_ids:
                    # 补充学员姓名（从 reports 冗余字段取）
                    name_row = conn.execute(
                        "SELECT student_name FROM reports WHERE student_id = ? LIMIT 1",
                        (sid,)
                    ).fetchone()
                    info["student_name"] = name_row["student_name"] if name_row else sid
                    results.append(info)
                    seen_ids.add(sid)

            # 波动较大学员
            for sid, info in volatility_students.items():
                if sid not in seen_ids:
                    name_row = conn.execute(
                        "SELECT student_name FROM reports WHERE student_id = ? LIMIT 1",
                        (sid,)
                    ).fetchone()
                    info["student_name"] = name_row["student_name"] if name_row else sid
                    results.append(info)
                    seen_ids.add(sid)

            return results[:limit]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 4. 实时进度展示
    # ------------------------------------------------------------------
    def get_realtime_progress(self) -> List[dict]:
        """
        实时进度：订阅中设备的当前操作进度
        对应 doc/72 §3.4

        数据来源：report_progress 表（P1 期增量事件入库时写入）
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT rp.device_id,
                          rp.done,
                          rp.total,
                          rp.current,
                          rp.current_sub_index,
                          rp.process_elapsed_ms,
                          rp.updated_at,
                          r.student_name,
                          r.is_stub
                   FROM report_progress rp
                   LEFT JOIN reports r ON r.report_id = rp.report_id
                   ORDER BY rp.updated_at DESC"""
            ).fetchall()

            devices = []
            for row in rows:
                devices.append({
                    "device_id": row["device_id"],
                    "student_name": row["student_name"] or "",
                    "done": row["done"] or 0,
                    "total": row["total"] or 0,
                    "current": row["current"] or "",
                    "current_sub_index": row["current_sub_index"] or 0,
                    "process_elapsed_ms": row["process_elapsed_ms"],
                    "is_stub": bool(row["is_stub"]) if row["is_stub"] is not None else False,
                    "updated_at": row["updated_at"]
                })
            return devices
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 5. 教学改进验证
    # ------------------------------------------------------------------
    def get_improvement_validation(self, cls: str,
                                   before_range: dict,
                                   after_range: dict,
                                   pass_threshold: float = 60.0) -> dict:
        """
        教学改进验证：对比调整前后的班级平均分/完成率变化
        对应 doc/72 §3.5

        Args:
            cls: 班级名
            before_range: {date_start, date_end}（epoch ms）
            after_range: {date_start, date_end}（epoch ms）
            pass_threshold: 通过线

        完成率定义：COUNT(finish_reason='completed') / COUNT(*)
        """
        conn = self._connect()
        try:
            def _calc_range(date_start: int, date_end: int) -> Optional[dict]:
                row = conn.execute(
                    """SELECT COUNT(*) AS report_count,
                              AVG(total_score) AS avg_score,
                              SUM(CASE WHEN finish_reason = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                              SUM(CASE WHEN total_score >= ? THEN 1 ELSE 0 END) AS pass_count
                       FROM reports
                       WHERE is_stub = 0
                         AND student_cls = ?
                         AND ts_upload_ms >= ?
                         AND ts_upload_ms <= ?""",
                    (pass_threshold, cls, int(date_start), int(date_end))
                ).fetchone()

                if not row or row["report_count"] == 0:
                    return None

                total = row["report_count"]
                completed = row["completed_count"] or 0
                avg_score = round(row["avg_score"], 1) if row["avg_score"] is not None else 0
                completion_rate = round(completed / total, 4) if total > 0 else 0
                pass_rate = round((row["pass_count"] or 0) / total, 4) if total > 0 else 0

                return {
                    "avg_score": avg_score,
                    "completion_rate": completion_rate,
                    "pass_rate": pass_rate,
                    "report_count": total
                }

            before = _calc_range(before_range.get("date_start", 0),
                                  before_range.get("date_end", 0))
            after = _calc_range(after_range.get("date_start", 0),
                                 after_range.get("date_end", 0))

            # 计算变化趋势
            trend = "no_data"
            delta = {"avg_score": 0, "completion_rate": 0}

            if before and after:
                delta["avg_score"] = round(after["avg_score"] - before["avg_score"], 1)
                delta["completion_rate"] = round(
                    after["completion_rate"] - before["completion_rate"], 4
                )
                # 以平均分变化为主导，完成率作辅助
                if delta["avg_score"] > 0 and delta["completion_rate"] >= 0:
                    trend = "improved"
                elif delta["avg_score"] < 0 and delta["completion_rate"] <= 0:
                    trend = "declined"
                else:
                    trend = "mixed"

            return {
                "cls": cls,
                "before": before,
                "after": after,
                "delta": delta,
                "trend": trend
            }
        finally:
            conn.close()
