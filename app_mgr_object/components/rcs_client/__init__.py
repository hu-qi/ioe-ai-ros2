#!/usr/bin/env python3
"""
RCS HTTP 客户端组件包

提供：
  - RCSHttpClient        : RCS-2000 V3.3 HTTP 接口封装
  - RCSPayloadBuilder     : 请求体构造器
  - RCSResponseParser     : 响应解析器
  - RCSClientError        : 客户端异常类
  - RCSTaskStatus         : 任务状态码常量
  - RCSRobotStatus        : AGV 状态码常量
  - RCSResponseCode       : 通用响应码常量
"""

from .rcs_http_client import RCSHttpClient, RCSClientError
from .rcs_payload_builder import RCSPayloadBuilder
from .rcs_response_parser import (
    RCSResponseParser,
    RCSTaskStatus,
    RCSRobotStatus,
    RCSResponseCode,
)

__all__ = [
    'RCSHttpClient',
    'RCSClientError',
    'RCSPayloadBuilder',
    'RCSResponseParser',
    'RCSTaskStatus',
    'RCSRobotStatus',
    'RCSResponseCode',
]