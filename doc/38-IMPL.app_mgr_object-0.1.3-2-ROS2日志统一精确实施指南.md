# app_mgr_object-0.1.3-2 ROS2 日志统一 — 最终精确实施方案

> 文档编号：38-IMPL
> 参照方案：[38.app_mgr_object-0.1.3-ROS2统一日志系统技术方案.md](./38.app_mgr_object-0.1.3-ROS2统一日志系统技术方案.md)
> 目标工程：`app_mgr_object-0.1.3(基础版)-2`
> 审计范围：`components/` 12 个目录 65 个 `.py` + `plugins/` 13 个 `.py` = 78 文件
> 改动文件：**6 个**，约 35 行
> 预期工期：2 小时

---

## 0. 最终审计结论（逐行验证）

### 0.1 合规项（无需改动）

| 文件 | 状态 | 证据 |
|---|---|---|
| `plugins/web_monitor_plugin.py` | ✅ | `ControlExecutor(..., logger=self.logger)` (L238), `AlarmManager(..., logger=self.logger)` (L243) |
| `plugins/bay_status_fusion_plugin.py` | ✅ | `BayCache(..., logger=self.logger)` (L70), `AreaStatusFilter(..., logger=self.logger)` (L299) |
| `plugins/callback_handler_plugin.py` | ✅ | `CallbackReceiver(logger=self.logger, ...)` (L54) |
| `components/web/control_executor.py` | ✅ | `__init__(..., logger=None)` + `if self.logger is None: logging.getLogger(__name__)` |
| `components/web/alarm_manager.py` — `AlarmManager` | ✅ | `__init__(..., logger=None)` (L285) + `if self.logger is None: logging.getLogger` (L292-294) |
| 其余 ~65 个组件文件 | ✅ | `logger or logging.getLogger(__name__)` 降级模式 |

### 0.2 不合规项（需改动）

| # | 文件 | 行号 | 问题 | 优先级 |
|---|---|---|---|---|
| 1 | `alarm_manager.py` | 73 | `AutoRecoveryManager.__init__` 无 `logger` 参数 | 🔴 |
| 2 | `alarm_manager.py` | 132 | `AutoRecoveryManager.check_and_recover` 中 `print()` | 🔴 |
| 3 | `alarm_manager.py` | 524,613,701 | `AlarmManager` 中 3 处 `print()` | 🟡 |
| 4 | `web_server.py` | 96 | `logging.getLogger('WebServer')` → 应改为 ROS2 child | 🔴 |
| 5 | `web_server.py` | 188-210 | `_get_logger()` 方法已废弃（`__init__` 不再调用） | 🟢 可删除 |
| 6 | `bay_status_fusion_plugin.py` | 30,32 | 模块级 2 处 `print()` | 🟡 |
| 7 | `event_bus.py` | 54 | 1 处 `print()` | 🟡 |

---

## 1. 改造原则

1. **组件侧**：保持 `logger or logging.getLogger(__name__)` 降级模式不变（无 ROS2 环境也能用）
2. **插件侧**：统一传入 `self.logger`（即 `node.get_logger()`，BasePlugin 已初始化）给组件
3. **`print()` 替换**：有 `self.logger` 的地方 → `self.logger.xxx()`；无 `self.logger` 的地方 → `logging.getLogger('ModuleName').xxx()` 兜底
4. **web_server 降级**：`logging.getLogger('WebServer')` → `self.node.get_logger().get_child('WebServer')`

---

## 2. 逐文件精确改动

### 2.1 `components/web/alarm_manager.py`

#### 改动 A — `AutoRecoveryManager.__init__` 增加 `logger` 参数（第 73 行）

```diff
 class AutoRecoveryManager:
     """自动恢复管理器"""

-    def __init__(self, config: Dict[str, Any], alarm_callback: Callable):
+    def __init__(self, config: Dict[str, Any], alarm_callback: Callable, logger=None):
         self.config = config
         self.alarm_callback = alarm_callback
+        self.logger = logger
+        if self.logger is None:
+            import logging
+            self.logger = logging.getLogger(__name__)
         self._recovery_history = []
         self._lock = threading.RLock()
```

#### 改动 B — `print()` → `self.logger.error()`（第 132 行）

```diff
             except Exception as e:
-                print(f"自动恢复失败: {e}")
+                self.logger.error(f"自动恢复失败: {e}")
                 return False
```

#### 改动 C — `AlarmManager.__init__` 中 `AutoRecoveryManager` 传入 `logger`（约第 308 行）

```diff
-        self.auto_recovery = AutoRecoveryManager(self.config, self._on_recovery_alarm)
+        self.auto_recovery = AutoRecoveryManager(self.config, self._on_recovery_alarm, logger=self.logger)
```

#### 改动 D — 3 处 `print()` → `self.logger.error()`（第 524, 613, 701 行）

```diff
         except Exception as e:
-            print(f"检查系统状态失败: {e}")
+            self.logger.error(f"检查系统状态失败: {e}")

...

             except Exception as e:
-                print(f"告警回调执行失败: {e}")
+                self.logger.error(f"告警回调执行失败: {e}")

...

         except Exception as e:
-            print(f"导出告警失败: {e}")
+            self.logger.error(f"导出告警失败: {e}")
```

---

### 2.2 `components/web/web_server.py`

#### 改动 A — 降级从 Python logging 改为 ROS2 child logger（第 93-96 行）

```diff
         self.logger = logger
         if self.logger is None:
-            import logging
-            self.logger = logging.getLogger('WebServer')
+            self.logger = self.node.get_logger().get_child('WebServer')
```

> `self.node` 已在 L92 赋值（`self.node = node`），可直接使用。

#### 改动 B（可选）— 删除废弃的 `_get_logger()` 方法（第 188-210 行）

```diff
-    def _get_logger(self):
-        """获取日志记录器"""
-        import logging
-        logger = logging.getLogger('WebServer')
-        if not logger.handlers:
-            handler = logging.StreamHandler()
-            formatter = logging.Formatter(
-                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
-            )
-            handler.setFormatter(formatter)
-            logger.addHandler(handler)
-        logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
-        return logger
```

> 该方法在 `__init__` 中已不再调用（改用 `logger` 参数），删除 ~22 行冗余代码。

---

### 2.3 `plugins/bay_status_fusion_plugin.py`

#### 改动 A — 模块级 `print()` 替换为 Python logging 兜底（第 25-36 行）

```diff
+import logging
+_bf_logger = logging.getLogger('BayStatusFusion')

 try:
     from cpp_ros2_interfaces.msg import BayStatus, BayChannelStatus, BayArea
     MSG_AVAILABLE = True
-    print(f"[DEBUG] 成功导入 BayStatus 自定义消息")
+    _bf_logger.debug("BayStatus 自定义消息导入成功")
 except ImportError as e:
-    print(f"[DEBUG] 导入 BayStatus 失败: {e}")
+    _bf_logger.warning(f"BayStatus 自定义消息导入失败: {e}")
     MSG_AVAILABLE = False
     BayStatus = None
     BayChannelStatus = None
     BayArea = None
```

> 模块级代码无法使用 `self.logger`（类尚未实例化），使用 `logging.getLogger('BayStatusFusion')` 兜底。导入成功/失败信息在 `_configure_impl` 和 `_activate_impl` 中已有更多日志（L71-77, L90-103），此处改为 DEBUG 级别。

---

### 2.4 `plugins/event_bus.py`

#### 改动 A — `print()` 替换为 Python logging 兜底（第 1 行附近 + 第 54 行）

```diff
+import logging
+_eb_logger = logging.getLogger('EventBus')

# ... 中间代码不变 ...

             except Exception as e:
-                print(f"事件处理错误: {e}")
+                _eb_logger.error(f"事件处理错误: {e}")
```

> `event_bus.py` 不依赖 ROS2 Node，使用 Python logging 兜底。

---

## 3. 改动汇总

| # | 文件 | 行号 | 改动 | 增/删 |
|---|---|---|---|---|
| 1 | `alarm_manager.py` | 73-78 | `AutoRecoveryManager.__init__` 增加 `logger` 参数 + 降级 | +5 |
| 2 | `alarm_manager.py` | 132 | `print(...)` → `self.logger.error(...)` | ±1 |
| 3 | `alarm_manager.py` | ~308 | `AutoRecoveryManager(...)` 追加 `logger=self.logger` | +1 |
| 4 | `alarm_manager.py` | 524 | `print(...)` → `self.logger.error(...)` | ±1 |
| 5 | `alarm_manager.py` | 613 | `print(...)` → `self.logger.error(...)` | ±1 |
| 6 | `alarm_manager.py` | 701 | `print(...)` → `self.logger.error(...)` | ±1 |
| 7 | `web_server.py` | 94-96 | `logging.getLogger('WebServer')` → `node.get_logger().get_child('WebServer')` | -2 / +1 |
| 8 | `web_server.py` | 188-210 | **删除** `_get_logger()` 方法 | -22 |
| 9 | `bay_status_fusion_plugin.py` | 25,30,32 | 模块级 `print()` → `logging.getLogger('BayStatusFusion')` | +3 / -2 |
| 10 | `event_bus.py` | 1,54 | `print()` → `logging.getLogger('EventBus')` | +2 / -1 |
| **合计** | **6 文件** | — | — | **+16 / -31** |

---

## 4. 改造前后日志控制链路对比

### 改造前

```
params.yaml log_level: "info"
  → rclpy 设置 node logger 级别
  → BasePlugin.logger ✅ 受控（12 插件）
  → alarm_manager.py    ❌ print() 始终输出 + logging.getLogger 降级不受控
  → web_server.py       ❌ logging.getLogger('WebServer') 不受控
  → bay_status_fusion   ❌ print() 始终输出
  → event_bus.py        ❌ print() 始终输出
```

### 改造后

```
params.yaml log_level: "info"
  → rclpy 设置 node logger 级别
  → 所有插件 logger ✅ 受控
  → alarm_manager.py    ✅ 通过 logger 参数注入 ROS2 logger，受控
  → web_server.py       ✅ node.get_logger().get_child('WebServer')，受控
  → bay_status_fusion   ✅ logging.getLogger('BayStatusFusion')，通过 ROS2 logging.yaml 控制
  → event_bus.py        ✅ logging.getLogger('EventBus')，通过 ROS2 logging.yaml 控制
```

---

## 5. 生产部署日志控制

```bash
# 生产模式 — 仅告警和错误
ros2 param set /app_mgr_object log_level warn

# 故障排查 — 开 debug 无需重启
ros2 param set /app_mgr_object log_level debug

# 通过 Web API 持久化
curl -X PUT http://127.0.0.1:9183/api/config/params \
  -H 'Content-Type: application/json' \
  -d '{"params": {"log_level": "warn"}}'
```

---

## 6. 验证清单

| # | 验证项 | 操作 | 期望 |
|---|---|---|---|
| 1 | 启动无 `print()` 裸输出 | `ros2 launch ... 2>&1` | 无 "自动恢复失败" / "检查系统状态失败" / "告警回调执行失败" / "导出告警失败" / "[DEBUG]" / "事件处理错误" 等裸字符串 |
| 2 | `log_level=warn` 生效 | `ros2 param set /app_mgr_object log_level warn` | 所有 `[WebServer]` `[AlarmManager]` 前缀的 info/debug 日志静默 |
| 3 | `log_level=debug` 恢复 | `ros2 param set /app_mgr_object log_level debug` | 所有 debug 日志恢复可见 |
| 4 | `_get_logger()` 无引用 | grep 确认 | 编译/启动无引用报错 |
| 5 | 降级可用 | 脱离 ROS2 `import alarm_manager` | `logging.getLogger(__name__)` 降级正常工作 |

---

> **文档结束** — 6 文件，+16/-31 行。核心模式：`node.get_logger().get_child('Name')` / `logging.getLogger('Name')` 兜底 / `logger` 参数注入。改造后全部日志通过 `params.yaml` 的 `log_level` 一键全局控制。
