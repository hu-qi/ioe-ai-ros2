#!/usr/bin/env python3

import json
import logging
import threading
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import os


class TokenStorage:
    """令牌存储管理器 - 负责安全存储令牌信息"""
    
    def __init__(self, 
                 storage_file: Optional[str] = None,
                 logger=None):
        """
        初始化令牌存储
        
        Args:
            storage_file: 令牌存储文件路径，None表示使用内存存储
            logger: 日志记录器
        """
        self.storage_file = storage_file
        self.logger = logger
        self._lock = threading.RLock()
        
        # 内存存储
        self._token_data = {}
        
        # 从文件加载现有令牌
        if storage_file and os.path.exists(storage_file):
            self._load_from_file()
        
        self._log_info("令牌存储管理器初始化完成")
    
    def _log_info(self, message: str):
        """记录信息级别日志"""
        if self.logger:
            if hasattr(self.logger, 'info'):
                self.logger.info(f"[TokenStorage] {message}")
            else:
                print(f"[TokenStorage INFO] {message}")
        else:
            print(f"[TokenStorage INFO] {message}")
    
    def _log_warning(self, message: str):
        """记录警告级别日志"""
        if self.logger:
            if hasattr(self.logger, 'warn'):
                self.logger.warn(f"[TokenStorage] {message}")
            else:
                print(f"[TokenStorage WARN] {message}")
        else:
            print(f"[TokenStorage WARN] {message}")
    
    def _log_error(self, message: str):
        """记录错误级别日志"""
        if self.logger:
            if hasattr(self.logger, 'error'):
                self.logger.error(f"[TokenStorage] {message}")
            else:
                print(f"[TokenStorage ERROR] {message}")
        else:
            print(f"[TokenStorage ERROR] {message}")
    
    def _log_debug(self, message: str):
        """记录调试级别日志"""
        if self.logger:
            if hasattr(self.logger, 'debug'):
                self.logger.debug(f"[TokenStorage] {message}")
            else:
                print(f"[TokenStorage DEBUG] {message}")
        else:
            print(f"[TokenStorage DEBUG] {message}")

    def _load_from_file(self):
        """从文件加载令牌数据"""
        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                self._token_data = json.load(f)
            self._log_info(f"从文件加载令牌数据: {self.storage_file}")
        except Exception as e:
            self._log_error(f"加载令牌文件失败: {e}")
            self._token_data = {}

    def _save_to_file(self):
        """保存令牌数据到文件"""
        if not self.storage_file:
            return
        
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self._token_data, f, indent=2, ensure_ascii=False)
            
            self._log_debug(f"令牌数据已保存到文件: {self.storage_file}")
        except Exception as e:
            self._log_error(f"保存令牌文件失败: {e}")

    def store_token(self, 
                   token_type: str, 
                   token: str, 
                   expires_in: Optional[int] = None,
                   refresh_token: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        存储令牌信息
        
        Args:
            token_type: 令牌类型 (如: access_token, refresh_token)
            token: 令牌值
            expires_in: 过期时间(秒)
            refresh_token: 刷新令牌
            metadata: 元数据
            
        Returns:
            bool: 是否存储成功
        """
        with self._lock:
            try:
                expires_at = None
                if expires_in:
                    expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
                
                self._token_data[token_type] = {
                    'token': token,
                    'expires_at': expires_at,
                    'refresh_token': refresh_token,
                    'metadata': metadata or {},
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                self._save_to_file()
                self._log_debug(f"令牌已存储: {token_type}")
                return True
                
            except Exception as e:
                self._log_error(f"存储令牌失败: {e}")
                return False

    def get_token(self, token_type: str) -> Optional[Dict[str, Any]]:
        """
        获取令牌信息
        
        Args:
            token_type: 令牌类型
            
        Returns:
            Optional[Dict]: 令牌信息，None表示不存在或已过期
        """
        with self._lock:
            try:
                if token_type not in self._token_data:
                    self._log_debug(f"令牌不存在: {token_type}")
                    return None
                
                token_info = self._token_data[token_type]
                
                # 检查令牌是否过期
                expires_at = token_info.get('expires_at')
                if expires_at:
                    try:
                        expires_time = datetime.fromisoformat(expires_at)
                        if datetime.now() >= expires_time:
                            self._log_debug(f"令牌已过期: {token_type}")
                            return None
                    except Exception as e:
                        self._log_warning(f"解析过期时间失败: {e}")
                
                self._log_debug(f"令牌获取成功: {token_type}")
                return token_info.copy()
                
            except Exception as e:
                self._log_error(f"获取令牌失败: {e}")
                return None

    def remove_token(self, token_type: str) -> bool:
        """
        移除令牌
        
        Args:
            token_type: 令牌类型
            
        Returns:
            bool: 是否移除成功
        """
        with self._lock:
            try:
                if token_type in self._token_data:
                    del self._token_data[token_type]
                    self._save_to_file()
                    self._log_debug(f"令牌已移除: {token_type}")
                    return True
                else:
                    self._log_debug(f"令牌不存在，无需移除: {token_type}")
                    return False
                    
            except Exception as e:
                self._log_error(f"移除令牌失败: {e}")
                return False

    def is_token_valid(self, token_type: str) -> bool:
        """
        检查令牌是否有效
        
        Args:
            token_type: 令牌类型
            
        Returns:
            bool: 令牌是否有效
        """
        token_info = self.get_token(token_type)
        return token_info is not None

    def get_all_tokens(self) -> Dict[str, Any]:
        """
        获取所有令牌信息
        
        Returns:
            Dict: 所有令牌信息
        """
        with self._lock:
            return self._token_data.copy()

    def clear_all_tokens(self) -> bool:
        """
        清除所有令牌
        
        Returns:
            bool: 是否清除成功
        """
        with self._lock:
            try:
                self._token_data.clear()
                self._save_to_file()
                self._log_info("所有令牌已清除")
                return True
            except Exception as e:
                self._log_error(f"清除令牌失败: {e}")
                return False