#!/usr/bin/env python3
"""
P0 回归测试：批量匹配候选截断不得残留目的仓占用（幽灵锁定）。

覆盖场景（doc/50.app_mgr_object-0.2.0-触发机制全链路分析报告.md R-01）：
  1. batch_scan_all 按 max_tasks 截断后，被丢弃候选的目的仓不残留 reserved；
  2. greedy_scan_type(max_tasks=...) 生成即限流，不产生超出名额的占用；
  3. 容量二次缩水时 TriggerEngine.release_candidates 释放被截断候选；
  4. 显式配对覆盖同样受 max_tasks 约束；
  5. 入队后 remove_by_src 释放目的仓（队列侧既有机制回归）。

运行方式（无 ROS2 环境亦可）：
  python test_trigger_ghost_lock.py
  pytest test_trigger_ghost_lock.py
"""

import sys
import types
from pathlib import Path


def _ensure_rclpy_stub():
    """缺失 rclpy（Windows 开发机）时注入最小桩，保证组件可独立加载。"""
    if 'rclpy' in sys.modules:
        return
    rclpy_mod = types.ModuleType('rclpy')
    logging_mod = types.ModuleType('rclpy.logging')

    class _StubLogger:
        def debug(self, *a, **k):
            pass

        def info(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

    logging_mod.get_logger = lambda *a, **k: _StubLogger()
    rclpy_mod.logging = logging_mod
    sys.modules['rclpy'] = rclpy_mod
    sys.modules['rclpy.logging'] = logging_mod


_ensure_rclpy_stub()

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app_mgr_object.components.trigger.batch_matcher import TaskBatchMatcher
from app_mgr_object.components.task_cache.dest_bay_cache import DestBayCache
from app_mgr_object.components.task_cache.config_cache import ConfigCache
from app_mgr_object.components.task_cache.robot_cache import RobotCache
from app_mgr_object.components.trigger.trigger_engine import TriggerEngine


class _StubLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeBayCache:
    """最小起始仓位缓存桩：只提供 matcher 依赖的查询接口。"""

    def __init__(self, bays):
        self._bays = bays  # bay_id -> {'cargo_type': int, 'bind_time': float}

    def get_bound_bays_of_type(self, cargo_type, exclude_in_task=True):
        return [b for b, s in self._bays.items() if s['cargo_type'] == cargo_type]

    def get_bay_status(self, bay_id):
        return dict(self._bays.get(bay_id, {}))

    def mark_in_task(self, bay_id, value=True, source='task'):
        pass


def _make_env():
    """构造 8 始发仓(type1) × 8 目的仓(type1) 的测试环境。"""
    src_bays = {
        'S%02d' % i: {'cargo_type': 1, 'bind_time': float(i)}
        for i in range(1, 9)
    }
    dst_configs = {
        'T%04d' % (2000 + i): {'cargo_type': 1, 'floor': 2}
        for i in range(1, 9)
    }
    bay_cache = _FakeBayCache(src_bays)
    dest_cache = DestBayCache(bay_configs=dst_configs, logger=_StubLogger())
    matcher = TaskBatchMatcher(
        bay_cache, dest_cache,
        cargo_priority=[1], logger=_StubLogger(),
        pair_overrides={}, pairing_policy=None,
    )
    engine = TriggerEngine(
        bay_cache, dest_cache, RobotCache(robot_ids=[1001]),
        ConfigCache(), logger=_StubLogger(),
    )
    return matcher, dest_cache, engine, bay_cache


def test_batch_truncation_no_ghost_lock():
    """修复核心：截断后被丢弃候选的目的仓不得残留 reserved/占用。"""
    matcher, dc, _, _ = _make_env()
    cands = matcher.batch_scan_all(max_tasks=4)

    assert len(cands) == 4
    kept = {c.dst_bay for c in cands}
    dropped = set(dc.get_all_bay_ids()) - kept
    assert len(dropped) == 4

    for bay in dropped:
        assert not dc.is_reserved(bay), '幽灵锁定残留 reserved: %s' % bay
        assert dc.get_bay_status(bay)['is_empty'] is True, '幽灵锁定残留占用: %s' % bay
    for bay in kept:
        assert dc.is_reserved(bay), '保留候选应维持 matched 占用: %s' % bay


def test_greedy_max_tasks_limits_generation():
    """greedy 生成即限流，不产生超出名额的占用。"""
    matcher, dc, _, _ = _make_env()
    cands = matcher.greedy_scan_type(1, max_tasks=2)

    assert len(cands) == 2
    assert dc.get_reserved_count() == 2


def test_release_candidates_after_capacity_shrink():
    """容量二次缩水（smart_trigger 截断路径）释放被丢弃候选。"""
    matcher, dc, engine, _ = _make_env()
    cands = engine.batch_scan_all(max_tasks=6)

    assert len(cands) == 6
    assert dc.get_reserved_count() == 6

    kept, dropped = cands[:2], cands[2:]
    engine.release_candidates(dropped)

    assert dc.get_reserved_count() == 2
    for c in dropped:
        assert not dc.is_reserved(c.dst_bay)
        assert dc.get_bay_status(c.dst_bay)['is_empty'] is True
    for c in kept:
        assert dc.is_reserved(c.dst_bay)


def test_explicit_override_respects_max():
    """显式配对覆盖同样受 max_tasks 约束，且不产生匹配期占用。"""
    matcher, dc, _, _ = _make_env()
    matcher.set_pair_overrides({
        'S01': 'T2001', 'S02': 'T2002', 'S03': 'T2003',
    })
    cands = matcher.batch_scan_all(max_tasks=2)

    assert len(cands) == 2
    # 显式覆盖候选不入 matched 占用（既有行为），此处断言无残留
    assert dc.get_reserved_count() == 0
    assert all(dc.get_bay_status(c.dst_bay)['is_empty'] is True for c in cands)


def test_enqueue_releases_on_removal():
    """队列侧回归：入队占用 queued，remove_by_src 释放目的仓。"""
    from app_mgr_object.components.trigger.task_queue import TaskQueue

    matcher, dc, engine, bay_cache = _make_env()
    cands = matcher.batch_scan_all(max_tasks=4)
    assert len(cands) == 4

    tq = TaskQueue(
        resource_locker=engine.locker,
        robot_cache=RobotCache(robot_ids=[1001]),
        bay_cache=bay_cache,
        logger=_StubLogger(),
        state_coordinator=None,
        aging_ttl=300.0,
        max_size=50,
        dest_cache=dc,
    )
    tq.enqueue_all(cands, max_total=4)
    assert dc.get_reserved_count() == 4

    first = cands[0]
    tq.remove_by_src(first.src_bay)
    assert dc.get_reserved_count() == 3
    assert not dc.is_reserved(first.dst_bay)
    assert dc.get_bay_status(first.dst_bay)['is_empty'] is True


def main():
    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith('test_') and callable(v)
    ]
    for t in tests:
        t()
        print('PASS %s' % t.__name__)
    print('ALL %d TESTS PASS' % len(tests))


if __name__ == '__main__':
    main()
