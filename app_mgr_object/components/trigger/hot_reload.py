"""
hot_reload - 配置热加载骨架

提供：
- HotReloadRegistry: 热加载注册器
    - register(key, validator, applier): 注册热加载项
    - apply(name, cfg): 应用配置变更
- validate_dict: 校验器，要求值为 dict
- validate_positive_number: 校验器，要求值为正数

骨架实现，使节点能成功启动；具体应用逻辑由调用方 applier 提供。
"""
from typing import Any, Callable, Dict, Optional


def validate_dict(value: Any) -> bool:
    """校验 value 是否为 dict。"""
    return isinstance(value, dict)


def validate_positive_number(value: Any) -> bool:
    """校验 value 是否为正数（int/float）。"""
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


class HotReloadRegistry:
    """配置热加载注册器（骨架）。"""

    def __init__(self, logger=None):
        self.logger = logger
        self._entries: Dict[str, tuple] = {}  # key -> (validator, applier)

    def register(self, section: str, key: str,
                 validator: Callable[[Any], bool],
                 applier: Callable[[Any], Any]) -> None:
        """注册一个热加载项。

        Args:
            section: 配置段名（用于日志分组）
            key: 配置键名
            validator: 校验函数，返回 bool
            applier: 应用函数，接收校验通过的新值
        """
        self.logger = section
        self._entries[key] = (validator, applier)

    def apply(self, name: str, cfg: Any) -> Any:
        """应用配置变更。

        Args:
            name: 配置段名（用于日志）
            cfg: 新配置（dict 或其他）

        Returns:
            应用结果（骨架返回 None）
        """
        if not isinstance(cfg, dict):
            if self.logger:
                self.logger.warning(f"hot_reload [{name}]: 配置非 dict，跳过")
            return None
        applied = 0
        for key, (validator, applier) in self._entries.items():
            if key not in cfg:
                continue
            new_val = cfg[key]
            if not validator(new_val):
                if self.logger:
                    self.logger.warning(
                        f"hot_reload [{name}.{key}]: 校验失败，跳过 (值={new_val!r})")
                continue
            try:
                applier(new_val)
                applied += 1
                if self.logger:
                    self.logger.info(
                        f"hot_reload [{name}.{key}]: 已应用 (值={new_val!r})")
            except Exception as ex:
                if self.logger:
                    self.logger.error(
                        f"hot_reload [{name}.{key}]: 应用失败: {ex}")
        if self.logger:
            self.logger.info(f"hot_reload [{name}]: 应用 {applied} 项")
        return None
