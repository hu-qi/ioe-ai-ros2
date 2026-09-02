#!/usr/bin/env python3
"""
RCS 响应解析器 — 将 RCS HTTP 响应体解析为组件层标准数据结构

设计原则：
  - 响应解析与 HTTP 调用分离，便于单元测试
  - 对 RCS 返回的各种 code 做统一解释
  - 解析失败时返回安全的默认值而非抛异常
"""

from typing import Dict, Any, List, Optional


# ═══════════════════════════════════════════════════════════════
# RCS 状态码常量
# ═══════════════════════════════════════════════════════════════

class RCSRobotStatus:
    """AGV 状态码"""
    IDLE    = "1"   # 空闲
    BUSY    = "2"   # 执行中
    OFFLINE = "3"   # 离线
    ERROR   = "4"   # 异常


class RCSTaskStatus:
    """任务状态码"""
    PENDING     = "0"   # 待执行
    DISPATCHING = "1"   # 下发中
    RUNNING     = "2"   # 执行中
    PAUSED      = "3"   # 暂停
    COMPLETED   = "9"   # 已结束（正常完成）
    CANCELLED   = "8"   # 已取消
    FAILED      = "7"   # 失败


class RCSResponseCode:
    """RCS 通用响应 code"""
    SUCCESS = "0"   # 成功


class RCSResponseParser:
    """RCS 响应解析器 — 提供静态方法，不维护状态"""

    @staticmethod
    def is_success(resp: Dict[str, Any]) -> bool:
        """判断 RCS 响应是否成功"""
        return str(resp.get('code', '')) == RCSResponseCode.SUCCESS

    @staticmethod
    def parse_agv_status(resp: Dict[str, Any]) -> Dict[int, str]:
        """解析 queryAgvStatus 响应 → {robot_id: status}

        Returns:
            {1001: 'IDLE', 1002: 'BUSY'} 等
            解析失败返回空 dict
        """
        result = {}
        try:
            data_list = resp.get('data', [])
            if not isinstance(data_list, list):
                return result
            # status_map = {
            #     RCSRobotStatus.IDLE:    'IDLE',
            #     RCSRobotStatus.BUSY:    'BUSY',
            #     RCSRobotStatus.OFFLINE: 'OFFLINE',
            #     RCSRobotStatus.ERROR:   'ERROR',
            # }
            status_map = {
                '1': 'AVAILABLE',   # 任务完成 -> 可调度
                '2': 'BUSY',        # 执行中 -> 不可调度
                '3': 'ERROR',       # 任务异常 -> 不可调度
                '4': 'AVAILABLE',   # 任务空闲 -> 可调度
            }
            for item in data_list:
                robot_id = item.get('robotID') or item.get('agvCode')
                if robot_id is None:
                    continue
                status_code = str(item.get('status', item.get('agvStatus', '')))
                result[int(robot_id)] = status_map.get(status_code, 'UNKNOWN')
        except Exception:
            pass
        return result

    @staticmethod
    def parse_task_status(resp: Dict[str, Any]) -> Dict[str, str]:
        """解析 queryTaskStatus 响应 → {task_code: status}

        Returns:
            {'TASK_xxx': 'COMPLETED', ...}
            解析失败返回空 dict
        """
        result = {}
        try:
            data_list = resp.get('data', [])
            if not isinstance(data_list, list):
                return result
            status_map = {
                RCSTaskStatus.PENDING:     'PENDING',
                RCSTaskStatus.DISPATCHING: 'DISPATCHING',
                RCSTaskStatus.RUNNING:     'RUNNING',
                RCSTaskStatus.PAUSED:      'PAUSED',
                RCSTaskStatus.COMPLETED:   'COMPLETED',
                RCSTaskStatus.CANCELLED:   'CANCELLED',
                RCSTaskStatus.FAILED:      'FAILED',
            }
            for item in data_list:
                task_code = item.get('taskCode', '')
                if not task_code:
                    continue
                status_code = str(item.get('taskStatus', ''))
                result[task_code] = status_map.get(status_code, 'UNKNOWN')
        except Exception:
            pass
        return result

    @staticmethod
    def parse_gen_task_response(resp: Dict[str, Any]) -> Optional[str]:
        """解析 genAgvSchedulingTask 响应 → 返回 taskNo（RCS 任务流水号）

        Returns:
            成功时返回 RCS 任务流水号，失败返回 None
        """
        try:
            if RCSResponseParser.is_success(resp):
                return resp.get('data', {}).get('taskNo', '')
        except Exception:
            pass
        return None

    @staticmethod
    def parse_pod_berth(resp: Dict[str, Any]) -> Dict[str, bool]:
        """解析 queryPodBerthAndMat 响应 → {bay_id: is_empty}

        is_empty=True 表示该仓位为空（无容器绑定）
        """
        result = {}
        try:
            data_list = resp.get('data', [])
            if not isinstance(data_list, list):
                return result
            for item in data_list:
                bay_id = item.get('stgBinCode', '')
                if not bay_id:
                    continue
                ctnr_code = item.get('ctnrCode', '')
                result[bay_id] = (ctnr_code is None or ctnr_code == '')
        except Exception:
            pass
        return result

    @staticmethod
    def get_task_no(resp: Dict[str, Any]) -> str:
        """从 genAgvSchedulingTask 响应中提取 RCS 任务流水号

        Returns:
            任务流水号字符串，失败返回空字符串
        """
        return RCSResponseParser.parse_gen_task_response(resp) or ''