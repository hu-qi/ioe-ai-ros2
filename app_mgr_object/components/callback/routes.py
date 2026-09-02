#!/usr/bin/env python3
"""
回调路由模块 - 适配新架构
提供路由设置功能
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse, Response
from typing import Dict, Any, Optional, Callable
import time

from .receiver import CallbackReceiver


def setup_routes(app, node=None):
    """
    设置路由（便捷函数）
    
    Args:
        app: FastAPI应用
        node: ROS2节点实例
    
    Returns:
        FastAPI应用
    """
    # 如果提供了节点，创建完整的回调接收器
    if node:
        # 获取回调配置
        from ..base.param_manager import ParamManager
        param_manager = ParamManager(node) if not hasattr(node, 'param_manager') else node.param_manager
        
        config = {
            'port': param_manager.get_param('callback_port', 8080),
            'base_path': param_manager.get_param('callback_base_path', '/eyeSky/robot/reporter'),
            'host': '0.0.0.0'
        }
        
        # 创建回调接收器
        receiver = CallbackReceiver(node, config)
        
        # 合并路由
        for route in receiver.app.routes:
            app.router.routes.append(route)
        
        node.logger.info("回调路由已设置")
    
    # 添加基本的健康检查路由
    @app.get("/health")
    async def health_check():
        return JSONResponse(content={
            'status': 'healthy',
            'timestamp': time.time(),
            'service': 'rcs_callback'
        })
    
    return app


# 创建基本路由器（供其他模块使用）
router = APIRouter()


@router.get("/test")
async def test_endpoint():
    """测试端点"""
    return {"message": "Callback routes are working", "timestamp": time.time()}


@router.get("/version")
async def get_version():
    """获取版本信息"""
    from . import __version__
    return {
        "service": "rcs_callback",
        "version": __version__,
        "timestamp": time.time()
    }