#!/usr/bin/env python3
"""
参数管理器 - 独立YAML文件模式
支持将 plugin_configs 和 web_monitor 拆分为独立文件，实现原子热加载。
"""

import json
import yaml
import os
import shutil
import threading
import copy
from typing import Dict, List, Any, Optional, Callable

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy
from rcl_interfaces.msg import ParameterDescriptor, ParameterType


class ParamManager:
    """参数管理器（独立YAML文件模式）

    启动流程：
        1. 声明ROS2简单参数（包括 plugin_configs_dir / web_monitor_config 路径）
        2. 从 plugin_configs_dir 目录加载所有插件独立YAML，汇集成 _params['plugin_configs']
        3. 从 web_monitor_config 文件加载 Web 监控配置到 _params['web_monitor']
        4. 注册参数变更回调，支持热加载时触发插件刷新

    热加载流程（以更新 bay_configs 为例）：
        update_plugin_config_nested(['bay_status_fusion', 'bay_configs'], new_value)
            → 定位 config/plugin_configs/bay_status_fusion.yaml
            → 读取 → 修改 → 原子写入（_write_yaml_atomic）
            → 更新内存 _params['plugin_configs']['bay_status_fusion']
            → 触发 ROS2 参数回调（若有注册）和 EventBus 广播
    """

    def __init__(self, node: Node):
        self.node = node
        self.logger = node.get_logger()
        self._params = {}
        self._param_callbacks = {}

        # 文件写入锁（防止并发写）
        self._yaml_lock = threading.Lock()
        # 写版本计数器（调试用）
        self._write_version = 0
        # 缓存包共享目录路径
        self._pkg_share = None

        # Step 1: 声明 ROS2 参数（新参数 plugin_configs_dir / web_monitor_config）
        self._declare_common_parameters()

        # Step 2: 从独立 YAML 文件加载配置
        self._load_external_configs()

        # Step 3: 注册参数变更回调
        self._setup_param_callback()

        self.logger.info("参数管理器初始化完成（独立文件模式）")

    # ==================== 参数声明 ====================

    def _declare_common_parameters(self):
        """声明通用参数（独立文件模式）"""
        common_params = [
            ('dry_run', False),
            ('log_level', 'info'),
            ('operation_mode', 'development'),
            ('ros_network_interface', 'eth0'),
            ('api_network_interface', 'eth0'),
            ('person_change_stable_time', 10.0),
            ('state_change_offset', 5.0),
            ('state_change_stable_time', 15.0),
            ('callback_host', '0.0.0.0'),
            ('callback_port', 8080),
            ('callback_base_path', '/api/callback'),
            ('enable_signature', False),
            ('network_timeout', 30.0),
            ('network_retries', 3),
            ('network_backoff_factor', 0.5),
            ('request_worker_count', 4),
            ('request_max_queue_size', 1000),
            ('request_enable_priority', True),
            ('request_retry_count', 3),
            ('request_default_priority', 2),
            ('enable_status_filter', True),
            ('filter_update_interval', 3.0),
            ('topic_qos_depth', 10),
            ('topic_qos_reliability', 'reliable'),
            ('topic_qos_durability', 'volatile'),
            ('max_queue_size', 1000),
            ('retry_delay', 1.0),
            ('status_report_interval', 300),
            ('plugin_auto_start', True),
            ('plugin_configs_dir', 'config/plugin_configs'),
            ('web_monitor_config', 'config/web_monitor.yaml'),
            ('plugin_load_order', ''),   # 改为字符串，默认空
        ]

        for name, default in common_params:
            try:
                self.node.declare_parameter(name, default)
                param_value = self.node.get_parameter(name).value

                # 特殊处理 plugin_load_order：解析逗号分隔的字符串
                if name == 'plugin_load_order':
                    if isinstance(param_value, str) and param_value.strip():
                        # 按逗号分割，去除两边空格，过滤空字符串
                        load_order_list = [item.strip() for item in param_value.split(',') if item.strip()]
                        self._params[name] = load_order_list
                    else:
                        self._params[name] = []
                    continue

                # 其他字符串尝试 JSON/YAML 解析
                if isinstance(param_value, str) and param_value.strip():
                    try:
                        param_value = json.loads(param_value)
                    except json.JSONDecodeError:
                        try:
                            param_value = yaml.safe_load(param_value)
                        except yaml.YAMLError:
                            pass
                self._params[name] = param_value
            except Exception as e:
                self.logger.warning(f"声明参数 {name} 失败: {e}")
                self._params[name] = default

        # 确保 plugin_load_order 始终是列表
        if not isinstance(self._params.get('plugin_load_order'), list):
            self._params['plugin_load_order'] = []

    # ==================== 外部配置加载 ====================

    def _load_external_configs(self):
        """从独立 YAML 文件加载 plugin_configs 和 web_monitor"""
        pkg_share = self._get_pkg_share_dir()

        # 1. 加载 plugin_configs（目录模式）
        configs_dir_rel = self.get_param('plugin_configs_dir', 'config/plugin_configs')
        if not os.path.isabs(configs_dir_rel):
            configs_dir_rel = os.path.join(pkg_share, configs_dir_rel)
        plugin_configs = self._load_plugin_configs_from_dir(configs_dir_rel)
        if plugin_configs:
            self._params['plugin_configs'] = plugin_configs
            self.logger.info(f"plugin_configs 加载完成: {list(plugin_configs.keys())}")
        else:
            self.logger.warning("plugin_configs 为空，请检查 plugin_configs_dir 配置")
            self._params['plugin_configs'] = {}

        # 2. 加载 web_monitor（单文件模式）
        web_monitor_path = self.get_param('web_monitor_config', 'config/web_monitor.yaml')
        web_monitor = self._load_config_from_file(web_monitor_path)
        if web_monitor:
            self._params['web_monitor'] = web_monitor
            self.logger.info(f"web_monitor 配置加载完成: {len(web_monitor)} 项")
        else:
            self._params['web_monitor'] = {}

    def _load_plugin_configs_from_dir(self, configs_dir: str) -> dict:
        """从独立 YAML 目录加载所有插件配置，汇编为 plugin_configs dict。

        目录结构：
            config/plugin_configs/
                network.yaml            → plugin_configs['network']
                callback_handler.yaml   → plugin_configs['callback_handler']
                ...

        Returns:
            dict: 合并后的 plugin_configs（key = 文件名去 .yaml）
        """
        plugin_configs = {}

        if not os.path.isdir(configs_dir):
            self.logger.warning(f"插件配置目录不存在: {configs_dir}")
            return plugin_configs

        for entry in sorted(os.listdir(configs_dir)):
            if not entry.endswith('.yaml'):
                continue
            filepath = os.path.join(configs_dir, entry)
            plugin_name = entry[:-5]  # 去掉 .yaml 后缀
            try:
                config = self._read_yaml(filepath)
                if not isinstance(config, dict):
                    self.logger.warning(f"插件配置文件不是字典: {filepath}")
                    continue
                plugin_configs[plugin_name] = config
                self.logger.debug(f"已加载插件配置: {plugin_name} ({len(config)} 项)")
            except Exception as e:
                self.logger.error(f"加载插件配置失败 [{filepath}]: {e}")

        self.logger.info(f"从目录加载了 {len(plugin_configs)} 个插件配置")
        return plugin_configs

    def _load_config_from_file(self, filepath: str) -> dict:
        """从单个 YAML 文件加载配置（用于 web_monitor 等独立文件）。

        Args:
            filepath: YAML 文件路径（绝对路径或相对于包共享目录）

        Returns:
            dict: 解析后的配置字典，若文件不存在或格式错误则返回空字典
        """
        if not os.path.isabs(filepath):
            filepath = os.path.join(self._get_pkg_share_dir(), filepath)

        if not os.path.isfile(filepath):
            self.logger.warning(f"配置文件不存在: {filepath}，使用空配置")
            return {}

        try:
            config = self._read_yaml(filepath)
            if not isinstance(config, dict):
                self.logger.warning(f"配置文件不是字典: {filepath}")
                return {}
            self.logger.info(f"已加载配置: {filepath} ({len(config)} 项)")
            return config
        except Exception as e:
            self.logger.error(f"加载配置失败 [{filepath}]: {e}")
            return {}

    def _get_pkg_share_dir(self) -> str:
        """获取包共享目录（即 config/ 的父目录）"""
        if self._pkg_share:
            return self._pkg_share
        try:
            from ament_index_python.packages import get_package_share_directory
            self._pkg_share = get_package_share_directory('app_mgr_object')
        except Exception:
            self._pkg_share = os.getcwd()
        return self._pkg_share

    # ==================== 参数回调 ====================

    def _setup_param_callback(self):
        try:
            self.node.add_on_set_parameters_callback(self._on_parameters_changed)
        except Exception as e:
            self.logger.warning(f"设置参数回调失败: {e}")

    def _on_parameters_changed(self, params: List[rclpy.Parameter]):
        for param in params:
            name = param.name
            value = param.value
            if isinstance(value, str) and value.startswith(('{', '[')):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            self._params[name] = value

            # 分发参数变更回调
            cb = self._param_callbacks.get(name)
            if cb:
                try:
                    cb(name, value)
                except Exception as e:
                    self.logger.error(f"参数回调执行失败 {name}: {e}")

        return rclpy.SetParametersResult(successful=True)

    # ---------- 参数获取与更新 ----------
    def register_param_callback(self, param_name: str, callback: Callable):
        self._param_callbacks[param_name] = callback

    def get_param(self, name: str, default: Any = None) -> Any:
        if name in self._params:
            return self._params.get(name, default)
        try:
            param_value = self.node.get_parameter(name).value
            if isinstance(param_value, str) and param_value.startswith(('{', '[')):
                try:
                    param_value = json.loads(param_value)
                except json.JSONDecodeError:
                    pass
            self._params[name] = param_value
            return param_value
        except Exception:
            self._params[name] = default
            return default

    def get_all_params(self) -> Dict[str, Any]:
        return self._params.copy()

    def update_param(self, name: str, value: Any) -> bool:
        try:
            param = rclpy.Parameter(name, value=value)
            self.node.set_parameters([param])
            return True
        except Exception as e:
            self.logger.error(f"更新参数 {name} 失败: {e}")
            return False

    # ==================== 配置热加载（核心） ====================

    def update_plugin_config_nested(self, path: list, value: Any) -> bool:
        """更新 plugin_configs 中嵌套路径的值，并原子持久化到对应的独立 YAML 文件。

        映射规则：
            path[0] = 插件名 → 对应 config/plugin_configs/<plugin_name>.yaml

        Args:
            path: 键路径，如 ['bay_status_fusion', 'bay_configs']
                  或 ['smart_trigger', 'work_schedule', 'schedules', 0, 'start_time']
            value: 新值（可嵌套 dict/list/原子值）

        Returns:
            True 表示写入成功且内存更新完成，否则 False
        """
        if not path:
            self.logger.error("update_plugin_config_nested: path 不能为空")
            return False

        plugin_name = path[0]

        try:
            # 1. 定位独立 YAML 文件
            yaml_file = self._get_plugin_config_file(plugin_name)
            if not yaml_file or not os.path.isfile(yaml_file):
                self.logger.error(f"找不到插件配置文件: {plugin_name} (路径: {yaml_file})")
                return False

            # 2. 读取当前文件内容
            plugin_config = self._read_yaml(yaml_file)
            if not isinstance(plugin_config, dict):
                self.logger.error(f"插件配置 YAML 格式异常: {yaml_file}")
                return False

            plugin_config = copy.deepcopy(plugin_config)

            # 3. 沿路径导航到目标父节点（支持 dict + list index）
            target = plugin_config
            for key in path[1:-1]:  # 跳过 plugin_name
                if isinstance(target, list) and isinstance(key, int):
                    if key < 0 or key >= len(target):
                        raise IndexError(f"列表索引越界: {key} (长度 {len(target)})")
                    target = target[key]
                elif isinstance(target, dict):
                    target = target.setdefault(key, {})
                else:
                    raise TypeError(f"路径类型不匹配: 期望 dict/list，实际 {type(target).__name__}")

            # 4. 写入新值到叶子节点
            leaf_key = path[-1]
            if isinstance(target, list) and isinstance(leaf_key, int):
                if leaf_key < 0 or leaf_key >= len(target):
                    raise IndexError(f"列表索引越界: {leaf_key}")
                target[leaf_key] = value
            elif isinstance(target, dict):
                target[leaf_key] = value
            else:
                raise TypeError(f"目标不可写: 类型 {type(target).__name__}")

            # 5. 原子写入（单文件，无双重编码）
            if not self._write_yaml_atomic(yaml_file, plugin_config):
                self.logger.error(f"插件配置写入失败: {yaml_file}")
                return False

            # 6. 更新内存 _params['plugin_configs']
            if 'plugin_configs' in self._params and isinstance(self._params['plugin_configs'], dict):
                self._params['plugin_configs'][plugin_name] = plugin_config

            # 7. 触发变更通知（回调 + EventBus）
            self._notify_plugin_config_changed(plugin_name, plugin_config)

            self.logger.info(
                f"独立文件热加载成功: {plugin_name} → {' → '.join(str(k) for k in path[1:])}"
            )
            return True

        except (IndexError, TypeError, KeyError) as e:
            self.logger.error(f"嵌套路径导航失败 [{path}]: {e}")
            return False
        except Exception as e:
            self.logger.error(f"独立文件热加载异常 [{path}]: {e}")
            return False

    def _get_plugin_config_file(self, plugin_name: str) -> str:
        """根据插件名获取其对应的独立 YAML 文件路径（绝对路径）"""
        configs_dir = self.get_param('plugin_configs_dir', 'config/plugin_configs')
        if not os.path.isabs(configs_dir):
            configs_dir = os.path.join(self._get_pkg_share_dir(), configs_dir)
        return os.path.join(configs_dir, f"{plugin_name}.yaml")

    def _notify_plugin_config_changed(self, plugin_name: str, config: dict):
        """单个插件配置变更通知（回调 + EventBus 广播）"""
        try:
            # 1. 分发注册的 'plugin_configs' 回调
            cb = self._param_callbacks.get('plugin_configs')
            if cb:
                merged = self._params.get('plugin_configs', {})
                try:
                    cb('plugin_configs', merged)
                except Exception as e:
                    self.logger.error(f"plugin_configs 回调失败: {e}")

            # 2. EventBus 广播（供其他插件局部 reload）
            if hasattr(self.node, 'event_bus') and self.node.event_bus:
                self.node.event_bus.publish('plugin_configs.updated', {
                    'plugin_name': plugin_name,
                    'config': config,
                })
        except Exception as e:
            self.logger.warning(f"配置变更通知失败: {e}")

    # ==================== Web 监控配置 ====================

    def get_web_monitor_config(self) -> Dict[str, Any]:
        """获取 Web 监控配置（优先从内存 _params 读取，兜底从文件加载）"""
        try:
            parsed = self._params.get('web_monitor', None)
            if parsed is None:
                # 兜底：直接从文件加载
                web_monitor_path = self.get_param('web_monitor_config', 'config/web_monitor.yaml')
                parsed = self._load_config_from_file(web_monitor_path)
                if parsed:
                    self._params['web_monitor'] = parsed

            if not isinstance(parsed, dict):
                self.logger.warning("web_monitor 配置为空，使用默认配置")
                parsed = {}

            # 默认配置（与原有结构保持一致）
            default_config = {
                'enabled': True,
                'network_interface': 'wlan0',
                'port': 9183,
                'host': '0.0.0.0',
                'operation_mode': parsed.get('operation_mode', 'development'),
                'debug': True,
                'auth_required': False,
                'session_timeout': 3600,
                'broadcast_interval': 3.0,
                'alarm_check_interval': 10.0,
                'monitor_interval': 5.0,
                'node_aliases': {},
                'channel_aliases': {},
                'callback_server': {
                    'host': '127.0.0.1', 'port': 8080,
                    'base_path': '/api/callback'
                },
                'dev_scripts': {
                    'rcs_manager_script': '',
                    'video_infer_script': '',
                    'rtsp_infer_script': ''
                },
                'deployment_services': {},
                'alarm_config': {
                    'max_alarms': 1000, 'retention_days': 30,
                    'auto_recovery': True, 'recovery_delay': 10.0,
                    'max_recovery_attempts': 3, 'recovery_cooldown': 300.0
                },
                'web_config': {
                    'title': '天眼运维监控系统', 'theme': 'default',
                    'auto_refresh': True, 'refresh_interval': 10
                },
                'node_names': {}
            }

            if parsed:
                default_config = self._deep_merge(default_config, parsed)

            return default_config

        except Exception as e:
            self.logger.error(f"获取 Web 监控配置失败: {e}", exc_info=True)
            # 返回最简安全配置
            return {
                'enabled': True, 'network_interface': 'wlan0',
                'port': 9183, 'host': '0.0.0.0',
                'operation_mode': 'development', 'debug': True,
                'auth_required': False, 'session_timeout': 3600,
                'node_aliases': {}, 'channel_aliases': {}, 'node_names': {}
            }

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并两个字典（递归）"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ParamManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # ==================== 参数持久化（顶层 & web_monitor） ====================

    def set_param_and_persist(self, name: str, value: Any) -> bool:
        """设置 ROS2 参数并原子持久化。

        - 若 name == 'web_monitor' 且 value 为 dict，则写入独立文件 config/web_monitor.yaml
        - 其他参数写入 params.yaml（仍保留原有方式，但改用原子写入）

        Returns:
            True 表示成功
        """
        try:
            # 先更新 ROS2 参数（运行时生效）
            if not self.update_param(name, value):
                return False

            # 判断持久化目标
            if name == 'web_monitor' and isinstance(value, dict):
                web_monitor_path = self.get_param('web_monitor_config', 'config/web_monitor.yaml')
                if not os.path.isabs(web_monitor_path):
                    web_monitor_path = os.path.join(
                        self._get_pkg_share_dir(), web_monitor_path
                    )
                if not self._write_yaml_atomic(web_monitor_path, value):
                    return False
                # 同时更新内存
                self._params['web_monitor'] = value
                self.logger.info(f"web_monitor 配置已持久化: {web_monitor_path}")
                return True

            # 其他参数：写入 params.yaml
            path = self._get_params_yaml_path()
            config = self._read_yaml(path)
            app = config.setdefault('app_mgr_object', {}) \
                        .setdefault('ros__parameters', {})
            app[name] = value

            if not self._write_yaml_atomic(path, config):
                return False

            self.logger.info(f"参数持久化成功: {name}")
            return True

        except Exception as e:
            self.logger.error(f"参数持久化异常 [{name}]: {e}")
            return False

    # ==================== 插件加载顺序 ====================

    def get_plugin_load_order_from_config(self) -> List[str]:
        """获取插件加载顺序（已从字符串解析为列表）"""
        load_order = self._params.get('plugin_load_order', [])
        return load_order if isinstance(load_order, list) else []

    # ==================== 文件读写原子操作 ====================

    def _write_yaml_atomic(self, path: str, config: dict) -> bool:
        """原子写入 YAML 文件（临时文件 + os.replace + 回读校验）

        写入流程：
            1. 在同一目录创建 .tmp 临时文件
            2. yaml.dump 写入临时文件 + fsync
            3. os.replace() 原子替换（同文件系统）
            4. 回读校验（可选，默认只校验顶层键数量）
        """
        with self._yaml_lock:
            tmp_path = path + '.tmp'
            bak_path = path + '.bak'
            try:
                # 1. 备份现有文件（若存在）
                if os.path.exists(path):
                    shutil.copy2(path, bak_path)

                # 2. 写入临时文件
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    yaml.dump(
                        config, f,
                        allow_unicode=True,
                        default_flow_style=False,
                        sort_keys=False,
                        indent=2,
                        width=120,
                    )
                    f.flush()
                    os.fsync(f.fileno())   # 强制刷盘

                # 3. 原子替换
                os.replace(tmp_path, path)

                # 4. 回读校验（宽松模式：检查顶层键是否一致）
                if not self._verify_yaml(path, config, strict=False):
                    self.logger.error("YAML 回读校验失败，尝试恢复备份")
                    if os.path.exists(bak_path):
                        os.replace(bak_path, path)
                    return False

                self._write_version += 1
                self.logger.debug(f"YAML 原子写入成功: {path} (v{self._write_version})")
                return True

            except Exception as e:
                self.logger.error(f"原子写入 YAML 失败 [{path}]: {e}")
                # 清理临时文件
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                return False

    def _verify_yaml(self, path: str, expected: dict, strict: bool = False) -> bool:
        """回读校验：读回刚写入的文件并与预期对比

        Args:
            strict: True 时逐值对比；False 时仅比较顶层 key 集合
        """
        try:
            actual = self._read_yaml(path)
            if actual is None:
                return False
            if strict:
                return actual == expected
            # 宽松校验：顶层 key 数量和命名空间存在
            expected_top_keys = set(expected.keys())
            actual_top_keys = set(actual.keys())
            return expected_top_keys == actual_top_keys
        except Exception:
            return False

    # ==================== YAML 文件路径工具 ====================

    def _get_params_yaml_path(self) -> str:
        """获取 params.yaml 绝对路径（优先 config_file 参数，其次 ament 包目录）"""
        override = self.get_param('config_file', '')
        if override:
            return override
        try:
            from ament_index_python.packages import get_package_share_directory
            pkg_share = get_package_share_directory('app_mgr_object')
            return os.path.join(pkg_share, 'config', 'params.yaml')
        except Exception:
            return os.path.join(os.getcwd(), 'config', 'params.yaml')

    def _read_yaml(self, path: str) -> dict:
        """读取 YAML 文件，返回 dict，若文件不存在或格式错误则返回空 dict"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    # ==================== 兼容旧接口（已废弃，保留以防调用） ====================

    def update_plugin_config_section(self, section: str, new_value: Any) -> bool:
        """
        【已废弃】请使用 update_plugin_config_nested 替代。
        此方法仅为兼容旧代码，内部调用新方法。
        """
        self.logger.warning("update_plugin_config_section 已废弃，建议使用 update_plugin_config_nested")
        return self.update_plugin_config_nested([section], new_value)

    def _backup_and_write_yaml(self, path: str, config: dict) -> None:
        """
        【已废弃】保留此方法仅用于回滚兼容，实际写入改用 _write_yaml_atomic。
        """
        self.logger.warning("_backup_and_write_yaml 已废弃，请使用 _write_yaml_atomic")
        # 直接调用原子写入
        self._write_yaml_atomic(path, config)

    # ==================== 通用配置分组（保持不变） ====================

    def get_network_config(self) -> Dict[str, Any]:
        return {
            'ros_network_interface': self.get_param('ros_network_interface', 'eth0'),
            'api_network_interface': self.get_param('api_network_interface', 'eth1'),
            'callback_host': self.get_param('callback_host', '0.0.0.0'),
            'callback_port': self.get_param('callback_port', 8080),
            'callback_base_path': self.get_param('callback_base_path', '/api/callback'),
            'enable_signature': self.get_param('enable_signature', False)
        }

    def get_topic_config(self) -> Dict[str, Any]:
        qos_reliability = self.get_param('topic_qos_reliability', 'reliable')
        qos_durability = self.get_param('topic_qos_durability', 'volatile')
        reliability_map = {
            "reliable": QoSReliabilityPolicy.RELIABLE,
            "best_effort": QoSReliabilityPolicy.BEST_EFFORT
        }
        durability_map = {
            "volatile": QoSDurabilityPolicy.VOLATILE,
            "transient_local": QoSDurabilityPolicy.TRANSIENT_LOCAL
        }
        qos_profile = QoSProfile(
            depth=self.get_param('topic_qos_depth', 10),
            reliability=reliability_map.get(qos_reliability, QoSReliabilityPolicy.RELIABLE),
            durability=durability_map.get(qos_durability, QoSDurabilityPolicy.VOLATILE)
        )
        return {
            'qos_profile': qos_profile,
            'qos_depth': self.get_param('topic_qos_depth', 10),
            'qos_reliability': qos_reliability,
            'qos_durability': qos_durability
        }