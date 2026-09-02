#!/usr/bin/env python3
"""
事件桥 — 业务事件订阅与 WebSocket 实时推送。

职责：
    1. 订阅业务事件（仓位绑定/状态变化、任务创建/完成/失败、人工干预）
    2. 业务事件 → 采集最新业务数据 → WebSocket 广播 business_update
    3. 巷道状态变化 → WebSocket 广播 slot_update
    4. 告警产生 → WebSocket 广播 alarm_update
    5. 通用 WebSocket 广播方法

依赖：
    - node.event_bus      用于订阅业务事件
    - node.business_collector  用于采集业务数据
    - node.status_monitor  用于巷道状态
    - web_server.manager   用于 WebSocket 广播
"""

import time
import asyncio
import collections
from typing import Dict, Any, List

TASK_ALARM_LEVEL_MAP = {
    'INFO': 'info', 'WARNING': 'warning', 'SEVERE': 'error', 'CRITICAL': 'critical',
}

class EventBridge:
    """事件桥 — 连接业务事件总线与 WebSocket 实时推送"""

    def __init__(self, node, web_server):
        """
        Args:
            node: ROS2 Node（用于获取 event_bus / business_collector / status_monitor）
            web_server: WebServer 实例（用于 WebSocket 广播）
        """
        self.node = node
        self.web_server = web_server
        self.logger = node.get_logger()
        self._subscribed = False
        
        self._refresh_pending = False
        self._refresh_delay = 0.4   # 秒；等待引擎实例移除完成
        # P1 v5：最近失败任务缓存（异常红色连线数据源；failed 实例会从 active_instances 移除，须走事件缓存）
        self._recent_failures = collections.deque(maxlen=10)

    # ==================== 事件订阅 ====================

    def subscribe_all(self):
        """订阅所有业务事件 + 巷道状态事件"""
        event_bus = getattr(self.node, 'event_bus', None)
        if not event_bus:
            self.logger.error("❌ 事件总线不可用，无法订阅业务事件")
            return

        # 业务事件（触发业务汇总推送）
        business_events = [
            'bay.bound',
            'bay.status_changed',
            'bay.unbound',              # 解绑（人工移走货物）→ 刷新 + toast（doc/触发机制 §8.1）
            'trigger.task_created',
            'workflow.task_started',
            'workflow.task_completed',
            'workflow.task_needs_manual',
        ]
        for evt in business_events:
            event_bus.subscribe(evt, self._on_business_event)
        # 解绑专用：推送 bay_unbound 供前端 toast（运维可观测）
        event_bus.subscribe('bay.unbound', self._on_bay_unbound)
        # P1 v5：任务失败单独绑定（记录最近失败缓存 → 异常红色连线）
        event_bus.subscribe('workflow.task_failed', self._on_task_failed)

        # 巷道状态事件
        event_bus.subscribe('slot_status_changed', self._on_slot_status_changed)
        event_bus.subscribe('rcs.alarm_escalated', self._on_alarm_escalated)
        
        event_bus.subscribe('rcs.alarm_logged', self._on_task_alarm_logged)
        event_bus.subscribe('rcs.critical_alarm', self._on_task_critical_alarm)
        
        self._subscribed = True
        self.logger.info(f"✅ 已订阅 {len(business_events) + 2} 个业务事件（实时推送）")
        
        
        

    # ==================== 业务事件回调 ====================
    
    def _on_alarm_escalated(self, data: dict):
        """人工介入超时升级 → AlarmManager 告警（add_alarm 自带去重）"""
        try:
            task_id = data.get('task_id', '')
            duration = int(data.get('duration', 0))
            wm = getattr(self.node, 'web_monitor', None)
            # message 保持静态，避免时长变化导致去重失效
            message = f"任务 {task_id} 人工介入超时，请处置"
            if wm and getattr(wm, 'alarm_manager', None):
                wm.alarm_manager.add_alarm(
                    alarm_type='system',
                    level='warning',
                    message=message,
                    details={
                        'task_id': task_id,
                        'duration': duration,
                        'agv_code': data.get('agv_code', ''),
                        'source': 'manual_timeout_escalated',
                    },
                    source='task_monitor',
                )
                # 新增告警会通过 web_monitor 注册的回调自动 WebSocket 广播
            else:
                # AlarmManager 未就绪时的降级广播
                self.broadcast('alarm_update', {
                    'count': 1,
                    'new_alarms': [{
                        'id': f'ESC-{int(time.time() * 1000)}',
                        'type': 'system',
                        'level': 'warning',
                        'message': message,
                        'task_id': task_id,
                        'duration': duration,
                    }],
                })
        except Exception as e:
            self.logger.debug(f"告警升级推送失败: {e}")

    # def _on_business_event(self, data: dict):
    #     """业务事件回调 → 采集最新业务数据 → 推送 business_update"""
    #     try:
    #         bc = getattr(self.node, 'business_collector', None)
    #         if not bc:
    #             return
    #         summary = bc.collect_business_status()
    #         self.broadcast('business_update', summary)
    #     except Exception as e:
    #         self.logger.debug(f"业务事件推送失败: {e}")
    
    # ==================== P1 v5：任务失败缓存（异常红色连线） ====================

    def _on_task_failed(self, data: dict):
        """任务失败事件 → 记录最近失败缓存 + 触发业务刷新推送"""
        try:
            self._recent_failures.appendleft({
                'task_id': data.get('task_id', ''),
                'src_bay': data.get('src_bay', ''),
                'dst_bay': data.get('dst_bay', ''),
                'state': data.get('state', 'failed'),
                'robot_id': data.get('robot_id', ''),
                'failed_at': time.time(),
            })
            self.logger.warning(
                f"[P1] 任务失败记录: {data.get('task_id')} "
                f"{data.get('src_bay')}→{data.get('dst_bay')}"
            )
        except Exception as e:
            self.logger.debug(f"任务失败缓存失败: {e}")
        self._schedule_business_refresh()

    def get_recent_failures(self) -> List[dict]:
        """最近失败任务列表（异常连线数据源）"""
        return list(self._recent_failures)

    def _on_business_event(self, data: dict):
        """业务事件回调 → 防抖延迟采集推送"""
        self._schedule_business_refresh()
        
    def _schedule_business_refresh(self):
        if self._refresh_pending:
            return
        self._refresh_pending = True
        loop = getattr(self.node, 'asyncio_loop', None)
        if loop is None or loop.is_closed():
            self._refresh_pending = False
            return

        async def _delayed_refresh():
            try:
                await asyncio.sleep(self._refresh_delay)
                bc = getattr(self.node, 'business_collector', None)
                if bc:
                    summary = bc.collect_business_status()
                    self.broadcast('business_update', summary)
            except Exception as e:
                self.logger.debug(f"业务事件推送失败: {e}")
            finally:
                self._refresh_pending = False

        try:
            asyncio.run_coroutine_threadsafe(_delayed_refresh(), loop)
        except Exception as e:
            self._refresh_pending = False
            self.logger.debug(f"业务刷新调度失败: {e}")

    def _on_slot_status_changed(self, event_data: Dict[str, Any]):
        """巷道状态变化 → 推送 slot_update"""
        try:
            sm = getattr(self.node, 'status_monitor', None)
            if not sm:
                return
            lanes_cache = sm._get_lanes_cache_status() if hasattr(sm, '_get_lanes_cache_status') else {}
            self.broadcast('slot_update', {'lanes_cache': lanes_cache})
        except Exception as e:
            self.logger.error(f"处理 slot_status_changed 事件失败: {e}")

    def _on_bay_unbound(self, event_data: Dict[str, Any]):
        """始发仓解绑（人工移走货物/稳定无货）→ 推送 bay_unbound 供前端 toast（doc/触发机制 §8.1）"""
        try:
            self.broadcast('bay_unbound', {
                'bay_id': event_data.get('bay_id', ''),
                'action': event_data.get('action', 'stable_empty_unbind'),
                'ts': time.time(),
            })
        except Exception as e:
            self.logger.error(f"处理 bay_unbound 事件失败: {e}")

    # ==================== WebSocket 广播 ====================

    def broadcast(self, msg_type: str, data: Any = None):
        """通用 WebSocket 广播

        Args:
            msg_type: 消息类型（business_update / slot_update / alarm_update / config_updated / status_update）
            data: 消息数据体
        """
        try:
            if not self.web_server:
                return
            manager = self.web_server.manager
            loop = getattr(manager, '_event_loop', None)
            if not loop or loop.is_closed():
                return

            message = {
                'type': msg_type,
                'timestamp': time.time(),
                'data': data if data is not None else {},
            }

            asyncio.run_coroutine_threadsafe(
                manager.broadcast_json(message),
                loop
            )
        except Exception as e:
            self.logger.debug(f"WebSocket 广播失败 [{msg_type}]: {e}")

    def broadcast_config_updated(self, section: str):
        """配置热加载成功 → 推送 config_updated"""
        self.broadcast('config_updated', {
            'section': section,
            'timestamp': time.time(),
        })

    def broadcast_status_update(self, status: dict):
        """系统状态 → 推送 status_update"""
        self.broadcast('status_update', status)

    def broadcast_alarm_update(self, alarms: List[dict]):
        """告警更新 → 推送 alarm_update（仅推送未确认告警摘要）"""
        if not alarms:
            return
        unack_count = sum(1 for a in alarms if not a.get('acknowledged', True))
        new_alarms = [a for a in alarms if not a.get('acknowledged', True)]

        self.broadcast('alarm_update', {
            'count': unack_count,
            'new_alarms': new_alarms[:5],   # 最多推送 5 条，防止消息过大
        })

    def broadcast_status_periodic(self, status: dict):
        """状态监控周期推送（与 status_update 区分，避免刷屏）"""
        self.broadcast('status_periodic', status)
        
    def _on_task_alarm_logged(self, data: dict):
        try:
            task_code = data.get('task_code', '')
            wm = getattr(self.node, 'web_monitor', None)
            if not task_code or not wm or not getattr(wm, 'alarm_manager', None):
                return
            wm.alarm_manager.add_alarm(
                alarm_type='task',
                level=TASK_ALARM_LEVEL_MAP.get(
                    str(data.get('alarm_level', '')).upper(), 'info'),
                message=f"[任务 {task_code}] {data.get('warn_code', '告警')}: {data.get('warn_msg', '')}",
                details={'task_id': task_code,
                        'warn_code': data.get('warn_code', ''),
                        'agv_code': data.get('agv_code', '')},
                source='rcs_warn_callback',
            )
        except Exception as e:
            self.logger.debug(f"任务告警展示失败: {e}")

    def _on_task_critical_alarm(self, data: dict):
        try:
            task_code = data.get('task_code', '')
            wm = getattr(self.node, 'web_monitor', None)
            if not task_code or not wm or not getattr(wm, 'alarm_manager', None):
                return
            wm.alarm_manager.add_alarm(
                alarm_type='task', level='critical',
                message=f"[任务 {task_code}] 紧急告警: {data.get('warn_msg', '')}",
                details={'task_id': task_code, 'agv_code': data.get('agv_code', '')},
                source='rcs_critical_alarm',
            )
        except Exception as e:
            self.logger.debug(f"紧急告警展示失败: {e}")