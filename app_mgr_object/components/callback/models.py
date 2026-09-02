#/callback/models.py
"""
回调数据模型定义
对应RCS-2000 V4.2的SPI接口数据结构
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class TaskStatus(Enum):
    """任务状态枚举"""
    QUEUE = "QUEUE"
    WAIT = "WAIT"
    EXECUTING = "EXECUTING"
    MANUALED = "Manualed"
    FINISHED = "Finished"
    CANCELLED = "Cancelled"

class RobotStatus(Enum):
    """机器人状态枚举"""
    IDLE = "IDLE"
    WORKING = "WORKING"
    PAUSE = "PAUSE"

class AbnormalStatus(Enum):
    """异常状态枚举"""
    YES = "YES"
    NO = "NO"

class ChargingStatus(Enum):
    """充电状态枚举"""
    YES = "YES"
    NO = "NO"

class NetworkStatus(Enum):
    """网络状态枚举"""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"

class ManualStatus(Enum):
    """手动状态枚举"""
    MANUAL = "MANUAL"
    AUTO = "AUTO"

class EmergencyStatus(Enum):
    """急停状态枚举"""
    EMERGENCY = "EMERGENCY"
    NORMAL = "NORMAL"

@dataclass
class TaskFeedback:
    """任务执行过程反馈"""
    robot_task_code: str
    single_robot_code: str
    current_seq: Optional[int] = None
    extra: Optional[Dict[str, Any]] = None
    
    # 从extra中解析的具体值
    values: Optional[Dict[str, Any]] = field(default_factory=dict)
    map_code: Optional[str] = None
    method: Optional[str] = None  # start/outbin/end
    carrier_code: Optional[str] = None
    carrier_name: Optional[str] = None
    carrier_type: Optional[str] = None
    carrier_category: Optional[str] = None
    carrier_dir: Optional[str] = None
    slot_code: Optional[str] = None
    slot_name: Optional[str] = None
    slot_category: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    amr_category: Optional[str] = None
    amr_type: Optional[str] = None
    zone_code: Optional[str] = None

@dataclass
class TrafficControlRequest:
    """交管区域申请和释放请求"""
    single_robot_code: str
    zone_code: str
    invoke: str  # APPLY/RELEASE
    extra: Optional[Dict[str, Any]] = None

@dataclass
class ResourceRequestWMS:
    """WMS资源请求"""
    robot_task_code: str
    single_robot_code: str
    resource_type: str
    resource_code: str
    extra: Optional[Dict[str, Any]] = None

@dataclass
class PeripheralRequestWCS:
    """WCS外设请求"""
    robot_task_code: str
    eqpt_code: str
    action_type: str
    action_param: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None

@dataclass
class HomingCompleteFeedback:
    """机器人归巢完成反馈"""
    homing_code: str
    robot_codes: List[str]
    complete_time: datetime
    extra: Optional[Dict[str, Any]] = None

@dataclass
class BanishCompleteFeedback:
    """区域驱离机器人完成反馈"""
    banish_code: str
    robot_codes: List[str]
    complete_time: datetime
    extra: Optional[Dict[str, Any]] = None

@dataclass
class RobotAlarm:
    """机器人异常告警"""
    robot_alarm_code: str
    single_robot_code: str
    alarm_level: str
    alarm_code: str
    alarm_msg: str
    start_time: datetime
    end_time: Optional[datetime] = None
    extra: Optional[Dict[str, Any]] = None

@dataclass
class TaskAlarm:
    """任务异常告警"""
    task_alarm_code: str
    robot_task_code: str
    alarm_level: str
    alarm_code: str
    alarm_msg: str
    start_time: datetime
    end_time: Optional[datetime] = None
    extra: Optional[Dict[str, Any]] = None

@dataclass
class BindUnbindNotification:
    """绑定解绑通知"""
    notification_type: str  # BIND/UNBIND
    carrier_code: str
    site_code: str
    operation_time: datetime
    extra: Optional[Dict[str, Any]] = None