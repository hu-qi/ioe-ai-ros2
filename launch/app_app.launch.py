#!/usr/bin/env python3
from launch import LaunchDescription
from launch_ros.actions import Node
import os
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_dir = get_package_share_directory('app_mgr_object')
    config_path = os.path.join(pkg_dir, 'config', 'params.yaml')
    return LaunchDescription([
        Node(
            package='app_mgr_object',
            executable='app_mgr_node',
            name='app_mgr_object',
            output='screen',
            parameters=[config_path]
        )
    ])