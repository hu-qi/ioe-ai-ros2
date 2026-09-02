#!/usr/bin/env python3
"""
服务管理器 - 管理ROS2服务
"""

import threading
from typing import Dict, Any, Optional, Callable, List
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.callback_groups import ReentrantCallbackGroup
import traceback


class ServiceManager:
    def __init__(self, node: Node = None):
        self.node = node
        self.logger = node.get_logger() if node else None
        self._services: Dict[str, Any] = {}
        self._lock = threading.RLock()
        if self.logger:
            self.logger.info("服务管理器初始化完成")

    def set_node(self, node: Node):
        self.node = node
        self.logger = node.get_logger() if node else None
        if self.logger:
            self.logger.info("服务管理器节点引用已设置")

    def create_service(self, service_type, service_name: str, callback: Callable,
                       qos_profile=None, callback_group=None) -> bool:
        with self._lock:
            if not self.node:
                if self.logger:
                    self.logger.error("节点引用为None，无法创建服务")
                return False
            if service_name in self._services:
                if self.logger:
                    self.logger.warning(f"服务 {service_name} 已存在")
                return False
            try:
                if callback_group is None:
                    callback_group = ReentrantCallbackGroup()
                if qos_profile is None:
                    qos_profile = QoSProfile(
                        depth=10,
                        reliability=ReliabilityPolicy.RELIABLE,
                        durability=DurabilityPolicy.VOLATILE
                    )
                service = self.node.create_service(
                    srv_type=service_type,
                    srv_name=service_name,
                    callback=callback,
                    qos_profile=qos_profile,
                    callback_group=callback_group
                )
                self._services[service_name] = {
                    'service': service,
                    'type': service_type,
                    'callback': callback,
                    'callback_group': callback_group
                }
                if self.logger:
                    self.logger.info(f"服务创建成功: {service_name}")
                return True
            except Exception as e:
                error_msg = f"创建服务 {service_name} 失败: {e}\n{traceback.format_exc()}"
                if self.logger:
                    self.logger.error(error_msg)
                return False

    def create_trigger_service(self, service_name: str, callback: Callable,
                               response_success: bool = True,
                               response_message: str = "Success") -> bool:
        try:
            from std_srvs.srv import Trigger
            def wrapped_callback(request, response):
                try:
                    if callback:
                        result = callback(request, response)
                        if result is not None:
                            return result
                    response.success = response_success
                    response.message = response_message
                    return response
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"服务 {service_name} 回调执行失败: {e}")
                    response.success = False
                    response.message = f"Service error: {str(e)}"
                    return response
            qos_profile = QoSProfile(
                depth=10,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE
            )
            return self.create_service(Trigger, service_name, wrapped_callback, qos_profile)
        except Exception as e:
            if self.logger:
                self.logger.error(f"创建Trigger服务失败: {e}")
            return False

    def get_service(self, service_name: str):
        with self._lock:
            return self._services.get(service_name)

    def get_all_services(self) -> Dict[str, Any]:
        with self._lock:
            return {
                name: {
                    'type': info['type'].__name__,
                    'callback': info['callback'].__name__ if hasattr(info['callback'], '__name__') else 'unknown'
                }
                for name, info in self._services.items()
            }

    def remove_service(self, service_name: str) -> bool:
        with self._lock:
            if service_name not in self._services:
                if self.logger:
                    self.logger.warning(f"服务 {service_name} 不存在")
                return False
            try:
                del self._services[service_name]
                if self.logger:
                    self.logger.info(f"服务 {service_name} 已移除")
                return True
            except Exception as e:
                if self.logger:
                    self.logger.error(f"移除服务 {service_name} 失败: {e}")
                return False

    def remove_all_services(self):
        with self._lock:
            names = list(self._services.keys())
            for name in names:
                self.remove_service(name)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'service_count': len(self._services),
                'services': list(self._services.keys()),
                'status': 'running'
            }