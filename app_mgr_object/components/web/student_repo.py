"""
student_repo.py — 学员管理插件 SQLite 仓储层

工程基线: app_mgr_object-0.2.1
关联文档: doc/69 学员管理插件开发方案

职责:
  1. students 表 DDL 初始化（幂等）
  2. 学员档案 CRUD（create / get / update / soft_delete）
  3. 分页列表检索（keyword 模糊命中 name/id/cls；cls/status 精确匹配）
  4. CSV 批量导入（bulk_upsert，单事务原子提交）
  5. 班级人数统计（count_by_cls，供后续看板插件调用）

设计要点:
  - 每次操作短连接 sqlite3.connect，with conn 自动事务提交/回滚
  - created_at / updated_at 由仓储层自动填充 int(time.time()*1000)
  - 软删除：status='deleted'，列表默认只查 status='active'
  - bulk_upsert 用 INSERT OR REPLACE 语义（工号已存在则覆盖更新）
"""

import os
import sqlite3
import time
import json
import re
from typing import Dict, Any, List, Optional


class StudentRepo:
    """学员表 SQLite 仓储"""

    SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "students_schema.sql")

    # 工号格式：字母数字下划线短横线，长度 1-32
    ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,32}$')

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
        """执行建表 DDL（幂等），并对存量库自动补列（迁移）"""
        with open(self.SCHEMA_FILE, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = self._connect()
        try:
            conn.executescript(schema_sql)
            # 迁移: 存量库缺 source 列时自动补齐(新增列, 幂等)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(students)")}
            if "source" not in cols:
                conn.execute("ALTER TABLE students ADD COLUMN source TEXT")
                if self.logger:
                    self.logger.info("StudentRepo: 迁移补列 students.source 完成")
            conn.commit()
            if self.logger:
                self.logger.info("StudentRepo: schema 初始化完成")
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
    # 校验
    # ------------------------------------------------------------------
    @classmethod
    def validate_id(cls, student_id: str) -> Optional[str]:
        """校验工号格式，返回错误消息或 None"""
        if not student_id:
            return "工号不能为空"
        if not cls.ID_PATTERN.match(student_id):
            return "工号格式非法：仅允许字母数字下划线短横线，长度1-32"
        return None

    @classmethod
    def validate_name(cls, name: str) -> Optional[str]:
        if not name or not name.strip():
            return "姓名不能为空"
        if len(name) > 32:
            return "姓名长度不能超过32"
        return None

    @classmethod
    def validate_enroll_date(cls, enroll_date: str) -> Optional[str]:
        if not enroll_date:
            return None
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', enroll_date):
            return "入学日期格式应为 YYYY-MM-DD"
        return None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create(self, student: dict) -> str:
        """新增学员，返回 id。工号已存在抛 ValueError"""
        sid = student.get("id", "").strip()
        name = student.get("name", "").strip()

        err = self.validate_id(sid)
        if err:
            raise ValueError(err)
        err = self.validate_name(name)
        if err:
            raise ValueError(err)

        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT 1 FROM students WHERE id = ? LIMIT 1", (sid,)
            ).fetchone()
            if existing:
                conn.close()
                raise ValueError(f"工号已存在: {sid}")

            now = self._now_ms()
            extra_val = student.get("extra")
            if isinstance(extra_val, dict):
                extra_val = json.dumps(extra_val, ensure_ascii=False)
            conn.execute(
                """INSERT INTO students (id, name, cls, trade, enroll_date, status, remark, source, extra, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
                (sid, name,
                 student.get("cls", "").strip() or None,
                 student.get("trade", "").strip() or None,
                 student.get("enroll_date", "").strip() or None,
                 student.get("remark", "").strip() or None,
                 student.get("source", "").strip() or "manual",
                 extra_val,
                 now, now)
            )
            conn.commit()
            return sid
        finally:
            conn.close()

    def get(self, student_id: str) -> Optional[dict]:
        """查单条学员档案"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM students WHERE id = ? LIMIT 1", (student_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_dict(row)
        finally:
            conn.close()

    def update(self, student_id: str, fields: dict) -> bool:
        """修改学员字段（工号不可改），返回是否找到记录"""
        # 过滤允许更新的字段
        allowed = {"name", "cls", "trade", "enroll_date", "status", "remark", "extra"}
        updates = {}
        for k, v in fields.items():
            if k in allowed:
                if k == "name":
                    err = self.validate_name(v)
                    if err:
                        raise ValueError(err)
                if k == "enroll_date":
                    err = self.validate_enroll_date(v)
                    if err:
                        raise ValueError(err)
                if k == "extra" and isinstance(v, dict):
                    v = json.dumps(v, ensure_ascii=False)
                updates[k] = v

        if not updates:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [self._now_ms(), student_id]

        conn = self._connect()
        try:
            cur = conn.execute(
                f"UPDATE students SET {set_clause}, updated_at = ? WHERE id = ?",
                params
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def soft_delete(self, student_id: str) -> bool:
        """软删除学员（status='deleted'），返回是否找到记录"""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE students SET status = 'deleted', updated_at = ? WHERE id = ?",
                (self._now_ms(), student_id)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 分页列表检索
    # ------------------------------------------------------------------
    def list(self, keyword: str = '', cls: str = '',
             status: str = 'active', page: int = 1,
             page_size: int = 20) -> dict:
        """
        分页列表 + 检索
          keyword: 模糊匹配 name / id / cls（三列 OR LIKE）
          cls: 精确匹配班级（空=不过滤）
          status: 精确匹配状态；传 'all' 表示不过滤
          page: 页码，从 1 开始
          page_size: 每页条数
        """
        where_parts: List[str] = []
        params: List[Any] = []

        if keyword:
            kw = f"%{keyword}%"
            where_parts.append("(name LIKE ? OR id LIKE ? OR cls LIKE ?)")
            params.extend([kw, kw, kw])

        if cls:
            where_parts.append("cls = ?")
            params.append(cls)

        if status and status != 'all':
            where_parts.append("status = ?")
            params.append(status)

        where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # 总数
        conn = self._connect()
        try:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM students{where_clause}", params
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            # 分页
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"""SELECT id, name, cls, trade, enroll_date, status, remark, source, created_at, updated_at
                    FROM students{where_clause}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [page_size, offset]
            ).fetchall()

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": [self._row_to_dict(r) for r in rows]
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CSV 批量导入
    # ------------------------------------------------------------------
    def bulk_upsert(self, rows: List[dict]) -> None:
        """
        批量 upsert（INSERT OR REPLACE 语义），单事务原子提交。
        每行 dict 需含: id, name, cls, trade, enroll_date, remark
        校验失败的行抛 ValueError(row_index, reason)。
        """
        if not rows:
            return

        # 先逐行校验
        for i, row in enumerate(rows):
            sid = (row.get("id") or "").strip()
            name = (row.get("name") or "").strip()
            err = self.validate_id(sid)
            if err:
                raise ValueError(f"第{i+1}行: {err}")
            err = self.validate_name(name)
            if err:
                raise ValueError(f"第{i+1}行: {err}")

        conn = self._connect()
        try:
            now = self._now_ms()
            data = []
            for row in rows:
                sid = row.get("id", "").strip()
                name = row.get("name", "").strip()
                cls_val = (row.get("cls") or "").strip() or None
                trade_val = (row.get("trade") or "").strip() or None
                enroll_val = (row.get("enroll_date") or "").strip() or None
                remark_val = (row.get("remark") or "").strip() or None
                source_val = (row.get("source") or "").strip() or "import"
                data.append((sid, name, cls_val, trade_val, enroll_val,
                             'active', remark_val, source_val, now, now))

            conn.executemany(
                """INSERT OR REPLACE INTO students
                   (id, name, cls, trade, enroll_date, status, remark, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                data
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 班级人数统计（供后续看板插件调用）
    # ------------------------------------------------------------------
    def count_by_cls(self) -> dict:
        """按班级分组统计在训学员人数"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT COALESCE(cls, '') AS cls, COUNT(*) AS cnt
                   FROM students
                   WHERE status != 'deleted'
                   GROUP BY cls
                   ORDER BY cnt DESC"""
            ).fetchall()
            return {r["cls"]: r["cnt"] for r in rows}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # extra 字段反序列化
        if "extra" in d and d["extra"]:
            try:
                d["extra"] = json.loads(d["extra"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
