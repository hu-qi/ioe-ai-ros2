#!/usr/bin/env python3
"""
网络通信模块 - 通用版本
提供HTTP客户端、接口绑定、签名鉴权等功能
"""

from .http_adapter import HTTPAdapter
from .interface_manager import InterfaceManager, NetworkInterfaceManager
from .exceptions import (
    NetworkError,
    AuthenticationError,
    AuthorizationError,
    RequestTimeoutError,
    InvalidResponseError,
    ConnectionError,
    InvalidConfigurationError
)
from .network_utils import get_interface_ip, generate_signature, validate_response

__all__ = [
    'HTTPAdapter',
    'InterfaceManager',
    'NetworkInterfaceManager',
    'NetworkError',
    'AuthenticationError',
    'AuthorizationError',
    'RequestTimeoutError',
    'InvalidResponseError',
    'ConnectionError',
    'InvalidConfigurationError',
    'get_interface_ip',
    'generate_signature',
    'validate_response'
]

__version__ = "1.0.0"