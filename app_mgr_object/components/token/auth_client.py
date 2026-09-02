#!/usr/bin/env python3

import requests
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from ..client.session_manager import SessionManager


class AuthClient:
    """认证客户端 - 专门用于处理认证相关的HTTP请求"""
    
    def __init__(self,
                 auth_server_url: str,
                 timeout: float = 10.0,
                 source_interface: str = "eth1",
                 fallback_interface: str = "eth0",
                 max_retries: int = 3,
                 logger=None):
        """
        初始化认证客户端
        
        Args:
            auth_server_url: 认证服务器URL
            timeout: 请求超时时间
            source_interface: 主网络接口
            fallback_interface: 备用网络接口
            max_retries: 最大重试次数
            logger: 日志记录器
        """
        self.auth_server_url = auth_server_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.logger = logger
        
        # 初始化会话管理器
        self.session_manager = SessionManager(
            source_interface=source_interface,
            fallback_interface=fallback_interface,
            timeout=timeout,
            max_retries=max_retries,
            logger=logger
        )
        
        self._log_info("认证客户端初始化完成")
    
    def _log_info(self, message: str):
        """记录信息级别日志"""
        if self.logger:
            if hasattr(self.logger, 'info'):
                self.logger.info(f"[AuthClient] {message}")
            else:
                print(f"[AuthClient INFO] {message}")
        else:
            print(f"[AuthClient INFO] {message}")
    
    def _log_warning(self, message: str):
        """记录警告级别日志"""
        if self.logger:
            if hasattr(self.logger, 'warn'):
                self.logger.warn(f"[AuthClient] {message}")
            else:
                print(f"[AuthClient WARN] {message}")
        else:
            print(f"[AuthClient WARN] {message}")
    
    def _log_error(self, message: str):
        """记录错误级别日志"""
        if self.logger:
            if hasattr(self.logger, 'error'):
                self.logger.error(f"[AuthClient] {message}")
            else:
                print(f"[AuthClient ERROR] {message}")
        else:
            print(f"[AuthClient ERROR] {message}")
    
    def _log_debug(self, message: str):
        """记录调试级别日志"""
        if self.logger:
            if hasattr(self.logger, 'debug'):
                self.logger.debug(f"[AuthClient] {message}")
            else:
                print(f"[AuthClient DEBUG] {message}")
        else:
            print(f"[AuthClient DEBUG] {message}")

    def request_token_by_password(self,
                                 username: str,
                                 password: str,
                                 client_id: str = "default_client",
                                 client_secret: Optional[str] = None,
                                 scope: str = "read write") -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        通过用户名密码获取令牌
        
        Args:
            username: 用户名
            password: 密码
            client_id: 客户端ID
            client_secret: 客户端密钥
            scope: 权限范围
            
        Returns:
            (成功标志, 令牌信息/错误信息)
        """
        try:
            session = self.session_manager.get_session()
            if not session:
                return False, {'error': '无法获取有效的HTTP会话'}
            
            # 准备请求数据
            data = {
                'grant_type': 'password',
                'username': username,
                'password': password,
                'client_id': client_id,
                'scope': scope
            }
            
            if client_secret:
                data['client_secret'] = client_secret
            
            # 发送认证请求
            url = f"{self.auth_server_url}/oauth/token"
            
            self._log_debug(f"请求令牌: {url}")
            
            response = session.post(
                url,
                data=data,
                timeout=self.timeout,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                self._log_info("令牌获取成功")
                return True, token_data
            else:
                error_msg = f"认证失败: HTTP {response.status_code} - {response.text[:200]}"
                self._log_warning(error_msg)
                return False, {'error': error_msg, 'status_code': response.status_code}
                
        except requests.exceptions.ConnectionError as e:
            error_msg = f"连接认证服务器失败: {str(e)}"
            self._log_error(error_msg)
            return False, {'error': error_msg, 'type': 'connection_error'}
        except requests.exceptions.Timeout as e:
            error_msg = f"认证请求超时: {str(e)}"
            self._log_warning(error_msg)
            return False, {'error': error_msg, 'type': 'timeout'}
        except Exception as e:
            error_msg = f"认证请求异常: {str(e)}"
            self._log_error(error_msg)
            return False, {'error': error_msg, 'type': 'unknown'}

    def request_token_by_client_credentials(self,
                                          client_id: str,
                                          client_secret: str,
                                          scope: str = "read write") -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        通过客户端凭证获取令牌
        
        Args:
            client_id: 客户端ID
            client_secret: 客户端密钥
            scope: 权限范围
            
        Returns:
            (成功标志, 令牌信息/错误信息)
        """
        try:
            session = self.session_manager.get_session()
            if not session:
                return False, {'error': '无法获取有效的HTTP会话'}
            
            # 准备请求数据
            data = {
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': scope
            }
            
            # 发送认证请求
            url = f"{self.auth_server_url}/oauth/token"
            
            self._log_debug(f"请求客户端令牌: {url}")
            
            response = session.post(
                url,
                data=data,
                timeout=self.timeout,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                self._log_info("客户端令牌获取成功")
                return True, token_data
            else:
                error_msg = f"客户端认证失败: HTTP {response.status_code} - {response.text[:200]}"
                self._log_warning(error_msg)
                return False, {'error': error_msg, 'status_code': response.status_code}
                
        except Exception as e:
            error_msg = f"客户端认证请求异常: {str(e)}"
            self._log_error(error_msg)
            return False, {'error': error_msg, 'type': 'unknown'}

    def refresh_token(self, 
                     refresh_token: str,
                     client_id: str = "default_client",
                     client_secret: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        刷新访问令牌
        
        Args:
            refresh_token: 刷新令牌
            client_id: 客户端ID
            client_secret: 客户端密钥
            
        Returns:
            (成功标志, 新的令牌信息/错误信息)
        """
        try:
            session = self.session_manager.get_session()
            if not session:
                return False, {'error': '无法获取有效的HTTP会话'}
            
            # 准备请求数据
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': client_id
            }
            
            if client_secret:
                data['client_secret'] = client_secret
            
            # 发送刷新请求
            url = f"{self.auth_server_url}/oauth/token"
            
            self._log_debug(f"刷新令牌: {url}")
            
            response = session.post(
                url,
                data=data,
                timeout=self.timeout,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                self._log_info("令牌刷新成功")
                return True, token_data
            else:
                error_msg = f"令牌刷新失败: HTTP {response.status_code} - {response.text[:200]}"
                self._log_warning(error_msg)
                return False, {'error': error_msg, 'status_code': response.status_code}
                
        except Exception as e:
            error_msg = f"令牌刷新请求异常: {str(e)}"
            self._log_error(error_msg)
            return False, {'error': error_msg, 'type': 'unknown'}

    def revoke_token(self, 
                    token: str,
                    token_type_hint: str = "access_token",
                    client_id: Optional[str] = None,
                    client_secret: Optional[str] = None) -> bool:
        """
        撤销令牌
        
        Args:
            token: 要撤销的令牌
            token_type_hint: 令牌类型提示
            client_id: 客户端ID
            client_secret: 客户端密钥
            
        Returns:
            bool: 是否撤销成功
        """
        try:
            session = self.session_manager.get_session()
            if not session:
                self._log_error("无法获取有效的HTTP会话")
                return False
            
            # 准备请求数据
            data = {
                'token': token,
                'token_type_hint': token_type_hint
            }
            
            if client_id:
                data['client_id'] = client_id
            if client_secret:
                data['client_secret'] = client_secret
            
            # 发送撤销请求
            url = f"{self.auth_server_url}/oauth/revoke"
            
            self._log_debug(f"撤销令牌: {url}")
            
            response = session.post(
                url,
                data=data,
                timeout=self.timeout,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                self._log_info("令牌撤销成功")
                return True
            else:
                self._log_warning(f"令牌撤销失败: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            self._log_error(f"令牌撤销请求异常: {e}")
            return False

    def validate_token(self, token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        验证令牌有效性
        
        Args:
            token: 要验证的令牌
            
        Returns:
            (有效标志, 令牌信息/错误信息)
        """
        try:
            session = self.session_manager.get_session()
            if not session:
                return False, {'error': '无法获取有效的HTTP会话'}
            
            # 发送验证请求
            url = f"{self.auth_server_url}/oauth/check_token"
            
            self._log_debug(f"验证令牌: {url}")
            
            response = session.post(
                url,
                data={'token': token},
                timeout=self.timeout,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                token_info = response.json()
                
                # 检查令牌是否有效
                is_valid = token_info.get('active', False)
                if is_valid:
                    self._log_debug("令牌验证有效")
                else:
                    self._log_warning("令牌验证无效")
                
                return is_valid, token_info
            else:
                self._log_warning(f"令牌验证失败: HTTP {response.status_code}")
                return False, {'error': f'HTTP {response.status_code}', 'status_code': response.status_code}
                
        except Exception as e:
            self._log_error(f"令牌验证请求异常: {e}")
            return False, {'error': str(e)}