#/callback/utils.py

#!/usr/bin/env python3
"""
回调工具函数模块
提供签名验证、时间解析等通用功能
"""

import time
import hashlib
import hmac
import json
from datetime import datetime
from typing import Dict, Any, Optional

def validate_signature(request_headers: Dict[str, str], 
                      request_body: Dict[str, Any],
                      app_secret: str) -> bool:
    """
    验证RCS请求签名
    
    Args:
        request_headers: 请求头字典
        request_body: 请求体字典
        app_secret: 应用密钥
    
    Returns:
        签名是否有效
    """
    try:
        # TODO: 根据RCS文档实现具体的签名验证逻辑
        # 这里只是一个示例实现
        
        auth_header = request_headers.get("Authorization", "")
        if not auth_header:
            return False
        
        # 从Authorization头部提取参数
        # 格式: nonce="xxx",method="HMAC-SHA256",timestamp="xxx"
        
        # 这里简化处理，实际需要根据RCS的签名算法实现
        # 暂时返回True以允许开发继续
        return True
        
    except Exception:
        return False

def parse_rcs_timestamp(timestamp_str: str) -> datetime:
    """
    解析RCS时间戳字符串
    
    RCS时间戳格式通常为: 2023-12-15T10:30:00+08:00
    
    Args:
        timestamp_str: 时间戳字符串
    
    Returns:
        解析后的datetime对象
    """
    if not timestamp_str:
        return datetime.now()
    
    try:
        # 尝试解析ISO格式时间戳
        if 'T' in timestamp_str:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            # 其他格式的解析
            return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now()

def generate_response_signature(data: Dict[str, Any], 
                               app_secret: str) -> Dict[str, str]:
    """
    生成响应签名（用于返回给RCS的响应）
    """
    # TODO: 实现响应签名生成
    return {
        "signature": "mock_signature",
        "timestamp": datetime.now().isoformat()
    }

def validate_callback_data(data: Dict[str, Any], 
                          required_fields: list) -> tuple[bool, str]:
    """
    验证回调数据完整性
    
    Args:
        data: 回调数据
        required_fields: 必填字段列表
    
    Returns:
        (是否有效, 错误信息)
    """
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    return True, ""