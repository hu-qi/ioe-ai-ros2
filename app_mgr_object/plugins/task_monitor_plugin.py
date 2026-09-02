#!/usr/bin/env python3
"""
task_status_monitor_plugin — 任务状态按需周期轮询插件 (v2.0)

核心改进（相对 v1.0）:
  - 事件驱动的 Timer 启停: 有 monitoring 任务时激活, 无任务时停止
  - poll_if_needed() 代替盲轮询
  - 两轮连续空闲确认避免抖动
"""
import time
from typing import Dict, Any, Optional

from .base_plugin import BasePlugin
from app_mgr_object.components.task_monitor import (
    TaskStatusMonitor, TaskStatusCode
)


class TaskStatusMonitorPlugin(BasePlugin):
    PLUGIN_NAME = "task_status_monitor"
    PLUGIN_VERSION = "2.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        self._poll_interval = self.config.get('poll_interval', 10.0)
        self._poll_timeout   = self.config.get('poll_timeout', 8.0)
        self._enabled        = self.config.get('enabled', True)

        self._monitor: Optional[TaskStatusMonitor] = None
        self._poll_timer = None

        # 统计
        self._total_polls: int = 0
        self._status_changes: int = 0
        
        # === manual_intervention 轮询控制 ===
        self._last_manual_poll: float = 0.0
        self._manual_poll_interval: float = 30.0  # 30s 一次
        self._manual_timeout: float = 600.0       # 10分钟超时升级
        
        # ===  日志清理控制 ===
        self._cleanup_retention_days = self.config.get('log_retention_days', 90)
        self._cleanup_interval = self.config.get('log_cleanup_interval', 604800.0)  # 7天
        self._cleanup_timer = None

    # ════════════════════════════════════════════════════
    #  生命周期
    # ════════════════════════════════════════════════════

    def _configure_impl(self) -> bool:
        self._monitor = TaskStatusMonitor(
            on_status_changed=self._on_status_changed,
            poll_timeout=self._poll_timeout,
            logger=self.logger,
        )
        self._manual_timeout = self.config.get('manual_timeout', 600.0)
        self._manual_force_close_after = self.config.get('manual_force_close_after', 1800.0)
        self._manual_unknown_max_rounds = self.config.get('manual_unknown_max_rounds', 3)
        # 每任务状态跟踪（防重复注入 / 统计未知轮数）
        self._manual_unknown_rounds: Dict[str, int] = {}
        self._manual_force_closed: set = set()
    
        self.logger.info(f"TaskStatusMonitor 配置: "
                         f"poll_interval={self._poll_interval}s, enabled={self._enabled}")
        return True

    def _activate_impl(self) -> bool:
        if not self._enabled:
            return True

        # 事件订阅（用于按需启停 Timer）
        self.event_bus.subscribe('workflow.task_started', self._on_task_started)
        self.event_bus.subscribe('workflow.task_completed', self._on_task_ended)
        self.event_bus.subscribe('workflow.task_failed', self._on_task_ended)

        # 首次启动时检查是否有历史实例在 monitoring
        self._ensure_timer_if_needed()
        
        # ===  启动日志定期清理 ===
        # 启动时立即执行一次
        self._cleanup_logs_once()
        # 定期清理 (默认每 7 天)
        self._cleanup_timer = self.node.create_timer(
            self._cleanup_interval, self._cleanup_logs_once
        )
        self.logger.info(
            f"日志清理定时器已启动 (间隔 {self._cleanup_interval}s, "
            f"保留 {self._cleanup_retention_days} 天)"
        )

        self.logger.info("TaskStatusMonitor v2 激活完成 (按需轮询模式)")
        return True

    def _deactivate_impl(self) -> bool:
        self._stop_poll_timer()
        
        # ===  销毁清理定时器 ===
        if self._cleanup_timer:
            self.node.destroy_timer(self._cleanup_timer)
            self._cleanup_timer = None
            
        return True

    def _cleanup_impl(self) -> bool:
        self._monitor = None
        return True

    # ════════════════════════════════════════════════════
    #  Timer 生命周期 (按需启停)
    # ════════════════════════════════════════════════════

    def _start_poll_timer(self):
        """启动轮询定时器（已在运行时不再重复创建）"""
        if self._poll_timer is not None:
            return
        self._poll_timer = self.node.create_timer(
            self._poll_interval, self._poll_once
        )
        self.logger.info(f"轮询定时器已启动 (间隔 {self._poll_interval}s)")

    def _stop_poll_timer(self):
        """停止轮询定时器"""
        if self._poll_timer is not None:
            self.node.destroy_timer(self._poll_timer)
            self._poll_timer = None
            self.logger.info("轮询定时器已停止 (无活跃任务)")

    def _ensure_timer_if_needed(self):
        """根据当前 active instances 状态决定启用/停用 timer"""
        engine = self._get_workflow_engine()
        if not engine:
            return
        active = engine.get_active_monitoring_instances()
        if active:
            self._start_poll_timer()
        else:
            self._stop_poll_timer()

    # ════════════════════════════════════════════════════
    #  轮询执行
    # ════════════════════════════════════════════════════

    def _poll_once(self):
        """定时器回调: 执行一轮按需轮询 (monitoring + manual_intervention)"""
        try:
            engine = self._get_workflow_engine()
            if not engine:
                return

            # === 1. 监控 monitoring 实例  ===
            monitoring = engine.get_active_monitoring_instances()
            if monitoring:
                rcs = self._get_rcs_adapter()
                if rcs:
                    self._monitor.poll_if_needed(rcs, monitoring)

            # === 2. 监控 manual_intervention 实例 (低频率) ===
            if self._should_poll_manual():
                all_monitorable = engine.get_all_active_monitorable_instances()
                manual_only = {
                    k: v for k, v in all_monitorable.items()
                    if k not in monitoring
                }
                if manual_only:
                    rcs = self._get_rcs_adapter()
                    if rcs:
                        self._poll_manual_instances(rcs, manual_only, engine)

            # === 3. 判断是否停止 timer ===
            if not monitoring and not engine.get_all_active_monitorable_instances():
                if self._monitor.should_stop_timer():
                    self._stop_poll_timer()
                    return

            self._total_polls += 1

        except Exception as e:
            self.logger.warning(f"轮询执行异常: {e}")
            
    
    def _should_poll_manual(self) -> bool:
        """manual_intervention 实例轮询频率控制 (每 30s 一次)"""
        now = time.time()
        if now - self._last_manual_poll >= self._manual_poll_interval:
            self._last_manual_poll = now
            return True
        return False


    def _poll_manual_instances(self, rcs, manual_instances: dict, engine):
        """对 manual_intervention 实例查询 RCS 状态，实现自动自洽闭环。

        闭环策略（防悬空）：
        - RCS 终态 9/7/8 → auto_resolved / auto_failed
        - 超时 + 宽限后仍未终态 → auto_failed(manual_force_close)
        - RCS 无数据/未知连续 N 轮 → auto_failed(manual_unknown)
        - 无 rcs_task_no 且超时 + 宽限 → auto_failed(no_rcs_task_no)
        """
        import asyncio
        import json

        task_codes = list(manual_instances.keys())
        self.logger.debug(f"manual_intervention 轮询: {len(task_codes)} 个任务")
        if not task_codes:
            return

        try:
            # ① 批量按 taskCode 查询
            resp = rcs.query_task_status(task_codes)
            matched = {}
            if resp.get('code') == '0':
                for item in resp.get('data', []):
                    code = str(item.get('taskCode', ''))
                    if code in manual_instances:
                        matched[code] = str(item.get('taskStatus', ''))

            now = time.time()
            for task_code in task_codes:
                snap = engine.get_instance_snapshot(task_code)
                if not snap:
                    continue
                if snap['current_state'] != 'manual_intervention':
                    continue

                ctx = snap.get('context', {}) or {}
                rcs_task_no = ctx.get('rcs_task_no', '')
                entered_at = ctx.get('manual_entered_at', 0) or 0
                elapsed = now - entered_at if entered_at else 0
                robot_id = ctx.get('robot_id', '')

                # ② 状态获取：批量命中 → 直接使用；未命中 → taskNo 单查回退
                task_status = matched.get(task_code, '')
                if not task_status:
                    if rcs_task_no:
                        try:
                            r2 = rcs.query_task_status_unified(
                                task_code, rcs_task_no)
                            task_status = rcs.extract_task_status(
                                r2, task_code, rcs_task_no)
                        except Exception as e:
                            self.logger.warning(
                                f"manual 回退查询失败 {task_code}: {e}")
                            task_status = ''
                    else:
                        task_status = ''   # 无 rcs_task_no，无法查询

                # ③ 终态自动闭环
                if task_status == '9':
                    self.logger.info(
                        f"自动闭环: {task_code} RCS 已完成(9), 注入 auto_resolved")
                    self._inject_manual_event(
                        engine, task_code, 'auto_resolved',
                        {'task_status': task_status,
                        'source': 'task_monitor_auto_closure'})
                    self._manual_unknown_rounds.pop(task_code, None)
                    continue
                if task_status in ('7', '8'):
                    self.logger.warning(
                        f"自动闭环: {task_code} RCS 已终结({task_status}), 注入 auto_failed")
                    self._inject_manual_event(
                        engine, task_code, 'auto_failed',
                        {'task_status': task_status,
                        'source': 'task_monitor_auto_closure'})
                    self._manual_unknown_rounds.pop(task_code, None)
                    continue

                # ④ 未知/无数据轮数累计
                if not task_status:
                    rounds = self._manual_unknown_rounds.get(task_code, 0) + 1
                    self._manual_unknown_rounds[task_code] = rounds
                else:
                    self._manual_unknown_rounds[task_code] = 0

                # ⑤ 超时升级告警（修复后的 NameError 版本）
                if entered_at and elapsed > self._manual_timeout:
                    self.logger.warning(
                        f"告警升级: {task_code} 在 manual_intervention 已超 "
                        f"{int(elapsed)}s, 等待人工处置")
                    self._publish_event('rcs.alarm_escalated', {
                        'task_id': task_code,
                        'duration': elapsed,
                        'agv_code': robot_id,
                    })

                # ⑥ 强制闭环策略（防悬空）
                reason = None
                if entered_at and elapsed > (self._manual_timeout
                                            + self._manual_force_close_after):
                    reason = 'manual_force_close'   # 超时+宽限仍未终态
                elif not rcs_task_no and entered_at and elapsed > (
                        self._manual_timeout + self._manual_force_close_after):
                    reason = 'no_rcs_task_no'       # 无任务号且超期
                elif not task_status and rounds >= self._manual_unknown_max_rounds:
                    reason = 'manual_unknown'       # RCS 无数据/未知连续超限

                if reason and task_code not in self._manual_force_closed:
                    self._manual_force_closed.add(task_code)
                    self.logger.warning(
                        f"强制闭环: {task_code} 原因={reason}, "
                        f"注入 auto_failed（防悬空）")
                    try:
                        engine.log_exception(
                            task_code, 'manual_force_close',
                            json.dumps({
                                'reason': reason,
                                'rcs_status': task_status,
                                'elapsed': int(elapsed),
                                'rcs_task_no': rcs_task_no,
                            }))
                    except Exception:
                        pass
                    self._inject_manual_event(
                        engine, task_code, 'auto_failed',
                        {'task_status': task_status,
                        'reason': reason,
                        'source': 'task_monitor_force_close'})
                    self._manual_unknown_rounds.pop(task_code, None)

        except Exception as e:
            self.logger.warning(f"manual_intervention 轮询异常: {e}")
            
            
    def _inject_manual_event(self, engine, task_code: str, event: str,
                         data: dict):
        """注入事件到工作流实例（跨线程安全，失败仅记录）"""
        import asyncio
        try:
            future = asyncio.run_coroutine_threadsafe(
                engine.inject_event(task_code, event, data),
                self.node.asyncio_loop
            )
            future.add_done_callback(
                lambda f, tc=task_code, ev=event: (
                    self.logger.debug(f"{ev} 注入完成: {tc}")
                    if f.exception() is None
                    else self.logger.error(f"{ev} 注入失败: {tc} {f.exception()}")
                )
            )
        except Exception as e:
            self.logger.error(f"注入事件异常 {task_code} → {event}: {e}")

    # ════════════════════════════════════════════════════
    #  事件回调
    # ════════════════════════════════════════════════════

    def _on_task_started(self, data: dict):
        """有新任务启动 → 激活 timer"""
        task_id = data.get('task_id', '')
        self.logger.debug(f"任务启动，激活轮询: {task_id}")
        self._start_poll_timer()

    def _on_task_ended(self, data: dict):
        """任务终结 → 检查是否需要停 timer"""
        task_id = data.get('task_id', '')
        self.logger.debug(f"任务终结: {task_id}")
        # 延迟检查（下一轮 poll_once 会自动判断）
        # 立即检查一次以加速停止
        self._ensure_timer_if_needed()

    def _on_status_changed(self, task_code: str, new_status: str, engine_event: str):
        """TaskStatusMonitor 检测到终态变化 → 注入引擎"""
        engine = self._get_workflow_engine()
        if not engine:
            return
        import asyncio
        try:
            loop = self.node.asyncio_loop
            asyncio.run_coroutine_threadsafe(
                engine.inject_event(task_code, engine_event, {
                    'task_code': task_code,
                    'task_status': new_status,
                    'source': 'task_status_monitor',
                }), loop
            )
            self.logger.info(f"注入事件: {task_code} → {engine_event} "
                             f"(status={new_status})")
        except Exception as e:
            self.logger.error(f"注入事件失败: {e}")
            
    
    def _cleanup_logs_once(self):
        """执行一次日志清理（启动时 + 每 7 天）"""
        try:
            engine = self._get_workflow_engine()
            if not engine:
                return

            # 使用引擎公开方法，不再直接访问 _persistence
            result = engine.cleanup_old_logs(self._cleanup_retention_days)

            if result.get('total_deleted', 0) > 0:
                self.logger.info(
                    f"日志定期清理: 删除 {result['total_deleted']} 条 "
                    f"(保留 {self._cleanup_retention_days} 天)"
                )
        except Exception as e:
            self.logger.warning(f"日志清理异常 (非致命): {e}")        
    

    # ════════════════════════════════════════════════════
    #  辅助
    # ════════════════════════════════════════════════════

    def _get_workflow_engine(self):
        engine_plugin = getattr(self.node, 'workflow_engine', None)
        if engine_plugin is None:
            engine_plugin = self.node.plugin_manager.get_plugin('workflow_engine')
        if engine_plugin and hasattr(engine_plugin, 'get_engine'):
            return engine_plugin.get_engine()
        return None

    def _get_rcs_adapter(self):
        adapter = getattr(self.node, 'rcs_adapter', None)
        if adapter is None:
            adapter = self.node.plugin_manager.get_plugin('rcs_adapter')
        return adapter

    # ════════════════════════════════════════════════════
    #  状态查询 (Web/运维)
    # ════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        stats = self._monitor.get_stats() if self._monitor else {}
        base.update({
            'enabled': self._enabled,
            'poll_interval': self._poll_interval,
            'timer_active': self._poll_timer is not None,
            'total_polls': self._total_polls,
            'status_changes': self._status_changes,
            **stats,
        })
        return base

    def get_task_status(self, task_code: str) -> Optional[Dict[str, str]]:
        if self._monitor:
            s = self._monitor.get_last_known_status(task_code)
            if s:
                return {'task_code': task_code, 'status': s,
                        'status_name': TaskStatusCode.status_name(s)}
        return None

    def get_all_monitored(self) -> Dict[str, str]:
        return self._monitor.get_all_last_known() if self._monitor else {}