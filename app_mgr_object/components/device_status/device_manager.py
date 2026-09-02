#!/usr/bin/env python3

from typing import Dict, List, Any, Optional
import logging
from .signal_monitor import SignalMonitor
from .area_filter import AreaStatusFilter


class DeviceChannelStatus:
    """设备通道状态管理器 - 管理单个设备单个通道的所有区域状态"""

    def __init__(self, device_id: str, channel_id: int,
                 stable_threshold: int = 5, timeout: float = 2.0,
                 logger: Optional[logging.Logger] = None):
        """
        初始化设备通道状态管理器

        Args:
            device_id: 设备ID
            channel_id: 通道ID
            stable_threshold: 稳定状态阈值
            timeout: 超时时间
            logger: 日志记录器
        """
        self.device_id = device_id
        self.channel_id = channel_id
        self.stable_threshold = stable_threshold
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)

        # 区域状态滤波器字典
        self.area_filters: Dict[str, AreaStatusFilter] = {}

        # 信号状态滤波器
        # self.signal_status_filter = AreaStatusFilter(stable_threshold, timeout, logger)
        self.signal_status_filter = SignalMonitor(
            stable_threshold=stable_threshold,
            timeout=timeout,
            error_threshold=3,          # 可根据需要配置
            recovery_time=10.0,
            logger=logger
        )
        self.current_signal_stable = False
        self.signal_update_count = 0

    def update_area_status(self, area_name: str, has_object: bool) -> Dict[str, Any]:
        """
        更新区域状态

        Args:
            area_name: 区域名称
            has_object: 是否有目标

        Returns:
            状态变化信息
        """
        # 初始化区域滤波器（如果不存在）
        if area_name not in self.area_filters:
            self.area_filters[area_name] = AreaStatusFilter(
                self.stable_threshold, self.timeout, self.logger
            )

        filter_obj = self.area_filters[area_name]
        result = filter_obj.update(has_object)

        return {
            'area_name': area_name,
            'filter_result': result,
            'changed': result['changed'],
            'current_state': result['current_state']
        }

    def update_signal_status(self, signal_status: bool) -> Dict[str, Any]:
        """
        更新信号状态

        Args:
            signal_status: 信号状态

        Returns:
            状态变化信息
        """
        self.signal_update_count += 1
        result = self.signal_status_filter.update(signal_status)

        if result['changed']:
            self.current_signal_stable = result['current_state']

        return {
            'changed': result['changed'],
            'current_state': result['current_state'],
            'update_count': self.signal_update_count
        }

    def get_all_area_status(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有区域的当前状态

        Returns:
            区域状态字典
        """
        status_dict = {}
        for area_name, filter_obj in self.area_filters.items():
            status_dict[area_name] = {
                'stable_state': filter_obj.current_stable_state,
                'queue_size': len(filter_obj.status_queue),
                'update_count': filter_obj.update_count
            }
        return status_dict

    def get_area_names(self) -> List[str]:
        """获取所有区域名称"""
        return list(self.area_filters.keys())

    def get_channel_info(self) -> Dict[str, Any]:
        """获取通道信息"""
        return {
            'device_id': self.device_id,
            'channel_id': self.channel_id,
            'signal_stable': self.current_signal_stable,
            'area_count': len(self.area_filters),
            'area_names': self.get_area_names()
        }


class DeviceStatusManager:
    """设备状态管理器 - 管理所有设备的状态"""

    def __init__(self, stable_threshold: int = 5, timeout: float = 2.0,
                 logger: Optional[logging.Logger] = None):
        """
        初始化设备状态管理器

        Args:
            stable_threshold: 稳定状态阈值
            timeout: 超时时间
            logger: 日志记录器
        """
        self.stable_threshold = stable_threshold
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)
        self.device_channels: Dict[str, Dict[int, DeviceChannelStatus]] = {}

    def update_device_status(self, device_id: str, channel_id: int,
                           area_name: str, has_object: bool) -> Dict[str, Any]:
        """
        更新设备区域状态

        Args:
            device_id: 设备ID
            channel_id: 通道ID
            area_name: 区域名称
            has_object: 是否有目标

        Returns:
            更新结果
        """
        # 初始化设备通道（如果不存在）
        if device_id not in self.device_channels:
            self.device_channels[device_id] = {}

        if channel_id not in self.device_channels[device_id]:
            self.device_channels[device_id][channel_id] = DeviceChannelStatus(
                device_id, channel_id, self.stable_threshold, self.timeout, self.logger
            )

        channel_manager = self.device_channels[device_id][channel_id]
        return channel_manager.update_area_status(area_name, has_object)

    def update_device_signal(self, device_id: str, channel_id: int,
                           signal_status: bool) -> Dict[str, Any]:
        """
        更新设备信号状态

        Args:
            device_id: 设备ID
            channel_id: 通道ID
            signal_status: 信号状态

        Returns:
            更新结果
        """
        if device_id not in self.device_channels:
            self.device_channels[device_id] = {}

        if channel_id not in self.device_channels[device_id]:
            self.device_channels[device_id][channel_id] = DeviceChannelStatus(
                device_id, channel_id, self.stable_threshold, self.timeout, self.logger
            )

        channel_manager = self.device_channels[device_id][channel_id]
        return channel_manager.update_signal_status(signal_status)

    def get_all_status_summary(self) -> Dict[str, Any]:
        """
        获取所有设备状态汇总

        Returns:
            状态汇总字典
        """
        summary = {
            'total_devices': len(self.device_channels),
            'devices': {}
        }

        for device_id, channels in self.device_channels.items():
            device_info = {
                'total_channels': len(channels),
                'channels': {}
            }

            for channel_id, channel_manager in channels.items():
                channel_info = channel_manager.get_channel_info()
                channel_info['areas'] = channel_manager.get_all_area_status()
                device_info['channels'][channel_id] = channel_info

            summary['devices'][device_id] = device_info

        return summary

    def get_device_list(self) -> List[str]:
        """获取设备列表"""
        return list(self.device_channels.keys())

    def reset_device(self, device_id: str):
        """重置设备状态"""
        if device_id in self.device_channels:
            del self.device_channels[device_id]