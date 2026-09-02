#!/usr/bin/env python3
"""
回调处理器插件 - 通用版本
提供基于FastAPI的回调服务器，支持动态路由注册

RCS 回调扩展 (Phase 2):
- /agvCallback   -> 任务执行状态通知
- /warnCallback  -> 告警推送通知
- /bindNotify    -> 绑定/解绑通知
"""

import time
from typing import Dict, Any, Optional, Callable

from .base_plugin import BasePlugin
from ..components.callback.receiver import CallbackReceiver


class CallbackHandlerPlugin(BasePlugin):
    """回调处理器插件，封装CallbackReceiver，允许其他插件注册HTTP端点"""

    PLUGIN_NAME = "callback_handler"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        self.receiver: Optional[CallbackReceiver] = None
        self._host = self.config.get('host', '0.0.0.0')
        self._port = self.config.get('port', 8080)
        self._base_path = self.config.get('base_path', '/eyeSky/robot/reporter')
        self._rcs_enabled = self.config.get('rcs_callbacks_enabled', True)

    def _configure_impl(self) -> bool:
        """创建CallbackReceiver实例，但不启动"""
        try:
            # 如果节点有参数管理器，可以覆盖配置
            if hasattr(self.node, 'param_manager'):
                pm = self.node.param_manager
                self._host = pm.get_param('callback_host', self._host)
                self._port = pm.get_param('callback_port', self._port)
                self._base_path = pm.get_param('callback_base_path', self._base_path)

            receiver_config = {
                'host': self._host,
                'port': self._port,
                'base_path': self._base_path,
                'enable_docs': self.config.get('enable_docs', False)
            }

            self.receiver = CallbackReceiver(logger=self.logger, config=receiver_config)

            # 注册默认健康检查路由
            self.receiver.register_get("/health", self._health_check)

            # 将自身挂载到节点，供其他插件注册路由
            self.node.callback_handler = self

            self.logger.info(f"回调处理器插件配置完成: {self._host}:{self._port}{self._base_path}")
            return True
        except Exception as e:
            self.logger.error(f"回调处理器插件配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        """激活回调服务器：先注册路由，再启动"""
        if not self.receiver:
            self.logger.error("回调接收器未初始化")
            return False

        # 注册 RCS 回调路由（在启动前注册） ===
        if self._rcs_enabled:
            self.register_rcs_callbacks()
        else:
            self.logger.info("RCS 回调已禁用（rcs_callbacks_enabled=False）")
            
        # === 直接添加绝对路径路由，绕过 base_path ===
        if self.receiver and hasattr(self.receiver, 'app'):
            try:
                self.receiver.app.add_api_route(
                    '/eyeSky/robot/reporter/agvCallback',
                    self._on_agv_callback,
                    methods=['POST']
                )
                self.receiver.app.add_api_route(
                    '/eyeSky/robot/reporter/warnCallback',
                    self._on_warn_callback,
                    methods=['POST']
                )
                self.receiver.app.add_api_route(
                    '/eyeSky/robot/reporter/bindNotify',
                    self._on_bind_notify,
                    methods=['POST']
                )
                self.logger.info("已注册绝对路径的 RCS 回调路由（/eyeSky/robot/reporter/*）")
            except Exception as e:
                self.logger.error(f"注册绝对路径路由失败: {e}")

        # 启动 HTTP 服务器
        success = self.receiver.start()
        if success:
            self.logger.info("回调服务器已启动")
        else:
            self.logger.error("回调服务器启动失败")
        return success

    def _deactivate_impl(self) -> bool:
        """停止回调服务器"""
        if self.receiver:
            self.receiver.stop()
        return True

    def _cleanup_impl(self) -> bool:
        self.receiver = None
        return True

    # ---------- 公共路由注册接口 ----------
    def register_route(self, path: str, method: str, callback: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """注册一个自定义HTTP端点"""
        if self.receiver:
            self.receiver.register_route(path, method, callback)
            self.logger.info(f"注册路由: {method} {self._base_path}{path}")
        else:
            self.logger.error("回调接收器未初始化，无法注册路由")

    def register_post(self, path: str, callback: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """快捷注册POST路由"""
        self.register_route(path, 'POST', callback)

    def register_get(self, path: str, callback: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """快捷注册GET路由"""
        self.register_route(path, 'GET', callback)

    def _health_check(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """默认健康检查"""
        return {
            'status': 'ok',
            'timestamp': time.time(),
            'plugin': self.PLUGIN_NAME,
            'version': self.PLUGIN_VERSION
        }

    # ═══════════════════════════════════════════════════════════════
    #  RCS 回调路由注册与处理（业务逻辑）
    # ═══════════════════════════════════════════════════════════════

    def register_rcs_callbacks(self) -> bool:
        """
        注册 RCS 三个回调路由到 CallbackReceiver。

        Returns:
            bool: 注册成功返回 True
        """
        if not self.receiver:
            self.logger.error("CallbackReceiver 未初始化，无法注册 RCS 回调")
            return False

        try:
            # 1. 任务执行状态通知
            self.receiver.register_json_post('/agvCallback', self._on_agv_callback)
            self.logger.info("已注册 RCS 回调路由: POST /agvCallback")

            # 2. 告警推送通知
            self.receiver.register_json_post('/warnCallback', self._on_warn_callback)
            self.logger.info("已注册 RCS 回调路由: POST /warnCallback")

            # 3. 绑定/解绑通知
            self.receiver.register_json_post('/bindNotify', self._on_bind_notify)
            self.logger.info("已注册 RCS 回调路由: POST /bindNotify")

            return True

        except Exception as e:
            self.logger.error(f"注册 RCS 回调路由失败: {e}")
            return False

    def _on_agv_callback(self, data: dict) -> dict:
        """
        处理 agvCallback → 发布 rcs.agv_callback 事件

        Args:
            data: RCS 推送的 JSON body（示例结构见指南）

        Returns:
            标准响应 {"code": "0", "msg": "ok"}
        """
        event_data = {
            'task_code': data.get('taskCode', ''),
            'agv_code': data.get('agvCode', ''),
            'task_status': data.get('taskStatus', ''),
            'position_code': data.get('positionCode', ''),
            'timestamp': data.get('timestamp', ''),
        }

        self.logger.info(
            f"收到 agvCallback: task={event_data['task_code']}, "
            f"status={event_data['task_status']}, agv={event_data['agv_code']}"
        )

        # 发布到 EventBus（workflow_engine 会订阅）
        self._publish_event('rcs.agv_callback', event_data)

        return {'code': '0', 'msg': 'ok'}

    def _on_warn_callback(self, data: dict) -> dict:
        """
        处理 warnCallback → 发布 rcs.warn_callback 事件

        Args:
            data: RCS 推送的 JSON body

        Returns:
            标准响应 {"code": "0", "msg": "ok"}
        """
        event_data = {
            'warn_code': data.get('warnCode', ''),
            'warn_msg': data.get('warnMsg', ''),
            'agv_code': data.get('agvCode', ''),
            'task_code': data.get('taskCode', ''),
            'warn_level': data.get('warnLevel', '0'),
            'timestamp': data.get('timestamp', ''),
        }

        level_label = {0: '信息', 1: '警告', 2: '严重'}.get(
            int(event_data['warn_level']) if event_data['warn_level'].isdigit() else 0, '未知'
        )
        self.logger.warning(
            f"收到 warnCallback [{level_label}]: {event_data['warn_msg']} "
            f"(code={event_data['warn_code']}, agv={event_data['agv_code']})"
        )

        self._publish_event('rcs.warn_callback', event_data)

        return {'code': '0', 'msg': 'ok'}

    def _on_bind_notify(self, data: dict) -> dict:
        """
        处理 bindNotify → 发布 rcs.bind_notify 事件 + 同步更新缓存

        Args:
            data: RCS 推送的 JSON body

        Returns:
            标准响应 {"code": "0", "msg": "ok"}
        """
        stg_bin_code = data.get('stgBinCode', '')
        ind_bind = data.get('indBind', '1')
        ctnr_code = data.get('ctnrCode', '')

        event_data = {
            'stg_bin_code': stg_bin_code,
            'ind_bind': ind_bind,         # "1"=绑定, "0"=解绑
            'ctnr_code': ctnr_code,
            'timestamp': data.get('timestamp', ''),
        }

        action = "绑定" if ind_bind == "1" else "解绑"
        self.logger.info(
            f"收到 bindNotify: {action} 仓位 {stg_bin_code}, "
            f"容器={ctnr_code}"
        )

        # 发布事件到 EventBus（供 smart_trigger 等消费）
        self._publish_event('rcs.bind_notify', event_data)

        # 同步更新缓存
        self._sync_cache_on_bind_notify(stg_bin_code, ind_bind)

        return {'code': '0', 'msg': 'ok'}

    def _sync_cache_on_bind_notify(self, bay_code: str, ind_bind: str):
        """
        根据 bindNotify 同步更新内存缓存

        Args:
            bay_code: 仓位编码
            ind_bind: "1"=绑定, "0"=解绑
        """
        try:
            # 1. 更新起始仓位缓存（BayCache）
            bay_fusion = getattr(self.node, 'bay_status_fusion', None)
            if bay_fusion and bay_fusion.cache:
                if ind_bind == "1":
                    bay_fusion.cache.set_bound(bay_code)
                else:
                    bay_fusion.cache.set_unbound(bay_code)
                    bay_fusion.cache.mark_in_task(bay_code, False)
                self.logger.debug(f"起始仓位缓存已更新: {bay_code} ind_bind={ind_bind}")

            # 2. 更新终点仓位缓存（DestBayCache）
            status_poller = getattr(self.node, 'status_poller', None)
            if status_poller and status_poller.dest_cache:
                if ind_bind == "0":
                    # 解绑 → 终点仓位变为空
                    status_poller.dest_cache.update(
                        bay_code, is_empty=True, source='rcs_callback'
                    )
                elif ind_bind == "1":
                    # 绑定 → 终点仓位变为非空
                    status_poller.dest_cache.update(
                        bay_code, is_empty=False, source='rcs_callback'
                    )
                self.logger.debug(f"终点仓位缓存已更新: {bay_code} ind_bind={ind_bind}")

        except Exception as e:
            self.logger.warning(f"缓存同步失败: {e}")

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        if self.receiver:
            status.update(self.receiver.get_status())
        status['rcs_callbacks_enabled'] = self._rcs_enabled
        return status