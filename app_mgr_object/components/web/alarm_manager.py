#!/usr/bin/env python3
"""
告警管理器 - 记录和管理系统告警（增强版）
"""

import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict, field
from enum import Enum
import rclpy.logging


class AlarmLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"


class AlarmType(Enum):
    """告警类型"""
    NODE = "node"
    CHANNEL = "channel"
    SERVICE = "service"
    RECOVERY = "recovery"
    OPERATION = "operation"
    SYSTEM = "system"
    NETWORK = "network"
    TASK = "task"


@dataclass
class Alarm:
    """告警数据类"""
    id: str
    type: AlarmType
    level: AlarmLevel
    message: str
    details: Dict[str, Any]
    timestamp: float
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[float] = None
    resolved: bool = False
    resolved_at: Optional[float] = None
    source: str = "system"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result['type'] = self.type.value
        result['level'] = self.level.value
        result['time_str'] = datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        if self.acknowledged_at:
            result['acknowledged_at_str'] = datetime.fromtimestamp(
                self.acknowledged_at
            ).strftime('%Y-%m-%d %H:%M:%S')
        
        if self.resolved_at:
            result['resolved_at_str'] = datetime.fromtimestamp(
                self.resolved_at
            ).strftime('%Y-%m-%d %H:%M:%S')
        
        return result


class AutoRecoveryManager:
    """自动恢复管理器"""
    
    def __init__(self, config: Dict[str, Any], alarm_callback: Callable, logger=None):
        self.config = config
        self.alarm_callback = alarm_callback
        self.logger = logger or rclpy.logging.get_logger(__name__)
            
        self._recovery_history = []
        self._lock = threading.RLock()
        
        # 自动恢复配置
        self.enabled = config.get('auto_recovery', True)
        self.recovery_delay = config.get('recovery_delay', 10.0)
        self.max_recovery_attempts = config.get('max_recovery_attempts', 3)
        self.recovery_cooldown = config.get('recovery_cooldown', 300.0)  # 5分钟冷却时间
        
        # 恢复策略
        self.recovery_strategies = {
            'node': self._recover_node,
            'channel': self._recover_channel,
            'service': self._recover_service
        }
    
    def check_and_recover(self, alarm: Alarm) -> bool:
        """检查并执行自动恢复"""
        with self._lock:
            if not self.enabled:
                return False
            
            # 检查是否需要自动恢复
            if not self._should_recover(alarm):
                return False
            
            # 执行恢复
            try:
                recovery_func = self.recovery_strategies.get(alarm.type.value)
                if recovery_func:
                    success = recovery_func(alarm)
                    
                    # 记录恢复历史
                    self._record_recovery(alarm, success)
                    
                    # 触发恢复告警
                    if success:
                        self.alarm_callback(
                            "recovery",
                            "info",
                            f"自动恢复成功: {alarm.message}",
                            {"alarm_id": alarm.id, "recovery_time": time.time()}
                        )
                    else:
                        self.alarm_callback(
                            "recovery",
                            "warning",
                            f"自动恢复失败: {alarm.message}",
                            {"alarm_id": alarm.id, "recovery_time": time.time()}
                        )
                    
                    return success
                
                return False
                
            except Exception as e:
                self.logger.error(f"自动恢复失败: {e}")
                return False
    
    def _should_recover(self, alarm: Alarm) -> bool:
        """检查是否应该执行自动恢复"""
        # 检查告警级别（只对严重和警告级别进行恢复）
        if alarm.level not in [AlarmLevel.CRITICAL, AlarmLevel.WARNING]:
            return False
        
        # 检查是否已确认（已确认的告警不进行自动恢复）
        if alarm.acknowledged:
            return False
        
        # 检查是否已解决
        if alarm.resolved:
            return False
        
        # 检查恢复尝试次数
        alarm_recovery_count = sum(1 for r in self._recovery_history 
                                 if r.get('alarm_id') == alarm.id)
        if alarm_recovery_count >= self.max_recovery_attempts:
            return False
        
        # 检查冷却时间
        last_recovery = self._get_last_recovery_time(alarm.id)
        if last_recovery and (time.time() - last_recovery) < self.recovery_cooldown:
            return False
        
        return True
    
    def _recover_node(self, alarm: Alarm) -> bool:
        """恢复节点异常"""
        # 根据节点类型执行不同的恢复策略
        node_name = alarm.details.get('node_name', '')
        
        if 'rtsp_infer' in node_name or 'video_multi' in node_name:
            # 重启推理节点
            return self._restart_infer_nodes()
        elif 'rcs_manager' in node_name:
            # 重启RCS管理器
            return self._restart_rcs_manager()
        
        return False
    
    def _recover_channel(self, alarm: Alarm) -> bool:
        """恢复通道异常"""
        # 通道异常通常需要重启视频处理节点
        return self._restart_infer_nodes()
    
    def _recover_service(self, alarm: Alarm) -> bool:
        """恢复服务异常"""
        # 重启服务
        service_name = alarm.details.get('service_name', '')
        if service_name:
            return self._restart_service(service_name)
        return False
    
    def _restart_infer_nodes(self) -> bool:
        """重启推理节点"""
        try:
            # 这里应该调用ControlExecutor的方法
            # 暂时模拟成功
            time.sleep(2)
            return True
        except:
            return False
    
    def _restart_rcs_manager(self) -> bool:
        """重启RCS管理器"""
        try:
            # 这里应该调用ControlExecutor的方法
            # 暂时模拟成功
            time.sleep(2)
            return True
        except:
            return False
    
    def _restart_service(self, service_name: str) -> bool:
        """重启服务"""
        try:
            # 这里应该调用ControlExecutor的方法
            # 暂时模拟成功
            time.sleep(2)
            return True
        except:
            return False
    
    def _record_recovery(self, alarm: Alarm, success: bool):
        """记录恢复历史"""
        recovery_record = {
            'timestamp': time.time(),
            'alarm_id': alarm.id,
            'alarm_type': alarm.type.value,
            'success': success,
            'message': alarm.message
        }
        
        self._recovery_history.append(recovery_record)
        
        # 保持历史记录长度
        if len(self._recovery_history) > 100:
            self._recovery_history = self._recovery_history[-100:]
    
    def _get_last_recovery_time(self, alarm_id: str) -> Optional[float]:
        """获取最后一次恢复时间"""
        for recovery in reversed(self._recovery_history):
            if recovery.get('alarm_id') == alarm_id:
                return recovery.get('timestamp')
        return None
    
    def get_recovery_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取恢复历史"""
        with self._lock:
            history = self._recovery_history.copy()
            history.sort(key=lambda x: x['timestamp'], reverse=True)
            
            if limit > 0:
                history = history[:limit]
            
            # 格式化时间
            for record in history:
                record['time_str'] = datetime.fromtimestamp(
                    record['timestamp']
                ).strftime('%Y-%m-%d %H:%M:%S')
            
            return history
    
    def get_recovery_stats(self) -> Dict[str, Any]:
        """获取恢复统计"""
        with self._lock:
            total_recoveries = len(self._recovery_history)
            successful_recoveries = sum(1 for r in self._recovery_history if r.get('success', False))
            
            # 按类型统计
            by_type = {}
            for recovery in self._recovery_history:
                alarm_type = recovery.get('alarm_type', 'unknown')
                by_type[alarm_type] = by_type.get(alarm_type, 0) + 1
            
            return {
                'total_recoveries': total_recoveries,
                'successful_recoveries': successful_recoveries,
                'success_rate': (successful_recoveries / total_recoveries * 100) if total_recoveries > 0 else 0,
                'by_type': by_type,
                'enabled': self.enabled,
                'max_attempts': self.max_recovery_attempts,
                'cooldown': self.recovery_cooldown
            }


class AlarmManager:
    """告警管理器（增强版）"""
    
    def __init__(self, config: Dict[str, Any] = None, logger=None):
        self.config = config or {} 
        self.logger = logger or rclpy.logging.get_logger(__name__)   
        self.alarms: List[Alarm] = []
        self._lock = threading.RLock()
        self._next_id = 1
        
        
        
        # 告警配置
        self.max_alarms = self.config.get('max_alarms', 1000)
        self.retention_days = self.config.get('retention_days', 30)
        
        # 告警回调函数
        self._alarm_callbacks = []
        
        # 自动恢复管理器
        self.auto_recovery = AutoRecoveryManager(config, self.add_alarm, logger=self.logger)
        
        # 告警规则
        self._alarm_rules = self._init_alarm_rules()
        
    def _enforce_alarm_limit(self):                # ← 新增方法
        if len(self.alarms) > self.max_alarms:
            self.alarms = self.alarms[:self.max_alarms]
    
    def _init_alarm_rules(self) -> Dict[str, Dict[str, Any]]:
        """初始化告警规则"""
        return {
            'node_offline': {
                'condition': lambda data: not data.get('alive', True),
                'level': AlarmLevel.CRITICAL,
                'type': AlarmType.NODE,
                'message_template': "节点 {node_name} ({alias}) 离线",
                'details_fields': ['node_name', 'alias', 'last_check']
            },
            'channel_error': {
                'condition': lambda data: not data.get('signal_status', True),
                'level': AlarmLevel.WARNING,
                'type': AlarmType.CHANNEL,
                'message_template': "通道 {channel_id} 信号异常",
                'details_fields': ['channel_id', 'device_id', 'last_update']
            },
            'service_stopped': {
                'condition': lambda data: not data.get('is_running', True),
                'level': AlarmLevel.WARNING,
                'type': AlarmType.SERVICE,
                'message_template': "服务 {service_name} 已停止",
                'details_fields': ['service_name', 'last_check']
            },
            'health_low': {
                'condition': lambda data: data.get('health_score', 100) < 60,
                'level': AlarmLevel.WARNING,
                'type': AlarmType.SYSTEM,
                'message_template': "系统健康度低: {health_score}%",
                'details_fields': ['health_score', 'components']
            }
        }
    
    def add_alarm(self,
                  alarm_type: str,
                  level: str,
                  message: str,
                  details: Dict[str, Any] = None,
                  source: str = "system") -> Optional[Alarm]:
        """添加告警（带去重：相同消息且未确认的告警只更新时间）"""
        with self._lock:
            # =====  去重检查 =====
            # 查找是否存在相同 (type, level, message, source) 且未确认的告警
            existing = None
            for a in self.alarms:
                if (a.type.value == alarm_type
                        and a.level.value == level
                        and a.message == message
                        and a.source == source
                        and not a.acknowledged):
                    existing = a
                    break

            if existing:
                # 仅更新时间戳（不影响其他告警的位置和排序）
                existing.timestamp = time.time()
                existing.details = details or existing.details
                self.logger.debug(f"告警去重: [{alarm_type}/{level}] {message} — 已更新时间戳")
                return existing   # 不触发新增回调，避免前端重复渲染
            # ===== 去重检查结束 =====

            # 生成告警ID
            alarm_id = f"ALM-{int(time.time() * 1000)}-{len(self.alarms):04d}"

            # 解析告警类型和级别
            try:
                alarm_type_enum = AlarmType(alarm_type)
            except ValueError:
                self.logger.warning(f"未知的告警类型: {alarm_type}")
                alarm_type_enum = AlarmType.SYSTEM

            try:
                alarm_level_enum = AlarmLevel(level)
            except ValueError:
                self.logger.warning(f"未知的告警级别: {level}")
                alarm_level_enum = AlarmLevel.INFO

            # 创建告警对象
            alarm = Alarm(
                id=alarm_id,
                type=alarm_type_enum,
                level=alarm_level_enum,
                message=message,
                details=details or {},
                timestamp=time.time(),
                source=source
            )

            # 添加到告警列表
            self.alarms.append(alarm)

            # 按时间排序（最新在前）
            self.alarms.sort(key=lambda x: x.timestamp, reverse=True)

            # 检查告警数量限制
            self._enforce_alarm_limit()

            # 处理自动恢复
            if self.auto_recovery:
                recovery_alarms = self.auto_recovery.check_and_recover(alarm)
                # 将恢复告警也添加到列表
                if recovery_alarms:
                    for rec_alarm in recovery_alarms:
                        self.alarms.insert(0, rec_alarm)

            # ===== 只有新增的告警才触发回调 =====
            self._trigger_alarm_callbacks(alarm)

            self.logger.info(f"新告警: [{alarm_type}/{level}] {message}")

            return alarm
    
    def check_system_status(self, system_status: Dict[str, Any]) -> List[Alarm]:
        """检查系统状态并生成告警（修复 nodes 结构）"""
        new_alarms = []

        try:
            # ---------- 规范化 nodes ----------
            nodes_raw = system_status.get('nodes', {})
            if isinstance(nodes_raw, dict) and 'monitored_nodes' in nodes_raw:
                # 标准结构：使用 monitored_nodes
                nodes = nodes_raw.get('monitored_nodes', {})
            else:
                # 兼容旧结构：直接使用
                nodes = nodes_raw

            # 确保 nodes 是字典，否则置空
            if not isinstance(nodes, dict):
                nodes = {}

            # ---------- 规范化 channels ----------
            channels_raw = system_status.get('channels', {})
            if isinstance(channels_raw, dict) and 'channels' in channels_raw:
                channels = channels_raw.get('channels', {})
            else:
                channels = channels_raw
            if not isinstance(channels, dict):
                channels = {}

            # ---------- 规范化 services ----------
            services = system_status.get('services', {})
            if not isinstance(services, dict):
                services = {}

            # ---------- 节点告警 ----------
            for node_name, node_info in nodes.items():
                if not node_info.get('alive', True):
                    alarm = self.add_alarm(
                        'node',
                        'critical',
                        f"节点 {node_name} ({node_info.get('alias', node_name)}) 离线",
                        {
                            'node_name': node_name,
                            'alias': node_info.get('alias', node_name),
                            'last_check': node_info.get('last_check'),
                            'source': 'status_monitor'
                        }
                    )
                    new_alarms.append(alarm)

            # ---------- 通道告警 ----------
            for channel_key, channel_info in channels.items():
                if not channel_info.get('signal_status', True):
                    alarm = self.add_alarm(
                        'channel',
                        'warning',
                        f"通道 {channel_info.get('alias', channel_key)} 信号异常",
                        {
                            'channel_id': channel_info.get('channel_id'),
                            'device_id': channel_info.get('device_id'),
                            'last_update': channel_info.get('last_update'),
                            'source': 'status_monitor'
                        }
                    )
                    new_alarms.append(alarm)

            # ---------- 服务告警 ----------
            for service_name, service_info in services.items():
                if not service_info.get('is_running', True):
                    alarm = self.add_alarm(
                        'service',
                        'warning',
                        f"服务 {service_name} 已停止",
                        {
                            'service_name': service_name,
                            'last_check': service_info.get('last_check'),
                            'source': 'status_monitor'
                        }
                    )
                    new_alarms.append(alarm)

            # ---------- 健康度告警 ----------
            health_score = system_status.get('health_score', 100)
            if health_score < 60:
                alarm = self.add_alarm(
                    'system',
                    'warning' if health_score >= 40 else 'critical',
                    f"系统健康度低: {health_score}%",
                    {
                        'health_score': health_score,
                        'components': {
                            'nodes': len(nodes),
                            'channels': len(channels),
                            'services': len(services)
                        },
                        'source': 'status_monitor'
                    }
                )
                new_alarms.append(alarm)

        except Exception as e:
            self.logger.error(f"检查系统状态失败: {e}")

        return new_alarms
    
    def get_alarms(self, 
                   limit: int = 100, 
                   include_acknowledged: bool = False,
                   include_resolved: bool = False,
                   alarm_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取告警列表"""
        with self._lock:
            # 清理过期告警
            self._cleanup_old_alarms()
            
            # 过滤告警
            filtered_alarms = self.alarms.copy()
            
            if not include_acknowledged:
                filtered_alarms = [a for a in filtered_alarms if not a.acknowledged]
            
            if not include_resolved:
                filtered_alarms = [a for a in filtered_alarms if not a.resolved]
            
            if alarm_type:
                filtered_alarms = [a for a in filtered_alarms if a.type.value == alarm_type]
            
            # 按时间倒序排序
            filtered_alarms.sort(key=lambda x: x.timestamp, reverse=True)
            
            # 限制数量
            if limit > 0:
                filtered_alarms = filtered_alarms[:limit]
            
            return [alarm.to_dict() for alarm in filtered_alarms]
    
    def get_recent_alarms(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近告警"""
        return self.get_alarms(limit=limit, 
                             include_acknowledged=False, 
                             include_resolved=False)
    
    def acknowledge_alarm(self, alarm_id: str, username: str = "system") -> bool:
        """确认告警"""
        with self._lock:
            for alarm in self.alarms:
                if alarm.id == alarm_id:
                    alarm.acknowledged = True
                    alarm.acknowledged_by = username
                    alarm.acknowledged_at = time.time()
                    return True
            return False
    
    def resolve_alarm(self, alarm_id: str) -> bool:
        """解决告警"""
        with self._lock:
            for alarm in self.alarms:
                if alarm.id == alarm_id:
                    alarm.resolved = True
                    alarm.resolved_at = time.time()
                    return True
            return False
    
    def clear_alarms(self, alarm_type: Optional[str] = None, 
                    level: Optional[str] = None, 
                    resolved_only: bool = False) -> int:
        """清理告警"""
        with self._lock:
            count_before = len(self.alarms)
            
            # 过滤要保留的告警
            self.alarms = [
                alarm for alarm in self.alarms
                if (not alarm_type or alarm.type.value != alarm_type) and
                   (not level or alarm.level.value != level) and
                   (not resolved_only or not alarm.resolved)
            ]
            
            return count_before - len(self.alarms)
    
    def register_alarm_callback(self, callback: Callable[[Alarm], None]):
        """注册告警回调"""
        self._alarm_callbacks.append(callback)
    
    def _trigger_alarm_callbacks(self, alarm: Alarm):
        """触发告警回调"""
        for callback in self._alarm_callbacks:
            try:
                callback(alarm)
            except Exception as e:
                self.logger.error(f"告警回调执行失败: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取告警统计"""
        with self._lock:
            total_alarms = len(self.alarms)
            unacknowledged = sum(1 for a in self.alarms if not a.acknowledged)
            unresolved = sum(1 for a in self.alarms if not a.resolved)
            
            # 按级别统计
            by_level = {}
            for level in AlarmLevel:
                by_level[level.value] = sum(1 for a in self.alarms if a.level == level)
            
            # 按类型统计
            by_type = {}
            for alarm_type in AlarmType:
                by_type[alarm_type.value] = sum(1 for a in self.alarms if a.type == alarm_type)
            
            # 按源统计
            by_source = {}
            for alarm in self.alarms:
                source = alarm.source
                by_source[source] = by_source.get(source, 0) + 1
            
            return {
                'total_alarms': total_alarms,
                'unacknowledged_alarms': unacknowledged,
                'unresolved_alarms': unresolved,
                'by_level': by_level,
                'by_type': by_type,
                'by_source': by_source,
                'max_alarms': self.max_alarms,
                'retention_days': self.retention_days,
                'auto_recovery_stats': self.auto_recovery.get_recovery_stats()
            }
    
    def _cleanup_old_alarms(self):
        """清理过期告警"""
        retention_seconds = self.retention_days * 24 * 3600
        cutoff_time = time.time() - retention_seconds
        
        self.alarms = [
            alarm for alarm in self.alarms
            if alarm.timestamp > cutoff_time or 
               (not alarm.acknowledged and not alarm.resolved)
        ]
    
    def get_alarm_history(self, hours: int = 24) -> Dict[str, List]:
        """获取告警历史"""
        with self._lock:
            cutoff_time = time.time() - (hours * 3600)
            
            history_alarms = [a for a in self.alarms if a.timestamp > cutoff_time]
            history_alarms.sort(key=lambda x: x.timestamp)
            
            # 按小时分组
            hourly_counts = {}
            for alarm in history_alarms:
                hour_key = datetime.fromtimestamp(alarm.timestamp).strftime('%Y-%m-%d %H:00')
                hourly_counts[hour_key] = hourly_counts.get(hour_key, 0) + 1
            
            # 转换为列表格式
            hours_list = sorted(hourly_counts.keys())
            counts_list = [hourly_counts[h] for h in hours_list]
            
            return {
                'hours': hours_list,
                'counts': counts_list,
                'total': len(history_alarms)
            }
    
    def export_alarms(self, filepath: str) -> bool:
        """导出告警数据"""
        try:
            with self._lock:
                data = {
                    'export_time': time.time(),
                    'alarm_count': len(self.alarms),
                    'alarms': [alarm.to_dict() for alarm in self.alarms]
                }
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                return True
                
        except Exception as e:
            self.logger.error(f"导出告警失败: {e}")
            return False