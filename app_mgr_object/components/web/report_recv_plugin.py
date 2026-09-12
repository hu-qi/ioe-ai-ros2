"""
report_recv_plugin.py — 报告接收插件

工程基线: app_mgr_object-0.2.1
关联文档: doc/38 (整包 schema 1.0), doc/45 (增量 schema 1.1 + doc/58 统一计时)

职责:
  1. 接收 doc/38 整包报告, 解析入库 (六表)
  2. 接收 doc/45 增量事件, 追加到对应轮次事件流
  3. 实现 doc/45 §4 订阅管理 (多设备同时订阅)
  4. 接收 doc/45 §6 evidence 抓拍图 (multipart)
  5. 按去重键实现幂等 (整包 device_id+round.start_ms, 增量 INSERT OR IGNORE)
  6. 原始 JSON 完整留存, 支持未来深度分析

独立部署: 不硬依赖 P0 学员管理插件, 可独立运行 (软关联机制)
"""

import os
import json
import time
from typing import Dict, Any, Optional

from ...plugins.base_plugin import BasePlugin
from .report_repo import ReportRepo
from .event_merge import EventMerge


class ReportRecvPlugin(BasePlugin):
    """报告接收插件"""

    PLUGIN_NAME = "report_recv"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        # 数据库与存储路径配置
        self._db_path: str = self.config.get(
            "db_path",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "app.db")
        )
        self._raw_json_dir: str = self.config.get(
            "raw_json_dir",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "data", "reports")
        )
        self._evidence_dir: str = self.config.get(
            "evidence_dir",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "data", "evidence")
        )

        # 组件
        self._repo: Optional[ReportRepo] = None
        self._merger: Optional[EventMerge] = None

    def _configure_impl(self) -> bool:
        """配置插件: 初始化仓储、合并器、目录"""
        try:
            # 确保目录存在
            os.makedirs(self._raw_json_dir, exist_ok=True)
            os.makedirs(self._evidence_dir, exist_ok=True)

            # 初始化仓储
            self._repo = ReportRepo(self._db_path, self.logger)
            self._repo.init_schema()

            # 初始化事件合并器
            self._merger = EventMerge(self._repo, self.logger)

            self.logger.info(
                f"ReportRecvPlugin 配置完成: db={self._db_path} "
                f"raw_json_dir={self._raw_json_dir} evidence_dir={self._evidence_dir}"
            )
            return True
        except Exception as e:
            self.logger.error(f"ReportRecvPlugin 配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        """激活插件"""
        self.logger.info("ReportRecvPlugin 激活成功")
        return True

    def _deactivate_impl(self) -> bool:
        """停用插件"""
        self.logger.info("ReportRecvPlugin 停用")
        return True

    def _cleanup_impl(self) -> bool:
        """清理插件资源"""
        self.logger.info("ReportRecvPlugin 清理完成")
        return True

    # ------------------------------------------------------------------
    # 路由注册钩子 (供 web_server 调用)
    # ------------------------------------------------------------------
    def register_routes(self, app, templates) -> None:
        """
        注册报告接收路由组.

        路由清单 (doc/38 §1, doc/45 §2/§4/§6):
          POST /api/v1/reports                  接收整包报告
          GET  /api/v1/reports                  报告列表检索
          GET  /api/v1/reports/{report_id}      报告详情
          POST /api/v1/events                   接收增量事件
          POST /api/v1/subscriptions            订阅设备
          GET  /api/v1/subscriptions/{device_id} 查询订阅状态
          DELETE /api/v1/subscriptions/{device_id} 退订设备
          GET  /api/v1/subscriptions            订阅设备列表
          POST /api/v1/evidence                 接收抓拍图
        """
        from fastapi import Request, UploadFile, File, Form, HTTPException
        from fastapi.responses import JSONResponse, FileResponse

        repo = self._repo
        merger = self._merger
        logger = self.logger

        # ------------------------------------------------------------ #
        # 0. 报告管理页面
        # ------------------------------------------------------------ #
        @app.get("/reports")
        async def reports_page(request: Request):
            """报告管理页：列表多条件筛选 + 详情查看."""
            return templates.TemplateResponse(
                request, "reports.html"
            )

        # ------------------------------------------------------------ #
        # 1. 接收整包报告 (doc/38 §1)
        # ------------------------------------------------------------ #
        @app.post("/api/v1/reports")
        async def receive_full_report(request: Request):
            """接收 doc/38 整包报告, 解析入库, 原始 JSON 落盘."""
            try:
                payload = await request.json()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": f"JSON 解析失败: {e}", "data": {}}
                )

            # 基本校验
            if not payload.get("device_id") or not payload.get("round"):
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "缺必填字段 (device_id/round)", "data": {}}
                )

            device_id = payload["device_id"]
            round_data = payload["round"]
            start_ms = round_data.get("start_ms", 0)
            report_id = f"R{device_id}_{start_ms}"

            # 原始 JSON 落盘
            raw_path = repo.save_raw_json(
                device_id, report_id, payload, self._raw_json_dir
            )

            # 整包入库 (去重幂等)
            result_id, is_dup = repo.insert_full_report(payload, raw_json_path=raw_path)

            # P3: 整包兜底通道 — round.evidence[] 元数据入库（幂等键同实时通道）
            # file 为端侧绝对路径（平台无文件），仅作关联记录；本地转换时跳过不存在的路径
            try:
                for ev in (round_data.get("evidence") or []):
                    if not isinstance(ev, dict) or ev.get("sub") is None or ev.get("ts") is None:
                        continue
                    repo.insert_evidence_meta(
                        device_id, start_ms, int(ev.get("sub")), int(ev.get("ts")),
                        str(ev.get("file", "")), file_size=0
                    )
            except Exception as ev_err:
                logger.warning(f"整包 evidence 元数据写入异常（不阻塞）: {ev_err}")

            if is_dup:
                logger.info(f"整包去重命中 report_id={result_id}")

            # 发布事件总线事件 (供统计插件订阅)
            self._publish_event("report.received", {
                "report_id": result_id,
                "device_id": device_id,
                "student_id": (payload.get("student") or {}).get("id"),
                "is_duplicate": is_dup
            })

            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "report_id": result_id,
                    "device_id": device_id,
                    "finish_reason": round_data.get("finish_reason", ""),
                    "evidence": len(round_data.get("evidence") or []),
                }
            }

        # ------------------------------------------------------------ #
        # 2. 接收增量事件 (doc/45 §2)
        # ------------------------------------------------------------ #
        @app.post("/api/v1/events")
        async def receive_delta_events(request: Request):
            """接收 doc/45 增量事件, 追加到对应轮次事件流."""
            try:
                payload = await request.json()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": f"JSON 解析失败: {e}", "data": {}}
                )

            # 基本校验
            if payload.get("schema_version") != "1.1":
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "schema_version 必须为 1.1", "data": {}}
                )
            if not payload.get("device_id") or not payload.get("round_start_ms"):
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "缺必填字段 (device_id/round_start_ms)", "data": {}}
                )

            # 增量入库 (INSERT OR IGNORE 天然去重)
            inserted = merger.merge_delta_into_report(payload)

            # 发布实时增量事件 (供看板插件 WebSocket 推送)
            self._publish_event("report.realtime_delta", {
                "device_id": payload["device_id"],
                "round_start_ms": payload["round_start_ms"],
                "progress": payload.get("progress", {}),
                "events": payload.get("events", []),
                "inserted": inserted
            })

            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "device_id": payload["device_id"],
                    "delta_events": inserted
                }
            }

        # ------------------------------------------------------------ #
        # 3. 报告列表检索 (doc/38 §8 Mock 建议)
        # ------------------------------------------------------------ #
        @app.get("/api/v1/reports")
        async def list_reports(
            student_id: str = "",
            device_id: str = "",
            finish_reason: str = "",
            start_ms: int = 0,
            end_ms: int = 0,
            step_index: int = -1,
            page: int = 1,
            page_size: int = 20
        ):
            """报告列表检索 (多条件过滤 + 分页). step_index >= 0 时按步骤下钻过滤."""
            if page_size > 100:
                page_size = 100

            filters = {}
            if student_id:
                filters["student_id"] = student_id
            if device_id:
                filters["device_id"] = device_id
            if finish_reason:
                filters["finish_reason"] = finish_reason
            if start_ms:
                filters["start_ms"] = start_ms
            if end_ms:
                filters["end_ms"] = end_ms
            if step_index >= 0:
                filters["step_index"] = step_index

            result = repo.list_reports(filters, page, page_size)
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 4. 报告详情
        # ------------------------------------------------------------ #
        @app.get("/api/v1/reports/{report_id}")
        async def get_report_detail(report_id: str):
            """报告详情: reports + report_steps + report_substeps + report_events."""
            detail = repo.get_report_detail(report_id)
            if not detail:
                return JSONResponse(
                    status_code=404,
                    content={"code": 404, "message": "报告不存在", "data": {}}
                )
            return {"code": 0, "message": "ok", "data": detail}

        # ------------------------------------------------------------ #
        # 5. 订阅管理 (doc/45 §4, 多设备)
        # ------------------------------------------------------------ #
        @app.post("/api/v1/subscriptions")
        async def subscribe_device(request: Request):
            """订阅设备 (doc/dev01 §6, 可选统计能力).

            v3 (doc/83/84) 后端侧已移除订阅机制, 本接口仅保留用于
            平台侧统计/展示, 不再主动推送 notify_subscribe 到端侧。
            """
            try:
                payload = await request.json()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": f"JSON 解析失败: {e}", "data": {}}
                )

            device_id = payload.get("device_id")
            if not device_id:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "缺必填字段 device_id", "data": {}}
                )

            note = payload.get("note", "")
            result = repo.upsert_subscription(device_id, note)
            return {"code": 0, "message": "ok", "data": result}

        @app.get("/api/v1/subscriptions/{device_id}")
        async def get_subscription_status(device_id: str):
            """查询订阅状态 (doc/45 §4.2, doc/dev01 §6, 边缘端轮询用).

            未订阅设备返回 active=false（HTTP 200），而非 404——
            dev01 v2 下端侧轮询未订阅设备属正常态，不应报错。
            """
            sub = repo.get_subscription(device_id)
            if not sub:
                return {
                    "code": 0,
                    "message": "ok",
                    "data": {"device_id": device_id, "active": False}
                }
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "device_id": sub["device_id"],
                    "active": sub["active"] == 1,
                    "subscribed_at_ms": sub["subscribed_at_ms"]
                }
            }

        @app.delete("/api/v1/subscriptions/{device_id}")
        async def unsubscribe_device(device_id: str):
            """退订设备 (doc/45 §4.3). active 置 0."""
            result = repo.deactivate_subscription(device_id)
            return {"code": 0, "message": "ok", "data": result}

        @app.get("/api/v1/subscriptions")
        async def list_subscriptions():
            """订阅设备列表 (doc/45 §4.4)."""
            result = repo.list_subscriptions()
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 6. evidence 抓拍图接收 (doc/45 §6)
        # ------------------------------------------------------------ #
        @app.post("/api/v1/evidence")
        async def receive_evidence(
            file: UploadFile = File(...),
            sub: int = Form(...),
            ts: int = Form(...),
            device_id: str = Form(...),
            round_start_ms: Optional[int] = Form(None)
        ):
            """接收 evidence 抓拍图 (multipart/form-data, doc/dev01 §5)."""
            try:
                file_bytes = await file.read()
                # round_start_ms 可选（端侧推荐携带），缺省回退为 ts
                effective_round_start = round_start_ms if round_start_ms else ts
                saved_path = repo.save_evidence(
                    device_id, effective_round_start, sub, ts, file_bytes, self._evidence_dir
                )
                # P3: 元数据入库（幂等键 device_id+round_start_ms+sub+ts）
                is_new = repo.insert_evidence_meta(
                    device_id, effective_round_start, sub, ts,
                    saved_path, file_size=len(file_bytes)
                )
                logger.info(f"evidence 保存成功: {saved_path} (new={is_new})")
                return {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "saved": saved_path,
                        "path": saved_path,
                        "device_id": device_id,
                        "sub": str(sub),
                        "ts": str(ts),
                        "round_start_ms": str(effective_round_start),
                    }
                }
            except Exception as e:
                logger.error(f"evidence 接收失败: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"code": 500, "message": f"evidence 存储失败: {e}", "data": {}}
                )

        # ------------------------------------------------------------ #
        # 7. 证据列表/图片访问 (P3, doc/01 §七)
        # ------------------------------------------------------------ #
        @app.get("/api/v1/evidence")
        async def list_evidence(
            device_id: str = "",
            round_start_ms: int = 0,
            sub: int = 0,
            limit: int = 200
        ):
            """证据元数据列表（jpg_path 非空表示已转换可直接展示）。"""
            if not device_id:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "缺必填参数 device_id", "data": {}}
                )
            if limit > 500:
                limit = 500
            rows = repo.list_evidence(device_id, round_start_ms, sub, limit)
            return {"code": 0, "message": "ok",
                    "data": {"evidence": rows, "count": len(rows)}}

        @app.get("/api/v1/evidence/{evidence_id}/image")
        async def evidence_image(evidence_id: int, thumb: int = 0):
            """证据图访问: 默认 JPG 展示图; thumb=1 返回缩略图; 未转换时回退 BMP 原图。"""
            row = repo.get_evidence_by_id(evidence_id)
            if not row:
                return JSONResponse(
                    status_code=404,
                    content={"code": 404, "message": "证据不存在", "data": {}}
                )
            candidates = ([row.get("thumb_path"), row.get("jpg_path")] if thumb
                          else [row.get("jpg_path"), row.get("thumb_path")])
            candidates.append(row.get("file_path"))  # BMP 原图兜底
            for path in candidates:
                if path and os.path.exists(path):
                    media = "image/bmp" if path.lower().endswith(".bmp") else "image/jpeg"
                    return FileResponse(path, media_type=media)
            # 平台无该文件（端侧路径登记记录）
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": "证据文件不存在（端侧路径登记记录）", "data": {"device_id": row.get("device_id"), "file_path": row.get("file_path")}}
            )

        if logger:
            logger.info("ReportRecvPlugin 路由注册完成 (11 个端点)")
