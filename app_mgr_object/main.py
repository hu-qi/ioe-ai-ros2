#!/usr/bin/env python3
"""
app_mgr_object 主入口
遵循插件化生命周期管理
"""
import yaml
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
import threading
import time
import signal
import sys
from typing import Dict, Any, List

# 导入基础管理器
from .base.param_manager import ParamManager
from .base.lifecycle_manager import LifecycleManager, LifecycleState
from .base.plugin_manager import PluginManager
from .base.service_manager import ServiceManager
from .base.subscription_manager import SubscriptionManager
from .base.timer_manager import TimerManager
from .base.ros2_logger import get_logger

# 导入事件总线
from .plugins.event_bus import EventBus

import asyncio


class AppMgrNode(Node):
    """应用底座主节点"""

    def __init__(self):
        super().__init__('app_mgr_object')
        self._start_time = time.time()
        self.logger = get_logger('main', self)

        # 1. 初始化事件总线（可选，供插件使用）
        self.event_bus = EventBus()

        # 2. 初始化基础管理器
        self._init_base_managers()
        
        # === 在 __init__ 中启动 asyncio 事件循环 ===
        self._asyncio_loop = asyncio.new_event_loop()
        def run_loop():
            asyncio.set_event_loop(self._asyncio_loop)
            self._asyncio_loop.run_forever()
        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()
        self.asyncio_loop = self._asyncio_loop
        self.logger.info("Asyncio 事件循环已启动")

        # 3. 配置日志级别
        self._configure_logging()

        # 4. 加载插件配置
        plugin_configs = self._get_plugin_configs()

        # 5. 发现插件
        self._discover_plugins()

        # 6. 按顺序加载插件
        self._load_plugins_in_order(plugin_configs)

        # 7. 将插件注册到生命周期管理器
        self._register_plugins_to_lifecycle(plugin_configs)

        # 8. 配置所有模块
        self._configure_all()

        # 9. 激活系统
        self._activate_all()
        
        
        

        self.logger.info("应用底座启动完成")

    def _init_base_managers(self):
        """初始化所有基础管理器"""
        self.param_manager = ParamManager(self)
        self.lifecycle_manager = LifecycleManager(self)
        self.plugin_manager = PluginManager(self)
        self.service_manager = ServiceManager(self)
        self.subscription_manager = SubscriptionManager(self)
        self.timer_manager = TimerManager(self)

        # 将管理器自身注册到生命周期管理器（可选）
        self.lifecycle_manager.register_module('param_manager', self.param_manager)
        self.lifecycle_manager.register_module('plugin_manager', self.plugin_manager)
        self.lifecycle_manager.register_module('service_manager', self.service_manager)
        self.lifecycle_manager.register_module('subscription_manager', self.subscription_manager)
        self.lifecycle_manager.register_module('timer_manager', self.timer_manager)

        self.logger.info("基础管理器初始化完成")

    def _configure_logging(self):
        """根据参数配置日志"""
        log_level = self.param_manager.get_param('log_level', 'info').lower()
        from rclpy.logging import LoggingSeverity
        severity_map = {
            'debug': LoggingSeverity.DEBUG,
            'info': LoggingSeverity.INFO,
            'warn': LoggingSeverity.WARN,
            'warning': LoggingSeverity.WARN,
            'error': LoggingSeverity.ERROR
        }
        self.get_logger().set_level(severity_map.get(log_level, LoggingSeverity.INFO))
        self.logger.info(f"日志级别设置为: {log_level}")

    def _get_plugin_configs(self) -> Dict[str, Dict[str, Any]]:
        configs = self.param_manager.get_param('plugin_configs', {})
        # 如果参数管理器已自动解析，configs 直接就是 dict
        if isinstance(configs, str):
            # 兜底：如果声明失败依旧是字符串，则按 YAML 解析
            try:
                configs = yaml.safe_load(configs)
            except yaml.YAMLError:
                configs = {}
        return configs if isinstance(configs, dict) else {}
    

    def _discover_plugins(self):
        """发现插件包内的所有插件"""
        # 插件包路径：app_mgr_object.plugins
        success = self.plugin_manager.discover('app_mgr_object.plugins')
        if not success:
            self.logger.error("插件发现失败，请检查包路径")
            
    def _load_plugins_in_order(self, configs: Dict[str, Dict[str, Any]]):
        load_order = self.param_manager.get_plugin_load_order_from_config()
        if not load_order:
            load_order = self.param_manager.get_param('plugin_load_order', [])
        if not isinstance(load_order, list):
            load_order = []
        if not load_order:
            self.logger.warning("未指定加载顺序，将加载所有插件")
            load_order = list(configs.keys())
        else:
            self.logger.info(f"指定加载顺序: {load_order}")

        loaded = []
        for plugin_name in load_order:
            # ===== 新增特殊处理：web_monitor 即使不在 configs 中也允许加载 =====
            if plugin_name not in configs:
                if plugin_name == 'web_monitor':
                    # web_monitor 的配置由自身从 param_manager 获取，传空字典
                    config = {}
                    self.logger.info(f"插件 {plugin_name} 使用独立配置加载")
                else:
                    self.logger.warning(f"插件 {plugin_name} 在配置中未找到，跳过")
                    continue
            else:
                config = configs[plugin_name]

            if not self._check_dependencies(plugin_name, config):
                self.logger.error(f"插件 {plugin_name} 依赖不满足，跳过")
                continue
            if self.plugin_manager.load_plugin(plugin_name, config):
                loaded.append(plugin_name)
            else:
                self.logger.error(f"插件 {plugin_name} 加载失败")
        self.logger.info(f"成功加载 {len(loaded)} 个插件: {loaded}")

    

    def _check_dependencies(self, plugin_name: str, config: Dict[str, Any]) -> bool:
        """检查插件的依赖是否已加载"""
        deps = config.get('dependencies', [])
        for dep in deps:
            if not self.plugin_manager.get_plugin(dep):
                self.logger.warning(f"插件 {plugin_name} 依赖 {dep} 未加载")
                return False
        return True
    
    def _register_plugins_to_lifecycle(self, configs: Dict[str, Dict[str, Any]]):
        """将已加载的插件注册到生命周期管理器（仅注册实际存在的插件）"""
        # 【修复】不再依赖 configs.keys()，而是直接遍历已加载的插件
        loaded_plugins = self.plugin_manager.get_loaded_plugin_names()
        
        for plugin_name in loaded_plugins:
            plugin = self.plugin_manager.get_plugin(plugin_name)
            if plugin:
                # 从 configs 中获取该插件的配置（可能不存在，则用空字典）
                plugin_config = configs.get(plugin_name, {})
                auto_activate = plugin_config.get('auto_start', True)
                self.lifecycle_manager.register_module(
                    f"plugin_{plugin_name}",
                    plugin,
                    auto_activate=auto_activate
                )
                self.logger.debug(f"插件 {plugin_name} 已注册到生命周期管理器")
            else:
                # 理论上不会发生，因为 loaded_plugins 来自实际存在的插件
                self.logger.warning(f"插件 {plugin_name} 已加载但实例为空，无法注册")

    

    def _configure_all(self):
        """配置所有已注册的模块"""
        self.lifecycle_manager.configure()  # 内部已打印日志
        

    def _activate_all(self):
        """激活所有自动激活的模块"""
        self.lifecycle_manager.activate()
        
       
    def shutdown(self):
        """优雅关闭"""
        self.logger.info("正在关闭系统...")
        self.lifecycle_manager.shutdown()
        self.logger.info("系统关闭完成")


def main(args=None):
    rclpy.init(args=args)

    node = None
    executor = None
    executor_thread = None
    shutdown_requested = False

    def sigint_handler(sig, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        node.get_logger().info("收到中断信号，正在关闭...")
        if executor:
            executor.shutdown()
        # 不调用 sys.exit，让主线程自然退出

    try:
        node = AppMgrNode()
        executor = MultiThreadedExecutor()
        executor.add_node(node)

        signal.signal(signal.SIGINT, sigint_handler)
        signal.signal(signal.SIGTERM, sigint_handler)

        executor_thread = threading.Thread(target=executor.spin, daemon=True)
        executor_thread.start()
        executor_thread.join()
                

    except KeyboardInterrupt:
        pass
    except Exception as e:
        if node:
            node.get_logger().error(f"运行错误: {e}")
        else:
            print(f"节点启动错误: {e}")
    finally:
        if not shutdown_requested:
            # 如果未通过信号处理，则手动清理
            if executor:
                executor.shutdown()
        if node:
            node.shutdown()
            node.destroy_node()
        # 确保只调用一次 rclpy.shutdown
        try:
            rclpy.shutdown()
        except RuntimeError as e:
            # 如果上下文未初始化，忽略
            pass


if __name__ == '__main__':
    main()