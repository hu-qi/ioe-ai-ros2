"""
teaching_dashboard_plugin.py — 教学看板插件

工程基线: app_mgr_object-0.2.1
关联文档: doc/72 教学看板插件开发方案

职责:
  1. 今日概览看板（考试人数、平均得分、通过率、待辅导学员数）
  2. 高频错误点 TOP5（遗漏率/超时率/顺序错误率最高的5个步骤，支持下钻）
  3. 需关注的学员列表（退步预警、波动较大、薄弱环节突出的学员，可点击进入学员详情页）
  4. 实时进度展示（订阅中设备的当前操作进度，30s 刷新）
  5. 教学改进验证（对比调整前后的班级平均分、完成率变化）

数据来源: 直连 reports / report_progress / diagnosis_results 表读聚合，
          不通过 P2 的 report_analysis_plugin API 间接调用（同库跨插件读惯例）。

实时推送: 订阅 P1 发布的 event_bus 事件 report.realtime_delta，
          转发到 web 层 WebSocket 推送到前端看板。
"""

import os
import json
import time
from typing import Dict, Any, Optional, List

from .base_plugin import BasePlugin
from ..components.web.dashboard_repo import DashboardRepo


class TeachingDashboardPlugin(BasePlugin):
    """教学看板插件"""

    PLUGIN_NAME = "teaching_dashboard"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        self._db_path: str = self.config.get(
            "db_path",
            os.path.join(os.path.dirname(__file__), "..", "config", "app.db")
        )

        # 看板参数
        self._refresh_interval_sec: int = int(self.config.get("refresh_interval_sec", 30))
        self._top_error_limit: int = int(self.config.get("top_error_limit", 5))
        self._pass_threshold: float = float(self.config.get("pass_threshold", 60.0))
        self._volatility_threshold: float = float(self.config.get("volatility_threshold", 15.0))
        self._attention_limit: int = int(self.config.get("attention_limit", 20))

        # 错误综合得分权重
        self._error_weights: dict = self.config.get("error_weights", {
            "omission": 0.4, "timeout": 0.4, "sequence_chaos": 0.2
        })

        # 组件
        self._repo: Optional[DashboardRepo] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def _configure_impl(self) -> bool:
        """配置插件：初始化仓储"""
        try:
            self._repo = DashboardRepo(self._db_path, self.logger)
            self._repo.init_schema()
            self.logger.info(f"TeachingDashboard 配置完成: db={self._db_path}")
            return True
        except Exception as e:
            self.logger.error(f"TeachingDashboard 配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        """激活插件：订阅 event_bus 实时增量事件"""
        # 订阅 P1 发布的实时增量事件，转发到 WebSocket
        if self.event_bus and hasattr(self.event_bus, 'subscribe'):
            try:
                self.event_bus.subscribe('report.realtime_delta',
                                         self._on_realtime_delta)
                self.logger.info("TeachingDashboard 已订阅 report.realtime_delta")
            except Exception as e:
                self.logger.warning(f"订阅 report.realtime_delta 失败（非致命）: {e}")
        else:
            self.logger.info("TeachingDashboard: event_bus 不可用，跳过订阅")

        self.logger.info("TeachingDashboard 激活成功")
        return True

    def _deactivate_impl(self) -> bool:
        self.logger.info("TeachingDashboard 停用")
        return True

    def _cleanup_impl(self) -> bool:
        self._repo = None
        return True

    # ------------------------------------------------------------------
    # event_bus 回调：实时增量 → WebSocket 推送
    # ------------------------------------------------------------------
    def _on_realtime_delta(self, data: dict) -> None:
        """
        收到增量事件 → 通过 WebSocket 推送到前端看板。
        复用 web_server.py 的 ConnectionManager.broadcast_json() 机制。
        """
        try:
            # 获取 web_server 的 ConnectionManager（通过 node 共享）
            conn_mgr = getattr(self.node, 'connection_manager', None) or \
                       getattr(self.node, 'web_server_connection_manager', None)
            if not conn_mgr:
                return

            # 构造推送消息
            message = {
                "type": "realtime_progress",
                "timestamp": time.time(),
                "data": {
                    "device_id": data.get("device_id"),
                    "round_start_ms": data.get("round_start_ms"),
                    "progress": data.get("progress", {}),
                    "events": data.get("events", [])
                }
            }

            # 通过事件循环广播
            if hasattr(conn_mgr, 'schedule_broadcast'):
                conn_mgr.schedule_broadcast(message)
            elif hasattr(conn_mgr, 'broadcast_json'):
                # 异步广播（需要在事件循环中执行）
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    loop.create_task(conn_mgr.broadcast_json(message))
                except RuntimeError:
                    pass  # 没有事件循环，跳过
        except Exception as e:
            if self.logger:
                self.logger.debug(f"实时增量推送失败: {e}")

    # ------------------------------------------------------------------
    # 路由注册钩子（由 web_server 调用）
    # ------------------------------------------------------------------
    def register_routes(self, app, templates) -> None:
        """
        注册教学看板路由组。

        路由清单 (doc/72 §4.3):
          GET /dashboard                          教学看板页面（HTML）
          GET /api/v1/dashboard/today_summary     今日概览
          GET /api/v1/dashboard/top_error_points  高频错误点 TOP5
          GET /api/v1/dashboard/attention_students 需关注的学员
          GET /api/v1/dashboard/realtime_progress  实时进度
          GET /api/v1/dashboard/improvement_validation 教学改进验证
        """
        from fastapi import Request
        from fastapi.responses import HTMLResponse, JSONResponse

        repo = self._repo
        logger = self.logger
        pass_threshold = self._pass_threshold
        top_error_limit = self._top_error_limit
        error_weights = self._error_weights
        volatility_threshold = self._volatility_threshold
        attention_limit = self._attention_limit

        # ------------------------------------------------------------ #
        # 0. 教学看板页面
        # ------------------------------------------------------------ #
        @app.get("/dashboard", response_class=HTMLResponse)
        async def dashboard_page(request: Request):
            return templates.TemplateResponse(request, "dashboard.html")

        # ------------------------------------------------------------ #
        # 1. 今日概览
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/today_summary")
        async def today_summary(process_name: str = ''):
            result = repo.get_today_summary(pass_threshold, process_name=process_name.strip())
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 2. 高频错误点 TOP5
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/top_error_points")
        async def top_error_points(limit: int = 0, process_name: str = ''):
            n = limit if limit > 0 else top_error_limit
            if n > 20:
                n = 20
            points = repo.get_top_error_points(limit=n, weights=error_weights,
                                               process_name=process_name.strip())
            return {"code": 0, "message": "ok",
                    "data": {"points": points, "count": len(points)}}

        # ------------------------------------------------------------ #
        # 3. 需关注的学员
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/attention_students")
        async def attention_students(limit: int = 0):
            n = limit if limit > 0 else attention_limit
            if n > 100:
                n = 100
            students = repo.get_attention_students(
                limit=n, volatility_threshold=volatility_threshold
            )
            return {"code": 0, "message": "ok",
                    "data": {"students": students, "count": len(students)}}

        # ------------------------------------------------------------ #
        # 4. 实时进度展示
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/realtime_progress")
        async def realtime_progress():
            devices = repo.get_realtime_progress()
            return {"code": 0, "message": "ok",
                    "data": {"devices": devices, "count": len(devices)}}

        # ------------------------------------------------------------ #
        # 5. 教学改进验证
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/improvement_validation")
        async def improvement_validation(
            cls: str = '',
            process_name: str = '',
            before_start: int = 0,
            before_end: int = 0,
            after_start: int = 0,
            after_end: int = 0
        ):
            if not cls:
                return JSONResponse(
                    status_code=422,
                    content={"code": 422, "message": "cls 不能为空", "data": {}}
                )
            if not (before_start and before_end and after_start and after_end):
                return JSONResponse(
                    status_code=422,
                    content={"code": 422,
                             "message": "需提供 before_start/before_end/after_start/after_end",
                             "data": {}}
                )

            result = repo.get_improvement_validation(
                cls=cls,
                before_range={"date_start": before_start, "date_end": before_end},
                after_range={"date_start": after_start, "date_end": after_end},
                pass_threshold=pass_threshold,
                process_name=process_name.strip()
            )
            return {"code": 0, "message": "ok", "data": result}

        # ------------------------------------------------------------ #
        # 6. 大屏：最近预警列表（诊断全类型 + 异常报告）
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/recent_alerts")
        async def recent_alerts(limit: int = 0, hours: int = 72):
            n = limit if limit > 0 else 30
            if n > 100:
                n = 100
            alerts = repo.get_recent_alerts(limit=n, hours=hours)
            return {"code": 0, "message": "ok",
                    "data": {"alerts": alerts, "count": len(alerts)}}

        # ------------------------------------------------------------ #
        # 7. 大屏：近 N 天成绩趋势
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/score_trend")
        async def score_trend(days: int = 7, cls: str = '', process_name: str = ''):
            if days <= 0:
                days = 7
            if days > 90:
                days = 90
            trend = repo.get_score_trend_cached(
                days=days, pass_threshold=pass_threshold,
                cls=cls.strip(), process_name=process_name.strip()
            )
            return {"code": 0, "message": "ok",
                    "data": {"trend": trend, "days": days}}

        # ------------------------------------------------------------ #
        # 8. 大屏：近 N 天班级对比
        # ------------------------------------------------------------ #
        @app.get("/api/v1/dashboard/class_comparison")
        async def class_comparison(days: int = 30, process_name: str = ''):
            if days <= 0:
                days = 30
            if days > 365:
                days = 365
            classes = repo.get_class_comparison_cached(
                days=days, pass_threshold=pass_threshold,
                process_name=process_name.strip()
            )
            return {"code": 0, "message": "ok",
                    "data": {"classes": classes, "count": len(classes)}}

        if logger:
            logger.info("TeachingDashboardPlugin 路由注册完成 (6 个端点)")
