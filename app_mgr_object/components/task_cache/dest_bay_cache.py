#!/usr/bin/env python3
"""
终点仓位状态缓存 — 维护终点仓位（T2001~T4006）的实时状态

数据结构（内存）:
    _bays: {
        "T2001": {
            "bay_id":      "T2001",
            "cargo_type":  1,
            "floor_no":    2,
            "is_empty":    True,       # True=空（可接受任务）
            "update_time": 1723456789.0,
            "source":      "rcs_callback",
        },
        ...
    }
"""

import time
import threading
from typing import Dict, List, Optional
from ..trigger.pairing_policy import Lane, StrategyPolicy, select_slot


class DestBayCacheEntry:
    """终点仓位状态条目"""
    __slots__ = ('bay_id', 'cargo_type', 'floor_no', 'lane',
                 'is_empty', 'update_time', 'source', 'revision')

    def __init__(self, bay_id: str, cargo_type: int, floor_no: int = 0,
                 lane: str = ''):
        self.bay_id = bay_id
        self.cargo_type = cargo_type
        self.floor_no = floor_no
        self.lane = lane or ''            # 所属巷道（doc/放置策略弹窗增强 §3.2，可选）
        self.is_empty = True
        self.update_time = 0.0
        self.source = 'init'
        self.revision = 0

    def to_dict(self) -> dict:
        return {
            'bay_id': self.bay_id,
            'cargo_type': self.cargo_type,
            'floor_no': self.floor_no,
            'lane': self.lane,
            'is_empty': self.is_empty,
            'update_time': self.update_time,
            'source': self.source,
            'revision': self.revision,
        }


class DestBayCache:
    """终点仓位状态缓存"""

    def __init__(self, bay_configs: Dict[str, dict] = None, logger=None):
        """
        Args:
            bay_configs: {bay_id: {cargo_type: int, floor: int}}
            logger: 日志记录器
        """
        self._lock = threading.RLock()
        self._logger = logger
        self._bays: Dict[str, DestBayCacheEntry] = {}
        # 配对策略（doc/目的仓位巷道FIFO策略）
        self._policy: Optional[dict] = None
        self._lanes: Dict[str, Lane] = {}       # lane_id -> Lane
        self._bay_lane: Dict[str, tuple] = {}   # bay_id -> (lane_id, slot_index)
        # 匹对稳定：目的仓保留占用（doc/触发机制审查 §3.2/3.6）
        self._reserved: Dict[str, str] = {}     # bay_id -> 占用来源 queued/matched/dispatched
        # 状态颜色（doc/触发机制 §九）：因始发解绑移出而释放的标记（蓝色）
        self._unbind_released: Dict[str, float] = {}   # bay_id -> 释放时间戳
        self._lane_state_management = False     # 巷道状态实时管理开关（最大占用匹对）

        if bay_configs:
            for bay_id, cfg in bay_configs.items():
                self._bays[bay_id] = DestBayCacheEntry(
                    bay_id,
                    cfg.get('cargo_type', 0),
                    cfg.get('floor', 0),
                    cfg.get('lane', '')
                )

    # ── 写入接口 ──

    def update(self, bay_id: str, is_empty: bool, source: str = 'polling'):
        """更新终点仓位状态。

        reserved（queued/matched/dispatched）中的仓位：轮询等外部状态
        不得将其置回空（doc/触发机制审查 §3.2 锁定稳定）。
        """
        with self._lock:
            entry = self._bays.get(bay_id)
            if not entry:
                return
            if is_empty and bay_id in self._reserved:
                return  # 保留占用，忽略置空
            entry.is_empty = is_empty
            entry.update_time = time.time()
            entry.source = source
            entry.revision += 1
    # ── 查询接口 ──

    def get_empty_bays_of_type(self, cargo_type: int) -> List[str]:
        """获取指定类型的空终点仓位列表"""
        with self._lock:
            return [e.bay_id for e in self._bays.values()
                    if e.cargo_type == cargo_type and e.is_empty]

    def get_any_empty_bay(self, cargo_type: int) -> Optional[str]:
        """获取指定类型下任一空仓位"""
        bays = self.get_empty_bays_of_type(cargo_type)
        return bays[0] if bays else None

    def get_bay_status(self, bay_id: str) -> Optional[dict]:
        """获取单个仓位状态"""
        with self._lock:
            entry = self._bays.get(bay_id)
            return entry.to_dict() if entry else None

    def get_all_bay_status(self) -> Dict[str, dict]:
        """获取所有终点仓位状态"""
        with self._lock:
            return {e.bay_id: e.to_dict() for e in self._bays.values()}

    def get_all_bay_ids(self) -> List[str]:
        """获取所有终点仓位编号"""
        return list(self._bays.keys())

    def has_empty_bay_of_type(self, cargo_type: int) -> bool:
        """指定类型是否有空仓位"""
        return len(self.get_empty_bays_of_type(cargo_type)) > 0

    # ── 配置热加载 ──

    def reload_config(self, bay_configs: Dict[str, dict]):
        """热加载配置"""
        with self._lock:
            for bay_id, cfg in bay_configs.items():
                if bay_id in self._bays:
                    self._bays[bay_id].cargo_type = cfg.get('cargo_type', 0)
                    self._bays[bay_id].floor_no = cfg.get('floor', 0)
                    self._bays[bay_id].lane = cfg.get('lane', '')
                else:
                    self._bays[bay_id] = DestBayCacheEntry(
                        bay_id,
                        cfg.get('cargo_type', 0),
                        cfg.get('floor', 0),
                        cfg.get('lane', '')
                    )
        # 仓位集变化后重建巷道索引
        self._rebuild_lanes()

    # ── 配对策略（doc/目的仓位巷道FIFO策略）──

    def set_pairing_policy(self, policy: Optional[dict]):
        """热加载巷道/放置策略配置（pairing_policy 段）。

        解析 lanes/type_rules/bay_rules/default_strategy 并重建巷道索引；
        无效巷道（无 id / 仓位不存在 / 跨巷道重复）跳过并告警。
        """
        with self._lock:
            self._policy = policy or {}
            self._lanes = {}
            self._bay_lane = {}
            # 巷道状态实时管理开关（doc/触发机制审查 §3.6）：最大占用匹对
            self._lane_state_management = bool(
                self._policy.get('lane_state_management', False))
            default = StrategyPolicy.parse(self._policy.get('default_strategy', 'any'))
            lanes_cfg = self._policy.get('lanes') or []
            for lane_cfg in lanes_cfg or []:
                if not isinstance(lane_cfg, dict):
                    continue
                lid = lane_cfg.get('id')
                if not lid or lid in self._lanes:
                    if self._logger:
                        self._logger.warning(f"配对策略: 巷道ID无效或重复: {lane_cfg}")
                    continue
                bays = lane_cfg.get('bays')
                if bays is None:
                    # bays 缺省：按 dest_bay_configs.lane 分组派生（编号升序=巷道顺序）
                    bays = sorted(
                        b for b, e in self._bays.items()
                        if e.lane == lid)
                    if self._logger:
                        self._logger.debug(
                            f"配对策略: 巷道 {lid} 按仓位 lane 字段派生 {len(bays)} 个仓位")
                valid_bays = []
                conflict = False
                for b in bays:
                    if b in self._bay_lane:
                        if self._logger:
                            self._logger.warning(f"配对策略: 巷道 {lid} 仓位 {b} 已在其他巷道，整巷跳过")
                        conflict = True
                        break
                    if b not in self._bays:
                        if self._logger:
                            self._logger.warning(f"配对策略: 巷道 {lid} 仓位 {b} 不在目的仓位配置中，跳过")
                        continue
                    valid_bays.append(b)
                if conflict or not valid_bays:
                    if self._logger:
                        self._logger.warning(f"配对策略: 巷道 {lid} 无有效仓位，忽略")
                    continue
                strategy = (StrategyPolicy.parse(lane_cfg.get('strategy'))
                            if lane_cfg.get('strategy') else default)
                self._lanes[lid] = Lane(lid, lane_cfg.get('floor', 0), strategy, valid_bays)
                for i, b in enumerate(valid_bays):
                    self._bay_lane[b] = (lid, i)
            if self._logger:
                self._logger.info(
                    f"配对策略热加载: {len(self._lanes)} 条巷道, default={default.value}")

    def _rebuild_lanes(self):
        """仓位配置热加载后重建巷道索引（保持引用同步）"""
        if self._policy:
            self.set_pairing_policy(self._policy)

    def _resolve_rule(self, src_bay: Optional[str], cargo_type: int):
        """三级规则回退：bay_rules(L1) > type_rules(L2) > 类型匹配巷道+default(L3)"""
        policy = self._policy or {}
        default = StrategyPolicy.parse(policy.get('default_strategy', 'any'))
        bay_rules = policy.get('bay_rules') or {}
        type_rules = policy.get('type_rules') or {}
        # L1: 始发仓位精确规则
        if src_bay:
            br = bay_rules.get(src_bay)
            if br:
                lanes = br.get('lanes') or []
                strat = (StrategyPolicy.parse(br.get('strategy'))
                         if br.get('strategy') else default)
                if lanes:
                    return lanes, strat
        # L2: 类型规则
        tr = type_rules.get(str(cargo_type))
        if tr is None:
            tr = type_rules.get(cargo_type)
        if tr:
            lanes = tr.get('lanes') or []
            strat = (StrategyPolicy.parse(tr.get('strategy'))
                     if tr.get('strategy') else default)
            if lanes:
                return lanes, strat
        # L3: 该类型匹配的巷道（按 id 排序）+ 默认策略
        matched = sorted(
            lid for lid, lane in self._lanes.items()
            if any(b in self._bays and self._bays[b].cargo_type == cargo_type
                   for b in lane.bay_ids))
        return matched, default

    def mark_occupied(self, bay_id: str, source: str = 'matched'):
        """标记目的仓占用（匹对稳定，doc/触发机制审查 §3.2/3.6）。

        source: matched（匹对中）/ queued（入队）/ dispatched（派发）。
        占用后 RCS 轮询不得置回空（update 尊重 reserved）；
        重新匹对时清除「解绑释放」标记（颜色橙，doc/触发机制 §九）。
        """
        with self._lock:
            if bay_id in self._bays:
                self._bays[bay_id].is_empty = False
                self._bays[bay_id].source = source
                self._bays[bay_id].update_time = time.time()
            self._reserved[bay_id] = source
            self._unbind_released.pop(bay_id, None)

    def release_occupied(self, bay_id: str, set_empty: bool = True,
                          source: str = ''):
        """释放目的仓保留占用。

        set_empty=True：任务失败/取消/老化/移除 → 置回空（可再匹配）；
        set_empty=False：任务完成（货物已到位）→ 保留 is_empty=False，仅清保留，
        由 RCS 轮询接管真实占用。
        source='unbind'：因始发仓解绑移出队列而释放 → 记录「解绑释放」标记
        （前端显示蓝色，doc/触发机制 §九）；其他来源清除该标记。
        """
        with self._lock:
            self._reserved.pop(bay_id, None)
            if source == 'unbind':
                self._unbind_released[bay_id] = time.time()
            elif source != 'unbind':
                self._unbind_released.pop(bay_id, None)
            if set_empty and bay_id in self._bays:
                self._bays[bay_id].is_empty = True
                self._bays[bay_id].source = 'released'
                self._bays[bay_id].update_time = time.time()

    def is_reserved(self, bay_id: str) -> bool:
        with self._lock:
            return bay_id in self._reserved

    def get_reserved_count(self) -> int:
        """已保留占用（queued/matched/dispatched）的目的仓数量（doc/触发机制 §8.2）"""
        with self._lock:
            return len(self._reserved)

    def get_bay_state(self, bay_id: str) -> str:
        """目的仓状态（前端四色，doc/触发机制 §九）。

        优先级：reserved（已匹对锁定·橙）> unbind（解绑释放·蓝）
              > occupied（有货占用·灰黑）> empty（空·绿）。
        """
        with self._lock:
            if bay_id in self._reserved:
                return 'reserved'
            if bay_id in self._unbind_released:
                return 'unbind'
            entry = self._bays.get(bay_id)
            if entry and not entry.is_empty:
                return 'occupied'
            return 'empty'

    def _max_occupied_next_slot(self, lane: Lane) -> Optional[int]:
        """巷道最大占用模型：找最大占用索引 → 候选 = 紧邻其后的空位（n+1）。

        中间空洞不影响匹配（doc/触发机制审查 §3.1/3.6）：只看最大占用仓位。
        **真实占用判定**：reserved（匹对中/入队/派发，货物尚未放入巷道）不视为
        巷道占用——其前方解绑释放的空仓（unbind，蓝）可再次匹对（AGV 可达，
        doc/触发机制实施后复审 §8.3 修复）。
        """
        max_occ = -1
        for i, b in enumerate(lane.bay_ids):
            if (b in self._bays and not self._bays[b].is_empty
                    and b not in self._reserved):
                max_occ = i
        # 候选：从 max_occ+1 向后扫描第一个「真实空位」——跳过 reserved/已占仓
        # （同批逐次匹对时前一个候选已 mark_occupied，需继续向后找下一个空位）
        for nxt in range(max_occ + 1, len(lane.bay_ids)):
            b = lane.bay_ids[nxt]
            if b in self._bays and self._bays[b].is_empty:
                return nxt
        return None

    def select_by_strategy(self, cargo_type: int,
                           src_bay: Optional[str] = None,
                           exclude: Optional[set] = None) -> Optional[str]:
        """按配对策略选择目的仓位；None = 巷道满/不可达（不降级任意空位）。

        exclude: 本批已配对的仓位集合（视为占用，避免同巷道重复选同一空位）。
        lane_state_management 启用时：每巷道按「最大占用 + 1」取候选（§3.1/3.6）；
        未启用：回退 any（字典序最小空位）；未配置巷道时同 any。
        """
        exclude = exclude or set()
        with self._lock:
            if not self._lanes:
                empties = [b for b in self.get_empty_bays_of_type(cargo_type)
                           if b not in exclude]
                return sorted(empties)[0] if empties else None
            lane_ids, strategy = self._resolve_rule(src_bay, cargo_type)
            for lid in lane_ids:
                lane = self._lanes.get(lid)
                if not lane:
                    continue
                if self._lane_state_management:
                    idx = self._max_occupied_next_slot(lane)
                    if idx is not None and lane.bay_ids[idx] not in exclude:
                        return lane.bay_ids[idx]
                    continue
                # 未启用开关：旧行为（任意空位 + 策略选择）
                empty = [i for i, b in enumerate(lane.bay_ids)
                         if b in self._bays and self._bays[b].is_empty
                         and b not in exclude]
                idx = select_slot(strategy, empty)
                if idx is not None:
                    return lane.bay_ids[idx]
            return None

    def get_lane_summary(self) -> List[dict]:
        """巷道摘要（前端策略查看）：id/floor/strategy/bays/占用统计"""
        with self._lock:
            result = []
            for lid in sorted(self._lanes.keys()):
                lane = self._lanes[lid]
                occupied = sum(1 for b in lane.bay_ids
                               if b in self._bays and not self._bays[b].is_empty)
                result.append({
                    'id': lid,
                    'floor': lane.floor,
                    'strategy': lane.strategy.value,
                    'bays': list(lane.bay_ids),
                    'occupied': occupied,
                    'total': len(lane.bay_ids),
                })
            return result

    def get_lane_id_of(self, bay_id: str) -> Optional[str]:
        """仓位所属巷道 id（配对结果展示用）"""
        with self._lock:
            entry = self._bay_lane.get(bay_id)
            return entry[0] if entry else None

    def get_strategy_of(self, bay_id: str) -> Optional[str]:
        """仓位所在巷道的放置策略（配对结果展示用）"""
        with self._lock:
            entry = self._bay_lane.get(bay_id)
            if entry:
                lane = self._lanes.get(entry[0])
                return lane.strategy.value if lane else None
            return None

