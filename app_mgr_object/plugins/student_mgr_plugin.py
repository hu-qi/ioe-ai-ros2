"""
student_mgr_plugin.py — 学员管理插件

工程基线: app_mgr_object-0.2.1
关联文档: doc/69 学员管理插件开发方案

职责:
  1. 学员档案 CRUD（工号唯一性校验、软删除）
  2. 分页列表 + 多条件模糊检索（姓名/工号/班级）
  3. CSV 批量导入（upsert，单事务原子提交）
  4. CSV 导出（按当前检索条件导出全量）
  5. 学员详情页骨架（档案 + 历史考试记录占位）

独立业务域: 与现有 AGV/仓位/任务域完全解耦，仅依赖 BasePlugin + web_server 路由注册。
"""

import csv
import io
import os
import time
from typing import Dict, Any, Optional, List

from .base_plugin import BasePlugin
from ..components.web.student_repo import StudentRepo


class StudentMgrPlugin(BasePlugin):
    """学员管理插件"""

    PLUGIN_NAME = "student_mgr"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        self._db_path: str = self.config.get(
            "db_path",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "app.db")
        )
        schema_path = self.config.get(
            "schema_path",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "students_schema.sql")
        )
        self._schema_path: str = schema_path
        self._page_size_default: int = int(self.config.get("page_size", 20))
        self._page_size_max: int = int(self.config.get("page_size_max", 100))
        self._import_max_rows: int = int(self.config.get("import_max_rows", 1000))
        self._repo: Optional[StudentRepo] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def _configure_impl(self) -> bool:
        """配置插件：初始化仓储、建表"""
        try:
            self._repo = StudentRepo(
                self._db_path, self.logger, schema_path=self._schema_path
            )
            self._repo.init_schema()
            self.logger.info(f"StudentMgr 配置完成: db={self._db_path}")
            return True
        except Exception as e:
            self.logger.error(f"StudentMgr 配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        """激活插件：web 路由注册由 web_server 启动时调用 register_routes"""
        self.logger.info("StudentMgr 激活成功")
        return True

    def _deactivate_impl(self) -> bool:
        self.logger.info("StudentMgr 停用")
        return True

    def _cleanup_impl(self) -> bool:
        self._repo = None
        return True

    # ------------------------------------------------------------------
    # 路由注册钩子（由 web_server 调用）
    # ------------------------------------------------------------------
    def _query_recent_reports(self, student_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        查询学员最近的考试报告（P1 reports 表，doc/70）。

        与报告接收插件共用 config/app.db；reports 表不存在时（P1 未部署）
        降级为空列表，保持学员插件可独立部署。
        """
        import sqlite3
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """SELECT report_id, device_id, process_name, process_type,
                              finish_reason, is_stub, duration_ms, total_score, ts_upload_ms
                       FROM reports
                       WHERE student_id = ?
                       ORDER BY ts_upload_ms DESC
                       LIMIT ?""",
                    (student_id, limit)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        except sqlite3.OperationalError:
            # reports 表尚未建表（P1 未部署）→ 独立部署降级
            return []

    def register_routes(self, app, templates) -> None:
        """
        注册学员管理路由组。

        路由清单 (doc/69 §5.1):
          GET    /students                       学员管理页面（HTML）
          GET    /api/v1/students                分页列表 + 检索
          GET    /api/v1/students/{student_id}   学员详情
          POST   /api/v1/students                新增学员
          PUT    /api/v1/students/{student_id}   修改学员
          DELETE /api/v1/students/{student_id}   软删除学员
          POST   /api/v1/students/import         CSV 批量导入
          GET    /api/v1/students/export         导出 CSV
        """
        from fastapi import Request, UploadFile, File, HTTPException
        from fastapi.responses import JSONResponse, StreamingResponse

        repo = self._repo
        logger = self.logger
        page_size_default = self._page_size_default
        page_size_max = self._page_size_max
        import_max_rows = self._import_max_rows

        # ------------------------------------------------------------ #
        # 0. 学员管理页面
        # ------------------------------------------------------------ #
        @app.get("/students", response_class=None)
        async def students_page(request: Request):
            from fastapi.responses import HTMLResponse
            return HTMLResponse(
                templates.TemplateResponse("students.html", {"request": request})
                .body.decode("utf-8")
                if hasattr(templates, "TemplateResponse") else ""
            )

        # ------------------------------------------------------------ #
        # 1. 分页列表 + 检索
        # ------------------------------------------------------------ #
        @app.get("/api/v1/students")
        async def list_students(
            keyword: str = '',
            cls: str = '',
            status: str = 'active',
            page: int = 1,
            page_size: int = 0
        ):
            ps = page_size if page_size > 0 else page_size_default
            if ps > page_size_max:
                ps = page_size_max
            if page < 1:
                page = 1
            result = repo.list(
                keyword=keyword.strip(),
                cls=cls.strip(),
                status=status,
                page=page,
                page_size=ps
            )
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 2. CSV 导出（必须在 {student_id} 路由之前注册，否则被当成 student_id）
        # ------------------------------------------------------------ #
        @app.get("/api/v1/students/export")
        async def export_students(
            keyword: str = '',
            cls: str = '',
            status: str = 'active'
        ):
            result = repo.list(
                keyword=keyword.strip(),
                cls=cls.strip(),
                status=status,
                page=1,
                page_size=100000
            )
            students: List[dict] = result.get("list", [])

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "name", "cls", "trade", "enroll_date", "status", "remark"])
            for s in students:
                writer.writerow([
                    s.get("id", ""),
                    s.get("name", ""),
                    s.get("cls", "") or "",
                    s.get("trade", "") or "",
                    s.get("enroll_date", "") or "",
                    s.get("status", ""),
                    s.get("remark", "") or "",
                ])

            date_str = time.strftime("%Y%m%d", time.localtime())
            filename = f"students_{date_str}.csv"
            csv_bytes = b'\xef\xbb\xbf' + output.getvalue().encode('utf-8')

            return StreamingResponse(
                io.BytesIO(csv_bytes),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
            )

        # ------------------------------------------------------------ #
        # 3. 学员详情
        # ------------------------------------------------------------ #
        @app.get("/api/v1/students/{student_id}")
        async def get_student(student_id: str):
            student = repo.get(student_id)
            if not student:
                return JSONResponse(
                    status_code=404,
                    content={"code": 404, "message": "学员不存在", "data": {}}
                )
            recent_reports = self._query_recent_reports(student_id)
            return {
                "code": 0, "message": "ok",
                "data": {"student": student, "recent_reports": recent_reports}
            }

        # ------------------------------------------------------------ #
        # 4. 新增学员
        # ------------------------------------------------------------ #
        @app.post("/api/v1/students")
        async def create_student(request: Request):
            try:
                payload = await request.json()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": f"JSON 解析失败: {e}", "data": {}}
                )

            # 基本校验
            sid = (payload.get("id") or "").strip()
            name = (payload.get("name") or "").strip()
            err = StudentRepo.validate_id(sid)
            if err:
                return JSONResponse(status_code=422,
                                    content={"code": 422, "message": err, "data": {}})
            err = StudentRepo.validate_name(name)
            if err:
                return JSONResponse(status_code=422,
                                    content={"code": 422, "message": err, "data": {}})

            # 字段长度校验
            for field, val in [("cls", payload.get("cls")),
                               ("trade", payload.get("trade"))]:
                v = (val or "").strip()
                if len(v) > 32:
                    return JSONResponse(
                        status_code=422,
                        content={"code": 422, "message": f"{field} 长度不能超过32", "data": {}}
                    )

            enroll = (payload.get("enroll_date") or "").strip()
            err = StudentRepo.validate_enroll_date(enroll)
            if err:
                return JSONResponse(status_code=422,
                                    content={"code": 422, "message": err, "data": {}})

            remark = (payload.get("remark") or "").strip()
            if len(remark) > 200:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "备注长度不能超过200", "data": {}}
                )

            try:
                new_id = repo.create(payload)
                self._publish_event("student.created", {"id": new_id})
                return {"code": 0, "message": "ok", "data": {"id": new_id}}
            except ValueError as e:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": str(e), "data": {}}
                )
            except Exception as e:
                logger.error(f"新增学员失败: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"code": 500, "message": f"内部错误: {e}", "data": {}}
                )

        # ------------------------------------------------------------ #
        # 4. 修改学员
        # ------------------------------------------------------------ #
        @app.put("/api/v1/students/{student_id}")
        async def update_student(student_id: str, request: Request):
            try:
                payload = await request.json()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": f"JSON 解析失败: {e}", "data": {}}
                )

            # 工号不可改
            if "id" in payload and payload["id"] != student_id:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "工号不可修改", "data": {}}
                )

            # 校验可选字段
            for field, val in [("cls", payload.get("cls")),
                               ("trade", payload.get("trade"))]:
                v = (val or "").strip() if val else ""
                if len(v) > 32:
                    return JSONResponse(
                        status_code=422,
                        content={"code": 422, "message": f"{field} 长度不能超过32", "data": {}}
                    )

            enroll = (payload.get("enroll_date") or "").strip() if payload.get("enroll_date") else ""
            err = StudentRepo.validate_enroll_date(enroll)
            if err:
                return JSONResponse(status_code=422,
                                    content={"code": 422, "message": err, "data": {}})

            remark = (payload.get("remark") or "").strip() if payload.get("remark") else ""
            if len(remark) > 200:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "备注长度不能超过200", "data": {}}
                )

            try:
                found = repo.update(student_id, payload)
                if not found:
                    return JSONResponse(
                        status_code=404,
                        content={"code": 404, "message": "学员不存在", "data": {}}
                    )
                self._publish_event("student.updated", {"id": student_id})
                return {"code": 0, "message": "ok", "data": {"id": student_id}}
            except ValueError as e:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": str(e), "data": {}}
                )
            except Exception as e:
                logger.error(f"修改学员失败: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"code": 500, "message": f"内部错误: {e}", "data": {}}
                )

        # ------------------------------------------------------------ #
        # 5. 软删除学员
        # ------------------------------------------------------------ #
        @app.delete("/api/v1/students/{student_id}")
        async def delete_student(student_id: str):
            found = repo.soft_delete(student_id)
            if not found:
                return JSONResponse(
                    status_code=404,
                    content={"code": 404, "message": "学员不存在", "data": {}}
                )
            self._publish_event("student.deleted", {"id": student_id})
            return {"code": 0, "message": "ok", "data": {"id": student_id}}

        # ------------------------------------------------------------ #
        # 6. CSV 批量导入
        # ------------------------------------------------------------ #
        @app.post("/api/v1/students/import")
        async def import_students(file: UploadFile = File(...)):
            # 读取文件内容
            try:
                content = await file.read()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": f"文件读取失败: {e}", "data": {}}
                )

            # 解码（UTF-8，兼容 BOM）
            if content.startswith(b'\xef\xbb\xbf'):
                content = content[3:]
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": "CSV 编码应为 UTF-8", "data": {}}
                )

            # 解析 CSV
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames or 'id' not in reader.fieldnames or 'name' not in reader.fieldnames:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": "CSV 表头需含 id, name 列", "data": {}}
                )

            rows: List[dict] = []
            errors: List[dict] = []
            for i, raw in enumerate(reader, start=2):  # 行号从 2 开始（1 行表头）
                sid = (raw.get("id") or "").strip()
                name = (raw.get("name") or "").strip()

                # 逐行校验
                err = StudentRepo.validate_id(sid)
                if err:
                    errors.append({"row": i, "reason": err})
                    continue
                err = StudentRepo.validate_name(name)
                if err:
                    errors.append({"row": i, "reason": err})
                    continue

                rows.append({
                    "id": sid,
                    "name": name,
                    "cls": (raw.get("cls") or "").strip(),
                    "trade": (raw.get("trade") or "").strip(),
                    "enroll_date": (raw.get("enroll_date") or "").strip(),
                    "remark": (raw.get("remark") or "").strip(),
                })

            # 行数上限校验
            total_rows = len(rows) + len(errors)
            if total_rows > import_max_rows:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422,
                             "message": f"导入行数超过上限 {import_max_rows}",
                             "data": {}}
                )

            # 批量 upsert
            success_count = 0
            failed_count = len(errors)
            try:
                repo.bulk_upsert(rows)
                success_count = len(rows)
            except ValueError as e:
                # bulk_upsert 内部校验失败
                errors.append({"row": 0, "reason": str(e)})
                failed_count = len(errors)
            except Exception as e:
                logger.error(f"CSV 批量导入失败: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"code": 500, "message": f"导入失败: {e}", "data": {}}
                )

            return {
                "code": 0, "message": "ok",
                "data": {
                    "success": success_count,
                    "failed": failed_count,
                    "errors": errors
                }
            }

        if logger:
            logger.info("StudentMgrPlugin 路由注册完成 (8 个端点)")
