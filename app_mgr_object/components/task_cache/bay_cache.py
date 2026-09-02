#!/usr/bin/env python3
"""
起始仓位状态缓存 — 维护起始仓位（A/B/C/D 前缀，如 A1001~D1006）的实时状态

修剪语义：topic 为全量周期发布（rtsp BayStatusPublisher 每 0.3s 遍历所有通道×仓位），
update_ai_result 每次刷新 last_seen；因此 prune_stale 可安全删除「曾出现但已消失」
的键（仓位改名/删除后不再出现在 topic 中），避免残留键导致前端「多仓位」。

数据结构（内存）:
    _bays: {
        "A1001": {
            "bay_id":       "A1001",
            "cargo_type":   1,
            "ai_detected":  True,
            "bind_status":  1,     # 0=未绑定, 1=已绑定, 2=绑定中
            "debounce_count": 3,
            "in_task":      False, # 是否已被分配任务
            "last_seen":    1723456789.0,
            "bind_time":    1723456790.0,
        },
        ...
    }
"""

import time
import threading
from typing import Dict, List, Optional


class BayCacheEntry:
    """单个仓位状态条目"""
    __slots__ = ('bay_id', 'cargo_type', 'ai_detected', 'bind_status',
                 'debounce_count', 'in_task', 'last_seen', 'bind_time',
                 'revision', 'source')

    def __init__(self, bay_id: str, cargo_type: int):
        self.bay_id = bay_id
        self.cargo_type = cargo_type
        self.ai_detected = False
        self.bind_status = 0
        self.debounce_count = 0
        self.in_task = False
        self.last_seen = 0.0
        self.bind_time = 0.0
        self.revision = 0
        self.source = 'init'

    def to_dict(self) -> dict:
        return {
            'bay_id': self.bay_id,
            'cargo_type': self.cargo_type,
            'ai_detected': self.ai_detected,
            'bind_status': self.bind_status,
            'debounce_count': self.debounce_count,
            'in_task': self.in_task,
            'last_seen': self.last_seen,
            'bind_time': self.bind_time,
            'revision': self.revision,
            'source': self.source,
        }

class BayCache:
    """起始仓位状态缓存"""

    def __init__(self, bay_configs: Dict[str, int] = None, logger=None):
        """
        Args:
            bay_configs: {bay_id: cargo_type} 初始配置
            logger: 日志记录器
        """
        self._lock = threading.RLock()
        self._logger = logger
        self._bays: Dict[str, BayCacheEntry] = {}

        if bay_configs:
            for bay_id, cargo_type in bay_configs.items():
                self._bays[bay_id] = BayCacheEntry(bay_id, cargo_type)

    # ── 写入接口 ──

    def update_ai_result(self, bay_id: str, has_cargo: bool, cargo_type: int = None):
        """更新 AI 检测原始结果"""
        with self._lock:
            entry = self._ensure_entry(bay_id, cargo_type)
            entry.ai_detected = has_cargo
            entry.last_seen = time.time()

    def increment_debounce(self, bay_id: str):
        """递增防抖计数"""
        with self._lock:
            entry = self._ensure_entry(bay_id, None)
            entry.debounce_count += 1

    def reset_debounce(self, bay_id: str):
        """重置防抖计数（收到无货信号时调用）"""
        with self._lock:
            entry = self._ensure_entry(bay_id, None)
            entry.debounce_count = 0

    def set_bound(self, bay_id: str):
        """标记仓位已绑定"""
        with self._lock:
            entry = self._ensure_entry(bay_id, None)
            entry.bind_status = 1
            entry.bind_time = time.time()

    def set_binding(self, bay_id: str):
        """标记仓位绑定中"""
        with self._lock:
            entry = self._ensure_entry(bay_id, None)
            entry.bind_status = 2

    def set_unbound(self, bay_id: str):
        """标记仓位未绑定"""
        with self._lock:
            entry = self._ensure_entry(bay_id, None)
            entry.bind_status = 0
            entry.bind_time = 0.0

    def mark_in_task(self, bay_id: str, value: bool = True, source: str = 'task'):
        """标记仓位被任务占用 / 释放"""
        with self._lock:
            entry = self._ensure_entry(bay_id, None)
            entry.in_task = value
            entry.source = source
            entry.revision += 1

    def update_cargo_type(self, bay_id: str, cargo_type: int):
        """更新仓位货物类型（配置热更新）"""
        with self._lock:
            if bay_id in self._bays:
                self._bays[bay_id].cargo_type = cargo_type

    # ── 查询接口 ──

    def get_bound_bays_of_type(self, cargo_type: int,
                               exclude_in_task: bool = True) -> List[str]:
        """获取指定类型下已绑定且可调度的仓位列表"""
        with self._lock:
            result = []
            for entry in self._bays.values():
                if entry.cargo_type != cargo_type:
                    continue
                if entry.bind_status != 1:
                    continue
                if exclude_in_task and entry.in_task:
                    continue
                result.append(entry.bay_id)
            return result

    def get_any_bound_bay(self, cargo_type: int) -> Optional[str]:
        """获取指定类型下任一已绑定且未分配任务的仓位"""
        bays = self.get_bound_bays_of_type(cargo_type, exclude_in_task=True)
        return bays[0] if bays else None

    def get_bay_status(self, bay_id: str) -> Optional[dict]:
        """获取单个仓位完整状态"""
        with self._lock:
            entry = self._bays.get(bay_id)
            return entry.to_dict() if entry else None

    def get_all_bay_status(self) -> Dict[str, dict]:
        """获取所有仓位状态快照"""
        with self._lock:
            return {bay_id: entry.to_dict()
                    for bay_id, entry in self._bays.items()}

    def get_bay_count(self) -> int:
        """获取仓位总数"""
        return len(self._bays)

    def get_bound_count(self) -> int:
        """获取已绑定仓位数量"""
        with self._lock:
            return sum(1 for e in self._bays.values() if e.bind_status == 1)

    def has_bound_bay_of_type(self, cargo_type: int) -> bool:
        """指定类型是否有已绑定且未分配任务的仓位"""
        return len(self.get_bound_bays_of_type(cargo_type)) > 0

    # ── 内部方法 ──

    def _ensure_entry(self, bay_id: str,
                      cargo_type: Optional[int]) -> BayCacheEntry:
        """确保仓位条目存在，不存在则创建"""
        if bay_id not in self._bays:
            ct = cargo_type if cargo_type is not None else 0
            self._bays[bay_id] = BayCacheEntry(bay_id, ct)
            if self._logger:
                self._logger.debug(f"新仓位注册: {bay_id} type={ct}")
        elif cargo_type is not None and cargo_type > 0:
            current = self._bays[bay_id]
            if current.cargo_type == 0:
                current.cargo_type = cargo_type
        return self._bays[bay_id]

    def reload_config(self, bay_configs: Dict[str, int]):
        """热加载仓位配置（用于 Web 配置更新后）"""
        with self._lock:
            for bay_id, cargo_type in bay_configs.items():
                if bay_id in self._bays:
                    self._bays[bay_id].cargo_type = cargo_type
                else:
                    self._bays[bay_id] = BayCacheEntry(bay_id, cargo_type)


    def prune_stale(self, timeout: float = 2.0) -> List[str]:
        """修剪「曾出现但已消失」的仓位条目，返回被删除的 bay_id 列表。

        前提：主题为全量周期发布（rtsp 每 0.3s 一帧、每帧含全部仓位），
        每帧 update_ai_result 会刷新 last_seen；因此
        now - last_seen > timeout 的键 = 已从主题消失（仓位改名/删除/通道移除）。

        安全保护：
        - last_seen <= 0 的键（初始配置预填充、从未在主题中出现过）**不删**，
          避免 rtsp 未启动/首帧未到时清空配置仓位；
        - 返回删除的 bay_id，供调用方同步清理关联状态（如防抖滤波器）。
        """
        with self._lock:
            now = time.time()
            stale = [bay_id for bay_id, entry in self._bays.items()
                     if entry.last_seen > 0 and now - entry.last_seen > timeout]
            for bay_id in stale:
                del self._bays[bay_id]
            if stale and self._logger:
                self._logger.info(
                    f"BayCache 修剪过期仓位 {len(stale)} 个: {', '.join(sorted(stale))}"
                )
            return stale

    def get_active_bay_ids(self) -> set:
        """当前缓存中的全部 bay_id 集合（供调用方清理关联状态）"""
        with self._lock:
            return set(self._bays.keys())
