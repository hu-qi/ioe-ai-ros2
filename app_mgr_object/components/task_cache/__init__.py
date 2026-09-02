#!/usr/bin/env python3
"""
状态缓存组件包

提供：
  - BayCache          : 起始仓位状态缓存（24个仓位）
  - BayCacheEntry     : 仓位状态条目
  - DestBayCache      : 终点仓位状态缓存（T2001~T4006）
  - DestBayCacheEntry : 终点仓位状态条目
  - RobotCache        : AGV叉车状态缓存
  - RobotCacheEntry   : 叉车状态条目
  - ConfigCache       : 配置热缓存（仓位映射、工作时段）
  - ScheduleEntry     : 工作时段条目
"""

from .bay_cache import BayCache, BayCacheEntry
from .dest_bay_cache import DestBayCache, DestBayCacheEntry
from .robot_cache import RobotCache, RobotCacheEntry
from .config_cache import ConfigCache, ScheduleEntry
from .state_coordinator import StateCoordinator

__all__ = [
    'BayCache', 'BayCacheEntry',
    'DestBayCache', 'DestBayCacheEntry',
    'RobotCache', 'RobotCacheEntry',
    'ConfigCache', 'ScheduleEntry',
    'StateCoordinator',
]