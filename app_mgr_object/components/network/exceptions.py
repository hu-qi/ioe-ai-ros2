#!/usr/bin/env python3
"""
网络异常定义 - 通用版本
"""

class NetworkError(Exception):
    """网络异常基类"""
    pass

class AuthenticationError(NetworkError):
    """认证错误"""
    pass

class AuthorizationError(NetworkError):
    """授权错误"""
    pass

class RequestTimeoutError(NetworkError):
    """请求超时"""
    pass

class InvalidResponseError(NetworkError):
    """无效响应"""
    pass

class ConnectionError(NetworkError):
    """连接错误"""
    pass

class InvalidConfigurationError(NetworkError):
    """无效配置"""
    pass