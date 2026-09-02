#!/usr/bin/env python3
"""
RCS HTTP 客户端 — 封装 RCS-2000 V3.3 全部对外任务接口

依赖：
  - NetworkPlugin（通过 node.network_plugin 获取 HTTP 会话）
  - 无 ROS2 依赖，纯 Python 组件

RCS-2000 V3.3 接口映射：
  2.1.1  genAgvSchedulingTask   → gen_agv_scheduling_task()
  2.1.2  continueTask           → continue_task()
  2.1.3  cancelTask             → cancel_task()
  2.2.1  agvCallback            → （由 rcs_callback_receiver_plugin 通过 HTTP 回调处理）
  2.2.2  warnCallback           → （同上）
  3.1.6  queryPodBerthAndMat    → query_pod_berth_and_mat()
  3.1.8  bindCtnrAndBin         → bind_ctnr_and_bin()
  3.1.9  queryTaskStatus        → query_task_status()
  3.1.10 queryAgvStatus         → query_agv_status()
"""

import time
import rclpy.logging
from typing import Dict, Any, List, Optional


class RCSClientError(Exception):
    """RCS 客户端异常"""
    pass


class RCSHttpClient:
    """RCS-2000 V3.3 HTTP 接口客户端

    依赖 node.network_plugin 提供的 HTTP 会话能力（接口绑定 + IP 获取）。
    所有方法均为同步调用，由调用方（插件）决定是否放入线程池。

    使用方式：
        client = RCSHttpClient(
            network_plugin=node.network_plugin,
            base_url="http://192.168.1.100:8080",
            timeout=10.0,
            max_retries=2,
            logger=node.get_logger()
        )
        resp = client.query_agv_status(robot_ids=[1001, 1002])
    """

    def __init__(self,
                 network_plugin,               # NetworkPlugin 实例
                 base_url: str,
                 timeout: float = 10.0,
                 max_retries: int = 2,
                 logger=None):
        """
        Args:
            network_plugin: NetworkPlugin 实例，提供 request() 方法
            base_url: RCS 服务端地址，如 "http://192.168.1.100:8080"
            timeout: 单次请求超时（秒）
            max_retries: 最大重试次数（不含首次）
            logger: 日志记录器
        """
        self._network = network_plugin
        self._base_url = base_url.rstrip('/')
        self._timeout = timeout
        self._max_retries = max_retries
        self._logger = logger or rclpy.logging.get_logger(__name__)

    # ═══════════════════════════════════════════════════════════════
    # 任务接口 (2.x)
    # ═══════════════════════════════════════════════════════════════

    def gen_agv_scheduling_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """2.1.1 生产任务单

        Args:
            payload: 请求体，由 RCSPayloadBuilder.build_task_payload() 构造
                {
                    "taskCode": "TASK_1723456789_01",
                    "taskTyp": "F13",
                    "priority": 64,
                    "agvCode": "1001",
                    "positionCodePath": [
                        {"positionCode": "A1001", "type": "00"},
                        {"positionCode": "T2001", "type": "00"}
                    ]
                }

        Returns:
            RCS 响应体，含 taskNo（任务流水号）
        """
        return self._post('/genAgvSchedulingTask', payload)

    def continue_task(self, task_code: str) -> Dict[str, Any]:
        """2.1.2 继续执行任务

        Args:
            task_code: 任务号（RCS 返回的 taskNo）
        """
        return self._post('/continueTask', {'taskCode': task_code})

    def cancel_task(self, task_code: str, force_cancel: str = "1") -> Dict[str, Any]:
        """2.1.3 取消任务

        Args:
            task_code: 任务号
            force_cancel: "1"=软取消（叉车背货回库）, "0"=硬取消（就地丢弃）

        注意：默认使用软取消 "1"，避免货物滞留通道造成安全隐患。
        """
        return self._post('/cancelTask', {
            'taskCode': task_code,
            'forceCancel': force_cancel
        })

    # ═══════════════════════════════════════════════════════════════
    # 查询接口 (3.x)
    # ═══════════════════════════════════════════════════════════════

    def query_agv_status(self, robot_ids: List[int]) -> Dict[str, Any]:
        """3.1.10 查询 AGV 状态

        Args:
            robot_ids: AGV 编号列表，如 [1001, 1002]

        Returns:
            RCS 响应体，含每台 AGV 的状态码（1=IDLE, 2=BUSY, 3=OFFLINE, 4=ERROR）
        """
        return self._post('/queryAgvStatus', {'robotIDs': robot_ids})

    def query_task_status(self, task_codes: List[str]) -> Dict[str, Any]:
        """3.1.9 查询任务状态

        Args:
            task_codes: RCS 任务号列表

        Returns:
            RCS 响应体，含每个任务的状态（9=已结束, 其他=执行中/异常）
        """
        return self._post('/queryTaskStatus', {'taskCodes': task_codes})

    def query_pod_berth_and_mat(self, stg_bin_codes: List[str]) -> Dict[str, Any]:
        """3.1.6 查询货架储位与物料批次关系

        用于查询终点仓位（T2001~T4006）的绑定状态，判断是否为空。

        Args:
            stg_bin_codes: 仓位编码列表

        Returns:
            RCS 响应体，含每个仓位的绑定关系数据。
            当 ctnrCode 为空时，表示该仓位无货（空）。
        """
        return self._post('/queryPodBerthAndMat', {'stgBinCodes': stg_bin_codes})

    # ═══════════════════════════════════════════════════════════════
    # 绑定接口 (3.x)
    # ═══════════════════════════════════════════════════════════════

    def bind_ctnr_and_bin(self,
                          ctnr_code: str,
                          ctnr_typ: str,
                          stg_bin_code: str,
                          ind_bind: str = "1") -> Dict[str, Any]:
        """3.1.8 容器与仓位绑定/解绑

        在起始仓位 AI 检测确认有货后，调用此接口绑定容器与仓位。
        绑定后该仓位才能被调度系统识别为"可调度"。

        Args:
            ctnr_code:   容器编码（通常等于仓位编号）
            ctnr_typ:    容器类型（货物类型编号字符串，如 "1"）
            stg_bin_code: 仓位编码
            ind_bind:    "1"=绑定, "0"=解绑
        """
        return self._post('/bindCtnrAndBin', {
            'ctnrCode': ctnr_code,
            'ctnrTyp': ctnr_typ,
            'stgBinCode': stg_bin_code,
            'indBind': ind_bind
        })

    # ═══════════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════════

    def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """发送 POST 请求，含自动重试

        Args:
            path: 接口路径（如 '/queryAgvStatus'）
            data: JSON 请求体

        Returns:
            解析后的 JSON 响应体

        Raises:
            RCSClientError: 所有重试均失败时抛出
        """
        url = f"{self._base_url}{path}"
        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                self._log_debug(f"RCS 请求 [{attempt+1}/{self._max_retries+1}]: POST {url}")
                resp = self._network.request(
                    'POST',
                    url,
                    data=data,
                    timeout=self._timeout
                )
                result = resp.json()
                self._log_debug(f"RCS 响应: {url} → code={result.get('code')}")
                return result

            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    wait = 0.5 * (attempt + 1)
                    self._log_warning(f"RCS 请求失败 [{attempt+1}], {wait}s 后重试: {e}")
                    time.sleep(wait)

        raise RCSClientError(f"RCS 请求失败 [{path}] 已重试 {self._max_retries} 次: {last_error}")

    def _log_debug(self, msg: str):
        if self._logger:
            self._logger.debug(msg)

    def _log_warning(self, msg: str):
        if self._logger:
            self._logger.warning(msg)