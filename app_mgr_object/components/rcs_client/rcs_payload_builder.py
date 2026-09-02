#!/usr/bin/env python3
"""
RCS 请求体构造器 — 标准化 genAgvSchedulingTask 接口的请求 payload

使用方式：
    builder = RCSPayloadBuilder()
    payload = builder.build_task_payload(
        task_context={
            'task_id': 'TASK_1723456789_01',
            'src_bay': 'A1001',
            'dst_bay': 'T2001',
            'robot_id': 1001,
        },
        task_typ='F13',
        priority=64
    )
"""

from typing import Dict, Any


class RCSPayloadBuilder:
    """构造 RCS-2000 V3.3 接口标准请求体"""

    @staticmethod
    def build_task_payload(task_context: Dict[str, Any],
                           task_typ: str = "F13",
                           priority: int = 64) -> Dict[str, Any]:
        """构造 genAgvSchedulingTask 请求体

        Args:
            task_context: 任务上下文，必须包含:
                - task_id:   任务唯一标识
                - src_bay:   起始仓位编号（如 "A1001"）
                - dst_bay:   终点仓位编号（如 "T2001"）
                - robot_id:  分配的 AGV 编号（如 1001）
            task_typ: 任务类型码，默认 "F13"（巷道到工作台）
            priority: 优先级 1~127，值越大越高，默认 64

        Returns:
            符合 RCS 接口规范的 JSON 请求体
        """
        return {
            'taskCode': task_context['task_id'],
            'taskTyp': task_typ,
            'priority': priority,
            'agvCode': str(task_context['robot_id']),
            'positionCodePath': [
                {
                    'positionCode': task_context['src_bay'],
                    'type': '00'
                },
                {
                    'positionCode': task_context['dst_bay'],
                    'type': '00'
                }
            ]
        }

    @staticmethod
    def build_bind_payload(bay_id: str, cargo_type: int,
                           ind_bind: str = "1") -> Dict[str, Any]:
        """构造 bindCtnrAndBin 请求体

        Args:
            bay_id:     仓位编号
            cargo_type: 货物类型 1~6
            ind_bind:   "1"=绑定, "0"=解绑

        Returns:
            绑定请求体
        """
        return {
            'ctnrCode': bay_id,
            'ctnrTyp': str(cargo_type),
            'stgBinCode': bay_id,
            'indBind': ind_bind
        }

    @staticmethod
    def build_force_dispatch_payload(src_bay: str, dst_bay: str,
                                     robot_id: int, task_id: str,
                                     task_typ: str = "F13",
                                     priority: int = 64) -> Dict[str, Any]:
        """构造强制下发（手动）任务的请求体

        与自动任务的区别仅在于 task_id 的前缀（FORCE_ 而非 TASK_）。
        """
        return RCSPayloadBuilder.build_task_payload(
            task_context={
                'task_id': task_id,
                'src_bay': src_bay,
                'dst_bay': dst_bay,
                'robot_id': robot_id,
            },
            task_typ=task_typ,
            priority=priority
        )