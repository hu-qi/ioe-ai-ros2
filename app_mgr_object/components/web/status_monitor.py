#!/usr/bin/env python3
"""
状态监控器 - 完整版（包含ROS2节点监控和通道监控）
"""

import time
import subprocess
import threading
import json
import requests
import psutil
import netifaces
import traceback  # ✅ 新增：用于异常堆栈记录
from typing import Dict, Any, List, Optional, Tuple
import rclpy
from rclpy.node import Node
import rclpy.logging


class StatusMonitor:
    """状态监控器（完整版）"""
    
    def __init__(self, node: Node, config: Dict[str, Any] = None):
        self.node = node
        self.logger = node.get_logger() if hasattr(node, 'get_logger') else rclpy.logging.get_logger(__name__)
        self.config = config or {}
        
        # 使用配置中的值
        self.node_aliases = self.config.get('node_aliases', {})
        if not self.node_aliases:
            self.logger.warning("没有配置任何监控节点，节点监控将无效")
            self._monitored_nodes = []
        else:
            # 严格取别名键作为监控列表，后续不再变更
            self._monitored_nodes = list(self.node_aliases.keys())
            self.logger.info(f"将被监控的节点列表: {self._monitored_nodes}")
        self.channel_aliases = self.config.get('channel_aliases', {})
        self.callback_server = self.config.get('callback_server', {})
        self.operation_mode = self.config.get('operation_mode', 'development')
        
        
        
        # 监控的节点列表
        self.deployment_services = self.config.get('deployment_services', {})
        # 使用字典的所有值作为监控的服务名列表
        self.monitored_services = list(self.deployment_services.values()) if self.deployment_services else []
        if not self.monitored_services:
            self.logger.warning("没有配置部署服务，服务监控将不可用")
        
        
        # 缓存
        self._cache = {
            'ros2_nodes': {},
            'channels': {},
            'services': {},
            'system_info': {},
            'last_update': 0,
            'start_time': time.time()
        }
        
        # 锁
        self._lock = threading.RLock()
        
        # HTTP客户端配置
        self._http_timeout = (2, 3)   # 加载优化：(3,5)→(2,3)（doc/前端页面加载优化）
        
        # 系统信息
        self._init_system_info()
        
        self.logger.info(f"状态监控器初始化完成，运行模式: {self.operation_mode}")
    
    def _init_system_info(self):
        """初始化系统信息"""
        try:
            # 获取主机名
            import socket
            hostname = socket.gethostname()
            
            # 获取IP地址
            # ip_address = self._get_ip_address()
            ip_address = self._get_wlan0_ip_address()
            
            # 获取CPU和内存信息
            cpu_count = psutil.cpu_count()
            memory = psutil.virtual_memory()
            
            self._cache['system_info'] = {
                'hostname': hostname,
                'ip_address': ip_address,
                'cpu_count': cpu_count,
                'total_memory': memory.total,
                'available_memory': memory.available,
                'memory_percent': memory.percent,
                'start_time': self._cache['start_time'],
                'operation_mode': self.operation_mode
            }
            
        except Exception as e:
            self.logger.warning(f"初始化系统信息失败: {e}")
    
    def _get_ip_address(self):
        """获取IP地址 - 内网环境优化版"""
        try:
            import socket
            
            # 方法1：尝试通过getaddrinfo获取
            try:
                hostname = socket.gethostname()
                addrinfo_list = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
                
                for addr_info in addrinfo_list:
                    ip = addr_info[4][0]
                    if (ip and 
                        ip != '127.0.0.1' and 
                        not ip.startswith('169.254.') and 
                        ip != '0.0.0.0'):
                        self.logger.debug(f"通过getaddrinfo获取到IP: {ip}")
                        return ip
            except Exception as e:
                self.logger.debug(f"通过getaddrinfo获取IP失败: {e}")
            
            # 方法2：通过socket绑定获取
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                
                try:
                    s.bind(('', 0))
                    ip = s.getsockname()[0]
                    
                    if ip and ip != '0.0.0.0' and ip != '127.0.0.1':
                        self.logger.debug(f"通过socket绑定获取到IP: {ip}")
                        return ip
                        
                finally:
                    s.close()
                    
            except Exception as e:
                self.logger.debug(f"通过socket绑定获取IP失败: {e}")
            
                        
            # 所有方法都失败，返回回环地址
            self.logger.warning("所有IP获取方法均失败，返回回环地址")
            return '127.0.0.1'
            
        except Exception as e:
            self.logger.error(f"获取IP地址失败: {e}")
            return '127.0.0.1'
        
    def _get_wlan0_ip_address(self):
        """获取wlan0网卡的IP地址 - 内网优化版"""
        try:
            # 延迟导入netifaces
            import netifaces
            
            # 首先尝试获取wlan0 IP地址
            try:
                if 'wlan0' in netifaces.interfaces():
                    addresses = netifaces.ifaddresses('wlan0')
                    if netifaces.AF_INET in addresses:
                        ip_info = addresses[netifaces.AF_INET][0]
                        ip_addr = ip_info.get('addr')
                        if ip_addr and ip_addr != '127.0.0.1':
                            self.logger.info(f"获取到wlan0 IP地址: {ip_addr}")
                            return ip_addr
            except Exception as e:
                self.logger.debug(f"获取wlan0 IP地址失败: {e}")
            
            # 如果wlan0不存在，尝试其他无线网卡
            try:
                for interface in netifaces.interfaces():
                    if interface.startswith('wl') or interface.startswith('wlan'):
                        addresses = netifaces.ifaddresses(interface)
                        if netifaces.AF_INET in addresses:
                            ip_info = addresses[netifaces.AF_INET][0]
                            ip_addr = ip_info.get('addr')
                            if ip_addr and ip_addr != '127.0.0.1':
                                self.logger.info(f"使用 {interface} 替代 wlan0: {ip_addr}")
                                return ip_addr
            except Exception as e:
                self.logger.debug(f"获取无线网卡IP地址失败: {e}")
            
            # 如果都没有，使用改进的_get_ip_address方法
            self.logger.warning("未找到wlan0或类似无线网卡，使用通用IP获取方法")
            return self._get_ip_address()
                
        except ImportError as e:
            self.logger.warning(f"netifaces库未安装，使用通用IP获取方法: {e}")
            return self._get_ip_address()
        except Exception as e:
            self.logger.warning(f"获取wlan0 IP地址失败: {e}")
            return self._get_ip_address()
    
    def get_ros2_nodes_status(self) -> Dict[str, Any]:
        with self._lock:
            try:
                self.logger.debug("开始获取ROS2节点状态...")

                all_nodes = self._get_ros2_nodes()
                self.logger.debug(f"发现系统中过滤后有 {len(all_nodes)} 个应用节点: {all_nodes}")

                all_raw_nodes = self._get_raw_ros2_nodes()
                self.logger.debug(f"原始节点总数: {len(all_raw_nodes)}")

                nodes_status = {}
                monitored_nodes = self._monitored_nodes
                if not monitored_nodes:
                    self.logger.error("没有配置任何监控节点，请检查 params.yaml 中的 node_aliases")
                    return {'monitored_nodes': {}, 'all_system_nodes': all_nodes, 'statistics': {}}

                for node_name in monitored_nodes:
                    is_alive = node_name in all_nodes
                    # 详细检查日志降级为 debug
                    self.logger.debug(f"检查节点 {node_name}: {'存在' if is_alive else '不存在'}")

                    pid = None
                    uptime = None
                    if is_alive:
                        pid = self._get_node_pid(node_name)
                        uptime = self._get_node_uptime(node_name)

                    nodes_status[node_name] = {
                        'name': node_name,
                        'alive': is_alive,
                        'alias': self.node_aliases.get(node_name, node_name),
                        'last_check': time.time(),
                        'pid': pid,
                        'uptime': uptime,
                        'status': 'running' if is_alive else 'stopped',
                        'status_color': 'success' if is_alive else 'danger',
                        'requires_restart': not is_alive
                    }

                total_monitored_nodes = len(monitored_nodes)
                alive_nodes = sum(1 for node in nodes_status.values() if node.get('alive', False))
                statistics = {
                    'total_monitored': total_monitored_nodes,
                    'alive': alive_nodes,
                    'dead': total_monitored_nodes - alive_nodes,
                    'health_percent': (alive_nodes / total_monitored_nodes * 100) if total_monitored_nodes > 0 else 0,
                    'total_system_nodes': len(all_nodes),
                    'raw_system_nodes_count': len(all_raw_nodes)
                }

                # 唯一保留的重要 info 日志：节点统计摘要
                self.logger.info(f"[节点] 监控节点: {alive_nodes}/{total_monitored_nodes} 正常运行")

                result = {
                    'monitored_nodes': nodes_status,
                    'all_system_nodes': all_nodes,
                    'statistics': statistics
                }

                self._cache['ros2_nodes'] = result
                self._cache['last_update'] = time.time()
                return result

            except Exception as e:
                self.logger.error(f"获取ROS2节点状态失败: {e}\n{traceback.format_exc()}")
                return {
                    'monitored_nodes': {},
                    'all_system_nodes': [],
                    'statistics': {}
                }

    def _get_raw_ros2_nodes(self) -> List[str]:
        """获取原始ROS2节点列表（不过滤）"""
        nodes = []
        
        # 使用rclpy API获取原始节点列表
        try:
            node_names = self.node.get_node_names()
            namespace = self.node.get_namespace()
            if namespace == '/':
                for name in node_names:
                    nodes.append(f'/{name}')
            else:
                for name in node_names:
                    if namespace.endswith('/'):
                        nodes.append(f'{namespace}{name}')
                    else:
                        nodes.append(f'{namespace}/{name}')
        except Exception as e:
            self.logger.debug(f"获取原始节点列表失败: {e}")
        
        return nodes
    
    def _get_ros2_nodes(self) -> List[str]:
        """获取ROS2节点列表（增强版本，过滤系统节点）"""
        nodes = []
        
        # 方法1：使用rclpy API（加载优化：重试 3→1，doc/前端页面加载优化）
        max_retries = 1
        for retry in range(max_retries):
            try:
                node_names = self.node.get_node_names()
                if node_names:
                    namespace = self.node.get_namespace()
                    if namespace == '/':
                        for name in node_names:
                            nodes.append(f'/{name}')
                    else:
                        for name in node_names:
                            # 确保命名空间格式正确
                            if namespace.endswith('/'):
                                nodes.append(f'{namespace}{name}')
                            else:
                                nodes.append(f'{namespace}/{name}')
                    self.logger.debug(f"通过API获取到 {len(node_names)} 个节点")
                    break
                else:
                    self.logger.debug(f"第{retry+1}次重试获取节点列表")
                    time.sleep(0.5)
            except Exception as e:
                self.logger.debug(f"API获取节点失败，重试{retry+1}/{max_retries}: {e}")
                if retry == max_retries - 1:
                    self.logger.warning(f"无法通过API获取节点: {e}")
        
        # 方法2：使用命令行作为备选
        if not nodes:
            try:
                result = subprocess.run(
                    ['ros2', 'node', 'list'],
                    capture_output=True,
                    text=True,
                    timeout=3   # 加载优化：10s→3s（doc/前端页面加载优化）
                )
                
                if result.returncode == 0:
                    raw_nodes = [node.strip() for node in result.stdout.split('\n') if node.strip()]
                    # 过滤掉可能包含的命名空间重复
                    for node in raw_nodes:
                        if node not in nodes:
                            nodes.append(node)
                    self.logger.debug(f"命令行获取到 {len(nodes)} 个节点")
            except FileNotFoundError:
                self.logger.warning("ros2命令未找到，请确保ROS2环境正确设置")
            except Exception as e:
                self.logger.debug(f"命令行获取节点失败: {e}")
        
        # 过滤不需要的系统节点
        filtered_nodes = self._filter_system_nodes(nodes)
        
        self.logger.debug(f"原始节点列表: {nodes}")
        self.logger.debug(f"过滤后节点: {filtered_nodes}")
        
        return filtered_nodes
    
    
    def _get_lanes_cache_status(self) -> Dict[str, Any]:
        """
        从 DeviceStatusManager 获取所有区域状态，按通道分组返回。
        每个通道包含信号状态和区域内各位置的有货/无货信息。
        """
        try:
            device_manager = getattr(self.node, 'device_manager', None)
            if not device_manager:
                self.logger.warning("device_manager 未就绪，返回空数据")
                return {'channels': []}

            summary = device_manager.get_all_status_summary()
            channels = []

            # 遍历设备（通常只有一个 dev01）
            for device_id, device_info in summary.get('devices', {}).items():
                # 按通道 ID 排序，保证 0,1,2 顺序
                for channel_id in sorted(device_info.get('channels', {}).keys()):
                    ch_data = device_info['channels'][channel_id]
                    areas = []

                    # 区域名按字典序排序（如 A001 ~ A005）
                    for area_name in sorted(ch_data.get('areas', {}).keys()):
                        area_status = ch_data['areas'][area_name]
                        areas.append({
                            'name': area_name,                             # 完整名称，如 510201A001
                            'has_object': area_status.get('stable_state', False)
                        })

                    channels.append({
                        'channel_id': channel_id,
                        'signal_status': ch_data.get('signal_stable', False),
                        'areas': areas
                    })

            return {'channels': channels}

        except Exception as e:
            self.logger.error(f"获取区域状态失败: {e}")
            return {'channels': []}

    def _filter_system_nodes(self, nodes: List[str]) -> List[str]:
        """过滤系统节点，只保留应用节点，模式从配置读取"""
        # 从配置获取过滤模式，若缺失则使用默认模式
        default_patterns = [
            r'^/_ros2cli_daemon_',
            r'^/_rosapi',
            r'^/_rosbridge',
            r'^/launch_ros',
            r'^/rosout',
        ]
        patterns = self.config.get('system_node_patterns', default_patterns)
        if not isinstance(patterns, list):
            patterns = default_patterns
        
        import re
        filtered = []
        for node in nodes:
            keep_node = True
            for pattern in patterns:
                if re.match(pattern, node):
                    keep_node = False
                    self.logger.debug(f"过滤系统节点: {node} (匹配模式: {pattern})")
                    break
            if keep_node:
                filtered.append(node)
        return filtered
    
    def _get_node_pid(self, node_name: str) -> Optional[int]:
        try:
            # ---- 方法1：通过 ros2 node info 命令获取 PID ----
            result = subprocess.run(
                ['ros2', 'node', 'info', node_name],
                capture_output=True,
                text=True,
                timeout=2   # 加载优化：3s→2s（doc/前端页面加载优化）
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    # 兼容多种 PID 关键词（ROS 2 Humble / Iron 等版本差异）
                    if any(keyword in line for keyword in ('PID', 'Process ID', 'Pid')):
                        try:
                            # 按冒号或空格分割，提取数字部分
                            parts = line.replace(':', ' ').split()
                            for p in parts:
                                if p.isdigit():
                                    return int(p)
                        except Exception:
                            continue
            
            # ---- 方法2：通过 psutil 查找进程 ----
            # 去除节点名前导斜杠，适应命令行参数格式
            search_name = node_name.lstrip('/')
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info['cmdline']
                    if cmdline:
                        # 检查命令行中是否包含节点名（含或不含前导斜杠）
                        for cmd in cmdline:
                            if node_name in cmd or search_name in cmd:
                                return proc.info['pid']
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                        
            return None
            
        except Exception as e:
            self.logger.debug(f"获取节点 {node_name} PID 失败: {e}")
            return None
    
    def _get_node_uptime(self, node_name: str) -> Optional[str]:
        """获取节点运行时间"""
        try:
            pid = self._get_node_pid(node_name)
            if pid is None:
                return None
            
            try:
                proc = psutil.Process(pid)
                create_time = proc.create_time()
                uptime_seconds = time.time() - create_time
                return self._format_uptime(uptime_seconds)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None
                
        except Exception as e:
            self.logger.debug(f"获取节点运行时间失败: {e}")
            return None
    
    def _format_uptime(self, seconds: float) -> str:
        """格式化运行时间"""
        if seconds < 60:
            return f"{int(seconds)}秒"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}分{secs}秒"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}时{minutes}分"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}天{hours}时"
    
    def get_channels_status(self) -> Dict[str, Any]:
        with self._lock:
            try:
                device_manager = getattr(self.node, 'device_manager', None)
                if device_manager is not None:
                    channels_data = self._format_device_manager_status(device_manager)
                    self._cache['channels'] = channels_data
                    self._cache['last_update'] = time.time()
                    return channels_data

                # 当 device_manager 不存在时，返回缓存或默认空数据
                self.logger.debug("device_manager 未就绪，返回缓存或默认通道状态")
                return self._cache.get('channels', {
                    'channels': {},
                    'total_channels': 0,
                    'normal_channels': 0,
                    'abnormal_channels': 0,
                    'health_rate': 0,
                    'last_check': time.time()
                })

            except Exception as e:
                self.logger.error(f"获取通道状态失败: {e}")
                return self._cache.get('channels', {
                    'channels': {},
                    'total_channels': 0,
                    'normal_channels': 0,
                    'abnormal_channels': 0,
                    'health_rate': 0,
                    'last_check': time.time()
                })
                
    def _format_device_manager_status(self, device_manager) -> Dict[str, Any]:
        """将 DeviceStatusManager 的结构转换为前端展示的通道状态格式"""
        summary = device_manager.get_all_status_summary()
        channels = {}
        total_channels = 0
        normal_channels = 0

        # 遍历所有设备和通道
        for device_id, device_info in summary.get('devices', {}).items():
            for channel_id, channel_data in device_info.get('channels', {}).items():
                total_channels += 1
                signal_status = channel_data.get('signal_stable', False)
                if signal_status:
                    normal_channels += 1

                # 区域占位详情（可进一步解析 areas）
                area_details = channel_data.get('areas', {})
                occupied = sum(1 for a in area_details.values() if a.get('stable_state'))
                empty = len(area_details) - occupied

                channel_key = f"device_{device_id}_channel_{channel_id}"
                alias = self.channel_aliases.get(channel_key, f"设备{device_id}通道{channel_id}")
                last_update = time.time()  # 从 device_manager 内部无法获得精确时间，用当前时间近似

                channels[channel_key] = {
                    'device_id': device_id,
                    'channel_id': channel_id,
                    'signal_status': signal_status,
                    'last_update': last_update,
                    'last_update_str': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_update)),
                    'alias': alias,
                    'status': 'normal' if signal_status else 'abnormal',
                    'status_color': 'success' if signal_status else 'danger',
                    'requires_restart': not signal_status,
                    'area_summary': {'occupied': occupied, 'empty': empty},
                    'raw_info': channel_data
                }

        health_rate = (normal_channels / total_channels * 100) if total_channels > 0 else 0

        return {
            'channels': channels,
            'total_channels': total_channels,
            'normal_channels': normal_channels,
            'abnormal_channels': total_channels - normal_channels,
            'health_rate': round(health_rate, 1),
            'last_check': time.time()
        }            
                
    
    def _get_channels_from_callback(self) -> Dict[str, Any]:
        """从回调接口获取通道状态"""
        try:
            # 构造请求URL
            host = self.callback_server.get('host', '127.0.0.1')
            port = self.callback_server.get('port', 8080)
            base_path = self.callback_server.get('base_path', '/eyeSky/robot/reporter')
            
            url = f"http://{host}:{port}{base_path}/channel/status"
            params = {'pretty': 'true'}  # 添加pretty参数
            
            self.logger.debug(f"请求通道状态: {url}")
            
            # 发送HTTP请求
            response = requests.get(url, params=params, timeout=self._http_timeout)
            response.raise_for_status()
            
            data = response.json()
            
            # 解析通道数据
            channels = data.get('channels', {})
            
            channels_status = {
                'channels': {},
                'total_channels': 0,
                'normal_channels': 0,
                'abnormal_channels': 0,
                'health_rate': 0,
                'last_check': time.time(),
                'raw_data': data
            }
            
            total = 0
            normal = 0
            
            # 遍历所有设备
            for device_id, device_channels in channels.items():
                # 遍历设备的所有通道
                for channel_id_str, channel_info in device_channels.items():
                    try:
                        channel_id = int(channel_id_str)
                        channel_key = f"device_{device_id}_channel_{channel_id}"
                        
                        total += 1
                        
                        signal_status = channel_info.get('signal_status', False)
                        if signal_status:
                            normal += 1
                        
                        # 使用别名配置
                        alias = self.channel_aliases.get(
                            f"channel_{channel_id}", 
                            f"设备{device_id}通道{channel_id}"
                        )
                        
                        status_color = 'success' if signal_status else 'danger'
                        
                        # 处理时间戳
                        last_update_raw = channel_info.get('last_update')
                        if last_update_raw:
                            try:
                                # 尝试解析为浮点数
                                last_update = float(last_update_raw)
                            except (ValueError, TypeError):
                                # 如果不行，使用当前时间
                                last_update = time.time()
                        else:
                            last_update = time.time()
                        
                        channels_status['channels'][channel_key] = {
                            'device_id': device_id,
                            'channel_id': channel_id,
                            'signal_status': signal_status,
                            'last_update': last_update,  # 确保是浮点数
                            'last_update_str': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_update)),
                            'alias': alias,
                            'status': 'normal' if signal_status else 'abnormal',
                            'status_color': status_color,
                            'requires_restart': not signal_status,  # 需要重启的标志
                            'raw_info': channel_info
                        }
                        
                    except (ValueError, KeyError) as e:
                        self.logger.debug(f"解析通道信息失败: {e}")
                        continue
            
            channels_status['total_channels'] = total
            channels_status['normal_channels'] = normal
            channels_status['abnormal_channels'] = total - normal
            channels_status['health_rate'] = (normal / total * 100) if total > 0 else 0
            
            self.logger.debug(f"获取到 {total} 个通道，{normal} 个正常，健康率: {channels_status['health_rate']:.1f}%")
            
            return channels_status
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP请求通道状态失败: {e}")
            # 返回空数据
            return {
                'channels': {},
                'total_channels': 0,
                'normal_channels': 0,
                'abnormal_channels': 0,
                'health_rate': 0,
                'last_check': time.time(),
                'error': str(e)
            }
        except Exception as e:
            self.logger.error(f"解析通道状态失败: {e}")
            raise
    
    def get_services_status(self) -> Dict[str, Any]:
        with self._lock:
            try:
                if self.operation_mode != 'deployment':
                    self._cache['services'] = {}
                    return {}
                
                services_status = {}
                for service_name in self.monitored_services:    # 使用动态列表
                    status = self._get_systemd_service_status(service_name)
                    services_status[service_name] = status
                
                self._cache['services'] = services_status
                self._cache['last_update'] = time.time()
                return services_status
            except Exception as e:
                self.logger.error(f"获取服务状态失败: {e}")
                return self._cache.get('services', {})
            
            
    
    def _get_systemd_service_status(self, service_name: str) -> Dict[str, Any]:
        """获取systemd服务状态"""
        try:
            # 使用systemctl命令获取服务状态
            result = subprocess.run(
                ['sudo', 'systemctl', 'status', service_name],
                capture_output=True,
                text=True,
                timeout=3   # 加载优化：5s→3s（doc/前端页面加载优化）
            )
            
            output = result.stdout + result.stderr
            is_running = 'active (running)' in output
            is_enabled = 'enabled' in output
            
            return {
                'is_running': is_running,
                'is_enabled': is_enabled,
                'last_check': time.time(),
                'output': output,
                'status': 'running' if is_running else 'stopped',
                'status_color': 'success' if is_running else 'danger',
                'requires_restart': not is_running  # 需要重启的标志
            }
            
        except Exception as e:
            self.logger.debug(f"获取服务 {service_name} 状态失败: {e}")
            return {
                'is_running': False,
                'is_enabled': False,
                'last_check': time.time(),
                'output': str(e),
                'status': 'unknown',
                'status_color': 'warning',
                'requires_restart': False
            }
    
    def get_system_status(self) -> Dict[str, Any]:
        """获取完整系统状态（优化版）"""
        try:
            # 并行获取各种状态
            import concurrent.futures
            
            # 加载优化：result(timeout=2.5) 兜底 + shutdown(wait=False)，单探测不拖垮 /api/status（doc/前端页面加载优化）
            _executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
            _n_f = _executor.submit(self.get_ros2_nodes_status)
            _c_f = _executor.submit(self.get_channels_status)
            _s_f = _executor.submit(self.get_services_status)

            def _r(fut, dft):
                try:
                    return fut.result(timeout=2.5)
                except Exception:
                    return dft

            nodes_status = _r(_n_f, self._cache.get('ros2_nodes', {}))
            channels_status = _r(_c_f, self._cache.get('channels', {
                'channels': {}, 'total_channels': 0, 'normal_channels': 0,
                'abnormal_channels': 0, 'health_rate': 0}))
            services_status = _r(_s_f, {})
            _executor.shutdown(wait=False)   # 超时任务后台继续，不阻塞
            
            # 添加调试日志
            self.logger.debug(f"节点状态结构: keys={list(nodes_status.keys())}")
            self.logger.debug(f"通道状态结构: keys={list(channels_status.keys())}")
            self.logger.debug(f"服务状态数量: {len(services_status)}")
            
            # 计算健康分数
            health_score = self._calculate_health_score(nodes_status, channels_status, services_status)
            
            # 获取系统负载信息
            system_load = self._get_system_load()
            
            # 获取巷道缓存状态
            lanes_cache_status = self._get_lanes_cache_status()
            
            # 构建完整状态
            status = {
                'timestamp': time.time(),
                'nodes': nodes_status,
                'channels': channels_status,
                'services': services_status,
                'health_score': health_score,
                'system_info': {
                    **self._cache.get('system_info', {}),
                    **system_load,
                    'operation_mode': self.operation_mode
                },
                'status': 'healthy' if health_score >= 80 else 'warning' if health_score >= 60 else 'critical',
                'requires_action': self._check_requires_action(nodes_status, channels_status, services_status),
                'lanes_cache': lanes_cache_status,
                'operation_mode': self.operation_mode
            }
            
            self.logger.info(f"系统状态获取完成: 健康度={health_score}%, 状态={status['status']}")
            
            return status
            
        except Exception as e:
            self.logger.error(f"获取系统状态失败: {e}\n{traceback.format_exc()}")
            
            return {
                'timestamp': time.time(),
                'status': 'error',
                'message': str(e),
                'health_score': 80.0,  # 返回一个默认健康度，避免前端显示0.0%
                'requires_action': False
            }
    
    def _calculate_health_score(self, nodes_status: Dict[str, Any], 
                           channels_status: Dict[str, Any], 
                           services_status: Dict[str, Any]) -> float:
        """计算健康分数（修复版）"""
        try:
            # 节点健康度 (权重: 40%)
            node_weight = 0.4
            node_health = 100  # 默认值
            
            # 从新的数据结构中获取监控的节点
            monitored_nodes = nodes_status.get('monitored_nodes', {})
            
            if monitored_nodes:
                alive_nodes = sum(1 for node in monitored_nodes.values() 
                                if node.get('alive', False))
                total_monitored = len(monitored_nodes)
                
                if total_monitored > 0:
                    node_health = (alive_nodes / total_monitored * 100)
                    self.logger.debug(f"节点健康度计算: {alive_nodes}/{total_monitored} = {node_health}%")
            else:
                # 如果monitored_nodes为空，检查是否是旧的数据结构
                node_health = 0
                for node_info in nodes_status.values():
                    if isinstance(node_info, dict) and 'alive' in node_info:
                        alive = node_info.get('alive', False)
                        node_health = 100 if alive else 0
                        break
            
            # 通道健康度 (权重: 40%)
            channel_weight = 0.4
            # 从channels_status中获取健康率，如果没有则从channels数据中计算
            channel_health = channels_status.get('health_rate', 0)
            
            if channel_health == 0:
                # 如果health_rate为0，尝试从channels数据中计算
                channels = channels_status.get('channels', {})
                if channels:
                    normal_count = sum(1 for channel in channels.values() 
                                    if channel.get('signal_status', False))
                    total_channels = len(channels)
                    if total_channels > 0:
                        channel_health = (normal_count / total_channels * 100)
            
            # 服务健康度 (权重: 20%)
            service_weight = 0.2
            service_health = 100  # 默认值
            
            if services_status:
                running_services = sum(1 for service in services_status.values() 
                                    if service.get('is_running', False))
                total_services = len(services_status)
                
                if total_services > 0:
                    service_health = (running_services / total_services * 100)
            else:
                # 开发模式下没有服务，服务健康度为100%
                if self.operation_mode == 'development':
                    service_health = 100
                else:
                    service_health = 0
            
            # 加权计算总健康度
            self.logger.debug(f"健康度计算权重: 节点={node_health}%*{node_weight}, 通道={channel_health}%*{channel_weight}, 服务={service_health}%*{service_weight}")
            
            total_health = (
                node_health * node_weight + 
                channel_health * channel_weight + 
                service_health * service_weight
            )
            
            self.logger.debug(f"系统健康度计算完成: {total_health:.1f}% (节点:{node_health:.1f}%, 通道:{channel_health:.1f}%, 服务:{service_health:.1f}%)")
            
            return round(total_health, 1)
            
        except Exception as e:
            self.logger.error(f"计算健康分数失败: {e}\n{traceback.format_exc()}")
            # 返回一个默认值，避免前端显示0.0%
            return 80.0  # 假设系统基本健康
    
    def _get_system_load(self) -> Dict[str, Any]:
        """获取系统负载信息"""
        try:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # 内存使用
            memory = psutil.virtual_memory()
            
            # 磁盘使用
            disk = psutil.disk_usage('/')
            
            # 系统负载
            load_avg = psutil.getloadavg()
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_used_gb': round(memory.used / (1024**3), 2),
                'memory_total_gb': round(memory.total / (1024**3), 2),
                'disk_percent': disk.percent,
                'disk_used_gb': round(disk.used / (1024**3), 2),
                'disk_total_gb': round(disk.total / (1024**3), 2),
                'load_avg_1min': load_avg[0],
                'load_avg_5min': load_avg[1],
                'load_avg_15min': load_avg[2]
            }
        except Exception as e:
            self.logger.debug(f"获取系统负载失败: {e}")
            return {}
    
    def _check_requires_action(self, nodes_status: Dict[str, Any],
                          channels_status: Dict[str, Any],
                          services_status: Dict[str, Any]) -> bool:
        """检查是否需要操作（重启等）- 修复版"""
        try:
            # 检查节点是否需要重启
            monitored_nodes = nodes_status.get('monitored_nodes', {})
            if not monitored_nodes:
                # 兼容旧数据结构
                monitored_nodes = nodes_status
            
            for node_info in monitored_nodes.values():
                if node_info.get('requires_restart', False):
                    self.logger.debug(f"节点需要重启: {node_info.get('name', 'unknown')}")
                    return True
            
            # 检查通道是否需要重启
            channels = channels_status.get('channels', {})
            for channel_info in channels.values():
                if channel_info.get('requires_restart', False):
                    self.logger.debug(f"通道需要重启: {channel_info.get('alias', 'unknown')}")
                    return True
            
            # 检查服务是否需要重启
            for service_name, service_info in services_status.items():
                if service_info.get('requires_restart', False):
                    self.logger.debug(f"服务需要重启: {service_name}")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.debug(f"检查是否需要操作失败: {e}")
            return False
    
    def get_cached_status(self) -> Dict[str, Any]:
        """获取缓存的状态"""
        with self._lock:
            return self._cache.copy()
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        status = self.get_cached_status()
        
        nodes_status = status.get('ros2_nodes', {})
        channels_status = status.get('channels', {})
        services_status = status.get('services', {})
        
        # 统计
        total_nodes = len(nodes_status)
        alive_nodes = sum(1 for n in nodes_status.values() if n.get('alive', False))
        
        total_channels = channels_status.get('total_channels', 0)
        normal_channels = channels_status.get('normal_channels', 0)
        
        total_services = len(services_status)
        running_services = sum(1 for s in services_status.values() if s.get('is_running', False))
        
        return {
            'timestamp': status.get('last_update', 0),
            'nodes': {
                'total': total_nodes,
                'alive': alive_nodes,
                'health_percent': (alive_nodes / total_nodes * 100) if total_nodes > 0 else 0
            },
            'channels': {
                'total': total_channels,
                'normal': normal_channels,
                'health_percent': channels_status.get('health_rate', 0)
            },
            'services': {
                'total': total_services,
                'running': running_services,
                'health_percent': (running_services / total_services * 100) if total_services > 0 else 0
            },
            'system_info': status.get('system_info', {})
        }