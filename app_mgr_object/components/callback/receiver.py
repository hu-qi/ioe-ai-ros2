#!/usr/bin/env python3
"""
通用回调接收器 - 基于FastAPI
提供轻量级HTTP服务器，支持注册路由和回调函数
"""

import json
import asyncio
import threading
import time
import logging
from typing import Dict, Any, Optional, Callable, List

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
import uvicorn


class CallbackReceiver:
    """通用回调接收器，支持动态注册路由"""

    def __init__(self,
                 logger: Optional[logging.Logger] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        初始化回调接收器

        Args:
            logger: 日志记录器
            config: 配置字典，支持：
                - host: 监听地址，默认 '0.0.0.0'
                - port: 监听端口，默认 8080
                - base_path: 基础路径，默认 '/api/callback'
        """
        self.logger = logger or logging.getLogger(__name__)
        self.config = config or {}
        self.host = self.config.get('host', '0.0.0.0')
        self.port = self.config.get('port', 8080)
        self.base_path = self.config.get('base_path', '/api/callback').rstrip('/')

        # 创建FastAPI应用
        self.app = FastAPI(
            title="通用回调服务器",
            description="提供HTTP回调接口",
            version="1.0.0",
            docs_url="/api/docs" if self.config.get('enable_docs', False) else None
        )

        # 路由映射：path -> (methods, callback)
        self._routes: Dict[str, Dict[str, Callable]] = {}
        self._server_thread: Optional[threading.Thread] = None
        self._running = False
        self._uvicorn_server: Optional[uvicorn.Server] = None

        self._setup_default_routes()

    def _setup_default_routes(self):
        """设置默认路由：健康检查、根路径"""
        @self.app.get("/health")
        async def health():
            return JSONResponse(content={
                'status': 'healthy',
                'timestamp': time.time(),
                'running': self._running
            })

        @self.app.get("/")
        async def root():
            return JSONResponse(content={
                'service': '通用回调服务器',
                'version': '1.0.0',
                'routes': list(self._routes.keys())
            })

    def register_route(self, path: str, method: str, callback: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """
        注册一个路由和回调函数

        Args:
            path: 路由路径（相对于base_path）
            method: HTTP方法（GET, POST, PUT, DELETE等）
            callback: 回调函数，接收请求体（字典）返回响应字典
        """
        full_path = f"{self.base_path}{path}"
        if full_path not in self._routes:
            self._routes[full_path] = {}

        async def endpoint(request: Request):
            try:
                # 根据方法获取数据
                if method.upper() == 'GET':
                    data = dict(request.query_params)
                else:
                    data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
                # 调用用户回调
                result = callback(data)
                return JSONResponse(content=result)
            except Exception as e:
                self.logger.error(f"处理请求 {full_path} 失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # 将endpoint添加到FastAPI路由
        self.app.add_api_route(full_path, endpoint, methods=[method.upper()])
        self._routes[full_path][method.upper()] = callback
        self.logger.info(f"注册路由: {method.upper()} {full_path}")

    def register_json_post(self, path: str, callback: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """快捷注册POST JSON路由"""
        self.register_route(path, 'POST', callback)

    def register_get(self, path: str, callback: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """快捷注册GET路由"""
        self.register_route(path, 'GET', callback)

    def start(self) -> bool:
        """启动回调服务器（非阻塞）"""
        if self._running:
            self.logger.warning("服务器已在运行")
            return True

        def run_server():
            try:
                self.logger.info(f"启动回调服务器: {self.host}:{self.port}")
                config = uvicorn.Config(
                    self.app,
                    host=self.host,
                    port=self.port,
                    log_level="error",
                    access_log=False
                )
                self._uvicorn_server = uvicorn.Server(config)
                self._running = True
                self._uvicorn_server.run()
            except Exception as e:
                self.logger.error(f"服务器运行错误: {e}")
            finally:
                self._running = False

        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        # 等待启动
        time.sleep(0.5)
        if self._server_thread.is_alive():
            self.logger.info(f"回调服务器已启动，监听 {self.host}:{self.port}")
            return True
        else:
            self.logger.error("服务器启动失败")
            return False

    def stop(self):
        """停止服务器"""
        self._running = False
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)
        self.logger.info("回调服务器已停止")

    def get_status(self) -> Dict[str, Any]:
        """获取服务器状态"""
        return {
            'running': self._running,
            'host': self.host,
            'port': self.port,
            'route_count': len(self._routes),
            'routes': list(self._routes.keys())
        }