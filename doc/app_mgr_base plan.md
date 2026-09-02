## app_mar_base框架构建需求说明

### 1. 背景与目标
当前工程 `rcs_mgr_app` 是一个基于 ROS2 的插件化应用，实现了巷道状态监控、WMS 上报等功能。随着业务发展，需要将其中通用基础设施抽取为独立底座，以便快速构建新业务应用。目标底座应具备以下特征：
- **模块化**：将基础功能与业务逻辑分离，提供清晰的分层架构。
- **可扩展**：通过插件机制动态加载业务模块，支持第三方插件开发。
- **标准化**：遵循 ROS2 开发规范，统一生命周期管理、参数配置、日志等。
- **易用性**：提供简洁的 main 入口和配置方式，降低新业务开发门槛。

### 2. 功能需求
#### 2.1 基础模块（base）
- **参数管理器**：支持从 YAML/ROS 参数加载配置，提供动态更新回调。
- **生命周期管理器**：管理各模块（如插件、组件）的状态（未配置、非活跃、活跃、错误），支持顺序配置、激活、停用、清理。
- **插件管理器**：自动发现包内或指定路径的插件类，支持按依赖顺序加载、配置、激活插件，提供插件实例获取接口。
- **服务管理器**：统一创建 ROS 服务，支持 Trigger 等标准服务类型，记录服务状态。
- **话题管理器**：统一创建发布者/订阅者，管理 QoS 配置，支持按设备批量创建。
- **定时器管理器**：统一创建周期/单次定时器，支持统计执行时间、自动监控。
- **日志管理器**：封装 ROS2 日志和 Python logging，支持统一级别设置、文件输出、性能计时。

#### 2.2 组件模块（components）
组件为可独立复用的功能单元，不依赖具体业务，供插件调用。
- **网络组件**：提供 HTTP 客户端，支持绑定指定网卡、签名鉴权、重试机制、连接池管理。
- **任务队列组件**：提供优先级任务队列、工作线程池、任务状态跟踪，支持异步执行和回调。
- **Web 运维组件**：提供基于 FastAPI 的 Web 服务器，支持静态文件、模板、WebSocket 广播，集成系统状态监控、控制执行、告警管理。
- **回调服务器组件**：提供轻量级 HTTP 回调接口（如 Flask/FastAPI），用于接收外部系统状态查询和上报。
- **滤波组件**：对输入数据进行稳定滤波（如连续计数、时间窗口），减少误报。
- **通道监控组件**（可抽象为通用状态监控）：监控外部信号（如硬件通道），记录信号状态、超时、异常计数，提供状态查询。

#### 2.3 插件模块（plugins）
插件是业务功能的载体，继承自 `BasePlugin`，实现生命周期方法，可组合使用多个组件。底座内置一组通用插件：
- **网络插件**：封装网络组件，提供网卡 IP 获取、会话管理，供其他插件使用。
- **回调处理器插件**：启动回调服务器组件，注册状态查询接口，将 HTTP 请求转化为内部事件或任务。
- **请求处理器插件**：封装任务队列组件，对外提供任务提交接口，供其他插件使用。
- **Web 监控插件**：启动 Web 服务器组件，集成状态监控和控制执行，提供运维界面。
- （可选）**状态上报插件**：周期或触发式上报系统状态到外部系统。

#### 2.4 标准化入口（main）
- 创建 ROS2 节点，初始化基础模块（参数管理器、生命周期管理器、插件管理器等）。
- 从参数服务器或配置文件加载插件配置。
- 发现并加载插件，按依赖顺序执行配置、激活。
- 启动多线程执行器，处理 ROS 事件。
- 提供优雅关闭（信号处理）和资源清理。

### 3. 非功能性需求
- **可扩展性**：新增业务只需开发新插件，无需修改底座代码。
- **可配置性**：所有行为通过参数控制，支持运行时动态调整。
- **稳定性**：组件内部异常不传播，插件失败不影响底座运行。
- **日志可追溯**：统一日志格式，包含时间戳、模块名、级别，支持文件输出。
- **文档清晰**：提供模块接口说明、插件开发指南、配置示例。

---

## 构建底座的架构开发思路和步骤

### 1. 总体架构设计
采用分层架构，依赖关系自顶向下：
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

- **基础框架层**：与 ROS2 紧密耦合，管理节点生命周期和基础资源。
- **组件层**：独立于 ROS2，但可能依赖节点提供的 logger 或事件总线。
- **插件层**：依赖组件和基础框架，实现具体业务逻辑，通过事件总线通信。
- **应用层**：由用户开发的业务插件组成，通过配置文件组装。

### 2. 模块划分与接口设计

#### 2.1 基础框架（base）
- **ParamManager**：`get_param(name, default)`，`set_param(name, value)`，`register_callback(name, func)`。
- **LifecycleManager**：`register_module(name, module, auto_activate)`，`configure(name)`，`activate(name)`，`deactivate(name)`，`cleanup(name)`，`get_state(name)`。
- **PluginManager**：`discover(package)`，`load(plugin_name, config)`，`get_plugin(name)`，`get_all_plugins()`。
- **ServiceManager**：`create_service(service_type, service_name, callback, qos)`，`get_service(name)`。
- **SubscriptionManager**：`create_subscription(msg_type, topic, callback, qos)`，`get_subscription(name)`。
- **TimerManager**：`create_timer(name, period, callback, oneshot)`，`start(name)`，`cancel(name)`。
- **ROS2Logger**：提供 `debug/info/warning/error` 方法，支持 `PerformanceTimer` 上下文管理器。

#### 2.2 组件（components）
每个组件应设计为类，构造函数接受 `node` 或 `logger`，并提供公共方法。
- **NetworkComponent**：`get_interface_ip(interface)`，`request(method, url, data, ...)`，`close_all()`。
- **TaskQueueComponent**：`submit_task(task_type, params, priority, callback)`，`get_status()`，`stop()`。
- **WebComponent**：`start()`，`stop()`，`get_server_info()`，需要传入状态获取回调和控制执行回调。
- **CallbackComponent**：`start(port, base_path)`，`register_status_callback(func)`，`register_control_callback(func)`。
- **FilterComponent**：`filter(device_id, channel, key, value, timestamp)`，返回稳定状态。
- **ChannelMonitorComponent**：`update(device_id, channel_id, signal, timestamp)`，`is_normal(device, channel)`，`get_status()`。

#### 2.3 插件（plugins）
- **BasePlugin** 定义接口：`configure(config)`，`activate()`，`deactivate()`，`cleanup()`，`get_status()`。提供默认空实现。
- 插件通过依赖注入获得组件实例（例如在 configure 时从 node 获取）。

### 3. 开发步骤

#### 步骤1：提取基础框架
- 从现有工程复制 `base` 目录，整理优化：
  - 统一命名，移除业务相关代码。
  - 增强异常处理，保证各管理器独立。
  - 为每个管理器添加 `get_status` 方法，便于监控。
- 将 `ros2_logger.py` 完善，支持文件日志和性能计时。

#### 步骤2：抽取通用组件
- 识别 `components` 中可复用的部分：
  - `network`：完全通用，保留并优化异常处理。
  - `filters`：通用，可独立。
  - `request_handler`：通用任务队列，抽取为 `task_queue`。
  - `web`：Web 监控组件，需剥离业务依赖（如巷道监控），改为通过回调函数获取数据。
  - `callback`：回调服务器组件，类似 Web，通过回调函数处理请求。
  - `channel`：通道监控，虽然当前用于硬件通道，但可抽象为“信号监控”，保留。
- 每个组件独立成子包，提供清晰的 __init__.py 导出主要类。

#### 步骤3：重构插件层
- 将 `core` 中的 `base_plugin.py` 和 `event_bus.py` 放入底座 `core`。
- 将通用插件（如 `network_plugin.py`, `callback_handler_plugin.py`, `request_handler_plugin.py`, `web_monitor_plugin.py`）移至 `plugins` 目录，并重构它们使用组件而不是直接实现所有逻辑。
- 移除业务插件（如 `parking_monitor_plugin`, `wms_lane_report_plugin`），它们将放入独立业务包。

#### 步骤4：编写标准入口
- 创建 `main.py`，流程如下：
  1. 初始化 ROS2 节点。
  2. 实例化基础管理器：`param_manager`, `lifecycle_manager`, `plugin_manager`, `service_manager`, `subscription_manager`, `timer_manager`。
  3. 从参数获取插件配置（如 `plugin_configs` 字典）。
  4. 调用 `plugin_manager.discover('rcs_mgr_base.plugins')` 发现内置插件。
  5. 按依赖顺序加载插件（可从配置中读取 `load_order`）。
  6. 调用 `lifecycle_manager.configure()` 配置所有注册模块（包括插件）。
  7. 调用 `lifecycle_manager.activate()` 激活所有标记为 `auto_activate` 的模块。
  8. 启动多线程执行器，等待退出信号。
  9. 捕获信号，调用 `lifecycle_manager.shutdown()` 清理。

#### 步骤5：配置与 launch 文件
- 提供默认 `params.yaml`，包含基础参数（日志级别、网络接口等）和插件配置。
- 编写 launch 文件，加载参数并启动节点。

#### 步骤6：文档与示例
- 编写 README，说明底座架构、模块功能、配置方法。
- 提供插件开发示例（如一个简单的“HelloPlugin”），展示如何继承 `BasePlugin`、使用组件。
- 提供 API 文档（可使用 Sphinx 或 mkdocs）。

### 4. 关键设计要点
- **依赖注入**：组件和插件不应直接创建对方，而是通过节点属性（如 `node.network_component`）或事件总线获取。在 `configure` 阶段，插件可以从节点获取组件实例。
- **事件总线**：用于插件间通信，避免直接耦合。事件类型可定义常量。
- **配置分层**：全局参数通过 `param_manager` 管理，插件配置通过 `plugin_manager` 在加载时传入。
- **错误隔离**：插件生命周期方法应捕获所有异常，避免影响底座。管理器记录错误并更新状态。
- **线程安全**：所有管理器内部操作加锁，插件回调可能运行在 ROS 线程或自定义线程中，需注意。

### 5. 测试策略
- 单元测试：测试各管理器独立功能，使用 mock ROS2 节点。
- 集成测试：启动底座，加载测试插件，验证生命周期和组件交互。
- 性能测试：验证任务队列、Web 服务器在高负载下的表现。

---

通过以上步骤，我们将得到一个稳定、可扩展的 ROS2 应用底座，后续新业务只需开发插件并配置即可快速部署，大幅提升开发效率和系统可靠性。



