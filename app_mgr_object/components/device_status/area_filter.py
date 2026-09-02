#!/usr/bin/env python3

from collections import deque
import time
from typing import Dict, Any, Optional
import logging


class AreaStatusFilter:
    """区域状态滤波器 - 处理单个区域的状态滤波"""

    def __init__(self, stable_threshold: int = 5, timeout: float = 2.0, logger: Optional[logging.Logger] = None):
        """
        初始化区域状态滤波器

        Args:
            stable_threshold: 稳定状态判定阈值
            timeout: 滤波超时时间(秒)
            logger: 日志记录器
        """
        self.stable_threshold = stable_threshold
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)
        self.status_queue = deque(maxlen=stable_threshold)
        self.last_update_time = time.time()
        self.current_stable_state = False
        self.stable_state_changed = False
        self.update_count = 0

    def update(self, new_status: bool) -> Dict[str, Any]:
        """
        更新状态并返回滤波结果

        Args:
            new_status: 新的状态值

        Returns:
            包含状态变化信息的字典
        """
        current_time = time.time()
        self.update_count += 1

        # 检查超时，如果超时则清空队列
        if current_time - self.last_update_time > self.timeout:
            if self.status_queue:
                self.logger.debug("状态滤波超时，清空历史状态队列")
            self.status_queue.clear()

        # 添加新状态到队列
        self.status_queue.append(new_status)
        self.last_update_time = current_time

        result = {
            'changed': False,
            'current_state': self.current_stable_state,
            'queue_size': len(self.status_queue),
            'update_count': self.update_count
        }

        # 检查是否达到稳定状态判定条件
        if len(self.status_queue) >= self.stable_threshold:
            all_true = all(self.status_queue)
            all_false = not any(self.status_queue)

            old_state = self.current_stable_state

            if all_true and not self.current_stable_state:
                self.current_stable_state = True
                self.stable_state_changed = True
                result['changed'] = True
                result['current_state'] = True
                result['change_type'] = 'true_stable'

            elif all_false and self.current_stable_state:
                self.current_stable_state = False
                self.stable_state_changed = True
                result['changed'] = True
                result['current_state'] = False
                result['change_type'] = 'false_stable'
            else:
                self.stable_state_changed = False
                result['change_type'] = 'no_change'
        else:
            result['change_type'] = 'collecting'

        return result

    def get_status_info(self) -> Dict[str, Any]:
        """获取当前状态信息"""
        return {
            'current_stable_state': self.current_stable_state,
            'queue_size': len(self.status_queue),
            'queue_contents': list(self.status_queue),
            'last_update_time': self.last_update_time,
            'update_count': self.update_count
        }

    def reset(self):
        """重置滤波器状态"""
        self.status_queue.clear()
        self.current_stable_state = False
        self.stable_state_changed = False
        self.update_count = 0
        self.last_update_time = time.time()