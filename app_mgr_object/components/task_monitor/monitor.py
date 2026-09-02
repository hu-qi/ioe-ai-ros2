#!/usr/bin/env python3
"""
TaskStatusMonitor — 任务状态按需周期轮询组件（v2.0）

与 v1.0 的差异:
  - 新增强制闲置检测 poll_if_needed(active_instances)
  - 应只在 active_instances 非空时被调用
  - 内置 idle_rounds 计数器用于两轮确认机制
"""

import time
import logging
import threading
from typing import Dict, Optional, Callable


class TaskStatusCode:
    PENDING     = "0"
    DISPATCHING = "1"
    RUNNING     = "2"
    PAUSED      = "3"
    FAILED      = "7"
    CANCELLED   = "8"
    COMPLETED   = "9"

    FINAL_STATES = {FAILED, CANCELLED, COMPLETED}
    
    # 状态码到名称的映射
    CODE_TO_NAME = {
        "0": "PENDING",
        "1": "DISPATCHING",
        "2": "RUNNING",
        "3": "PAUSED",
        "7": "FAILED",
        "8": "CANCELLED",
        "9": "COMPLETED",
    }

    # 名称到状态码的反向映射
    NAME_TO_CODE = {v: k for k, v in CODE_TO_NAME.items()}

    @classmethod
    def to_engine_event(cls, status_code: str) -> Optional[str]:
        mapping = {
            cls.COMPLETED:  'callback_completed',
            cls.FAILED:     'callback_exception',
            cls.CANCELLED:  'callback_exception',
        }
        return mapping.get(status_code, None)

    @classmethod
    def status_name(cls, code: str) -> str:
        return cls.CODE_TO_NAME.get(code, 'UNKNOWN')
    
    @classmethod
    def normalize(cls, status: str) -> str:
        """将状态名称或状态码统一转换为数字状态码"""
        # 如果已经是数字状态码（在映射中），直接返回
        if status in cls.CODE_TO_NAME:
            return status
        # 否则尝试按名称映射
        return cls.NAME_TO_CODE.get(status, status)  # 若无法映射则原样返回


class TaskStatusMonitor:

    def __init__(self,
                 on_status_changed: Optional[Callable[[str, str, str], None]] = None,
                 poll_timeout: float = 8.0,
                 logger=None):
        self._on_status_changed = on_status_changed
        self._poll_timeout = poll_timeout
        self._logger = logger

        self._last_known: Dict[str, str] = {}
        self._lock = threading.RLock()

        # 统计
        self._poll_count: int = 0
        self._poll_skip_count: int = 0       # 新增: 无任务跳过次数
        self._poll_error_count: int = 0
        self._change_detected_count: int = 0
        self._last_poll_time: float = 0.0
        self._last_poll_duration_ms: float = 0.0
        self._idle_consecutive_rounds: int = 0  # 新增: 连续空闲轮数

    # ════════════════════════════════════════════════════
    #  核心: poll_if_needed (按需入口)
    # ════════════════════════════════════════════════════

    def poll_if_needed(self, rcs_adapter, active_instances: Dict[str, str]) -> bool:
        """按需执行一轮轮询

        由插件层的 Timer 回调调用。插件层已在外部判断 active_instances
        非空时才调用此方法，但此方法仍做二次防护。

        Args:
            rcs_adapter:      RCSAdapterPlugin 实例
            active_instances: {task_code: rcs_task_no} 映射

        Returns:
            True  — 本轮实际执行了 RCS 查询
            False — 无活跃实例，跳过本轮（调用方可用于停止 timer）
        """
        if not active_instances:
            self._poll_skip_count += 1
            self._idle_consecutive_rounds += 1
            self._log_debug(f"无活跃实例, 跳过第 {self._poll_skip_count} 次轮询 "
                            f"(连续空闲 {self._idle_consecutive_rounds} 轮)")
            return False

        # 有活跃实例时重置空闲计数
        self._idle_consecutive_rounds = 0
        changes = self._do_poll(rcs_adapter, active_instances)
        return True

    def should_stop_timer(self) -> bool:
        """判断是否应该停止定时器（连续 2 轮无活跃实例）"""
        return self._idle_consecutive_rounds >= 2

    # ════════════════════════════════════════════════════
    #  内部轮询逻辑
    # ════════════════════════════════════════════════════

    def _do_poll(self, rcs_adapter, active_instances: Dict[str, str]) -> Dict[str, str]:
        self._poll_count += 1
        task_codes = list(active_instances.keys())
        start_time = time.time()
        self._log_debug(f"第 {self._poll_count} 轮轮询: {len(task_codes)} 个任务")

        try:
            resp = rcs_adapter.query_task_status(task_codes)
            elapsed = (time.time() - start_time) * 1000
            self._last_poll_time = start_time
            self._last_poll_duration_ms = elapsed

            if resp.get('code') != '0':
                self._poll_error_count += 1
                self._log_warning(f"RCS queryTaskStatus 异常: code={resp.get('code')}")
                return {}

            data_list = resp.get('data', [])
            if not isinstance(data_list, list):
                self._poll_error_count += 1
                return {}

            changes = {}
            for item in data_list:
                task_code = item.get('taskCode', '')
                if not task_code:
                    continue

                raw_status = item.get('taskStatus', '')
                # 标准化为数字状态码
                new_status = TaskStatusCode.normalize(str(raw_status))

                old_status = self._get_last_known(task_code)
                if old_status == new_status:
                    continue

                self._set_last_known(task_code, new_status)
                changes[task_code] = new_status
                self._change_detected_count += 1

                self._log_info(f"状态变化: {task_code} "
                    f"{TaskStatusCode.status_name(old_status) if old_status else '---'}→"
                    f"{TaskStatusCode.status_name(new_status)}")

                if new_status in TaskStatusCode.FINAL_STATES:
                    engine_event = TaskStatusCode.to_engine_event(new_status)
                    if engine_event and self._on_status_changed:
                        try:
                            self._on_status_changed(task_code, new_status, engine_event)
                        except Exception as e:
                            self._log_error(f"状态变化回调异常: {e}")

            self._cleanup_final(active_instances)
            self._poll_error_count = 0
            return changes

        except Exception as e:
            self._poll_error_count += 1
            self._log_error(f"轮询异常: {e}")
            return {}

    # ════════════════════════════════════════════════════

    def _get_last_known(self, task_code: str) -> str:
        with self._lock:
            return self._last_known.get(task_code, '')

    def _set_last_known(self, task_code: str, status: str):
        with self._lock:
            self._last_known[task_code] = status

    def _cleanup_final(self, active: Dict[str, str]):
        with self._lock:
            to_remove = [tc for tc, st in self._last_known.items()
                         if st in TaskStatusCode.FINAL_STATES]
            for tc in to_remove:
                self._last_known.pop(tc, None)
                active.pop(tc, None)
                self._log_debug(f"已清理终态任务: {tc}")

    def reset(self):
        with self._lock:
            self._last_known.clear()
            self._poll_count = 0
            self._poll_skip_count = 0
            self._poll_error_count = 0
            self._change_detected_count = 0
            self._idle_consecutive_rounds = 0

    def get_last_known_status(self, task_code: str) -> Optional[str]:
        with self._lock:
            return self._last_known.get(task_code, None)

    def get_all_last_known(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._last_known)

    def get_stats(self) -> dict:
        return {
            'poll_count': self._poll_count,
            'poll_skip_count': self._poll_skip_count,
            'poll_error_count': self._poll_error_count,
            'change_detected_count': self._change_detected_count,
            'last_poll_time': self._last_poll_time,
            'last_poll_duration_ms': self._last_poll_duration_ms,
            'monitored_tasks': len(self._last_known),
            'idle_consecutive_rounds': self._idle_consecutive_rounds,
        }

    def _log_info(self, msg: str):
        if self._logger: self._logger.info(f"[TaskMonitor] {msg}")

    def _log_debug(self, msg: str):
        if self._logger: self._logger.debug(f"[TaskMonitor] {msg}")

    def _log_warning(self, msg: str):
        if self._logger: self._logger.warning(f"[TaskMonitor] {msg}")

    def _log_error(self, msg: str):
        if self._logger: self._logger.error(f"[TaskMonitor] {msg}")