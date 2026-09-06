# Project Prompt — app_mgr_object

## Project Identity

This is `app_mgr_object`, a plugin-based ROS2 application framework (ament_python).
It provides lifecycle management, parameter management, plugin discovery, and
component reuse for rapidly building extensible ROS2 applications.

## Tech Stack

- ROS2 (Humble on Ubuntu 22.04 / Jazzy on Ubuntu 24.04)
- Python 3.10 (Humble) or 3.12 (Jazzy)
- FastAPI + Uvicorn (Web monitoring panel on port 9183)
- aiohttp (async HTTP client for RCS adapter)
- cv_bridge + OpenCV (inference image manager for calibration module)
- Custom messages: `cpp_ros2_interfaces` (BayStatus/BayChannelStatus/BayArea)

## Architecture (4 layers)

1. **Base framework layer** (`base/`): tightly coupled with ROS2, manages node
   lifecycle and base resources (ParamManager, LifecycleManager, PluginManager,
   ServiceManager, SubscriptionManager, TimerManager).
2. **Component layer** (`components/`): independent reusable units (network,
   task queue, callback, filtering, signal monitoring, web server, image manager).
3. **Plugin layer** (`plugins/`): business functionality carriers, inherit
   `BasePlugin`, compose components. 9 plugins loaded via `plugin_load_order`.
4. **Application layer**: business plugins developed by users, assembled via
   config files.

## Deployment Topology

Single ROS2 node `/app_mgr_object` running 9 in-process plugins:
network, callback_handler, rcs_adapter, bay_status_fusion, status_poller,
workflow_engine, task_status_monitor, smart_trigger, web_monitor.

External dependencies (not in this repo, optional):
- Video inference node (`/rtsp_multi_inference`) — publishes `/dev01_object_status`
- RCS server (HTTP `/queryAgvStatus` etc.)
- OPS service (HTTP `127.0.0.1:1818`)

Web ports: 8080 (RCS callback server), 9183 (Web monitoring panel).

## Key Conventions

- Chinese comments and Chinese/Pinyin variable names are valid — preserve them.
- New code should prefer English identifiers but respect existing Chinese naming.
- `db_schema.sql` is a legacy artifact — code does NOT use SQLite; persistence
  is YAML-based (`param_manager.py`) and JSON-based (`token_storage.py`,
  `alarm_manager.py`).
- OpenCV is only used by `image_manager.py` and `web_server.py` (calibration/
  image encoding). Business core does NOT touch cv2.

## Skill Inventory

- `deploy-app-mgr` (.agents/skills/deploy-app-mgr/SKILL.md): Full deployment
  workflow to a fresh Ubuntu host — environment probe, ROS2 install, source
  upload, config adaptation, build, systemd service, 8-check verification.
  Mirrored at .atomcode/skills/deploy-app-mgr/SKILL.md for AtomCode loading.
