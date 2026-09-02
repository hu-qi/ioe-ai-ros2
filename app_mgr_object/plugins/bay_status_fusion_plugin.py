#!/usr/bin/env python3
"""
bay_status_fusion_plugin — 数据融合插件

职责：
  - 订阅 AI 检测 `/ai_bay_status` 话题（BayStatus 消息）
  - 遍历 BayStatus → BayChannelStatus[] → BayArea[] 层级结构
  - 使用 AreaStatusFilter 对每个仓位做防抖滤波
  - 稳定有货时触发 RCS 绑定 (bindCtnrAndBin)
  - 维护 BayCache 起始仓位状态
  - 通过 EventBus 发布 bay.status_changed / bay.bound 事件

依赖：
  - rcs_adapter (Phase 1)
  - AreaStatusFilter (复用已有组件)
  - BayCache (task_cache 组件包)
  - BayStatus / BayChannelStatus / BayArea (ROS2 自定义消息)
"""

from typing import Dict, Any, Optional
import threading

from .base_plugin import BasePlugin
from app_mgr_object.components.device_status.area_filter import AreaStatusFilter
from app_mgr_object.components.task_cache.bay_cache import BayCache

try:
    from cpp_ros2_interfaces.msg import BayStatus, BayChannelStatus, BayArea
    MSG_AVAILABLE = True
    print(f"[DEBUG] 成功导入 BayStatus 自定义消息")
except ImportError as e:
    print(f"[DEBUG] 导入 BayStatus 失败: {e}")
    MSG_AVAILABLE = False
    BayStatus = None
    BayChannelStatus = None
    BayArea = None


class BayStatusFusionPlugin(BasePlugin):
    """数据融合插件 — AI 层级信号 → 稳定业务事件 → RCS 绑定"""

    PLUGIN_NAME = "bay_status_fusion"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        # 解析配置
        self._stable_threshold = self.config.get('stable_threshold', 3)
        self._filter_timeout = self.config.get('filter_timeout', 2.0)
        self._bind_enabled = self.config.get('bind_enabled', True)
        self._ai_topic = self.config.get('ai_topic', '/ai_bay_status')
        # 主题活跃集修剪窗口：topic 全量周期发布(0.3s/帧)，窗口内未出现即视为消失（改名/删除）
        self._prune_timeout = float(self.config.get('prune_timeout', 2.0))

        # 综合缓存
        self.cache: BayCache = None

        # 每个仓位独立的 AreaStatusFilter
        self._filters: Dict[str, AreaStatusFilter] = {}
        self._filters_lock = threading.Lock()

        # ROS2 订阅器
        self._subscription = None
        # 绑定失败重试（doc/52 §7.6）：bind.retry_* 由 smart_trigger.yaml 驱动
        self._bind_retry_cfg = dict(self.config.get('bind') or {})
        self._bind_retries: Dict[str, int] = {}
        self._bind_retry_timers: Dict[str, Any] = {}

    # ════════════════════════════════════════════════════
    #  生命周期
    # ════════════════════════════════════════════════════

    def _configure_impl(self) -> bool:
        bay_configs = self.config.get('bay_configs', None)
        self.cache = BayCache(bay_configs=bay_configs, logger=self.logger)
        self.logger.info(
            f"BayStatusFusion 配置完成: stable_threshold={self._stable_threshold}, "
            f"filter_timeout={self._filter_timeout}, bind_enabled={self._bind_enabled}, "
            f"topic={self._ai_topic}"
        )
        return True

    def _activate_impl(self) -> bool:
        """激活：订阅 AI 检测话题"""
        if not MSG_AVAILABLE:
            self.logger.warning(
                "BayStatus 自定义消息未编译，将使用通用订阅模式。"
                "请确保已执行 colcon build 编译 custom_msgs。"
            )
            # 降级：使用通用消息类型订阅
            from std_msgs.msg import String
            self._subscription = self.node.create_subscription(
                String,
                self._ai_topic,
                self._on_bay_status_fallback,
                10
            )
        else:
            self._subscription = self.node.create_subscription(
                BayStatus,
                self._ai_topic,
                self._on_bay_status,
                10
            )
        self.logger.info(f"BayStatusFusion 激活完成，订阅话题: {self._ai_topic}")
        return True

    def _deactivate_impl(self) -> bool:
        if self._subscription:
            self.node.destroy_subscription(self._subscription)
            self._subscription = None
        self._filters.clear()
        for bay_id, timer in list(self._bind_retry_timers.items()):
            try:
                self.node.destroy_timer(timer)
            except Exception:
                pass
        self._bind_retry_timers.clear()
        self._bind_retries.clear()
        return True

    def _cleanup_impl(self) -> bool:
        self.cache = None
        self._filters.clear()
        return True

    # ════════════════════════════════════════════════════
    #  核心回调 — 正式消息（BayStatus）
    # ════════════════════════════════════════════════════

    def _on_bay_status(self, msg):
        """
        处理 BayStatus 层级消息

        BayStatus 结构:
            header:   std_msgs/Header
            device_id: string               # 如 "dev01"
            channels: BayChannelStatus[]    # 通道列表

        BayChannelStatus 结构:
            channel_id: int32              # 通道编号
            signal_status: bool            # 通道信号状态
            areas: BayArea[]               # 仓位列表

        BayArea 结构:
            bay_id: string                # 仓位编号，如 "A1001"
            has_cargo: bool               # 是否有货物
            cargo_type: int32             # 货物类型 (1~6)
            timestamp: float64            # 检测时间戳
        """
        device_id = msg.device_id
        channel_count = len(msg.channels)
        total_areas = sum(len(ch.areas) for ch in msg.channels)
        
        self.logger.info(
            f"[仓位状态] 收到 AI 检测消息: device={device_id}, "
            f"channels={channel_count}, 总仓位={total_areas}"
        )
        
        # 遍历通道
        for channel in msg.channels:
            channel_id = channel.channel_id
            signal_ok = channel.signal_status
            
            if not signal_ok:
                self.logger.warning(
                    f"[仓位状态] 通道 {channel_id} 无信号，跳过 {len(channel.areas)} 个仓位"
                )
                continue
            
            # 打印该通道的仓位状态摘要
            area_status = []
            for area in channel.areas:
                bay_id = area.bay_id
                has_cargo = area.has_cargo
                cargo_type = area.cargo_type
                status_str = "有货" if has_cargo else "无货"
                area_status.append(f"{bay_id}:{status_str}(type={cargo_type})")
            
            self.logger.debug(
                f"[仓位状态] 通道 {channel_id}: {len(channel.areas)} 个仓位"
            )
            self.logger.info(f"[仓位状态]   → {', '.join(area_status[:4])}{'...' if len(area_status) > 4 else ''}")
            
            # 处理每个仓位
            for area in channel.areas:
                self._process_single_bay(area.bay_id, area.has_cargo, area.cargo_type)

        # 帧末：修剪主题中已消失的仓位（改名/删除）
        self._prune_stale_bays()

    def _on_bay_status_fallback(self, msg):
        """
        降级回调 — 当 BayStatus 消息未编译时使用
        预期 msg.data 为 JSON 格式的 dict
        """
        import json
        try:
            data = json.loads(msg.data)
            device_id = data.get('device_id', 'unknown')
            channels = data.get('channels', [])

            self.logger.debug(f"收到 AI 检测消息 (fallback): device={device_id}")

            for channel in channels:
                if not channel.get('signal_status', False):
                    continue
                for area in channel.get('areas', []):
                    bay_id = area.get('bay_id')
                    has_cargo = area.get('has_cargo', False)
                    cargo_type = area.get('cargo_type', 0)
                    if bay_id:
                        self._process_single_bay(bay_id, has_cargo, cargo_type)

            # 帧末：修剪主题中已消失的仓位（改名/删除）
            self._prune_stale_bays()

        except Exception as e:
            self.logger.error(f"解析 AI 消息失败 (fallback): {e}")

    # ════════════════════════════════════════════════════
    #  主题活跃集修剪（doc/仓位名称类型编排 §13 方案A）
    # ════════════════════════════════════════════════════

    def _prune_stale_bays(self):
        """修剪主题中已消失的仓位（改名/删除），同步清理防抖滤波器。

        每帧（0.3s 全量发布）调用一次：prune_stale 删除
        last_seen > 0 且超过窗口未出现的键；随后清理 _filters 中
        对应的滤波器与历史残留（_get_filter 只增不删，防内存累积）。
        """
        try:
            if not self.cache:
                return
            stale = self.cache.prune_stale(timeout=self._prune_timeout)
            with self._filters_lock:
                active = self.cache.get_active_bay_ids()
                orphans = [bay_id for bay_id in self._filters
                           if bay_id not in active]
                for bay_id in orphans:
                    self._filters.pop(bay_id, None)
            if stale:
                self.logger.info(
                    f"[仓位状态] 修剪消失仓位 {len(stale)} 个并清理滤波器: "
                    f"{', '.join(sorted(stale))}"
                )
            elif orphans:
                self.logger.debug(
                    f"[仓位状态] 清理残留滤波器 {len(orphans)} 个: "
                    f"{', '.join(sorted(orphans))}"
                )
        except Exception as e:
            self.logger.error(f"[仓位状态] 修剪仓位异常: {e}")

    #  单仓位处理逻辑
    # ════════════════════════════════════════════════════

    def _process_single_bay(self, bay_id: str, has_cargo: bool, cargo_type: int):
        """对单个仓位执行防抖滤波 → 判断绑定"""

        # 1. 获取或创建该仓位的滤波器
        flt = self._get_filter(bay_id)

        # 2. 更新滤波状态
        result = flt.update(has_cargo)

        # 3. 同步更新缓存中的 AI 原始结果
        self.cache.update_ai_result(bay_id, has_cargo, cargo_type)

        # 4. 处理状态变化
        if result.get('changed'):
            if result.get('current_state') is True:
                self._on_stable_cargo(bay_id, cargo_type, result)
            else:
                self._on_stable_empty(bay_id, result)

    def _on_stable_cargo(self, bay_id: str, cargo_type: int, result: dict):
        """稳定有货 → 触发 RCS 绑定"""
        self.logger.info(f"仓位 {bay_id} 稳定有货 (cargo_type={cargo_type}), 触发绑定")

        status = self.cache.get_bay_status(bay_id)
        if status and status.get('bind_status') == 1:
            self.logger.debug(f"仓位 {bay_id} 已绑定，跳过")
            self._cancel_bind_retry(bay_id)
            self._bind_retries.pop(bay_id, None)
            return

        self._publish_event('bay.status_changed', {
            'bay_id': bay_id,
            'has_cargo': True,
            'cargo_type': cargo_type,
            'action': 'stable_cargo_detected',
            'filter_info': result,
        })

        if not self._bind_enabled:
            self.logger.debug(f"绑定已禁用，跳过仓位 {bay_id}")
            return

        self.cache.set_binding(bay_id)
        self._bind_retries[bay_id] = 0
        self._do_bind(bay_id, cargo_type)

    # ── 绑定失败重试（doc/52 §7.6） ──

    def set_bind_retry_config(self, cfg: dict):
        """热加载：绑定失败重试配置（smart_trigger 事件透传）"""
        self._bind_retry_cfg = dict(cfg or {})

    def _do_bind(self, bay_id: str, cargo_type: int) -> bool:
        """执行 RCS 绑定；失败时按 bind.retry_* 调度重试。"""
        try:
            rcs_adapter = self._get_rcs_adapter()
            resp = rcs_adapter.bind_ctnr_and_bin(
                bay_id=bay_id,
                cargo_type=cargo_type,
                ind_bind="1"
            )

            if resp.get('code') == '0':
                self.cache.set_bound(bay_id)
                self._bind_retries.pop(bay_id, None)
                self._cancel_bind_retry(bay_id)
                self._publish_event('bay.bound', {
                    'bay_id': bay_id,
                    'cargo_type': cargo_type,
                    'rcs_response': resp,
                })
                self.logger.info(f"仓位 {bay_id} 绑定成功")
                return True

            return self._schedule_bind_retry(
                bay_id, cargo_type, resp.get('msg', '未知错误'))
        except Exception as e:
            return self._schedule_bind_retry(bay_id, cargo_type, str(e))

    def _schedule_bind_retry(self, bay_id: str, cargo_type: int,
                             reason: str) -> bool:
        """按 retry_enabled/retry_count/retry_delay 调度绑定重试；超限则解绑告警。"""
        if not self._bind_retry_cfg.get('retry_enabled'):
            self.cache.set_unbound(bay_id)
            self._bind_retries.pop(bay_id, None)
            self.logger.error(f"仓位 {bay_id} 绑定失败: {reason}（重试未启用）")
            return False

        attempt = self._bind_retries.get(bay_id, 0) + 1
        max_retry = int(self._bind_retry_cfg.get('retry_count', 3))
        if attempt > max_retry:
            self.cache.set_unbound(bay_id)
            self._bind_retries.pop(bay_id, None)
            self.logger.error(
                f"仓位 {bay_id} 绑定失败 {attempt - 1} 次后放弃: {reason}")
            return False

        self._bind_retries[bay_id] = attempt
        delay = float(self._bind_retry_cfg.get('retry_delay', 5.0))
        self.logger.warning(
            f"仓位 {bay_id} 绑定失败({attempt}/{max_retry}): {reason}，"
            f"{delay}s 后重试")
        try:
            timer = self.node.create_timer(
                delay, lambda: self._retry_bind_tick(bay_id, cargo_type))
            self._bind_retry_timers[bay_id] = timer
        except Exception as e:
            self.cache.set_unbound(bay_id)
            self.logger.error(f"仓位 {bay_id} 重试定时器创建失败: {e}")
            return False
        return True

    def _retry_bind_tick(self, bay_id: str, cargo_type: int):
        """重试定时器回调：销毁定时器后重新执行绑定。"""
        timer = self._bind_retry_timers.pop(bay_id, None)
        if timer is not None:
            try:
                self.node.destroy_timer(timer)
            except Exception:
                pass
        # 重试前保持 binding 状态；若仓位已被解绑/重绑则跳过
        status = self.cache.get_bay_status(bay_id)
        if not status or status.get('bind_status') != 2:
            self._bind_retries.pop(bay_id, None)
            return
        self._do_bind(bay_id, cargo_type)

    def _cancel_bind_retry(self, bay_id: str):
        """取消该仓位的重试定时器（成功/解绑/停用时调用）"""
        timer = self._bind_retry_timers.pop(bay_id, None)
        if timer is not None:
            try:
                self.node.destroy_timer(timer)
            except Exception:
                pass

    def _on_stable_empty(self, bay_id: str, result: dict):
        """稳定无货 → 仅更新缓存，发布事件"""
        self.logger.debug(f"仓位 {bay_id} 稳定无货")
        # 取消该仓位的绑定重试（货物已移走）
        self._cancel_bind_retry(bay_id)
        self._bind_retries.pop(bay_id, None)
        self._publish_event('bay.status_changed', {
            'bay_id': bay_id,
            'has_cargo': False,
            'action': 'stable_empty_detected',
            'filter_info': result,
        })
        
        # ===== 若当前绑定状态为“已绑定”，主动解绑（补偿） =====
        status = self.cache.get_bay_status(bay_id)
        if status and status.get('bind_status') == 1:
            self.cache.set_unbound(bay_id)
            self.logger.info(f"仓位 {bay_id} 因稳定无货，自动解绑（补偿）")
            # 人工移走货物/稳定无货 → 通知触发侧移出匹对队列（doc/触发机制审查 §3.3）
            self._publish_event('bay.unbound', {'bay_id': bay_id, 'action': 'stable_empty_unbind'})

    # ════════════════════════════════════════════════════
    #  辅助方法
    # ════════════════════════════════════════════════════

    def _get_filter(self, bay_id: str) -> AreaStatusFilter:
        with self._filters_lock:
            if bay_id not in self._filters:
                self._filters[bay_id] = AreaStatusFilter(
                    stable_threshold=self._stable_threshold,
                    timeout=self._filter_timeout,
                    logger=self.logger
                )
                self.logger.debug(f"创建仓位 {bay_id} 的滤波器")
            return self._filters[bay_id]

    def _get_rcs_adapter(self):
        adapter = getattr(self.node, 'rcs_adapter', None)
        if adapter is None:
            adapter = self.node.plugin_manager.get_plugin('rcs_adapter')
        if adapter is None:
            raise RuntimeError("RCS 适配器未加载")
        return adapter

    # ════════════════════════════════════════════════════
    #  状态查询（Web / 运维用）
    # ════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            'filter_count': len(self._filters),
            'bay_count': self.cache.get_bay_count() if self.cache else 0,
            'bound_count': self.cache.get_bound_count() if self.cache else 0,
            'bind_enabled': self._bind_enabled,
        })
        return base

    def get_all_bay_status(self) -> Dict[str, dict]:
        if self.cache:
            return self.cache.get_all_bay_status()
        return {}

    def get_filter_info(self, bay_id: str) -> Optional[dict]:
        flt = self._filters.get(bay_id)
        return flt.get_status_info() if flt else None

