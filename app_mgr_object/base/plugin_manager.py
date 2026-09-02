#!/usr/bin/env python3
"""
插件管理器 - 通用版本
"""

import importlib
import os
import sys
import pkgutil
import inspect
from typing import Dict, List, Any, Optional
import traceback

from ..plugins.base_plugin import BasePlugin  # 添加导入

class PluginManager:
    """通用插件管理器"""
    
    def __init__(self, node):
        self.node = node
        self.logger = node.get_logger()
        self._plugins = {}  # name -> info
        
    def discover(self, package_path: str) -> bool:
        """
        发现指定包路径下的所有插件（继承自 BasePlugin 的类）
        
        Args:
            package_path: 包路径，例如 'app_mgr_object.plugins'
        """
        try:
            package = importlib.import_module(package_path)
        except ImportError as e:
            self.logger.error(f"无法导入包 {package_path}: {e}")
            return False

        package_dir = os.path.dirname(package.__file__) if hasattr(package, '__file__') else None
        if not package_dir or not os.path.exists(package_dir):
            self.logger.error(f"包目录不存在: {package_dir}")
            return False

        self.logger.info(f"开始发现插件，搜索包: {package_path}, 目录: {package_dir}")

        # 遍历包内所有模块
        for finder, name, ispkg in pkgutil.iter_modules([package_dir]):
            if ispkg:
                continue
            module_fullname = f"{package_path}.{name}"
            try:
                module = importlib.import_module(module_fullname)
            except Exception as e:
                self.logger.warning(f"导入模块 {module_fullname} 失败: {e}")
                continue

            # 查找模块中定义的插件类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if not inspect.isclass(attr):
                    continue
                # 只考虑在当前模块定义的类（排除导入的类）
                if attr.__module__ != module_fullname:
                    continue
                # 检查是否是 BasePlugin 的子类，且不是 BasePlugin 本身
                if (issubclass(attr, BasePlugin) and
                    attr.__name__ != 'BasePlugin' and
                    hasattr(attr, 'PLUGIN_NAME')):
                    plugin_name = attr.PLUGIN_NAME.lower()
                    if plugin_name in self._plugins:
                        self.logger.warning(f"插件名称重复: {plugin_name}，跳过")
                        continue
                    self._plugins[plugin_name] = {
                        'name': plugin_name,
                        'class': attr,
                        'module': module_fullname,
                        'instance': None,
                        'config': {},
                        'enabled': False
                    }
                    self.logger.info(f"发现插件: {plugin_name} (类: {attr.__name__})")

        self.logger.info(f"插件发现完成，共 {len(self._plugins)} 个")
        return True

    def load_plugin(self, plugin_name: str, config: Dict[str, Any] = None) -> bool:
        plugin_name = plugin_name.lower()
        if plugin_name not in self._plugins:
            self.logger.error(f"插件 {plugin_name} 未发现")
            return False
        if self._plugins[plugin_name]['instance'] is not None:
            self.logger.warning(f"插件 {plugin_name} 已加载")
            return True

        plugin_class = self._plugins[plugin_name]['class']
        try:
            instance = plugin_class(node=self.node, config=config or {})
            self._plugins[plugin_name]['instance'] = instance
            self._plugins[plugin_name]['config'] = config or {}
            self._plugins[plugin_name]['enabled'] = True
            self.logger.info(f"插件 {plugin_name} 加载成功")
            return True
        except Exception as e:
            self.logger.error(f"加载插件 {plugin_name} 失败: {e}\n{traceback.format_exc()}")
            return False

    def load_all_plugins(self, configs: Dict[str, Dict[str, Any]] = None):
        configs = configs or {}
        loaded = 0
        for plugin_name in configs:
            if plugin_name not in self._plugins:
                self.logger.warning(f"插件 {plugin_name} 未发现，跳过")
                continue
            if self.load_plugin(plugin_name, configs[plugin_name]):
                loaded += 1
        self.logger.info(f"已加载 {loaded}/{len(configs)} 个插件")

    def unload_plugin(self, plugin_name: str) -> bool:
        plugin_name = plugin_name.lower()
        if plugin_name not in self._plugins or self._plugins[plugin_name]['instance'] is None:
            self.logger.warning(f"插件 {plugin_name} 未加载")
            return False
        try:
            inst = self._plugins[plugin_name]['instance']
            if hasattr(inst, 'cleanup'):
                inst.cleanup()
            self._plugins[plugin_name]['instance'] = None
            self._plugins[plugin_name]['enabled'] = False
            self.logger.info(f"插件 {plugin_name} 卸载成功")
            return True
        except Exception as e:
            self.logger.error(f"卸载插件 {plugin_name} 失败: {e}")
            return False

    def enable_plugin(self, plugin_name: str) -> bool:
        plugin_name = plugin_name.lower()
        if plugin_name not in self._plugins:
            return False
        if self._plugins[plugin_name]['instance'] is None:
            if not self.load_plugin(plugin_name, self._plugins[plugin_name]['config']):
                return False
        self._plugins[plugin_name]['enabled'] = True
        inst = self._plugins[plugin_name]['instance']
        if hasattr(inst, 'on_enable'):
            try:
                inst.on_enable()
            except Exception as e:
                self.logger.error(f"插件 {plugin_name} on_enable 失败: {e}")
        return True

    def disable_plugin(self, plugin_name: str) -> bool:
        plugin_name = plugin_name.lower()
        if plugin_name not in self._plugins:
            return False
        self._plugins[plugin_name]['enabled'] = False
        inst = self._plugins[plugin_name]['instance']
        if inst and hasattr(inst, 'on_disable'):
            try:
                inst.on_disable()
            except Exception as e:
                self.logger.error(f"插件 {plugin_name} on_disable 失败: {e}")
        return True

    def get_plugin(self, plugin_name: str):
        plugin_name = plugin_name.lower()
        info = self._plugins.get(plugin_name)
        return info['instance'] if info else None
    
    def get_loaded_plugin_names(self) -> list:
        """获取所有已成功加载的插件名称列表"""
        loaded = []
        for name, info in self._plugins.items():
            if info.get('instance') is not None:
                loaded.append(name)
        return loaded

    def get_all_plugins(self) -> Dict[str, Any]:
        return {
            name: {
                'enabled': info['enabled'],
                'has_instance': info['instance'] is not None,
                'class': info['class'].__name__
            }
            for name, info in self._plugins.items()
        }

    def configure_plugin(self, plugin_name: str, config: Dict[str, Any]) -> bool:
        plugin_name = plugin_name.lower()
        inst = self.get_plugin(plugin_name)
        if not inst:
            return False
        if hasattr(inst, 'configure'):
            try:
                inst.configure(config)
            except Exception as e:
                self.logger.error(f"配置插件 {plugin_name} 失败: {e}")
                return False
        self._plugins[plugin_name]['config'] = config
        return True

    def call_plugin_method(self, plugin_name: str, method_name: str, *args, **kwargs):
        inst = self.get_plugin(plugin_name)
        if not inst or not self._plugins[plugin_name]['enabled']:
            return None
        method = getattr(inst, method_name, None)
        if not method:
            return None
        try:
            return method(*args, **kwargs)
        except Exception as e:
            self.logger.error(f"调用插件 {plugin_name}.{method_name} 失败: {e}")
            return None

    def get_status(self) -> Dict[str, Any]:
        return {
            'plugin_count': len(self._plugins),
            'plugins': {name: info['enabled'] for name, info in self._plugins.items()}
        }