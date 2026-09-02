# src/rcs_mgr_app/rcs_mgr_app/callback/channel_status_query.py
#!/usr/bin/env python3
"""
通道状态查询处理器
用于处理通道状态相关的HTTP查询请求
"""

import json
import time
from typing import Dict, Any, Optional, List


class ChannelStatusQueryHandler:
    """通道状态查询处理器"""
    
    def __init__(self, node):
        self.node = node
        self.logger = node.get_logger()
    
    def get_all_channels_status(self) -> Dict[str, Any]:
        """获取所有通道状态（使用新的超时检查）"""
        try:
            # 尝试从多个来源获取通道监控管理器
            channel_monitor = self._get_channel_monitor()
            
            if not channel_monitor:
                return {
                    "timestamp": int(time.time() * 1000),
                    "error": "通道监控管理器未初始化",
                    "channels": {},
                    "stats": {}
                }
            
            # 获取所有通道状态（新的方法包含超时检查）
            all_channels = channel_monitor.get_all_channels_status()
            stats = channel_monitor.get_stats()
            
            # 计算健康率（考虑超时）
            total_channels = stats.get('total_channels', 0)
            normal_channels = stats.get('normal_channels', 0)
            timeout_channels = stats.get('timeout_channels', 0)
            
            health_rate = (normal_channels / total_channels * 100) if total_channels > 0 else 0
            
            return {
                "timestamp": int(time.time() * 1000),
                "channels": all_channels,
                "stats": stats,
                "summary": {
                    "total_channels": total_channels,
                    "normal_channels": normal_channels,
                    "abnormal_channels": total_channels - normal_channels,
                    "timeout_channels": timeout_channels,
                    "health_rate": health_rate,
                    "devices": stats.get('devices', []),
                    "last_update": stats.get('last_update', 0),
                    "signal_timeout": stats.get('signal_timeout', 30.0)
                }
            }
            
        except Exception as e:
            self.logger.error(f"获取所有通道状态失败: {e}")
            return {
                "timestamp": int(time.time() * 1000),
                "error": str(e),
                "channels": {},
                "stats": {}
            }
    
    def get_device_channels_status(self, device_id: str) -> Dict[str, Any]:
        """获取指定设备的通道状态"""
        try:
            channel_monitor = self._get_channel_monitor()
            
            if not channel_monitor:
                return {
                    "timestamp": int(time.time() * 1000),
                    "error": "通道监控管理器未初始化",
                    "device_id": device_id,
                    "channels": {}
                }
            
            # 获取设备通道状态
            device_channels = channel_monitor.get_device_channels_status(device_id)
            
            # 转换为字典格式
            channels_dict = {}
            for channel_id, channel_info in device_channels.items():
                channels_dict[channel_id] = channel_info.to_dict()
            
            # 计算统计
            total_channels = len(channels_dict)
            normal_channels = sum(1 for c in channels_dict.values() 
                                if c.get('signal_status', False))
            
            return {
                "timestamp": int(time.time() * 1000),
                "device_id": device_id,
                "total_channels": total_channels,
                "normal_channels": normal_channels,
                "abnormal_channels": total_channels - normal_channels,
                "health_rate": (normal_channels / total_channels * 100) if total_channels > 0 else 0,
                "channels": channels_dict
            }
            
        except Exception as e:
            self.logger.error(f"获取设备通道状态失败: {e}")
            return {
                "timestamp": int(time.time() * 1000),
                "error": str(e),
                "device_id": device_id,
                "channels": {}
            }
    
    def get_specific_channel_status(self, device_id: str, channel_id: int) -> Dict[str, Any]:
        """获取指定通道的详细状态"""
        try:
            channel_monitor = self._get_channel_monitor()
            
            if not channel_monitor:
                return {
                    "timestamp": int(time.time() * 1000),
                    "error": "通道监控管理器未初始化",
                    "device_id": device_id,
                    "channel_id": channel_id,
                    "status": "UNKNOWN"
                }
            
            # 获取特定通道状态
            channel_info = channel_monitor.get_channel_status(device_id, channel_id)
            
            if channel_info:
                # 检查通道是否正常
                is_normal = channel_monitor.is_channel_normal(device_id, channel_id)
                
                return {
                    "timestamp": int(time.time() * 1000),
                    "device_id": device_id,
                    "channel_id": channel_id,
                    "status": channel_info.to_dict(),
                    "is_normal": is_normal,
                    "available": is_normal,
                    "available_channels": channel_monitor.get_available_channels(device_id)
                }
            else:
                return {
                    "timestamp": int(time.time() * 1000),
                    "device_id": device_id,
                    "channel_id": channel_id,
                    "error": "通道不存在",
                    "status": "UNKNOWN",
                    "is_normal": False,
                    "available": False
                }
            
        except Exception as e:
            self.logger.error(f"获取特定通道状态失败: {e}")
            return {
                "timestamp": int(time.time() * 1000),
                "error": str(e),
                "device_id": device_id,
                "channel_id": channel_id,
                "status": "UNKNOWN"
            }
    
    def get_channel_stats(self) -> Dict[str, Any]:
        """获取通道统计信息"""
        try:
            channel_monitor = self._get_channel_monitor()
            
            if not channel_monitor:
                return {
                    "timestamp": int(time.time() * 1000),
                    "error": "通道监控管理器未初始化",
                    "stats": {}
                }
            
            # 获取统计信息
            stats = channel_monitor.get_stats()
            
            # 计算健康率
            total_channels = stats.get('total_channels', 0)
            normal_channels = stats.get('normal_channels', 0)
            health_rate = (normal_channels / total_channels * 100) if total_channels > 0 else 0
            
            return {
                "timestamp": int(time.time() * 1000),
                "stats": stats,
                "summary": {
                    "total_channels": total_channels,
                    "normal_channels": normal_channels,
                    "abnormal_channels": total_channels - normal_channels,
                    "health_rate": health_rate,
                    "status_updates": stats.get('total_updates', 0),
                    "status_changes": stats.get('status_changes', 0),
                    "devices": stats.get('devices', []),
                    "last_update": stats.get('last_update', 0)
                }
            }
            
        except Exception as e:
            self.logger.error(f"获取通道统计信息失败: {e}")
            return {
                "timestamp": int(time.time() * 1000),
                "error": str(e),
                "stats": {}
            }
    
    def _get_channel_monitor(self):
        """获取通道监控管理器"""
        # 方法1：从节点直接获取
        if hasattr(self.node, 'channel_monitor'):
            return self.node.channel_monitor
        
        # 方法2：从停车监控插件获取
        if hasattr(self.node, 'plugin_manager'):
            plugin_manager = self.node.plugin_manager
            parking_plugin = plugin_manager.get_plugin('parking_monitor')
            if parking_plugin and hasattr(parking_plugin, 'channel_monitor'):
                return parking_plugin.channel_monitor
        
        # 方法3：从缓存管理器获取（如果集成了）
        if hasattr(self.node, 'lane_cache_manager'):
            lane_cache_manager = self.node.lane_cache_manager
            if hasattr(lane_cache_manager, 'channel_monitor'):
                return lane_cache_manager.channel_monitor
        
        return None