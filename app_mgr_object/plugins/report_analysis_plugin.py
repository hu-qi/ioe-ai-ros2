"""
report_analysis_plugin.py — 统计分析插件

工程基线: app_mgr_object-0.2.1
关联文档: doc/71 统计分析插件开发方案

职责:
  1. 步骤用时分布统计（AVG / 合规率 / SOP 对比）
  2. 学员累计统计（考试次数 / 平均得分 / 完成率趋势 / 薄弱步骤 TOP3）
  3. 步骤瓶颈诊断（4 类阈值规则，对齐需求说明.docx §3.3.3）
  4. 教学建议生成（每条诊断结果配对"教官行动建议"文本）
  5. 统计结果缓存（避免重复计算，TTL 300s）

跨插件读库合法性: 既有 smart_trigger_plugin 跨插件读 task_cache，
本插件跨插件读 reports 系列表做统计聚合，符合既有"同库跨插件读"惯例。
"""

import os
import json
import time
from typing import Dict, Any, Optional, List

from .base_plugin import BasePlugin
from ..components.web.analysis_repo import AnalysisRepo
from ..components.web.diagnosis_engine import DiagnosisEngine


class ReportAnalysisPlugin(BasePlugin):
    """统计分析插件"""

    PLUGIN_NAME = "report_analysis"
    PLUGIN_VERSION = "1.0.0"

    # 默认诊断阈值（对齐需求说明.docx §3.3.3）
    DEFAULT_THRESHOLDS = {
        "bottleneck_multiplier": 1.5,
        "persistent_error_rate": 0.30,
        "sequence_chaos_rate": 0.20,
        "regression_window_recent": 3,
        "regression_window_history": 5,
        "regression_threshold": 0.85,
    }

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        self._db_path: str = self.config.get(
            "db_path",
            os.path.join(os.path.dirname(__file__), "..", "config", "app.db")
        )
        schema_path = self.config.get(
            "schema_path",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "analysis_schema.sql")
        )
        self._schema_path: str = schema_path

        # SOP 标准用时来源
        self._sop_model_paths: dict = self.config.get("sop_model_paths", {})

        # 诊断阈值
        self._thresholds: dict = dict(self.DEFAULT_THRESHOLDS)
        self._thresholds.update(self.config.get("thresholds", {}))

        # 缓存
        self._cache_ttl_sec: int = int(self.config.get("cache_ttl_sec", 300))

        # 分页
        self._page_size_default: int = int(self.config.get("page_size", 20))
        self._page_size_max: int = int(self.config.get("page_size_max", 100))

        # 组件
        self._repo: Optional[AnalysisRepo] = None
        self._diagnosis_engine: Optional[DiagnosisEngine] = None
        self._sop_standards: Dict[str, Dict[int, float]] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def _configure_impl(self) -> bool:
        """配置插件：初始化仓储、诊断引擎、加载 SOP 标准"""
        try:
            self._repo = AnalysisRepo(
                self._db_path, self.logger, schema_path=self._schema_path
            )
            self._repo.init_schema()

            # 加载 SOP 标准用时
            self._load_sop_standards()

            self._diagnosis_engine = DiagnosisEngine(
                repo=self._repo,
                thresholds=self._thresholds,
                sop_standards=self._sop_standards,
                logger=self.logger
            )

            self.logger.info(f"ReportAnalysis 配置完成: db={self._db_path}")
            return True
        except Exception as e:
            self.logger.error(f"ReportAnalysis 配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        self.logger.info("ReportAnalysis 激活成功")
        return True

    def _deactivate_impl(self) -> bool:
        self.logger.info("ReportAnalysis 停用")
        return True

    def _cleanup_impl(self) -> bool:
        self._repo = None
        self._diagnosis_engine = None
        return True

    # ------------------------------------------------------------------
    # SOP 标准用时加载
    # ------------------------------------------------------------------
    def _load_sop_standards(self):
        """
        从 model JSON 加载步骤标准用时。
        缺省策略：若文件不存在或无 standard_duration_ms 字段，
        降级为"仅统计实际用时，不做合规判断"（doc/71 §6 降级）。
        """
        for process_type, path in self._sop_model_paths.items():
            try:
                if not os.path.exists(path):
                    if self.logger:
                        self.logger.info(f"SOP model JSON 不存在: {path}，降级为仅统计")
                    continue

                with open(path, "r", encoding="utf-8") as f:
                    model = json.load(f)

                # model JSON 格式约定（doc/71 §3.2）：
                # {"steps": [{"idx": 1, "name": "...", "standard_duration_ms": 8000}, ...]}
                standards: Dict[int, float] = {}
                steps = model.get("steps", [])
                if isinstance(steps, list):
                    for step in steps:
                        idx = step.get("idx")
                        std_ms = step.get("standard_duration_ms")
                        if idx is not None and std_ms is not None:
                            standards[int(idx)] = float(std_ms)

                if standards:
                    self._sop_standards[process_type] = standards
                    if self.logger:
                        self.logger.info(
                            f"SOP 标准用时已加载: {process_type}, {len(standards)} 个步骤"
                        )
                else:
                    if self.logger:
                        self.logger.info(
                            f"SOP model JSON 无 standard_duration_ms 字段: {path}，降级"
                        )
            except (json.JSONDecodeError, IOError) as e:
                if self.logger:
                    self.logger.warning(f"SOP model JSON 加载失败: {path}, {e}")

    # ------------------------------------------------------------------
    # 路由注册钩子（由 web_server 调用）
    # ------------------------------------------------------------------
    def register_routes(self, app, templates) -> None:
        """
        注册统计分析路由组。

        路由清单 (doc/71 §5.4):
          GET /api/v1/analysis/step_duration      步骤用时分布统计
          GET /api/v1/analysis/student_cumulative  学员累计统计
          GET /api/v1/analysis/class_summary       班级汇总
          GET /api/v1/analysis/diagnosis           综合诊断（4 类阈值）
          GET /api/v1/analysis/diagnoses           诊断结果列表
        """
        from fastapi import Request
        from fastapi.responses import JSONResponse

        repo = self._repo
        engine = self._diagnosis_engine
        cache_ttl = self._cache_ttl_sec
        logger = self.logger

        # ------------------------------------------------------------ #
        # 1. 步骤用时分布统计
        # ------------------------------------------------------------ #
        @app.get("/api/v1/analysis/step_duration")
        async def step_duration_stats(
            cls: str = '',
            device_id: str = '',
            student_id: str = '',
            process_name: str = '',
            date_start: int = 0,
            date_end: int = 0
        ):
            filters = {
                "cls": cls.strip(),
                "device_id": device_id.strip(),
                "student_id": student_id.strip(),
                "process_name": process_name.strip(),
                "date_start": date_start,
                "date_end": date_end,
            }
            cache_key = f"step_duration|{json.dumps(filters, sort_keys=True)}"
            cached = repo.get_cached_result(cache_key, cache_ttl)
            if cached is not None:
                return {"code": 0, "message": "ok", "data": cached}

            result = repo.get_step_duration_stats(filters)
            report_count = result.get("report_count", 0)
            repo.save_cached_result(cache_key, "step_duration", filters, result, report_count)
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 2. 学员累计统计
        # ------------------------------------------------------------ #
        @app.get("/api/v1/analysis/student_cumulative")
        async def student_cumulative_stats(
            student_id: str = '',
            process_name: str = '',
            date_start: int = 0,
            date_end: int = 0
        ):
            if not student_id:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "student_id 不能为空", "data": {}}
                )
            date_range = {"date_start": date_start, "date_end": date_end}
            result = repo.get_student_cumulative_stats(student_id, date_range, process_name=process_name.strip())
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 3. 班级汇总
        # ------------------------------------------------------------ #
        @app.get("/api/v1/analysis/class_summary")
        async def class_summary_stats(
            cls: str = '',
            process_name: str = '',
            date_start: int = 0,
            date_end: int = 0
        ):
            if not cls:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "cls 不能为空", "data": {}}
                )
            date_range = {"date_start": date_start, "date_end": date_end}
            result = repo.get_class_summary(cls, date_range, process_name=process_name.strip())
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 4. 综合诊断（4 类阈值规则）
        # ------------------------------------------------------------ #
        @app.get("/api/v1/analysis/diagnosis")
        async def diagnosis(
            scope: str = 'class',
            cls: str = '',
            student_id: str = '',
            date_start: int = 0,
            date_end: int = 0,
            process_name: str = ''
        ):
            date_range = {"date_start": date_start, "date_end": date_end}
            diagnoses = engine.diagnose_all(
                cls=cls.strip(),
                student_id=student_id.strip(),
                date_range=date_range,
                process_name=process_name.strip()
            )

            # 持久化诊断结果
            for d in diagnoses:
                d["diagnosis_id"] = repo.save_diagnosis(d)

            return {
                "code": 0, "message": "ok",
                "data": {
                    "diagnoses": diagnoses,
                    "count": len(diagnoses)
                }
            }

        # ------------------------------------------------------------ #
        # 5. 诊断结果列表查询
        # ------------------------------------------------------------ #
        @app.get("/api/v1/analysis/diagnoses")
        async def list_diagnoses(
            diagnosis_type: str = '',
            target_id: str = '',
            limit: int = 100
        ):
            if limit > 500:
                limit = 500
            results = repo.list_diagnoses(
                diagnosis_type=diagnosis_type.strip(),
                target_id=target_id.strip(),
                limit=limit
            )
            return {
                "code": 0, "message": "ok",
                "data": {"diagnoses": results, "count": len(results)}
            }

        # ------------------------------------------------------------ #
        # 6. 教学闭环 (P5, doc/01 §6.4 / doc/02 §4.4)
        # ------------------------------------------------------------ #
        @app.post("/api/v1/teaching_actions")
        async def create_teaching_action(request: Request):
            """记录教学调整事件。必填: description / class_name; 可选: action_date(ms)/target_substep/process_name。"""
            try:
                payload = await request.json()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"code": 400, "message": f"JSON 解析失败: {e}", "data": {}}
                )
            if not payload.get("description") or not payload.get("class_name"):
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "缺必填字段 (description/class_name)", "data": {}}
                )
            action_id = repo.create_teaching_action(payload)
            return {"code": 0, "message": "ok", "data": {"action_id": action_id}}

        @app.get("/api/v1/teaching_actions")
        async def list_teaching_actions(
            class_name: str = '',
            process_name: str = '',
            limit: int = 50
        ):
            """教学调整事件列表（时间倒序）。"""
            if limit > 200:
                limit = 200
            actions = repo.list_teaching_actions(
                class_name=class_name.strip(),
                process_name=process_name.strip(),
                limit=limit
            )
            return {"code": 0, "message": "ok",
                    "data": {"actions": actions, "count": len(actions)}}

        @app.get("/api/v1/teaching_actions/{action_id}/verify")
        async def verify_teaching_action(action_id: int):
            """改进效果验证: 对比调整前后班级平均分/完成率/通过率（前后各 30 天窗口）。"""
            result = repo.verify_teaching_action(action_id)
            if result is None:
                return JSONResponse(
                    status_code=404,
                    content={"code": 404, "message": "教学调整事件不存在", "data": {}}
                )
            return {"code": 0, "message": "ok", "data": result}

        if logger:
            logger.info("ReportAnalysisPlugin 路由注册完成 (8 个端点)")
