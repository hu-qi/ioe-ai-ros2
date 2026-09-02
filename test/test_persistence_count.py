#!/usr/bin/env python3
"""
任务统计状态值兼容回归测试（doc/60 P1）。

覆盖场景：
  1. count_by_date 状态集合：今日 SUCCESS（兼容历史 completed）；
  2. count_by_date 状态集合：今日 FAILED（兼容历史 failed）；
  3. 昨日记录不计入；
  4. 单值字符串调用仍兼容；
  5. 非法 date_field 返回 -1；空集合返回 0。

运行方式（无 ROS2 环境亦可）：
  python test_persistence_count.py
  pytest test_persistence_count.py
"""

import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path


def _ensure_rclpy_stub():
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

from app_mgr_object.components.workflow.persistence import (
    WorkflowPersistence,
    STATUS_COMPLETED_SET,
    STATUS_FAILED_SET,
)


def _today():
    return time.strftime('%Y-%m-%d')


def _insert(conn, task_id, status, completed_at, created_at, cargo_type=1):
    conn.execute(
        "INSERT INTO task_instances "
        "(task_id, status, created_at, completed_at, cargo_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, status, created_at, completed_at, cargo_type),
    )


def _make_db():
    """构造混合状态数据：今日 SUCCESS×2 + completed×1 + FAILED×2 + failed×1 + RUNNING×1；昨日 SUCCESS×1。"""
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows 文件句柄容错
    db = os.path.join(tmp.name, 't.db')
    p = WorkflowPersistence(db, logger=None)
    today = _today()
    with sqlite3.connect(db) as conn:
        _insert(conn, 't1', 'SUCCESS', today + ' 10:00:00', today + ' 09:00:00')
        _insert(conn, 't2', 'SUCCESS', today + ' 11:00:00', today + ' 10:00:00')
        _insert(conn, 't3', 'completed', today + ' 12:00:00', today + ' 11:00:00')  # 历史写法
        _insert(conn, 't4', 'FAILED', today + ' 13:00:00', today + ' 12:00:00')
        _insert(conn, 't5', 'FAILED', today + ' 14:00:00', today + ' 13:00:00')
        _insert(conn, 't6', 'failed', today + ' 15:00:00', today + ' 14:00:00')    # 历史写法
        _insert(conn, 't7', 'RUNNING', None, today + ' 15:00:00')
        _insert(conn, 't8', 'SUCCESS', '2000-01-01 10:00:00', '2000-01-01 09:00:00')  # 昨日（非今日）
    return p, tmp


def test_count_today_completed_compat_set():
    """今日完成 = SUCCESS/completed 集合计数（3 条）。"""
    p, tmp = _make_db()
    try:
        assert p.count_by_date(STATUS_COMPLETED_SET, 'completed_at', _today()) == 3
    finally:
        tmp.cleanup()


def test_count_today_failed_compat_set():
    """今日失败 = FAILED/failed 集合计数（3 条）。"""
    p, tmp = _make_db()
    try:
        assert p.count_by_date(STATUS_FAILED_SET, 'completed_at', _today()) == 3
    finally:
        tmp.cleanup()


def test_yesterday_not_counted():
    """非今日记录不计入。"""
    p, tmp = _make_db()
    try:
        assert p.count_by_date(STATUS_COMPLETED_SET, 'completed_at', _today()) == 3
        assert p.count_by_date(STATUS_COMPLETED_SET, 'completed_at', '2000-01-01') == 1
    finally:
        tmp.cleanup()


def test_single_string_still_supported():
    """单值字符串调用仍兼容（旧调用语义）。"""
    p, tmp = _make_db()
    try:
        assert p.count_by_date('SUCCESS', 'completed_at', _today()) == 2
        assert p.count_by_date('completed', 'completed_at', _today()) == 1
    finally:
        tmp.cleanup()


def test_invalid_field_and_empty_set():
    """非法日期字段返回 -1；空集合返回 0。"""
    p, tmp = _make_db()
    try:
        assert p.count_by_date(STATUS_COMPLETED_SET, 'hack', _today()) == -1
        assert p.count_by_date((), 'completed_at', _today()) == 0
    finally:
        tmp.cleanup()


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