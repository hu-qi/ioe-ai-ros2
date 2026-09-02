# rcs_mgr_app 技术底座适配参考文档

> **版本**: 1.0.0 | **语言**: Python 3 | **运行时**: ROS2 Humble | **许可**: Apache-2.0  
> 本文档面向基于 `rcs_mgr_app` 核心框架进行二次开发或项目迁移的开发者，说明如何将当前工程作为技术底座复用，并针对不同项目需求做出适配。

---

## 1. 底座定位与设计原则

`rcs_mgr_app` 采用**微内核 + 插件化分层架构**，本文将这一架构提炼为可复用的技术底座。底座聚焦于：

- 提供稳定的基础框架（参数管理、生命周期、插件自动发现、日志、定时器、服务）
- 保留三大核心插件作为**标准基础设施**：`network`（网络）、`parking_monitor`（数据采集与缓存）、`web_monitor`（运维监控）
- 将业务功能（上报、查询、外部接口）全部抽象为**可替换或新增的插件**
- 插件的加载顺序、依赖关系和配置完全由 YAML 参数文件驱动，无需修改框架代码

底座的设计原则：

| 原则 | 说明 |
|------|------|
| **框架不变，插件可换** | `base/` 和 `components/` 层作为通用基础设施，在所有项目中保持一致 |
| **数据源标准化** | `parking_monitor` 统一对接 ROS2 话题，产出结构化缓存，供所有下游插件消费 |
| **运维界面统一** | `web_monitor` 提供节点管理、通道/信号健康度、视频查看等通用运维能力 |
| **业务适配即插件** | 新项目的特殊需求（如向上位机上报、不同协议接口）只需增加新插件并更新配置 |

---

## 2. 保留核心插件详解

底座默认激活以下三个基础插件，无需修改即可在不同项目中复用。

### 2.1 parking_monitor（数据采集与缓存）

**职责**：订阅推理节点发布的 ROS2 话题，进行状态滤波、缓存聚合，为其他插件提供统一的数据访问层。

**关键输出**：

- `node.parking_state_manager` – 按单个仓位管理的原始状态（保持兼容旧逻辑）
- `node.lane_cache_manager` – 按巷道/货架聚合的状态缓存（**推荐其他插件优先使用**）
- `node.channel_monitor` – 通道信号健康度监控（超时、异常计数、自动恢复）

**适配新项目时的关注点**：

1. **话题名称与消息类型**  
   当前订阅话题为 `parking{device_id}_status`，消息类型为自定义 `AllChannelStatus`。  
   新项目若使用不同的话题名称或消息结构，只需在插件 `_activate_impl()` 中修改订阅逻辑（创建订阅时的 topic 和 msg type），并在回调 `_parking_status_callback` 中调整解析代码，确保最终能提取到：
   - `device_id`（设备标识）
   - `channel_id`（通道号，0/1 语义需与业务对齐）
   - `park_name`（仓位唯一标识，如 `CJWAK200-Z20-01`）
   - `has_cargo`（是否有货物，布尔值）
   - `signal_status`（通道信号是否正常，布尔值，可选）

2. **滤波器参数**  
   通过 `params.yaml` 中的 `state_change_stable_time` 控制状态判定稳定时间，按需调整。

3. **缓存数据结构**  
   `lane_cache_manager` 会根据 `park_name` 解析出 `lane_prefix` 和 `shelf_code`，然后按巷道聚合。新项目的仓位命名规则若不同，需修改 `lane_cache_manager` 中的解析逻辑（例如 `parse_park_name` 方法），以适配新的巷道/货架编号格式。

4. **数据源语义**  
   默认业务语义：“通道0为出货（检测无货→空仓），通道1为进货（检测有货→满仓）”。  
   若新项目语义不同，需在 `ParkingStateManager` 和 `lane_cache_manager` 中调整 `_should_update_status` 或通道到最终状态的映射逻辑。

### 2.2 network（设备网络管理）

**职责**：管理多网卡环境下的 IP 获取、会话绑定、网络配置统一下发。

**关键输出**：

- `node.network_manager` – 网络接口管理器
- `network_plugin.get_api_ip()` / `get_ros_ip()` – 提供 API 服务 IP 和 ROS 通信 IP

**适配新项目时的关注点**：

- 通过 `params.yaml` 配置 `ros_network_interface` 和 `api_network_interface` 即完成网络切换。
- 若仅单网卡，将两个接口设为相同名称即可。
- 其他插件通过网络插件获取 IP 而非硬编码，因此更换网络环境只需修改 YAML。

### 2.3 web_monitor（运维监控界面）

**职责**：提供基于 FastAPI + WebSocket + Jinja2 的 Web 运维界面，包含节点状态、通道信号健康度、系统资源监控、告警（可选）、控制命令执行，以及**视频查看功能**。

**关键特性**：

- 端点：`http://{api_ip}:9183`
- WebSocket 实时推送状态
- 节点别名、通道别名均可通过 `params.yaml` 的 `web_monitor` 字段配置，无需修改代码
- **视频查看**：利用推理节点发布的可视化话题（如 `/debug/rtsp_*`）或 RTSP 流地址，在运维界面集成视频预览（此项需配合推理节点的实际发布话题实现）

**适配新项目时的关注点**：

1. **节点别名与通道别名**  
   在 `params.yaml` 的 `web_monitor.node_aliases` 和 `web_monitor.channel_aliases` 中定义监控页面上显示的友好名称，与具体项目使用的 ROS2 节点名、设备通道 ID 对应。

2. **控制脚本/服务**  
   开发环境下通过脚本启停节点（`dev_scripts`），部署环境下通过 systemd 服务（`deployment_services`）。新项目需按要求填写对应的脚本路径或服务名称。

3. **视频查看**  
   - 若推理节点发布带渲染结果的话题（如图像话题 `sensor_msgs/Image`），可在 Web 页面通过 WebSocket 桥接或 MJPEG 流方式展示。
   - 底座预留了 `inference_image_manager`，可在插件配置中启用 `calibration` 并指定 `image_topic_base`，配合推理节点的图像话题实现监控。
   - 若需要查看原始 RTSP 流，可在界面上直接嵌入 RTSP URL（需在配置中提供 `rtsp_urls` 映射）。

4. **告警模块**  
   当前告警管理器默认不启用，如需使用，可在配置中开启并定义告警规则。

---

## 3. 基础框架层（不可变部分）

底座的基础框架层（`base/`）和通用组件层（`components/`）被视为**稳定基础**，跨项目迁移时**不应修改内部逻辑**，以保证框架的一致性。这些模块的职责和接口已在原《架构参考文档》第 2.1–2.2 节详细说明，此处不再重复。

如果新项目不使用 ROS2，则可参照原文档第 7.2 节进行 ROS2 解耦。

---

## 4. 插件体系与扩展指南

底座鼓励通过开发新插件来满足业务需求。所有插件均存放在 `plugins/` 目录下，遵循统一的生命周期接口。

### 4.1 插件开发模板

```python
# plugins/my_reporter/my_reporter_plugin.py
from ..base_plugin import BasePlugin

class MyReporterPlugin(BasePlugin):
    PLUGIN_NAME = "my_reporter"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config=None):
        super().__init__(node, config)
        # 初始化插件私有组件

    def _configure_impl(self) -> bool:
        # 从 param_manager 读取配置，初始化管理器
        # 可通过 self.node.lane_cache_manager 获取数据缓存
        return True

    def _activate_impl(self) -> bool:
        # 创建定时器、订阅或服务
        self._timer = self.node.create_timer(5.0, self._on_tick)
        return True

    def _on_tick(self):
        # 从 lane_cache_manager 获取数据并执行业务逻辑
        lanes = self.node.lane_cache_manager.get_all_lanes_status()
        # 自定义上报逻辑...
```

### 4.2 数据获取方式

所有下游插件统一通过以下途径获取实时状态（不再自行订阅原始话题）：

- **巷道聚合状态**（推荐）  
  `lanes_status = self.node.lane_cache_manager.get_all_lanes_status()`  
  返回每个巷道的 `FULL/EMPTY/PARTIAL` 状态、稳定性、各货架详细状态等。

- **原始仓位状态**  
  `slots = self.node.parking_state_manager.get_all_slots()`  
  用于需要单个仓位粒度的场景。

- **通道健康度**  
  `channel_stats = self.node.channel_monitor.get_all_channels_status()`  
  提供每个通道的信号是否正常、连续异常计数等。

### 4.3 插件加载配置

新开发的插件无需修改任何代码，只需在 `params.yaml` 中调整：

```yaml
plugin_load_order: ["network", "callback_handler", "parking_monitor", "my_reporter", "web_monitor"]
```

同时可以在 `main.py` 的 `_get_plugin_configs()` 中按需为新插件增加配置项（如依赖、定时周期等），或直接在插件内部从 `param_manager` 读取专用配置。

---

## 5. 配置文件适配指南

项目的全部差异化配置集中在 `config/params.yaml` 中。以下列出与底座适配直接相关的关键参数及其修改说明：

| 参数 | 说明 | 适配建议 |
|------|------|----------|
| `ros_network_interface` / `api_network_interface` | 网络接口名称 | 按实际设备修改 |
| `device_ids` | 设备 ID 列表 | 必须与实际推理节点发布的 topic 中的 device 部分一致 |
| `callback_port` | REST API 端口 | 按需修改 |
| `web_monitor` (YAML 块) | Web 运维界面全套配置 | 必须根据新的节点名、脚本路径、通道别名进行填充，详见下节 |
| `wms_lane_config` (JSON) | 巷道定义（前缀、仓位数、稳定延迟） | 必须与 `park_name` 解析规则匹配，否则缓存聚合失败 |
| `plugin_load_order` | 插件加载顺序 | 加入自定义插件，注意依赖关系 |
| `state_change_stable_time` | 状态判稳时长 | 按信号抖动程度调整 |

**示例：web_monitor 配置块**  
```yaml
web_monitor: |
  enabled: true
  network_interface: "wlan0"
  host: "0.0.0.0"
  port: 9183
  operation_mode: "deployment"
  node_aliases:
    "/rcs_manager": "管理节点"
    "/my_inference_node": "推理节点"
  channel_aliases:
    "device_01_channel_0": "出货通道"
    "device_01_channel_1": "进货通道"
  dev_scripts:
    rcs_manager_script: "/opt/project/start_rcs.sh"
    infer_script: "/opt/project/start_infer.sh"
  deployment_services:
    rcs_manager_service: "rcs_manager.service"
    infer_service: "my_infer.service"
  calibration:
    enabled: true
    image_topic_base: "/debug/rtsp_"
    device_id: "dev01"
    channel_count: 2
    target_node: "/my_inference_node"
    config_file: "/opt/project/infer_config.yaml"
```

> **注意**：`web_monitor` 的所有节点名称、通道别名、脚本路径均由此配置块驱动，底座代码中已移除所有硬编码默认值，因此迁移时必须完整提供。

---

## 6. 上报/业务插件适配模式

原有工程中的 `wms_lane_report`、`status_reporter` 等插件属于特定项目的业务逻辑。在新项目中，可参照同样模式实现自己的上报插件，常见模式有三种：

### 6.1 定时全量上报（如 status_reporter）

- 插件内部创建定时器，定期遍历 `lane_cache_manager.get_all_lanes_status()` 或 `parking_state_manager.get_all_slots()`，组装 JSON 后通过 HTTP/RPC 上报。
- 可通过 `params.yaml` 配置上报间隔和 URL。

### 6.2 状态触发上报（如 wms_lane_report）

- 使用 `lane_cache_manager` 提供的稳定性信息和状态变化检测，实现“满仓稳定后上报一次”、“空仓重置许可”等复杂逻辑。
- 底座中的 `WMSLaneReportManager` 提供了防重复上报、冷却期、空到满许可等可复用逻辑，可继承或参考其代码实现类似管理器。

### 6.3 外部查询接口

- 可通过 `callback_handler` 插件中的 FastAPI 服务器添加 REST 端点，同样从缓存获取数据返回。
- 也可新增 ROS2 服务（如 `query_service` 插件）供其他 ROS2 节点调用。

---

## 7. 部署与运维

底座在部署上的要求与原工程一致：

- **依赖**：ROS2 Humble、Python 3.10+、FastAPI、netifaces 等。
- **启动**：`ros2 launch rcs_mgr_app rcs_app.launch.py`
- **配置检查**：启动日志会打印网络接口 IP、插件加载状态、缓存初始状态等信息，可据此判断适配是否正确。

**健康检查端点**（不变）：  
- `GET http://{api_ip}:8080/eyeSky/robot/reporter/health`  
- `GET http://{api_ip}:9183/health`  
- WebSocket 状态推送 `ws://{api_ip}:9183/ws`

---

## 8. 迁移检查清单

将底座应用于新项目时，按以下步骤操作：

1. **[ ] 修改 `params.yaml`**  
   - 设置网络接口  
   - 配置 `device_ids`  
   - 填写 `web_monitor` 完整配置（节点别名、脚本、通道别名等）  
   - 调整 `wms_lane_config` 以匹配仓位命名规则

2. **[ ] 适配 `parking_monitor` 话题**  
   - 检查推理节点发布的话题名和消息类型  
   - 修改 `_activate_impl` 中的订阅代码和回调解析逻辑  
   - 如有需要，调整 `lane_cache_manager` 的仓位名解析方法

3. **[ ] 确认缓存数据正确**  
   - 启动后观察日志输出的巷道状态，确保状态聚合符合业务语义

4. **[ ] 开发/移植业务插件**  
   - 按需新增插件，从 `lane_cache_manager` 获取数据  
   - 更新 `plugin_load_order` 和 `main.py` 中的插件配置字典（可选）

5. **[ ] 测试 Web 运维界面**  
   - 访问 `http://{api_ip}:9183`，确认节点状态、通道信号显示正确  
   - 测试控制脚本（启停节点）和视频查看功能

6. **[ ] 配置健康检查和日志**  
   - 保持原有日志级别配置  
   - 可选择性启用文件日志

---

以上即为 `rcs_mgr_app` 技术底座的完整适配参考文档。遵循此指南，即可在不同仓储物流视觉项目中快速复用本系统的插件化架构、数据缓存机制和运维监控能力，只需关注业务插件和配置文件即可完成迁移。