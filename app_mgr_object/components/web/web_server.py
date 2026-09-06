#!/usr/bin/env python3
"""
Web服务器 - 修复WebSocket版本
"""
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False
import json
import time
import asyncio
import threading
import socket
import netifaces
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn
from rclpy.node import Node
import concurrent.futures

class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = threading.RLock()
        self._event_loop = None
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
    
    async def broadcast_json(self, data: dict):
        """广播JSON数据到所有连接"""
        with self._lock:
            disconnected = []
            message = json.dumps(data, ensure_ascii=False)
            
            for connection in self.active_connections:
                try:
                    await connection.send_text(message)
                except Exception:
                    disconnected.append(connection)
            
            # 移除断开的连接
            for connection in disconnected:
                self.disconnect(connection)
    
    def get_connection_count(self) -> int:
        """获取当前连接数"""
        with self._lock:
            return len(self.active_connections)
    
    def set_event_loop(self, loop):
        """设置事件循环"""
        self._event_loop = loop
    
    def schedule_broadcast(self, data: dict):
        """安排广播任务到事件循环"""
        if self._event_loop and not self._event_loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self.broadcast_json(data),
                self._event_loop
            )


class WebServer:
    """Web服务器（修复WebSocket版本）"""
    
    def __init__(self, 
                config: Dict[str, Any],
                node: Node,
                status_callback: Callable[[], Dict[str, Any]],
                control_callback: Callable[[str, str, Dict[str, Any]], Dict[str, Any]],
                logger=None):
        """
        初始化Web服务器
        """
        self.config = config
        self.node = node 
        self.status_callback = status_callback
        self.control_callback = control_callback
        self.logger = logger
        if self.logger is None:
            self.logger = self.node.get_logger().get_child('WebServer')
            
                
        # 使用配置中的值
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 9183)
        self.debug = config.get('debug', True)
        self.operation_mode = config.get('operation_mode', 'development')
        
        # 获取网络接口配置（用于日志显示）
        self.network_interface = config.get('network_interface', 'wlan0')       
        
        
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        
        self.logger.info(f"Web服务器配置 - 网络接口: {self.network_interface}, 监听地址: {self.host}:{self.port}")
        
        # 创建FastAPI应用
        self.app = FastAPI(
            title="天眼运维监控系统",
            description="ROS2节点和通道状态监控系统",
            version="2.0.0",
            docs_url="/api/docs" if config.get('debug', True) else None,
            redoc_url="/api/redoc" if config.get('debug', True) else None,
            openapi_url="/api/openapi.json" if config.get('debug', True) else None
        )
        
        # 添加中间件处理.map文件
        @self.app.middleware("http")
        async def ignore_map_files_middleware(request: Request, call_next):
            """中间件：忽略.map文件请求"""
            if request.url.path.endswith('.map'):
                from starlette.responses import Response
                return Response(status_code=204)
            return await call_next(request)
        
        # WebSocket连接管理器
        self.manager = ConnectionManager()
        self._event_loop = None
        
        # 模板和静态文件
        self.templates_dir = Path(__file__).parent / "templates"
        self.static_dir = Path(__file__).parent / "static"
        
        # 创建静态文件目录
        self.static_dir.mkdir(exist_ok=True)
        
        # 创建自定义的静态文件处理
        class CustomStaticFiles(StaticFiles):
            async def get_response(self, path: str, scope):
                """重写get_response方法，处理.map文件"""
                if path.endswith('.map'):
                    from starlette.responses import Response
                    return Response(status_code=204)
                return await super().get_response(path, scope)
        
        # 挂载静态文件
        if self.static_dir.exists():
            self.app.mount("/static", StaticFiles(directory=self.static_dir), name="static")
        
        # 设置模板
        if self.templates_dir.exists():
            self.templates = Jinja2Templates(directory=self.templates_dir)
        else:
            self.logger = self.logger
            self.logger.warning(f"模板目录不存在: {self.templates_dir}")
            self.templates = None
        
        # 启动时间
        self._lock = threading.RLock()  # 添加锁
        self._operation_logs = []       # 添加操作日志列表
        self._start_time = time.time()  # 确保启动时间已设置
        
        # 设置路由
        self._setup_routes()
        
        # ===== 业务/配置/任务路由（v3.0） =======
        self._setup_business_routes()        
        
        # 服务器线程
        self.server_thread = None
        self.running = False
        self._uvicorn_server = None       
        
        
        # 启动WebSocket广播线程
        self._start_websocket_broadcast()
        
        # 启动告警检查线程（如果有告警回调）
        # if self.alarm_callback:
        #     self._start_alarm_check()
    
    # def _get_logger(self):
    #     """获取日志记录器"""
    #     import logging
    #     logger = logging.getLogger('WebServer')
    #     if not logger.handlers:
    #         handler = logging.StreamHandler()
    #         formatter = logging.Formatter(
    #             '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
    #             datefmt='%Y-%m-%d %H:%M:%S'
    #         )
    #         handler.setFormatter(formatter)
    #         logger.addHandler(handler)
    #         logger.setLevel(logging.INFO)
    #     return logger
    
    
    
    def _setup_routes(self):
        """设置所有路由"""     
        
        # ==================== 静态文件路由优先处理 ====================
        @self.app.get("/static/{directory}/{filename}")
        async def serve_static_file(directory: str, filename: str):
            """服务静态文件，过滤.map文件"""
            if filename.endswith('.map'):
                from starlette.responses import Response
                return Response(status_code=204, headers={"Cache-Control": "no-store"})
            
            file_path = self.static_dir / directory / filename
            if file_path.exists():
                return FileResponse(file_path)
            else:
                raise HTTPException(status_code=404, detail="File not found")
        
        # ==================== 静态文件映射处理 ====================
        @self.app.get("/static/{rest_of_path:path}.map")
        async def ignore_static_source_maps(rest_of_path: str):
            """忽略静态.map文件的请求 - 返回204 No Content"""
            from starlette.responses import Response
            return Response(status_code=204)
        
        @self.app.get("/{path:path}.map")
        async def ignore_all_source_maps(path: str):
            """忽略所有.map文件的请求 - 返回204 No Content"""
            from starlette.responses import Response
            return Response(status_code=204)
        
        # ==================== 页面路由 ====================
        @self.app.get("/")
        @self.app.get("/index")
        async def index(request: Request):
            """首页"""
            if self.templates:
                return self.templates.TemplateResponse(
                    request,
                    "index.html",
                    {"config": self.config}
                )
            return HTMLResponse("<h1>天眼运维监控系统</h1>")

        @self.app.get("/monitor")
        async def monitor(request: Request):
            """状态监控页"""
            if self.templates:
                return self.templates.TemplateResponse(
                    request,
                    "monitor.html",
                    {"config": self.config}
                )
            return HTMLResponse("<h1>状态监控</h1>")

        @self.app.get("/control")
        async def control(request: Request):
            """运维控制页"""
            if self.templates:
                return self.templates.TemplateResponse(
                    request,
                    "control.html",
                    {"config": self.config}
                )
            return HTMLResponse("<h1>运维控制</h1>")
        
        # @self.app.get("/alarms")
        # async def alarms(request: Request):
        #     """告警管理页"""
        #     if self.templates:
        #         return self.templates.TemplateResponse(
        #             "alarms.html", 
        #             {"request": request, "config": self.config}
        #         )
        #     return HTMLResponse("<h1>告警管理</h1>")
        
        @self.app.get("/test")
        async def test(request: Request):
            """测试页"""
            if self.templates:
                return self.templates.TemplateResponse(
                    request,
                    "test.html",
                    {"config": self.config}
                )
            return HTMLResponse("<h1>测试页面</h1>")
        
        # ==================== API路由 - 状态查询 ====================
        @self.app.get("/api/status")
        async def get_status():
            """获取系统状态"""
            try:
                if self.status_callback:
                    status_data = self.status_callback()
                    
                    # 确保IP地址是最新的（从服务器获取wlan0 IP）
                    if 'system_info' in status_data:
                        # 从WebServer获取IP（优先wlan0）
                        actual_ip = self._get_actual_ip()
                        status_data['system_info']['ip_address'] = actual_ip
                        
                    return JSONResponse(content=status_data)
                else:
                    raise HTTPException(status_code=503, detail="Status callback not available")
            except Exception as e:
                self.logger.error(f"获取状态失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/status/nodes")
        async def get_nodes_status():
            """获取节点状态"""
            try:
                if self.status_callback:
                    status_data = self.status_callback()
                    nodes_status = status_data.get('nodes', {})
                    return JSONResponse(content=nodes_status)
                else:
                    raise HTTPException(status_code=503, detail="Status callback not available")
            except Exception as e:
                self.logger.error(f"获取节点状态失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/status/channels")
        async def get_channels_status():
            """获取通道状态"""
            try:
                if self.status_callback:
                    status_data = self.status_callback()
                    channels_status = status_data.get('channels', {})
                    return JSONResponse(content=channels_status)
                else:
                    raise HTTPException(status_code=503, detail="Status callback not available")
            except Exception as e:
                self.logger.error(f"获取通道状态失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/status/services")
        async def get_services_status():
            """获取服务状态"""
            try:
                if self.status_callback:
                    status_data = self.status_callback()
                    services_status = status_data.get('services', {})
                    return JSONResponse(content=services_status)
                else:
                    raise HTTPException(status_code=503, detail="Status callback not available")
            except Exception as e:
                self.logger.error(f"获取服务状态失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/status/system")
        async def get_system_info():
            """获取系统信息"""
            try:
                if self.status_callback:
                    status_data = self.status_callback()
                    system_info = status_data.get('system_info', {})
                    return JSONResponse(content=system_info)
                else:
                    raise HTTPException(status_code=503, detail="Status callback not available")
            except Exception as e:
                self.logger.error(f"获取系统信息失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # ==================== API路由 - 控制操作 ====================
        @self.app.get("/api/control/limits")
        async def get_operation_limits():
            """获取操作限制信息"""
            try:
                if hasattr(self.control_callback, 'get_operation_limits_info'):
                    result = self.control_callback('system', 'get_operation_limits_info', {})
                    return JSONResponse(content=result)
                
                # 默认返回
                return JSONResponse(content={
                    "success": True,
                    "limits": {
                        "max_per_minute": 10,
                        "max_per_hour": 50,
                        "cooldown_seconds": 5
                    },
                    "current_usage": {
                        "minute": 0,
                        "hour": 0,
                        "total": 0
                    }
                })
            except Exception as e:
                self.logger.error(f"获取操作限制失败: {e}")
                return JSONResponse(content={
                    "success": False,
                    "error": str(e)
                })
                
        @self.app.post("/api/control/force_cleanup_with_sigint")
        async def force_cleanup_with_sigint(request: Request):
            """强制清理所有相关进程（使用SIGINT信号）"""
            try:
                data = await request.json() if request.body else {}
                params = data.get('params', {})
                infer_type = params.get('infer_type', 'video')
                
                # 根据类型确定脚本名称
                if infer_type == 'video':
                    script_name = 'video_run_infer.sh'
                    patterns = ['video_multi_dev01', 'video_run_infer.sh']
                elif infer_type == 'rtsp':
                    script_name = 'rtsp_yolo_infer.sh'
                    patterns = ['rtsp_infer_dev01', 'rtsp_yolo_infer.sh']
                else:
                    return JSONResponse(content={
                        "success": False,
                        "error": f"未知的推理类型: {infer_type}"
                    })
                
                # 发送SIGINT信号
                killed_count = 0
                for pattern in patterns:
                    # 查找进程并发送SIGINT
                    cmd = f"pids=$(pgrep -f '{pattern}'); for pid in $pids; do pgid=$(ps -o pgid= $pid | tr -d ' '); if [ -n \"$pgid\" ]; then kill -INT -$pgid 2>/dev/null; echo \"向进程组 $pgid 发送SIGINT信号\"; fi; done"
                    result = self.control_callback('system', 'execute_command', {'command': cmd})
                    if result.get('success'):
                        killed_count += 1
                
                # 等待清理
                time.sleep(3)
                
                # 强制清理任何残留进程
                for pattern in patterns:
                    cmd = f"pkill -9 -f '{pattern}' 2>/dev/null || true"
                    self.control_callback('system', 'execute_command', {'command': cmd})
                
                return JSONResponse(content={
                    "success": True,
                    "killed_count": killed_count,
                    "method": "SIGINT",
                    "message": f"已使用SIGINT信号清理 {infer_type} 类型的所有进程"
                })
                
            except Exception as e:
                self.logger.error(f"强制清理失败: {e}")
                return JSONResponse(content={
                    "success": False,
                    "error": str(e)
                })
                
        @self.app.get("/api/control/mode")
        async def get_system_mode():
            """获取系统运行模式"""
            try:
                if not self.control_callback:
                    return JSONResponse(content={
                        "success": False, 
                        "error": "控制回调未初始化"
                    })
                
                # 调用控制回调函数获取模式
                # result = self.control_callback('system', 'check', {})
                result = self.control_callback('system', 'get_mode', {})
                
                # 从结果中提取模式信息
                if result.get('success'):
                    # 假设结果中包含模式信息
                    mode_info = {
                        "success": True,
                        "mode": result.get('mode', 'development'),
                        "details": result.get('details', {})
                    }
                else:
                    # 降级处理
                    mode_info = {
                        "success": True,
                        "mode": "development",
                        "details": {
                            "operation_mode": "development",
                            "detected_by": "fallback",
                            "environment": "unknown"
                        }
                    }
                
                return JSONResponse(content=mode_info)
                
            except Exception as e:
                self.logger.error(f"获取系统模式失败: {e}")
                return JSONResponse(content={
                    "success": False,
                    "error": str(e),
                    "mode": "development"
                })

        @self.app.get("/api/control/dev_nodes")
        async def get_dev_nodes():
            try:
                # 从 web_server 自身的配置中获取节点别名列表
                node_aliases = self.config.get('node_aliases', {})
                nodes = list(node_aliases.keys())

                if not nodes:
                    return JSONResponse(content={
                        "success": True,
                        "nodes": [],
                        "total_count": 0,
                        "mode": "development",
                        "warning": "没有配置节点"
                    })
                return JSONResponse(content={
                    "success": True,
                    "nodes": nodes,
                    "total_count": len(nodes),
                    "mode": "development"
                })
            except Exception as e:
                return JSONResponse(status_code=500, content={"error": str(e)})

        # ==================== 快速操作相关路由 ====================
        @self.app.post("/api/control/system_check")
        async def system_check_api(request: Request):
            """系统检查"""
            try:
                data = await request.json() if request.body else {}
                params = data.get('params', {})
                operator = data.get('operator', 'system')
                
                if not self.control_callback:
                    return JSONResponse(content={
                        "success": False, 
                        "error": "控制回调未初始化"
                    })
                
                # 调用控制回调执行系统检查
                result = self.control_callback('system', 'check', params)
                
                # 记录操作日志
                self._log_operation('system_check', operator, params, result.get('success', False), result.get('error', ''))
                
                return JSONResponse(content=result)
                
            except Exception as e:
                self.logger.error(f"系统检查失败: {e}")
                return JSONResponse(content={
                    "success": False, 
                    "error": str(e)
                })

        @self.app.post("/api/control/clear_cache")
        async def clear_cache_api(request: Request):
            """清理缓存"""
            try:
                data = await request.json() if request.body else {}
                params = data.get('params', {})
                operator = data.get('operator', 'system')
                
                if not self.control_callback:
                    return JSONResponse(content={
                        "success": False, 
                        "error": "控制回调未初始化"
                    })
                
                # 调用控制回调清理缓存
                result = self.control_callback('system', 'clear_cache', params)
                
                # 记录操作日志
                self._log_operation('clear_cache', operator, params, result.get('success', False), result.get('error', ''))
                
                return JSONResponse(content=result)
                
            except Exception as e:
                self.logger.error(f"清理缓存失败: {e}")
                return JSONResponse(content={
                    "success": False, 
                    "error": str(e)
                })

        # ==================== P2：OPS 统一节点控制（doc/P2 v2，灰度后移除原 /api/control/*） ====================
        def ops_proxy():
            return getattr(self.node, "ops_proxy", None)

        def ops_unavailable():
            return JSONResponse(content={
                "success": False, "error": "ops_proxy 未初始化（ops_integration 未启用）"
            })

        @self.app.get("/api/ops/nodes")
        def ops_nodes():
            """节点运维列表：权威源 OPS /api/nodes + watchdog 状态 + display_map 展示名"""
            proxy = ops_proxy()
            if not proxy:
                return ops_unavailable()
            try:
                return JSONResponse(content=proxy.list_nodes())
            except Exception as e:
                self.logger.error(f"获取 OPS 节点列表失败: {e}")
                return JSONResponse(content={"success": False, "error": str(e), "nodes": []})

        @self.app.post("/api/ops/nodes/{name}/action")
        async def ops_node_action(name: str, request: Request):
            """节点控制：body {action: start|stop|restart} → OPS 执行（协调看门狗）"""
            proxy = ops_proxy()
            if not proxy:
                return ops_unavailable()
            try:
                data = await request.json() if request.body else {}
                action = data.get('action', '')
                result = proxy.execute(name, action)
                self.logger.info(f"[Ops] {action} {name} → {result}")
                return JSONResponse(content=result)
            except Exception as e:
                self.logger.error(f"OPS 节点操作失败 [{name}]: {e}")
                return JSONResponse(content={"success": False, "error": str(e)})

        @self.app.get("/api/ops/status")
        def ops_status():
            """OPS 系统状态（P3 复用）"""
            proxy = ops_proxy()
            if not proxy:
                return ops_unavailable()
            try:
                return JSONResponse(content=proxy.ops_status())
            except Exception as e:
                self.logger.error(f"获取 OPS 状态失败: {e}")
                return JSONResponse(content={"success": False, "error": str(e)})

        @self.app.get("/api/ops/channels")
        def ops_channels():
            """P3 v2：权威通道状态（OPS /api/rtsp/channels，帧新鲜度，doc/P3 v2）"""
            proxy = ops_proxy()
            if not proxy:
                return ops_unavailable()
            try:
                return JSONResponse(content=proxy.channels_status())
            except Exception as e:
                self.logger.error(f"获取 OPS 通道状态失败: {e}")
                return JSONResponse(content={"success": False, "error": str(e)})

        # ==================== 原有的控制API路由 ====================

        @self.app.post("/api/control/execute_command")
        async def execute_command(request: Request):
            """执行命令"""
            try:
                data = await request.json() if request.body else {}
                params = data.get('params', {})
                
                if not self.control_callback:
                    return JSONResponse(content={
                        "success": False, 
                        "error": "控制回调未初始化"
                    })
                
                result = self.control_callback('system', 'execute_command', params)
                return JSONResponse(content=result)
                
            except Exception as e:
                self.logger.error(f"执行命令失败: {e}")
                return JSONResponse(content={
                    "success": False, 
                    "error": str(e)
                })

        @self.app.get("/api/control/stats")
        async def get_control_stats():
            """获取操作统计"""
            try:
                # 从控制执行器获取统计信息
                if self.control_callback:
                    # 正确调用：使用 system.get_stats 而不是 system.get_operation_stats
                    result = self.control_callback('system', 'get_stats', {})
                    if result.get('success'):
                        return JSONResponse(content=result)
                
                # 如果无法获取，返回模拟数据
                return JSONResponse(content={
                    "success": True,
                    "stats": {
                        "total_operations": 0,
                        "successful_operations": 0,
                        "success_rate": 0,
                        "by_action": {}
                    }
                })
            except Exception as e:
                self.logger.error(f"获取操作统计失败: {e}")
                return JSONResponse(content={
                    "success": False,
                    "error": str(e)
                })
        
        @self.app.get("/api/control/logs")
        async def get_control_logs(limit: int = 10):
            """获取操作日志"""
            try:
                # 验证limit参数
                if limit <= 0:
                    limit = 10
                if limit > 100:
                    limit = 100  # 限制最大返回数量
                
                # 从控制执行器获取日志
                if self.control_callback:
                    # 正确调用：使用 system.get_logs 而不是 system.get_operation_logs
                    result = self.control_callback('system', 'get_logs', {'limit': limit})
                    
                    if result and isinstance(result, dict):
                        # 如果已经是字典格式，直接返回
                        return JSONResponse(content=result)
                    elif result and isinstance(result, list):
                        # 如果是列表，转换为正确的字典格式
                        return JSONResponse(content={
                            "success": True,
                            "logs": result,
                            "count": len(result),
                            "limit": limit
                        })
                    else:
                        # 如果无法获取，返回空列表
                        return JSONResponse(content={
                            "success": True,
                            "logs": [],
                            "count": 0,
                            "limit": limit
                        })
                
                # 如果无法获取，返回空列表
                return JSONResponse(content={
                    "success": True,
                    "logs": [],
                    "count": 0,
                    "limit": limit
                })
            except Exception as e:
                self.logger.error(f"获取操作日志失败: {e}")
                return JSONResponse(content={
                    "success": False,
                    "error": str(e),
                    "logs": [],
                    "count": 0
                })
                
        @self.app.get("/api/control/node_config")
        async def get_node_config():
            """返回节点配置（名称、别名、类型）"""
            node_aliases = self.config.get('node_aliases', {})
            node_names_config = self.config.get('node_names', {})  # 已在 web_server_config 中包含
            
            # 根据 node_names 确定每个节点的类型，默认 'unknown'
            node_type_map = {}
            for type_name, info in node_names_config.items():
                for node in info.get('nodes', []):
                    node_type_map[node] = type_name
            
            nodes = []
            for name, alias in node_aliases.items():
                nodes.append({
                    "name": name,
                    "alias": alias,
                    "type": node_type_map.get(name, "unknown")
                })
            return JSONResponse(content={"nodes": nodes, "count": len(nodes)})

        @self.app.get("/api/control/service_config")
        async def get_service_config():
            """返回部署服务列表"""
            services_dict = self.config.get('deployment_services', {})
            services = list(services_dict.values())
            return JSONResponse(content={"services": services, "count": len(services)})
        
        
        
        
        # ==================== API路由 - 告警管理 ====================
        # @self.app.get("/api/alarms")
        # async def get_alarms(limit: int = 100, acknowledged: bool = False):
        #     """获取告警列表"""
        #     try:
        #         if self.alarm_callback:
        #             alarms = self.alarm_callback()
        #             if limit > 0:
        #                 alarms = alarms[:limit]
        #             return JSONResponse(content=alarms)
        #         else:
        #             raise HTTPException(status_code=503, detail="Alarm callback not available")
        #     except Exception as e:
        #         self.logger.error(f"获取告警失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))
        
        # @self.app.get("/api/alarms/stats")
        # async def get_alarm_stats():
        #     """获取告警统计"""
        #     try:
        #         if self.alarm_stats_callback:
        #             stats = self.alarm_stats_callback()
        #             return JSONResponse(content=stats)
        #         else:
        #             # 返回默认统计
        #             return JSONResponse(content={
        #                 "total_alarms": 0,
        #                 "unacknowledged_alarms": 0,
        #                 "unresolved_alarms": 0,
        #                 "by_level": {},
        #                 "by_type": {},
        #                 "by_source": {}
        #             })
        #     except Exception as e:
        #         self.logger.error(f"获取告警统计失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))
        
        # @self.app.get("/api/alarms/history")
        # async def get_alarm_history(hours: int = 24):
        #     """获取告警历史"""
        #     try:
        #         return JSONResponse(content={
        #             "hours": [],
        #             "counts": [],
        #             "total": 0
        #         })
        #     except Exception as e:
        #         self.logger.error(f"获取告警历史失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))
        
        # @self.app.post("/api/alarms/{alarm_id}/acknowledge")
        # async def acknowledge_alarm(alarm_id: str, request: Request):
        #     """确认告警"""
        #     try:
        #         data = await request.json() if request.body else {}
        #         username = data.get('username', 'system')
                
        #         if self.alarm_acknowledge_callback:
        #             success = self.alarm_acknowledge_callback(alarm_id, username, data.get('notes', ''))
        #             return JSONResponse(content={"success": success, "alarm_id": alarm_id})
        #         else:
        #             raise HTTPException(status_code=503, detail="Alarm acknowledge callback not available")
        #     except Exception as e:
        #         self.logger.error(f"确认告警失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))
        
        # @self.app.post("/api/alarms/{alarm_id}/resolve")
        # async def resolve_alarm(alarm_id: str):
        #     """解决告警"""
        #     try:
        #         if self.alarm_resolve_callback:
        #             success = self.alarm_resolve_callback(alarm_id)
        #             return JSONResponse(content={"success": success, "alarm_id": alarm_id})
        #         else:
        #             raise HTTPException(status_code=503, detail="Alarm resolve callback not available")
        #     except Exception as e:
        #         self.logger.error(f"解决告警失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))
        
        # @self.app.delete("/api/alarms")
        # async def clear_alarms(alarm_type: Optional[str] = None, 
        #                       level: Optional[str] = None, 
        #                       resolved_only: bool = False):
        #     """清理告警"""
        #     try:
        #         if self.alarm_clear_callback:
        #             count = self.alarm_clear_callback()
        #             return JSONResponse(content={"success": True, "cleared_count": count})
        #         else:
        #             raise HTTPException(status_code=503, detail="Alarm clear callback not available")
        #     except Exception as e:
        #         self.logger.error(f"清理告警失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))
        
        
        # ==================== 标定模块路由 ====================
        @self.app.get("/calibration", response_class=HTMLResponse)
        async def calibration_page(request: Request):
            # P4 v2：打开标定页时触发 OPS 标定配置同步（防抖 30s，doc/P4 §9）
            # 注：_ensure_calibration_sync 为 __init__ 内局部函数（闭包），非实例方法
            _ensure_calibration_sync()
            if self.templates:
                return self.templates.TemplateResponse(request, "calibration.html", {})
            return HTMLResponse("<h1>标定页面未找到</h1>")

        # ===== P4 v2：标定配置 OPS 自动同步（doc/P4 §9，防抖） =====
        def _ensure_calibration_sync():
            now = time.time()
            if getattr(self, '_cal_sync_ts', 0) and (now - self._cal_sync_ts) < 30:
                return
            self._cal_sync_ts = now
            try:
                mgr = getattr(self.node, 'image_manager', None)
                proxy = getattr(self.node, 'ops_proxy', None)
                if mgr and proxy:
                    mgr.sync_from_ops(proxy)
            except Exception:
                pass

        @self.app.get("/api/calibration/channel_count")
        async def get_calibration_channel_count():
            # P4：OPS 代理优先（doc/P4），OPS 不可达降级 image_manager
            proxy = getattr(self.node, 'ops_proxy', None)
            if proxy:
                r = proxy.calibration("GET", "/api/calibration/channel_count")
                if isinstance(r, dict) and "count" in r:
                    return {"count": r["count"]}
            mgr = getattr(self.node, 'image_manager', None)
            if mgr:
                return {"count": mgr.channel_count}
            return JSONResponse(status_code=503, content={"error": "image manager not ready"})

        @self.app.get("/api/calibration/areas/{channel_id}")
        async def get_calibration_areas(channel_id: int):
            # P4：OPS 代理优先（doc/P4），OPS 不可达降级 image_manager
            proxy = getattr(self.node, 'ops_proxy', None)
            if proxy:
                r = proxy.calibration("GET", "/api/calibration/areas/%d" % channel_id)
                if isinstance(r, dict) and "areas" in r:
                    return JSONResponse(content={"areas": r["areas"]})
            mgr = getattr(self.node, 'image_manager', None)
            if not mgr:
                raise HTTPException(status_code=503)
            areas = mgr.get_inference_areas(channel_id)
            if areas is None:
                self.logger.warning(f"Failed to get areas for channel {channel_id}, returning empty list")
                areas = []   # 返回空列表，不再报500
            return JSONResponse(content={"areas": areas})

        @self.app.post("/api/calibration/save")
        async def save_calibration(data: dict):
            channel_id = data.get("channel_id")
            areas = data.get("areas", [])
            if channel_id is None:
                raise HTTPException(status_code=400)
            # P4：OPS 代理优先（doc/P4），OPS 不可达降级 image_manager
            proxy = getattr(self.node, 'ops_proxy', None)
            if proxy:
                r = proxy.calibration("POST", "/api/calibration/save",
                                      body={"channel_id": channel_id, "areas": areas})
                if isinstance(r, dict) and r.get("success", False):
                    return {"status": "success"}
                if isinstance(r, dict) and r.get("success") is False and not r.get("offline"):
                    return {"status": "failure", "error": r.get("error", "")}
            mgr = getattr(self.node, 'image_manager', None)
            if not mgr:
                raise HTTPException(status_code=503)
            success = mgr.save_calibration(channel_id, areas)
            return {"status": "success" if success else "failure"}

        @self.app.get("/api/calibration/frame/{channel_id}")
        async def get_calibration_frame(channel_id: int):
            if not CV2_AVAILABLE:
                raise HTTPException(status_code=503, detail="标定模块不可用：未安装 OpenCV (python3-opencv)")
            # P4：OPS 代理优先（raw 二进制 JPEG，doc/P4），OPS 不可达降级 image_manager
            proxy = getattr(self.node, 'ops_proxy', None)
            if proxy:
                data = proxy.calibration("GET", "/api/calibration/frame/%d" % channel_id, raw=True)
                if isinstance(data, bytes) and len(data) > 0:
                    return Response(content=data, media_type="image/jpeg")
            mgr = getattr(self.node, 'image_manager', None)
            if not mgr:
                raise HTTPException(status_code=503)
            frame = mgr.get_latest_frame(channel_id)
            if frame is None:
                return Response(status_code=204)
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return Response(content=buffer.tobytes(), media_type="image/jpeg")

        @self.app.get("/api/calibration/inference_param/{name}")
        async def get_inference_param(name: str):
            # P4：OPS 代理优先（doc/P4），OPS 不可达降级 image_manager
            proxy = getattr(self.node, 'ops_proxy', None)
            if proxy:
                r = proxy.calibration("GET", "/api/calibration/inference_param/%s" % name)
                if isinstance(r, dict) and "value" in r:
                    return {"name": name, "value": r["value"]}
            mgr = getattr(self.node, 'image_manager', None)
            if not mgr:
                raise HTTPException(status_code=503)
            val = mgr.get_inference_param(name)
            return {"name": name, "value": val}

        @self.app.post("/api/calibration/set_param")
        async def set_inference_param(data: dict):
            name = data.get("name")
            value = data.get("value")
            if not name:
                raise HTTPException(status_code=400)
            # P4：OPS 代理优先（doc/P4），OPS 不可达降级 image_manager
            proxy = getattr(self.node, 'ops_proxy', None)
            if proxy:
                r = proxy.calibration("POST", "/api/calibration/set_param",
                                      body={"name": name, "value": value})
                if isinstance(r, dict) and r.get("success", False):
                    return {"status": "success"}
                if isinstance(r, dict) and r.get("success") is False and not r.get("offline"):
                    return {"status": "failure", "error": r.get("error", "")}
            mgr = getattr(self.node, 'image_manager', None)
            if not mgr:
                raise HTTPException(status_code=503)
            success = mgr.set_inference_param(name, value)
            return {"status": "success" if success else "failure"}

        @self.app.websocket("/ws/calibration/{channel_id}")
        async def calibration_ws(websocket: WebSocket, channel_id: int):
            await websocket.accept()
            loop = asyncio.get_running_loop()
            mgr = getattr(self.node, 'image_manager', None)
           
            # ========== 清除该通道缓存，丢弃旧帧 ==========
            if mgr:
                mgr.clear_channel_cache(channel_id, renew_sub=True)


            JPEG_QUALITY = 70
            POLL_INTERVAL = 0.1          # 100ms 轮询一次
            last_sent_ts = 0.0           # 重置发送时间戳

            try:
                while True:
                    await asyncio.sleep(POLL_INTERVAL)

                    # 检查是否有比上次发送更新的帧
                    frame, ts = mgr.get_frame_and_ts_if_newer(channel_id, last_sent_ts)
                    if frame is not None:
                        last_sent_ts = ts

                        # 无 OpenCV 时跳过编码（标定模块非核心）
                        if not CV2_AVAILABLE:
                            continue

                        # 发送帧元数据
                        meta = {
                            "type": "frame_meta",
                            "ts": ts,
                            "server_send_time": time.time()
                        }
                        await websocket.send_text(json.dumps(meta))

                        # 编码并发送 JPEG 帧
                        buffer = await loop.run_in_executor(
                            self._executor,
                            lambda f=frame.copy(): cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1]
                        )
                        await websocket.send_bytes(buffer.tobytes())

            except WebSocketDisconnect:
                self.logger.info(f"WebSocket disconnected for channel {channel_id}")
            except Exception as e:
                # 检查是否是正常的关闭码
                is_normal_close = False
                if hasattr(e, 'code'):
                    is_normal_close = e.code in (1000, 1001)
                elif '1001' in str(e) or '1000' in str(e):
                    is_normal_close = True

                if is_normal_close:
                    self.logger.info(f"WebSocket closed normally for channel {channel_id}: {e}")
                else:
                    self.logger.error(f"WebSocket error for channel {channel_id}: {e}")
            finally:
                # 连接断开后清除该通道缓存，避免下次打开显示旧画面
                if mgr:                    
                    self.logger.info(f"WebSocket channel {channel_id} disconnected, clearing frame cache...")
                    mgr.clear_channel_cache(channel_id, renew_sub=False)
                    self.logger.info(f"Frame cache cleared for channel {channel_id}")
        
        # ==================== WebSocket路由 ====================
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket连接端点 - 修复版"""
            # 保存 uvicorn 主事件循环（只需执行一次）
            if self.manager._event_loop is None:
                self.manager.set_event_loop(asyncio.get_running_loop())
                
                
            await websocket.accept()
            
            # 添加连接
            with self.manager._lock:
                self.manager.active_connections.append(websocket)
            
            connection_count = len(self.manager.active_connections)
            self.logger.info(f"WebSocket连接建立，当前连接数: {connection_count}")
            
            try:
                # 发送欢迎消息
                await websocket.send_json({
                    "type": "welcome",
                    "message": "WebSocket连接成功",
                    "timestamp": time.time(),
                    "connections": connection_count
                })
                
                # 保持连接
                while True:
                    try:
                        # 接收消息（带超时）
                        data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                        
                        if data.strip() == "ping":
                            await websocket.send_text("pong")
                        
                    except asyncio.TimeoutError:
                        # 心跳保持
                        await websocket.send_json({
                            "type": "heartbeat",
                            "timestamp": time.time()
                        })
                    except WebSocketDisconnect:
                        break
                        
            except Exception as e:
                self.logger.debug(f"WebSocket处理异常: {e}")
            finally:
                # 清理连接
                with self.manager._lock:
                    if websocket in self.manager.active_connections:
                        self.manager.active_connections.remove(websocket)
                
                self.logger.info(f"WebSocket连接关闭，剩余连接数: {len(self.manager.active_connections)}")
                
        
        
        # ==================== 健康检查路由 ====================
        @self.app.get("/health")
        async def health_check():
            """健康检查"""
            return JSONResponse(content={
                "status": "healthy" if self.running else "stopped",
                "server": f"{self.config.get('host', '0.0.0.0')}:{self.config.get('port', 9183)}",
                "running": self.running,
                "uptime": time.time() - self._start_time if self.running else 0,
                "connections": len(self.manager.active_connections)
            })
            
    # ═══════════════════════════════════════════════════════
    # 业务可视化 / 配置热加载 / 任务操作 路由
    # ═══════════════════════════════════════════════════════
    def _setup_business_routes(self):
        """业务/配置/任务路由（v3.0）— 通过 node 上挂载的组件获取数据"""
        import json as _json

        def _bc():
            return getattr(self.node, 'business_collector', None)
        def _cm():
            return getattr(self.node, 'config_manager', None)
        def _tc():
            return getattr(self.node, 'task_controller', None)

        def _err(what: str):
            return JSONResponse(status_code=503,
                content={"success": False, "error": f"{what}未就绪"})

        # ===== 配置管理路由 =====
        @self.app.get("/api/config/all")
        async def get_config_all():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, "data": cm.get_all_config()})

        @self.app.get("/api/config/bay")
        async def get_bay_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, **cm.get_bay_config()})

        @self.app.put("/api/config/bay")
        async def set_bay_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            return JSONResponse(content=cm.apply_config('bay_configs', data.get('mappings', {})))

        @self.app.get("/api/config/dest")
        async def get_dest_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, **cm.get_dest_config()})

        @self.app.put("/api/config/dest")
        async def set_dest_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            return JSONResponse(content=cm.apply_config('dest_bay_configs', data.get('mappings', {})))

        @self.app.get("/api/config/schedule")
        async def get_schedule_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, **cm.get_schedule_config()})

        @self.app.put("/api/config/schedule")
        async def set_schedule_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            value = data.get('schedules') if 'schedules' in data else data
            return JSONResponse(content=cm.apply_config('work_schedule', value))

        @self.app.get("/api/config/pairs")
        async def get_pairs_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, **cm.get_pair_overrides()})

        @self.app.put("/api/config/pairs")
        async def set_pairs_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            return JSONResponse(content=cm.apply_config('pair_overrides', data.get('mappings', {})))

        @self.app.get("/api/config/policy")
        async def get_policy_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, **cm.get_pairing_policy()})

        @self.app.put("/api/config/policy")
        async def set_policy_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            return JSONResponse(content=cm.apply_config('pairing_policy', data.get('policy', {})))

        @self.app.get("/api/config/params")
        async def get_params_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, **cm.get_params_config()})

        @self.app.put("/api/config/params")
        async def set_params_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            return JSONResponse(content=cm.apply_params(data.get('params', {})))

        # ── doc/52 阶段2：触发机制/状态轮询配置热加载端点（持久化+事件驱动生效） ──
        TRIGGER_SECTIONS = ('max_total_tasks', 'max_tasks_per_scan', 'aging_ttl',
                            'scan_interval', 'max_queue_size', 'dispatch_per_round',
                            'src_scan_order', 'agv', 'bind')
        POLLER_SECTIONS = ('robot_poll_interval', 'dest_poll_interval',
                           'agv_status_mapping')

        @self.app.get("/api/config/trigger")
        async def get_trigger_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            return JSONResponse(content={"success": True, "data": cm.get_trigger_config()})

        @self.app.put("/api/config/trigger")
        async def set_trigger_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            applied, rejected = [], {}
            for section in TRIGGER_SECTIONS:
                if section not in data:
                    continue
                res = cm.apply_config(section, data[section])
                if res.get('success'):
                    applied.append(section)
                else:
                    rejected[section] = res.get('error')
            return JSONResponse(content={
                'success': not rejected, 'applied': applied, 'rejected': rejected,
                'message': f'触发配置更新: {applied}' if applied else '无可更新配置段'})

        @self.app.get("/api/config/status_poller")
        async def get_status_poller_config():
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = cm.get_trigger_config()
            return JSONResponse(content={"success": True, "data": {
                k: data.get(k) for k in POLLER_SECTIONS}})

        @self.app.put("/api/config/status_poller")
        async def set_status_poller_config(request: Request):
            cm = _cm()
            if not cm: return _err("配置管理器")
            data = await request.json()
            applied, rejected = [], {}
            for section in POLLER_SECTIONS:
                if section not in data:
                    continue
                res = cm.apply_config(section, data[section])
                if res.get('success'):
                    applied.append(section)
                else:
                    rejected[section] = res.get('error')
            return JSONResponse(content={
                'success': not rejected, 'applied': applied, 'rejected': rejected,
                'message': f'状态轮询配置更新: {applied}' if applied else '无可更新配置段'})

        # ===== 业务只读路由 =====
        @self.app.get("/api/business/summary")
        async def get_business_summary():
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content=bc.collect_business_status())

        @self.app.get("/api/bay/status")
        async def get_bay_status():
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content={"success": True, **bc.get_bay_status()})

        @self.app.get("/api/dest/status")
        async def get_dest_status():
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content={"success": True, **bc.get_dest_status()})

        @self.app.get("/api/agv/status")
        async def get_agv_status():
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content={"success": True, **bc.get_agv_status()})

        @self.app.get("/api/task/queue")
        async def get_task_queue():
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content={"success": True, **bc.get_task_queue_data()})

        @self.app.get("/api/task/instances")
        async def get_task_instances():
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content={"success": True, **bc.get_active_instances()})

        @self.app.get("/api/task/stats")
        async def get_task_stats():
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content={"success": True, **bc.get_task_statistics()})

        @self.app.get("/api/task/history")
        async def get_task_history(limit: int = 50, offset: int = 0):
            bc = _bc()
            if not bc: return _err("业务采集器")
            return JSONResponse(content={
                "success": True,
                **bc.get_task_history(limit=limit, offset=offset)
            })

        # ===== 任务人工操作路由 =====
        @self.app.post("/api/task/control")
        async def task_control_api(request: Request):
            tc = _tc()
            if not tc: return _err("任务控制器")
            data = await request.json()
            return JSONResponse(content=tc.task_control(
                operation=data.get('operation', 'query'),
                task_id=data.get('task_id', ''),
                src_bay=data.get('src_bay', ''),
                dst_bay=data.get('dst_bay', ''),
                robot_id=data.get('robot_id', 0),
                cargo_type=data.get('cargo_type', 1),
            ))

        # ===== 告警管理路由（新增 — 启用告警模块后的数据源）=====
        @self.app.get("/api/alarms")
        async def get_alarms(limit: int = 100, acknowledged: bool = False):
            wm = getattr(self.node, 'web_monitor', None)
            if not wm: return _err("Web监控插件")
            alarms = wm.get_alarms(limit=limit, include_acknowledged=acknowledged)
            return JSONResponse(content={"success": True, "alarms": alarms})

        @self.app.get("/api/alarms/stats")
        async def get_alarm_stats():
            wm = getattr(self.node, 'web_monitor', None)
            if not wm: return _err("Web监控插件")
            return JSONResponse(content={"success": True, **wm.get_alarm_stats()})

        @self.app.post("/api/alarms/acknowledge")
        async def acknowledge_alarm(request: Request):
            wm = getattr(self.node, 'web_monitor', None)
            if not wm: return _err("Web监控插件")
            data = await request.json()
            ok = wm.acknowledge_alarm(
                alarm_id=data.get('alarm_id', ''),
                username=data.get('username', 'system'),
                notes=data.get('notes', ''),
            )
            return JSONResponse(content={"success": ok})

        @self.app.post("/api/alarms/resolve")
        async def resolve_alarm(request: Request):
            wm = getattr(self.node, 'web_monitor', None)
            if not wm: return _err("Web监控插件")
            data = await request.json()
            ok = wm.resolve_alarm(alarm_id=data.get('alarm_id', ''))
            return JSONResponse(content={"success": ok})

        @self.app.post("/api/alarms/clear")
        async def clear_alarms():
            wm = getattr(self.node, 'web_monitor', None)
            if not wm: return _err("Web监控插件")
            count = wm.clear_alarms()
            return JSONResponse(content={"success": True, "cleared": count})

        self.logger.info("✅ 业务/配置/任务/告警路由注册完成（14+5 端点）")
    
    def _start_websocket_broadcast(self):
        """启动WebSocket广播线程 - 使用uvicorn主事件循环"""
        def broadcast_loop():
            last_broadcast_time = 0
            broadcast_interval = self.config.get("broadcast_interval", 10.0)
            while self.running:
                try:
                    current_time = time.time()
                    if current_time - last_broadcast_time >= broadcast_interval:
                        if self.status_callback:
                            status_data = self.status_callback()
                            message = {
                                "type": "status_update",
                                "timestamp": current_time,
                                "data": status_data
                            }
                            loop = self.manager._event_loop
                            if loop and not loop.is_closed():
                                asyncio.run_coroutine_threadsafe(
                                    self.manager.broadcast_json(message),
                                    loop
                                )
                            else:
                                self.logger.warning("uvicorn主事件循环不可用，跳过定时广播")
                            last_broadcast_time = current_time
                    time.sleep(1)
                except Exception as e:
                    self.logger.error(f"WebSocket广播错误: {e}")
                    time.sleep(5)

        self._broadcast_thread = threading.Thread(target=broadcast_loop, daemon=True)
        self._broadcast_thread.start()
    
    def _broadcast_to_all(self, message: dict):
        """广播消息到所有连接 - 同步版本"""
        import json
        message_str = json.dumps(message, ensure_ascii=False)
        disconnected = []
        
        for connection in self.manager.active_connections:
            try:
                # 在单独的线程中发送
                asyncio.run_coroutine_threadsafe(
                    connection.send_text(message_str),
                    asyncio.get_event_loop()
                )
            except Exception:
                disconnected.append(connection)
        
        # 移除断开的连接
        for connection in disconnected:
            if connection in self.manager.active_connections:
                self.manager.active_connections.remove(connection)
    
    def _start_alarm_check(self):
        """启动告警检查线程"""
        def alarm_check_loop():
            last_check_time = 0
            check_interval = self.config.get("alarm_check_interval", 10.0)
            
            while self.running:
                try:
                    current_time = time.time()
                    
                    if current_time - last_check_time >= check_interval:
                        try:
                            if self.alarm_callback:
                                alarms = self.alarm_callback()
                                unacknowledged = sum(1 for a in alarms if not a.get("acknowledged", False))
                                
                                message = {
                                    "type": "alarm_update",
                                    "timestamp": current_time,
                                    "count": unacknowledged
                                }
                                
                                self._broadcast_to_all(message)
                        except Exception as e:
                            self.logger.debug(f"获取告警失败: {e}")
                        
                        last_check_time = current_time
                    
                    time.sleep(5)
                    
                except Exception as e:
                    self.logger.error(f"告警检查错误: {e}")
                    time.sleep(10)
        
        self._alarm_check_thread = threading.Thread(target=alarm_check_loop, daemon=True)
        self._alarm_check_thread.start()
        
    def _get_actual_ip(self):
        """获取实际的监听IP地址 - 返回绑定的IP"""
        try:
            # 首先返回绑定的IP地址
            if self.host and self.host != '0.0.0.0':
                self.logger.info(f"返回绑定的IP地址: {self.host}")
                return self.host
            
            # 如果绑定的不是特定IP（0.0.0.0），则获取配置接口的IP
            network_interface = self.config.get('network_interface', 'wlan0')
            
            try:
                import netifaces
                if network_interface in netifaces.interfaces():
                    addresses = netifaces.ifaddresses(network_interface)
                    if netifaces.AF_INET in addresses:
                        ip_info = addresses[netifaces.AF_INET][0]
                        ip_addr = ip_info.get('addr')
                        if ip_addr and ip_addr != '127.0.0.1':
                            self.logger.info(f"获取到{network_interface} IP地址: {ip_addr}")
                            return ip_addr
            except Exception as e:
                self.logger.debug(f"使用配置接口获取IP失败: {e}")
            
            # 备选方法：通过socket获取
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.1)
                s.bind(('', 0))
                ip = s.getsockname()[0]
                s.close()
                
                if ip and ip != '0.0.0.0' and ip != '127.0.0.1':
                    self.logger.info(f"通过socket绑定获取IP: {ip}")
                    return ip
            except Exception as e:
                self.logger.debug(f"通过socket获取IP失败: {e}")
            
            # 最后的备选方法：使用gethostname
            try:
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
                if ip and ip != '127.0.0.1':
                    self.logger.info(f"通过主机名解析获取IP: {ip}")
                    return ip
            except Exception as e:
                self.logger.debug(f"通过主机名解析获取IP失败: {e}")
            
            # 如果所有方法都失败，使用回退IP
            fallback_ip = '127.0.0.1'
            self.logger.warning(f"所有IP获取方法失败，使用回退地址: {fallback_ip}")
            return fallback_ip
            
        except Exception as e:
            self.logger.error(f"获取实际IP失败: {e}")
            return '127.0.0.1'
        
    
    def _log_operation(self, action: str, operator: str, params: dict, success: bool, error: str = ""):
        """记录操作日志"""
        log_entry = {
            "timestamp": time.time(),
            "action": action,
            "operator": operator,
            "params": params,
            "success": success,
            "error": error,
            "details": f"{action}操作{'成功' if success else '失败'}"
        }
        
        # 存储日志（这里可以存储到数据库或文件中）
        self._operation_logs.append(log_entry)
        
        # 限制日志数量，最多保留1000条
        if len(self._operation_logs) > 1000:
            self._operation_logs = self._operation_logs[-1000:]
        
        self.logger.info(f"操作记录: {action} by {operator} - {'成功' if success else '失败'}")  
        
        
    def get_operation_stats(self):
        """获取操作统计"""
        with self._lock:
            total_ops = len(self._operation_logs)
            successful_ops = sum(1 for log in self._operation_logs if log.get('success', False))
            success_rate = (successful_ops / total_ops * 100) if total_ops > 0 else 0
            
            # 按操作类型统计
            by_action = {}
            for log in self._operation_logs:
                action = log.get('action', 'unknown')
                by_action[action] = by_action.get(action, 0) + 1
            
            return {
                "success": True,
                "stats": {
                    "total_operations": total_ops,
                    "successful_operations": successful_ops,
                    "success_rate": success_rate,
                    "by_action": by_action
                }
            }  
            
    
    def get_operation_logs(self, limit: int = 10):
        """获取操作日志 - 始终返回一致的格式"""
        with self._lock:
            try:
                # 验证limit参数
                if limit <= 0:
                    limit = 10
                if limit > 100:
                    limit = 100
                
                # 获取所有日志的副本
                all_logs = self._operation_logs.copy()
                
                # 如果日志为空，返回空数组但结构一致
                if not all_logs:
                    return {
                        "success": True,
                        "logs": [],
                        "count": 0,
                        "limit": limit,
                        "total": 0
                    }
                
                # 获取指定数量的最新日志（从最新到最旧）
                logs = all_logs[-limit:] if len(all_logs) > limit else all_logs
                
                # 反转顺序，让最新的在最前面
                logs_reversed = list(reversed(logs))
                
                # 统一返回格式
                return {
                    "success": True,
                    "logs": logs_reversed,
                    "count": len(logs_reversed),
                    "limit": limit,
                    "total": len(all_logs)
                }
                    
            except Exception as e:
                self.logger.error(f"获取操作日志失败: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "logs": [],
                    "count": 0,
                    "limit": limit,
                    "total": 0
                }
    
        
    def start(self):
        """启动Web服务器 - 修复版本"""
        if self.running:
            self.logger.warning("Web服务器已在运行")
            return True
        
        try:
            # 获取主机配置
            host = self.config.get('host', '0.0.0.0')
            port = self.config.get('port', 9183)
            network_interface = self.config.get('network_interface', 'wlan0')
            self.logger.info(f"启动Web服务器配置: host={host}, port={port}")
            
            # 详细记录网络配置
            self.logger.info(f"Web服务器配置:")
            self.logger.info(f"  - 网络接口: {network_interface}")
            self.logger.info(f"  - 监听地址: {host}:{port}")
            
            # 获取接口信息用于日志
            if host != '0.0.0.0':
                self.logger.info(f"  - 绑定到特定IP: {host}")
            else:
                self.logger.info(f"  - 监听所有接口 (0.0.0.0)")
            
            # 检查并安装WebSocket依赖
            self._check_websocket_deps()
            
            def run_server():
                try:
                    self.logger.info(f"启动Web服务器线程: {host}:{port}")
                    
                    # 配置uvicorn，明确启用WebSocket支持
                    config = uvicorn.Config(
                        app=self.app,
                        host=host,  # 使用配置的host
                        port=port,
                        log_level="info",
                        access_log=True,
                        reload=False,
                        # WebSocket关键配置
                        ws='auto',  # 自动选择WebSocket实现
                        ws_ping_interval=20,
                        ws_ping_timeout=20,
                        ws_max_size=10485760,
                        lifespan='auto',
                    )
                    
                    self._uvicorn_server = uvicorn.Server(config)
                    self._uvicorn_server.run()
                    
                except Exception as e:
                    self.logger.error(f"Web服务器运行错误: {e}")
            
            # 创建并启动线程
            self.server_thread = threading.Thread(
                target=run_server, 
                daemon=True,
                name="WebServer"
            )
            self.server_thread.start()
            
            # 等待服务器启动
            max_wait = 15
            for i in range(max_wait):
                time.sleep(1)
                if self._check_server_running(host, port):
                    self.running = True
                    self.logger.info(f"服务器启动成功！耗时 {i+1} 秒")
                    break
                else:
                    self.logger.info(f"等待服务器启动... {i+1}/{max_wait}")
            else:
                self.logger.error("服务器启动超时")
                return False
            
            # 打印启动信息
            self._print_server_info(host, port)
            
            return True
            
        except Exception as e:
            self.logger.error(f"启动Web服务器失败: {e}")
            return False

    def _check_websocket_deps(self):
        """检查WebSocket依赖"""
        try:
            import websockets
            self.logger.info(f"WebSocket库已安装: websockets {websockets.__version__}")
            return True
        except ImportError:
            self.logger.warning("WebSocket库未安装，将使用兼容模式")
            self.logger.warning("建议运行: pip install 'uvicorn[standard]'")
            return False

    def _check_server_running(self, host: str, port: int) -> bool:
        """检查服务器是否运行"""
        try:
            import requests
            response = requests.get(f"http://{host}:{port}/health", timeout=2)
            return response.status_code == 200
        except:
            return False
        
    def _print_server_info(self, host: str, port: int):
        """打印服务器信息"""
        logger = self.logger
        
        # 获取实际IP用于显示
        actual_ip = self._get_actual_ip()
        server_url = f"http://{actual_ip}:{port}"
        
        # 获取网络接口信息
        network_interface = self.config.get('network_interface', 'wlan0')
        interface_desc = f" (接口: {network_interface})"
        
        info_lines = [
            "=" * 60,
            "🌐 Web监控服务器已启动",
            "=" * 60,
            f"📡 监听地址: {host}:{port}",
            f"🌍 访问地址: {server_url}{interface_desc}",
            "",
            "🔍 主要接口:",
            f"  1. 仪表盘: {server_url}/",
            f"  2. 状态监控: {server_url}/monitor",
            f"  3. 运维控制: {server_url}/control",
            f"  4. 系统状态: {server_url}/api/status",
            f"  5. API文档: {server_url}/api/docs",
            f"  6. WebSocket: ws://{actual_ip}:{port}/ws",
            "",
            "⚙️ 系统信息:",
            f"  版本: 2.0.0",
            f"  模式: {self.config.get('operation_mode', 'development')}",
            f"  网络接口: {network_interface}",
            f"  调试模式: {self.config.get('debug', False)}",
            "=" * 60
        ]
        
        for line in info_lines:
            logger.info(line)  
            
    def stop(self):
        """停止Web服务器"""
        self.running = False
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        self.logger.info("Web服务器正在停止...")
    
    def is_running(self) -> bool:
        """检查Web服务器是否在运行"""
        return self.running
    
    def get_server_info(self) -> Dict[str, Any]:
        """获取服务器信息"""
        return {
            'running': self.running,
            'config': self.config,
            'connections': len(self.manager.active_connections),
            'uptime': time.time() - self._start_time
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取服务器统计信息"""
        return {
            "connections": len(self.manager.active_connections),
            "uptime": time.time() - self._start_time,
            "running": self.running
        }
    
    def run(self):
        """运行Web服务器（兼容接口）"""
        return self.start()
    
    def get_status_with_limits(self):
        """获取包含操作限制的状态"""
        if self.status_callback:
            status_data = self.status_callback()
            
            # 确保系统信息中包含wlan0 IP
            if 'system_info' in status_data:
                # 获取wlan0 IP
                wlan0_ip = self._get_actual_ip()
                # 更新系统信息中的IP地址
                status_data['system_info']['wlan0_ip_address'] = wlan0_ip
                status_data['system_info']['display_ip'] = wlan0_ip  # 用于显示的IP
            
            # 添加操作限制信息
            if hasattr(self.control_callback, 'get_operation_limits_info'):
                limits_info = self.control_callback('system', 'get_operation_limits_info', {})
                if limits_info.get('success'):
                    status_data['operation_limits'] = limits_info
            
            return status_data
        return {}