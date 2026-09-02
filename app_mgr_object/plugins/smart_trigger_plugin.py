#!/usr/bin/env python3
"""
smart_trigger_plugin — 智能触发器插件

基于配置（config/plugin_configs/smart_trigger.yaml）执行触发匹配：
  - 周期扫描起始仓位状态（scan_interval）
  - 按货物优先级（cargo_priority）和扫描顺序（src_scan_order）排序候选
  - 检查工作时间（work_schedule）：development 模式任意放行，deployment 模式按工作时间
  - 检查全局任务数上限（max_total_tasks）和每轮派发上限（dispatch_per_round）
  - AGV 选择策略（round_robin / least_busy / specified）
  - 匹配目的仓位 → 派发任务到工作流引擎

依赖：
  - BayCache（task_cache 组件包）— 起始仓位状态
  - DestBayCache（task_cache 组件包）— 目的仓位配对
  - workflow_engine_plugin — 创建工作流实例
"""
import time
import threading
import datetime
from typing import Dict, Any, Optional, List, Callable
from collections import deque

from .base_plugin import BasePlugin


class SmartTriggerPlugin(BasePlugin):
    """智能触发器插件。"""

    PLUGIN_NAME = "smart_trigger"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        # 配置项
        self._operation_mode: str = "development"
        self._scan_interval: float = 2.0
        self._cargo_priority: List[int] = [1, 2, 3, 4, 5, 6]
        self._max_tasks_per_scan: int = 4
        self._max_total_tasks: int = 3
        self._max_queue_size: int = 50
        self._aging_ttl: float = 300.0
        self._dispatch_per_round: int = 3
        self._src_scan_order: Dict[str, Any] = {"mode": "by_bay_id_asc"}
        self._agv_config: Dict[str, Any] = {
            "select_strategy": "round_robin",
            "specified_ids": [],
            "available_statuses": ["AVAILABLE"],
        }
        self._bind_config: Dict[str, Any] = {
            "retry_enabled": False,
            "retry_count": 3,
            "retry_delay": 5.0,
        }
        self._work_schedule: Dict[str, Any] = {"enabled": True, "holidays": [], "schedules": []}

        # 运行时状态
        self._trigger_queue: deque = deque()
        self._dispatched_count: int = 0
        self._scan_count: int = 0
        self._last_scan_ts: float = 0.0
        self._lock = threading.Lock()

        # 依赖注入（activate 时解析）
        self._bay_cache = None
        self._dest_bay_cache = None
        self._workflow_engine = None
        self._rcs_adapter = None

        # 扫描线程
        self._scan_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

        # AGV 轮询状态
        self._agv_round_robin_idx = 0

    # ════════════════════════════════════════════════════
    #  生命周期
    # ════════════════════════════════════════════════════

    def _configure_impl(self) -> bool:
        cfg = self.config or {}
        self._operation_mode = str(cfg.get("operation_mode", "development"))
        self._scan_interval = float(cfg.get("scan_interval", 2.0))
        self._cargo_priority = list(cfg.get("cargo_priority", [1, 2, 3, 4, 5, 6]))
        self._max_tasks_per_scan = int(cfg.get("max_tasks_per_scan", 4))
        self._max_total_tasks = int(cfg.get("max_total_tasks", 3))
        self._max_queue_size = int(cfg.get("max_queue_size", 50))
        self._aging_ttl = float(cfg.get("aging_ttl", 300.0))
        self._dispatch_per_round = int(cfg.get("dispatch_per_round", 3))
        self._src_scan_order = cfg.get("src_scan_order", {"mode": "by_bay_id_asc"})
        self._agv_config = cfg.get("agv", self._agv_config)
        self._bind_config = cfg.get("bind", self._bind_config)
        self._work_schedule = cfg.get("work_schedule", self._work_schedule)
        self.logger.info(
            f"smart_trigger 配置完成: mode={self._operation_mode}, "
            f"scan={self._scan_interval}s, priorities={self._cargo_priority}, "
            f"max_total={self._max_total_tasks}")
        return True

    def _activate_impl(self) -> bool:
        # 解析依赖插件
        self._resolve_dependencies()

        # 启动扫描线程
        self._stop_flag.clear()
        self._scan_thread = threading.Thread(
            target=self._scan_loop, daemon=True)
        self._scan_thread.start()
        self.logger.info("smart_trigger 激活: 扫描线程已启动")
        return True

    def _deactivate_impl(self) -> bool:
        self._stop_flag.set()
        if self._scan_thread:
            self._scan_thread.join(timeout=3)
        with self._lock:
            self._trigger_queue.clear()
        self.logger.info("smart_trigger 停用")
        return True

    def _cleanup_impl(self) -> bool:
        with self._lock:
            self._trigger_queue.clear()
        return True

    def _resolve_dependencies(self) -> None:
        pm = getattr(self.node, "plugin_manager", None)
        if pm:
            self._workflow_engine = pm.get_plugin("workflow_engine")
            self._rcs_adapter = pm.get_plugin("rcs_adapter")
        # BayCache / DestBayCache 通过 node 或插件获取
        bay_fusion = pm.get_plugin("bay_status_fusion") if pm else None
        if bay_fusion and hasattr(bay_fusion, "cache"):
            self._bay_cache = bay_fusion.cache

    # ════════════════════════════════════════════════════
    #  扫描循环
    # ════════════════════════════════════════════════════

    def _scan_loop(self) -> None:
        """周期扫描起始仓位，匹配并派发任务。"""
        while not self._stop_flag.is_set():
            try:
                self._scan_once()
            except Exception as ex:
                self.logger.error(f"smart_trigger 扫描异常: {ex}")
            self._stop_flag.wait(self._scan_interval)

    def _scan_once(self) -> None:
        """单次扫描：检查前置条件 → 收集候选 → 排序 → 派发。"""
        self._scan_count += 1
        self._last_scan_ts = time.time()

        # 1. 工作时间检查（deployment 模式）
        if self._operation_mode == "deployment":
            if not self._is_within_work_schedule():
                return

        # 2. 全局任务数上限检查
        active_tasks = self._count_active_tasks()
        if active_tasks >= self._max_total_tasks:
            self.logger.debug(
                f"smart_trigger 跳过扫描: 活跃任务 {active_tasks} >= 上限 {self._max_total_tasks}")
            return

        # 3. 收集候选仓位（有货且未锁定）
        candidates = self._collect_candidates()
        if not candidates:
            return

        # 4. 排序：货物优先级 → 扫描顺序
        candidates.sort(key=lambda c: (
            self._cargo_priority_index(c.get("cargo_type", 0)),
            c.get("bay_id", ""),
        ))

        # 5. 限制每轮扫描候选数
        candidates = candidates[:self._max_tasks_per_scan]

        # 6. 派发
        dispatched = 0
        for cand in candidates:
            if dispatched >= self._dispatch_per_round:
                break
            if self._count_active_tasks() >= self._max_total_tasks:
                break
            if self._dispatch_task(cand):
                dispatched += 1

        if dispatched > 0:
            self.logger.info(
                f"smart_trigger 扫描#{self._scan_count}: 派发 {dispatched} 个任务, "
                f"候选 {len(candidates)}, 活跃 {self._count_active_tasks()}")

    # ════════════════════════════════════════════════════
    #  候选收集与排序
    # ════════════════════════════════════════════════════

    def _collect_candidates(self) -> List[Dict[str, Any]]:
        """收集有货起始仓位作为候选。"""
        candidates: List[Dict[str, Any]] = []
        if self._bay_cache is None:
            return candidates

        try:
            # BayCache 应提供获取所有有货仓位的方法
            bays = []
            if hasattr(self._bay_cache, "get_cargo_bays"):
                bays = self._bay_cache.get_cargo_bays() or []
            elif hasattr(self._bay_cache, "get_all_bays"):
                bays = self._bay_cache.get_all_bays() or []

            for bay_info in bays:
                # bay_info 可能是 dict 或对象
                bay_id = self._get_field(bay_info, "bay_id") or self._get_field(bay_info, "id")
                has_cargo = self._get_field(bay_info, "has_cargo", True)
                cargo_type = self._get_field(bay_info, "cargo_type", 0)
                locked = self._get_field(bay_info, "locked", False)

                if not bay_id or locked or not has_cargo:
                    continue
                candidates.append({
                    "bay_id": bay_id,
                    "cargo_type": int(cargo_type) if cargo_type else 0,
                    "raw": bay_info,
                })
        except Exception as ex:
            self.logger.debug(f"smart_trigger 收集候选异常: {ex}")

        return candidates

    def _cargo_priority_index(self, cargo_type: int) -> int:
        """返回货物类型在优先级列表中的索引；不在列表则返回末尾。"""
        try:
            return self._cargo_priority.index(cargo_type)
        except ValueError:
            return len(self._cargo_priority)

    # ════════════════════════════════════════════════════
    #  任务派发
    # ════════════════════════════════════════════════════

    def _dispatch_task(self, candidate: Dict[str, Any]) -> bool:
        """匹配目的仓位并派发任务到工作流引擎。"""
        bay_id = candidate.get("bay_id", "")
        cargo_type = candidate.get("cargo_type", 0)

        # 1. 匹配目的仓位
        dest_bay = self._match_dest_bay(cargo_type, bay_id)
        if not dest_bay:
            self.logger.debug(
                f"smart_trigger: 仓位 {bay_id} (type={cargo_type}) 无匹配目的仓位")
            return False

        # 2. 选择 AGV
        agv_id = self._select_agv()
        if not agv_id:
            self.logger.debug(f"smart_trigger: 仓位 {bay_id} 无可用 AGV")
            return False

        # 3. 创建工作流实例
        ctx = {
            "src_bay": bay_id,
            "dest_bay": dest_bay,
            "cargo_type": cargo_type,
            "agv_id": agv_id,
            "dispatch_ts": time.time(),
        }

        if self._workflow_engine and hasattr(self._workflow_engine, "create_instance"):
            inst = self._workflow_engine.create_instance("agv_transport_atomic", ctx)
            if inst:
                with self._lock:
                    self._dispatched_count += 1
                self.logger.info(
                    f"smart_trigger 派发: {bay_id}→{dest_bay}, AGV={agv_id}, "
                    f"type={cargo_type}, wf_inst={inst.instance_id}")
                return True
            else:
                self.logger.warning(
                    f"smart_trigger: 工作流引擎创建实例失败 (仓位 {bay_id})")
                return False
        else:
            self.logger.debug("smart_trigger: 工作流引擎不可用，仅记录")
            with self._lock:
                self._dispatched_count += 1
                self._trigger_queue.append(ctx)
            return True

    def _match_dest_bay(self, cargo_type: int, src_bay: str) -> Optional[str]:
        """匹配目的仓位。优先用 DestBayCache，其次通用空位匹配。"""
        # 方式 1: DestBayCache.select_by_strategy
        if self._dest_bay_cache and hasattr(self._dest_bay_cache, "select_by_strategy"):
            try:
                return self._dest_bay_cache.select_by_strategy(
                    cargo_type, src_bay=src_bay)
            except Exception:
                pass

        # 方式 2: 通过 bay_fusion 的 cache 查找空位
        if self._bay_cache and hasattr(self._bay_cache, "get_empty_bays_of_type"):
            try:
                empties = self._bay_cache.get_empty_bays_of_type(cargo_type) or []
                if empties:
                    return sorted(empties)[0]
            except Exception:
                pass

        return None

    def _select_agv(self) -> Optional[int]:
        """按策略选择 AGV。"""
        strategy = self._agv_config.get("select_strategy", "round_robin")
        specified = self._agv_config.get("specified_ids", [])

        if strategy == "specified" and specified:
            return int(specified[0])

        # round_robin / least_busy: 简单轮询指定 ID 列表
        if specified:
            idx = self._agv_round_robin_idx % len(specified)
            self._agv_round_robin_idx += 1
            return int(specified[idx])

        # 无配置：返回 None（上层会跳过）
        return None

    # ════════════════════════════════════════════════════
    #  工作时间检查
    # ════════════════════════════════════════════════════

    def _is_within_work_schedule(self) -> bool:
        """检查当前时间是否在工作时间范围内。"""
        ws = self._work_schedule
        if not ws.get("enabled", True):
            return True  # 不启用工作时间限制 = 任意时间可调度

        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # 节假日检查
        holidays = ws.get("holidays", []) or []
        if today_str in holidays:
            return False

        # 检查每个 schedule
        schedules = ws.get("schedules", []) or []
        for sched in schedules:
            if not sched.get("enabled", True):
                continue
            if not self._match_day_of_week(now, sched.get("day_of_week", "")):
                continue
            start_time = sched.get("start_time", "00:00")
            end_time = sched.get("end_time", "23:59")
            if self._match_time_range(now, start_time, end_time):
                return True

        return False

    @staticmethod
    def _match_day_of_week(now: datetime.datetime, pattern: str) -> bool:
        """匹配星期几。pattern: 'mon-fri' / 'sat' / 'sun' / 'mon,wed,fri'。"""
        if not pattern:
            return True
        day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        now_dow = now.weekday()

        for part in pattern.split(","):
            part = part.strip().lower()
            if "-" in part:
                start, end = part.split("-", 1)
                s = day_map.get(start, -1)
                e = day_map.get(end, -1)
                if s <= now_dow <= e:
                    return True
            else:
                if day_map.get(part, -1) == now_dow:
                    return True
        return False

    @staticmethod
    def _match_time_range(now: datetime.datetime,
                          start_time: str, end_time: str) -> bool:
        """检查当前时间是否在 [start_time, end_time] 范围内。"""
        try:
            fmt = "%H:%M"
            start = datetime.datetime.strptime(start_time, fmt).time()
            end = datetime.datetime.strptime(end_time, fmt).time()
            now_t = now.time()
            return start <= now_t <= end
        except (ValueError, TypeError):
            return True  # 解析失败 = 不限制

    # ════════════════════════════════════════════════════
    #  辅助
    # ════════════════════════════════════════════════════

    def _count_active_tasks(self) -> int:
        """统计当前活跃任务数（队列中 + 工作流引擎中未完成的实例）。"""
        count = 0
        with self._lock:
            count += len(self._trigger_queue)
        if self._workflow_engine and hasattr(self._workflow_engine, "list_instances"):
            try:
                instances = self._workflow_engine.list_instances(include_finished=False)
                count += len(instances)
            except Exception:
                pass
        return count

    @staticmethod
    def _get_field(obj: Any, field: str, default: Any = None) -> Any:
        """从 dict 或对象获取字段。"""
        if isinstance(obj, dict):
            return obj.get(field, default)
        return getattr(obj, field, default)

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        with self._lock:
            queue_len = len(self._trigger_queue)
        base.update({
            "operation_mode": self._operation_mode,
            "scan_interval": self._scan_interval,
            "scan_count": self._scan_count,
            "dispatched_count": self._dispatched_count,
            "queue_length": queue_len,
            "active_tasks": self._count_active_tasks(),
            "last_scan_ts": self._last_scan_ts,
        })
        return base
