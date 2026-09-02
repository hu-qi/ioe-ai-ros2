#!/usr/bin/env python3
"""
配置管理器 — 配置读写与热加载应用。

依赖：node.param_manager（用于 YAML 持久化）
"""

import time
from typing import Dict, Any


def _is_positive_number(value) -> bool:
    """正数校验（供配置校验复用）"""
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


class ConfigManager:
    """配置热加载管理器"""

    def __init__(self, node):
        self.node = node
        self.logger = node.get_logger()
        self._reload_handlers = {}

    def register_handler(self, section: str, handler: callable):
        """注册热加载处理器"""
        self._reload_handlers[section] = handler

    def apply_config(self, section: str, value: Any) -> dict:
        """Web 配置热加载入口"""
        try:
            handler = self._reload_handlers.get(section)
            if handler:
                error = self._validate_section(section, value)
                if error:
                    return {'success': False, 'error': error}

            path_map = {
                'bay_configs':      ['bay_status_fusion', 'bay_configs'],
                'dest_bay_configs': ['status_poller', 'dest_bay_configs'],
                'work_schedule':    ['smart_trigger', 'work_schedule'],
                'pair_overrides':   ['smart_trigger', 'pair_overrides'],
                'cargo_priority':   ['smart_trigger', 'cargo_priority'],
                'pairing_policy':   ['status_poller', 'pairing_policy'],
                # ── doc/52 阶段2：触发机制节奏/策略/绑定重试（事件驱动热加载） ──
                'max_total_tasks':   ['smart_trigger', 'max_total_tasks'],
                'max_tasks_per_scan': ['smart_trigger', 'max_tasks_per_scan'],
                'aging_ttl':         ['smart_trigger', 'aging_ttl'],
                'scan_interval':     ['smart_trigger', 'scan_interval'],
                'max_queue_size':    ['smart_trigger', 'max_queue_size'],
                'dispatch_per_round': ['smart_trigger', 'dispatch_per_round'],
                'src_scan_order':    ['smart_trigger', 'src_scan_order'],
                'agv':               ['smart_trigger', 'agv'],
                'bind':              ['smart_trigger', 'bind'],
                'robot_poll_interval': ['status_poller', 'robot_poll_interval'],
                'dest_poll_interval':  ['status_poller', 'dest_poll_interval'],
                'agv_status_mapping':  ['status_poller', 'agv_status_mapping'],
            }
            path = path_map.get(section, [section])

            pm = getattr(self.node, 'param_manager', None)
            if pm is None:
                return {'success': False, 'error': '参数管理器未就绪'}

            if not pm.update_plugin_config_nested(path, value):
                return {'success': False, 'error': '配置持久化失败'}

            if handler:
                handler(value)

            return {'success': True, 'message': f'配置段 {section} 已更新', 'hot_reload': True}
        except Exception as e:
            self.logger.error(f"apply_config 失败 [{section}]: {e}")
            return {'success': False, 'error': str(e)}

    def _validate_section(self, section: str, value: Any) -> str:
        """配置业务校验，返回错误信息（空串 = 通过）"""
        if section == 'bay_configs':
            if not isinstance(value, dict):
                return 'bay_configs 必须是 {bay_id: cargo_type} 字典'
            for bid, ct in value.items():
                try:
                    if int(ct) not in range(1, 7):
                        return f'{bid}: cargo_type 必须为 1~6，收到 {ct}'
                except (TypeError, ValueError):
                    return f'{bid}: cargo_type 必须为 1~6，收到 {ct}'
            return ''
        if section == 'dest_bay_configs':
            if not isinstance(value, dict):
                return 'dest_bay_configs 必须是 {bay_id: {cargo_type, floor}} 字典'
            for bid, cfg in value.items():
                try:
                    if int(cfg.get('cargo_type', 0)) not in range(1, 7):
                        return f'{bid}: cargo_type 必须为 1~6'
                except (TypeError, ValueError):
                    return f'{bid}: cargo_type 必须为 1~6'
                if 'lane' in cfg and (cfg['lane'] is None or not str(cfg['lane']).strip()):
                    return f'{bid}: lane 必须是非空字符串（或省略）'
            return ''
        if section == 'work_schedule':
            # 兼容两种形态：list（旧 schedules 数组）或 dict（{enabled, holidays, schedules}）
            if isinstance(value, list):
                schedules = value
            elif isinstance(value, dict):
                if 'enabled' in value and not isinstance(value['enabled'], bool):
                    return 'work_schedule.enabled 必须是布尔值'
                holidays = value.get('holidays') or []
                if not isinstance(holidays, list):
                    return 'work_schedule.holidays 必须是日期列表'
                for h in holidays:
                    if not isinstance(h, str) or len(h) != 10:
                        return f'work_schedule.holidays 必须是 YYYY-MM-DD 格式: {h}'
                schedules = value.get('schedules') or []
            else:
                return 'work_schedule 必须是列表或字典'
            if not isinstance(schedules, list):
                return 'work_schedule.schedules 必须是列表'
            for s in schedules:
                if not isinstance(s, dict) or not all(k in s for k in ('day_of_week', 'start_time', 'end_time')):
                    return f'工作时段缺少字段: {s}'
            return ''
        if section == 'pair_overrides':
            if not isinstance(value, dict):
                return 'pair_overrides 必须是 {src_bay: dst_bay} 字典'
            return ''
        if section == 'cargo_priority':
            if not isinstance(value, list) or not value:
                return 'cargo_priority 必须是非空列表'
            return ''
        if section == 'pairing_policy':
            if not isinstance(value, dict):
                return 'pairing_policy 必须是字典'
            if 'default_strategy' in value and value['default_strategy'] not in ('fifo', 'filo', 'any'):
                return f"default_strategy 必须为 fifo/filo/any，收到 {value['default_strategy']}"
            lanes = value.get('lanes') or []
            if not isinstance(lanes, list):
                return 'lanes 必须是列表'
            seen_ids, seen_bays = set(), set()
            for lane in lanes:
                if not isinstance(lane, dict):
                    return 'lanes 元素必须是对象'
                lid = lane.get('id')
                if not lid or not str(lid).strip():
                    return '巷道缺少 id'
                if lid in seen_ids:
                    return f'巷道 id 重复: {lid}'
                seen_ids.add(lid)
                bays = lane.get('bays')
                if bays is not None:
                    if not isinstance(bays, list) or not bays:
                        return f'巷道 {lid} 的 bays 必须是列表'
                    for b in bays:
                        if b in seen_bays:
                            return f'仓位 {b} 跨巷道重复'
                        seen_bays.add(b)
                if lane.get('strategy') and lane['strategy'] not in ('fifo', 'filo', 'any'):
                    return f"巷道 {lid} strategy 必须为 fifo/filo/any"
            for rules_name in ('type_rules', 'bay_rules'):
                rules = value.get(rules_name) or {}
                if not isinstance(rules, dict):
                    return f'{rules_name} 必须是字典'
                for k, rule in rules.items():
                    if not isinstance(rule, dict):
                        return f'{rules_name}[{k}] 必须是对象'
                    lanes_ref = rule.get('lanes') or []
                    for lid in lanes_ref:
                        if lid not in seen_ids:
                            return f'{rules_name}[{k}] 引用未定义的巷道: {lid}'
                    if rule.get('strategy') and rule['strategy'] not in ('fifo', 'filo', 'any'):
                        return f'{rules_name}[{k}] strategy 必须为 fifo/filo/any'
            return ''
        # ── doc/52 阶段4：触发机制节奏/策略/绑定重试/轮询配置校验 ──
        if section in ('scan_interval', 'aging_ttl', 'robot_poll_interval', 'dest_poll_interval'):
            if not _is_positive_number(value):
                return f'{section} 必须为正数'
            return ''
        if section in ('max_total_tasks', 'max_tasks_per_scan',
                       'max_queue_size', 'dispatch_per_round'):
            try:
                return '' if int(value) >= 0 else f'{section} 必须为非负整数'
            except (TypeError, ValueError):
                return f'{section} 必须是整数'
        if section == 'src_scan_order':
            if not isinstance(value, dict):
                return 'src_scan_order 必须是字典'
            mode = value.get('mode', 'by_bay_id_asc')
            if mode not in ('by_bay_id_asc', 'by_bind_time_desc', 'custom'):
                return (f"src_scan_order.mode 必须为 by_bay_id_asc/by_bind_time_desc/custom，"
                        f"收到 {mode}")
            custom = value.get('custom') or []
            if not isinstance(custom, list):
                return 'src_scan_order.custom 必须是列表'
            return ''
        if section == 'agv':
            if not isinstance(value, dict):
                return 'agv 必须是字典'
            strategy = value.get('select_strategy')
            if strategy and strategy not in ('round_robin', 'least_busy', 'specified'):
                return (f"agv.select_strategy 必须为 round_robin/least_busy/specified，"
                        f"收到 {strategy}")
            for key in ('specified_ids', 'available_statuses'):
                if key in value and not isinstance(value[key], list):
                    return f'agv.{key} 必须是列表'
            return ''
        if section == 'bind':
            if not isinstance(value, dict):
                return 'bind 必须是字典'
            if 'retry_enabled' in value and not isinstance(value['retry_enabled'], bool):
                return 'bind.retry_enabled 必须是布尔值'
            try:
                if int(value.get('retry_count', 3)) < 0:
                    return 'bind.retry_count 必须为非负整数'
            except (TypeError, ValueError):
                return 'bind.retry_count 必须是整数'
            if not _is_positive_number(value.get('retry_delay', 5.0)):
                return 'bind.retry_delay 必须为正数'
            return ''
        if section == 'agv_status_mapping':
            if not isinstance(value, dict):
                return 'agv_status_mapping 必须是字典'
            allowed = ('AVAILABLE', 'BUSY', 'OFFLINE', 'ERROR')
            for k, v in value.items():
                if v not in allowed:
                    return f'agv_status_mapping[{k}] 必须为 {allowed} 之一，收到 {v}'
            return ''
        return ''

    # ==================== 配置读取 ====================

    def get_all_config(self) -> dict:
        return {
            'bay_configs':      self.get_bay_config(),
            'dest_bay_configs': self.get_dest_config(),
            'work_schedule':    self.get_schedule_config(),
            'pair_overrides':   self.get_pair_overrides(),
            'pairing_policy':   self.get_pairing_policy(),
            'trigger_params':   self.get_trigger_config(),
            'params':           self.get_params_config(),
        }

    def get_trigger_config(self) -> dict:
        """读取触发机制节奏/策略/绑定重试配置（doc/52 阶段4，供前端展示）"""
        pm = getattr(self.node, 'param_manager', None)
        pc = (pm._params.get('plugin_configs', {}) if pm else {})
        trigger = pc.get('smart_trigger', {})
        poller = pc.get('status_poller', {})
        return {
            'max_total_tasks': trigger.get('max_total_tasks', 4),
            'max_tasks_per_scan': trigger.get('max_tasks_per_scan', 4),
            'aging_ttl': trigger.get('aging_ttl', 300.0),
            'scan_interval': trigger.get('scan_interval', 2.0),
            'max_queue_size': trigger.get('max_queue_size', 50),
            'dispatch_per_round': trigger.get('dispatch_per_round', 3),
            'src_scan_order': trigger.get('src_scan_order', {}),
            'agv': trigger.get('agv', {}),
            'bind': trigger.get('bind', {}),
            'robot_poll_interval': poller.get('robot_poll_interval', 3.0),
            'dest_poll_interval': poller.get('dest_poll_interval', 10.0),
            'agv_status_mapping': poller.get('agv_status_mapping', {}),
        }

    def get_bay_config(self) -> dict:
        pm = getattr(self.node, 'param_manager', None)
        pc = (pm._params.get('plugin_configs', {}) if pm else {})
        bay = pc.get('bay_status_fusion', {})
        return {'mappings': bay.get('bay_configs', {}), 'last_modified': time.strftime('%Y-%m-%d %H:%M:%S')}

    def get_dest_config(self) -> dict:
        pm = getattr(self.node, 'param_manager', None)
        pc = (pm._params.get('plugin_configs', {}) if pm else {})
        poller = pc.get('status_poller', {})
        return {'mappings': poller.get('dest_bay_configs', {}), 'last_modified': time.strftime('%Y-%m-%d %H:%M:%S')}

    def get_schedule_config(self) -> dict:
        pm = getattr(self.node, 'param_manager', None)
        pc = (pm._params.get('plugin_configs', {}) if pm else {})
        trigger = pc.get('smart_trigger', {})
        ws = trigger.get('work_schedule', {})
        if isinstance(ws, dict):
            return {
                'work_schedule': {
                    'enabled': ws.get('enabled', True),
                    'holidays': ws.get('holidays', []),
                    'schedules': ws.get('schedules', []),
                },
                'schedules': ws.get('schedules', []),   # 兼容旧字段
            }
        return {'work_schedule': {'enabled': True, 'holidays': [], 'schedules': ws or []},
                'schedules': ws or []}

    def get_pair_overrides(self) -> dict:
        pm = getattr(self.node, 'param_manager', None)
        pc = (pm._params.get('plugin_configs', {}) if pm else {})
        trigger = pc.get('smart_trigger', {})
        return {'pair_overrides': trigger.get('pair_overrides', {})}

    def get_pairing_policy(self) -> dict:
        pm = getattr(self.node, 'param_manager', None)
        pc = (pm._params.get('plugin_configs', {}) if pm else {})
        poller = pc.get('status_poller', {})
        return {'policy': poller.get('pairing_policy', {})}

    def get_params_config(self) -> dict:
        pm = getattr(self.node, 'param_manager', None)
        if not pm:
            return {'params': {}}
        keys = ['log_level', 'network_timeout', 'network_retries',
                'request_worker_count', 'request_max_queue_size',
                'status_report_interval', 'plugin_auto_start']
        all_params = pm.get_all_params()
        return {'params': {k: all_params.get(k) for k in keys if k in all_params}}

    def apply_params(self, params: dict) -> dict:
        pm = getattr(self.node, 'param_manager', None)
        if not pm:
            return {'success': False, 'error': '参数管理器未加载'}
        allowed = {'log_level', 'network_timeout', 'network_retries',
                   'request_worker_count', 'request_max_queue_size',
                   'status_report_interval', 'plugin_auto_start'}
        applied, failed = {}, {}
        for name, value in (params or {}).items():
            if name not in allowed:
                continue
            if pm.set_param_and_persist(name, value):
                applied[name] = value
            else:
                failed[name] = value
        return {'success': not failed, 'applied': applied, 'failed': failed}
