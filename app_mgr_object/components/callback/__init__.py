#!/usr/bin/env python3
"""
回调组件 - 通用版本
提供基于FastAPI的HTTP回调服务器，支持注册路由和回调函数
"""

from .receiver import CallbackReceiver
from .utils import validate_signature

__all__ = [
    'CallbackReceiver',
    'validate_signature'
]