#!/usr/bin/env python3
"""
状态协调器 — 统一资源状态联动更新入口（P1-2）
"""
import threading
import logging

class StateCoordinator:
    def __init__(self, robot_cache, bay_cache, dest_cache, locker,
                 logger: logging.Logger = None):
        self._robot_cache = robot_cache
        self._bay_cache = bay_cache
        self._dest_cache = dest_cache
        self._locker = locker
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._released_task_ids = set()  #已释放任务集合（幂等释放）

    def dispatch_task(self, robot_id: int, src_bay: str, dst_bay: str,
                      task_id: str = '') -> bool:
        with self._lock:
            if not self._locker.lock(robot_id, src_bay, dst_bay):
                self._log_debug(f"dispatch 资源冲突: robot={robot_id} src={src_bay} dst={dst_bay}")
                return False
            # 任务重新下发时清除历史释放记录（支持同 task_id 重试）
            if task_id:
                self._released_task_ids.discard(task_id)
            if src_bay:
                self._bay_cache.mark_in_task(src_bay, True, source='dispatch')
            if robot_id:
                self._robot_cache.set_busy(robot_id, task_id or src_bay,
                                           source='dispatch')
            # 匹对稳定：派发时目的仓保留占用（dispatched，doc/触发机制审查 §3.2）
            if dst_bay and self._dest_cache is not None:
                self._dest_cache.mark_occupied(dst_bay, source='dispatched')
            self._log_info(f"dispatch: robot={robot_id} {src_bay}→{dst_bay} task={task_id}")
            return True

    def release_task(self, task_context: dict, force: bool = False) -> bool:
        """统一资源释放入口（幂等）。

        Args:
            task_context: 任务上下文，需含 robot_id / src_bay / dst_bay / task_id
            force: 为 True 时即使已释放也再次执行（用于人工强制清理）

        Returns:
            True  — 本次实际执行了释放
            False — 已释放过（幂等跳过）或未做任何释放
        """
        with self._lock:
            task_id = task_context.get('task_id') or task_context.get('task_code')
            if not task_id:
                # 无 task_id 无法幂等：保持旧行为直接释放
                self._log_warning("release_task: 缺少 task_id，按非幂等方式释放")
                return self._release_task_impl(task_context)

            if task_id in self._released_task_ids and not force:
                self._log_debug(f"任务 {task_id} 已释放，跳过重复释放")
                return False

            ok = self._release_task_impl(task_context)
            if ok:
                self._released_task_ids.add(task_id)
            return ok
        
    def _release_task_impl(self, task_context: dict) -> bool:
        robot_id = task_context.get('robot_id')
        src_bay = task_context.get('src_bay')
        dst_bay = task_context.get('dst_bay')

        self._locker.release(robot_id=robot_id, src_bay=src_bay, dst_bay=dst_bay)
        if src_bay:
            self._bay_cache.mark_in_task(src_bay, False, source='release')
        if robot_id:
            self._robot_cache.set_idle(robot_id, source='release')
        if dst_bay and self._dest_cache is not None:
            # 匹对稳定：释放保留占用（doc/触发机制审查 §3.2）。
            # 任务完成（货物到位）→ 保留 is_empty=False 由 RCS 接管；失败/取消 → 回空。
            task_status = (task_context.get('status') or '').lower()
            set_empty = task_status in ('failed', 'cancelled', 'canceled', 'aborted', 'error')
            self._dest_cache.release_occupied(dst_bay, set_empty=set_empty)
            if not set_empty:
                self._dest_cache.update(dst_bay, is_empty=False, source='task_complete')

        self._log_info(
            f"release: task={task_context.get('task_id')} "
            f"robot={robot_id} {src_bay}→{dst_bay}"
        )
        return True
    
    def get_released_task_ids(self) -> set:
        with self._lock:
            return set(self._released_task_ids)

    def reset_release_state(self):
        """人工清理/测试用：清空全部释放记录（不释放资源）"""
        with self._lock:
            self._released_task_ids.clear()

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                'locked': self._locker.get_locked_count(),
                'robots': self._robot_cache.get_all_robot_status(),
                'src_bays': self._bay_cache.get_all_bay_status(),
                'dst_bays': self._dest_cache.get_all_bay_status(),
            }

    def _log_info(self, msg: str):
        if self._logger:
            self._logger.info(f"[StateCoordinator] {msg}")

    def _log_debug(self, msg: str):
        if self._logger:
            self._logger.debug(f"[StateCoordinator] {msg}")