"""
pairing_policy - 巷道配对策略骨架

提供：
- Lane: 巷道对象(id/floor/strategy/bay_ids)
- StrategyPolicy: 策略枚举(any/fifo/filo/lifo/nearest)，含 parse / select_slot
- select_slot: 按策略从候选索引列表中选一个

骨架实现，使节点能成功启动；具体策略语义可后续补全。
"""
from typing import List, Optional


class StrategyPolicy:
    """配对策略（简化版枚举，便于热加载解析字符串）。"""
    ANY = 'any'
    FIFO = 'fifo'
    FILO = 'filo'
    LIFO = 'lifo'
    NEAREST = 'nearest'

    _VALID = {ANY, FIFO, FILO, LIFO, NEAREST}

    def __init__(self, value: str = ANY):
        self.value = value if value in self._VALID else self.ANY

    @classmethod
    def parse(cls, value: Optional[str]) -> 'StrategyPolicy':
        """从字符串解析策略，无法识别时回退 any。"""
        if not value:
            return cls(cls.ANY)
        return cls(str(value).strip().lower())

    def __repr__(self):
        return f"StrategyPolicy({self.value!r})"


class Lane:
    """巷道对象。"""

    def __init__(self, lane_id: str, floor: int = 0,
                 strategy: Optional[StrategyPolicy] = None,
                 bay_ids: Optional[List[str]] = None):
        self.lane_id = lane_id
        self.id = lane_id  # 兼容别名
        self.floor = floor
        self.strategy = strategy if strategy is not None else StrategyPolicy()
        self.bay_ids = list(bay_ids) if bay_ids else []

    def __repr__(self):
        return (f"Lane(id={self.lane_id!r}, floor={self.floor}, "
                f"strategy={self.strategy.value!r}, bays={len(self.bay_ids)})")


def select_slot(strategy: StrategyPolicy, empty_indices: List[int]) -> Optional[int]:
    """按策略从空位索引列表中选择一个槽位索引。

    骨架实现：
    - any / fifo / nearest: 取第一个（索引最小）
    - filo / lifo: 取最后一个（索引最大）
    - 空列表返回 None
    """
    if not empty_indices:
        return None
    s = strategy.value if isinstance(strategy, StrategyPolicy) else str(strategy)
    if s in (StrategyPolicy.FILO, StrategyPolicy.LIFO):
        return empty_indices[-1]
    # any / fifo / nearest 默认取第一个
    return empty_indices[0]
