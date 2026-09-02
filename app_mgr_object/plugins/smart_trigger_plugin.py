#!/usr/bin/env python3
"""
smart_trigger_plugin — 智能触发器插件骨架

按 plugins/__init__.py 第 19 行要求提供 SmartTriggerPlugin 类。
骨架实现：继承 BasePlugin，复用默认生命周期方法，使节点能成功 import 与启动。
具体触发匹配逻辑可后续补全（参考 doc/21_smart_trigger_v1.md 等文档）。
"""
from typing import Dict, Any, Optional

from .base_plugin import BasePlugin


class SmartTriggerPlugin(BasePlugin):
    """智能触发器插件（骨架）。"""

    PLUGIN_NAME = "smart_trigger"
    PLUGIN_VERSION = "0.1.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        self._trigger_rules: list = []
        self._trigger_queue: list = []

    def _configure_impl(self) -> bool:
        # 从配置加载触发规则（骨架：仅记录）
        rules = self.config.get('triggers', [])
        if isinstance(rules, list):
            self._trigger_rules = rules
        self.logger.info(
            f"smart_trigger 配置完成: {len(self._trigger_rules)} 条触发规则")
        return True

    def _activate_impl(self) -> bool:
        self.logger.info("smart_trigger 激活（骨架，无实际匹配）")
        return True

    def _deactivate_impl(self) -> bool:
        self._trigger_queue.clear()
        self.logger.info("smart_trigger 停用")
        return True

    def _cleanup_impl(self) -> bool:
        self._trigger_rules.clear()
        self._trigger_queue.clear()
        return True

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            'trigger_rules': len(self._trigger_rules),
            'pending_triggers': len(self._trigger_queue),
        })
        return base
