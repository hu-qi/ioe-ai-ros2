#!/usr/bin/env python3
"""
任务统计数据源就绪语义化回归测试（doc/58 阶段1 R-01）。

覆盖场景：
  1. workflow_engine 插件未加载 → ready=False + last_error=未加载；
  2. 插件存在但引擎未就绪 → ready=False + last_error=未激活；
  3. 正常数据源 → ready=True 且统计值正确；
  4. 统计异常 → ready=False + last_error 非空。

运行方式（无 ROS2 环境亦可）：
  python test_business_stats_ready.py
  pytest test_business_stats_ready.py
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

# 直接按文件加载 business_collector 模块，绕开 web/__init__.py 的运行库依赖（psutil 等）
import importlib.util
_spec = importlib.util.spec_from_file_location(
    'business_collector',
    str(_PROJECT_ROOT / 'app_mgr_object' / 'components' / 'web' / 'business_collector.py'),
)
_bc_mod = importlib.util.module_from_spec(_spec)
sys.modules['business_collector'] = _bc_mod
_spec.loader.exec_module(_bc_mod)
BusinessCollector = _bc_mod.BusinessCollector


class _Logger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _PluginHost:
    logger = _Logger()


class _PluginMgr:
    def __init__(self, plugins):
        self._plugins = plugins or {}

    def get_plugin(self, name):
        return self._plugins.get(name)


class _Node:
    def __init__(self, plugins):
        self.plugin_manager = _PluginMgr(plugins)


class _EngineStub:
    def __init__(self, active=None, c1=0, c2=0, raise_on_active=False, rows=None):
        self._active = active or {}
        self._c1 = c1
        self._c2 = c2
        self._raise = raise_on_active
        self._rows = rows or []

    def get_active_instances(self):
        if self._raise:
            raise RuntimeError('db down')
        return dict(self._active)

    def count_today_completed(self, day):
        return self._c1

    def count_today_failed(self, day):
        return self._c2

    def get_all_instances_from_db(self, limit=500, offset=0):
        return list(self._rows)


class _DestCacheStub:
    def __init__(self, reserved=0):
        self._reserved = reserved

    def get_reserved_count(self):
        return self._reserved


class _PollerStub:
    def __init__(self, reserved=0):
        self.dest_cache = _DestCacheStub(reserved)


def _make_bc(plugins):
    return BusinessCollector(_Node(plugins), _PluginHost())


def test_stats_ready_false_wf_missing():
    """workflow_engine 插件未加载 → ready=False。"""
    bc = _make_bc({})
    out = bc.get_task_statistics()
    assert out.get('ready') is False, '未加载时应 ready=False'
    assert out.get('last_error') == 'workflow_engine 未加载'
    assert out.get('today_completed') == 0


def test_stats_ready_false_engine_missing():
    """插件存在但引擎未就绪 → ready=False。"""
    class _WfNoEngine:
        def get_engine(self):
            return None
    bc = _make_bc({'workflow_engine': _WfNoEngine()})
    out = bc.get_task_statistics()
    assert out.get('ready') is False
    assert out.get('last_error') == 'workflow_engine 未激活'


def test_stats_ready_true_normal():
    """正常数据源 → ready=True 且统计值正确。"""
    engine = _EngineStub(
        active={'t1': {'status': 'monitoring'}},
        c1=2, c2=1,
    )
    bc = _make_bc({
        'workflow_engine': type('Wf', (), {'get_engine': lambda self: engine})(),
        'status_poller': _PollerStub(reserved=3),
    })
    out = bc.get_task_statistics()
    assert out.get('ready') is True
    assert out.get('today_completed') == 2
    assert out.get('failed') == 1
    assert out.get('executing') == 1        # monitoring 非终态
    assert out.get('total') == 1
    assert out.get('locked_dest') == 3
    assert out.get('last_error') == ''


def test_stats_ready_false_exception():
    """统计过程异常 → ready=False 且 last_error 非空。"""
    engine = _EngineStub(raise_on_active=True)
    bc = _make_bc({
        'workflow_engine': type('Wf', (), {'get_engine': lambda self: engine})(),
    })
    out = bc.get_task_statistics()
    assert out.get('ready') is False
    assert out.get('last_error') != ''


def test_stats_fallback_counts_compat_statuses():
    """SQL 返回 -1 触发回退遍历时，兼容 SUCCESS/completed 与 FAILED/failed（doc/60 P3）。"""
    today = time.strftime('%Y-%m-%d')
    rows = [
        {'status': 'SUCCESS', 'created_at': today + ' 10:00:00', 'completed_at': today + ' 11:00:00'},
        {'status': 'completed', 'created_at': today + ' 09:00:00', 'completed_at': today + ' 12:00:00'},
        {'status': 'FAILED', 'created_at': today + ' 08:00:00', 'completed_at': today + ' 10:30:00'},
        {'status': 'failed', 'created_at': today + ' 07:00:00', 'completed_at': today + ' 09:30:00'},
        {'status': 'RUNNING', 'created_at': today + ' 06:00:00', 'completed_at': ''},
    ]
    engine = _EngineStub(active={}, c1=-1, c2=-1, rows=rows)
    bc = _make_bc({
        'workflow_engine': type('Wf', (), {'get_engine': lambda self: engine})(),
        'status_poller': _PollerStub(reserved=0),
    })
    out = bc.get_task_statistics()
    assert out.get('ready') is True
    assert out.get('today_completed') == 2, '回退应计 SUCCESS+completed'
    assert out.get('failed') == 2, '回退应计 FAILED+failed'


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