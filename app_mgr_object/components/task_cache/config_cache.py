#!/usr/bin/env python3
"""
配置热缓存 — 维护可通过 Web 动态修改的业务配置

维护内容：
  - 仓位-货物类型映射
  - 工作时间窗口
  - 通用系统参数（防抖阈值、轮询间隔等）
"""

import time
import threading
from typing import Dict, List, Any, Optional


class ScheduleEntry:
    """工作时间窗口条目"""
    def __init__(self, day_of_week: str, start_time: str, end_time: str):
        self.day_of_week = day_of_week
        self.start_time = start_time      # "08:00"
        self.end_time = end_time          # "18:00"


class ConfigCache:
    """配置热缓存"""

    def __init__(self, sys_configs: Dict[str, str] = None, logger=None):
        """
        Args:
            sys_configs: 初始系统配置 {key: value}
            logger: 日志记录器
        """
        self._lock = threading.RLock()
        self._logger = logger

        # 系统配置
        self._sys_config: Dict[str, str] = sys_configs or {}

        # 仓位映射
        self._source_bay_mapping: Dict[str, int] = {}   # bay_id → cargo_type
        self._dest_bay_mapping: Dict[str, dict] = {}    # bay_id → {cargo_type, floor}

        # 工作时段
        self._schedules: List[ScheduleEntry] = []

        self._update_time = time.time()

    # ── 系统配置 ──

    def get_sys(self, key: str, default: Any = None) -> Any:
        """获取系统配置值"""
        with self._lock:
            return self._sys_config.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数类型系统配置"""
        try:
            return int(self.get_sys(key, str(default)))
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """获取浮点类型系统配置"""
        try:
            return float(self.get_sys(key, str(default)))
        except (ValueError, TypeError):
            return default

    def set_sys(self, key: str, value: str):
        """更新系统配置"""
        with self._lock:
            self._sys_config[key] = value
            self._update_time = time.time()

    # ── 仓位映射 ──

    def set_source_mapping(self, mapping: Dict[str, int]):
        """设置起始仓位映射"""
        with self._lock:
            self._source_bay_mapping = mapping.copy()
            self._update_time = time.time()

    def set_dest_mapping(self, mapping: Dict[str, dict]):
        """设置终点仓位映射"""
        with self._lock:
            self._dest_bay_mapping = mapping.copy()
            self._update_time = time.time()

    def get_source_mapping(self) -> Dict[str, int]:
        with self._lock:
            return self._source_bay_mapping.copy()

    def get_dest_mapping(self) -> Dict[str, dict]:
        with self._lock:
            return self._dest_bay_mapping.copy()

    # ── 工作时段 ──

    def set_schedules(self, schedules: List[Dict[str, str]]):
        """设置工作时段"""
        with self._lock:
            self._schedules = [
                ScheduleEntry(s['day_of_week'], s['start_time'], s['end_time'])
                for s in schedules
            ]
            self._update_time = time.time()

    def get_schedules(self) -> List[ScheduleEntry]:
        with self._lock:
            return list(self._schedules)

    def get_update_time(self) -> float:
        return self._update_time