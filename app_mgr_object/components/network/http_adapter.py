#!/usr/bin/env python3
"""
HTTP适配器 - 通用版本
支持网络接口绑定、重试、连接池管理
"""

import aiohttp
import asyncio
import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import urljoin

from .exceptions import (
    AuthenticationError,
    AuthorizationError,
    RequestTimeoutError,
    InvalidResponseError,
    ConnectionError,
    NetworkError
)
from .network_utils import get_interface_ip, validate_response


class HTTPAdapter:
    """通用HTTP适配器，支持接口绑定和重试"""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        初始化HTTP适配器

        Args:
            config: 配置字典，包含以下可选字段：
                - base_url: 基础URL
                - request_timeout: 请求超时（秒）
                - connect_timeout: 连接超时（秒）
                - sock_read_timeout: 套接字读取超时（秒）
                - network_interface: 默认网络接口名称
                - max_retries: 默认最大重试次数
                - enable_signature: 是否启用签名（需子类实现）
            logger: 日志记录器，如果不提供则使用标准logging
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        self.base_url = config.get('base_url', '')
        self.max_retries = config.get('max_retries', 3)

        self.timeout = aiohttp.ClientTimeout(
            total=config.get('request_timeout', 30),
            connect=config.get('connect_timeout', 10),
            sock_read=config.get('sock_read_timeout', 30)
        )

        # 会话池管理
        self._sessions: Dict[str, aiohttp.ClientSession] = {}
        self._session_lock = asyncio.Lock()
        self._default_interface = config.get('network_interface')

        self.logger.info(f"HTTP适配器初始化: base_url={self.base_url}, interface={self._default_interface}")

    def _create_connector(self, interface_name: Optional[str] = None) -> aiohttp.TCPConnector:
        """创建TCP连接器，可绑定指定接口"""
        try:
            local_addr = None
            if interface_name:
                ip_address = get_interface_ip(interface_name)
                local_addr = (ip_address, 0)
                self.logger.debug(f"绑定到接口 {interface_name}, IP: {ip_address}")
            elif self._default_interface:
                ip_address = get_interface_ip(self._default_interface)
                local_addr = (ip_address, 0)

            connector_args = {
                'limit': 50,
                'limit_per_host': 10,
                'enable_cleanup_closed': True,
                'ttl_dns_cache': 300,
                'use_dns_cache': True,
            }
            if local_addr:
                connector_args['local_addr'] = local_addr

            return aiohttp.TCPConnector(**connector_args)
        except Exception as e:
            self.logger.warning(f"创建连接器失败: {e}，使用默认配置")
            return aiohttp.TCPConnector()

    async def get_session(self, interface_name: Optional[str] = None) -> aiohttp.ClientSession:
        """获取或创建HTTP会话（按接口隔离）"""
        session_key = interface_name or 'default'

        async with self._session_lock:
            if session_key not in self._sessions or self._sessions[session_key].closed:
                connector = self._create_connector(interface_name)
                self._sessions[session_key] = aiohttp.ClientSession(
                    connector=connector,
                    timeout=self.timeout,
                    headers={'User-Agent': 'HTTPAdapter/1.0', 'Accept': 'application/json'}
                )
                self.logger.debug(f"创建新会话: {session_key}")
            return self._sessions[session_key]

    async def close_all(self):
        """关闭所有HTTP会话"""
        async with self._session_lock:
            for key, session in list(self._sessions.items()):
                if not session.closed:
                    await session.close()
                del self._sessions[key]
            self.logger.info("所有HTTP会话已关闭")

    async def request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        retry_count: Optional[int] = None,
        interface_name: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        发送HTTP请求

        Args:
            method: HTTP方法（GET, POST, PUT, DELETE等）
            path: 请求路径（将拼接到base_url后）
            data: 请求体字典
            params: URL查询参数
            headers: 请求头
            retry_count: 重试次数，None则使用默认
            interface_name: 指定网络接口
            **kwargs: 其他aiohttp参数

        Returns:
            解析后的JSON响应字典

        Raises:
            NetworkError 或其子类
        """
        url = urljoin(self.base_url, path)
        request_headers = headers or {}
        if data and method.upper() in ['POST', 'PUT', 'PATCH']:
            request_headers.setdefault('Content-Type', 'application/json;charset=UTF-8')

        retries = retry_count if retry_count is not None else self.max_retries
        last_exception = None

        for attempt in range(retries):
            try:
                session = await self.get_session(interface_name)

                self.logger.debug(f"发送 {method} 请求: {url}")
                if data:
                    self.logger.debug(f"请求数据: {json.dumps(data, indent=2)[:500]}")

                async with session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    headers=request_headers,
                    ssl=False,
                    **kwargs
                ) as response:
                    response_text = await response.text()
                    self.logger.debug(f"响应状态: {response.status}")
                    self.logger.debug(f"响应内容: {response_text[:500]}")

                    if response.status >= 400:
                        error_msg = f"HTTP {response.status}: {response_text}"
                        if response.status == 401:
                            raise AuthenticationError(error_msg)
                        elif response.status == 403:
                            raise AuthorizationError("权限拒绝")
                        elif response.status >= 500:
                            if attempt < retries - 1:
                                wait = 2 ** attempt
                                self.logger.warning(f"服务器错误，等待 {wait}s 后重试...")
                                await asyncio.sleep(wait)
                                continue
                            else:
                                raise NetworkError(f"服务器错误，重试{retries}次后失败")
                        else:
                            raise NetworkError(error_msg)

                    if response_text.strip():
                        try:
                            result = json.loads(response_text)
                        except json.JSONDecodeError:
                            raise InvalidResponseError(f"无效JSON: {response_text[:200]}")
                    else:
                        result = {}

                    if not validate_response(result):
                        self.logger.warning(f"响应结构验证失败: {result}")

                    return result

            except asyncio.TimeoutError:
                last_exception = RequestTimeoutError(f"请求超时: {url}")
                self.logger.error(f"请求超时 (尝试 {attempt+1}/{retries})")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except aiohttp.ClientError as e:
                last_exception = ConnectionError(f"连接错误: {e}")
                self.logger.error(f"连接错误 (尝试 {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except Exception as e:
                last_exception = NetworkError(f"请求异常: {e}")
                self.logger.error(f"请求异常 (尝试 {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue

        raise last_exception or NetworkError("请求失败")

    async def get(self, path: str, **kwargs):
        return await self.request('GET', path, **kwargs)

    async def post(self, path: str, data=None, **kwargs):
        return await self.request('POST', path, data=data, **kwargs)

    async def put(self, path: str, data=None, **kwargs):
        return await self.request('PUT', path, data=data, **kwargs)

    async def delete(self, path: str, data=None, **kwargs):
        return await self.request('DELETE', path, data=data, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_all()

    def get_status(self) -> Dict[str, Any]:
        """获取适配器状态"""
        return {
            'session_count': len(self._sessions),
            'default_interface': self._default_interface,
            'base_url': self.base_url,
        }