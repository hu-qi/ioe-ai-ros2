# app_mgr_object - 通用ROS2应用底座框架

## 简介
`app_mgr_object` 是一个基于ROS2的插件化应用底座，提供生命周期管理、参数管理、插件发现、组件复用等功能，旨在帮助开发者快速构建可扩展的ROS2应用。

## 特性
- **模块化**：基础功能与业务逻辑分离，分层清晰。
- **可扩展**：通过插件机制动态加载业务模块，支持第三方插件。
- **标准化**：遵循ROS2开发规范，统一生命周期、参数、日志。
- **易用性**：简洁的main入口和配置方式，降低新业务开发门槛。

## 架构
- **基础框架层（base）**：与ROS2紧密耦合，管理节点生命周期和基础资源。
- **组件层（components）**：独立可复用的功能单元（网络、任务队列、回调、滤波、信号监控等）。
- **插件层（plugins）**：业务功能的载体，继承`BasePlugin`，可组合使用组件。
- **应用层**：由用户开发的业务插件组成，通过配置文件组装。

## 快速开始

### 安装依赖
```bash
sudo apt install python3-pip
pip3 install requests aiohttp netifaces psutil fastapi uvicorn pyyaml
#安装依赖
pip install -r install requirements.txt

#编译
colcon build --packages-select app_mgr_object
#启动
source install/setup.bash
ros2 launch app_mgr_object app_app.launch.py