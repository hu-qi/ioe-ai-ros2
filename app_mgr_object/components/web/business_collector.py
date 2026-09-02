#!/usr/bin/env python3
"""
业务数据采集器 — 从各业务插件采集实时数据，供 Web API 和 WebSocket 消费。

依赖：通过 node 获取 bay_status_fusion / status_poller / smart_trigger / workflow_engine 插件实例。
"""

import time
from typing import Dict, Any


class BusinessCollector:
    """业务数据采集器"""

    def __init__(self, node, plugin_host):
        """
        Args:
            node: ROS2 Node（用于获取 _get_plugin 工具方法）
            plugin_host: WebMonitorPlugin 实例（用于 logger 和 _get_plugin）
        """
        self.node = node
        self._host = plugin_host    # 保留引用用于 _get_plugin / logger
        self.logger = plugin_host.logger

    def _get_plugin(self, name: str):
        """安全获取业务插件实例"""
        plugin = getattr(self.node, name, None)
        if plugin is None and hasattr(self.node, 'plugin_manager'):
            plugin = self.node.plugin_manager.get_plugin(name)
        return plugin

    # ==================== 仓位采集 ====================

    def get_bay_status(self) -> dict:
        """采集起始仓位状态（BayCache → 24 格热力图数据）"""
        try:
            fusion = self._get_plugin('bay_status_fusion')
            if not fusion or not fusion.cache:
                return {'bays': [], 'total': 0}
            bays = fusion.cache.get_all_bay_status()
            now = time.time()
            result, by_type = [], {}
            for bid, bay in bays.items():
                ct = bay.get('cargo_type', 0)
                by_type.setdefault(str(ct), {'total': 0, 'bound': 0, 'available': 0})
                by_type[str(ct)]['total'] += 1
                if bay.get('bind_status') == 1:
                    by_type[str(ct)]['bound'] += 1
                    if not bay.get('in_task'):
                        by_type[str(ct)]['available'] += 1
                result.append({
                    'bay_id': bay['bay_id'],
                    'cargo_type': ct,
                    'bind_status': bay.get('bind_status', 0),
                    'bind_status_label': {0: '未绑定', 1: '已绑定', 2: '绑定中'}.get(
                        bay.get('bind_status', 0), '未知'),
                    'ai_detected': bay.get('ai_detected', False),
                    'in_task': bay.get('in_task', False),
                    'bind_time': bay.get('bind_time', 0),
                    'bind_duration': round(now - bay.get('bind_time', now), 1)
                        if bay.get('bind_status') == 1 else 0,
                    'last_seen': bay.get('last_seen', 0),
                })
            return {
                'timestamp': now, 'total': len(result),
                'bound_count': sum(1 for b in result if b['bind_status'] == 1),
                'in_task_count': sum(1 for b in result if b['in_task']),
                'by_type': by_type, 'bays': result,
            }
        except Exception as e:
            self.logger.error(f"采集起始仓位状态失败: {e}")
            return {'bays': [], 'total': 0, 'error': str(e)}

    def get_dest_status(self) -> dict:
        """采集终点仓位状态（DestBayCache → 18 格网格数据）"""
        try:
            poller = self._get_plugin('status_poller')
            if not poller or not poller.dest_cache:
                return {'bays': [], 'total': 0}
            bays = poller.dest_cache.get_all_bay_status()
            result, by_floor = [], {}
            for bid, bay in bays.items():
                floor = bay.get('floor_no', 0)
                by_floor.setdefault(str(floor), {'total': 0, 'empty': 0})
                by_floor[str(floor)]['total'] += 1
                if bay.get('is_empty'):
                    by_floor[str(floor)]['empty'] += 1
                # 目的仓状态（前端四色，doc/触发机制 §九）：
                # empty 空·绿 / occupied 有货占用·灰黑 / reserved 已匹对锁定·橙 / unbind 解绑释放·蓝
                status = 'empty'
                try:
                    status = poller.dest_cache.get_bay_state(bid)
                except Exception:
                    pass
                result.append({
                    'bay_id': bay['bay_id'],
                    'cargo_type': bay.get('cargo_type', 0),
                    'floor_no': floor,
                    'is_empty': bay.get('is_empty', True),
                    'status': status,
                    # doc/54 阶段3：蓝色=解绑释放，真实状态可再匹配（unbind 时 is_empty 必为 True）
                    'rematchable': (status == 'unbind' and bay.get('is_empty', True)),
                    'update_time': bay.get('update_time', 0),
                })
            return {
                'timestamp': time.time(), 'total': len(result),
                'empty_count': sum(1 for b in result if b['is_empty']),
                'reserved_count': sum(1 for b in result if b['status'] == 'reserved'),
                'unbind_count': sum(1 for b in result if b['status'] == 'unbind'),
                'rematchable_count': sum(1 for b in result if b.get('rematchable')),
                'by_floor': by_floor, 'bays': result,
            }
        except Exception as e:
            self.logger.error(f"采集终点仓位状态失败: {e}")
            return {'bays': [], 'total': 0, 'error': str(e)}

    # ==================== AGV 采集 ====================

    def get_agv_status(self) -> dict:
        """采集 AGV 状态（RobotCache → 卡片数据）"""
        try:
            poller = self._get_plugin('status_poller')
            if not poller or not poller.robot_cache:
                return {'robots': [], 'available_count': 0}
            robots = poller.robot_cache.get_all_robot_status()
            result = [{
                'robot_id': rid,
                'status': r.get('status', 'OFFLINE'),
                'battery': r.get('battery', 0),
                'position_code': r.get('position_code', ''),
                'current_task_id': r.get('current_task_id', ''),
                'update_time': r.get('update_time', 0),
            } for rid, r in robots.items()]
            return {
                'timestamp': time.time(),
                'available_count': sum(1 for r in result if r['status'] == 'AVAILABLE'),
                'total': len(result),
                'robots': result,
            }
        except Exception as e:
            self.logger.error(f"采集 AGV 状态失败: {e}")
            return {'robots': [], 'available_count': 0}

    # ==================== 任务采集 ====================

    def get_task_queue_data(self) -> dict:
        try:
            trigger = self._get_plugin('smart_trigger')
            if not trigger:
                return {'queue': [], 'size': 0, 'stats': {}, 'last_dequeued': []}
            task_queue = getattr(trigger, '_task_queue', None)
            if task_queue:
                stats = task_queue.get_stats()
                items = task_queue.get_queue_items() if hasattr(task_queue, 'get_queue_items') else []
                last_dequeued = (task_queue.get_last_dequeued()
                                if hasattr(task_queue, 'get_last_dequeued') else [])
                return {
                    'timestamp': time.time(),
                    'size': stats.get('queue_size', 0),
                    'queue': items,
                    'stats': stats,
                    'last_dequeued': last_dequeued,
                }
            return {'queue': [], 'size': 0, 'stats': {}, 'last_dequeued': []}
        except Exception as e:
            self.logger.error(f"采集任务队列失败: {e}")
            return {'queue': [], 'size': 0, 'stats': {}, 'last_dequeued': []}

    def get_active_instances(self) -> dict:
        """采集活跃工作流实例（兼容字符串列表返回）"""
        try:
            wf = self._get_plugin('workflow_engine')
            if not wf:
                return {'instances': [], 'count': 0}
            engine = wf.get_engine()
            if not engine:
                return {'instances': [], 'count': 0}

            # P1 v4 修复（doc/P1 规范 §十二）：engine.get_active_instances() 返回
            # {task_id: {task_id, current_state, status, src_bay, dst_bay, robot_id, cargo_type}} 字典，
            # 值里已含 src_bay/dst_bay——直接取 dict 值，勿走 snapshot（其无顶层 src_bay/dst_bay，会丢失）
            active_map = engine.get_active_instances() or {}
            result = []

            if isinstance(active_map, dict):
                for task_id, snap in active_map.items():
                    result.append({
                        'task_id': task_id,
                        'status': snap.get('status', 'unknown'),
                        'current_state': snap.get('current_state', ''),
                        'src_bay': snap.get('src_bay', ''),
                        'dst_bay': snap.get('dst_bay', ''),
                        'robot_id': snap.get('robot_id', ''),
                        'cargo_type': snap.get('cargo_type', 0),
                        'rcs_task_no': snap.get('rcs_task_no', ''),   # 任务面板“继续”按钮依据（doc/62）
                        'created_at': (time.strftime('%Y-%m-%d %H:%M:%S',
                            time.localtime(snap.get('created_at') or 0))
                            if snap.get('created_at') else ''),
                    })
            else:
                # 兼容旧字符串列表：从 snapshot 的 context 取 src/dst
                for item in active_map:
                    if isinstance(item, str):
                        snap = engine.get_instance_snapshot(item) or {}
                        ctx = snap.get('context', {}) or {}
                        result.append({
                            'task_id': item,
                            'status': snap.get('status', 'unknown'),
                            'current_state': snap.get('current_state', ''),
                            'src_bay': ctx.get('src_bay', ''),
                            'dst_bay': ctx.get('dst_bay', ''),
                            'robot_id': ctx.get('robot_id', ''),
                            'cargo_type': ctx.get('cargo_type', 0),
                            'rcs_task_no': ctx.get('rcs_task_no', ''),
                            'created_at': '',
                        })

            return {'timestamp': time.time(), 'instances': result, 'count': len(result)}
        except Exception as e:
            self.logger.error(f"采集活跃实例失败: {e}")
            return {'instances': [], 'count': 0}

    def get_task_statistics(self) -> dict:
        """采集任务统计（doc/AGV状态卡改造与工作时间设置 §3.2）

        返回：today_completed（今日完成）/ executing（执行中）/ failed（今日异常）
              ready（数据源是否就绪）/ last_error（未就绪或异常原因，doc/58 R-01）
        """
        empty = {'by_status': {}, 'total': 0,
                 'today_completed': 0, 'executing': 0, 'failed': 0,
                 'locked_dest': 0}
        try:
            wf = self._get_plugin('workflow_engine')
            if not wf:
                self.logger.warning("任务统计: workflow_engine 插件未加载，数据源未就绪")
                return dict(empty, ready=False, source='workflow_engine',
                            last_error='workflow_engine 未加载')
            engine = wf.get_engine()
            if not engine:
                self.logger.warning("任务统计: workflow_engine 引擎未就绪，数据源未就绪")
                return dict(empty, ready=False, source='workflow_engine',
                            last_error='workflow_engine 未激活')
            active_dict = engine.get_active_instances() or {}
            by_status = {}
            for inst_data in active_dict.values():
                st = inst_data.get('status', 'unknown')
                by_status[st] = by_status.get(st, 0) + 1
            # 执行中 = 非终态
            terminal = ('completed', 'failed', 'cancelled', 'idle')
            executing = sum(v for k, v in by_status.items() if k not in terminal)
            # 今日完成 / 今日异常：任务历史 DB（精确 SQL，doc/触发机制 §10.3.1；
            # SQL 失败回退遍历 limit=500，避免统计中断）
            today_completed = 0
            failed = 0
            try:
                today = time.strftime('%Y-%m-%d')
                c1 = engine.count_today_completed(today)
                c2 = engine.count_today_failed(today)
                if c1 >= 0 and c2 >= 0:
                    today_completed, failed = c1, c2
                else:
                    # SQL 失败回退：遍历最近 500 条过滤
                    rows = engine.get_all_instances_from_db(limit=500, offset=0) or []
                    for row in rows:
                        status = str(row.get('status', '') or '')
                        created = str(row.get('created_at', '') or '')
                        completed = str(row.get('completed_at', '') or '')
                        if created.startswith(today) or completed.startswith(today):
                            # 兼容 SUCCESS/FAILED（现行）与 completed/failed（历史），doc/60
                            if status in ('SUCCESS', 'completed'):
                                today_completed += 1
                            elif status in ('FAILED', 'failed'):
                                failed += 1
            except Exception:
                pass
            # 已保留占用的目的仓数量（匹对稳定，doc/触发机制 §8.2）
            locked_dest = 0
            try:
                poller = self._get_plugin('status_poller')
                if poller and poller.dest_cache:
                    locked_dest = poller.dest_cache.get_reserved_count()
            except Exception:
                pass
            return {
                'timestamp': time.time(),
                'ready': True,
                'source': 'workflow_engine',
                'last_error': '',
                'by_status': by_status,
                'total': len(active_dict),
                'today_completed': today_completed,
                'executing': executing,
                'failed': failed,
                'locked_dest': locked_dest,
            }
        except Exception as e:
            self.logger.error(f"采集任务统计失败: {e}")
            return dict(empty, ready=False, source='workflow_engine',
                        last_error=str(e))

    def get_task_history(self, limit: int = 50, offset: int = 0) -> dict:
        """采集历史任务"""
        try:
            wf = self._get_plugin('workflow_engine')
            if not wf:
                return {'history': [], 'total': 0}
            engine = wf.get_engine()
            if not engine:
                return {'history': [], 'total': 0}
            rows = engine.get_all_instances_from_db(limit=limit, offset=offset) or []
            history = [{
                'task_id': r.get('task_id', ''),
                'status': r.get('status', ''),
                'current_state': r.get('current_state', ''),
                'src_bay': r.get('src_bay', ''),
                'dst_bay': r.get('dst_bay', ''),
                'created_at': r.get('created_at', ''),
                'completed_at': r.get('completed_at', ''),
            } for r in rows]
            return {'timestamp': time.time(), 'history': history, 'total': len(history)}
        except Exception as e:
            self.logger.error(f"采集历史任务失败: {e}")
            return {'history': [], 'total': 0}

    # ==================== 聚合摘要 ====================

    def collect_business_status(self) -> dict:
        """聚合采集所有业务数据，供 `/api/business/summary` 和 WebSocket 推送"""
        recent_failures = []
        try:
            eb = getattr(self.node, 'event_bridge', None)
            if eb and hasattr(eb, 'get_recent_failures'):
                recent_failures = eb.get_recent_failures() or []
        except Exception:
            pass
        return {
            'timestamp': time.time(),
            'bay': self.get_bay_status(),
            'dest': self.get_dest_status(),
            'agv': self.get_agv_status(),
            'task_queue': self.get_task_queue_data(),
            'active_instances': self.get_active_instances(),
            'recent_failures': recent_failures,   # P1 v5：最近失败任务（异常红色连线）
            'task_stats': self.get_task_statistics(),
        }