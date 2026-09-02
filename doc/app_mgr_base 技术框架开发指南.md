# app_mgr_base 技术框架开发指南

## 1. 概述

`app_mgr_base` 是一个基于 ROS2 的插件化应用底座，旨在为机器人自动化、智能仓储等业务场景提供快速构建可扩展应用的基础设施。它通过分层架构、生命周期管理和插件机制，将通用基础设施与具体业务逻辑分离，使开发者能够专注于业务插件的开发，而无需重复实现底层的参数管理、生命周期、日志、通信等模块。

### 主要特性
- **模块化**：基础功能与业务逻辑分离，架构清晰。
- **可扩展**：基于插件的动态加载机制，支持第三方业务插件。
- **标准化**：遵循 ROS2 开发规范，统一生命周期管理、参数配置、日志等。
- **易用性**：提供简洁的入口和配置方式，降低新业务开发门槛。

## 2. 总体架构

```
应用层（业务插件）
    ↓
插件层（内置通用插件）
    ↓
组件层（功能组件）
    ↓
基础框架层（base）
    ↓
ROS2 节点 + 外部依赖
```

- **基础框架层 (base)**：与 ROS2 紧密耦合，提供参数管理、生命周期管理、插件管理、服务/订阅/定时器管理等核心基础设施。
- **组件层 (components)**：独立于业务的通用功能单元，如网络客户端、任务队列、回调服务器、Web 服务器、状态监控、控制执行器等。组件可被插件调用。
- **插件层 (plugins)**：业务功能的载体。每个插件继承自 `BasePlugin`，实现生命周期方法，并可组合使用多个组件。底座内置了多个通用插件（如网络插件、回调处理器插件、请求处理器插件、Web监控插件），业务插件可在此基础上扩展。
- **应用层**：由用户开发的业务插件组成，通过配置文件组装，形成完整应用。

## 3. 核心概念

### 3.1 插件基类 (BasePlugin)
所有插件必须继承 `app_mgr_base.plugins.base_plugin.BasePlugin` 并实现以下生命周期方法（均为可选，默认实现为空）：

- `configure(self, config: Dict[str, Any] = None) -> bool`：配置插件，返回成功状态。
- `activate(self) -> bool`：激活插件，返回成功状态。
- `deactivate(self) -> bool`：停用插件，返回成功状态。
- `cleanup(self) -> bool`：清理资源，返回成功状态。

插件还可以定义 `on_enable()`、`on_disable()` 等回调，以及 `get_status()` 方法返回插件状态。

每个插件应定义类属性：
- `PLUGIN_NAME`：插件唯一标识（小写）。
- `PLUGIN_VERSION`：版本号。

### 3.2 生命周期管理器 (LifecycleManager)
管理所有注册模块（包括基础管理器、插件）的生命周期状态。状态包括：
- `UNCONFIGURED`：未配置
- `INACTIVE`：已配置，未激活
- `ACTIVE`：已激活
- `FINALIZED`：已清理
- `ERROR`：错误

通过 `register_module(name, module, auto_activate)` 注册模块，并通过 `configure()`、`activate()`、`deactivate()`、`cleanup()` 控制状态流转。

### 3.3 参数管理器 (ParamManager)
封装 ROS2 参数系统，提供 `get_param(name, default)` 和 `update_param(name, value)` 方法。支持从 YAML 加载参数，并自动解析 JSON 字符串（用于嵌套字典）。所有插件通过它获取配置。

### 3.4 插件管理器 (PluginManager)
负责发现、加载、卸载插件。通过 `discover(package_path)` 扫描指定包中的插件类（继承自 `BasePlugin` 且非抽象类），然后通过 `load_plugin(name, config)` 实例化插件。插件加载后可通过 `get_plugin(name)` 获取实例。

### 3.5 事件总线 (EventBus)
轻量级的插件间通信机制。插件可以通过 `event_bus.subscribe(event_type, callback)` 订阅事件，通过 `event_bus.publish(event_type, data)` 发布事件。事件总线实例挂载在 ROS2 节点上（`node.event_bus`）。

### 3.6 组件 (components)
组件是独立于业务的可复用模块，位于 `app_mgr_base.components` 下。主要组件包括：

- **network**：HTTP 客户端，支持接口绑定、重试、签名鉴权。
- **task_queue**：优先级任务队列，支持异步任务处理。
- **callback**：基于 FastAPI 的回调服务器，可动态注册路由。
- **web**：Web 监控组件，包含状态监控器、控制执行器、Web 服务器。
- **filter**：状态稳定滤波。
- **channel_monitor**：通用信号监控。

组件通常通过插件初始化，并挂载到节点上供其他插件访问（如 `node.network_plugin`）。

## 4. 内置插件说明

底座默认提供了四个通用插件，它们按以下顺序加载：

1. **network**：网络插件，提供网络接口管理和 HTTP 请求能力。
   - 功能：获取指定网卡 IP、创建绑定会话、发送同步 HTTP 请求。
   - 挂载点：`node.network_plugin`

2. **callback_handler**：回调处理器插件，启动 FastAPI 回调服务器。
   - 功能：注册 HTTP 路由，接收外部回调请求。
   - 挂载点：`node.callback_handler`

3. **request_handler**：请求处理器插件，封装优先级任务队列。
   - 功能：提交任务、注册任务处理器、获取队列状态。
   - 挂载点：`node.request_handler`

4. **web_monitor**：Web 监控插件，整合状态监控、控制执行和 Web 服务器。
   - 功能：提供 Web 运维界面，监控节点和通道状态，执行系统操作。
   - 配置：通过 `web_monitor` 参数指定监控节点、别名、脚本路径等。

这些插件在 `params.yaml` 中通过 `plugin_configs` 和 `web_monitor` 配置。它们展示了如何组合使用组件，是开发业务插件的良好参考。

## 5. 开发新插件

### 5.1 创建插件文件
在 `app_mgr_base/plugins/` 目录下新建一个 Python 文件，例如 `my_business_plugin.py`。内容如下：

```python
#!/usr/bin/env python3
from .base_plugin import BasePlugin
from typing import Dict, Any

class MyBusinessPlugin(BasePlugin):
    PLUGIN_NAME = "my_business"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        # 初始化自己的属性
        self.some_component = None

    def _configure_impl(self) -> bool:
        """从配置中读取参数，初始化所需组件"""
        self.logger.info("配置我的业务插件")
        # 获取配置参数
        param1 = self.config.get('param1', 'default')
        # 访问其他插件（例如网络插件）
        self.network = getattr(self.node, 'network_plugin', None)
        if not self.network:
            self.logger.warning("网络插件不可用，部分功能受限")
        # 初始化自定义组件
        # self.some_component = MyComponent(self.node, self.config)
        return True

    def _activate_impl(self) -> bool:
        """激活插件，启动业务逻辑"""
        self.logger.info("激活我的业务插件")
        # 例如注册回调路由
        if hasattr(self.node, 'callback_handler'):
            self.node.callback_handler.register_get("/my_api", self.handle_my_api)
        return True

    def _deactivate_impl(self) -> bool:
        """停用插件，清理运行中的任务"""
        self.logger.info("停用我的业务插件")
        return True

    def _cleanup_impl(self) -> bool:
        """清理资源"""
        self.some_component = None
        return True

    def handle_my_api(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 HTTP 请求的回调函数"""
        return {"message": "Hello from my plugin", "data": data}

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update({
            "my_status": "ok",
            "param1": self.config.get('param1')
        })
        return status
```

### 5.2 在 `__init__.py` 中导出插件类
编辑 `app_mgr_base/plugins/__init__.py`，添加：

```python
from .my_business_plugin import MyBusinessPlugin

__all__ = [
    # ... 原有插件
    'MyBusinessPlugin',
]
```

### 5.3 配置插件
在 `params.yaml` 中，`plugin_configs` 部分添加插件配置，并在 `plugin_load_order` 中指定加载顺序：

```yaml
plugin_configs:
  # ... 原有插件
  my_business:
    auto_start: true
    param1: "my_value"
    dependencies: ["network"]   # 可选，依赖其他插件

plugin_load_order: ["network", "callback_handler", "request_handler", "web_monitor", "my_business"]
```

如果插件需要更复杂的嵌套配置，可以在 `plugin_configs` 中直接提供字典，或者在顶层单独定义一个参数（如 `my_business_config`），然后在插件中通过 `self.node.param_manager.get_param('my_business_config', {})` 获取。但更推荐将配置放在 `plugin_configs` 的插件条目内，因为插件管理器会将该配置传递给插件构造函数。

### 5.4 使用现有组件
插件可通过 `node` 访问其他插件实例：

```python
network_plugin = self.node.network_plugin
if network_plugin:
    response = network_plugin.request('GET', 'http://example.com/api')
```

也可以直接使用组件（如任务队列）：
```python
request_handler = self.node.request_handler
if request_handler:
    task_id = request_handler.submit_task('my_task', {'data': 123})
```

### 5.5 事件通信
通过事件总线发布/订阅事件：

```python
# 发布事件
self.event_bus.publish('my_event', {'key': 'value'})

# 订阅事件（通常在 _activate_impl 中）
self.event_bus.subscribe('my_event', self.handle_my_event)
```

## 6. 组件使用说明

### 6.1 网络组件 (network)
- 获取接口 IP：`self.network_plugin.get_interface_ip('eth0')`
- 发送 HTTP 请求：`self.network_plugin.request(method, url, data=..., headers=...)` 返回 `requests.Response` 对象。
- 清理会话：`self.network_plugin.clear_sessions()`

### 6.2 任务队列组件 (request_handler)
- 注册任务处理器：`self.request_handler.register_task_processor('my_task', my_handler_function)`
- 提交任务：`self.request_handler.submit_task('my_task', params, priority=TaskPriority.NORMAL)`
- 获取队列状态：`self.request_handler.get_queue_status()`

### 6.3 回调服务器组件 (callback_handler)
- 注册路由：`self.callback_handler.register_get('/my_path', my_callback)` 或 `register_post`
- 回调函数签名：`def my_callback(data: Dict[str, Any]) -> Dict[str, Any]`

### 6.4 Web 监控组件 (web_monitor)
该插件本身提供了 Web 界面，业务插件可以：
- 通过 `status_monitor` 获取系统信息、节点状态、通道状态。
- 通过 `control_executor` 执行系统命令、服务操作。
- 通过 `web_server` 获取服务器状态。

通常业务插件无需直接与 Web 组件交互，而是通过注册自己的 API 路由到 `callback_handler` 或 `web_server`（需要扩展 Web 服务器功能）。目前 `web_server` 未提供动态注册路由的接口，但可以通过 `callback_handler` 实现。

## 7. 配置说明

配置文件 `params.yaml` 遵循 ROS2 参数格式，包含以下主要部分：

### 7.1 全局参数
```yaml
log_level: "info"                # 日志级别 (debug/info/warning/error)
plugin_auto_start: true          # 插件自动激活
```

### 7.2 插件配置 (plugin_configs)
```yaml
plugin_configs:
  network:
    auto_start: true
    ros_network_interface: "eth0"
    api_network_interface: "eth1"
  callback_handler:
    auto_start: true
    port: 8080
    base_path: "/api/callback"
  request_handler:
    auto_start: true
    worker_count: 4
    max_queue_size: 1000
  web_monitor:
    auto_start: true
  my_business:
    auto_start: true
    param1: value
```

### 7.3 加载顺序
```yaml
plugin_load_order: ["network", "callback_handler", "request_handler", "web_monitor", "my_business"]
```

### 7.4 Web监控插件详细配置
```yaml
web_monitor: >-
  {
    "enabled": true,
    "network_interface": "wlan0",
    "port": 9183,
    "host": "0.0.0.0",
    "operation_mode": "development",
    "monitored_nodes": ["/rcs_manager", "/rtsp_infer_dev01", "/video_multi_dev01"],
    "node_aliases": {
      "/rcs_manager": "RCS管理节点",
      ...
    },
    "callback_server": {
      "host": "127.0.0.1",
      "port": 8080,
      "base_path": "/api/callback"
    },
    "dev_scripts": {
      "rcs_manager_script": "/opt/.../start_rcs.sh",
      ...
    },
    "deployment_services": {
      "rtsp_yolo_service": "rtsp-yolo-infer.service",
      "rcs_manager_service": "rcs_manager.service"
    }
  }
```

**注意**：由于 ROS2 参数系统限制，嵌套字典必须表示为 JSON 字符串。使用 `>-` 折叠块可以保持可读性。

## 8. 部署与运行

### 8.1 编译
```bash
cd ~/ros2_ws
colcon build --packages-select app_mgr_base
source install/setup.bash
```

### 8.2 启动
```bash
ros2 launch app_mgr_base app_app.launch.py
```

### 8.3 验证
- 访问 Web 界面：`http://<ip>:9183`
- 测试回调服务器健康检查：`curl http://localhost:8080/api/callback/health`

### 8.4 日志
所有日志统一输出到控制台，可通过 `log_level` 控制级别。如需文件输出，可在 `ros2_logger.py` 中配置 `enable_file_log` 和 `log_dir`。

## 9. 示例：HelloPlugin

下面是一个完整的示例插件，展示如何注册 HTTP 端点和任务处理器。

```python
# plugins/hello_plugin.py
from .base_plugin import BasePlugin
from ..components.task_queue.models import TaskPriority
import time

class HelloPlugin(BasePlugin):
    PLUGIN_NAME = "hello"
    PLUGIN_VERSION = "1.0.0"

    def _configure_impl(self) -> bool:
        self.counter = 0
        return True

    def _activate_impl(self) -> bool:
        # 注册 HTTP 端点
        if hasattr(self.node, 'callback_handler'):
            self.node.callback_handler.register_get("/hello", self.handle_hello)
        # 注册任务处理器
        if hasattr(self.node, 'request_handler'):
            self.node.request_handler.register_task_processor('say_hello', self.process_say_hello)
        return True

    def handle_hello(self, data):
        self.counter += 1
        return {
            'message': 'Hello, World!',
            'counter': self.counter,
            'timestamp': time.time()
        }

    def process_say_hello(self, params):
        name = params.get('name', 'world')
        return True, {'greeting': f'Hello, {name}!'}

    def get_status(self):
        status = super().get_status()
        status['counter'] = self.counter
        return status
```

配置 `params.yaml` 中添加：
```yaml
plugin_configs:
  hello:
    auto_start: true
plugin_load_order: ["network", "callback_handler", "request_handler", "web_monitor", "hello"]
```

编译运行后，可通过 `curl http://localhost:8080/api/callback/hello` 测试。

## 10. 常见问题

### Q: 插件加载失败，提示“插件名称重复”？
A: 确保 `PLUGIN_NAME` 是唯一的，且基类 `BasePlugin` 本身不会被当作插件。插件管理器会自动跳过 `BasePlugin`。

### Q: 如何在插件中获取其他插件实例？
A: 通过 `node` 属性访问，如 `self.node.network_plugin`。插件在 `configure` 阶段将自己挂载到节点上（例如 `self.node.network_plugin = self`），因此其他插件可以访问。

### Q: 配置文件中的 `web_monitor` 是 JSON 字符串，如何书写更清晰？
A: 使用 YAML 的 `>-` 折叠块，内部保持 JSON 格式。这是 ROS2 参数系统的限制，因为 ROS2 不支持嵌套字典作为参数值。

### Q: 如何让插件在部署模式下执行不同的操作？
A: 插件可以通过 `self.config.get('operation_mode')` 获取运行模式，或者通过 `self.control_executor`（如果有）获取模式。在 `web_monitor_plugin` 中已经展示了如何根据模式切换行为。

### Q: 事件总线如何使用？
A: 在节点初始化时创建了 `event_bus`，挂载在 `node.event_bus`。插件可通过 `self.event_bus` 访问。订阅事件需提供回调函数，发布事件时附带任意数据。

### Q: 如何调试插件？
A: 设置 `log_level: "debug"` 可以看到详细的参数加载和插件生命周期日志。也可以在插件代码中添加 `self.logger.debug()` 输出。

## 11. 总结

`app_mgr_base` 提供了一个稳定、可扩展的 ROS2 应用开发底座。
开发者只需专注于业务逻辑，编写插件并配置即可快速构建应用。底座内置的通用插件和组件可大幅减少重复工作，统一的参数管理、生命周期和事件机制保证了系统的健壮性和可维护性。希望本指南能帮助您快速上手，开发出高质量的 ROS2 业务应用。