#!/usr/bin/env python3
"""
推理图像管理器 - 标定模块核心
订阅调试图像话题，提供帧缓存、参数读写、区域保存功能
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import threading
import subprocess
import yaml
import os
import time
import re        
import shlex        
from typing import Dict, Optional, List, Any

class InferenceImageManager:
    def __init__(self, node: Node, config: dict):
        self.node = node
        self.logger = node.get_logger()
        self.config = config
        self.bridge = CvBridge()
        self.latest_frames: Dict[int, cv2.Mat] = {}
        self._lock = threading.Lock()
        self._subscribers = []

        # 读取配置参数
        self.image_topic_base = config.get('image_topic_base', '/debug/rtsp_')
        self.device_id = config.get('device_id', 'dev01')
        self.channel_count = config.get('channel_count', 2)
        self.target_node = config.get('target_node', '/rtsp_multi_inference')
        self.config_file = config.get('config_file', '')

        self._setup_subscriptions()
        
        self._frame_timestamps: Dict[int, float] = {}   # 记录每通道最新帧时间戳
        
        # self._frame_events: Dict[int, threading.Event] = {}
        # for i in range(self.channel_count):
        #     self._frame_events[i] = threading.Event()
    
    def _setup_subscriptions(self):
        from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE
        )
        for i in range(self.channel_count):
            topic = f"{self.image_topic_base}{self.device_id}_{i}"
            sub = self.node.create_subscription(
                Image, topic,
                lambda msg, ch=i: self._image_callback(msg, ch),
                qos
            )
            self._subscribers.append(sub)          # 使用已有的列表
            self.logger.info(f"[Calibration] Subscribed to {topic}")
            
    # ===== P4 v2：标定配置从 OPS 自动同步（doc/P4 §9，消除双配置） =====
    def sync_from_ops(self, proxy):
        """从 OPS /api/calibration/status 同步 channel_count/topic_base/device_id/target_node；
        配置变化时重建订阅；OPS 不可达/失败返回 False（保留 yaml 降级配置）"""
        if not proxy:
            return False
        try:
            r = proxy.calibration("GET", "/api/calibration/status")
            if not isinstance(r, dict) or not r.get("success", False):
                return False
            new_count = int(r.get("channel_count", self.channel_count) or self.channel_count)
            new_base = r.get("topic_base") or self.image_topic_base
            new_dev = r.get("device_id") or self.device_id
            new_target = r.get("target_node") or self.target_node
            changed = (new_count != self.channel_count or new_base != self.image_topic_base
                       or new_dev != self.device_id or new_target != self.target_node)
            if not changed:
                return True
            self.logger.info(
                f"[Calibration] OPS 配置同步: channel_count {self.channel_count}→{new_count}, "
                f"topic_base={new_base}, device_id={new_dev}, target_node={new_target}")
            self.channel_count = new_count
            self.image_topic_base = new_base
            self.device_id = new_dev
            self.target_node = new_target
            self.rebuild_subscriptions()
            return True
        except Exception as e:
            self.logger.warning(f"[Calibration] OPS 配置同步失败: {e}")
            return False

    def rebuild_subscriptions(self):
        """销毁全部订阅并按当前配置重建（OPS 同步后）"""
        with self._lock:
            for sub in self._subscribers:
                try:
                    self.node.destroy_subscription(sub)
                except Exception:
                    pass
            self._subscribers = []
        self._setup_subscriptions()

    def renew_subscription(self, channel_id: int):
        """销毁并重新创建指定通道的订阅"""
        if channel_id >= len(self._subscribers):
            self.logger.warning(f"Channel {channel_id} out of range, cannot renew")
            return
        # 销毁旧的订阅
        old_sub = self._subscribers[channel_id]
        self.node.destroy_subscription(old_sub)
        # 创建新订阅
        topic = f"{self.image_topic_base}{self.device_id}_{channel_id}"
        from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE
        )
        new_sub = self.node.create_subscription(
            Image, topic,
            lambda msg, ch=channel_id: self._image_callback(msg, ch),
            qos
        )
        self._subscribers[channel_id] = new_sub
        self.logger.info(f"[Calibration] Renewed subscription for channel {channel_id}")

    # def _setup_subscriptions(self):
    #     from rclpy.qos import qos_profile_sensor_data
    #     for i in range(self.channel_count):
    #         topic = f"{self.image_topic_base}{self.device_id}_{i}"
    #         self._subscribers.append(
    #             self.node.create_subscription(
    #                 Image, topic,
    #                 lambda msg, ch=i: self._image_callback(msg, ch),
    #                 qos_profile_sensor_data
    #             )
    #         )
    #         self.logger.info(f"[Calibration] Subscribed to {topic}")

    def _image_callback(self, msg: Image, channel_id: int):
        try:
            cv_img = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
            # 提取时间戳（优先使用消息自带的时间，单位：秒）
            if msg.header.stamp.sec > 0 or msg.header.stamp.nanosec > 0:
                ts = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            else:
                ts = time.time()   # 若消息未设置时间戳，使用接收时刻
            with self._lock:
                self.latest_frames[channel_id] = cv_img
                self._frame_timestamps[channel_id] = ts
            
            # 通知等待的 WebSocket 协程：新帧已到
            # self._frame_events[channel_id].set()
        except Exception as e:
            self.logger.error(f"Image callback error for ch{channel_id}: {e}")
            
    # 阻塞等待新帧（供 WebSocket 使用）
    # def wait_for_new_frame(self, channel_id: int, timeout: float = None) -> bool:
    #     """
    #     等待新帧到达，返回 True 表示有新帧，False 表示超时。
    #     每次调用后会自动清除事件标志。
    #     """
    #     event = self._frame_events[channel_id]
    #     if event.wait(timeout):
    #         event.clear()        # 清除标志，准备下次等待
    #         return True
    #     return False
            
    def get_latest_frame_with_ts(self, channel_id: int) -> Optional[tuple]:
        """返回 (帧图像, 时间戳) 或 None"""
        with self._lock:
            frame = self.latest_frames.get(channel_id)
            ts = self._frame_timestamps.get(channel_id, time.time())
            if frame is None:
                return None
            return (frame, ts)        

    def get_latest_frame(self, channel_id: int) -> Optional[cv2.Mat]:
        with self._lock:
            return self.latest_frames.get(channel_id)

    def get_channel_count(self) -> int:
        return self.channel_count

    # ---------- 推理节点参数操作 ----------
    def _run_ros2_param(self, cmd_type: str, name: str, value=None) -> (bool, str):
        """执行 ros2 param get/set 命令"""
        if cmd_type == 'get':
            cmd = f"ros2 param get {self.target_node} {name}"
        else:
            yaml_str = yaml.dump(value, default_flow_style=True).strip()
            cmd = f"ros2 param set {self.target_node} {name} {shlex.quote(yaml_str)}"
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            self.logger.error(f"ros2 param command failed: {e}")
            return False, str(e)

    def get_inference_param(self, name: str) -> Optional[Any]:
        """获取推理节点参数，兼容多种输出格式"""
        success, output = self._run_ros2_param('get', name)
        if not success:
            self.logger.warning(f"ros2 param get {name} failed")
            return None

        output = output.strip()
        self.logger.info(f"Raw output for {name}: {output}")

        # 提取第一个冒号后面的所有内容（忽略前缀描述如 "String values are:"）
        match = re.search(r':\s*(.*)', output, re.DOTALL)
        if not match:
            self.logger.warning(f"Cannot extract value from output: {output}")
            return None

        val_str = match.group(1).strip()

        # 处理 Python array('q', [...]) 格式
        if val_str.startswith('array('):
            start_idx = val_str.find('[')
            end_idx = val_str.rfind(']')
            if start_idx != -1 and end_idx != -1:
                inner = val_str[start_idx:end_idx+1]
                try:
                    points = yaml.safe_load(inner)   # 用 yaml 解析，无需 ast
                    if isinstance(points, list):
                        return points
                    else:
                        self.logger.error(f"Parsed value is not a list: {points}")
                        return None
                except Exception as e:
                    self.logger.error(f"Failed to parse array literal with yaml: {e}")
                    return None
            else:
                return None

        # 尝试 YAML 解析
        try:
            value = yaml.safe_load(val_str)
            return value
        except Exception:
            self.logger.error(f"YAML parse failed for {name}, raw value: {val_str}")
            return val_str

    def _set_remote_parameters(self, channel_id: int, names: List[str], points: List[int]) -> bool:
        """使用 ros2 param set 命令设置远程节点参数，带超时保护"""
        try:
            # 设置名称列表
            names_str = yaml.dump(names, default_flow_style=True).strip()
            cmd_names = f"ros2 param set {self.target_node} polygon_ch{channel_id}_names {shlex.quote(names_str)}"
            self.logger.info(f"Executing: {cmd_names}")
            result = subprocess.run(cmd_names, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                self.logger.error(f"  ✗ Failed to set names: {result.stderr.strip()}")
                return False
            self.logger.info(f"  ✓ names set")

            # 设置坐标点列表
            points_str = yaml.dump(points, default_flow_style=True).strip()
            cmd_points = f"ros2 param set {self.target_node} polygon_ch{channel_id}_points {shlex.quote(points_str)}"
            self.logger.info(f"Executing: {cmd_points}")
            result = subprocess.run(cmd_points, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                self.logger.error(f"  ✗ Failed to set points: {result.stderr.strip()}")
                return False
            self.logger.info(f"  ✓ points set - hot reload triggered!")
            return True
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout setting remote parameters for channel {channel_id}")
            return False
        except Exception as e:
            self.logger.error(f"Exception setting remote parameters: {e}")
            return False
        
    def set_inference_param(self, name: str, value) -> bool:
        """设置单个推理节点参数（如视频发布开关），使用安全命令行"""
        try:
            yaml_str = yaml.dump(value, default_flow_style=True).strip()
            cmd = f"ros2 param set {self.target_node} {name} {shlex.quote(yaml_str)}"
            self.logger.info(f"Executing: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                self.logger.error(f"ros2 param set failed: {result.stderr.strip()}")
                return False
            return True
        except Exception as e:
            self.logger.error(f"set_inference_param exception: {e}")
            return False

    # ---------- 区域数据操作 ----------
    def get_inference_areas(self, channel_id: int) -> Optional[List[dict]]:
        """从推理节点获取多边形区域（标定数据）"""
        try:
            names = self.get_inference_param(f"polygon_ch{channel_id}_names")
            points = self.get_inference_param(f"polygon_ch{channel_id}_points")

            self.logger.info(f"Polygon names type: {type(names)}, points type: {type(points)}")
            if not isinstance(names, list) or not isinstance(points, list):
                self.logger.warning(
                    f"Polygon params for channel {channel_id} are not lists, "
                    f"names={names}, points={points}"
                )
                return []

            areas = []
            current = []
            area_idx = 0
            for v in points:
                if v == -1:
                    if current and area_idx < len(names):
                        pts = [[current[i], current[i+1]] for i in range(0, len(current), 2)]
                        areas.append({
                            "name": names[area_idx],
                            "type": "polygon",
                            "points": pts
                        })
                        area_idx += 1
                        current = []
                else:
                    current.append(v)
            # 处理末尾无 -1 的情况
            if current and area_idx < len(names):
                pts = [[current[i], current[i+1]] for i in range(0, len(current), 2)]
                areas.append({
                    "name": names[area_idx],
                    "type": "polygon",
                    "points": pts
                })
            return areas
        except Exception as e:
            self.logger.error(f"get_inference_areas error: {e}")
            return []

    def save_calibration(self, channel_id: int, areas: List[dict]) -> bool:
        """保存标定数据：先写 YAML 文件，再远程热更新"""
        try:
            # 提取名称和坐标，并强制坐标转为 int
            names = [area['name'] for area in areas]
            points = []
            for area in areas:
                for pt in area.get('points', []):
                    # pt 可能是 [x, y]，强制转换整数
                    points.append(int(pt[0]))
                    points.append(int(pt[1]))
                points.append(-1)

            # 1. 持久化到 YAML 文件
            if self.config_file:
                self._update_yaml_file(channel_id, names, points)
            else:
                self.logger.warning("No config_file specified, skipping file write")

            # 2. 远程热更新
            self.logger.info(f"Setting remote parameters on node '{self.target_node}'")
            remote_ok = self._set_remote_parameters(channel_id, names, points)
            if not remote_ok:
                self.logger.warning("Remote update failed, but YAML file has been saved")

            self.logger.info(f"Completed save_calibration for channel {channel_id}")
            return True
        except Exception as e:
            self.logger.error(f"save_calibration error: {e}")
            return False

    def _update_yaml_file(self, channel_id: int, names: List[str], points: List[int]):
        """安全写入 YAML，自动匹配节点名，不破坏其他参数"""
        try:
            # 读取原文件
            file_content = {}
            if os.path.exists(self.config_file) and os.path.getsize(self.config_file) > 0:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    file_content = yaml.safe_load(f) or {}
            else:
                self.logger.warning(f"{self.config_file} empty or missing, creating new")

            # 兼容节点名带不带前导斜杠
            short_name = self.target_node.lstrip('/')
            long_name = '/' + short_name

            node_key = None
            if long_name in file_content:
                node_key = long_name
            elif short_name in file_content:
                node_key = short_name
            else:
                node_key = long_name  # 新建使用规范写法

            # 确保节点字典存在
            if node_key not in file_content:
                file_content[node_key] = {}
            node_dict = file_content[node_key]
            ros_params = node_dict.setdefault('ros__parameters', {})

            # 强制坐标整数化（防止浮点数混入）
            int_points = [int(p) for p in points]

            # 更新参数
            ros_params[f"polygon_ch{channel_id}_names"] = names
            ros_params[f"polygon_ch{channel_id}_points"] = int_points

            # 写回文件（width=1000 防止长数组被折行）
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(file_content, f,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                        indent=2,
                        width=1000)
            self.logger.info(f"Updated config file: {self.config_file}")

        except Exception as e:
            self.logger.error(f"Failed to update YAML: {e}")
            raise
        
    def get_last_frame_ts(self, channel_id: int) -> float:
        """返回最新帧的时间戳，若还没有帧则返回 0"""
        with self._lock:
            return self._frame_timestamps.get(channel_id, 0.0)

    def get_frame_and_ts_if_newer(self, channel_id: int, base_ts: float) -> tuple:
        """
        如果最新帧的时间戳比 base_ts 更新，则返回 (frame, ts)；
        否则返回 (None, current_ts)
        """
        with self._lock:
            frame = self.latest_frames.get(channel_id)
            ts = self._frame_timestamps.get(channel_id, 0.0)
            if frame is None:
                return None, ts
            if ts > base_ts:
                return frame, ts
            else:
                return None, ts
            
    def clear_channel_cache(self, channel_id: int, renew_sub: bool = True):
        """清除指定通道的帧缓存，并可选择重建订阅"""
        with self._lock:
            self.latest_frames.pop(channel_id, None)
            self._frame_timestamps.pop(channel_id, None)
        if renew_sub:
            self.renew_subscription(channel_id)
        self.logger.info(f"Cleared frame cache for channel {channel_id}")
            
    def shutdown(self):
        for sub in self._subscribers:
            self.node.destroy_subscription(sub)
        self._subscribers.clear()
        self.latest_frames.clear()
        self.logger.info("Image manager shut down")