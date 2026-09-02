#!/usr/bin/env python3
"""
Web监控插件 - 组件化门面（告警模块已启用）
职责：插件生命周期管理 + 组件组装 + 告警门面 + 系统状态门面
"""
import os
import time
import threading
import json
import asyncio
from typing import Dict, Any, List, Optional

import rclpy
from rclpy.node import Node

from .base_plugin import BasePlugin
from ..components.web.status_monitor import StatusMonitor
from ..components.web.control_executor import ControlExecutor
from ..components.web.alarm_manager import AlarmManager, Alarm, AlarmLevel, AlarmType
from ..components.web.web_server import WebServer
from ..components.web.image_manager import InferenceImageManager

# 新增组件
from ..components.web.business_collector import BusinessCollector
from ..components.web.config_manager import ConfigManager
from ..components.web.task_controller import TaskController
from ..components.web.event_bridge import EventBridge


class WebMonitorPlugin(BasePlugin):
    """Web监控插件（组件化门面 — 告警已启用）"""

    PLUGIN_NAME = "web_monitor"
    PLUGIN_VERSION = "2.1.0"
    PLUGIN_DESCRIPTION = "Web监控插件，提供系统状态监控、告警和运维控制功能"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        # 组件实例
        self.status_monitor = None
        self.control_executor = None
        self.alarm_manager = None          #  启用
        self.web_server = None

        # 新增组件
        self.business_collector = None
        self.config_manager = None
        self.task_controller = None
        self.event_bridge = None           #  新增

        # 组件配置
        self._status_config = None
        self._control_config = None
        self._alarm_config = None
        self._web_server_config = None

        # 状态缓存
        self._status_cache = {}
        self._last_status_time = 0
        self._status_lock = threading.RLock()

        self.plugin_config = {}
        self._stop_event = threading.Event()
        
        self._last_business_hash = None
        self.logger.info("Web监控插件初始化完成（v2.1.0 — 告警已启用）")

    # ==================== 配置阶段 ====================

    def _configure_impl(self):
        """配置实现 — 获取配置、创建组件、注册处理器、挂载到 node"""
        try:
            self.logger.info("开始配置Web监控插件")

            if not hasattr(self.node, 'param_manager'):
                self.logger.error("无法获取参数管理器")
                return False

            web_config = self.node.param_manager.get_web_monitor_config()
            if isinstance(web_config, dict):
                self.logger.info(f"web_config keys: {list(web_config.keys())}")
            else:
                self.logger.warning(f"web_config类型异常: {type(web_config)}，尝试修复")
                try:
                    if isinstance(web_config, str):
                        web_config = json.loads(web_config)
                    else:
                        web_config = {}
                except Exception:
                    web_config = {}

            self.plugin_config = web_config

            if not self.plugin_config.get('enabled', True):
                self.logger.info("Web监控插件未启用")
                return True

            # 网络接口 IP
            network_interface = self.plugin_config.get('network_interface', 'wlan0')
            interface_ip = self._get_interface_ip(network_interface)
            self.plugin_config['host'] = interface_ip or '0.0.0.0'

            # 内部组件配置
            self._init_components_config()

            # ===== 创建业务组件 =====
            self.business_collector = BusinessCollector(self.node, self)
            self.config_manager = ConfigManager(self.node)
            self.task_controller = TaskController(self.node)
            self.event_bridge = EventBridge(self.node, None)  # web_server 尚未创建

            # ===== 注册配置热加载处理器 =====
            self._register_reload_handlers()

            # ===== 挂载到 node（供 web_server 路由访问） =====
            self.node.web_monitor = self
            self.node.business_collector = self.business_collector
            self.node.config_manager = self.config_manager
            self.node.task_controller = self.task_controller
            self.node.event_bridge = self.event_bridge

            # ===== P2：OPS 统一节点控制代理（doc/P2 v2，配置 yaml 驱动） =====
            self.node.ops_proxy = None
            ops_cfg = web_config.get('ops_integration', {}) or {}
            if ops_cfg.get('enabled', True):
                try:
                    from ..components.web.ops_proxy import OpsControlProxy
                    self.node.ops_proxy = OpsControlProxy(
                        base_url=ops_cfg.get('base_url', 'http://127.0.0.1:1818'),
                        timeout_s=ops_cfg.get('timeout_s', 10),
                        display_map=ops_cfg.get('display_map', {}) or {},
                        logger=self.logger)
                    self.logger.info(
                        f"✅ OpsControlProxy 就绪: {ops_cfg.get('base_url', 'http://127.0.0.1:1818')}"
                    )
                except Exception as e:
                    self.logger.error(f"OpsControlProxy 初始化失败: {e}")

            self.logger.info(
                f"Web监控插件配置完成 — 端口:{web_config.get('port')}, "
                f"模式:{web_config.get('operation_mode')}, 组件化+v2.1.0"
            )
            return True

        except Exception as e:           
            import traceback
            self.logger.error(f"配置Web监控插件失败: {e}\n{traceback.format_exc()}")
            return False

    # ==================== 配置热加载 ====================

    def _register_reload_handlers(self):
        """将内存应用函数注册到 config_manager"""
        self.config_manager.register_handler('bay_configs',
            lambda v: self._apply_bay_configs(v))
        self.config_manager.register_handler('dest_bay_configs',
            lambda v: self._apply_dest_configs(v))
        self.config_manager.register_handler('work_schedule',
            lambda v: self._apply_work_schedule(v))
        self.config_manager.register_handler('pair_overrides',
            lambda v: self._apply_pair_overrides(v))
        self.config_manager.register_handler('pairing_policy',
            lambda v: self._apply_pairing_policy(v))
        self.config_manager.register_handler('cargo_priority',
            lambda v: self._apply_cargo_priority(v))

    def _apply_bay_configs(self, mappings: dict):
        fusion = self._get_plugin('bay_status_fusion')
        if fusion and fusion.cache:
            fusion.cache.reload_config(mappings)
        trigger = self._get_plugin('smart_trigger')
        if trigger and hasattr(trigger, '_config_cache'):
            trigger._config_cache.set_source_mapping(mappings)
        self.logger.info(f"起始仓位映射热加载: {len(mappings)} 个")

    def _apply_dest_configs(self, mappings: dict):
        poller = self._get_plugin('status_poller')
        if poller and poller.dest_cache:
            poller.dest_cache.reload_config(mappings)
        trigger = self._get_plugin('smart_trigger')
        if trigger and hasattr(trigger, '_config_cache'):
            trigger._config_cache.set_dest_mapping(mappings)
        self.logger.info(f"终点仓位映射热加载: {len(mappings)} 个")

    def _apply_work_schedule(self, value):
        """工作时段热加载：兼容 list（旧 schedules）与 dict（{enabled, holidays, schedules}）"""
        if isinstance(value, list):
            work_schedule = {'enabled': True, 'holidays': [], 'schedules': value}
        else:
            work_schedule = value or {}
        trigger = self._get_plugin('smart_trigger')
        if trigger and trigger._trigger_engine:
            trigger._trigger_engine.set_work_schedule(work_schedule)
        if trigger and hasattr(trigger, '_config_cache'):
            trigger._config_cache.set_schedules(work_schedule.get('schedules') or [])
        n = len(work_schedule.get('schedules') or [])
        self.logger.info(
            f"工作时段热加载: {n} 条 (enabled={work_schedule.get('enabled', True)}, "
            f"holidays={len(work_schedule.get('holidays') or [])}个)")

    def _apply_pair_overrides(self, overrides: dict):
        trigger = self._get_plugin('smart_trigger')
        if trigger and trigger._trigger_engine:
            trigger._trigger_engine.set_pair_overrides(overrides)
        self.logger.info(f"配对覆盖热加载: {len(overrides)} 条")

    def _apply_cargo_priority(self, priority: list):
        trigger = self._get_plugin('smart_trigger')
        if trigger and trigger._trigger_engine:
            trigger._trigger_engine.set_cargo_priority(priority)
        self.logger.info(f"货物优先级热加载: {priority}")

    def _apply_pairing_policy(self, policy: dict):
        """配对策略热加载（巷道/放置策略，doc/目的仓位巷道FIFO策略）"""
        poller = self._get_plugin('status_poller')
        if poller and poller.dest_cache:
            poller.dest_cache.set_pairing_policy(policy)
        trigger = self._get_plugin('smart_trigger')
        if trigger and trigger._trigger_engine:
            trigger._trigger_engine.set_pairing_policy(policy)
        lanes = len((policy or {}).get('lanes') or [])
        self.logger.info(f"配对策略热加载: {lanes} 条巷道")

    # ==================== 激活阶段 ====================

    def _activate_impl(self):
        """激活实现 — 初始化组件 + 启动服务 + 订阅事件"""
        try:
            if not self.plugin_config.get('enabled', True):
                self.logger.info("Web监控插件未启用")
                return True

            if not self._status_config:
                self.logger.error("组件配置未初始化")
                return False

            # 1. 初始化组件（含告警管理器）
            self._init_components()

            # 2. 启动状态监控线程
            self._start_monitoring()

            # 3. 事件桥订阅（替换原内联订阅逻辑）
            if self.event_bridge:
                self.event_bridge.subscribe_all()
            else:
                self.logger.warning("event_bridge 未创建，跳过事件订阅")

            # 4. 启动 Web 服务器
            success = self._start_web_server()
            if success:
                # web_server 创建后注入到 event_bridge
                if self.event_bridge:
                    self.event_bridge.web_server = self.web_server
                self.logger.info("✅ Web监控插件激活成功（告警模块已启用）")
                return True
            else:
                self.logger.error("❌ Web服务器启动失败")
                return False

        except Exception as e:            
            import traceback
            self.logger.error(f"激活Web监控插件失败: {e}\n{traceback.format_exc()}")
            return False
        
    def _init_components(self):
        """初始化各组件 — 告警管理器已启用"""
        # 状态监控器
        self.status_monitor = StatusMonitor(self.node, self._status_config)
        self.node.status_monitor = self.status_monitor

        # 控制执行器
        detected_mode = self.plugin_config.get('operation_mode', 'development')
        self.control_executor = ControlExecutor(
            mode=detected_mode,
            config=self._control_config,
            logger=self.logger
        )

        # ===== 告警管理器（已启用） =====
        # self.alarm_manager = AlarmManager(self._alarm_config)
        self.alarm_manager = AlarmManager(self._alarm_config, logger=self.logger)
        # 注册告警回调 → 通过 event_bridge 广播
        self.alarm_manager.register_alarm_callback(self._on_new_alarm)
        auto_recovery = self._alarm_config.get('auto_recovery', True)
        self.logger.info(f"✅ 告警管理器已启用（auto_recovery={auto_recovery}）")

        # 标定图像管理器（可选）
        calib_config = self.plugin_config.get('calibration', {})
        if calib_config.get('enabled', False):
            self.image_manager = InferenceImageManager(self.node, calib_config)
            self.node.image_manager = self.image_manager
            self.logger.info("标定图像管理器已初始化")
            # P4 v2：标定配置从 OPS 自动同步（doc/P4 §9）——OPS 可用时覆盖 yaml 配置并重建订阅
            try:
                proxy = getattr(self.node, 'ops_proxy', None)
                if proxy:
                    self.image_manager.sync_from_ops(proxy)
            except Exception as e:
                self.logger.warning(f"标定配置 OPS 同步失败: {e}")

        self.logger.info(f"组件初始化完成 — 模式:{detected_mode}")

    def _start_monitoring(self):
        """启动状态监控线程"""
        def monitoring_loop():
            monitor_interval = self.plugin_config.get('monitor_interval', 5.0)
            while not self._stop_event.is_set():
                try:
                    status = self._get_system_status()
                    # 告警检查 — alarm_manager 已启用
                    self._check_and_generate_alarms(status)
                    # 状态广播 — 通过 event_bridge
                    if self.event_bridge:
                        self.event_bridge.broadcast_status_periodic(status)
                        
                    # 业务快照变更检测推送
                    try:
                        summary = self.business_collector.collect_business_status()
                        h = self._snapshot_hash(summary)
                        if h != self._last_business_hash:
                            self._last_business_hash = h
                            self.event_bridge.broadcast('business_update', summary)
                    except Exception as e:
                        self.logger.debug(f"业务快照推送失败: {e}")
                except Exception as e:
                    self.logger.error(f"状态监控循环错误: {e}")
                # time.sleep(monitor_interval)
                self._stop_event.wait(monitor_interval)   # 可中断睡眠

        self._monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
        self._monitoring_thread.start()
        self.logger.info(f"状态监控线程启动，间隔: {self.plugin_config.get('monitor_interval')}秒")

    
    
    def _snapshot_hash(self, summary: dict) -> str:
        """生成业务快照轻量指纹"""
        import hashlib, json
        compact = {
            'bay': [(b.get('bay_id'), b.get('bind_status'), b.get('in_task'),
                    b.get('cargo_type'))
                    for b in (summary.get('bay') or {}).get('bays', [])],
            'dest': [(b.get('bay_id'), b.get('is_empty'))
                    for b in (summary.get('dest') or {}).get('bays', [])],
            'agv': [(r.get('robot_id'), r.get('status'), r.get('battery'))
                    for r in (summary.get('agv') or {}).get('robots', [])],
            'queue': [(q.get('src_bay'), q.get('dst_bay'), q.get('cargo_type'))
                    for q in (summary.get('task_queue') or {}).get('queue', [])],
            'instances': [(i.get('task_id'), i.get('status'), i.get('current_state'))
                        for i in (summary.get('active_instances') or {}).get('instances', [])],
        }
        return hashlib.md5(
            json.dumps(compact, sort_keys=True, default=str).encode()
        ).hexdigest()
    
    def _start_web_server(self):
        """启动 Web 服务器"""
        try:
            self.logger.info("开始启动Web服务器...")
            self.web_server = WebServer(
                config=self._web_server_config,
                node=self.node,
                status_callback=self.get_system_status,
                control_callback=self.execute_control,
                logger=self.logger
            )
            success = self.web_server.start()
            if success:
                self.logger.info("✅ Web服务器启动成功")
                return True
            self.logger.error("❌ Web服务器启动失败")
            return False
        except Exception as e:
            self.logger.error(f"启动Web服务器异常: {e}")
            return False

    # ==================== 监 控 + 告 警 ====================

    def _get_system_status(self) -> Dict[str, Any]:
        """获取系统状态（内部）"""
        try:
            if self.status_monitor:
                status = self.status_monitor.get_system_status()
                if 'operation_mode' not in status:
                    status['operation_mode'] = self.plugin_config.get('operation_mode', 'development')
                status['plugin_info'] = {
                    'name': self.PLUGIN_NAME,
                    'version': self.PLUGIN_VERSION,
                    'enabled': self._enabled
                }
                if self.web_server:
                    status['web_server'] = self.web_server.get_server_info()
                with self._status_lock:
                    self._status_cache = status
                    self._last_status_time = time.time()
                return status
            return {
                'timestamp': time.time(), 'status': 'error',
                'message': '状态监控器未初始化',
                'nodes': {}, 'channels': {}, 'services': {}, 'health_score': 0
            }
        except Exception as e:
            self.logger.error(f"获取系统状态失败: {e}")
            return {
                'timestamp': time.time(), 'status': 'error',
                'message': str(e), 'health_score': 0
            }

    def _check_and_generate_alarms(self, status: Dict[str, Any]):
        """系统状态 → 告警检查 → 广播"""
        try:
            if not self.alarm_manager:
                return
            # ✅ alarm_manager 检查系统状态，返回新告警列表
            new_alarms = self.alarm_manager.check_system_status(status)
            if new_alarms and self.event_bridge:
                self.event_bridge.broadcast_alarm_update(
                    [a.to_dict() if hasattr(a, 'to_dict') else a for a in new_alarms]
                )
        except Exception as e:
            self.logger.error(f"告警检查失败: {e}")

    def _on_new_alarm(self, alarm):
        """告警回调 → WebSocket 广播"""
        try:
            self.logger.warning(
                f"新告警: {alarm.message} (级别: {alarm.level.value if hasattr(alarm, 'level') else 'unknown'})"
            )
            if self.event_bridge:
                alarm_dict = alarm.to_dict() if hasattr(alarm, 'to_dict') else alarm
                self.event_bridge.broadcast_alarm_update([alarm_dict])
        except Exception as e:
            self.logger.error(f"新告警处理失败: {e}")

    # ==================== 公开 API ====================

    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态（API） — 带缓存"""
        with self._status_lock:
            if time.time() - self._last_status_time < 2.0 and self._status_cache:
                return self._status_cache
        status = self._get_system_status()
        plugin_mode = self.plugin_config.get('operation_mode', 'development')
        status['operation_mode'] = plugin_mode
        if self.control_executor:
            mode_info = self.control_executor.get_system_mode()
            if mode_info.get('success'):
                status['control_mode'] = mode_info.get('mode', 'development')
        return status

    def execute_control(self, command_type: str, command: str,
                        params: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行控制命令（API）"""
        try:
            params = params or {}
            if not self.control_executor:
                return {'success': False, 'error': '控制执行器未初始化'}
            if command_type == 'control':
                return self.control_executor.execute_operation(command, params)
            if command_type in ('node', 'service', 'system'):
                return self.control_executor.execute(command_type, command, params)
            return {'success': False, 'error': f'不支持的命令类型: {command_type}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def execute_control_action(self, action: str,
                               params: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行控制动作（兼容旧接口）"""
        params = params or {}
        if not self.control_executor:
            return {'success': False, 'error': '控制执行器未初始化'}
        # P2：节点/服务控制已统一经 OPS（/api/ops/*），本地 systemctl 路径已移除
        if action in ('restart_infer_nodes', 'restart_rcs_manager', 'start_service', 'stop_service'):
            return {'success': False,
                    'error': '节点/服务控制已由 OPS 统一执行（节点运维页），本地路径已移除: %s' % action}
        elif action in ('start_service', 'stop_service'):
            service_name = params.get('service_name')
            if not service_name:
                return {'success': False, 'error': '未指定服务名称'}
            method = (self.control_executor.start_service if action == 'start_service'
                     else self.control_executor.stop_service)
            return method(service_name)
        return {'success': False, 'error': f'不支持的动作: {action}'}

    # ==================== 告警门面 ====================

    def get_alarms(self, limit: int = 100,
                   include_acknowledged: bool = False) -> List[Dict[str, Any]]:
        try:
            if self.alarm_manager:
                return self.alarm_manager.get_alarms(limit, include_acknowledged)
            return []
        except Exception as e:
            self.logger.error(f"获取告警列表失败: {e}")
            return []

    def get_alarm_stats(self) -> Dict[str, Any]:
        try:
            if self.alarm_manager:
                return self.alarm_manager.get_stats()
            return {
                'total_alarms': 0, 'unacknowledged_alarms': 0,
                'unresolved_alarms': 0
            }
        except Exception as e:
            self.logger.error(f"获取告警统计失败: {e}")
            return {}

    def acknowledge_alarm(self, alarm_id: str, username: str = "system",
                          notes: str = "") -> bool:
        try:
            if self.alarm_manager:
                return self.alarm_manager.acknowledge_alarm(alarm_id, username)
            return False
        except Exception as e:
            self.logger.error(f"确认告警失败: {e}")
            return False

    def resolve_alarm(self, alarm_id: str) -> bool:
        try:
            if self.alarm_manager:
                return self.alarm_manager.resolve_alarm(alarm_id)
            return False
        except Exception as e:
            self.logger.error(f"解决告警失败: {e}")
            return False

    def clear_alarms(self) -> int:
        try:
            if self.alarm_manager:
                return self.alarm_manager.clear_alarms()
            return 0
        except Exception as e:
            self.logger.error(f"清理告警失败: {e}")
            return 0

    # ==================== 辅助方法 ====================

    def _get_plugin(self, name: str):
        """安全获取业务插件实例"""
        plugin = getattr(self.node, name, None)
        if plugin is None and hasattr(self.node, 'plugin_manager'):
            plugin = self.node.plugin_manager.get_plugin(name)
        return plugin

    def _get_interface_ip(self, interface_name: str) -> str:
        """获取指定网络接口的IPv4地址"""
        try:
            import netifaces
            interfaces = netifaces.interfaces()
            if interface_name not in interfaces:
                self.logger.warning(f"网络接口 {interface_name} 不存在: {interfaces}")
                return None
            addresses = netifaces.ifaddresses(interface_name)
            if netifaces.AF_INET in addresses:
                ip_info = addresses[netifaces.AF_INET][0]
                ip_address = ip_info.get('addr')
                if ip_address and ip_address != '127.0.0.1':
                    return ip_address
            return None
        except ImportError:
            self.logger.error("netifaces 未安装: pip install netifaces")
            return None
        except Exception as e:
            self.logger.error(f"获取IP失败 [{interface_name}]: {e}")
            return None

    def _init_components_config(self):
        """初始化各组件配置"""
        try:
            node_aliases = self.plugin_config.get('node_aliases', {})
            if not isinstance(node_aliases, dict):
                node_aliases = {}

            self._status_config = {
                'node_aliases': node_aliases,
                'channel_aliases': self.plugin_config.get('channel_aliases', {}),
                'callback_server': self.plugin_config.get('callback_server', {}),
                'operation_mode': self.plugin_config.get('operation_mode', 'development'),
            }
            self._control_config = {
                'dev_scripts': self.plugin_config.get('dev_scripts', {}),
                'deployment_services': self.plugin_config.get('deployment_services', {}),
                'node_names': self.plugin_config.get('node_names', {}),
            }
            self._alarm_config = self.plugin_config.get('alarm_config', {})
            self._web_server_config = {
                'host': self.plugin_config.get('host', '0.0.0.0'),
                'port': self.plugin_config.get('port', 9183),
                'debug': self.plugin_config.get('debug', True),
                'operation_mode': self.plugin_config.get('operation_mode', 'development'),
                'broadcast_interval': self.plugin_config.get('broadcast_interval', 3.0),
                'alarm_check_interval': self.plugin_config.get('alarm_check_interval', 10.0),
                'dev_scripts': self._control_config['dev_scripts'],
                'deployment_services': self._control_config['deployment_services'],
                'node_aliases': self._status_config['node_aliases'],
                'channel_aliases': self._status_config['channel_aliases'],
                'callback_server': self._status_config['callback_server'],
                'node_names': self._control_config['node_names'],
            }
            self.logger.info("组件配置初始化完成")
        except Exception as e:
            self.logger.error(f"初始化组件配置失败: {e}")
            raise

    # ==================== 插件生命周期 ====================

    def _deactivate_impl(self):
        try:
            self._stop_event.set()   # 替代 self._enabled = False
            # self._enabled = False
            if self.web_server:
                self.web_server.stop()
                self.web_server = None
            if hasattr(self, '_monitoring_thread'):
                self._monitoring_thread.join(timeout=5)
            if hasattr(self, 'image_manager') and self.image_manager:
                self.image_manager.shutdown()
            self.status_monitor = None
            self.control_executor = None
            self.alarm_manager = None
            self.logger.info("Web监控插件已停用")
            return True
        except Exception as e:
            self.logger.error(f"停用Web监控插件失败: {e}")
            return False

    def _cleanup_impl(self):
        self._status_cache = {}
        self.plugin_config = {}
        self.logger.info("Web监控插件已清理")

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update({
            'web_server_running': self.web_server.is_running() if self.web_server else False,
            'status_monitor_ready': self.status_monitor is not None,
            'control_executor_ready': self.control_executor is not None,
            'alarm_manager_ready': self.alarm_manager is not None,       # ✅
            'event_bridge_ready': self.event_bridge is not None,         # ✅
            'config': {
                'host': self.plugin_config.get('host'),
                'port': self.plugin_config.get('port'),
                'mode': self.plugin_config.get('operation_mode'),
                'monitor_interval': self.plugin_config.get('monitor_interval'),
            },
            'statistics': {
                'status_cache_time': self._last_status_time,
                'ws_clients': self.web_server.manager.get_connection_count()
                    if self.web_server else 0,
            },
        })
        return status

    def get_status_summary(self) -> Dict[str, Any]:
        return {
            'plugin': self.PLUGIN_NAME,
            'enabled': self._enabled,
            'web_server_running': self.web_server.is_running() if self.web_server else False,
            'mode': self.plugin_config.get('operation_mode', 'development'),
            'host': self.plugin_config.get('host'),
            'port': self.plugin_config.get('port'),
        }