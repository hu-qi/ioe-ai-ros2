#!/usr/bin/env python3
"""
生命周期管理器
"""

from enum import Enum
from typing import Dict, List, Any, Optional, Callable
import threading
import time


class LifecycleState(Enum):
    """生命周期状态"""
    UNCONFIGURED = "unconfigured"
    INACTIVE = "inactive"
    ACTIVE = "active"
    FINALIZED = "finalized"
    ERROR = "error"


class LifecycleManager:
    """生命周期管理器"""
    
    def __init__(self, node):
        self.node = node
        self.logger = node.get_logger()
        self._state = LifecycleState.UNCONFIGURED
        self._state_lock = threading.RLock()
        
        # 模块状态跟踪
        self._modules = {}  # name -> {'module': obj, 'state': LifecycleState}
        
        # 状态变更回调
        self._state_change_callbacks = []
    
    def register_module(self, name: str, module: Any, auto_activate: bool = False):
        """注册模块"""
        with self._state_lock:
            self._modules[name] = {
                'module': module,
                'state': LifecycleState.UNCONFIGURED,
                'auto_activate': auto_activate
            }
            self.logger.debug(f"注册模块: {name}")
    
    def configure(self, name: str = None) -> bool:
        """配置模块"""
        with self._state_lock:
            if name:
                # 配置单个模块
                if name not in self._modules:
                    self.logger.error(f"模块 {name} 未注册")
                    return False
                
                module_info = self._modules[name]
                try:
                    if hasattr(module_info['module'], 'configure'):
                        if module_info['module'].configure():
                            module_info['state'] = LifecycleState.INACTIVE
                            self.logger.info(f"模块 {name} 配置成功")
                            return True
                    else:
                        # 如果模块没有configure方法，直接标记为INACTIVE
                        module_info['state'] = LifecycleState.INACTIVE
                        return True
                except Exception as e:
                    self.logger.error(f"模块 {name} 配置失败: {e}")
                    module_info['state'] = LifecycleState.ERROR
                    return False
            
            else:
                # 配置所有模块
                success = True
                for mod_name in self._modules:
                    if not self.configure(mod_name):
                        success = False
                
                if success:
                    self._state = LifecycleState.INACTIVE
                    self.logger.info("所有模块配置完成")
                
                return success
    
    def activate(self, name: str = None) -> bool:
        """激活模块"""
        with self._state_lock:
            if name:
                # 激活单个模块
                if name not in self._modules:
                    self.logger.error(f"模块 {name} 未注册")
                    return False
                
                module_info = self._modules[name]
                if module_info['state'] != LifecycleState.INACTIVE:
                    self.logger.error(f"模块 {name} 状态不正确: {module_info['state']}")
                    return False
                
                try:
                    if hasattr(module_info['module'], 'activate'):
                        if module_info['module'].activate():
                            module_info['state'] = LifecycleState.ACTIVE
                            self.logger.info(f"模块 {name} 激活成功")
                            return True
                    else:
                        # 如果模块没有activate方法，直接标记为ACTIVE
                        module_info['state'] = LifecycleState.ACTIVE
                        return True
                except Exception as e:
                    self.logger.error(f"模块 {name} 激活失败: {e}")
                    module_info['state'] = LifecycleState.ERROR
                    return False
            
            else:
                # 激活所有模块
                success = True
                for mod_name, module_info in self._modules.items():
                    if module_info['auto_activate']:
                        if not self.activate(mod_name):
                            success = False
                
                if success:
                    self._state = LifecycleState.ACTIVE
                    self.logger.info("系统激活完成")
                
                return success
    
    def deactivate(self, name: str = None) -> bool:
        """停用模块"""
        with self._state_lock:
            if name:
                # 停用单个模块
                if name not in self._modules:
                    self.logger.error(f"模块 {name} 未注册")
                    return False
                
                module_info = self._modules[name]
                if module_info['state'] != LifecycleState.ACTIVE:
                    self.logger.warning(f"模块 {name} 不是活跃状态: {module_info['state']}")
                
                try:
                    if hasattr(module_info['module'], 'deactivate'):
                        if module_info['module'].deactivate():
                            module_info['state'] = LifecycleState.INACTIVE
                            self.logger.info(f"模块 {name} 停用成功")
                            return True
                    else:
                        # 如果模块没有deactivate方法，直接标记为INACTIVE
                        module_info['state'] = LifecycleState.INACTIVE
                        return True
                except Exception as e:
                    self.logger.error(f"模块 {name} 停用失败: {e}")
                    module_info['state'] = LifecycleState.ERROR
                    return False
            
            else:
                # 停用所有模块
                success = True
                for mod_name in self._modules:
                    if not self.deactivate(mod_name):
                        success = False
                
                if success:
                    self._state = LifecycleState.INACTIVE
                    self.logger.info("系统停用完成")
                
                return success
    
    def cleanup(self, name: str = None) -> bool:
        """清理模块"""
        with self._state_lock:
            if name:
                # 清理单个模块
                if name not in self._modules:
                    self.logger.error(f"模块 {name} 未注册")
                    return False
                
                module_info = self._modules[name]
                try:
                    if hasattr(module_info['module'], 'cleanup'):
                        module_info['module'].cleanup()
                    
                    module_info['state'] = LifecycleState.FINALIZED
                    self.logger.info(f"模块 {name} 清理完成")
                    return True
                except Exception as e:
                    self.logger.error(f"模块 {name} 清理失败: {e}")
                    module_info['state'] = LifecycleState.ERROR
                    return False
            
            else:
                # 清理所有模块
                success = True
                for mod_name in self._modules:
                    if not self.cleanup(mod_name):
                        success = False
                
                if success:
                    self._state = LifecycleState.FINALIZED
                    self.logger.info("系统清理完成")
                
                return success
    
    def shutdown(self):
        """关闭所有模块"""
        self.logger.info("开始关闭系统...")
        
        # 停用所有模块
        self.deactivate()
        
        # 清理所有模块
        self.cleanup()
        
        self.logger.info("系统关闭完成")
    
    def get_module_state(self, name: str) -> LifecycleState:
        """获取模块状态"""
        with self._state_lock:
            if name in self._modules:
                return self._modules[name]['state']
            return LifecycleState.UNCONFIGURED
    
    def get_system_state(self) -> LifecycleState:
        """获取系统状态"""
        return self._state
    
    def get_health_status(self) -> Dict[str, Any]:
        """获取健康状态"""
        with self._state_lock:
            health = {
                'system_state': self._state.value,
                'modules': {},
                'healthy': True
            }
            
            for name, info in self._modules.items():
                module_state = info['state']
                health['modules'][name] = module_state.value
                
                if module_state == LifecycleState.ERROR:
                    health['healthy'] = False
            
            return health
        
    def get_module_status(self, name: str) -> Dict[str, Any]:
        """获取模块详细状态"""
        with self._state_lock:
            if name not in self._modules:
                return {'error': f'模块 {name} 未注册'}
            
            module_info = self._modules[name]
            module = module_info['module']
            
            status = {
                'name': name,
                'state': module_info['state'].value,
                'auto_activate': module_info['auto_activate']
            }
            
            # 如果模块有状态方法，调用它
            if hasattr(module, 'get_status'):
                try:
                    module_status = module.get_status()
                    if isinstance(module_status, dict):
                        status.update(module_status)
                except Exception as e:
                    status['module_status_error'] = str(e)
            
            return status
    
    def get_all_modules_status(self) -> Dict[str, Any]:
        """获取所有模块状态"""
        with self._state_lock:
            modules_status = {}
            for name in self._modules:
                modules_status[name] = self.get_module_status(name)
            
            return {
                'system_state': self._state.value,
                'module_count': len(self._modules),
                'modules': modules_status
            }
    
    def add_state_change_callback(self, callback: Callable):
        """添加状态变更回调"""
        self._state_change_callbacks.append(callback)
    
    def trigger_state_change(self, from_state: LifecycleState, to_state: LifecycleState):
        """触发状态变更事件"""
        for callback in self._state_change_callbacks:
            try:
                callback(from_state, to_state)
            except Exception as e:
                self.logger.error(f"状态变更回调执行失败: {e}")
                
    def get_status(self) -> Dict[str, Any]:
        """获取管理器自身状态"""
        with self._state_lock:
            return {
                'system_state': self._state.value,
                'module_count': len(self._modules),
                'modules': {name: info['state'].value for name, info in self._modules.items()}
            }