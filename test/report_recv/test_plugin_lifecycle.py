"""
插件层 ReportRecvPlugin 生命周期验证

覆盖 doc/70 §5.1 插件类结构：
  - 插件实例化 & 配置成功（_configure_impl）
  - 插件激活成功（_activate_impl）
  - 插件停用成功（_deactivate_impl）
  - 插件清理成功（_cleanup_impl）

不依赖 ROS2 节点（用 stub node）。
"""

import os

from conftest import DB, RAW_DIR, EVID_DIR, StubLogger
from app_mgr_object.components.web.report_recv_plugin import ReportRecvPlugin


class StubNode:
    """ROS2 节点 stub，插件初始化不依赖真实 ROS2"""
    def get_logger(self):
        return StubLogger()


def _make_plugin():
    return ReportRecvPlugin(
        StubNode(),
        config={
            "db_path": DB,
            "raw_json_dir": RAW_DIR,
            "evidence_dir": EVID_DIR,
        }
    )


def test_plugin_configure():
    """插件配置成功"""
    plugin = _make_plugin()
    ok = plugin.configure()
    assert ok is True, "插件 configure 应返回 True"
    assert plugin._repo is not None, "_repo 应已初始化"
    assert plugin._merger is not None, "_merger 应已初始化"


def test_plugin_activate():
    """插件激活成功"""
    plugin = _make_plugin()
    plugin.configure()
    ok = plugin.activate()
    assert ok is True, "插件 activate 应返回 True"


def test_plugin_deactivate():
    """插件停用成功"""
    plugin = _make_plugin()
    plugin.configure()
    plugin.activate()
    ok = plugin.deactivate()
    assert ok is True, "插件 deactivate 应返回 True"


def test_plugin_cleanup():
    """插件清理成功"""
    plugin = _make_plugin()
    plugin.configure()
    plugin.activate()
    plugin.deactivate()
    ok = plugin.cleanup()
    assert ok is True, "插件 cleanup 应返回 True"


def test_plugin_config_passthrough():
    """配置透传：yaml 里的 db_path/raw_json_dir/evidence_dir 必须生效

    回归 doc/70 §5.5：web_monitor_plugin._web_server_config 曾漏透传
    report_recv 段，导致 yaml 定制静默回落到代码默认路径。
    本测试直接构造插件 config（模拟 _web_server_config['report_recv']），
    验证三个路径键都被插件读取并使用。
    """
    custom_db = os.path.join(os.path.dirname(DB), "custom_app.db")
    plugin = ReportRecvPlugin(
        StubNode(),
        config={
            "db_path": custom_db,
            "raw_json_dir": RAW_DIR,
            "evidence_dir": EVID_DIR,
        }
    )
    plugin.configure()
    assert plugin._db_path == custom_db, "db_path 透传失败"
    assert plugin._raw_json_dir == RAW_DIR, "raw_json_dir 透传失败"
    assert plugin._evidence_dir == EVID_DIR, "evidence_dir 透传失败"
    # 验证 schema 建在定制 db_path 上
    assert os.path.exists(custom_db), "定制 db_path 未被使用"
