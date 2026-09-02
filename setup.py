#!/usr/bin/env python3
"""
setup.py - 修复包安装问题
"""

from setuptools import find_namespace_packages, setup
import os
from glob import glob
from pathlib import Path

package_name = 'app_mgr_object'

# 静默创建MANIFEST.in
manifest_file = Path('MANIFEST.in')
if not manifest_file.exists():
    manifest_content = """# 包含模板文件
recursive-include app_mgr_object/components/web/templates *.html
# 包含静态文件
recursive-include app_mgr_object/components/web/static *
# ROS配置文件
include config/*.yaml
include launch/*.py
include resource/*
include package.xml
"""
    manifest_file.write_text(manifest_content)
    
#使用find_packages查找当前目录下的包
# 排除非Python包的目录
packages = find_namespace_packages(include=['app_mgr_object', 'app_mgr_object.*'])

setup(
    name=package_name,
    version='0.0.0',
    
    # 使用find_packages自动发现包
    # 注意：这里不使用package_dir参数，因为包就在当前目录
    packages=packages,
    
    # 包含包数据
    include_package_data=True,
    package_data={
        package_name: [
            # 模板文件
            'components/web/templates/*.html',
            # 静态文件
            'components/web/static/*',
            'components/web/static/**/*',  # 递归包含
        ],
    },
    
    # ============================================================
    # data_files: 将非 Python 文件安装到 share/ 目录
    # ==========================================================
    data_files=[
        # 1. ament 索引
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),

        # 2. 包根目录（package.xml）
        ('share/' + package_name, ['package.xml']),

        # ===== config/ 根目录 =====
        # 包含 params.yaml 和 db_schema.sql
        (os.path.join('share', package_name, 'config'), [
            'config/params.yaml',
            'config/db_schema.sql',
            'config/web_monitor.yaml',
        ]),

        # ===== config/workflows/ 子目录 =====
        # 包含所有 YAML 工作流定义
        (os.path.join('share', package_name, 'config', 'workflows'),
            glob('config/workflows/*.yaml')),
        
        # ===== config/plugin_configs/ 子目录 =====
        (os.path.join('share', package_name, 'config', 'plugin_configs'), [
            'config/plugin_configs/network.yaml',
            'config/plugin_configs/callback_handler.yaml',
            'config/plugin_configs/rcs_adapter.yaml',
            'config/plugin_configs/bay_status_fusion.yaml',
            'config/plugin_configs/status_poller.yaml',
            'config/plugin_configs/task_status_monitor.yaml',
            'config/plugin_configs/workflow_engine.yaml',
            'config/plugin_configs/smart_trigger.yaml',
        ]),
        
        # ===== launch/ 目录 =====
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
    ],
    
    install_requires=['setuptools'],
    zip_safe=False,  # ROS2 要求为 False
    
    maintainer='root',
    maintainer_email='root@example.com',
    description='通用ROS2应用底座框架',
    license='Apache-2.0',  # 使用SPDX许可证表达式
    
    entry_points={
        'console_scripts': [
            'app_mgr_node = app_mgr_object.main:main',
        ],
    },
)