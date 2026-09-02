#!/usr/bin/env python3
"""
订阅管理器 - 管理ROS2订阅
"""

import threading
from typing import Dict, Any, Optional, Callable, List, Type
from rclpy.node import Node
from rclpy.qos import QoSProfile


class SubscriptionManager:
    """ROS2订阅管理器"""
    
    def __init__(self, node: Node):
        self.node = node
        self.logger = node.get_logger()
        
        # 存储所有订阅
        self._subscriptions: Dict[str, Any] = {}
        
        # 锁
        self._lock = threading.RLock()
    
    def create_subscription(self, 
                           msg_type: Type,
                           topic_name: str, 
                           callback: Callable,
                           qos_profile: QoSProfile = QoSProfile(depth=10),
                           subscription_name: str = None,
                           callback_group=None) -> bool:
        """创建订阅"""
        with self._lock:
            # 如果没有指定订阅名称，使用topic名称
            if subscription_name is None:
                subscription_name = topic_name
            
            if subscription_name in self._subscriptions:
                self.logger.warning(f"订阅 {subscription_name} 已存在")
                return False
            
            try:
                # 创建订阅
                subscription = self.node.create_subscription(
                    msg_type=msg_type,
                    topic=topic_name,
                    callback=callback,
                    qos_profile=qos_profile,
                    callback_group=callback_group
                )
                
                # 存储订阅
                self._subscriptions[subscription_name] = {
                    'subscription': subscription,
                    'topic': topic_name,
                    'type': msg_type,
                    'callback': callback,
                    'qos': qos_profile
                }
                
                self.logger.info(f"订阅创建成功: {subscription_name} -> {topic_name}")
                return True
                
            except Exception as e:
                self.logger.error(f"创建订阅 {subscription_name} 失败: {e}")
                return False
    
    def create_device_subscriptions(self, 
                                    msg_type: Type,
                                    device_ids: List[str],
                                    callback_template: Callable,
                                    qos_profile: QoSProfile = None,
                                    topic_prefix: str = "parking") -> Dict[str, bool]:
        """为多个设备创建订阅"""
        results = {}
        
        for device_id in device_ids:
            topic_name = f"{topic_prefix}{device_id}_status"
            subscription_name = f"device_{device_id}"
            
            # 创建设备特定的回调函数
            def create_device_callback(dev_id):
                def device_callback(msg):
                    try:
                        callback_template(msg, dev_id)
                    except Exception as e:
                        self.logger.error(f"设备 {dev_id} 回调处理失败: {e}")
                return device_callback
            
            # 创建订阅
            success = self.create_subscription(
                msg_type=msg_type,
                topic_name=topic_name,
                callback=create_device_callback(device_id),
                qos_profile=qos_profile,
                subscription_name=subscription_name
            )
            
            results[device_id] = success
        
        return results
    
    def get_subscription(self, subscription_name: str):
        """获取订阅"""
        with self._lock:
            return self._subscriptions.get(subscription_name)
    
    def get_all_subscriptions(self) -> Dict[str, Any]:
        """获取所有订阅"""
        with self._lock:
            return {
                name: {
                    'topic': info['topic'],
                    'type': info['type'].__name__,
                    'callback': info['callback'].__name__ if hasattr(info['callback'], '__name__') else 'unknown'
                }
                for name, info in self._subscriptions.items()
            }
    
    def remove_subscription(self, subscription_name: str) -> bool:
        """移除订阅"""
        with self._lock:
            if subscription_name not in self._subscriptions:
                self.logger.warning(f"订阅 {subscription_name} 不存在")
                return False
            
            try:
                # 获取订阅句柄
                subscription_info = self._subscriptions[subscription_name]
                
                # 注意：ROS2 Python中无法直接销毁订阅
                # 可以移除引用，让垃圾回收器处理
                del self._subscriptions[subscription_name]
                
                self.logger.info(f"订阅 {subscription_name} 已移除")
                return True
                
            except Exception as e:
                self.logger.error(f"移除订阅 {subscription_name} 失败: {e}")
                return False
    
    def remove_all_subscriptions(self):
        """移除所有订阅"""
        with self._lock:
            subscription_names = list(self._subscriptions.keys())
            for name in subscription_names:
                self.remove_subscription(name)
    
    def get_subscription_count(self) -> int:
        """获取订阅数量"""
        with self._lock:
            return len(self._subscriptions)
    
    def get_topic_subscriptions(self, topic_name: str) -> List[str]:
        """获取指定topic的所有订阅"""
        with self._lock:
            return [
                name for name, info in self._subscriptions.items()
                if info['topic'] == topic_name
            ]
    
    def get_status(self) -> Dict[str, Any]:
        """获取订阅管理器状态"""
        with self._lock:
            # 按topic统计
            topic_stats = {}
            for info in self._subscriptions.values():
                topic = info['topic']
                if topic not in topic_stats:
                    topic_stats[topic] = 0
                topic_stats[topic] += 1
            
            return {
                'total_subscriptions': len(self._subscriptions),
                'topics': list(topic_stats.keys()),
                'topic_statistics': topic_stats,
                'status': 'running'
            }