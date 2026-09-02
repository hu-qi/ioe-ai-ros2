#!/usr/bin/env python3
"""
status_poller_plugin — 状态轮询同步插件

职责：
  - 定时轮询 RCS 获取叉车实时状态（3s 间隔）
  - 定时轮询 RCS 获取终点仓位状态（60s 间隔）
  - 维护 RobotCache 和 DestBayCache 内存缓存
  - 启动时执行一次全量加载
  - 补偿回调丢失

依赖：
  - rcs_adapter (Phase 1)
  - RobotCache, DestBayCache (task_cache 组件包)
"""

from typing import Dict, Any, List, Optional
import time
from .base_plugin import BasePlugin
from app_mgr_object.components.task_cache.robot_cache import RobotCache
from app_mgr_object.components.task_cache.dest_bay_cache import DestBayCache

from app_mgr_object.components.trigger.hot_reload import HotReloadRegistry, validate_dict, validate_positive_number


class StatusPollerPlugin(BasePlugin):
    """状态轮询同步插件"""

    PLUGIN_NAME = "status_poller"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        self._robot_ids: List[int] = self.config.get('robot_ids', [1001, 1002])
        self._robot_poll_interval: float = self.config.get('robot_poll_interval', 3.0)
        self._dest_poll_interval: float = self.config.get('dest_poll_interval', 10.0)
        self._enabled = self.config.get('enabled', True)
        # RCS→内部状态映射（doc/52 §7.5）：可热加载
        self._status_mapping: Dict[str, str] = dict(self.config.get('agv_status_mapping') or {
            'IDLE': 'AVAILABLE',
            'AVAILABLE': 'AVAILABLE',
            'BUSY': 'BUSY',
            'OFFLINE': 'OFFLINE',
            'ERROR': 'ERROR',
        })

        self.robot_cache: RobotCache = None
        self.dest_cache: DestBayCache = None

        self._robot_timer = None
        self._dest_timer = None
        self._initial_poll_done = False
        self._last_robot_poll: float = 0.0
        self._last_dest_poll: float = 0.0
        self._robot_poll_errors: int = 0
        self._dest_poll_errors: int = 0

    def _configure_impl(self) -> bool:
        self.robot_cache = RobotCache(robot_ids=self._robot_ids, logger=self.logger)
        dest_configs = self.config.get('dest_bay_configs', None)
        self.dest_cache = DestBayCache(bay_configs=dest_configs, logger=self.logger)
        # 启动注入配对策略（doc/52 阶段1，R-01）：pairing_policy 直接进入目的仓缓存
        if self.config.get('pairing_policy'):
            self.dest_cache.set_pairing_policy(self.config.get('pairing_policy'))
        lanes = len((self.config.get('pairing_policy') or {}).get('lanes') or [])
        self.logger.info(
            f"StatusPoller 配置完成: robots={self._robot_ids}, "
            f"robot_interval={self._robot_poll_interval}s, "
            f"dest_interval={self._dest_poll_interval}s, "
            f"pairing_policy 巷道={lanes} 条, agv_status_mapping={len(self._status_mapping)} 项"
        )
        return True

    def _activate_impl(self) -> bool:
        if not self._enabled:
            self.logger.info("StatusPoller 已禁用")
            return True
        self._robot_timer = self.node.create_timer(self._robot_poll_interval, self._poll_robot_status)
        self._dest_timer = self.node.create_timer(self._dest_poll_interval, self._poll_dest_bays)
        
        self._init_timer = self.node.create_timer(0.5, self._initial_full_poll)
        # YAML 配置化热加载（doc/52 §7.2）：轮询间隔/状态映射/配对策略
        
        self._hot_reload = HotReloadRegistry(logger=self.logger)
        self._register_hot_reload()
        self.event_bus.subscribe('plugin_configs.updated', self._on_config_updated)
        self.logger.info(f"StatusPoller 激活完成")
        return True

    def _deactivate_impl(self) -> bool:
        for timer in [self._robot_timer, self._dest_timer]:
            if timer:
                self.node.destroy_timer(timer)
        self._robot_timer = None
        self._dest_timer = None
        if self.event_bus:
            self.event_bus.unsubscribe('plugin_configs.updated', self._on_config_updated)
        return True

    def _cleanup_impl(self) -> bool:
        self.robot_cache = None
        self.dest_cache = None
        return True

    def _initial_full_poll(self):
        if hasattr(self, '_init_timer') and self._init_timer:
            self._init_timer.cancel()
            self._init_timer = None
        self.logger.info("执行初始全量加载...")
        self._poll_robot_status()
        self._poll_dest_bays()
        self._initial_poll_done = True
        self.logger.info("初始全量加载完成")

    def _poll_robot_status(self):
        try:
            adapter = self._get_rcs_adapter()
            resp = adapter.query_agv_status(self._robot_ids)
            if resp.get('code') != '0':
                self._robot_poll_errors += 1
                self.logger.warning(f"叉车状态轮询失败: {resp.get('msg')}")
                return

            # 状态映射：RCS 状态 → 内部状态（agv_status_mapping 可配置，doc/52 §7.5）
            status_mapping = self._status_mapping or {
                'IDLE': 'AVAILABLE',       # 空闲 -> 可调度
                'AVAILABLE': 'AVAILABLE',
                'BUSY': 'BUSY',
                'OFFLINE': 'OFFLINE',
                'ERROR': 'ERROR',
            }

            for item in resp.get('data', []):
                robot_id = item.get('robotID')
                raw_status = item.get('agvStatus', 'OFFLINE')
                status = status_mapping.get(raw_status, 'OFFLINE')
                self.robot_cache.update_status(
                    robot_id=int(robot_id) if robot_id else 0,
                    status=status,
                    battery=int(item.get('battery')) if item.get('battery') else None,
                    position_code=item.get('positionCode'),
                    source='polling',
                )
            self._last_robot_poll = self.node.get_clock().now().nanoseconds / 1e9
            self._robot_poll_errors = 0
        except Exception as e:
            self._robot_poll_errors += 1
            self.logger.warning(f"叉车状态轮询异常: {e}")
            
    def refresh_dest_bays(self):
        """立即刷新终点仓位状态（重置定时器）"""
        if not self._enabled or not self.dest_cache:
            return
        # 取消当前定时器
        if self._dest_timer:
            self.node.destroy_timer(self._dest_timer)
            self._dest_timer = None
        # 执行轮询
        self._poll_dest_bays()
        # 重新创建定时器
        self._dest_timer = self.node.create_timer(self._dest_poll_interval, self._poll_dest_bays)

    # ════════════════════════════════════════════════════
    #  YAML 配置化热加载（doc/52 §7.2）
    # ════════════════════════════════════════════════════

    def _register_hot_reload(self):
        """注册 status_poller 各配置段的热加载处理器。"""
        r = self._hot_reload
        r.register('status_poller', 'robot_poll_interval',
                   validate_positive_number, self._apply_robot_poll_interval)
        r.register('status_poller', 'dest_poll_interval',
                   validate_positive_number, self._apply_dest_poll_interval)
        r.register('status_poller', 'agv_status_mapping',
                   validate_dict, self._apply_status_mapping)
        r.register('status_poller', 'pairing_policy',
                   validate_dict, self._apply_pairing_policy)

    def _on_config_updated(self, data: dict):
        """plugin_configs.updated 事件 → 热加载注册表应用（doc/52 §7.2）"""
        plugin_name = (data or {}).get('plugin_name', '')
        if plugin_name != 'status_poller':
            return
        cfg = (data or {}).get('config') or {}
        result = self._hot_reload.apply('status_poller', cfg)
        if result['applied']:
            self.logger.info(f"状态轮询配置热加载: {result['applied']}")
        if result['rejected']:
            self.logger.warning(f"状态轮询配置热加载拒绝: {result['rejected']}")

    def _apply_robot_poll_interval(self, value):
        self._robot_poll_interval = float(value)
        self._rebuild_robot_timer()

    def _apply_dest_poll_interval(self, value):
        self._dest_poll_interval = float(value)
        self._rebuild_dest_timer()

    def _apply_status_mapping(self, value):
        self._status_mapping = dict(value or {})

    def _apply_pairing_policy(self, value):
        if self.dest_cache is not None:
            self.dest_cache.set_pairing_policy(value or {})

    def _rebuild_robot_timer(self):
        """热更新 AGV 轮询定时器（销毁旧定时器，按新间隔重建）"""
        if self._robot_timer:
            self.node.destroy_timer(self._robot_timer)
            self._robot_timer = None
        self._robot_timer = self.node.create_timer(
            self._robot_poll_interval, self._poll_robot_status)

    def _rebuild_dest_timer(self):
        """热更新目的仓轮询定时器（销毁旧定时器，按新间隔重建）"""
        if self._dest_timer:
            self.node.destroy_timer(self._dest_timer)
            self._dest_timer = None
        self._dest_timer = self.node.create_timer(
            self._dest_poll_interval, self._poll_dest_bays)

    def _poll_dest_bays(self):
        all_codes = self.dest_cache.get_all_bay_ids()
        if not all_codes:
            self.logger.debug("终点仓位列表为空，跳过轮询")
            return
        try:
            adapter = self._get_rcs_adapter()
            resp = adapter.query_pod_berth_and_mat(all_codes)
            if resp.get('code') != '0':
                self._dest_poll_errors += 1
                self.logger.warning(f"终点仓位轮询失败: {resp.get('msg')}")
                return

            data_list = resp.get('data', [])
            if not data_list:
                self.logger.warning("RCS 返回空终点仓位数据")
                return

            # 分组存储：按楼层前缀分组，记录每个仓位及其空/占用状态
            grouped_status = {}
            for item in data_list:
                stg_code = item.get('stgBinCode')
                ctnr_code = item.get('ctnrCode')
                is_empty = (not ctnr_code)
                self.dest_cache.update(stg_code, is_empty=is_empty, source='polling')
                floor_key = stg_code[:2] if stg_code.startswith('T') else stg_code
                grouped_status.setdefault(floor_key, []).append((stg_code, is_empty))

            self._last_dest_poll = time.time()
            self._dest_poll_errors = 0

            # 构建日志（多行显示，与初始仓位格式一致）
            self.logger.info(f"[终点仓位查询] 共 {len(data_list)} 个终点")
            for floor in sorted(grouped_status.keys()):
                statuses = [f"{bay}:{'空' if is_empty else '有货'}" for bay, is_empty in grouped_status[floor]]
                self.logger.info(f"  {floor}: {', '.join(statuses)}")

        except Exception as e:
            self._dest_poll_errors += 1
            self.logger.warning(f"终点仓位轮询异常: {e}")

    def _get_rcs_adapter(self):
        adapter = getattr(self.node, 'rcs_adapter', None)
        if adapter is None:
            adapter = self.node.plugin_manager.get_plugin('rcs_adapter')
        if adapter is None:
            raise RuntimeError("RCS 适配器未加载")
        return adapter

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            'robot_count': self.robot_cache.get_robot_count() if self.robot_cache else 0,
            'dest_bay_count': len(self.dest_cache.get_all_bay_ids()) if self.dest_cache else 0,
            'idle_robot': self.robot_cache.get_idle_robot() if self.robot_cache else None,
            'last_robot_poll': self._last_robot_poll,
            'last_dest_poll': self._last_dest_poll,
            'robot_poll_errors': self._robot_poll_errors,
            'dest_poll_errors': self._dest_poll_errors,
            'initial_poll_done': self._initial_poll_done,
        })
        return base

    def get_robot_status(self, robot_id: int) -> Optional[dict]:
        return self.robot_cache.get_robot_status(robot_id) if self.robot_cache else None

    def get_all_robot_status(self) -> Dict[int, dict]:
        return self.robot_cache.get_all_robot_status() if self.robot_cache else {}

    def get_dest_bay_status(self, bay_id: str) -> Optional[dict]:
        return self.dest_cache.get_bay_status(bay_id) if self.dest_cache else None

