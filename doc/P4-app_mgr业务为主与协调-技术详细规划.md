# P4 技术详细规划：app_mgr 业务为主 + 视觉/运维协调（需求 3）

- 日期：2026-08-26
- 状态：规划（待审核后实施）
- 父方案：运维统一控制与任务仓位连线技术方案.md §四（需求 3）
- 工程：app_mgr_object-0.2.0(标准版) + device_ops_center-v0.0.1（OPS :1818）

---

## 一、目标（父方案 §四 需求 3）

- app_mgr web **以业务为主**（仓位/任务/AGV/告警/配对连线/标定），其他数据/接口来自 **rtsp 节点或 OPS 基础运维节点**协调；
- 职责边界：业务（app_mgr 自产）｜视觉（OPS 代理 rtsp 节点）｜运维（OPS 单点）｜配对决策（app_mgr）；
- 已完成铺垫：P1 连线（✅）、P2 统一控制经 OPS + 灰度移除（✅）、P3 统一状态 OPS 优先 + 通道口径统一（✅）。

## 二、现状（已实勘）

- **app_mgr 标定页**：calibration.js 调自身 `/api/calibration/*`（channel_count/save/areas/inference_param/set_param）+ `/ws/calibration/{ch}` 每通道 WS（image_manager 自订阅 /debug 帧）——**与 OPS 标定能力重复**（OPS 有同名单接口 + /ws/calibration 单连接多通道 + roi_frames 帧龄权威判定）；
- **OPS 标定接口完整**：channel_count / status / areas/{ch} / save / probe / frame/{ch} / inference_param / set_param + `/ws/calibration`（单连接多通道）+ `/ws/calibration/{ch}`；
- **OPS CORS**：allow_origins=['*']、**allow_methods=['GET']**（仅只读，POST 未开放）；
- P2/P3 已实现：OpsControlProxy（list_nodes/execute/channels_status/ops_status）、/api/ops/* 路由、节点运维/状态 OPS 权威 + 本地降级。

## 三、P4 操作内容与技术方案

### P4-1 标定 REST 接口代理（OPS 为视觉配置权威，前端零改）

- app_mgr web_server 新增 `/api/ops/calibration/*` 代理：OpsControlProxy 增加 `calibration(path, method, body)` 通用转发 → OPS `:1818/api/calibration/*`；
- app_mgr `/api/calibration/save|areas|channel_count|inference_param|set_param|probe|frame` 路由**改转发 OPS**（保留降级：OPS 不可达时回退 image_manager 本地实现）；
- **前端 calibration.js 零改动**（路径不变，后端转发）；
- 效果：ROI 保存/读取/参数设置统一经 OPS 落到 rtsp 节点（OPS roi_calib/param_proxy），消除双写不一致。

### P4-2 OPS CORS 扩展（支持未来直连）

- OPS CORS `allow_methods` 补 `POST, OPTIONS`（当前仅 GET）——为 app_mgr 前端直连 OPS 标定 WS/API 预留（现用后端代理，不依赖）。

### P4-3 标定帧 WS 协调（分步）

- **当前（P4-3a）**：保留 app_mgr image_manager 自订阅 /debug 帧（降级自持，OPS 标定 REST 不可用时标定页仍可画图）；
- **后续（P4-3b，可选增强）**：标定帧改连 OPS `/ws/calibration`（单连接多通道，doc/68 协议）——calibration.js 重接（较大改造，列入后续迭代）；OPS 帧龄权威判定已统一（P3 v3）。

### P4-4 新节点自动展示（验证 + 文档）

- OPS managed_nodes.yaml 新增节点（含 restart 配置）→ app_mgr 节点运维卡/监控页**自动显示**（P2 list_nodes + P3 状态权威源）；验证并写入操作手册。

### P4-5 职责边界清理与文档

- ControlExecutor 保留为兼容层（已停 UI）；重复运维逻辑已清理（P2 灰度移除）；
- image_manager 定位：标定帧降级源（OPS 标定优先）；
- 更新《部署生产环境操作流程.md》：视觉/运维/业务三入口操作说明（app_mgr 业务、OPS 运维+视觉配置、rtsp 节点）。

## 四、职责边界表（最终）

| 类别 | 数据/动作 | 来源 | 落地状态 |
|---|---|---|---|
| 业务 | 仓位绑定/目的仓/AGV/任务队列/活跃实例/工作流/告警/配对覆盖/时段 | app_mgr 自产 | ✅ 保留强化（index/任务/仓位） |
| 配对决策 | src→dst 匹配、AGV 分配、下发 RCS | app_mgr（trigger/workflow/rcs_client） | ✅ 保留 |
| 连线展示 | 任务配对连线 + 浮动面板 | app_mgr 前端（business_update） | ✅ P1 完成 |
| 视觉-标定配置 | ROI 保存/读取、推理参数、channel_count | **OPS 代理 rtsp 节点** | P4-1（本次） |
| 视觉-标定帧 | /debug 帧 | app_mgr image_manager（降级自持）→ 后续直连 OPS /ws/calibration | P4-3a 当前 / P4-3b 后续 |
| 运维-节点控制 | start/stop/restart | **OPS 单点**（watchdog 协调） | ✅ P2 完成 |
| 运维-节点状态 | watchdog 探活 | **OPS 权威 + 本地降级** | ✅ P3 完成 |
| 运维-通道状态 | 帧龄（roi_frames） | **OPS 权威**（/api/rtsp/channels + /api/status 修正） | ✅ P3 v2/v3 完成 |
| 新节点 | 注册即展示 | OPS managed_nodes.yaml → app_mgr 自动 | ✅ P2/P3 + P4-4 验证 |

## 五、文件改动清单（P4）

| 文件 | 改动 |
|---|---|
| app_mgr: components/web/ops_proxy.py | 新增 calibration(path, method, body) 通用转发 |
| app_mgr: components/web/web_server.py | /api/calibration/* 改代理 OPS（save/areas/channel_count/inference_param/set_param/probe/frame，OPS 不可达降级本地） |
| device_ops_center: api_routes.py | CORS allow_methods 补 POST, OPTIONS |
| app_mgr: doc/P4-app_mgr业务为主与协调-技术详细规划.md | 本文件 |
| doc/部署生产环境操作流程.md | 三入口操作说明补充 |

## 六、验证清单

1. app_mgr 标定页：保存 ROI → OPS /api/calibration/save 生效（rtsp 节点配置更新）；读取 areas 一致；
2. 停 OPS：标定 REST 降级本地（页面可用性不中断）；帧 WS 仍工作（image_manager）；
3. OPS CORS：POST 预检通过（OPTIONS 200）；
4. 新节点注册：OPS managed_nodes.yaml 加节点 → app_mgr 节点运维/状态自动出现；
5. 回归：业务（仓位/任务/AGV/告警/连线/面板）、控制页运维（OPS）、监控页状态（OPS 优先+降级）。

## 七、假设

- OPS 标定接口与 app_mgr 前端字段兼容（channel_id/areas 等——实勘同构）；
- 标定帧 WS 保留 app_mgr image_manager（后续直连 OPS 为增强项）；
- CORS POST 开放仅为预留（后端代理为主，不依赖跨域）。


---

## 九、P4 v2：标定页通道数/订阅话题从 OPS 自动获取（消除双配置）

### 9.1 需求
app_mgr 标定页的**通道数、订阅话题**改为从 OPS 获取，不再单独在 app_mgr config yaml 配置——实现标定页与 OPS 话题**自动同步**，避免多端配置重复操作。

### 9.2 现状（已实勘）
- app_mgr image_manager（InferenceImageManager）：`__init__(config)` 从 web_monitor.yaml `calibration` 段读 `image_topic_base/device_id/channel_count/target_node/config_file` → `_setup_subscriptions()` 订阅 `/debug/rtsp_{device_id}_{i}`（0..channel_count-1）——**固定配置，与 OPS 重复**；
- OPS 权威：governor 有 `topic_base/device_id/channel_count`（video.yaml）+ `TARGET_NODE`；`/api/calibration/status` 已返回 `channel_count + topics + frame_age_ms`（**缺 topic_base/device_id/target_node 字段，可补**）；
- 前端 channel_count 已走 OPS 代理（P4-1），但 image_manager **订阅启动时按 yaml 固定**——OPS 改 channel_count 后 app_mgr 不跟随。

### 9.3 方案（标定配置 OPS 权威 + 自动同步）
1. **OPS `/api/calibration/status` 增强**：补 `topic_base`、`device_id`、`target_node` 字段（governor 属性）——一次返回权威标定配置；
2. **app_mgr image_manager 新增 `sync_from_ops(proxy)`**：GET OPS status → 取 channel_count/topic_base/device_id/target_node → 与当前不同 → 更新属性 + **重建订阅**（destroy 全部 + `_setup_subscriptions` 按新值）；`__init__` 保留 yaml 为**初始/降级**；
3. **触发时机**：
   - 启动时：web_monitor_plugin `_activate_impl` 创建 image_manager 后 `sync_from_ops(node.ops_proxy)`（OPS 可用覆盖 yaml）；
   - 标定页打开时：web_server calibration_page 入口 `ensure_ops_sync()`（防抖 30s）——OPS 改 channel_count 重启后打开标定页自动跟随；
   - 前端 channel_count 已走 OPS 代理 → 自动显示 OPS 值；
4. **web_monitor.yaml calibration 段**：保留为降级配置，注释「OPS 优先自动同步，仅 OPS 不可达时使用」。

### 9.4 开发步骤
1. OPS：/api/calibration/status 补 topic_base/device_id/target_node；
2. app_mgr image_manager：sync_from_ops + 订阅重建（destroy+重建）；
3. web_monitor_plugin：_activate_impl 后 sync_from_ops（OPS 可用）；
4. web_server calibration_page：ensure_ops_sync 防抖入口；
5. web_monitor.yaml 注释更新；
6. 验证（见 9.6）。

### 9.5 文件改动清单
| 文件 | 改动 |
|---|---|
| device_ops_center: components/web_portal/api_routes.py | /api/calibration/status 补 topic_base/device_id/target_node |
| app_mgr: components/web/image_manager.py | sync_from_ops + 订阅重建 |
| app_mgr: plugins/web_monitor_plugin.py | 初始化后 sync_from_ops |
| app_mgr: components/web/web_server.py | calibration_page ensure_ops_sync（防抖） |
| app_mgr: config/web_monitor.yaml | calibration 段注释更新（OPS 优先） |

### 9.6 验证清单
1. OPS /api/calibration/status 返回 topic_base/device_id/target_node；
2. app_mgr 启动日志订阅话题来自 OPS（N=OPS channel_count）；
3. **自动同步**：OPS 改 channel_count=8 → 重启 OPS → app_mgr 重启/打开标定页 → 订阅 8 通道（yaml 仍 6，OPS 覆盖）；
4. 停 OPS → 降级 yaml（6 通道）→ OPS 恢复重启后同步；
5. 标定页 channel_count 显示 OPS 值；ROI 保存/参数 OPS 代理正常；
6. 回归：标定绘制/保存/帧显示/业务。

### 9.7 假设
- OPS /api/calibration/status 为标定配置唯一权威（video.yaml + governor 属性）；
- OPS 配置变更需重启 OPS 生效（channel_count 需重启参数）；
- 订阅重建在启动/标定页打开时触发（非实时热更，满足"避免双配置重复操作"目标）。

---

## 十、P4 v2 实施记录（2026-08-26，标定配置 OPS 自动同步）

### 已完成改动
| 文件 | 改动 |
|---|---|
| device_ops_center: components/web_portal/api_routes.py | /api/calibration/status 补 topic_base / device_id / target_node（governor 权威，video.yaml 驱动） |
| app_mgr: components/web/image_manager.py | 新增 sync_from_ops(proxy)（拉 OPS status → channel_count/topic_base/device_id/target_node 差异则更新 + 重建订阅）+ rebuild_subscriptions()（destroy 全部 + 按新配置重建）；yaml 为降级初始值 |
| app_mgr: plugins/web_monitor_plugin.py | _init_components 创建 image_manager 后 sync_from_ops(node.ops_proxy)（OPS 可用覆盖 yaml） |
| app_mgr: components/web/web_server.py | calibration_page 打开时 _ensure_calibration_sync()（防抖 30s） |
| app_mgr: config/web_monitor.yaml | calibration 段注释更新（OPS 权威自动同步，字段仅降级） |

### 验证结果
- py_compile：OPS api_routes / app_mgr image_manager / plugin / web_server 全 OK；
- sync_from_ops + rebuild_subscriptions + plugin 接线 + calibration_page 防抖 + OPS status 增强 全确认。

### 板端回归清单（待执行）
1. app_mgr 启动日志：订阅话题来自 OPS（Subscribed to /debug/rtsp_dev01_0..N-1，N=OPS channel_count）；
2. **自动同步**：OPS 改 video.yaml channel_count（如 8）→ 重启 OPS → app_mgr 重启或打开标定页 → 订阅 8 通道（yaml 仍 3，OPS 覆盖）；
3. 停 OPS → 降级 yaml（3 通道）→ OPS 恢复重启后同步；
4. 标定页 channel_count 显示 OPS 值；ROI 保存/参数 OPS 代理正常；
5. 回归：标定绘制/保存/帧显示/业务。


### 修复记录（2026-08-26，标定页 500）
- **问题**：打开标定页 Internal Server Error（500）；
- **根因**：`_ensure_calibration_sync` 定义为 `__init__` 内**局部函数**（8 空格缩进），但 `calibration_page` 用 `self._ensure_calibration_sync()` 当**实例方法**调用 → AttributeError → 500；
- **修复**：`calibration_page` 改闭包调用 `_ensure_calibration_sync()`（去掉 self，局部函数在 __init__ 作用域可解析）；
- **验证**：py_compile OK；grep 无 `self._ensure_calibration_sync` 残留。


---

## 八、实施记录（2026-08-26，P4 已实施）

### 已完成改动
| 文件 | 改动 |
|---|---|
| app_mgr: components/web/ops_proxy.py | `_call` 支持 `raw=True`（返回二进制 content，JPEG 帧）；新增 `calibration(method, path, body=None, raw=False)` 通用转发 |
| app_mgr: components/web/web_server.py | /api/calibration/channel_count、areas/{id}、save、inference_param/{name}、set_param、frame/{id} **改 OPS 代理优先**（OPS 不可达/失败降级 image_manager 本地实现）——前端 calibration.js 零改动 |
| device_ops_center: components/web_portal/api_routes.py | CORS `allow_methods` 补 `POST, OPTIONS`（预留直连） |

### 验证结果
- py_compile：ops_proxy.py / web_server.py / OPS api_routes.py 全 OK；
- web_server 6 路由代理确认（channel_count/areas/save/inference_param/set_param/frame raw）；
- ops_proxy calibration + raw 确认；image_manager 降级保留。

### 板端回归清单（待执行）
1. app_mgr 标定页：画 ROI 保存 → 经 OPS /api/calibration/save 落到 rtsp 节点（OPS 日志/rtsp 参数更新）；读取 areas 一致；
2. 推理参数读取/设置 → OPS 代理生效；
3. 停 OPS：标定 REST 降级 image_manager（页面可用），帧 WS 仍工作；
4. OPS CORS：POST 预检 OPTIONS 200；
5. 回归：业务/连线/面板/控制页运维/监控页状态。