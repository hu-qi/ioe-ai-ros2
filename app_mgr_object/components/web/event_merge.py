"""
event_merge.py — 增量 + 整包事件流合并器

工程基线: app_mgr_object-0.2.1
关联文档: doc/45 §2 (增量 events), doc/38 §4 (整包 events)

职责:
  增量与整包事件流的去重合并.
  report_events 表 PRIMARY KEY (report_id, ts, kind, sub) 天然去重,
  合并器在此基础上提供:
    1. merge_delta_into_report: 增量事件追加到对应轮次事件流
    2. reconcile_full_report:   整包到达时与已存增量事件对账, 补全存根报告
    3. get_merged_event_stream: 读取合并后的完整事件流 (按 ts 升序)

去重键 (doc/45 §1):
  增量: device_id + round_start_ms + events[].ts
  整包: device_id + round.start_ms
  events 天然去重: (report_id, ts, kind, sub)
"""

import logging
from typing import Dict, Any, List, Optional


class EventMerge:
    """增量 + 整包事件流合并器"""

    def __init__(self, repo, logger=None):
        """
        Args:
            repo: ReportRepo 实例
            logger: 日志器
        """
        self.repo = repo
        self.logger = logger or logging.getLogger(__name__)

    def merge_delta_into_report(self, payload: Dict[str, Any]) -> int:
        """
        增量事件合并入口.

        处理流程:
          1. 解析 doc/45 event_delta payload
          2. 定位或创建对应 report 记录 (增量可能先于整包到达)
          3. events 逐条 INSERT OR IGNORE (source=delta), 天然去重
          4. 更新 report_progress 实时进度快照

        Args:
            payload: doc/45 §2 event_delta payload

        Returns:
            实际新增条数 (INSERT OR IGNORE 命中行数)
        """
        events = payload.get("events", []) or []
        if not events:
            if self.logger:
                self.logger.debug("EventMerge: 增量 payload 无 events, 跳过")
            return 0

        inserted = self.repo.insert_delta_events(payload)

        if self.logger:
            self.logger.info(
                f"EventMerge: 增量合并完成 inserted={inserted}/{len(events)}"
            )
        return inserted

    def reconcile_full_report(self, payload: Dict[str, Any]) -> str:
        """
        整包到达时与已存增量事件对账.

        处理流程:
          1. 查 reports 表同 device_id + round.start_ms, 已存在则返回 (幂等)
          2. 整包 events 全量 INSERT OR IGNORE (source=batch)
             - 与已存 delta 事件天然去重 (PK: report_id, ts, kind, sub)
          3. 补全存根报告的 finish_reason / end_ms / duration_ms / student 信息
          4. 原始 JSON 落盘

        Args:
            payload: doc/38 §2 整包 payload

        Returns:
            report_id
        """
        device_id = payload.get("device_id", "")
        round_data = payload.get("round", {})
        start_ms = round_data.get("start_ms", 0)
        report_id = f"R{device_id}_{start_ms}"

        # 检查是否已存在 (幂等)
        existing = None
        import sqlite3
        conn = self.repo._connect()
        try:
            existing = conn.execute(
                "SELECT report_id, is_stub FROM reports WHERE report_id = ?",
                (report_id,)
            ).fetchone()
        finally:
            conn.close()

        if existing and not existing["is_stub"]:
            if self.logger:
                self.logger.info(
                    f"EventMerge: 整包去重命中 report_id={report_id}, 跳过"
                )
            return report_id

        # 整包入库 (INSERT OR REPLACE 语义, 补全存根)
        result_id = self.repo.insert_full_report(payload)

        if self.logger:
            self.logger.info(
                f"EventMerge: 整包对账完成 report_id={result_id} "
                f"was_stub={existing['is_stub'] if existing else 0}"
            )
        return result_id

    def get_merged_event_stream(self, report_id: str) -> List[Dict[str, Any]]:
        """
        读取合并后的完整事件流 (按 ts 升序).

        增量 (source=delta) 与整包 (source=batch) 事件已通过 PK 天然去重,
        此方法直接读取 report_events 表该 report_id 的全部事件.

        Args:
            report_id: 报告 ID

        Returns:
            事件列表, 每条含 (ts, kind, step, sub, source), 按 ts 升序
        """
        import sqlite3
        conn = self.repo._connect()
        try:
            rows = conn.execute(
                """SELECT ts, kind, step, sub, source
                   FROM report_events
                   WHERE report_id = ?
                   ORDER BY ts ASC, kind ASC""",
                (report_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
