"""
analysis_repo.py — 统计分析插件仓储层

工程基线: app_mgr_object-0.2.1
关联文档: doc/71 统计分析插件开发方案

职责:
  1. analysis_cache / diagnosis_results 两表 DDL 初始化（幂等）
  2. 直连 reports / report_steps / report_substeps / report_events 表读聚合
  3. 步骤用时分布统计（AVG / STDDEV / 合规率 / SOP 对比）
  4. 学员累计统计（考试次数 / 平均得分 / 完成率趋势 / 薄弱步骤 TOP3）
  5. 步骤瓶颈诊断数据支撑（平均用时、遗漏率、顺序错误率）
  6. 学员退步预警数据支撑（成绩趋势）
  7. 统计结果缓存读写 + 诊断结果持久化

跨插件读库合法性: 既有 smart_trigger_plugin 跨插件读 task_cache，
本插件跨插件读 reports 系列表做统计聚合，符合既有"同库跨插件读"惯例。
"""

import os
import json
import sqlite3
import time
from typing import Dict, Any, List, Optional


class AnalysisRepo:
    """统计分析 SQLite 仓储：直连 reports 系列表读聚合 + 自有缓存/诊断表"""

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
        """执行建表 DDL（幂等）"""
        with open(self.SCHEMA_FILE, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = self._connect()
        try:
            conn.executescript(schema_sql)
            conn.commit()
            if self.logger:
                self.logger.info("AnalysisRepo: schema 初始化完成")
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
    # 缓存读写
    # ------------------------------------------------------------------
    def get_cached_result(self, cache_key: str, ttl_sec: int = 300) -> Optional[dict]:
        """读缓存，过期返回 None"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT result_json, computed_at FROM analysis_cache WHERE cache_key = ? LIMIT 1",
                (cache_key,)
            ).fetchone()
            if not row:
                return None
            age_sec = (self._now_ms() - row["computed_at"]) / 1000.0
            if age_sec > ttl_sec:
                return None
            try:
                return json.loads(row["result_json"])
            except (json.JSONDecodeError, TypeError):
                return None
        finally:
            conn.close()

    def save_cached_result(self, cache_key: str, dimension: str,
                           filters: dict, result: dict, report_count: int) -> None:
        """写缓存（upsert）"""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO analysis_cache
                   (cache_key, dimension, filters_json, result_json, computed_at, report_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (cache_key, dimension,
                 json.dumps(filters, ensure_ascii=False),
                 json.dumps(result, ensure_ascii=False),
                 self._now_ms(), report_count)
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 诊断结果持久化
    # ------------------------------------------------------------------
    def save_diagnosis(self, diagnosis: dict) -> str:
        """保存单条诊断结果，返回 diagnosis_id"""
        did = diagnosis.get("diagnosis_id") or f"D{self._now_ms()}"
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO diagnosis_results
                   (diagnosis_id, diagnosis_type, scope, target_id,
                    metric_value, threshold_value, advice_text,
                    computed_at, date_window_start, date_window_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (did, diagnosis.get("diagnosis_type", ""),
                 diagnosis.get("scope", ""),
                 diagnosis.get("target_id"),
                 diagnosis.get("metric_value"),
                 diagnosis.get("threshold_value"),
                 diagnosis.get("advice_text", ""),
                 self._now_ms(),
                 diagnosis.get("date_window_start"),
                 diagnosis.get("date_window_end"))
            )
            conn.commit()
            return did
        finally:
            conn.close()

    def list_diagnoses(self, diagnosis_type: str = '',
                       target_id: str = '',
                       limit: int = 100) -> List[dict]:
        """查询诊断结果列表"""
        where_parts: List[str] = []
        params: List[Any] = []
        if diagnosis_type:
            where_parts.append("diagnosis_type = ?")
            params.append(diagnosis_type)
        if target_id:
            where_parts.append("target_id = ?")
            params.append(target_id)

        where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        params.extend([limit])

        conn = self._connect()
        try:
            rows = conn.execute(
                f"""SELECT * FROM diagnosis_results{where_clause}
                    ORDER BY computed_at DESC LIMIT ?""",
                params
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 过滤条件构造
    # ------------------------------------------------------------------
    @staticmethod
    def _build_report_filters(filters: dict) -> tuple:
        """
        构造 reports 表查询 WHERE 子句。
        filters 可含: cls, device_id, student_id, date_start, date_end, finish_reason
        """
        where_parts: List[str] = []
        params: List[Any] = []

        cls = filters.get("cls", "")
        if cls:
            where_parts.append("r.student_cls = ?")
            params.append(cls)

        device_id = filters.get("device_id", "")
        if device_id:
            where_parts.append("r.device_id = ?")
            params.append(device_id)

        student_id = filters.get("student_id", "")
        if student_id:
            where_parts.append("r.student_id = ?")
            params.append(student_id)

        date_start = filters.get("date_start", 0)
        if date_start:
            where_parts.append("r.ts_upload_ms >= ?")
            params.append(int(date_start))

        date_end = filters.get("date_end", 0)
        if date_end:
            where_parts.append("r.ts_upload_ms <= ?")
            params.append(int(date_end))

        finish_reason = filters.get("finish_reason", "")
        if finish_reason:
            where_parts.append("r.finish_reason = ?")
            params.append(finish_reason)

        # 排除存根报告（统计只算完整报告）
        where_parts.append("r.is_stub = 0")

        where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""
        return where_clause, params

    # ------------------------------------------------------------------
    # 步骤用时分布统计（描述性）
    # ------------------------------------------------------------------
    def get_step_duration_stats(self, filters: dict) -> dict:
        """
        步骤用时分布：AVG / STDDEV / 合规率 / SOP 对比
        对应 doc/71 §4.1
        """
        where_clause, params = self._build_report_filters(filters)

        conn = self._connect()
        try:
            # 报告总数
            cnt_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM reports r{where_clause}", params
            ).fetchone()
            report_count = cnt_row["cnt"] if cnt_row else 0

            if report_count == 0:
                return {"steps": [], "report_count": 0}

            # 按步骤 idx 聚合
            sql = f"""
                SELECT rs.idx,
                       rs.name,
                       COUNT(*)                AS sample_count,
                       AVG(rs.duration_ms)     AS avg_ms,
                       MIN(rs.duration_ms)     AS min_ms,
                       MAX(rs.duration_ms)     AS max_ms
                FROM report_steps rs
                INNER JOIN reports r ON r.report_id = rs.report_id
                {where_clause}
                GROUP BY rs.idx, rs.name
                ORDER BY rs.idx
            """
            rows = conn.execute(sql, params).fetchall()

            steps = []
            for row in rows:
                avg_ms = row["avg_ms"] or 0
                steps.append({
                    "idx": row["idx"],
                    "name": row["name"] or f"步骤{row['idx']}",
                    "avg_duration_ms": round(avg_ms, 1),
                    "min_duration_ms": row["min_ms"],
                    "max_duration_ms": row["max_ms"],
                    "sample_count": row["sample_count"],
                })

            return {"steps": steps, "report_count": report_count}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 学员累计统计（描述性 + 诊断性）
    # ------------------------------------------------------------------
    def get_student_cumulative_stats(self, student_id: str,
                                     date_range: Optional[dict] = None) -> dict:
        """
        学员累计统计：考试次数 / 平均得分 / 完成率趋势 / 薄弱步骤 TOP3
        对应 doc/71 §4.2
        """
        filters: dict = {"student_id": student_id}
        if date_range:
            if date_range.get("date_start"):
                filters["date_start"] = date_range["date_start"]
            if date_range.get("date_end"):
                filters["date_end"] = date_range["date_end"]

        where_clause, params = self._build_report_filters(filters)

        conn = self._connect()
        try:
            # 基本统计
            row = conn.execute(
                f"""SELECT COUNT(*) AS exam_count,
                           AVG(r.total_score) AS avg_score,
                           MIN(r.total_score) AS min_score,
                           MAX(r.total_score) AS max_score
                    FROM reports r{where_clause}""",
                params
            ).fetchone()

            exam_count = row["exam_count"] if row else 0
            if exam_count == 0:
                return {
                    "student_id": student_id,
                    "exam_count": 0,
                    "avg_score": 0,
                    "scores": [],
                    "weak_steps": []
                }

            avg_score = round(row["avg_score"], 1) if row["avg_score"] is not None else 0

            # 成绩趋势（按上报时间升序）
            trend_rows = conn.execute(
                f"""SELECT r.report_id, r.total_score, r.ts_upload_ms, r.finish_reason
                    FROM reports r{where_clause}
                    ORDER BY r.ts_upload_ms ASC""",
                params
            ).fetchall()

            scores = []
            for tr in trend_rows:
                scores.append({
                    "report_id": tr["report_id"],
                    "score": tr["total_score"],
                    "ts_upload_ms": tr["ts_upload_ms"],
                    "finish_reason": tr["finish_reason"]
                })

            # 薄弱步骤 TOP3：按该学员各步骤平均用时降序取前3
            weak_sql = f"""
                SELECT rs.idx, rs.name,
                       AVG(rs.duration_ms) AS avg_ms,
                       COUNT(*) AS cnt
                FROM report_steps rs
                INNER JOIN reports r ON r.report_id = rs.report_id
                {where_clause}
                GROUP BY rs.idx, rs.name
                ORDER BY avg_ms DESC
                LIMIT 3
            """
            weak_rows = conn.execute(weak_sql, params).fetchall()
            weak_steps = []
            for wr in weak_rows:
                weak_steps.append({
                    "idx": wr["idx"],
                    "name": wr["name"] or f"步骤{wr['idx']}",
                    "avg_duration_ms": round(wr["avg_ms"], 1) if wr["avg_ms"] else 0,
                    "sample_count": wr["cnt"]
                })

            return {
                "student_id": student_id,
                "exam_count": exam_count,
                "avg_score": avg_score,
                "min_score": row["min_score"],
                "max_score": row["max_score"],
                "scores": scores,
                "weak_steps": weak_steps
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 班级汇总
    # ------------------------------------------------------------------
    def get_class_summary(self, cls: str,
                          date_range: Optional[dict] = None) -> dict:
        """
        班级汇总：全班平均分 / 通过率 / 高频错误点
        对应 doc/71 §4.3
        """
        filters: dict = {"cls": cls}
        if date_range:
            if date_range.get("date_start"):
                filters["date_start"] = date_range["date_start"]
            if date_range.get("date_end"):
                filters["date_end"] = date_range["date_end"]

        where_clause, params = self._build_report_filters(filters)

        conn = self._connect()
        try:
            row = conn.execute(
                f"""SELECT COUNT(*) AS total,
                           AVG(r.total_score) AS avg_score,
                           SUM(CASE WHEN r.total_score >= 60 THEN 1 ELSE 0 END) AS pass_count
                    FROM reports r{where_clause}""",
                params
            ).fetchone()

            total = row["total"] if row else 0
            if total == 0:
                return {"cls": cls, "total": 0, "avg_score": 0, "pass_rate": 0, "top_error_steps": []}

            avg_score = round(row["avg_score"], 1) if row["avg_score"] is not None else 0
            pass_count = row["pass_count"] or 0
            pass_rate = round(pass_count / total, 4) if total > 0 else 0

            # 高频错误点 TOP5：按步骤超时率+遗漏率综合得分排序
            # 遗漏率 = COUNT(report WHERE step.state IN (0,3)) / COUNT(report)
            # 超时率 = COUNT(report WHERE substep.timeout=1 AND substep.idx IN step) / COUNT(report)
            error_sql = f"""
                SELECT rs.idx,
                       rs.name,
                       COUNT(*) AS sample_count,
                       SUM(CASE WHEN rs.state IN (0, 3) THEN 1 ELSE 0 END) AS omission_count,
                       AVG(rs.duration_ms) AS avg_ms
                FROM report_steps rs
                INNER JOIN reports r ON r.report_id = rs.report_id
                {where_clause}
                GROUP BY rs.idx, rs.name
                ORDER BY omission_count DESC
                LIMIT 5
            """
            error_rows = conn.execute(error_sql, params).fetchall()
            top_error_steps = []
            for er in error_rows:
                sc = er["sample_count"] or 1
                omission_rate = round(er["omission_count"] / sc, 4) if sc > 0 else 0
                top_error_steps.append({
                    "idx": er["idx"],
                    "name": er["name"] or f"步骤{er['idx']}",
                    "omission_rate": omission_rate,
                    "sample_count": er["sample_count"]
                })

            return {
                "cls": cls,
                "total": total,
                "avg_score": avg_score,
                "pass_rate": pass_rate,
                "top_error_steps": top_error_steps
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 诊断数据支撑
    # ------------------------------------------------------------------
    def get_step_avg_duration(self, step_idx: int, filters: dict) -> float:
        """步骤平均用时（毫秒）"""
        where_clause, params = self._build_report_filters(filters)
        params_with_idx = params + [step_idx]

        conn = self._connect()
        try:
            row = conn.execute(
                f"""SELECT AVG(rs.duration_ms) AS avg_ms
                    FROM report_steps rs
                    INNER JOIN reports r ON r.report_id = rs.report_id
                    {where_clause}
                    AND rs.idx = ?""",
                params_with_idx
            ).fetchone()
            return round(row["avg_ms"], 1) if row and row["avg_ms"] is not None else 0.0
        finally:
            conn.close()

    def get_step_omission_rate(self, step_idx: int, filters: dict) -> float:
        """
        步骤遗漏率：COUNT(report WHERE step.state IN (0,3)) / COUNT(report)
        state: 0=未开始, 3=跳过 → 均视为遗漏
        """
        where_clause, params = self._build_report_filters(filters)
        params_with_idx = params + [step_idx]

        conn = self._connect()
        try:
            row = conn.execute(
                f"""SELECT COUNT(*) AS total,
                           SUM(CASE WHEN rs.state IN (0, 3) THEN 1 ELSE 0 END) AS omission
                    FROM report_steps rs
                    INNER JOIN reports r ON r.report_id = rs.report_id
                    {where_clause}
                    AND rs.idx = ?""",
                params_with_idx
            ).fetchone()
            total = row["total"] if row and row["total"] else 0
            if total == 0:
                return 0.0
            omission = row["omission"] or 0
            return round(omission / total, 4)
        finally:
            conn.close()

    def get_step_timeout_rate(self, step_idx: int, filters: dict) -> float:
        """
        步骤超时率：基于子步骤 timeout 标记
        COUNT(report WHERE ANY substep.timeout=1 in step) / COUNT(report)
        """
        where_clause, params = self._build_report_filters(filters)

        conn = self._connect()
        try:
            # 先取该步骤的 report_id 列表
            report_ids_row = conn.execute(
                f"""SELECT DISTINCT rs.report_id
                    FROM report_steps rs
                    INNER JOIN reports r ON r.report_id = rs.report_id
                    {where_clause}
                    AND rs.idx = ?""",
                params + [step_idx]
            ).fetchall()

            if not report_ids_row:
                return 0.0

            report_ids = [r["report_id"] for r in report_ids_row]
            total = len(report_ids)
            if total == 0:
                return 0.0

            # 查这些 report 中是否有子步骤超时
            placeholders = ",".join("?" * len(report_ids))
            timeout_row = conn.execute(
                f"""SELECT COUNT(DISTINCT report_id) AS timeout_count
                    FROM report_substeps
                    WHERE report_id IN ({placeholders})
                      AND timeout = 1""",
                report_ids
            ).fetchone()
            timeout_count = timeout_row["timeout_count"] if timeout_row else 0
            return round(timeout_count / total, 4)
        finally:
            conn.close()

    def get_student_score_trend(self, student_id: str, window: int = 8) -> List[dict]:
        """
        学员成绩趋势：取最近 N 次报告的 total_score，按时间升序
        用于退步预警诊断
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT report_id, total_score, ts_upload_ms, finish_reason
                   FROM reports
                   WHERE student_id = ? AND is_stub = 0
                   ORDER BY ts_upload_ms DESC
                   LIMIT ?""",
                (student_id, window)
            ).fetchall()
            # 反转为升序（最旧→最新）
            return list(reversed([{
                "report_id": r["report_id"],
                "score": r["total_score"],
                "ts_upload_ms": r["ts_upload_ms"],
                "finish_reason": r["finish_reason"]
            } for r in rows]))
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 辅助：获取所有步骤 idx 列表（用于诊断遍历）
    # ------------------------------------------------------------------
    def get_all_step_indices(self, filters: dict) -> List[int]:
        """获取有数据的步骤 idx 列表，升序"""
        where_clause, params = self._build_report_filters(filters)

        conn = self._connect()
        try:
            rows = conn.execute(
                f"""SELECT DISTINCT rs.idx
                    FROM report_steps rs
                    INNER JOIN reports r ON r.report_id = rs.report_id
                    {where_clause}
                    ORDER BY rs.idx""",
                params
            ).fetchall()
            return [r["idx"] for r in rows]
        finally:
            conn.close()
