"""
report_repo.py — 报告接收插件 SQLite 仓储层

工程基线: app_mgr_object-0.2.1
关联文档: doc/38 (整包 schema 1.0), doc/45 (增量 schema 1.1 + doc/58 统一计时)

职责:
  1. reports / report_steps / report_substeps / report_events / report_progress / subscriptions 六表 CRUD
  2. 整包入库: 解析 doc/38 payload, 写 reports + report_steps + report_substeps + report_events
  3. 增量入库: 解析 doc/45 event_delta payload, 写 report_events + report_progress
  4. 订阅管理: doc/45 §4 四接口 (订阅/查询/退订/列表), 支持多设备同时订阅
  5. 软关联标记: 入库时查 students 表设置 student_bound, 不阻塞入库
  6. 去重幂等: 整包 device_id + round.start_ms, 增量 INSERT OR IGNORE 天然去重
"""

import os
import json
import time
import sqlite3
from typing import Dict, Any, List, Optional, Tuple


class ReportRepo:
    """报告六表 SQLite 仓储"""

    SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "reports_schema.sql")

    def __init__(self, db_path: str, logger=None):
        self.db_path = db_path
        self.logger = logger
        self._ensure_parent_dir()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _ensure_parent_dir(self):
        parent = os.path.dirname(self.db_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

    def init_schema(self) -> None:
        """执行建表 DDL (幂等) + 增量字段迁移"""
        with open(self.SCHEMA_FILE, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = self._connect()
        try:
            conn.executescript(schema_sql)
            self._migrate_subscriptions_columns(conn)
            conn.commit()
            if self.logger:
                self.logger.info("ReportRepo: schema 初始化完成")
        finally:
            conn.close()

    def _migrate_subscriptions_columns(self, conn: sqlite3.Connection) -> None:
        """给已存在的 subscriptions 表补齐 v2/v3 新增字段（CREATE TABLE IF NOT EXISTS 不会改已有表）。"""
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(subscriptions)")
        existing_cols = {row[1] for row in cur.fetchall()}

        # v2: 单 edge_ip（旧）→ v3: edge_ips JSON 数组
        # 迁移策略：若存在旧 edge_ip 字段，先读出值，新增 edge_ips 字段后把旧值转成 JSON 数组写回
        legacy_edge_ip_value = None
        if "edge_ip" in existing_cols and "edge_ips" not in existing_cols:
            # 读出旧 edge_ip 值
            rows = cur.execute("SELECT device_id, edge_ip FROM subscriptions").fetchall()
            legacy_edge_ip_value = {r["device_id"]: r["edge_ip"] for r in rows} if rows else {}
            # 旧字段不删（SQLite 不支持 DROP COLUMN），新字段 edge_ips 补上
            cur.execute("ALTER TABLE subscriptions ADD COLUMN edge_ips TEXT")
            if self.logger:
                self.logger.info("ReportRepo: 迁移字段 subscriptions.edge_ips (从 edge_ip)")

        new_cols = [
            ("edge_ips", "TEXT"),
            ("edge_port", "INTEGER"),
            ("notify_status", "TEXT"),
            ("notify_ts", "INTEGER"),
            ("notify_detail", "TEXT"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols and col_name != "edge_ips":
                cur.execute(
                    f"ALTER TABLE subscriptions ADD COLUMN {col_name} {col_type}"
                )
                if self.logger:
                    self.logger.info(f"ReportRepo: 迁移字段 subscriptions.{col_name}")

        # 若刚迁移 edge_ips，把旧 edge_ip 值转成 JSON 数组写回
        if legacy_edge_ip_value:
            import json as _json
            for device_id, old_ip in legacy_edge_ip_value.items():
                if old_ip:
                    cur.execute(
                        "UPDATE subscriptions SET edge_ips = ? WHERE device_id = ?",
                        (_json.dumps([old_ip]), device_id),
                    )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    # ------------------------------------------------------------------
    # 软关联: 查 students 表判断 student_id 是否存在
    # ------------------------------------------------------------------
    def _check_student_bound(self, conn: sqlite3.Connection, student_id: Optional[str]) -> int:
        """查 students 表, 存在返回 1, 不存在/未绑定返回 0. 不阻塞主流程."""
        if not student_id:
            return 0
        try:
            row = conn.execute(
                "SELECT 1 FROM students WHERE id = ? AND status != 'deleted' LIMIT 1",
                (student_id,)
            ).fetchone()
            return 1 if row else 0
        except sqlite3.Error:
            # students 表不存在或查询失败, 不阻塞入库
            if self.logger:
                self.logger.debug(f"ReportRepo: students 表查询失败, student_bound=0")
            return 0

    # ------------------------------------------------------------------
    # 整包入库 (doc/38 schema 1.0)
    # ------------------------------------------------------------------
    def insert_full_report(self, payload: Dict[str, Any], raw_json_path: Optional[str] = None) -> Tuple[str, bool]:
        """
        整包入库, 返回 (report_id, is_duplicate).

        去重键: device_id + round.start_ms (doc/38 §7.6)
        幂等: 已存在则直接返回, 不重复入库
        """
        device_id = payload.get("device_id", "")
        round_data = payload.get("round", {})
        start_ms = round_data.get("start_ms", 0)
        report_id = f"R{device_id}_{start_ms}"
        ts_upload_ms = payload.get("ts_upload_ms", self._now_ms())
        now_ms = self._now_ms()

        conn = self._connect()
        try:
            # 去重检查（读 is_stub 以区分"完整报告去重"与"存根报告待补全"）
            existing = conn.execute(
                "SELECT report_id, is_stub FROM reports WHERE report_id = ?",
                (report_id,)
            ).fetchone()

            if existing and not existing["is_stub"]:
                # 已是完整报告 → 幂等跳过
                if self.logger:
                    self.logger.info(
                        f"ReportRepo: 整包去重命中 report_id={report_id}")
                return report_id, True

            # 解析 student (doc/38 §3)
            student = payload.get("student", {}) or {}
            student_id = student.get("id")
            student_name = student.get("name", "")
            student_cls = student.get("cls", "")

            # 软关联标记 (不阻塞)
            student_bound = self._check_student_bound(conn, student_id)

            if existing and existing["is_stub"]:
                # 存根报告补全：UPDATE 为完整报告
                conn.execute(
                    """UPDATE reports SET
                       device_id=?, student_id=?, student_name=?, student_cls=?,
                       student_bound=?, process_name=?, process_type=?,
                       finish_reason=?, is_stub=0, start_ms=?, end_ms=?,
                       duration_ms=?, process_elapsed_ms=?, total_score=?,
                       raw_json_path=?, ts_upload_ms=?, created_at=?
                       WHERE report_id=?""",
                    (device_id, student_id, student_name, student_cls,
                     student_bound,
                     round_data.get("process_name", ""),
                     round_data.get("process_type", ""),
                     round_data.get("finish_reason", ""),
                     start_ms,
                     round_data.get("end_ms"),
                     round_data.get("duration_ms"),
                     round_data.get("process_elapsed_ms"),
                     round_data.get("total_score"),
                     raw_json_path,
                     ts_upload_ms,
                     now_ms,
                     report_id)
                )
            else:
                # 全新整包入库
                conn.execute(
                    """INSERT INTO reports
                       (report_id, device_id, student_id, student_name, student_cls,
                        student_bound, process_name, process_type, finish_reason,
                        is_stub, start_ms, end_ms, duration_ms, process_elapsed_ms,
                        total_score, raw_json_path, ts_upload_ms, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (report_id, device_id, student_id, student_name, student_cls,
                     student_bound,
                     round_data.get("process_name", ""),
                     round_data.get("process_type", ""),
                     round_data.get("finish_reason", ""),
                     start_ms,
                     round_data.get("end_ms"),
                     round_data.get("duration_ms"),
                     round_data.get("process_elapsed_ms"),
                     round_data.get("total_score"),
                     raw_json_path,
                     ts_upload_ms,
                     now_ms)
                )

            # 写 report_steps (doc/38 §5)
            steps = round_data.get("steps", []) or []
            for s in steps:
                conn.execute(
                    """INSERT OR REPLACE INTO report_steps
                       (report_id, idx, name, state, start_ms, end_ms,
                        duration_ms, interval_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (report_id,
                     s.get("idx"),
                     s.get("name", ""),
                     s.get("state", 0),
                     s.get("start_ms"),
                     s.get("end_ms"),
                     s.get("duration_ms"),
                     s.get("interval_ms"))
                )

            # 写 report_substeps (doc/38 §5)
            substeps = round_data.get("substeps", []) or []
            for ss in substeps:
                conn.execute(
                    """INSERT OR REPLACE INTO report_substeps
                       (report_id, idx, name, state, start_ms, end_ms,
                        duration_ms, count, total_duration_ms, timeout)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (report_id,
                     ss.get("idx"),
                     ss.get("name", ""),
                     ss.get("state", 0),
                     ss.get("start_ms"),
                     ss.get("end_ms"),
                     ss.get("duration_ms"),
                     ss.get("count", 1),
                     ss.get("total_duration_ms"),
                     1 if ss.get("timeout") else 0)
                )

            # 写 report_events (doc/38 §4, source=batch)
            events = round_data.get("events", []) or []
            for ev in events:
                conn.execute(
                    """INSERT OR IGNORE INTO report_events
                       (report_id, ts, kind, step, sub, source)
                       VALUES (?, ?, ?, ?, ?, 'batch')""",
                    (report_id,
                     ev.get("ts", 0),
                     ev.get("kind", 0),
                     ev.get("step"),
                     ev.get("sub"))
                )

            conn.commit()
            if self.logger:
                self.logger.info(
                    f"ReportRepo: 整包入库成功 report_id={report_id} "
                    f"steps={len(steps)} substeps={len(substeps)} events={len(events)}"
                )
            return report_id, False
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 增量入库 (doc/45 schema 1.1)
    # ------------------------------------------------------------------
    def insert_delta_events(self, payload: Dict[str, Any]) -> int:
        """
        增量事件入库, 返回实际新增条数.

        去重键: device_id + round_start_ms + events[].ts (doc/45 §1)
        机制: report_events 表 PRIMARY KEY (report_id, ts, kind, sub), INSERT OR IGNORE
        """
        device_id = payload.get("device_id", "")
        round_start_ms = payload.get("round_start_ms", 0)
        report_id = f"R{device_id}_{round_start_ms}"
        now_ms = self._now_ms()

        # 解析 student (增量也可能带 student, doc/45 §2)
        student = payload.get("student", {}) or {}
        student_id = student.get("id")
        student_name = student.get("name", "")
        student_cls = student.get("cls", "")

        # 解析 progress (doc/45 §2)
        progress = payload.get("progress", {}) or {}
        process_elapsed_ms = payload.get("process_elapsed_ms")

        events = payload.get("events", []) or []
        max_ts = max((ev.get("ts", 0) for ev in events), default=0)

        conn = self._connect()
        try:
            # 确保报告记录存在 (增量可能先于整包到达)
            existing = conn.execute(
                "SELECT report_id, is_stub FROM reports WHERE report_id = ?",
                (report_id,)
            ).fetchone()

            if not existing:
                # 创建存根报告 (is_stub=1, 待整包补全)
                student_bound = self._check_student_bound(conn, student_id)
                conn.execute(
                    """INSERT INTO reports
                       (report_id, device_id, student_id, student_name, student_cls,
                        student_bound, process_name, process_type, finish_reason,
                        is_stub, start_ms, end_ms, duration_ms, process_elapsed_ms,
                        total_score, raw_json_path, ts_upload_ms, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, '', '', NULL, 1, ?, NULL, NULL, ?, NULL, NULL, ?, ?)""",
                    (report_id, device_id, student_id, student_name, student_cls,
                     student_bound,
                     round_start_ms,
                     process_elapsed_ms,
                     now_ms,
                     now_ms)
                )
            else:
                # 已存在, 更新 process_elapsed_ms (若有)
                if process_elapsed_ms is not None:
                    conn.execute(
                        "UPDATE reports SET process_elapsed_ms = ? WHERE report_id = ?",
                        (process_elapsed_ms, report_id)
                    )

            # 写 report_events (source=delta, INSERT OR IGNORE 天然去重)
            inserted = 0
            for ev in events:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO report_events
                       (report_id, ts, kind, step, sub, source)
                       VALUES (?, ?, ?, ?, ?, 'delta')""",
                    (report_id,
                     ev.get("ts", 0),
                     ev.get("kind", 0),
                     ev.get("step"),
                     ev.get("sub"))
                )
                inserted += cur.rowcount

            # 写/更新 report_progress (doc/45 §2)
            conn.execute(
                """INSERT INTO report_progress
                   (report_id, device_id, round_start_ms, done, total,
                    current, current_sub_index, process_elapsed_ms,
                    last_delta_ts, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(report_id) DO UPDATE SET
                    device_id=excluded.device_id,
                    round_start_ms=excluded.round_start_ms,
                    done=excluded.done,
                    total=excluded.total,
                    current=excluded.current,
                    current_sub_index=excluded.current_sub_index,
                    process_elapsed_ms=excluded.process_elapsed_ms,
                    last_delta_ts=excluded.last_delta_ts,
                    updated_at=excluded.updated_at""",
                (report_id, device_id, round_start_ms,
                 progress.get("done", 0),
                 progress.get("total", 0),
                 progress.get("current", ""),
                 progress.get("current_sub_index", 0),
                 process_elapsed_ms,
                 max_ts,
                 now_ms)
            )

            conn.commit()
            if self.logger:
                self.logger.info(
                    f"ReportRepo: 增量入库 report_id={report_id} "
                    f"events={len(events)} inserted={inserted}"
                )
            return inserted
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 存根补全 (整包到达时, 补全已存在的存根报告)
    # ------------------------------------------------------------------
    def reconcile_full_report(self, payload: Dict[str, Any]) -> str:
        """
        整包到达时, 与已存增量事件对账, 补全存根报告.
        实际实现复用 insert_full_report (INSERT OR REPLACE 语义).
        """
        report_id, is_dup = self.insert_full_report(payload)
        return report_id

    # ------------------------------------------------------------------
    # 报告检索 (doc/38 §8 Mock 建议)
    # ------------------------------------------------------------------
    def list_reports(self, filters: Dict[str, Any], page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """报告列表检索 (多条件过滤 + 分页)"""
        where_parts = []
        params = []

        if filters.get("student_id"):
            where_parts.append("student_id = ?")
            params.append(filters["student_id"])
        if filters.get("device_id"):
            where_parts.append("device_id = ?")
            params.append(filters["device_id"])
        if filters.get("finish_reason"):
            where_parts.append("finish_reason = ?")
            params.append(filters["finish_reason"])
        if filters.get("start_ms"):
            where_parts.append("start_ms >= ?")
            params.append(filters["start_ms"])
        if filters.get("end_ms"):
            where_parts.append("start_ms <= ?")
            params.append(filters["end_ms"])
        if filters.get("step_index") is not None:
            # 下钻过滤（doc/72 V-03）：仅返回包含指定步骤的报告
            where_parts.append(
                "EXISTS (SELECT 1 FROM report_steps rs "
                "WHERE rs.report_id = reports.report_id AND rs.idx = ?)"
            )
            params.append(filters["step_index"])

        where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        offset = (page - 1) * page_size

        conn = self._connect()
        try:
            # 总数
            count_row = conn.execute(
                f"SELECT COUNT(*) as total FROM reports{where_clause}", params
            ).fetchone()
            total = count_row["total"] if count_row else 0

            # 分页数据
            rows = conn.execute(
                f"""SELECT report_id, device_id, student_id, student_name,
                           student_cls, student_bound, process_name, process_type,
                           finish_reason, is_stub, start_ms, end_ms, duration_ms,
                           process_elapsed_ms, total_score, raw_json_path,
                           ts_upload_ms, created_at
                    FROM reports{where_clause}
                    ORDER BY ts_upload_ms DESC
                    LIMIT ? OFFSET ?""",
                params + [page_size, offset]
            ).fetchall()

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": [dict(r) for r in rows]
            }
        finally:
            conn.close()

    def get_report_detail(self, report_id: str) -> Optional[Dict[str, Any]]:
        """报告详情: reports + report_steps + report_substeps + report_events"""
        conn = self._connect()
        try:
            report_row = conn.execute(
                "SELECT * FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            if not report_row:
                return None

            steps = conn.execute(
                "SELECT * FROM report_steps WHERE report_id = ? ORDER BY idx",
                (report_id,)
            ).fetchall()

            substeps = conn.execute(
                "SELECT * FROM report_substeps WHERE report_id = ? ORDER BY idx",
                (report_id,)
            ).fetchall()

            events = conn.execute(
                "SELECT * FROM report_events WHERE report_id = ? ORDER BY ts",
                (report_id,)
            ).fetchall()

            return {
                "report": dict(report_row),
                "steps": [dict(r) for r in steps],
                "substeps": [dict(r) for r in substeps],
                "events": [dict(r) for r in events]
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 订阅管理 (doc/45 §4, 多设备)
    # ------------------------------------------------------------------
    def upsert_subscription(
        self,
        device_id: str,
        note: str = "",
        edge_ips: Optional[List[str]] = None,
        edge_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """订阅设备 (doc/45 §4.1). 重复订阅 = 更新 note + 保持 active (resubscribed=true).

        v3 增强: 接受 edge_ips（IP 列表）/edge_port，订阅时初始化 notify_status='pending'，
        平台据此主动往所有边缘端推送"你被订阅了"的通知（全推）。
        """
        import json as _json
        now_ms = self._now_ms()
        edge_ips_json = _json.dumps(edge_ips) if edge_ips else None
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT * FROM subscriptions WHERE device_id = ?", (device_id,)
            ).fetchone()

            if existing:
                # 重复订阅：重新激活 active=1，更新 note + resubscribed 标记
                conn.execute(
                    """UPDATE subscriptions
                       SET active = 1, note = ?, updated_at_ms = ?, resubscribed = 1,
                           edge_ips = COALESCE(?, edge_ips),
                           edge_port = COALESCE(?, edge_port),
                           notify_status = 'pending'
                       WHERE device_id = ?""",
                    (note, now_ms, edge_ips_json, edge_port, device_id)
                )
            else:
                conn.execute(
                    """INSERT INTO subscriptions
                       (device_id, active, note, edge_ips, edge_port,
                        notify_status, subscribed_at_ms, updated_at_ms, resubscribed)
                       VALUES (?, 1, ?, ?, ?, 'pending', ?, ?, 0)""",
                    (device_id, note, edge_ips_json, edge_port, now_ms, now_ms)
                )

            conn.commit()
            return {
                "device_id": device_id,
                "active": True,
                "edge_ips": edge_ips,
                "edge_port": edge_port,
                "subscribed_at_ms": existing["subscribed_at_ms"] if existing else now_ms
            }
        finally:
            conn.close()

    def update_notify_status(
        self,
        device_id: str,
        status: str,
        notify_ts: Optional[int] = None,
        notify_detail: Optional[str] = None,
    ) -> None:
        """更新订阅推送通知状态（pending/sent/partial/failed）+ 各 IP 明细。"""
        now_ms = notify_ts or self._now_ms()
        conn = self._connect()
        try:
            if notify_detail is not None:
                conn.execute(
                    """UPDATE subscriptions
                       SET notify_status = ?, notify_ts = ?, notify_detail = ?
                       WHERE device_id = ?""",
                    (status, now_ms, notify_detail, device_id),
                )
            else:
                conn.execute(
                    """UPDATE subscriptions
                       SET notify_status = ?, notify_ts = ?
                       WHERE device_id = ?""",
                    (status, now_ms, device_id),
                )
            conn.commit()
        finally:
            conn.close()

    def get_subscription(self, device_id: str) -> Optional[Dict[str, Any]]:
        """查询订阅状态 (doc/45 §4.2, 边缘端轮询用)"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE device_id = ?", (device_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def deactivate_subscription(self, device_id: str) -> Dict[str, Any]:
        """退订设备 (doc/45 §4.3). active 置 0."""
        now_ms = self._now_ms()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT * FROM subscriptions WHERE device_id = ?", (device_id,)
            ).fetchone()
            was_active = existing and existing["active"] == 1

            conn.execute(
                """UPDATE subscriptions SET active = 0, updated_at_ms = ?
                   WHERE device_id = ?""",
                (now_ms, device_id)
            )
            conn.commit()
            return {
                "device_id": device_id,
                "active": False,
                "was_active": was_active
            }
        finally:
            conn.close()

    def list_subscriptions(self) -> Dict[str, Any]:
        """订阅设备列表 (doc/45 §4.4)"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM subscriptions ORDER BY subscribed_at_ms"
            ).fetchall()
            devices = {r["device_id"]: dict(r) for r in rows}
            return {"devices": devices}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # evidence 存储 (doc/45 §6, multipart 抓拍图)
    # ------------------------------------------------------------------
    def save_evidence(self, device_id: str, round_start_ms: int,
                      sub: int, ts: int, file_bytes: bytes, evidence_dir: str) -> str:
        """保存 evidence 抓拍图, 返回存储路径."""
        sub_dir = os.path.join(evidence_dir, device_id, str(round_start_ms))
        os.makedirs(sub_dir, exist_ok=True)
        file_path = os.path.join(sub_dir, f"sub_{sub}_ts_{ts}.jpg")
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        return file_path

    # ------------------------------------------------------------------
    # 原始 JSON 落盘 (doc/38 §7 完整留存)
    # ------------------------------------------------------------------
    def save_raw_json(self, device_id: str, report_id: str,
                      payload: Dict[str, Any], raw_json_dir: str) -> str:
        """保存原始 JSON, 返回文件路径."""
        sub_dir = os.path.join(raw_json_dir, device_id)
        os.makedirs(sub_dir, exist_ok=True)
        file_path = os.path.join(sub_dir, f"{report_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return file_path
