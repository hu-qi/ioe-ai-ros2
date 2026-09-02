#!/usr/bin/env python3
"""
叉车状态缓存 — 维护 AGV 叉车（1001, 1002）的实时状态

数据结构（内存）:
    _robots: {
        1001: {
            "robot_id":         1001,
            "status":           "IDLE",     # IDLE/BUSY/OFFLINE/ERROR
            "current_task_id":  "",
            "battery":          85,
            "position_code":    "",
            "update_time":      1723456789.0,
        },
        ...
    }
"""

import time
import threading
from typing import Dict, List, Optional


class RobotCacheEntry:
    """叉车状态条目"""
    __slots__ = ('robot_id', 'status', 'current_task_id', 'battery',
                 'position_code', 'update_time', 'revision', 'source')

    def __init__(self, robot_id: int):
        self.robot_id = robot_id
        self.status = 'OFFLINE'
        self.current_task_id = ''
        self.battery = 0
        self.position_code = ''
        self.update_time = 0.0
        self.revision = 0
        self.source = 'init'   
        

    def to_dict(self) -> dict:
        return {
            'robot_id': self.robot_id,
            'status': self.status,
            'current_task_id': self.current_task_id,
            'battery': self.battery,
            'position_code': self.position_code,
            'update_time': self.update_time,
            'revision': self.revision,
            'source': self.source,
        }


class RobotCache:
    """叉车状态缓存"""

    def __init__(self, robot_ids: List[int] = None, logger=None):
        """
        Args:
            robot_ids: AGV 编号列表，如 [1001, 1002]
            logger: 日志记录器
        """
        self._lock = threading.RLock()
        self._logger = logger
        self._robots: Dict[int, RobotCacheEntry] = {}
        self._next_index = 0   # 轮询游标，仅属于 RobotCache
        # AGV 选择策略（doc/52 §7.3）：round_robin / least_busy / specified
        self._select_strategy = 'round_robin'
        self._available_statuses = ('AVAILABLE',)
        self._specified_ids: List[int] = []

        if robot_ids:
            for rid in robot_ids:
                self._robots[rid] = RobotCacheEntry(rid)

    # ── 写入接口 ──

    def update_status(self, robot_id: int, status: str,
                      battery: int = None, position_code: str = None,
                      source: str = 'polling'):
        """更新叉车状态"""
        with self._lock:
            entry = self._robots.get(robot_id)
            if not entry:
                return
            entry.status = status
            entry.update_time = time.time()
            entry.source = source
            entry.revision += 1
            if battery is not None:
                entry.battery = battery
            if position_code is not None:
                entry.position_code = position_code

    def set_busy(self, robot_id: int, task_id: str = '', source: str = 'workflow'):
        """标记叉车为忙碌"""
        with self._lock:
            entry = self._robots.get(robot_id)
            if entry:
                entry.status = 'BUSY'
                entry.current_task_id = task_id
                entry.update_time = time.time()
                entry.source = source
                entry.revision += 1

    def set_idle(self, robot_id: int, source: str = 'workflow'):
        """标记叉车为空闲"""
        with self._lock:
            entry = self._robots.get(robot_id)
            if entry:
                entry.status = 'AVAILABLE'
                entry.current_task_id = ''
                entry.update_time = time.time()
                entry.source = source
                entry.revision += 1

    def set_select_policy(self, strategy: str = None,
                          available_statuses: list = None,
                          specified_ids: list = None):
        """热加载：AGV 选择策略（round_robin/least_busy/specified）与可调度状态集合。

        strategy: round_robin（轮询，现状）/ least_busy（空闲最早）/ specified（指定编号）；
        available_statuses: 可调度状态集合，如 ['AVAILABLE']；
        specified_ids: strategy=specified 时的 AGV 编号列表。
        """
        with self._lock:
            if strategy:
                s = str(strategy).strip().lower()
                if s in ('round_robin', 'least_busy', 'specified'):
                    self._select_strategy = s
            if available_statuses is not None:
                self._available_statuses = tuple(
                    str(x) for x in available_statuses if str(x).strip())
            if specified_ids is not None:
                self._specified_ids = [int(x) for x in specified_ids]

    # ── 查询接口 ──

    # def get_idle_robot(self) -> Optional[int]:
    #     """获取任一空闲叉车的 ID"""
    #     with self._lock:
    #         for entry in self._robots.values():
    #             if entry.status == 'IDLE':
    #                 return entry.robot_id
    #         return None
        
    def get_idle_robot(self) -> Optional[int]:
        """旧接口，直接调用 get_available_robot"""
        return self.get_available_robot()
        
    def get_available_robot(self) -> Optional[int]:
        """获取一个可调度的AGV（策略：round_robin/least_busy/specified）"""
        with self._lock:
            available_ids = [rid for rid, entry in self._robots.items()
                             if entry.status in self._available_statuses]
            if not available_ids:
                return None

            if self._select_strategy == 'specified':
                pick = [rid for rid in available_ids if rid in self._specified_ids]
                if pick:
                    return pick[0]

            if self._select_strategy == 'least_busy':
                # 空闲最早（update_time 最小）优先，示例策略；可扩展任务数/电量加权
                return min(available_ids, key=lambda rid: self._robots[rid].update_time)

            # 轮询（现状）
            idx = self._next_index % len(available_ids)
            rid = available_ids[idx]
            self._next_index = (idx + 1) % len(available_ids)
            return rid

    def get_robot_status(self, robot_id: int) -> Optional[dict]:
        """获取单个叉车状态"""
        with self._lock:
            entry = self._robots.get(robot_id)
            return entry.to_dict() if entry else None

    def get_all_robot_status(self) -> Dict[int, dict]:
        """获取所有叉车状态"""
        with self._lock:
            return {rid: e.to_dict() for rid, e in self._robots.items()}

    def has_idle_robot(self) -> bool:
        """是否有空闲叉车"""
        return self.get_idle_robot() is not None

    def get_robot_count(self) -> int:
        """获取叉车总数"""
        return len(self._robots)
