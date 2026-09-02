#!/usr/bin/env python3
"""
网络插件 - 通用版本
提供网络接口管理和HTTP请求能力
"""

import requests
from typing import Dict, Any, Optional, List

from .base_plugin import BasePlugin
from ..components.network.interface_manager import NetworkInterfaceManager
from ..components.network.exceptions import NetworkError


class NetworkPlugin(BasePlugin):
    """网络插件，封装NetworkInterfaceManager并提供同步HTTP请求"""

    PLUGIN_NAME = "network"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        self.interface_manager: Optional[NetworkInterfaceManager] = None
        self._ros_interface = None
        self._api_interface = None
        self._ros_ip = None
        self._api_ip = None
        # 缓存绑定会话，按接口名称
        self._sessions: Dict[str, requests.Session] = {}

    def _configure_impl(self) -> bool:
        """从参数管理器加载网络配置"""
        try:
            if not hasattr(self.node, 'param_manager'):
                self.logger.error("节点缺少 param_manager，无法加载配置")
                return False

            pm = self.node.param_manager
            self._ros_interface = pm.get_param('ros_network_interface', 'eth0')
            self._api_interface = pm.get_param('api_network_interface', 'eth1')

            self.interface_manager = NetworkInterfaceManager(self.logger)

            # 获取IP地址
            self._ros_ip = self.interface_manager.get_interface_ip(self._ros_interface) or ""
            self._api_ip = self.interface_manager.get_interface_ip(self._api_interface) or ""

            # 将自身挂载到节点，供其他插件访问
            self.node.network_plugin = self

            self.logger.info(f"网络插件配置完成: ROS接口={self._ros_interface} IP={self._ros_ip}, "
                             f"API接口={self._api_interface} IP={self._api_ip}")
            return True
        except Exception as e:
            self.logger.error(f"网络插件配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        """激活时无需额外操作"""
        self.logger.info("网络插件已激活")
        return True

    def _deactivate_impl(self) -> bool:
        """停用时清理所有会话"""
        self.clear_sessions()
        self.logger.info("网络插件已停用")
        return True

    def _cleanup_impl(self) -> bool:
        self.interface_manager = None
        self._sessions.clear()
        return True

    # ---------- 公共接口 ----------
    def get_interface_ip(self, interface_name: str) -> str:
        """获取指定接口的IPv4地址"""
        if self.interface_manager:
            return self.interface_manager.get_interface_ip(interface_name) or ""
        return ""

    def get_ros_ip(self) -> str:
        return self._ros_ip

    def get_api_ip(self) -> str:
        return self._api_ip

    def get_network_config(self) -> Dict[str, str]:
        return {
            'ros_interface': self._ros_interface,
            'ros_ip': self._ros_ip,
            'api_interface': self._api_interface,
            'api_ip': self._api_ip,
        }

    def clear_sessions(self):
        """清理所有缓存的绑定会话"""
        self._sessions.clear()
        if self.interface_manager:
            self.interface_manager.clear_session_pool()
        self.logger.info("所有网络会话已清理")

    def request(self,
                method: str,
                url: str,
                params: Optional[Dict] = None,
                data: Optional[Dict] = None,
                headers: Optional[Dict] = None,
                timeout: float = 30.0,
                interface: Optional[str] = None,
                **kwargs) -> requests.Response:
        """
        发送同步HTTP请求，自动绑定到指定接口（若提供）或使用默认API接口。

        Returns:
            requests.Response 对象

        Raises:
            NetworkError 或其子类
        """
        iface = interface or self._api_interface
        session = self._get_session(iface)
        try:
            resp = session.request(
                method=method.upper(),
                url=url,
                params=params,
                json=data,
                headers=headers,
                timeout=timeout,
                **kwargs
            )
            resp.raise_for_status()  # 非2xx状态码会抛出HTTPError
            return resp
        except requests.exceptions.RequestException as e:
            raise NetworkError(f"HTTP请求失败: {e}") from e

    def _get_session(self, interface: str) -> requests.Session:
        """获取（或创建）绑定到指定接口的会话"""
        if interface not in self._sessions:
            if self.interface_manager:
                self._sessions[interface] = self.interface_manager.create_bound_session(interface)
            else:
                self._sessions[interface] = requests.Session()
        return self._sessions[interface]

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update({
            'ros_interface': self._ros_interface,
            'ros_ip': self._ros_ip,
            'api_interface': self._api_interface,
            'api_ip': self._api_ip,
            'session_count': len(self._sessions),
        })
        return status