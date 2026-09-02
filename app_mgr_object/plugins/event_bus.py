# core/event_bus.py
#!/usr/bin/env python3
"""
事件总线 - 插件间通信机制（支持同步和异步发布）
"""
import rclpy.logging
from typing import Dict, Any, Callable, List
import threading
import asyncio


class EventBus:
    """事件总线 - 支持同步和异步事件发布"""
    
    def __init__(self, logger=None):
        self._listeners: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()
        self.logger = logger or rclpy.logging.get_logger('EventBus')
    
    def subscribe(self, event_type: str, callback: Callable):
        """订阅事件"""
        with self._lock:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            self._listeners[event_type].append(callback)
    
    def unsubscribe(self, event_type: str, callback: Callable):
        """取消订阅"""
        with self._lock:
            if event_type in self._listeners and callback in self._listeners[event_type]:
                self._listeners[event_type].remove(callback)
    
    def publish(self, event_type: str, data: Any = None):
        """
        同步发布事件（支持同步和异步回调）
        """
        with self._lock:
            if event_type not in self._listeners:
                return
            listeners = self._listeners[event_type][:]

        for callback in listeners:
            try:
                if asyncio.iscoroutinefunction(callback):
                    # 异步回调：获取当前事件循环并创建任务
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(callback(data))
                    except RuntimeError:
                        # 没有运行中的事件循环，创建新循环运行
                        asyncio.run(callback(data))
                else:
                    callback(data)
            except Exception as e:
                self.logger.error(f"事件处理错误: {e}")
    
    async def async_publish(self, event_type: str, data: Any = None):
        """
        异步发布事件（Phase 0 新增）
        
        特性：
        1. 在 asyncio 事件循环中安全调用，不阻塞主线程
        2. 使用 run_in_executor 将同步回调放到线程池执行
        3. 支持混合回调（同步函数和异步函数）
        """
        loop = asyncio.get_event_loop()
        
        with self._lock:
            if event_type not in self._listeners:
                return
            
            # 复制监听器列表，防止在迭代过程中被修改
            listeners = self._listeners[event_type][:]
        
        # 并发执行所有回调（不阻塞彼此）
        tasks = []
        for callback in listeners:
            if asyncio.iscoroutinefunction(callback):
                # 如果回调本身就是异步函数，直接 await
                tasks.append(callback(data))
            else:
                # 如果是同步函数，在线程池中执行以避免阻塞事件循环
                tasks.append(loop.run_in_executor(None, callback, data))
        
        if tasks:
            # 等待所有回调执行完成（或超时控制）
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def clear(self):
        """清空所有监听器"""
        with self._lock:
            self._listeners.clear()