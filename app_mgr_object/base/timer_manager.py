#!/usr/bin/env python3
"""
定时器管理器 - 管理ROS2定时器
"""

import threading
import time
from typing import Dict, Any, Optional, Callable, List
from rclpy.node import Node


class TimerManager:
    def __init__(self, node: Node):
        self.node = node
        self.logger = node.get_logger()
        self._timers: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._timer_stats = {}

    
    def create_timer(self, timer_name: str, callback: Callable,
                 period_sec: float, oneshot: bool = False,
                 autostart: bool = True) -> bool:
        with self._lock:
            if timer_name in self._timers:
                self.logger.warning(f"定时器 {timer_name} 已存在")
                return False

            try:
                # 一次性定时器：执行后自动取消
                if oneshot:
                    def oneshot_callback():
                        try:
                            callback()
                            self._update_timer_stats(timer_name, time.time(), True)
                        except Exception as e:
                            self.logger.error(f"定时器 {timer_name} 回调执行失败: {e}")
                            self._update_timer_stats(timer_name, time.time(), False)
                        finally:
                            self.cancel_timer(timer_name)

                    timer = self.node.create_timer(period_sec, oneshot_callback)

                    # 初始化统计信息
                    self._timer_stats[timer_name] = {
                        'total_executions': 0,
                        'successful_executions': 0,
                        'failed_executions': 0,
                        'last_execution_time': 0,
                        'average_execution_time': 0,
                        'created_time': time.time()
                    }
                    self._timers[timer_name] = {
                        'timer': timer,
                        'callback': callback,
                        'period': period_sec,
                        'oneshot': True,
                        'autostart': autostart,
                        'running': autostart
                    }
                    if not autostart:
                        timer.cancel()
                        self._timers[timer_name]['running'] = False

                    self.logger.info(f"一次性定时器创建成功: {timer_name} (延迟: {period_sec}s)")
                    return True

                # 周期性定时器
                else:
                    def periodic_callback():
                        start = time.time()
                        try:
                            callback()
                            self._update_timer_stats(timer_name, start, True)
                        except Exception as e:
                            self.logger.error(f"定时器 {timer_name} 回调执行失败: {e}")
                            self._update_timer_stats(timer_name, start, False)

                    timer = self.node.create_timer(period_sec, periodic_callback)

                    # 初始化统计信息
                    self._timer_stats[timer_name] = {
                        'total_executions': 0,
                        'successful_executions': 0,
                        'failed_executions': 0,
                        'last_execution_time': 0,
                        'average_execution_time': 0,
                        'created_time': time.time()
                    }
                    self._timers[timer_name] = {
                        'timer': timer,
                        'callback': callback,
                        'period': period_sec,
                        'oneshot': False,
                        'autostart': autostart,
                        'running': autostart
                    }
                    if not autostart:
                        timer.cancel()
                        self._timers[timer_name]['running'] = False

                    self.logger.info(f"周期性定时器创建成功: {timer_name} (周期: {period_sec}s)")
                    return True

            except Exception as e:
                self.logger.error(f"创建定时器 {timer_name} 失败: {e}")
                return False

    def _update_timer_stats(self, name: str, start: float, success: bool):
        if name not in self._timer_stats:
            return
        exec_time = time.time() - start
        stats = self._timer_stats[name]
        stats['total_executions'] += 1
        if success:
            stats['successful_executions'] += 1
        else:
            stats['failed_executions'] += 1
        stats['last_execution_time'] = exec_time
        if stats['average_execution_time'] == 0:
            stats['average_execution_time'] = exec_time
        else:
            stats['average_execution_time'] = stats['average_execution_time'] * 0.9 + exec_time * 0.1

    def start_timer(self, timer_name: str) -> bool:
        with self._lock:
            if timer_name not in self._timers:
                self.logger.error(f"定时器 {timer_name} 不存在")
                return False
            info = self._timers[timer_name]
            if info['running']:
                return True
            try:
                info['timer'].reset()
                info['running'] = True
                self.logger.info(f"定时器 {timer_name} 已启动")
                return True
            except Exception as e:
                self.logger.error(f"启动定时器 {timer_name} 失败: {e}")
                return False

    def cancel_timer(self, timer_name: str) -> bool:
        with self._lock:
            if timer_name not in self._timers:
                self.logger.error(f"定时器 {timer_name} 不存在")
                return False
            info = self._timers[timer_name]
            if not info['running']:
                return True
            try:
                info['timer'].cancel()
                info['running'] = False
                self.logger.info(f"定时器 {timer_name} 已取消")
                return True
            except Exception as e:
                self.logger.error(f"取消定时器 {timer_name} 失败: {e}")
                return False

    def remove_timer(self, timer_name: str) -> bool:
        with self._lock:
            if timer_name not in self._timers:
                self.logger.warning(f"定时器 {timer_name} 不存在")
                return False
            try:
                if self._timers[timer_name]['running']:
                    self._timers[timer_name]['timer'].cancel()
                del self._timers[timer_name]
                if timer_name in self._timer_stats:
                    del self._timer_stats[timer_name]
                self.logger.info(f"定时器 {timer_name} 已移除")
                return True
            except Exception as e:
                self.logger.error(f"移除定时器 {timer_name} 失败: {e}")
                return False

    def remove_all_timers(self):
        with self._lock:
            names = list(self._timers.keys())
            for name in names:
                self.remove_timer(name)

    def get_timer(self, timer_name: str):
        with self._lock:
            return self._timers.get(timer_name)

    def get_all_timers(self) -> Dict[str, Any]:
        with self._lock:
            return {
                name: {
                    'period': info['period'],
                    'oneshot': info['oneshot'],
                    'running': info['running'],
                    'callback': info['callback'].__name__ if hasattr(info['callback'], '__name__') else 'unknown'
                }
                for name, info in self._timers.items()
            }

    def get_timer_stats(self, timer_name: str = None) -> Dict[str, Any]:
        with self._lock:
            if timer_name:
                return self._timer_stats.get(timer_name, {})
            return self._timer_stats.copy()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            running = sum(1 for t in self._timers.values() if t['running'])
            oneshot = sum(1 for t in self._timers.values() if t['oneshot'])
            return {
                'total_timers': len(self._timers),
                'running_timers': running,
                'stopped_timers': len(self._timers) - running,
                'oneshot_timers': oneshot,
                'periodic_timers': len(self._timers) - oneshot,
                'status': 'running'
            }