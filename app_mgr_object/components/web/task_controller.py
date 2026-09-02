#!/usr/bin/env python3
"""
任务控制器 — 任务人工操作（retry / cancel / force_trigger / continue / query）。
"""

import time
import asyncio
from typing import Dict, Any


class TaskController:
    """任务人工操作控制器"""

    def __init__(self, node):
        self.node = node
        self.logger = node.get_logger()

    def _get_plugin(self, name: str):
        plugin = getattr(self.node, name, None)
        if plugin is None and hasattr(self.node, 'plugin_manager'):
            plugin = self.node.plugin_manager.get_plugin(name)
        return plugin

    def task_control(self, operation: str, task_id: str = '',
                     src_bay: str = '', dst_bay: str = '',
                     robot_id: int = 0, cargo_type: int = 1) -> dict:
        """Web 人工操作入口"""
        wf = self._get_plugin('workflow_engine')
        if not wf:
            return {'success': False, 'error': '工作流引擎未加载'}
        engine = wf.get_engine()
        loop = self.node.asyncio_loop

        try:
            if operation == 'query':
                snap = engine.get_instance_snapshot(task_id)
                if snap:
                    return {'success': True, 'task_id': task_id, **snap}
                row = engine.get_task_from_db(task_id)
                if row:
                    return {'success': True, 'task_id': task_id, 'archived': True,
                            'status': row.get('status'),
                            'current_state': row.get('current_state')}
                return {'success': False, 'error': f'任务不存在: {task_id}'}

            if operation in ('retry', 'cancel'):
                event = 'user_retry' if operation == 'retry' else 'user_cancel'
                future = asyncio.run_coroutine_threadsafe(
                    engine.inject_event(task_id, event, {'source': 'web'}), loop)
                future.result(timeout=5)
                return {'success': True, 'task_id': task_id,
                        'operation': operation,
                        'message': f'{operation} 命令已发送: {task_id}'}

            if operation == 'force_trigger':
                if not src_bay or not dst_bay:
                    return {'success': False, 'error': 'force_trigger 需要 src_bay 和 dst_bay'}

                # ① AGV 校验与自动分配
                poller = self._get_plugin('status_poller')
                robot_cache = poller.robot_cache if poller else None
                if not robot_cache:
                    return {'success': False, 'error': 'status_poller 未加载，无法获取 AGV 状态'}

                if robot_id and robot_id > 0:
                    rinfo = robot_cache.get_robot_status(robot_id)
                    if not rinfo:
                        return {'success': False, 'error': f'AGV {robot_id} 不存在'}
                    if rinfo.get('status') != 'AVAILABLE':
                        return {'success': False, 'error':
                                f'AGV {robot_id} 不可用（当前 {rinfo.get("status")}）'}
                else:
                    robot_id = robot_cache.get_available_robot()
                    if not robot_id:
                        return {'success': False, 'error': '无可用 AGV，无法下发强制任务'}

                # ② 生成任务 ID 并锁定资源
                new_id = f"WEB_{int(time.time() * 1000)}"
                ctx = {'task_id': new_id, 'src_bay': src_bay, 'dst_bay': dst_bay,
                    'robot_id': robot_id, 'cargo_type': cargo_type or 1}

                coordinator = getattr(self.node, 'state_coordinator', None)
                locked = False
                if coordinator is not None:
                    locked = coordinator.dispatch_task(robot_id, src_bay, dst_bay, task_id=new_id)
                    if not locked:
                        return {'success': False,
                                'error': '资源冲突：AGV/起始仓/目的仓已被占用或不可用'}

                # ③ 创建工作流实例（失败则回滚释放）
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        engine.create_instance('agv_transport_atomic', ctx), loop)
                    future.result(timeout=5)
                except Exception as e:
                    if coordinator is not None and locked:
                        coordinator.release_task(ctx)
                    return {'success': False, 'error': f'任务创建失败: {e}'}

                return {'success': True, 'task_id': new_id,
                        'operation': 'force_trigger', 'robot_id': robot_id}

            if operation == 'continue':
                snap = engine.get_instance_snapshot(task_id) or {}
                rcs_no = snap.get('rcs_task_no', '')
                if not rcs_no:
                    return {'success': False, 'error': f'无 RCS 任务号: {task_id}'}
                rcs = self._get_plugin('rcs_adapter')
                if not rcs:
                    return {'success': False, 'error': 'RCS 适配器未加载'}
                resp = rcs.continue_task(rcs_no)
                return {'success': resp.get('code') == '0',
                        'message': resp.get('msg', ''), 'task_id': task_id}

            return {'success': False, 'error': f'不支持的操作: {operation}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}