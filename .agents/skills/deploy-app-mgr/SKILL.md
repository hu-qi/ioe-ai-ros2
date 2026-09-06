---
name: deploy-app-mgr
description: 把 app_mgr_object ROS2 应用底座部署到一台全新的 Ubuntu 主机上（从环境探查、源码上传、配置适配、编译、systemd 服务到 8 项验证清单的完整流程）。触发：用户说"部署到 XXX"、"迁移到新机器"、"在 XXX 上跑起来"、"从零部署"，或要求把部署流程沉淀为 skill。
---

# 把 app_mgr_object 部署到新主机

把 `app_mgr_object`（ROS2 插件化应用底座）部署到一台全新 Ubuntu 主机。
目标产物：`systemctl is-active app_mgr` → `active`，Web 监控 `HTTP 200`，9 个插件全部加载。

## 0. 何时使用

用户说"部署到 `<IP>`"、"迁移到新机器"、"在 `<IP>` 上跑起来"、"从零部署"，
或要求把部署流程沉淀为 skill。

## 1. 环境探查（先摸清目标主机）

SSH 连上目标主机后，**一次性**执行以下探查命令并记录结果：

```bash
uname -a                              # 内核 + 架构 (x86_64 / aarch64)
lsb_release -a 2>/dev/null || cat /etc/os-release   # 系统版本
python3 --version; which python3       # Python 版本 (3.10 / 3.12)
nproc; free -h | head -2; df -h /      # CPU / 内存 / 磁盘
ip -br addr                            # 网卡名 (eth0 / enp2s0 / wlan0 ...)
ls /opt/ros/*/setup.bash 2>/dev/null   # 已装的 ROS2 发行版
which colcon ros2 2>&1                 # colcon / ros2 是否就绪
ls /root/ros2_ws 2>/dev/null && echo WS_EXISTS || echo WS_NOT_EXISTS
systemctl is-active app_mgr 2>&1       # 是否已有旧服务
ss -tlnp 2>/dev/null | grep -E '8080|9183' || echo PORTS_FREE
```

### 1.1 决策矩阵（根据探查结果选路径）

| 目标主机情况 | ROS2 路径 | 说明 |
|---|---|---|
| Ubuntu 22.04 (jammy) + Python 3.10 | Humble (`/opt/ros/humble`) | 官方支持，最稳 |
| Ubuntu 24.04 (noble) + Python 3.12 | **Jazzy** (`/opt/ros/jazzy`) | Humble 官方不支持 noble；Jazzy 是 noble 的官方发行版 |
| 已装 ROS2 (任意发行版) | 复用现有 | 只需 `source` 对应 `setup.bash` |

> **关键**：后续所有 `source` 命令、`systemd` 文件里的路径、`apt` 包名都要对应所选发行版。
> 例：Jazzy 用 `ros-jazzy-desktop`，Humble 用 `ros-humble-desktop`。

## 2. 安装 ROS2 + Python 依赖（若缺失）

### 2.1 配置 ROS2 apt 仓库

```bash
# 清华 TUNA 镜像 (内网测试机用 trusted=yes 绕过签名)
apt-get update
apt-get install -y curl gnupg2 lsb-release ca-certificates software-properties-common wget

# 根据架构选 arch= (arm64 / amd64)
echo "deb [arch=amd64 trusted=yes] https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu jammy main" \
  > /etc/apt/sources.list.d/ros2.list
apt-get update
```

> **注意**：如果目标主机是 amd64 (x86_64)，`arch=arm64` 改为 `arch=amd64`。
> **注意**：`trusted=yes` 绕过 GPG 签名验证，仅适用于内网测试机。生产环境用 `signed-by`。

### 2.2 安装 ROS2 Desktop

```bash
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ros-<distro>-desktop \         # humble / jazzy
  ros-dev-tools \
  python3-colcon-common-extensions \
  python3-rosdep \
  python3-argcomplete \
  python3-pip
```

### 2.3 安装 Python 依赖

项目 `requirements.txt` 要求：
```
requests>=2.25.0, aiohttp>=3.8.0, netifaces>=0.11.0,
fastapi>=0.100.0, uvicorn[standard]>=0.23.0, pyyaml>=6.0,
psutil>=5.9.0, websockets>=12.0
```

```bash
pip3 install --break-system-packages --ignore-installed \
  "fastapi>=0.100.0" "pydantic>=2.0" "starlette>=0.27" \
  "uvicorn[standard]>=0.23.0" "aiohttp>=3.8.0" \
  "websockets>=12.0" "jinja2>=3.0" "python-multipart>=0.0.6" \
  "pyyaml>=6.0" "psutil>=5.9.0" "netifaces>=0.11.0" "requests>=2.25.0" \
  typing_extensions
```

> **踩坑点**：debian 系统 `typing_extensions` 被 RECORD 锁定，`pip install` 报
> `Cannot uninstall typing_extensions`。解决：加 `--ignore-installed`。

### 2.4 验证 ROS2 + Python 包

```bash
source /opt/ros/<distro>/setup.bash
ros2 pkg list | wc -l          # 应 ≥ 273
python3 -c 'import fastapi,uvicorn,aiohttp,yaml,psutil,netifaces,websockets,jinja2; print("all-ok")'
```

## 3. 上传源码到目标主机

### 3.1 需要上传的包

| 本地路径 | 远程路径 | 说明 |
|---|---|---|
| `E:\develop\ioe-ai\code` | `/root/ros2_ws/src/app_mgr_object/` | 主应用包 (ament_python) |
| `E:\develop\ioe-ai\cpp_ros2_interfaces` | `/root/ros2_ws/src/cpp_ros2_interfaces/` | 自定义消息包 (ament_cmake) |

> **为什么上传 cpp_ros2_interfaces**：
> `app_mgr_object` 的 `bay_status_fusion` 插件 `import cpp_ros2_interfaces.msg` (BayStatus)，
> 用于强类型订阅 `/dev01_object_status`。代码用 try/except 包裹 import，
> 缺失时 `MSG_AVAILABLE=False` 退化为不订阅——不致命但功能缺失。
> **它是消息库，不是节点**；运行时只有 `/app_mgr_object` 一个节点。

### 3.2 上传方式（Python paramiko，非交互式 SSH）

```python
import paramiko
from pathlib import Path

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("<IP>", username="root", password="<PWD>", timeout=15,
          allow_agent=False, look_for_keys=False)

def _upload_tree(sftp, local: Path, remote: str):
    # 创建远程目录
    parts = remote.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try: sftp.stat(cur)
        except IOError:
            try: sftp.mkdir(cur)
            except IOError: pass
    # 上传 (跳过 __pycache__ / .git / build / install / log)
    SKIP = {"__pycache__", ".git", "build", "install", "log", ".pytest_cache"}
    for child in sorted(local.iterdir()):
        if child.name in SKIP: continue
        r = remote.rstrip("/") + "/" + child.name
        if child.is_dir():
            _upload_tree(sftp, child, r)
        else:
            sftp.put(str(child), r)

sftp = c.open_sftp()
_upload_tree(sftp, Path(r"E:\develop\ioe-ai\code"),
             "/root/ros2_ws/src/app_mgr_object")
_upload_tree(sftp, Path(r"E:\develop\ioe-ai\cpp_ros2_interfaces"),
             "/root/ros2_ws/src/cpp_ros2_interfaces")
sftp.close()
c.close()
```

> **跳过目录**：`__pycache__`、`.git`、`build`、`install`、`log`、`.pytest_cache`、`*.egg-info`。

### 3.3 验证上传

```bash
ls /root/ros2_ws/src/
# 应看到: app_mgr_object  cpp_ros2_interfaces

ls /root/ros2_ws/src/app_mgr_object/app_mgr_object/plugins/ | wc -l
# 应 ≥ 9 (9 个插件 .py + __init__.py + base_plugin.py + event_bus.py)

ls /root/ros2_ws/src/cpp_ros2_interfaces/msg/
# 应看到: BayArea.msg  BayChannelStatus.msg  BayStatus.msg
```

## 4. 修改配置文件适配目标主机

### 4.1 需要改的配置项

| 配置文件 | 字段 | 旧值 (示例) | 新值 (按目标主机实际改) | 原因 |
|---|---|---|---|---|
| `config/params.yaml` | `ros_network_interface` | `"eth0"` | `"<目标主机实际网卡名>"` | 网卡名不同 |
| `config/params.yaml` | `api_network_interface` | `"eth0"` | `"<目标主机实际网卡名>"` | 同上 |
| `config/plugin_configs/network.yaml` | `ros_network_interface` | `"eth0"` | `"<目标主机实际网卡名>"` | 同上 |
| `config/plugin_configs/network.yaml` | `api_network_interface` | `"eth0"` | `"<目标主机实际网卡名>"` | 同上 |
| `app_mgr_object/base/param_manager.py` | 默认值 `ros_network_interface` | `'eth0'` | `'<目标主机实际网卡名>'` | 代码内默认值 |
| `app_mgr_object/base/param_manager.py` | 默认值 `api_network_interface` | `'eth0'` | `'<目标主机实际网卡名>'` | 同上 |
| `config/plugin_configs/rcs_adapter.yaml` | `rcs_base_url` | `"http://192.168.31.249:8080"` | 目标主机 IP 或真正的 RCS 地址 | 指向旧主机 |
| `config/web_monitor.yaml` | `calibration.config_file` | `/opt/jmSY-PROJECT/.../params.yaml` | 目标主机上实际标定配置路径 | 绝对路径指向旧部署 |

> **最常踩的坑**：网卡名。用 `ip -br addr` 确认目标主机实际网卡名
> (常见：`eth0` / `enp2s0` / `wlan0`)。配错会 WARN 刷屏。

### 4.2 修改方式（sed 精确替换）

```bash
# 1. params.yaml + network.yaml: eth0 -> 实际网卡名 (例如 enp2s0)
sed -i 's/"eth0"/"enp2s0"/g' /root/ros2_ws/src/app_mgr_object/config/params.yaml
sed -i 's/"eth0"/"enp2s0"/g' /root/ros2_ws/src/app_mgr_object/config/plugin_configs/network.yaml

# 2. param_manager.py 默认值
sed -i "s/'eth0'/'enp2s0'/g" /root/ros2_ws/src/app_mgr_object/app_mgr_object/base/param_manager.py

# 3. rcs_adapter.yaml: .249 -> 目标 IP (保持 enabled:false 不变)
sed -i 's|http://192.168.31.249:8080|http://<目标IP>:8080|' \
  /root/ros2_ws/src/app_mgr_object/config/plugin_configs/rcs_adapter.yaml

# 4. web_monitor.yaml calibration config_file 路径
sed -i 's|/opt/jmSY-PROJECT/.../params.yaml|<目标主机上实际路径>|' \
  /root/ros2_ws/src/app_mgr_object/config/web_monitor.yaml
```

### 4.3 外部依赖服务 (非阻断，但影响功能完整性)

这些是**业务侧未部署的配套服务**，不是代码缺陷：

| 服务 | 地址 | 处理 (无该服务时) |
|---|---|---|
| RCS 服务端 | `<IP>:8080` 或其他端口 | 保持 `rcs_adapter` + `status_poller` 的 `enabled: false` |
| OPS 服务 | `127.0.0.1:1818` | 保持 `ops_integration.enabled: false` |
| 视频推理节点 | `/rtsp_multi_inference` | 会导致"节点离线"告警，非致命 |

### 4.4 SQLite 数据库 (无需初始化)

> **重要澄清**：`config/db_schema.sql` 是一份遗留的建表脚本，
> 但**项目代码里没有任何 `import sqlite3` 或 `sqlite3.connect`**。
> grep `task_manager.db` / `/data/task` 在整个 `app_mgr_object/` 下零命中。
> 持久化用的是 YAML 文件 (`param_manager.py` 的 `set_param_and_persist`)
> 和 JSON 文件 (`token_storage.py`、`alarm_manager.py`)。
> **所以 `/data/task_manager.db` 无需初始化**——db_schema.sql 可忽略。

## 5. 修复 OpenCV 兼容性 (cv2.Mat bug)

> **仅在系统 OpenCV < 4.5.1 时需要** (没有 `cv2.Mat` 类)。
> 用 `python3 -c "import cv2; print(hasattr(cv2,'Mat'))"` 确认。

如果报 `AttributeError: module 'cv2' has no attribute 'Mat'`：

### 5.1 改 `app_mgr_object/components/web/image_manager.py`

```python
# 顶部加 import numpy as np (在 import cv2 之后)
import cv2
import numpy as np          # ← 新增

# 第 26 行: cv2.Mat -> np.ndarray
self.latest_frames: Dict[int, np.ndarray] = {}    # ← 改

# 第 181 行: cv2.Mat -> np.ndarray
def get_latest_frame(self, channel_id: int) -> Optional[np.ndarray]:    # ← 改
```

### 5.2 OpenCV 依赖分析 (为什么需要它)

**OpenCV 不是核心业务依赖**，只被 2 个文件使用，都集中在 Web 标定/图像这块：

1. **`image_manager.py`** (推理图像管理器)：
   - `from cv_bridge import CvBridge` — ROS2 图像消息 ↔ OpenCV 矩阵转换
   - 用于订阅视频推理节点发布的调试图像话题，缓存帧供 Web 端标定页面查看

2. **`web_server.py`** (Web 服务器)：
   - `import cv2` — 两处 `cv2.im_encode('.jpg', frame, ...)` 做 JPEG 编码
   - 用于 HTTP `/api/calibration/frame` 和 WebSocket 推流

**业务核心** (仓位融合 / 触发匹配 / 工作流引擎 / RCS 适配 / 任务监控) **完全不碰 cv2**，
纯 Python + ROS2 + HTTP。

**为何装了 opencv**：`cv_bridge` 是 ROS2 处理图像的标准包，
apt 装 `ros-*-cv-bridge` 会连带装系统 `python3-opencv`。

**为何报 `cv2.Mat` 错**：代码用 `cv2.Mat` 做类型注解，
但旧版 OpenCV (4.6.0 等) 没有 `Mat` 类 (4.5.1+ 才有)。改成 `np.ndarray` 即可。

## 6. 编译 (先消息包，后主包)

> **编译顺序**：必须先编译 `cpp_ros2_interfaces` (自定义消息)，
> 再编译 `app_mgr_object` (依赖这些消息)。

```bash
source /opt/ros/<distro>/setup.bash
cd /root/ros2_ws

# 6a. 先编译自定义消息包
colcon build --packages-select cpp_ros2_interfaces
# 预期: Finished <<< cpp_ros2_interfaces [6.48s]

# 6b. 再编译主应用包
colcon build --packages-select app_mgr_object --symlink-install
# 预期: Finished <<< app_mgr_object [2.66s]
```

> **`--symlink-install`** 让 install 目录用符号链接指向 src，
> 修改源码后无需重新 `colcon build` (仅 Python 包适用)。

### 6.1 验证编译输出

```bash
ls /root/ros2_ws/install/
# 应看到: app_mgr_object/  cpp_ros2_interfaces/

ls /root/ros2_ws/install/app_mgr_object/lib/app_mgr_object/
# 应看到: app_mgr_node  (可执行文件)
```

## 7. 手工启动测试 (先验证能跑再装 systemd)

```bash
source /opt/ros/<distro>/setup.bash
source /root/ros2_ws/install/setup.bash

# 手工跑 10s 看有没有崩
timeout 10 ros2 run app_mgr_object app_mgr_node 2>&1 | tail -40
```

**预期**：9 个插件全部加载激活，然后 `timeout` 触发 SIGTERM 优雅关闭。
日志里应看到 `成功加载 9 个插件` 和 `✅ Web服务器启动成功`。

如果报错，先修：
- `cv2.Mat` 报错 → 见 §5
- `ModuleNotFoundError: No module named 'fastapi'` → 见 §2.3
- `eth1 不存在` 警告 → 见 §4.1 (网卡名配错)

## 8. 安装 systemd 服务并启动

### 8.1 上传 service 文件

把本地 `deploy/app_mgr.service` 上传到目标主机 `/etc/systemd/system/app_mgr.service`。

### 8.2 修复 service 文件里的 ROS2 路径

service 文件默认写的是 Humble 路径，需要根据目标主机实际 ROS2 发行版改：

```bash
# 如果目标主机装的是 Jazzy (而不是 Humble)：
sed -i 's|/opt/ros/humble/setup.bash|/opt/ros/jazzy/setup.bash|g' \
  /etc/systemd/system/app_mgr.service
```

### 8.3 service 文件关键配置

```ini
[Unit]
Description=ROS2 app_mgr_object Node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Environment=ROS_DISTRO=<distro>           # humble / jazzy
Environment=ROS_DOMAIN_ID=0
Environment=RMW_IMPLEMENTATION=rmw_fastrtps_cpp
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/bin/bash -c 'source /opt/ros/<distro>/setup.bash && source /root/ros2_ws/install/setup.bash && echo "ROS2 environment ready"'
ExecStart=/bin/bash -c 'source /opt/ros/<distro>/setup.bash && source /root/ros2_ws/install/setup.bash && exec ros2 launch app_mgr_object app_app.launch.py'
ExecStop=/bin/bash -c 'pkill -f "app_mgr_node" 2>/dev/null; pkill -f "ros2 launch app_mgr" 2>/dev/null; exit 0'
Restart=on-failure
RestartSec=5
TimeoutStartSec=30
TimeoutStopSec=10
KillMode=mixed
StandardOutput=journal
StandardError=journal
SyslogIdentifier=app_mgr
LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

### 8.4 启用并启动

```bash
systemctl daemon-reload
systemctl enable app_mgr          # 开机自启
systemctl start app_mgr           # 启动

# 如果之前有反复重启的失败服务，先清理：
# systemctl stop app_mgr; systemctl reset-failed app_mgr; systemctl daemon-reload
```

## 9. 首次运行验证清单 (8 项全过即部署成功)

```bash
# ═══ 9a. 进程检查 ═══
pgrep -af "app_mgr_node"
# 应看到 app_mgr_node 进程，PID 非空

# ═══ 9b. ROS2 节点检查 ═══
source /opt/ros/<distro>/setup.bash
source /root/ros2_ws/install/setup.bash
ros2 node list
# 应看到: /app_mgr_object

# ═══ 9c. ROS2 话题检查 ═══
ros2 topic list
# 应看到至少: /dev01_object_status  /parameter_events  /rosout

# ═══ 9d. Web API 端口检查 (8080) ═══
curl -s http://<IP>:8080/ | head -5
# 应返回 JSON: {"service":"通用回调服务器","version":"1.0.0",...}

# ═══ 9e. Web 监控面板检查 (9183) ═══
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://<IP>:9183/
# 应返回: HTTP 200

# ═══ 9f. systemd 服务状态检查 ═══
systemctl is-active app_mgr     # 应输出: active
systemctl is-enabled app_mgr    # 应输出: enabled

# ═══ 9g. 日志检查 (无 ERROR) ═══
journalctl -u app_mgr --no-pager -n 50 | grep -c "ERROR"
# 应输出: 0

# ═══ 9h. 资源占用检查 ═══
ps -p $(pgrep -f "app_mgr_node" | head -1) -o pid,pcpu,pmem,rss,etime
# RSS 应在 180-220MB 范围
```

## 10. 更新代码流程 (本地改代码后重新部署)

```bash
# 1. 在本地修改代码 (编辑 E:\develop\ioe-ai\code\ 下的文件)
# 2. 上传修改的文件到远程 (用 paramiko/sftp)
# 3. 在远程重新编译 (如果改了 Python 代码且用 --symlink-install，可跳过)
source /opt/ros/<distro>/setup.bash
cd /root/ros2_ws
colcon build --packages-select app_mgr_object --symlink-install
# 4. 重启 systemd 服务
systemctl restart app_mgr
# 5. 验证
systemctl status app_mgr
journalctl -u app_mgr --no-pager -n 20
```

## 11. 常见故障排查速查表

| 现象 | 可能原因 | 排查命令 | 修复方法 |
|---|---|---|---|
| `systemctl status` 显示 `failed` | 编译失败或依赖缺失 | `journalctl -u app_mgr -n 50` | 检查编译输出，确认 Python 依赖已安装 |
| service 反复重启 | service 文件 ROS2 路径错 | `journalctl -u app_mgr \| grep "没有那个文件"` | 把 `/opt/ros/humble` 改为实际发行版路径 |
| 8080 端口无响应 | 节点未启动或崩溃 | `pgrep -af app_mgr_node` | `systemctl restart app_mgr` |
| 9183 返回 500 | Starlette TemplateResponse 签名不兼容 | `journalctl -u app_mgr \| grep TypeError` | 确认 `web_server.py` 用新签名 `(request, name, context)` |
| 日志大量 404 | status_poller 轮询打到本机 | `journalctl -u app_mgr \| grep 404` | 禁用 `status_poller.yaml` 的 `enabled` |
| `eth1 不存在` 警告 | 配置引用了不存在的网卡 | `ip addr` 确认实际网卡 | 把 `api_network_interface` 改为实际网卡名 |
| `cv2.Mat` 报错 | 旧 opencv 无 Mat 类 | `python3 -c "import cv2; print(cv2.__version__)"` | 把 `cv2.Mat` 改为 `np.ndarray` |
| `Cannot uninstall typing_extensions` | debian RECORD 锁 | pip install 报错信息 | 加 `--ignore-installed` |
| colcon build 卡住 | 网络不通或镜像不可达 | `curl -I https://mirrors.tuna.tsinghua.edu.cn` | 检查网络、DNS、镜像源配置 |

## 12. 项目节点拓扑 (部署范围参考)

本项目是一个**单节点多插件**的 ROS2 应用：

### 12.1 本项目自身节点 (1 个)

| 节点名 | 可执行 | 说明 |
|---|---|---|
| `/app_mgr_object` | `app_mgr_node` | 唯一主节点，9 个插件全在此进程内运行 |

9 个插件 (`config/params.yaml` 的 `plugin_load_order`)：

| # | 插件 | 作用 | 依赖外部 |
|---|---|---|---|
| 1 | `network` | 网络接口管理 | 无 |
| 2 | `callback_handler` | RCS 回调接收 (POST) | RCS 服务端会调它 |
| 3 | `rcs_adapter` | 调 RCS 接口下发任务 | **RCS 服务端** (当前禁用) |
| 4 | `bay_status_fusion` | 起始仓位状态融合 | 订阅 `/dev01_object_status` |
| 5 | `status_poller` | 轮询 AGV/仓位状态 | **RCS 服务端** (当前禁用) |
| 6 | `workflow_engine` | 工作流状态机引擎 | 无 |
| 7 | `task_status_monitor` | 任务状态监控 | 无 |
| 8 | `smart_trigger` | 智能触发匹配+派发 | 依赖 workflow_engine |
| 9 | `web_monitor` | Web 运维监控面板 (9183) | 可选 OPS 服务 |

### 12.2 外部依赖节点/服务 (本项目订阅或调用，但不在本仓库)

| 节点/服务 | 话题/地址 | 来源 | 当前状态 |
|---|---|---|---|
| 视频推理节点 | `/rtsp_multi_inference`，发布 `/dev01_object_status` | **独立仓库** `rtsp_multi_yolov_plugin` | 未部署 |
| RCS 服务端 | HTTP `/queryAgvStatus` 等 | **独立服务** | 未部署 (插件禁用) |
| OPS 服务 | HTTP `127.0.0.1:1818` | **独立服务** | 未部署 (集成禁用) |
| 自定义消息包 | `cpp_ros2_interfaces` (BayStatus 等) | **同工作空间** `E:\develop\ioe-ai\cpp_ros2_interfaces` | 需一并上传编译 |

### 12.3 本项目提供的 Web 服务端口

| 端口 | 用途 |
|---|---|
| 8080 | RCS 回调服务器 + 部分 API |
| 9183 | Web 运维监控面板 (FastAPI) |

## 13. 回滚方案

如果新版本部署失败，需要回退到上一个可用版本：

```bash
# 1. 停止服务
systemctl stop app_mgr

# 2. 回退代码 (如果有 git)
cd /root/ros2_ws/src/app_mgr_object
git log --oneline -5          # 查看最近的提交
git checkout <上一个可用版本的commit-hash>

# 3. 重新编译
source /opt/ros/<distro>/setup.bash
cd /root/ros2_ws
colcon build --packages-select app_mgr_object --symlink-install

# 4. 重启服务
systemctl start app_mgr

# 5. 验证
systemctl status app_mgr
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://<IP>:9183/
```

## 规则

- **先探查再动手**：SSH 连上后先跑 §1 的探查命令，根据结果选 ROS2 发行版路径 (§1.1)。
- **编译顺序固定**：先 `cpp_ros2_interfaces`，后 `app_mgr_object`。反了会报 `No module named 'cpp_ros2_interfaces'`。
- **网卡名必须改**：用 `ip -br addr` 确认目标主机实际网卡名，配错会 WARN 刷屏。
- **systemd 路径必须改**：service 文件里 `/opt/ros/humble/` 要改成目标主机实际 ROS2 发行版路径。
- **手工跑通再装 systemd**：先 `timeout 10 ros2 run ...` 确认节点能起来，再装 service。否则 service 反复重启难排查。
- **SQLite 无需初始化**：`db_schema.sql` 是遗留脚本，代码不读它。不要浪费时间初始化 `/data/task_manager.db`。
- **8 项检查全过才算成功**：§9 的 8 项检查清单 (进程/节点/话题/Web API/Web 监控/systemd/日志/资源) 全过才算部署完成。
- **不要跑真机 RCS 接口**：`rcs_adapter` 和 `status_poller` 默认 `enabled: false`。除非有真正的 RCS 服务端，否则不要启用，否则 404 刷屏。
