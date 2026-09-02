#!/usr/bin/env python3
"""
YAML 配置化改造回归测试（doc/52 阶段5）。

覆盖场景：
  1. TriggerEngine 启动注入（config 参数）——cargo_priority/pair_overrides/
     src_scan_order/max_tasks_per_scan 来自 YAML 配置（R-01 修复）；
  2. 始发扫描顺序（by_bay_id_asc / by_bind_time_desc / custom）；
  3. AGV 选择策略（round_robin / least_busy / specified + available_statuses）；
  4. TaskQueue 热更新接口（set_aging_ttl / set_max_size）；
  5. HotReloadRegistry 校验/应用/拒绝。

运行方式（无 ROS2 环境亦可）：
  python test_trigger_yaml_config.py
  pytest test_trigger_yaml_config.py
"""

import sys
import time
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
from app_mgr_object.components.trigger.task_queue import TaskQueue
from app_mgr_object.components.trigger.hot_reload import (
    HotReloadRegistry, validate_dict, validate_positive_number,
)


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
    robot_cache = RobotCache(robot_ids=[1001], logger=_StubLogger())
    matcher = TaskBatchMatcher(
        bay_cache, dest_cache,
        cargo_priority=[1], logger=_StubLogger(),
        pair_overrides={}, pairing_policy=None,
    )
    engine = TriggerEngine(
        bay_cache, dest_cache, robot_cache,
        ConfigCache(), logger=_StubLogger(),
    )
    return matcher, dest_cache, engine, bay_cache


# ────────────────────────────────────────────────────────────
#  1. 启动注入（R-01 修复）
# ────────────────────────────────────────────────────────────

def test_engine_startup_injection():
    """TriggerEngine 直接接收插件 YAML 配置，启动即生效（不依赖 ConfigCache）。"""
    src_bays = {
        'A1001': {'cargo_type': 3, 'bind_time': 1.0},
        'B1001': {'cargo_type': 1, 'bind_time': 2.0},
    }
    dst_configs = {
        'T2001': {'cargo_type': 1, 'floor': 2},
        'T2002': {'cargo_type': 3, 'floor': 2},
    }
    engine = TriggerEngine(
        _FakeBayCache(src_bays),
        DestBayCache(bay_configs=dst_configs, logger=_StubLogger()),
        RobotCache(robot_ids=[1001], logger=_StubLogger()),
        ConfigCache(),
        config={
            'cargo_priority': [3, 1],
            'max_tasks_per_scan': 4,
            'pair_overrides': {'A1001': 'T2002'},
            'src_scan_order': {'mode': 'custom', 'custom': ['B1001', 'A1001']},
        },
        logger=_StubLogger(),
    )
    assert engine._cargo_priority == [3, 1], 'cargo_priority 未从 config 注入'
    assert engine._max_tasks_per_scan == 4, 'max_tasks_per_scan 未从 config 注入'
    assert engine._batch_matcher._pair_overrides == {'A1001': 'T2002'}, \
        'pair_overrides 未从 config 注入'
    assert engine._batch_matcher._src_scan_order_mode == 'custom', \
        'src_scan_order 未从 config 注入'


# ────────────────────────────────────────────────────────────
#  2. 始发扫描顺序
# ────────────────────────────────────────────────────────────

def _reset_dest(dc):
    """释放全部目的仓占用（同批测试间隔离）"""
    for bay in dc.get_all_bay_ids():
        dc.release_occupied(bay, set_empty=True)


def test_matcher_src_scan_order_modes():
    """by_bay_id_asc（现状）与 by_bind_time_desc 的始发匹对顺序。"""
    matcher, dc, _, _ = _make_env()

    # 现状：bay_id 升序
    _reset_dest(dc)
    matcher.set_src_scan_order({'mode': 'by_bay_id_asc'})
    cands_asc = matcher.greedy_scan_type(1, max_tasks=3)
    assert cands_asc[0].src_bay == 'S01', 'by_bay_id_asc 应先 S01'

    # 绑定时间新者优先（bind_time=S08 最大）
    _reset_dest(dc)
    matcher.set_src_scan_order({'mode': 'by_bind_time_desc'})
    cands_desc = matcher.greedy_scan_type(1, max_tasks=3)
    assert cands_desc[0].src_bay == 'S08', 'by_bind_time_desc 应先 S08'

    # custom：显式顺序 + 未列出仓位按 bay_id 追加
    _reset_dest(dc)
    matcher.set_src_scan_order({'mode': 'custom', 'custom': ['S05', 'S01']})
    cands_custom = matcher.greedy_scan_type(1, max_tasks=3)
    assert [c.src_bay for c in cands_custom] == ['S05', 'S01', 'S02'], \
        'custom 顺序错误: %s' % [c.src_bay for c in cands_custom]


# ────────────────────────────────────────────────────────────
#  3. AGV 选择策略
# ────────────────────────────────────────────────────────────

def test_robot_select_policies():
    """round_robin / specified / least_busy / available_statuses。"""
    rc = RobotCache(robot_ids=[1001, 1002], logger=_StubLogger())
    rc.update_status(1001, 'AVAILABLE')
    rc.update_status(1002, 'AVAILABLE')

    # round_robin（默认）：交替
    rc.set_select_policy(strategy='round_robin')
    first = rc.get_available_robot()
    second = rc.get_available_robot()
    assert (first, second) in ((1001, 1002), (1002, 1001)), \
        'round_robin 应交替选择，实际 %s/%s' % (first, second)

    # specified
    rc.set_select_policy(strategy='specified', specified_ids=[1002])
    assert rc.get_available_robot() == 1002

    # least_busy：update_time 最小（空闲最早）
    rc._robots[1001].update_time = 100.0
    rc._robots[1002].update_time = 200.0
    rc.set_select_policy(strategy='least_busy')
    assert rc.get_available_robot() == 1001

    # available_statuses：仅 AVAILABLE 可选时 BUSY 不参与
    rc.update_status(1001, 'BUSY')
    rc.update_status(1002, 'AVAILABLE')
    rc._next_index = 0
    rc.set_select_policy(strategy='round_robin', available_statuses=['AVAILABLE'])
    assert rc.get_available_robot() == 1002


# ────────────────────────────────────────────────────────────
#  4. TaskQueue 热更新
# ────────────────────────────────────────────────────────────

def test_task_queue_hot_setters():
    """set_max_size / set_aging_ttl 运行期生效。"""
    matcher, dc, engine, bay_cache = _make_env()
    cands = matcher.batch_scan_all(max_tasks=4)
    assert len(cands) == 4

    tq = TaskQueue(
        resource_locker=engine.locker,
        robot_cache=RobotCache(robot_ids=[1001], logger=_StubLogger()),
        bay_cache=bay_cache,
        logger=_StubLogger(),
        state_coordinator=None,
        aging_ttl=300.0,
        max_size=50,
        dest_cache=dc,
    )
    # max_size 热更新：容量 1，超限候选释放目的仓占用
    tq.set_max_size(1)
    added = tq.enqueue_all(cands, max_total=None)
    assert added == 1 and tq.size() == 1, 'set_max_size 后应只入队 1 个'
    assert dc.get_reserved_count() == 1, '超限候选应释放目的仓占用'

    # aging_ttl 热更新：极短 TTL 使队列老化
    tq.set_aging_ttl(0.01)
    time.sleep(0.03)
    tq.age_out()
    assert tq.size() == 0, 'set_aging_ttl 后应老化移除'
    assert dc.get_reserved_count() == 0, '老化移除应释放目的仓占用'


# ────────────────────────────────────────────────────────────
#  5. HotReloadRegistry
# ────────────────────────────────────────────────────────────

def test_hot_reload_registry():
    """注册表：合法值应用、非法值拒绝且不影响原值。"""
    applied = []
    reg = HotReloadRegistry(logger=_StubLogger())
    reg.register('smart_trigger', 'aging_ttl',
                 validate_positive_number, lambda v: applied.append(v))
    reg.register('smart_trigger', 'agv',
                 validate_dict, lambda v: applied.append(v))

    res = reg.apply('smart_trigger', {'aging_ttl': 10.0, 'agv': {'select_strategy': 'round_robin'}})
    assert res['applied'] == ['aging_ttl', 'agv'], '合法值应全部应用'
    assert applied == [10.0, {'select_strategy': 'round_robin'}]

    applied.clear()
    res2 = reg.apply('smart_trigger', {'aging_ttl': -1, 'agv': 'bad'})
    assert len(res2['applied']) == 0, '非法值不应应用'
    assert len(res2['rejected']) == 2, '非法值应全部拒绝'
    assert applied == [], '非法值不得触发 apply'


class _FakeBayWithBind:
    """带 bind_status 的起始仓位桩（doc/54 阶段2 测试用）"""

    def __init__(self, bays):
        self._bays = bays  # bay_id -> {cargo_type, bind_time, bind_status}

    def get_bound_bays_of_type(self, cargo_type, exclude_in_task=True):
        return [b for b, s in self._bays.items()
                if s['cargo_type'] == cargo_type and s.get('bind_status') == 1]

    def get_bay_status(self, bay_id):
        return dict(self._bays.get(bay_id, {}))

    def mark_in_task(self, bay_id, value=True, source='task'):
        pass

    def set_unbound(self, bay_id):
        if bay_id in self._bays:
            self._bays[bay_id]['bind_status'] = 0


def test_remove_by_src_clears_queued_dst_and_rematch():
    """核心修复（doc/54 阶段1）：解绑移出后目的仓可被同类型新始发仓再次匹配（蓝变橙）。"""
    src_bays = {
        'S01': {'cargo_type': 1, 'bind_time': 1.0, 'bind_status': 1},
        'S02': {'cargo_type': 1, 'bind_time': 2.0, 'bind_status': 1},
    }
    bay = _FakeBayWithBind(src_bays)
    dc = DestBayCache({'T2001': {'cargo_type': 1, 'floor': 2}}, logger=_StubLogger())
    rc = RobotCache(robot_ids=[1001], logger=_StubLogger())
    eng = TriggerEngine(bay, dc, rc, None,
                        config={'max_tasks_per_scan': 4}, logger=_StubLogger())
    matcher = eng._batch_matcher

    cands = matcher.batch_scan_all(max_tasks=2)
    assert [(c.src_bay, c.dst_bay) for c in cands] == [('S01', 'T2001')]

    tq = TaskQueue(resource_locker=eng.locker, robot_cache=rc, bay_cache=bay,
                   logger=_StubLogger(), aging_ttl=300.0, max_size=50, dest_cache=dc)
    tq.enqueue_all(cands, max_total=4)

    # 人工移走初始仓货物 → 解绑 → 队列移除
    bay.set_unbound('S01')
    tq.remove_by_src('S01')
    assert 'T2001' not in tq.get_queued_sets()[1], 'queued_dst 必须清除残留'
    assert dc.get_bay_state('T2001') == 'unbind', '释放后应显示蓝色'
    assert dc.get_bay_status('T2001')['is_empty'] is True, '释放后应回空'

    # 同类型新货上料（S02 已绑定）→ 立即重新匹对成功
    qs, qd = tq.get_queued_sets()
    rematch = matcher.batch_scan_all(max_tasks=2, exclude_src=qs, exclude_dst=qd)
    assert [(c.src_bay, c.dst_bay) for c in rematch] == [('S02', 'T2001')], rematch
    # 蓝变橙：重新匹对后 mark_occupied 清除 unbind 标记
    assert dc.get_bay_state('T2001') == 'reserved', '重新匹对后应变为橙色 reserved'


def test_remove_by_src_releases_src_lock():
    """阶段3 防御（doc/54 N-2）：remove_by_src 幂等释放始发仓锁。"""
    bay = _FakeBayWithBind(
        {'S01': {'cargo_type': 1, 'bind_time': 1.0, 'bind_status': 1}})
    dc = DestBayCache({'T2001': {'cargo_type': 1, 'floor': 2}}, logger=_StubLogger())
    rc = RobotCache(robot_ids=[1001], logger=_StubLogger())
    eng = TriggerEngine(bay, dc, rc, None, config={}, logger=_StubLogger())
    tq = TaskQueue(resource_locker=eng.locker, robot_cache=rc, bay_cache=bay,
                   logger=_StubLogger(), dest_cache=dc)
    cands = eng._batch_matcher.batch_scan_all(max_tasks=1)
    tq.enqueue_all(cands, max_total=4)
    tq.remove_by_src('S01')
    assert not eng.locker.is_src_locked('S01'), 'remove_by_src 后始发仓锁应释放（幂等）'


def test_try_dequeue_purges_unbound_src():
    """阶段3 防御（doc/54 N-1）：bay.unbound 事件丢失时，出队前清理未绑定始发仓候选。"""
    bay = _FakeBayWithBind(
        {'S01': {'cargo_type': 1, 'bind_time': 1.0, 'bind_status': 1}})
    dc = DestBayCache({'T2001': {'cargo_type': 1, 'floor': 2}}, logger=_StubLogger())
    rc = RobotCache(robot_ids=[1001], logger=_StubLogger())
    rc.update_status(1001, 'AVAILABLE')
    eng = TriggerEngine(bay, dc, rc, None, config={}, logger=_StubLogger())
    tq = TaskQueue(resource_locker=eng.locker, robot_cache=rc, bay_cache=bay,
                   logger=_StubLogger(), dest_cache=dc)
    cands = eng._batch_matcher.batch_scan_all(max_tasks=1)
    tq.enqueue_all(cands, max_total=4)
    assert tq.size() == 1

    bay.set_unbound('S01')   # 模拟事件丢失：不调用 remove_by_src
    out = tq.try_dequeue()
    assert out is None, '未绑定始发仓候选不得派发'
    assert tq.size() == 0, '失效候选应被清理'
    assert 'T2001' not in tq.get_queued_sets()[1], 'queued_dst 应同步清理'
    assert dc.get_bay_status('T2001')['is_empty'] is True, '目的仓应回空'
    assert tq.get_stats()['skip_unbound_count'] == 1


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
