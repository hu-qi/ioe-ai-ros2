#!/usr/bin/env python3
"""
test/scoring/test_evidence_p3.py — P3 证据管理测试

覆盖（doc/01 §七、dev01 §2.3 幂等键）:
  - 元数据幂等: 同键重复插入跳过（INSERT OR IGNORE）
  - BMP→JPG 转换 + 缩略图 + 转换回写
  - 端侧路径登记记录（文件不存在）跳过不报错
  - 证据列表 / 图片访问 / 缩略图 / 404 API
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from PIL import Image  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app_mgr_object.components.web.report_repo import ReportRepo  # noqa: E402
from app_mgr_object.components.web.evidence_converter import EvidenceConverter  # noqa: E402
from app_mgr_object.components.web.report_recv_plugin import ReportRecvPlugin  # noqa: E402


class EvidenceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ev_dir = os.path.join(self.tmp, "evidence")
        self.repo = ReportRepo(os.path.join(self.tmp, "t.db"))
        self.repo.init_schema()

    def _make_bmp_evidence(self, device_id="dev01", round_ms=1000, sub=1, ts=100):
        bmp = self.repo.save_evidence(device_id, round_ms, sub, ts, b"", self.ev_dir)
        Image.new("RGB", (320, 240), (10, 120, 200)).save(bmp, "BMP")
        self.repo.insert_evidence_meta(device_id, round_ms, sub, ts, bmp, os.path.getsize(bmp))
        return bmp


class TestEvidenceMeta(EvidenceTestBase):
    def test_idempotent_insert(self):
        bmp = self._make_bmp_evidence()  # _make_bmp_evidence 内已首次入库
        size = os.path.getsize(bmp)
        # 同键重复到达 → 幂等命中 False，不重复入库
        self.assertFalse(self.repo.insert_evidence_meta("dev01", 1000, 1, 100, bmp, size))
        self.assertEqual(len(self.repo.list_evidence("dev01", 1000)), 1)
        # 不同 ts → 新记录
        self.assertTrue(self.repo.insert_evidence_meta("dev01", 1000, 1, 200, bmp, size))
        self.assertEqual(len(self.repo.list_evidence("dev01", 1000)), 2)

    def test_pending_conversion_and_writeback(self):
        self._make_bmp_evidence()
        self.assertEqual(len(self.repo.list_pending_conversion()), 1)
        converted, skipped, failed = EvidenceConverter(self.repo).convert_pending()
        self.assertEqual((converted, skipped, failed), (1, 0, 0))
        row = self.repo.list_evidence("dev01", 1000)[0]
        self.assertTrue(os.path.exists(row["jpg_path"]))
        self.assertTrue(os.path.exists(row["thumb_path"]))
        self.assertEqual(self.repo.list_pending_conversion(), [])

    def test_edge_path_registration_skipped(self):
        """整包兜底通道的端侧绝对路径（平台无文件）→ skip 不 failed。"""
        self.repo.insert_evidence_meta("dev01", 1000, 2, 200, "/edge/only/x.bmp", 0)
        converted, skipped, failed = EvidenceConverter(self.repo).convert_pending()
        self.assertEqual((converted, skipped, failed), (0, 1, 0))


class TestEvidenceAPI(EvidenceTestBase):
    def setUp(self):
        super().setUp()
        self.plugin = ReportRecvPlugin.__new__(ReportRecvPlugin)
        self.plugin._repo = self.repo
        self.plugin._merger = None
        self.plugin._evidence_dir = self.ev_dir
        self.plugin.logger = type(
            "L", (), {"info": staticmethod(lambda *a, **k: None),
                      "error": staticmethod(lambda *a, **k: None),
                      "warning": staticmethod(lambda *a, **k: None)})()
        app = FastAPI()
        self.plugin.register_routes(app, None)
        self.client = TestClient(app)

    def test_list_and_image_endpoints(self):
        self._make_bmp_evidence()
        EvidenceConverter(self.repo).convert_pending()

        r = self.client.get("/api/v1/evidence", params={"device_id": "dev01", "round_start_ms": 1000})
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["count"], 1)
        ev_id = body["data"]["evidence"][0]["id"]

        # 缺 device_id → 422
        self.assertEqual(self.client.get("/api/v1/evidence").status_code, 422)

        # JPG 展示图
        r = self.client.get(f"/api/v1/evidence/{ev_id}/image")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/jpeg")
        self.assertEqual(r.content[:2], b"\xff\xd8")

        # 缩略图
        r = self.client.get(f"/api/v1/evidence/{ev_id}/image", params={"thumb": 1})
        self.assertEqual(r.status_code, 200)

    def test_image_404(self):
        self.assertEqual(self.client.get("/api/v1/evidence/999/image").status_code, 404)
        # 端侧路径登记记录 → 文件不存在 → 404
        self.repo.insert_evidence_meta("dev01", 2000, 3, 300, "/edge/only/x.bmp", 0)
        rows = self.client.get(
            "/api/v1/evidence", params={"device_id": "dev01", "round_start_ms": 2000}
        ).json()["data"]["evidence"]
        self.assertEqual(self.client.get(f"/api/v1/evidence/{rows[0]['id']}/image").status_code, 404)


if __name__ == "__main__":
    unittest.main()
