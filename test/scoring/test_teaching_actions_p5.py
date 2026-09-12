#!/usr/bin/env python3
"""
test/scoring/test_teaching_actions_p5.py — P5 教学闭环测试

覆盖（doc/01 §6.4 / doc/02 §4.4）:
  - teaching_actions 表 CRUD（create/get/list）
  - 改进效果验证: 调整前后班级平均分/完成率/通过率对比 + trend 判定
  - HTTP 接口: POST/GET /api/v1/teaching_actions + /verify + 422/404
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app_mgr_object.components.web.analysis_repo import AnalysisRepo  # noqa: E402
from app_mgr_object.components.web.report_repo import ReportRepo  # noqa: E402
from app_mgr_object.plugins.report_analysis_plugin import ReportAnalysisPlugin  # noqa: E402

DAY = 24 * 3600 * 1000


class TeachingActionsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        ReportRepo(self.db).init_schema()
        self.repo = AnalysisRepo(self.db)
        self.repo.init_schema()
        self.now = int(time.time() * 1000)

        # 调整前 3 份低分报告（timeout/manual），调整后 3 份高分（completed）
        data = [(-15, 50, "timeout"), (-10, 55, "timeout"), (-5, 52, "manual"),
                (5, 75, "completed"), (10, 80, "completed"), (15, 82, "completed")]
        conn = self.repo._connect()
        for i, (off, score, reason) in enumerate(data):
            conn.execute(
                "INSERT INTO reports (report_id, device_id, student_cls, process_name, is_stub,"
                " start_ms, finish_reason, total_score, ts_upload_ms, created_at)"
                " VALUES (?,?,?,?,0,?,?,?,?,?)",
                (f"R{i}", "dev01", "一班", "拆解", 1000, reason, score,
                 self.now + off * DAY, self.now + off * DAY))
        conn.commit()
        conn.close()

    def _make_client(self):
        inst = ReportAnalysisPlugin.__new__(ReportAnalysisPlugin)
        inst._repo = self.repo
        inst._diagnosis_engine = None
        inst._cache_ttl_sec = 300
        inst.logger = None
        app = FastAPI()
        inst.register_routes(app, None)
        return TestClient(app, raise_server_exceptions=False)


class TestRepoCrud(TeachingActionsTestBase):
    def test_create_get_list(self):
        aid = self.repo.create_teaching_action({
            "description": "增加示范讲解", "class_name": "一班",
            "process_name": "拆解", "action_date": self.now,
        })
        got = self.repo.get_teaching_action(aid)
        self.assertEqual(got["description"], "增加示范讲解")
        self.assertEqual(got["class_name"], "一班")

        self.repo.create_teaching_action({
            "description": "二班调整", "class_name": "二班",
        })
        self.assertEqual(len(self.repo.list_teaching_actions()), 2)
        self.assertEqual(len(self.repo.list_teaching_actions(class_name="二班")), 1)

    def test_verify_trend_improved(self):
        aid = self.repo.create_teaching_action({
            "description": "拆解专项", "class_name": "一班",
            "process_name": "拆解", "action_date": self.now,
        })
        v = self.repo.verify_teaching_action(aid)
        self.assertEqual(v["before"]["report_count"], 3)
        self.assertEqual(v["after"]["report_count"], 3)
        self.assertGreater(v["delta"]["avg_score"], 0)
        self.assertEqual(v["trend"], "improved")

    def test_verify_no_data(self):
        aid = self.repo.create_teaching_action({
            "description": "无数据班", "class_name": "三班", "action_date": self.now,
        })
        v = self.repo.verify_teaching_action(aid)
        self.assertIsNone(v["before"])
        self.assertIsNone(v["after"])
        self.assertEqual(v["trend"], "no_data")

    def test_verify_missing_action(self):
        self.assertIsNone(self.repo.verify_teaching_action(999))


class TestHttpEndpoints(TeachingActionsTestBase):
    def test_create_list_verify_flow(self):
        client = self._make_client()

        r = client.post("/api/v1/teaching_actions", json={
            "description": "针对拆解步骤1增加示范讲解与专项练习",
            "class_name": "一班", "process_name": "拆解", "action_date": self.now,
        })
        self.assertEqual(r.json()["code"], 0)
        action_id = r.json()["data"]["action_id"]

        # 必填校验 → 422
        self.assertEqual(
            client.post("/api/v1/teaching_actions", json={"description": "x"}).status_code, 422)

        # 列表
        body = client.get("/api/v1/teaching_actions", params={"class_name": "一班"}).json()
        self.assertEqual(body["data"]["count"], 1)

        # 改进验证
        d = client.get(f"/api/v1/teaching_actions/{action_id}/verify").json()["data"]
        self.assertEqual(d["trend"], "improved")

        # 404
        self.assertEqual(
            client.get("/api/v1/teaching_actions/999/verify").status_code, 404)


if __name__ == "__main__":
    unittest.main()
