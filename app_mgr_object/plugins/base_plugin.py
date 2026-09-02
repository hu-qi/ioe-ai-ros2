# base_plugin.py
#!/usr/bin/env python3
"""
插件基类 - 提供抽象方法的默认实现
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import rclpy
import time


class BasePlugin(ABC):
    """插件基类"""
    
    PLUGIN_NAME = "base_plugin"
    PLUGIN_VERSION = "1.0.0"
    
    def __init__(self, node, config: Dict[str, Any] = None):
        """
        初始化插件
        
        Args:
            node: ROS2节点实例
            config: 插件配置
        """
        self.node = node
        self.logger = node.get_logger()
        self.config = config or {}
        
        # 获取事件总线（如果节点已初始化）
        self.event_bus = getattr(node, 'event_bus', None)
        
        # 插件状态
        self._enabled = False
        self._initialized = False
        self._configured = False
        self._error = None
        
        self.logger.debug(f"插件 {self.PLUGIN_NAME} 初始化")
    
    def configure(self, config: Dict[str, Any] = None) -> bool:
        """配置插件"""
        try:
            if config:
                self.config.update(config)
            
            success = self._configure_impl()
            if success:
                self._configured = True
                self._initialized = True
                self.logger.info(f"插件 {self.PLUGIN_NAME} 配置完成")
                
                # 发布配置完成事件
                self._publish_event('plugin.configured', {
                    'plugin_name': self.PLUGIN_NAME,
                    'success': success
                })
            else:
                self._error = "配置失败"
                self.logger.error(f"插件 {self.PLUGIN_NAME} 配置失败")
            
            return success
            
        except Exception as e:
            self._error = str(e)
            self.logger.error(f"插件 {self.PLUGIN_NAME} 配置异常: {e}")
            return False
    
    def activate(self) -> bool:
        """激活插件"""
        try:
            if not self._configured:
                self.logger.warning(f"插件 {self.PLUGIN_NAME} 未配置，先进行配置")
                if not self.configure():
                    return False
            
            success = self._activate_impl()
            if success:
                self._enabled = True
                self._error = None
                self.logger.info(f"插件 {self.PLUGIN_NAME} 激活成功")
                
                # 发布激活完成事件
                self._publish_event('plugin.activated', {
                    'plugin_name': self.PLUGIN_NAME,
                    'success': success
                })
            else:
                self._error = "激活失败"
                self.logger.error(f"插件 {self.PLUGIN_NAME} 激活失败")
            
            return success
            
        except Exception as e:
            self._error = str(e)
            self.logger.error(f"插件 {self.PLUGIN_NAME} 激活异常: {e}")
            return False
    
    def deactivate(self) -> bool:
        """停用插件"""
        try:
            success = self._deactivate_impl()
            if success:
                self._enabled = False
                self.logger.info(f"插件 {self.PLUGIN_NAME} 停用成功")
                
                # 发布停用完成事件
                self._publish_event('plugin.deactivated', {
                    'plugin_name': self.PLUGIN_NAME,
                    'success': success
                })
            else:
                self.logger.error(f"插件 {self.PLUGIN_NAME} 停用失败")
            
            return success
            
        except Exception as e:
            self.logger.error(f"插件 {self.PLUGIN_NAME} 停用异常: {e}")
            return False
    
    def cleanup(self) -> bool:
        """清理插件"""
        try:
            success = self._cleanup_impl()
            if success:
                self.logger.info(f"插件 {self.PLUGIN_NAME} 清理完成")
                
                # 发布清理完成事件
                self._publish_event('plugin.cleaned', {
                    'plugin_name': self.PLUGIN_NAME,
                    'success': success
                })
            else:
                self.logger.error(f"插件 {self.PLUGIN_NAME} 清理失败")
            
            return success
            
        except Exception as e:
            self.logger.error(f"插件 {self.PLUGIN_NAME} 清理异常: {e}")
            return False
    
    def on_enable(self):
        """插件启用时的回调"""
        pass
    
    def on_disable(self):
        """插件禁用时的回调"""
        pass
    
    def is_enabled(self) -> bool:
        """检查插件是否启用"""
        return self._enabled
    
    def is_initialized(self) -> bool:
        """检查插件是否已初始化"""
        return self._initialized
    
    def is_configured(self) -> bool:
        """检查插件是否已配置"""
        return self._configured
    
    def get_status(self) -> Dict[str, Any]:
        """获取插件状态"""
        return {
            'name': self.PLUGIN_NAME,
            'version': self.PLUGIN_VERSION,
            'enabled': self._enabled,
            'initialized': self._initialized,
            'configured': self._configured,
            'error': self._error,
            'config_keys': list(self.config.keys())
        }
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        status = 'running' if self._enabled else 'stopped'
        if self._error:
            status = 'error'
        elif self._configured and not self._enabled:
            status = 'configured'
        elif self._initialized and not self._configured:
            status = 'initialized'
        
        return {
            'status': status,
            'plugin_name': self.PLUGIN_NAME,
            'version': self.PLUGIN_VERSION
        }
    
    def _publish_event(self, event_type: str, data: Dict[str, Any] = None):
        """发布事件到事件总线"""
        try:
            event_data = data or {}
            event_data['timestamp'] = time.time()
            event_data['plugin_name'] = self.PLUGIN_NAME
            
            # 查找事件总线
            event_bus = None
            if self.event_bus:
                event_bus = self.event_bus
            elif hasattr(self.node, 'event_bus'):
                event_bus = self.node.event_bus
            
            # 发布事件
            if event_bus and hasattr(event_bus, 'publish'):
                event_bus.publish(event_type, event_data)
                
        except Exception as e:
            # 事件发布失败不应影响插件功能
            if hasattr(self, 'logger'):
                self.logger.debug(f"发布事件失败 {event_type}: {e}")
    
    # 提供默认实现而不是抽象方法
    def _configure_impl(self) -> bool:
        """配置实现 - 默认实现"""
        self.logger.info(f"插件 {self.PLUGIN_NAME} 配置完成")
        return True
    
    def _activate_impl(self) -> bool:
        """激活实现 - 默认实现"""
        self.logger.info(f"插件 {self.PLUGIN_NAME} 激活完成")
        return True
    
    def _deactivate_impl(self) -> bool:
        """停用实现 - 默认实现"""
        self.logger.info(f"插件 {self.PLUGIN_NAME} 停用完成")
        return True
    
    def _cleanup_impl(self) -> bool:
        """清理实现 - 默认实现"""
        self.logger.info(f"插件 {self.PLUGIN_NAME} 清理完成")
        return True