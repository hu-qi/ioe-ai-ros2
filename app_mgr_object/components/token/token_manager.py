#!/usr/bin/env python3

import logging
import threading
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from .token_storage import TokenStorage
from .auth_client import AuthClient


class TokenManager:
    """令牌管理器 - 核心令牌管理功能"""
    
    def __init__(self,
                 auth_server_url: str,
                 storage_file: Optional[str] = None,
                 auto_refresh: bool = True,
                 refresh_margin: int = 300,  # 提前5分钟刷新
                 source_interface: str = "eth1",
                 fallback_interface: str = "eth0",
                 timeout: float = 10.0,
                 logger=None):
        """
        初始化令牌管理器
        
        Args:
            auth_server_url: 认证服务器URL
            storage_file: 令牌存储文件路径
            auto_refresh: 是否自动刷新令牌
            refresh_margin: 刷新提前量(秒)
            source_interface: 主网络接口
            fallback_interface: 备用网络接口
            timeout: 请求超时时间
            logger: 日志记录器
        """
        self.auth_server_url = auth_server_url
        self.auto_refresh = auto_refresh
        self.refresh_margin = refresh_margin
        self.timeout = timeout
        self.logger = logger
        
        # 初始化子模块
        self.token_storage = TokenStorage(
            storage_file=storage_file,
            logger=logger
        )
        
        self.auth_client = AuthClient(
            auth_server_url=auth_server_url,
            timeout=timeout,
            source_interface=source_interface,
            fallback_interface=fallback_interface,
            logger=logger
        )
        
        self._lock = threading.RLock()
        
        self._log_info("令牌管理器初始化完成")
    
    def _log_info(self, message: str):
        """记录信息级别日志"""
        if self.logger:
            if hasattr(self.logger, 'info'):
                self.logger.info(f"[TokenManager] {message}")
            else:
                print(f"[TokenManager INFO] {message}")
        else:
            print(f"[TokenManager INFO] {message}")
    
    def _log_warning(self, message: str):
        """记录警告级别日志"""
        if self.logger:
            if hasattr(self.logger, 'warn'):
                self.logger.warn(f"[TokenManager] {message}")
            else:
                print(f"[TokenManager WARN] {message}")
        else:
            print(f"[TokenManager WARN] {message}")
    
    def _log_error(self, message: str):
        """记录错误级别日志"""
        if self.logger:
            if hasattr(self.logger, 'error'):
                self.logger.error(f"[TokenManager] {message}")
            else:
                print(f"[TokenManager ERROR] {message}")
        else:
            print(f"[TokenManager ERROR] {message}")
    
    def _log_debug(self, message: str):
        """记录调试级别日志"""
        if self.logger:
            if hasattr(self.logger, 'debug'):
                self.logger.debug(f"[TokenManager] {message}")
            else:
                print(f"[TokenManager DEBUG] {message}")
        else:
            print(f"[TokenManager DEBUG] {message}")

    def authenticate_with_password(self,
                                  username: str,
                                  password: str,
                                  client_id: str = "default_client",
                                  client_secret: Optional[str] = None,
                                  scope: str = "read write") -> Tuple[bool, Optional[str]]:
        """
        使用用户名密码进行认证
        
        Args:
            username: 用户名
            password: 密码
            client_id: 客户端ID
            client_secret: 客户端密钥
            scope: 权限范围
            
        Returns:
            (成功标志, 访问令牌/错误信息)
        """
        with self._lock:
            try:
                # 请求令牌
                success, token_data = self.auth_client.request_token_by_password(
                    username=username,
                    password=password,
                    client_id=client_id,
                    client_secret=client_secret,
                    scope=scope
                )
                
                if not success:
                    return False, token_data.get('error', '认证失败')
                
                # 存储令牌
                access_token = token_data.get('access_token')
                refresh_token = token_data.get('refresh_token')
                expires_in = token_data.get('expires_in')
                
                if not access_token:
                    return False, '响应中缺少访问令牌'
                
                # 存储访问令牌
                self.token_storage.store_token(
                    token_type='access_token',
                    token=access_token,
                    expires_in=expires_in,
                    refresh_token=refresh_token,
                    metadata={
                        'grant_type': 'password',
                        'username': username,
                        'client_id': client_id,
                        'scope': scope
                    }
                )
                
                # 如果有刷新令牌，也存储
                if refresh_token:
                    self.token_storage.store_token(
                        token_type='refresh_token',
                        token=refresh_token,
                        metadata={'associated_access_token': access_token}
                    )
                
                self._log_info("密码认证成功")
                return True, access_token
                
            except Exception as e:
                error_msg = f"密码认证异常: {str(e)}"
                self._log_error(error_msg)
                return False, error_msg

    def authenticate_with_client_credentials(self,
                                           client_id: str,
                                           client_secret: str,
                                           scope: str = "read write") -> Tuple[bool, Optional[str]]:
        """
        使用客户端凭证进行认证
        
        Args:
            client_id: 客户端ID
            client_secret: 客户端密钥
            scope: 权限范围
            
        Returns:
            (成功标志, 访问令牌/错误信息)
        """
        with self._lock:
            try:
                # 请求令牌
                success, token_data = self.auth_client.request_token_by_client_credentials(
                    client_id=client_id,
                    client_secret=client_secret,
                    scope=scope
                )
                
                if not success:
                    return False, token_data.get('error', '客户端认证失败')
                
                # 存储令牌
                access_token = token_data.get('access_token')
                expires_in = token_data.get('expires_in')
                
                if not access_token:
                    return False, '响应中缺少访问令牌'
                
                self.token_storage.store_token(
                    token_type='access_token',
                    token=access_token,
                    expires_in=expires_in,
                    metadata={
                        'grant_type': 'client_credentials',
                        'client_id': client_id,
                        'scope': scope
                    }
                )
                
                self._log_info("客户端凭证认证成功")
                return True, access_token
                
            except Exception as e:
                error_msg = f"客户端凭证认证异常: {str(e)}"
                self._log_error(error_msg)
                return False, error_msg

    def get_valid_access_token(self) -> Optional[str]:
        """
        获取有效的访问令牌（自动处理刷新）
        
        Returns:
            Optional[str]: 有效的访问令牌，None表示无法获取
        """
        with self._lock:
            try:
                # 获取存储的访问令牌
                token_info = self.token_storage.get_token('access_token')
                
                if not token_info:
                    self._log_debug("没有可用的访问令牌")
                    return None
                
                # 检查是否需要刷新
                if self.auto_refresh and self._needs_refresh(token_info):
                    self._log_debug("访问令牌需要刷新")
                    return self._refresh_access_token()
                
                # 返回有效的访问令牌
                access_token = token_info.get('token')
                self._log_debug("返回有效的访问令牌")
                return access_token
                
            except Exception as e:
                self._log_error(f"获取访问令牌异常: {e}")
                return None

    def _needs_refresh(self, token_info: Dict[str, Any]) -> bool:
        """检查令牌是否需要刷新"""
        expires_at = token_info.get('expires_at')
        if not expires_at:
            return False
        
        try:
            expires_time = datetime.fromisoformat(expires_at)
            # 如果剩余时间小于刷新提前量，则需要刷新
            time_remaining = expires_time - datetime.now()
            return time_remaining.total_seconds() <= self.refresh_margin
        except Exception as e:
            self._log_warning(f"检查令牌过期时间失败: {e}")
            return False

    def _refresh_access_token(self) -> Optional[str]:
        """刷新访问令牌"""
        try:
            # 获取刷新令牌
            refresh_token_info = self.token_storage.get_token('refresh_token')
            if not refresh_token_info:
                self._log_warning("没有可用的刷新令牌")
                return None
            
            refresh_token = refresh_token_info.get('token')
            if not refresh_token:
                self._log_warning("刷新令牌为空")
                return None
            
            # 获取客户端信息（从访问令牌的元数据中）
            access_token_info = self.token_storage.get_token('access_token')
            metadata = access_token_info.get('metadata', {}) if access_token_info else {}
            client_id = metadata.get('client_id', 'default_client')
            client_secret = metadata.get('client_secret')
            
            # 刷新令牌
            success, token_data = self.auth_client.refresh_token(
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret
            )
            
            if not success:
                self._log_warning(f"令牌刷新失败: {token_data.get('error')}")
                return None
            
            # 存储新的访问令牌
            new_access_token = token_data.get('access_token')
            new_refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in')
            
            if not new_access_token:
                self._log_warning("刷新响应中缺少访问令牌")
                return None
            
            self.token_storage.store_token(
                token_type='access_token',
                token=new_access_token,
                expires_in=expires_in,
                refresh_token=new_refresh_token or refresh_token,  # 使用新的或保持旧的刷新令牌
                metadata=metadata
            )
            
            # 如果有新的刷新令牌，更新存储
            if new_refresh_token:
                self.token_storage.store_token(
                    token_type='refresh_token',
                    token=new_refresh_token,
                    metadata={'associated_access_token': new_access_token}
                )
            
            self._log_info("访问令牌刷新成功")
            return new_access_token
            
        except Exception as e:
            self._log_error(f"刷新访问令牌异常: {e}")
            return None

    def validate_current_token(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        验证当前令牌的有效性
        
        Returns:
            (有效标志, 令牌信息/错误信息)
        """
        access_token = self.get_valid_access_token()
        if not access_token:
            return False, {'error': '没有有效的访问令牌'}
        
        return self.auth_client.validate_token(access_token)

    def revoke_current_tokens(self) -> bool:
        """撤销当前所有令牌"""
        with self._lock:
            try:
                # 获取当前访问令牌
                access_token_info = self.token_storage.get_token('access_token')
                access_token = access_token_info.get('token') if access_token_info else None
                
                # 获取当前刷新令牌
                refresh_token_info = self.token_storage.get_token('refresh_token')
                refresh_token = refresh_token_info.get('token') if refresh_token_info else None
                
                # 撤销访问令牌
                if access_token:
                    self.auth_client.revoke_token(access_token, 'access_token')
                
                # 撤销刷新令牌
                if refresh_token:
                    self.auth_client.revoke_token(refresh_token, 'refresh_token')
                
                # 清除本地存储
                self.token_storage.clear_all_tokens()
                
                self._log_info("所有令牌已撤销并清除")
                return True
                
            except Exception as e:
                self._log_error(f"撤销令牌异常: {e}")
                return False

    def get_token_info(self) -> Dict[str, Any]:
        """获取令牌信息"""
        return self.token_storage.get_all_tokens()

    def is_authenticated(self) -> bool:
        """检查是否已认证"""
        return self.get_valid_access_token() is not None

    def shutdown(self):
        """关闭令牌管理器"""
        self._log_info("正在关闭令牌管理器...")
        # 目前不需要特殊清理操作
        self._log_info("令牌管理器已关闭")