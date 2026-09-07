"""
test_student_repo.py — 学员仓储层单元测试

工程基线: app_mgr_object-0.2.1
关联文档: doc/69 学员管理插件开发方案 §9.3 验收标准
"""

import os
import sys
import tempfile
import sqlite3
import pytest

# 确保工程根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app_mgr_object.components.web.student_repo import StudentRepo


@pytest.fixture
def repo(tmp_path):
    """临时 db + 临时 schema 文件"""
    db_path = str(tmp_path / "test_students.db")
    schema_path = str(tmp_path / "students_schema.sql")
    with open(os.path.join(PROJECT_ROOT, "config", "students_schema.sql"), "r") as f:
        schema_sql = f.read()
    with open(schema_path, "w") as f:
        f.write(schema_sql)

    class FakeLogger:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def error(self, *a, **k): pass
        def warning(self, *a, **k): pass

    r = StudentRepo(db_path, logger=FakeLogger(), schema_path=schema_path)
    r.init_schema()
    return r


# ============================================================
# V-02 新增学员成功，工号重复返回错误
# ============================================================
class TestCreate:
    def test_create_success(self, repo):
        sid = repo.create({"id": "S001", "name": "张明"})
        assert sid == "S001"
        s = repo.get("S001")
        assert s is not None
        assert s["name"] == "张明"
        assert s["status"] == "active"

    def test_create_duplicate_raises(self, repo):
        repo.create({"id": "S001", "name": "张明"})
        with pytest.raises(ValueError, match="工号已存在"):
            repo.create({"id": "S001", "name": "李华"})

    def test_create_empty_id_raises(self, repo):
        with pytest.raises(ValueError, match="工号不能为空"):
            repo.create({"id": "", "name": "张明"})

    def test_create_empty_name_raises(self, repo):
        with pytest.raises(ValueError, match="姓名不能为空"):
            repo.create({"id": "S001", "name": ""})

    def test_create_invalid_id_format_raises(self, repo):
        with pytest.raises(ValueError, match="工号格式非法"):
            repo.create({"id": "含空格 的工号", "name": "张明"})

    def test_create_with_all_fields(self, repo):
        sid = repo.create({
            "id": "S2024001", "name": "张明", "cls": "机修一班",
            "trade": "火炮维修", "enroll_date": "2024-09-01",
            "remark": "转校生", "extra": {"gender": "male"}
        })
        s = repo.get(sid)
        assert s["cls"] == "机修一班"
        assert s["trade"] == "火炮维修"
        assert s["enroll_date"] == "2024-09-01"
        assert s["remark"] == "转校生"


# ============================================================
# V-03 列表分页 + 模糊检索
# ============================================================
class TestList:
    def _seed(self, repo, n):
        for i in range(n):
            repo.create({"id": f"S{i:03d}", "name": f"学员{i}",
                         "cls": "机修一班" if i % 2 == 0 else "机修二班"})

    def test_list_pagination(self, repo):
        self._seed(repo, 25)
        r = repo.list(page=1, page_size=20)
        assert r["total"] == 25
        assert len(r["list"]) == 20
        r2 = repo.list(page=2, page_size=20)
        assert len(r2["list"]) == 5

    def test_list_keyword_search_name(self, repo):
        self._seed(repo, 10)
        r = repo.list(keyword="学员3", status="all")
        assert r["total"] == 1
        assert r["list"][0]["name"] == "学员3"

    def test_list_keyword_search_id(self, repo):
        self._seed(repo, 10)
        r = repo.list(keyword="S00", status="all")
        assert r["total"] == 10

    def test_list_cls_filter(self, repo):
        self._seed(repo, 10)
        r = repo.list(cls="机修一班", status="all")
        assert r["total"] == 5

    def test_list_status_filter(self, repo):
        repo.create({"id": "S001", "name": "张明"})
        repo.create({"id": "S002", "name": "李华"})
        repo.soft_delete("S002")
        r = repo.list(status="active")
        assert r["total"] == 1
        assert r["list"][0]["id"] == "S001"
        r2 = repo.list(status="deleted")
        assert r2["total"] == 1


# ============================================================
# V-04 修改学员字段生效，工号不可改
# ============================================================
class TestUpdate:
    def test_update_success(self, repo):
        repo.create({"id": "S001", "name": "张明", "cls": "一班"})
        found = repo.update("S001", {"name": "张明改", "cls": "二班"})
        assert found is True
        s = repo.get("S001")
        assert s["name"] == "张明改"
        assert s["cls"] == "二班"

    def test_update_nonexistent_returns_false(self, repo):
        found = repo.update("NOTEXIST", {"name": "test"})
        assert found is False

    def test_update_invalid_enroll_date_raises(self, repo):
        repo.create({"id": "S001", "name": "张明"})
        with pytest.raises(ValueError):
            repo.update("S001", {"enroll_date": "invalid"})


# ============================================================
# V-05 软删除后列表不可见，数据库记录保留
# ============================================================
class TestSoftDelete:
    def test_soft_delete_hides_from_active_list(self, repo):
        repo.create({"id": "S001", "name": "张明"})
        found = repo.soft_delete("S001")
        assert found is True
        r = repo.list(status="active")
        assert r["total"] == 0
        # 但记录仍在数据库
        s = repo.get("S001")
        assert s is not None
        assert s["status"] == "deleted"

    def test_soft_delete_nonexistent_returns_false(self, repo):
        found = repo.soft_delete("NOTEXIST")
        assert found is False


# ============================================================
# V-06/V-07 CSV 批量导入
# ============================================================
class TestBulkUpsert:
    def test_bulk_upsert_success(self, repo):
        rows = [
            {"id": "S001", "name": "张明", "cls": "一班", "trade": "火炮"},
            {"id": "S002", "name": "李华", "cls": "一班", "trade": "火炮"},
        ]
        repo.bulk_upsert(rows)
        r = repo.list(status="all")
        assert r["total"] == 2

    def test_bulk_upsert_replace_existing(self, repo):
        repo.create({"id": "S001", "name": "原名"})
        rows = [{"id": "S001", "name": "新名"}]
        repo.bulk_upsert(rows)
        s = repo.get("S001")
        assert s["name"] == "新名"

    def test_bulk_upsert_invalid_row_raises(self, repo):
        rows = [{"id": "", "name": "张明"}]  # 空工号
        with pytest.raises(ValueError, match="第1行"):
            repo.bulk_upsert(rows)

    def test_bulk_upsert_empty_list_no_error(self, repo):
        repo.bulk_upsert([])
        r = repo.list(status="all")
        assert r["total"] == 0


# ============================================================
# count_by_cls
# ============================================================
class TestCountByCls:
    def test_count_by_cls(self, repo):
        repo.create({"id": "S001", "name": "A", "cls": "一班"})
        repo.create({"id": "S002", "name": "B", "cls": "一班"})
        repo.create({"id": "S003", "name": "C", "cls": "二班"})
        result = repo.count_by_cls()
        assert result.get("一班") == 2
        assert result.get("二班") == 1
