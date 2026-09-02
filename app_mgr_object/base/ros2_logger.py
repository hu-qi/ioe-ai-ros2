#!/usr/bin/env python3
"""
统一日志管理器 - 通用版本
"""

import logging
import sys
import os
import time
from typing import Optional, Dict, Any
from datetime import datetime

import rclpy
from rclpy.node import Node
from rclpy.logging import LoggingSeverity


class UnifiedLogger:
    _loggers: Dict[str, 'UnifiedLogger'] = {}

    def __new__(cls, name: str = None, node: Optional[Node] = None):
        if name is None:
            name = 'default'
        if name not in cls._loggers:
            instance = super().__new__(cls)
            instance._initialize(name, node)
            cls._loggers[name] = instance
        return cls._loggers[name]

    def _initialize(self, name: str, node: Optional[Node]):
        self.name = name
        self.node = node
        self.python_logger = logging.getLogger(f"app_mgr.{name}")
        self.python_logger.propagate = False

        self._level_map = {
            'debug': logging.DEBUG,
            'info': logging.INFO,
            'warning': logging.WARNING,
            'error': logging.ERROR,
            'critical': logging.CRITICAL
        }
        self._ros_level_map = {
            'debug': LoggingSeverity.DEBUG,
            'info': LoggingSeverity.INFO,
            'warning': LoggingSeverity.WARN,
            'error': LoggingSeverity.ERROR,
            'fatal': LoggingSeverity.FATAL
        }

        self.default_level = 'info'
        self.enable_file_log = False
        self.log_dir = '/var/log/app_mgr'  # 通用路径

        self._setup_handlers()

    def _setup_handlers(self):
        self.python_logger.handlers = []
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._level_map[self.default_level])
        formatter = logging.Formatter(
            '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        self.python_logger.addHandler(console_handler)

        if self.enable_file_log:
            self._setup_file_handler()

    def _setup_file_handler(self):
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            log_file = os.path.join(
                self.log_dir,
                f"app_mgr_{datetime.now().strftime('%Y%m%d')}.log"
            )
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(self._level_map[self.default_level])
            file_formatter = logging.Formatter(
                '[%(asctime)s] [%(name)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            self.python_logger.addHandler(file_handler)
        except Exception as e:
            self.error(f"设置文件日志失败: {e}")

    def configure(self, config: Dict[str, Any]):
        """从参数字典配置日志级别、文件日志等"""
        self.default_level = config.get('level', self.default_level)
        self.enable_file_log = config.get('enable_file_log', self.enable_file_log)
        self.log_dir = config.get('log_dir', self.log_dir)

        # 同步 ROS2 日志级别
        if self.node:
            ros_level = self._ros_level_map.get(self.default_level, LoggingSeverity.INFO)
            self.node.get_logger().set_level(ros_level)

        # 同步 Python 日志级别
        python_level = self._level_map.get(self.default_level, logging.INFO)
        self.python_logger.setLevel(python_level)
        for handler in self.python_logger.handlers:
            handler.setLevel(python_level)

        # 重新设置文件日志（如果启用）
        if self.enable_file_log:
            self._setup_handlers()

        self.info(f"日志配置完成: level={self.default_level}, file_log={self.enable_file_log}, log_dir={self.log_dir}")

    def get_logger(self) -> logging.Logger:
        return self.python_logger

    def debug(self, msg: str, *args, **kwargs):
        self.python_logger.debug(msg, *args, **kwargs)
        if self.node:
            self.node.get_logger().debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self.python_logger.info(msg, *args, **kwargs)
        if self.node:
            self.node.get_logger().info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self.python_logger.warning(msg, *args, **kwargs)
        if self.node:
            self.node.get_logger().warn(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self.python_logger.error(msg, *args, **kwargs)
        if self.node:
            self.node.get_logger().error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self.python_logger.critical(msg, *args, **kwargs)
        if self.node:
            self.node.get_logger().fatal(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        self.python_logger.exception(msg, *args, **kwargs)
        if self.node:
            self.node.get_logger().error(f"{msg}: {sys.exc_info()[1]}")

    def log_performance(self, func_name: str, execution_time: float, **kwargs):
        msg = f"性能统计 - {func_name}: {execution_time:.3f}s"
        if kwargs:
            details = " ".join([f"{k}={v}" for k, v in kwargs.items()])
            msg = f"{msg} | {details}"
        if execution_time > 1.0:
            self.warning(msg)
        elif execution_time > 0.5:
            self.info(msg)
        else:
            self.debug(msg)

    def get_log_stats(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'level': self.default_level,
            'file_log_enabled': self.enable_file_log,
            'handlers': len(self.python_logger.handlers),
            'node_available': self.node is not None
        }


def get_logger(name: str = None, node: Node = None, config: Dict = None) -> UnifiedLogger:
    logger = UnifiedLogger(name, node)
    if config:
        logger.configure(config)
    return logger


class PerformanceTimer:
    def __init__(self, logger: UnifiedLogger, operation: str, **kwargs):
        self.logger = logger
        self.operation = operation
        self.kwargs = kwargs
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        execution_time = time.time() - self.start_time
        self.logger.log_performance(self.operation, execution_time, **self.kwargs)


# 向后兼容类
class ROS2Logger:
    def __init__(self, name: str, node: Optional[Node] = None):
        self.logger = get_logger(name, node)

    def get_logger(self) -> logging.Logger:
        return self.logger.get_logger()

    def debug(self, msg: str, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warn(self, msg: str, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def fatal(self, msg: str, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)