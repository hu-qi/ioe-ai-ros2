#!/usr/bin/env python3
"""
网络工具函数 - 通用版本
提供接口IP获取、签名生成等功能
"""

import hmac
import hashlib
import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from urllib.parse import urlparse

import netifaces


def get_interface_ip(interface_name: str) -> str:
    """
    获取指定网络接口的IPv4地址

    Args:
        interface_name: 接口名称

    Returns:
        IP地址字符串

    Raises:
        ValueError: 接口不存在或无IPv4地址
    """
    try:
        addresses = netifaces.ifaddresses(interface_name)
        if netifaces.AF_INET in addresses:
            ip_address = addresses[netifaces.AF_INET][0]['addr']
            return ip_address
        else:
            raise ValueError(f"接口 {interface_name} 没有IPv4地址")
    except Exception as e:
        raise ValueError(f"无法获取接口 {interface_name} IP: {e}")


def generate_signature(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]],
    request_id: str,
    app_key: str,
    app_secret: str,
    version: str = "1.0",
    base_url: str = ""
) -> Dict[str, Any]:
    """
    生成签名（示例算法，可根据实际需求修改）

    Args:
        method: HTTP方法
        path: 请求路径
        body: 请求体
        request_id: 请求ID
        app_key: 应用密钥
        app_secret: 应用密钥
        version: 版本号
        base_url: 基础URL，用于提取host

    Returns:
        包含签名和头信息的字典
    """
    nonce = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    trace_id = str(uuid.uuid4())

    parsed_url = urlparse(base_url)
    host = parsed_url.netloc

    sign_str = f"{method.upper()} {path} HTTP/1.1\n"
    sign_str += f'AUTHORIZATION: nonce="{nonce}",method="HMAC-SHA256",timestamp="{timestamp}"\n'
    sign_str += f'HOST: {host}\n'
    sign_str += f'X-APP-KEY: {app_key}\n'
    sign_str += f'X-REQUEST-ID: {request_id}\n'
    sign_str += f'X-TRACE-ID: {trace_id}\n'
    sign_str += f'X-VERSION: {version}\n'
    sign_str += '\n'

    if body:
        sign_str += json.dumps(body, separators=(',', ':'))

    h = hmac.new(app_secret.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256)
    hash_value = h.digest()
    md5 = hashlib.md5()
    md5.update(hash_value)
    sign = md5.hexdigest()[:16]

    headers = {
        'Authorization': f'nonce="{nonce}",method="HMAC-SHA256",timestamp="{timestamp}"',
        'Content-Type': 'application/json;charset=UTF-8',
        'X-APP-KEY': app_key,
        'X-REQUEST-ID': request_id,
        'X-TRACE-ID': trace_id,
        'X-VERSION': version,
        'Host': host
    }

    return {'sign': sign, 'headers': headers, 'sign_str': sign_str}


def validate_response(response: Dict[str, Any]) -> bool:
    """
    验证响应结构（简单检查，可根据需求定制）

    Args:
        response: 响应字典

    Returns:
        True 如果包含'code'字段（假设），否则False
    """
    return isinstance(response, dict) and 'code' in response