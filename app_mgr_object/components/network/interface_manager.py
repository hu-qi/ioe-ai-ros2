#!/usr/bin/env python3
"""
网络接口管理器 - 通用版本
管理网络接口的IP地址和绑定会话
"""

import logging
import netifaces
import requests
from typing import Optional, List, Dict, Any

from .http_adapter import HTTPAdapter
from .exceptions import InvalidConfigurationError
from .network_utils import get_interface_ip


class NetworkInterfaceManager:
    """网络接口管理器，提供接口IP查询和绑定会话创建"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.sessions = {}

    def get_interface_ip(self, interface_name: str) -> Optional[str]:
        """
        获取指定网络接口的IPv4地址

        Args:
            interface_name: 接口名称，如 'eth0', 'wlan0'

        Returns:
            IP地址字符串，如果接口不存在或无IPv4地址则返回None
        """
        try:
            interfaces = netifaces.interfaces()
            if interface_name not in interfaces:
                self.logger.warning(f"网络接口 {interface_name} 不存在")
                return None

            addrs = netifaces.ifaddresses(interface_name)
            if netifaces.AF_INET in addrs:
                ip_info = addrs[netifaces.AF_INET][0]
                ip_address = ip_info.get('addr')
                if ip_address:
                    self.logger.debug(f"接口 {interface_name} IP: {ip_address}")
                    return ip_address
            self.logger.warning(f"接口 {interface_name} 没有IPv4地址")
            return None
        except Exception as e:
            self.logger.error(f"获取接口IP失败: {e}")
            return None

    def create_bound_session(self, interface_name: str) -> requests.Session:
        """
        创建绑定到指定网络接口的requests.Session

        Args:
            interface_name: 网络接口名称

        Returns:
            绑定到该接口的Session对象，如果失败则返回普通Session
        """
        try:
            interface_ip = self.get_interface_ip(interface_name)
            if not interface_ip:
                self.logger.warning(f"无法获取接口 {interface_name} IP，使用默认会话")
                return requests.Session()

            # 自定义适配器以绑定源地址
            class InterfaceAdapter(requests.adapters.HTTPAdapter):
                def __init__(self, source_address, **kwargs):
                    self.source_address = source_address
                    super().__init__(**kwargs)

                def init_poolmanager(self, *args, **kwargs):
                    kwargs['source_address'] = self.source_address
                    super().init_poolmanager(*args, **kwargs)

                def proxy_manager_for(self, *args, **kwargs):
                    kwargs['source_address'] = self.source_address
                    return super().proxy_manager_for(*args, **kwargs)

            session = requests.Session()
            adapter = InterfaceAdapter(source_address=(interface_ip, 0))
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            self.logger.info(f"创建绑定到 {interface_name} 的会话，IP: {interface_ip}")
            return session
        except Exception as e:
            self.logger.error(f"创建绑定会话失败: {e}")
            return requests.Session()

    def clear_session_pool(self):
        """清理会话池"""
        self.sessions.clear()
        self.logger.info("会话池已清理")

    def get_status(self) -> Dict[str, Any]:
        """获取管理器状态"""
        return {
            'session_count': len(self.sessions),
        }


class InterfaceManager:
    """接口管理器，管理API接口定义和调用（需子类实现具体接口）"""

    def __init__(self, http_adapter: HTTPAdapter, interface_name: Optional[str] = None):
        self.adapter = http_adapter
        self.interface_name = interface_name
        self.interface_ip = None
        self.interfaces = {}  # 子类应填充此字典

        if interface_name:
            self._initialize_interface()

    def _initialize_interface(self):
        """初始化接口IP（子类可扩展）"""
        manager = NetworkInterfaceManager(self.adapter.logger)
        self.interface_ip = manager.get_interface_ip(self.interface_name)
        self.adapter.logger.info(f"绑定到接口 {self.interface_name}, IP: {self.interface_ip}")

    def call_interface(self, interface_name: str, data=None, custom_headers=None, **kwargs):
        """
        调用指定接口（需子类实现具体路由）
        此方法为模板方法，子类应重写或使用具体实现
        """
        raise NotImplementedError("子类必须实现 call_interface 方法")

    def list_interfaces(self) -> List[str]:
        """列出所有可用接口"""
        return list(self.interfaces.keys())

    def get_interface_info(self, interface_name: str) -> Dict[str, Any]:
        """获取接口信息"""
        if interface_name not in self.interfaces:
            raise InvalidConfigurationError(f"接口 {interface_name} 不存在")
        return self.interfaces[interface_name]