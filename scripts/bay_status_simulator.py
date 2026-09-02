#!/usr/bin/env python3
"""
bay_status_simulator.py — 增强版
支持键盘手动控制和自动任务完成更新
发布 /dev01_object_status (BayStatus)
订阅 /task_completed (TaskCompleted)
"""

import json
import time
import threading
import sys
import os
from typing import Dict, Optional

# ════════════════════════════════════════════════════════════
#  ROS2 初始化
# ════════════════════════════════════════════════════════════
try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    RCLPY_AVAILABLE = True
except ImportError:
    print("[ERROR] rclpy 未安装，请检查 ROS2 环境")
    sys.exit(1)

# 尝试导入自定义消息
try:
    from cpp_ros2_interfaces.msg import BayStatus, BayChannelStatus, BayArea
    from cpp_ros2_interfaces.msg import TaskCompleted
    CUSTOM_MSG_AVAILABLE = True
    print("[DEBUG] 成功导入 BayStatus 和 TaskCompleted 自定义消息")
except ImportError as e:
    print(f"[WARN] 导入自定义消息失败: {e}")
    print("[ERROR] 请确保 cpp_ros2_interfaces 已编译并 source 环境")
    sys.exit(1)

# 键盘监听（优先尝试 pynput，失败则提示）
try:
    from pynput import keyboard as pynput_keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    print("[WARN] pynput 未安装，尝试安装...")
    os.system(f"{sys.executable} -m pip install pynput -q")
    try:
        from pynput import keyboard as pynput_keyboard
        PYNPUT_AVAILABLE = True
    except ImportError:
        print("[ERROR] pynput 安装失败")
        print("[INFO] 尝试使用 keyboard 库（需 sudo）...")
        try:
            import keyboard
            KEYBOARD_AVAILABLE = True
        except ImportError:
            KEYBOARD_AVAILABLE = False
            print("[ERROR] keyboard 库也未安装，请手动安装: pip install keyboard")
            sys.exit(1)

# ════════════════════════════════════════════════════════════
#  仓位配置
# ════════════════════════════════════════════════════════════
BAY_CONFIGS = {
    'A1001': 1, 'A1002': 1, 'A1003': 2, 'A1004': 2,
    'A1005': 3, 'A1006': 3,
    'B1001': 1, 'B1002': 1, 'B1003': 2, 'B1004': 2,
    'B1005': 3, 'B1006': 3,
    'C1001': 4, 'C1002': 4, 'C1003': 5, 'C1004': 5,
    'C1005': 6, 'C1006': 6,
    'D1001': 4, 'D1002': 4, 'D1003': 5, 'D1004': 5,
    'D1005': 6, 'D1006': 6,
}

CHANNEL_LAYOUT = [
    {'channel_id': 0, 'bays': ['A1001','A1002','A1003','A1004']},
    {'channel_id': 1, 'bays': ['A1005','A1006','B1001','B1002']},
    {'channel_id': 2, 'bays': ['B1003','B1004','B1005','B1006']},
    {'channel_id': 3, 'bays': ['C1001','C1002','C1003','C1004']},
    {'channel_id': 4, 'bays': ['C1005','C1006','D1001','D1002']},
    {'channel_id': 5, 'bays': ['D1003','D1004','D1005','D1006']},
]

A_BAYS = ["A1001","A1002","A1003","A1004","A1005","A1006"]
B_BAYS = ["B1001","B1002","B1003","B1004","B1005","B1006"]
C_BAYS = ["C1001","C1002","C1003","C1004","C1005","C1006"]
D_BAYS = ["D1001","D1002","D1003","D1004","D1005","D1006"]


class BayStatusSimulator(Node):
    def __init__(self):
        super().__init__('bay_status_simulator')

        self._bay_states: Dict[str, bool] = {bay: False for bay in BAY_CONFIGS}
        self._publish_count = 0
        self._idx = {'A': 0, 'B': 0, 'C': 0, 'D': 0}

        self._publisher = self.create_publisher(BayStatus, '/dev01_object_status', 10)
        self._task_sub = self.create_subscription(
            TaskCompleted,
            '/task_completed',
            self._on_task_completed,
            10
        )
        self.get_logger().info("已订阅 /task_completed，将自动更新仓位状态")

        self._timer = self.create_timer(1.0, self._publish_bay_status)

        # 选择键盘库
        self._keyboard_lib = None
        if PYNPUT_AVAILABLE:
            try:
                self._listener = pynput_keyboard.Listener(
                    on_press=self._on_key_press,
                    on_release=self._on_key_release
                )
                self._listener.daemon = True
                self._listener.start()
                self._keyboard_lib = 'pynput'
                self.get_logger().info(f"键盘监听器存活: {self._listener.is_alive()}")
            except Exception as e:
                self.get_logger().error(f"pynput 启动失败: {e}")
                self._keyboard_lib = None
        elif KEYBOARD_AVAILABLE:
            try:
                keyboard.on_press(self._on_key_press_kb)
                self._keyboard_lib = 'keyboard'
                self.get_logger().info("使用 keyboard 库")
            except Exception as e:
                self.get_logger().error(f"keyboard 启动失败: {e}")
                self._keyboard_lib = None

        if self._keyboard_lib is None:
            self.get_logger().error("无法启动键盘监听，请安装 pynput 或 keyboard 库")

        self.get_logger().info("BayStatus 模拟器已启动，按 a/b/c/d 手动设置仓位，q 退出")
        print("[INFO] 按 a/b/c/d 设置仓位，按空格显示状态，按 r 重置，按 q 退出")  # 额外提示

    # ---------- 任务完成回调 ----------
    def _on_task_completed(self, msg):
        src = msg.src_bay
        dst = msg.dst_bay
        status = msg.status
        if status != 'completed':
            return
        self.get_logger().info(f"任务完成: {msg.task_id}  src={src}  dst={dst}")
        updated = False
        if src and src in self._bay_states:
            self._bay_states[src] = False
            self.get_logger().info(f"  [自动] {src} → 无货")
            updated = True
        if dst and dst in self._bay_states:
            self._bay_states[dst] = True
            self.get_logger().info(f"  [自动] {dst} → 有货")
            updated = True
        if updated:
            self._publish_bay_status()

    # ---------- 发布 ----------
    def _publish_bay_status(self):
        now = time.time()
        msg = BayStatus()
        msg.header.stamp.sec = int(now)
        msg.header.stamp.nanosec = int((now - int(now)) * 1e9)
        msg.header.frame_id = 'bay_status_frame'
        msg.device_id = 'dev01'
        for ch_info in CHANNEL_LAYOUT:
            ch = BayChannelStatus()
            ch.channel_id = ch_info['channel_id']
            ch.signal_status = True
            for bay_id in ch_info['bays']:
                area = BayArea()
                area.bay_id = bay_id
                area.has_cargo = self._bay_states.get(bay_id, False)
                area.cargo_type = BAY_CONFIGS.get(bay_id, 0)
                area.timestamp = now
                ch.areas.append(area)
            msg.channels.append(ch)
        self._publisher.publish(msg)
        self._publish_count += 1

    # ---------- 键盘处理（pynput） ----------
    def _on_key_press(self, key):
        # 调试：打印按键
        print(f"[DEBUG] key pressed: {key}")
        try:
            if hasattr(key, 'char') and key.char:
                ch = key.char.upper()
                if ch in ('A', 'B', 'C', 'D'):
                    self._process_zone(ch)
                elif ch == ' ':
                    self._show_status()
                elif ch == 'R':
                    self._reset_all()
                elif ch == 'Q':
                    self.get_logger().info("退出模拟器")
                    rclpy.shutdown()
                    sys.exit(0)
        except Exception as e:
            print(f"Error in _on_key_press: {e}")

    def _on_key_release(self, key):
        pass

    # ---------- keyboard 库回调 ----------
    def _on_key_press_kb(self, event):
        # keyboard 的回调参数是 KeyboardEvent
        try:
            if event.event_type == 'down':
                key = event.name
                if len(key) == 1:
                    ch = key.upper()
                    if ch in ('A', 'B', 'C', 'D'):
                        self._process_zone(ch)
                    elif ch == ' ':
                        self._show_status()
                    elif ch == 'R':
                        self._reset_all()
                    elif ch == 'Q':
                        self.get_logger().info("退出模拟器")
                        rclpy.shutdown()
                        sys.exit(0)
        except Exception as e:
            print(f"Error in _on_key_press_kb: {e}")

    # ---------- 核心操作 ----------
    def _process_zone(self, zone):
        zone_map = {'A': A_BAYS, 'B': B_BAYS, 'C': C_BAYS, 'D': D_BAYS}
        bays = zone_map.get(zone, [])
        idx = self._idx.get(zone, 0)
        if idx < len(bays):
            bay = bays[idx]
            self._set_bay(bay)
            self._idx[zone] = idx + 1
            if self._idx[zone] >= len(bays):
                self.get_logger().info(f"{zone}区已满，再次按键将从头循环")
        else:
            self._idx[zone] = 0
            bay = bays[0]
            self._set_bay(bay)
            self._idx[zone] = 1

    def _set_bay(self, bay_id):
        if bay_id not in self._bay_states:
            self.get_logger().error(f"无效仓位: {bay_id}")
            return
        if self._bay_states[bay_id]:
            self.get_logger().info(f"⚠ {bay_id} 已经有货")
            return
        self._bay_states[bay_id] = True
        print(f"✓ {bay_id} 有货 (type={BAY_CONFIGS[bay_id]})")  # 直接打印确保看到
        self.get_logger().info(f"✓ {bay_id} 有货 (type={BAY_CONFIGS[bay_id]})")
        self._publish_bay_status()

    def _show_status(self):
        print("\n当前有货仓位:")
        found = 0
        for bay, state in sorted(self._bay_states.items()):
            if state:
                print(f"  {bay} (type={BAY_CONFIGS[bay]})")
                found += 1
        if found == 0:
            print("  (无)")
        print(f"索引: A={self._idx['A']}, B={self._idx['B']}, C={self._idx['C']}, D={self._idx['D']}")

    def _reset_all(self):
        for bay in self._bay_states:
            self._bay_states[bay] = False
        self._idx = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
        self._publish_bay_status()
        self.get_logger().info("已重置所有仓位为无货")


def main(args=None):
    rclpy.init(args=args)
    node = BayStatusSimulator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()