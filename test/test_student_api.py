"""
test_student_api.py — 学员管理插件 API 级测试

工程基线: app_mgr_object-0.2.1
关联文档: doc/69 学员管理插件开发方案 §5 接口规范、§9.3 验收标准

覆盖:
  V-02 新增学员成功，工号重复返回 422
  V-03 列表分页正确，模糊检索命中 name/id/cls
  V-04 修改学员字段生效，工号不可改
  V-05 软删除后列表不可见，数据库记录保留
  V-06 CSV 导入成功
  V-07 CSV 导入含错误行返回 errors 明细
  V-08 CSV 导出
"""

import os
import sys
import io
import csv
import tempfile
import pytest
from unittest.mock import MagicMock, patch

# 确保工程根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app_mgr_object.components.web.student_repo import StudentRepo
from app_mgr_object.plugins.student_mgr_plugin import StudentMgrPlugin


@pytest.fixture
def app_and_repo(tmp_path):
    """构建临时 FastAPI app + StudentRepo"""
    db_path = str(tmp_path / "test_api.db")
    schema_path = str(tmp_path / "schema.sql")
    with open(os.path.join(PROJECT_ROOT, "config", "students_schema.sql"), "r") as f:
        schema_sql = f.read()
    with open(schema_path, "w") as f:
        f.write(schema_sql)

    repo = StudentRepo(db_path, logger=MagicMock(), schema_path=schema_path)
    repo.init_schema()

    # 构建 mock node
    fake_node = MagicMock()
    fake_node.get_logger.return_value = MagicMock()

    plugin = StudentMgrPlugin(
        node=fake_node,
        config={
            "db_path": db_path,
            "schema_path": schema_path,
            "page_size": 20,
            "page_size_max": 100,
            "import_max_rows": 1000,
        }
    )
    plugin.configure()
    plugin.activate()

    app = FastAPI()
    # mock templates（测试不渲染 HTML）
    mock_templates = MagicMock()
    plugin.register_routes(app, mock_templates)

    client = TestClient(app)
    return client, repo


# ============================================================
# V-02 新增学员
# ============================================================
class TestCreateStudent:
    def test_create_success(self, app_and_repo):
        client, _ = app_and_repo
        resp = client.post("/api/v1/students", json={
            "id": "S2024001", "name": "张明", "cls": "机修一班"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == "S2024001"

    def test_create_duplicate_returns_422(self, app_and_repo):
        client, _ = app_and_repo
        client.post("/api/v1/students", json={"id": "S001", "name": "张明"})
        resp = client.post("/api/v1/students", json={"id": "S001", "name": "李华"})
        assert resp.status_code == 422

    def test_create_empty_id_returns_422(self, app_and_repo):
        client, _ = app_and_repo
        resp = client.post("/api/v1/students", json={"id": "", "name": "张明"})
        assert resp.status_code == 422

    def test_create_empty_name_returns_422(self, app_and_repo):
        client, _ = app_and_repo
        resp = client.post("/api/v1/students", json={"id": "S001", "name": ""})
        assert resp.status_code == 422


# ============================================================
# V-03 列表分页 + 模糊检索
# ============================================================
class TestListStudents:
    def test_list_empty(self, app_and_repo):
        client, _ = app_and_repo
        resp = client.get("/api/v1/students")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 0

    def test_list_with_data(self, app_and_repo):
        client, repo = app_and_repo
        for i in range(5):
            repo.create({"id": f"S{i:03d}", "name": f"学员{i}"})
        resp = client.get("/api/v1/students?page=1&page_size=20&status=all")
        data = resp.json()["data"]
        assert data["total"] == 5
        assert len(data["students"]) == 5

    def test_list_keyword_search(self, app_and_repo):
        client, repo = app_and_repo
        repo.create({"id": "S001", "name": "张明"})
        repo.create({"id": "S002", "name": "李华"})
        resp = client.get("/api/v1/students?keyword=张明&page=1&page_size=20&status=all")
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["students"][0]["name"] == "张明"

    def test_edge_sync_format(self, app_and_repo):
        """dev01 v2 §7: 无 page/page_size/status 参数 = 端侧同步模式,
        响应为 data.students[].tid/name/cls."""
        client, repo = app_and_repo
        repo.create({"id": "S2024001", "name": "张明", "cls": "一班"})
        repo.create({"id": "S2024002", "name": "李华", "cls": "二班"})
        resp = client.get("/api/v1/students")
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["total"] == 2
        assert set(data.keys()) >= {"total", "students"}, "端侧同步模式响应缺少 students 字段"
        s0 = {s["tid"]: s for s in data["students"]}["S2024001"]
        assert s0["name"] == "张明"
        assert s0["cls"] == "一班"

    def test_list_pagination(self, app_and_repo):
        client, repo = app_and_repo
        for i in range(25):
            repo.create({"id": f"S{i:03d}", "name": f"学员{i}"})
        resp = client.get("/api/v1/students?page=1&page_size=20")
        data = resp.json()["data"]
        assert data["total"] == 25
        assert len(data["students"]) == 20
        resp2 = client.get("/api/v1/students?page=2&page_size=20")
        assert len(resp2.json()["data"]["students"]) == 5


# ============================================================
# V-04 修改学员
# ============================================================
class TestUpdateStudent:
    def test_update_success(self, app_and_repo):
        client, _ = app_and_repo
        client.post("/api/v1/students", json={"id": "S001", "name": "张明"})
        resp = client.put("/api/v1/students/S001", json={"name": "张明改"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_update_id_ignored(self, app_and_repo):
        client, _ = app_and_repo
        client.post("/api/v1/students", json={"id": "S001", "name": "张明"})
        # 尝试改工号
        resp = client.put("/api/v1/students/S001", json={"id": "S002", "name": "张明"})
        assert resp.status_code == 422

    def test_update_nonexistent_returns_404(self, app_and_repo):
        client, _ = app_and_repo
        resp = client.put("/api/v1/students/NOTEXIST", json={"name": "test"})
        assert resp.status_code == 404


# ============================================================
# V-05 软删除
# ============================================================
class TestDeleteStudent:
    def test_soft_delete_success(self, app_and_repo):
        client, _ = app_and_repo
        client.post("/api/v1/students", json={"id": "S001", "name": "张明"})
        resp = client.delete("/api/v1/students/S001")
        assert resp.status_code == 200
        # 列表中不可见
        list_resp = client.get("/api/v1/students")
        assert list_resp.json()["data"]["total"] == 0
        # 但详情仍可查
        detail_resp = client.get("/api/v1/students/S001")
        assert detail_resp.status_code == 200

    def test_delete_nonexistent_returns_404(self, app_and_repo):
        client, _ = app_and_repo
        resp = client.delete("/api/v1/students/NOTEXIST")
        assert resp.status_code == 404


# ============================================================
# V-06/V-07 CSV 导入
# ============================================================
class TestImportCSV:
    def _make_csv(self, rows):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "name", "cls", "trade"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        return output.getvalue().encode("utf-8")

    def test_import_success(self, app_and_repo):
        client, _ = app_and_repo
        csv_bytes = self._make_csv([
            {"id": "S001", "name": "张明", "cls": "一班", "trade": "火炮"},
            {"id": "S002", "name": "李华", "cls": "一班", "trade": "火炮"},
        ])
        resp = client.post(
            "/api/v1/students/import",
            files={"file": ("students.csv", csv_bytes, "text/csv")}
        )
        data = resp.json()["data"]
        assert data["success"] == 2
        assert data["failed"] == 0

    def test_import_with_invalid_rows(self, app_and_repo):
        client, _ = app_and_repo
        csv_bytes = self._make_csv([
            {"id": "S001", "name": "张明", "cls": "", "trade": ""},
            {"id": "", "name": "无名", "cls": "", "trade": ""},  # 空工号
        ])
        resp = client.post(
            "/api/v1/students/import",
            files={"file": ("students.csv", csv_bytes, "text/csv")}
        )
        data = resp.json()["data"]
        assert data["success"] == 1
        assert data["failed"] == 1
        assert len(data["errors"]) == 1

    def test_import_empty_csv_returns_zero(self, app_and_repo):
        client, _ = app_and_repo
        csv_bytes = self._make_csv([])
        resp = client.post(
            "/api/v1/students/import",
            files={"file": ("empty.csv", csv_bytes, "text/csv")}
        )
        data = resp.json()["data"]
        assert data["success"] == 0


# ============================================================
# V-08 CSV 导出
# ============================================================
class TestExportCSV:
    def test_export_returns_csv(self, app_and_repo):
        client, repo = app_and_repo
        repo.create({"id": "S001", "name": "张明", "cls": "一班"})
        resp = client.get("/api/v1/students/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        body = resp.content
        # UTF-8 BOM
        assert body.startswith(b'\xef\xbb\xbf')
        text = body[3:].decode("utf-8")
        assert "id" in text and "name" in text
        assert "S001" in text and "张明" in text
