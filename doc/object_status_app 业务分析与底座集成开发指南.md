# object_status_app 业务分析与底座集成开发指南

## 1. object_status_app 概述

`object_status_app` 是一个基于 ROS2 的独立节点应用，用于监控多个设备（如摄像头）下各区域的物料状态，通过滤波稳定状态，并通过 HTTP 上报给服务器。它实现了以下核心功能：

- **订阅多个设备的话题**：每个设备一个话题，消息格式为自定义的 `AllObject`，包含多个通道和区域的状态。
- **状态滤波**：对每个区域的 `has_object` 信号进行稳定滤波（连续相同值达到阈值后判定为稳定），同时对通道信号也进行滤波。
- **变化触发**：当某个区域的稳定状态发生变化时，立即触发状态打印（测试模式）和立即上报（如果配置为变化上报模式）。
- **定时上报**：根据配置的上报间隔，定时汇总所有区域的稳定状态并上报。
- **上报格式转换**：将内部状态转换为约定的 JSON 格式（HEADER 列表，每个条目包含 `LOCATION_ID`, `LOCATION_STATUS`（"true"=空闲, "false"=占用）, `CREAT_TIME`）。
- **网络发送**：支持测试模式（仅打印不上报）和生产模式，生产模式下支持同步发送和异步队列发送，队列中仅保留最新状态版本，避免重复发送旧状态。
- **网络接口绑定**：通过 `SessionManager` 将 HTTP 请求绑定到指定网卡，并支持主备接口切换。

## 2. 原工程架构分析

### 2.1 目录结构
```
object_status_app/
├── config/params.yaml              # 配置文件
├── launch/status_app.launch.py     # 启动文件
├── object_status_app/
│   ├── client/                      # HTTP客户端相关
│   │   ├── data_manager.py          # 数据格式构建与验证
│   │   ├── http_client.py           # HTTP请求发送
│   │   ├── session_manager.py       # 会话管理（接口绑定）
│   ├── filters/                      # 状态滤波模块
│   │   ├── area_filter.py            # 单区域滤波
│   │   ├── device_manager.py         # 设备/通道/区域状态管理
│   ├── network/                       # 网络上报模块
│   │   ├── network_manager.py         # 网络管理器（协调上报）
│   │   ├── request_queue.py           # 异步请求队列（版本替换）
│   ├── token/                          # 令牌管理（预留，未集成）
│   └── object_status_app.py            # 主节点
```

### 2.2 核心模块职责

| 模块 | 职责 |
|------|------|
| `object_status_app.py` | ROS2 节点，初始化参数、创建订阅、定时器，协调各模块工作。 |
| `filters/area_filter.py` | 单个区域的滤波逻辑，维护一个固定长度的队列，当队列满且值全相同时判定为稳定。 |
| `filters/device_manager.py` | 管理多个设备和通道，每个通道包含多个区域的 `AreaStatusFilter`，并提供信号滤波。 |
| `network/network_manager.py` | 根据测试模式和生产模式选择上报方式，生产模式下通过 `HttpClient` 发送，并支持异步队列。 |
| `network/request_queue.py` | 异步队列，只保留最新状态版本，丢弃旧请求，确保最终一致性。 |
| `client/http_client.py` | 实际发送 HTTP 请求，使用 `SessionManager` 绑定接口，使用 `DataManager` 构建数据。 |
| `client/session_manager.py` | 管理 HTTP 会话，支持主备网络接口绑定和状态检测。 |
| `client/data_manager.py` | 将内部状态转换为上报所需的 JSON 格式，并提供格式验证。 |
| `token/` | 预留的 OAuth2 认证模块，当前未使用。 |

### 2.3 数据流
1. ROS2 话题消息到达 → `status_callback`
2. 提取设备ID、通道ID、区域名、`has_object` 和信号状态
3. 更新 `DeviceStatusManager`：
   - 更新区域状态（滤波）
   - 更新信号状态（滤波）
4. 若区域状态变化，记录变化并触发立即动作：
   - 测试模式下立即打印完整状态
   - 若上报模式为变化上报（模式2或3），立即调用 `_trigger_immediate_report()` 异步上报
5. 定时器（测试模式）定期打印当前所有区域的稳定状态
6. 定时上报（模式1或3）定期调用 `report_current_status()` 汇总并上报

## 3. 在 app_mgr_base 上集成的开发思路

`app_mgr_base` 提供了插件化生命周期管理、参数管理、网络组件、任务队列等基础设施。我们将 `object_status_app` 的功能封装为一个业务插件 `object_status_plugin`，充分利用底座的能力，同时保留原业务逻辑的核心代码。

### 3.1 设计原则
- **复用底座组件**：使用底层的 `ParamManager` 获取配置，使用 `network_plugin` 发送 HTTP 请求，使用 `request_handler_plugin` 作为任务队列（可选）。
- **保持业务逻辑独立**：`filters` 和 `data_manager` 等模块与 ROS2 无关，可直接复用，仅需调整初始化方式（不再依赖 ROS2 节点，而是通过插件传入 logger 等）。
- **生命周期管理**：插件的 `configure` 中初始化所有业务模块，`activate` 中创建订阅和定时器，`deactivate` 中清理资源。
- **事件驱动**：状态变化可通过事件总线广播，供其他插件监听（可选）。

### 3.2 插件结构设计
```
plugins/object_status_plugin.py
├── __init__ (导入插件类)
├── object_status_plugin.py
│   ├── ObjectStatusPlugin (继承 BasePlugin)
│   ├── 使用底座组件：
│   │   ├── self.node.param_manager 获取配置
│   │   ├── self.node.network_plugin (如果使用) 发送 HTTP
│   │   ├── self.node.request_handler (如果使用) 提交异步任务
│   ├── 内部模块（复用原工程代码）：
│   │   ├── device_status_manager (DeviceStatusManager)
│   │   ├── data_manager (DataManager)
│   │   ├── request_queue (可选，若不用底座队列)
│   │   ├── session_manager (如果使用 network_plugin 则不需要)
│   │   ├── http_client (如果使用 network_plugin 则不需要)
│   ├── 定时器（通过底座 TimerManager 创建）
│   ├── 订阅（通过底座 SubscriptionManager 创建）
```

### 3.3 配置整合
原工程的 `params.yaml` 需要合并到底座的 `params.yaml` 中。可以在 `plugin_configs` 下为 `object_status_plugin` 添加配置项，例如：

```yaml
plugin_configs:
  # ... 已有插件
  object_status:
    auto_start: true
    device_list: ["dev01"]
    filter:
      stable_count_threshold: 5
      filter_timeout: 2.0
    status_print_interval: 5.0
    enable_signal_monitoring: true
    network:
      report_mode: 2
      report_interface: "eth1"
      fallback_interface: "eth0"
      server_url: "http://192.168.31.191:8080"
      api_endpoint: "/api/object_status"
      report_interval: 10.0
      timeout: 5.0
      max_retries: 3
      enable_reporting: true
      test_mode: false
      enable_async_queue: true
      queue_max_size: 1000
      retry_delay: 1.0
```

在插件中通过 `self.config` 获取这些值（注意 `plugin_configs` 下的配置会直接传给插件构造函数）。

### 3.4 利用底座网络组件
原工程实现了复杂的网络接口绑定和会话管理，但底座已经提供了 `network_plugin`，支持接口绑定和 HTTP 请求。我们可以选择：
使用方案B
- **方案 B**：保留原工程的 `network_manager` 等模块，但将其改造为不依赖 ROS2，仅通过插件传入的 logger 和配置运行。这样可最大程度复用原有逻辑。

**推荐方案 B**，因为原工程的 `request_queue` 实现了状态版本替换等特殊逻辑，复用更安全。改造要点：
- 移除对 ROS2 节点的依赖，将 `logger` 通过构造函数传入（可使用底座统一的 `self.logger`）。
- `network_manager` 初始化时，不再需要 `self` 节点，而是接收配置参数。
- 如果需要使用底座 `network_plugin` 发送请求，可在 `network_manager` 内部注入 `http_client`，而 `http_client` 可改造为使用 `network_plugin` 的 `request` 方法，但这样会增加耦合。简单做法是保留原 `HttpClient`，它内部依赖 `SessionManager` 和 `DataManager`，这两者与底座无关，可保留。

### 3.5 利用底座任务队列
原工程的 `request_queue` 实现了异步队列，如果希望复用底座 `request_handler_plugin`，需要实现状态版本替换逻辑。

### 3.6 利用底座定时器和订阅管理器
底座提供了 `TimerManager` 和 `SubscriptionManager`，插件可以通过它们创建定时器和订阅，避免直接调用 `self.node.create_timer` 等。这样可以统一管理，并在生命周期停用时自动取消。

## 4. 开发步骤

### 步骤1：创建插件文件
在 `app_mgr_base/plugins/` 下新建 `object_status_plugin.py`，并更新 `__init__.py` 导出插件类。

```python
# plugins/object_status_plugin.py
from .base_plugin import BasePlugin
from ..components.network.http_adapter import HTTPAdapter  # 如果使用底座网络
import threading
import time

class ObjectStatusPlugin(BasePlugin):
    PLUGIN_NAME = "object_status"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: dict = None):
        super().__init__(node, config)
        self.device_manager = None
        self.network_manager = None
        self.data_manager = None
        self.subscriptions = []
        self.timers = []
        self._is_running = False

    def _configure_impl(self) -> bool:
        # 1. 从 self.config 中获取所有参数
        device_list = self.config.get('device_list', ['dev01'])
        filter_config = self.config.get('filter', {})
        stable_threshold = filter_config.get('stable_count_threshold', 5)
        filter_timeout = filter_config.get('filter_timeout', 2.0)
        enable_signal = self.config.get('enable_signal_monitoring', True)
        status_print_interval = self.config.get('status_print_interval', 5.0)
        network_config = self.config.get('network', {})

        # 2. 初始化设备状态管理器
        from ..components.filters.device_manager import DeviceStatusManager  # 注意：需将原 filters 移至 components 或直接引用
        self.device_manager = DeviceStatusManager(
            stable_threshold=stable_threshold,
            timeout=filter_timeout
        )

        # 3. 初始化数据管理器
        from ..components.client.data_manager import DataManager  # 同样需要移动或引用
        self.data_manager = DataManager(logger=self.logger)

        # 4. 初始化网络管理器（保留原逻辑，但改造为不依赖 ROS2）
        from ..components.network.network_manager import NetworkManager
        self.network_manager = NetworkManager(
            report_interface=network_config.get('report_interface', 'eth1'),
            fallback_interface=network_config.get('fallback_interface', 'eth0'),
            server_url=network_config.get('server_url', ''),
            api_endpoint=network_config.get('api_endpoint', '/api/object_status'),
            timeout=network_config.get('timeout', 5.0),
            max_retries=network_config.get('max_retries', 3),
            test_mode=network_config.get('test_mode', False),
            enable_async_queue=network_config.get('enable_async_queue', True),
            queue_max_size=network_config.get('queue_max_size', 1000),
            retry_delay=network_config.get('retry_delay', 1.0),
            logger=self.logger
        )
        self.network_manager.start()  # 启动队列线程等

        # 5. 保存其他配置供激活使用
        self._device_list = device_list
        self._enable_signal = enable_signal
        self._status_print_interval = status_print_interval
        self._report_interval = network_config.get('report_interval', 10.0)
        self._report_mode = network_config.get('report_mode', 1)
        self._enable_reporting = network_config.get('enable_reporting', True)
        self._test_mode = network_config.get('test_mode', False)

        self.logger.info("ObjectStatusPlugin 配置完成")
        return True

    def _activate_impl(self) -> bool:
        self._is_running = True

        # 1. 创建订阅（使用 SubscriptionManager）
        from cpp_ros2_interfaces.msg import AllObject
        qos = self.node.subscription_manager.get_default_qos()  # 假设有这个方法
        for device_id in self._device_list:
            topic = f"/{device_id}_object_status"
            sub = self.node.subscription_manager.create_subscription(
                msg_type=AllObject,
                topic_name=topic,
                callback=lambda msg, dev_id=device_id: self.status_callback(msg, dev_id),
                qos_profile=qos
            )
            self.subscriptions.append(sub)

        # 2. 创建定时器（使用 TimerManager）
        if self._test_mode:
            # 状态打印定时器
            self.node.timer_manager.create_timer(
                "object_status_printer",
                self._print_status_callback,
                self._status_print_interval
            )
            self.timers.append("object_status_printer")

        if self._enable_reporting and self._report_mode in [1, 3]:
            # 定时上报定时器
            self.node.timer_manager.create_timer(
                "object_status_reporter",
                self._timer_report_callback,
                self._report_interval
            )
            self.timers.append("object_status_reporter")

        self.logger.info("ObjectStatusPlugin 已激活")
        return True

    def _deactivate_impl(self) -> bool:
        self._is_running = False
        # 取消定时器（TimerManager 会自动处理？但最好记录）
        for timer_name in self.timers:
            self.node.timer_manager.cancel_timer(timer_name)
        self.timers.clear()
        # 移除订阅（SubscriptionManager 无法直接销毁，但可置空）
        self.subscriptions.clear()
        # 停止网络管理器
        if self.network_manager:
            self.network_manager.shutdown()
        return True

    def _cleanup_impl(self) -> bool:
        self.device_manager = None
        self.network_manager = None
        self.data_manager = None
        return True

    def status_callback(self, msg, device_id):
        # 实现与原节点类似的回调逻辑
        # 使用 self.device_manager 更新状态，检测变化，触发立即上报等
        pass

    def _print_status_callback(self):
        # 定时打印状态
        pass

    def _timer_report_callback(self):
        # 定时上报
        pass

    def _trigger_immediate_report(self):
        # 立即上报（异步）
        pass
```

### 步骤2：迁移原有代码到底座组件目录
为了保持项目结构清晰，将原 `object_status_app` 中的通用模块（如 `filters`、`client`、`network`）迁移到底座的 `components` 目录下，例如：
- `app_mgr_base/components/filters/` 放置 `area_filter.py`, `device_manager.py`
- `app_mgr_base/components/client/` 放置 `data_manager.py`, `http_client.py`, `session_manager.py`
- `app_mgr_base/components/network/` 放置 `network_manager.py`, `request_queue.py`（注意不要与底座原有 `network` 冲突，可改名或放在子目录）

并在相应 `__init__.py` 中导出。

### 步骤3：调整模块依赖
- 所有模块中使用的 `logger` 改为从构造函数传入，不再使用 `get_logger()` 或 `print`。插件中传递 `self.logger`。
- 移除对 ROS2 的依赖（如 `rclpy`），除非必要。
- `network_manager` 中的 `start()` 和 `shutdown()` 方法需要正确处理线程。

### 步骤4：配置参数
在底座的主配置文件 `params.yaml` 中，添加 `plugin_configs.object_status` 部分，并确保 `plugin_load_order` 包含该插件。如果插件依赖其他插件（如 `network`），需声明依赖。

### 步骤5：编译与测试
```bash
colcon build --packages-select app_mgr_base
source install/setup.bash
ros2 launch app_mgr_base app_app.launch.py
```

观察日志，确保插件正常加载、订阅创建成功、状态变化能触发上报。

## 5. 集成要点总结

| 原工程模块 | 底座集成方式 |
|------------|--------------|
| `object_status_app.py` 主节点 | 拆分为插件生命周期方法 |
| `params.yaml` | 合并到底座配置，作为插件配置 |
| `filters/` | 移入 `components/filters`，保持独立 |
| `client/` | 移入 `components/client`，可复用 |
| `network/` | 移入 `components/network`（注意与底座网络组件区分），插件中初始化 |
| 订阅和定时器 | 使用底座 `SubscriptionManager` 和 `TimerManager` |
| 日志 | 使用插件 `self.logger`（底座统一日志） |
| 事件 | 如需与其他插件通信，可使用 `event_bus` |

## 6. 开发注意事项

1. **线程安全**：原工程使用 `threading.RLock` 保护共享数据，插件中应保持。
2. **异步队列的生命周期**：`network_manager.start()` 应在插件 `_activate_impl` 中调用，`shutdown` 在 `_deactivate_impl` 中调用。
3. **依赖管理**：如果插件依赖其他插件（如 `network_plugin`），需在配置中声明 `dependencies` 并在代码中通过 `self.node.network_plugin` 访问。
4. **配置验证**：插件应验证必要配置项是否存在，避免启动失败。
5. **错误处理**：回调中捕获异常，避免影响底座。

## 7. 扩展建议

- **认证集成**：原工程预留了 `token` 模块，可以后续扩展为使用 OAuth2 认证。可在 `network_manager` 中集成 `token_manager`，在发送请求前获取有效令牌。
- **多设备动态管理**：当前设备列表固定，可扩展为支持动态添加/移除设备（通过服务或参数动态更新）。
- **状态变化事件**：可将状态变化通过事件总线发布，供其他业务插件（如告警）监听。

---

通过以上步骤，即可将 `object_status_app` 的业务功能无缝集成到 `app_mgr_base` 底座中，享受底座提供的插件化生命周期、统一参数管理和组件复用等优势，同时保持原业务逻辑的完整性和稳定性。