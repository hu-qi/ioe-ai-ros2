#!/usr/bin/env python3
"""
通用信号监控器 - 集成稳定滤波、超时检测、连续错误与自动恢复
"""

from collections import deque
import time
from typing import Dict, Any, Optional
import logging


class SignalMonitor:
    """单信号状态监控器"""

    def __init__(self,
                 stable_threshold: int = 5,
                 timeout: float = 2.0,
                 error_threshold: int = 3,
                 recovery_time: float = 10.0,
                 logger: Optional[logging.Logger] = None):
        """
        Args:
            stable_threshold: 连续相同信号次数达到此值后状态稳定
            timeout: 信号更新时间超过此值(秒)则认为无效，会清空滤波队列
            error_threshold: 连续错误次数阈值，超过后保持异常，需自动恢复
            recovery_time: 异常后超过此时间(秒)无更新，自动恢复为正常
            logger: 日志记录器
        """
        self.stable_threshold = stable_threshold
        self.timeout = timeout
        self.error_threshold = error_threshold
        self.recovery_time = recovery_time
        self.logger = logger or logging.getLogger(__name__)

        self.status_queue = deque(maxlen=stable_threshold)
        self.last_update_time = time.time()
        self.current_stable_state = False
        self.continuous_error_count = 0
        self.update_count = 0

        self._signal_changed = False

    def update(self, new_signal: bool, timestamp: float = None) -> Dict[str, Any]:
        """
        更新信号并返回滤波结果

        Returns:
            dict with keys:
                changed: 稳定状态是否变化
                current_state: 当前稳定状态
                is_timeout: 是否超时（附加信息）
                continuous_error_count: 连续错误次数（附加信息）
        """
        if timestamp is None:
            timestamp = time.time()
        self.update_count += 1
        self._signal_changed = False

        # 超时处理：若距离上次更新超过 timeout，则清空队列，重置错误计数
        if timestamp - self.last_update_time > self.timeout:
            if self.status_queue:
                self.logger.debug("信号滤波超时，清空历史状态队列")
            self.status_queue.clear()
            self.continuous_error_count = 0

        self.status_queue.append(new_signal)
        self.last_update_time = timestamp

        # 稳定判定
        if len(self.status_queue) >= self.stable_threshold:
            all_true = all(self.status_queue)
            all_false = not any(self.status_queue)
            old_state = self.current_stable_state

            if all_true and not self.current_stable_state:
                self.current_stable_state = True
                self._signal_changed = True
                self.continuous_error_count = 0
            elif all_false and self.current_stable_state:
                self.current_stable_state = False
                self._signal_changed = True
                self.continuous_error_count += 1

        # 超时异常检查（若信号长时间无更新，视为异常）
        is_timeout = self.is_signal_timeout()
        if is_timeout:
            if self.current_stable_state:
                self.current_stable_state = False
                self._signal_changed = True

        # 自动恢复：若信号异常且超过 recovery_time 未更新，尝试恢复
        if not self.current_stable_state and not is_timeout:
            if self.continuous_error_count >= self.error_threshold:
                if timestamp - self.last_update_time > self.recovery_time:
                    self.current_stable_state = True
                    self.continuous_error_count = 0
                    self._signal_changed = True
                    self.logger.info("信号自动恢复")
                else:
                    self.current_stable_state = False
            else:
                # 未超过错误阈值，可视为临时波动，不改变状态
                pass

        return {
            'changed': self._signal_changed,
            'current_state': self.current_stable_state,
            'is_timeout': is_timeout,
            'continuous_error_count': self.continuous_error_count,
            'update_count': self.update_count
        }

    def is_signal_timeout(self) -> bool:
        """判断信号是否超时（超过 timeout 未更新）"""
        if self.timeout <= 0:
            return False
        return (time.time() - self.last_update_time) > self.timeout

    def get_status_info(self) -> Dict[str, Any]:
        return {
            'current_stable_state': self.current_stable_state,
            'queue_size': len(self.status_queue),
            'last_update_time': self.last_update_time,
            'update_count': self.update_count,
            'continuous_error_count': self.continuous_error_count
        }

    def reset(self):
        self.status_queue.clear()
        self.current_stable_state = False
        self.continuous_error_count = 0
        self.update_count = 0
        self.last_update_time = time.time()