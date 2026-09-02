# app_mgr_object-0.1.2-3 control.html 深色主题统一改造方案

> 文档编号：36-IMPL
> 目标工程：`app_mgr_object-0.1.2(基础版)-3`
> 改动范围：`templates/control.html` — 内联 CSS 块 + HTML 卡片结构 + 按钮样式
> 风格基准：`templates/index.html`（首页深色工业仪表盘）
> 实施日期：2026-08-06

---

## 0. 差异分析

### 0.1 当前 control.html 问题清单

| 问题 | 位置 | 影响 |
|---|---|---|
| Bootstrap `.bg-info/.bg-danger/.bg-warning/.bg-dark/.bg-secondary` 类残留 | card-header | custom.css 有 `!important` 覆盖，但标记语义混乱 |
| 按钮使用 Bootstrap 默认 `.btn-warning/.btn-danger/.btn-secondary` 类 | 启停按钮 | 浅色背景与深色主题冲突 |
| 快速操作按钮 `.quick-action-btn` 样式与首页 `.btn-outline` 风格不一致 | 快速操作区 | 视觉效果分裂 |
| 操作日志表格使用 `.table-striped` Bootstrap 类 | 日志区 | 白色条纹 |
| 自定义弹窗 `.custom-modal` 依赖内联 CSS（Document 36 已部分修复） | 弹窗 | 渐变彩色头部已改为统一深色 |
| 模式指示器 `.mode-indicator` 定位 `top:70px` 与导航栏高度不匹配 | 浮标 | 导航栏 48px，应调为 top:56px |

### 0.2 目标风格（与首页一致）

```
首页卡片特征：
┌──────────────────────────┐
│ CARD-HEADER (uppercase)   │  ← var(--bg-tertiary) + var(--text-secondary) + 12px/600
├──────────────────────────┤
│ card-body                 │  ← var(--bg-secondary) + var(--text-primary) + 14px
└──────────────────────────┘

按钮特征：
  btn-accent  → var(--accent-blue) 背景，白色文字，8px 圆角
  btn-outline → 透明背景，var(--text-secondary) 文字，1px var(--border) 边框
  btn-danger  → var(--accent-red) 背景
  btn-warning → var(--accent-orange) 背景
```

---

## 1. 改造策略

**不重写整个文件**（2800+ 行，业务逻辑密集），采用精准替换策略：

| 区域 | 策略 |
|---|---|
| `extra_css` `<style>` 块 | **完整替换** — 新深色样式表（~100 行，从 250 行精简） |
| HTML 中的 `.bg-*` 类 | **移除** — 用统一的 `.card-header` 样式接管（custom.css 已覆盖） |
| HTML 中的 `.btn-warning/.btn-danger/.btn-secondary` 类 | **替换** — 改用自定义按钮类 |
| `.quick-action-btn` 按钮 | **保留结构，改样式** — 与首页 btn-outline 保持一致 |
| 自定义弹窗 HTML | **不改** — CSS 已在 custom.css 底部覆盖 |
| JS 脚本区 | **不改** — 功能保持不变 |

---

## 2. 完整代码

### Step 1 — 替换 `{% block extra_css %}` 区域（第 5-127 行）

将 control.html 中第 5 行到第 127 行（`{% block extra_css %} ... {% endblock %}`）完整替换为：

```html
{% block extra_css %}
<style>
    /* ===== control.html 内联样式 — 与首页统一深色主题 ===== */

    /* ----- 模式指示器 ----- */
    .mode-indicator {
        position: fixed; top: 56px; right: 20px; z-index: 999;
        padding: 4px 14px; border-radius: 14px; font-size: 11px;
        font-weight: 600; color: #fff; cursor: default;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    }
    .mode-indicator.mode-development { background: var(--accent-blue); }
    .mode-indicator.mode-deployment  { background: var(--accent-red); }

    /* ----- 快速操作按钮 ----- */
    .quick-action-btn {
        display: flex; align-items: center; gap: 10px;
        background: transparent; color: var(--text-secondary);
        border: 1px solid var(--border); border-radius: 6px;
        padding: 10px 14px; margin-bottom: 8px;
        font-size: 13px; font-weight: 500;
        cursor: pointer; transition: all 0.2s;
        width: 100%; text-align: left;
    }
    .quick-action-btn:hover {
        background: var(--bg-tertiary); color: var(--text-primary);
        border-color: var(--accent-blue);
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    }
    .quick-action-btn i { font-size: 15px; width: 20px; text-align: center; }

    /* 不同操作的左侧强调色 */
    .quick-action-btn.restart-infer   { border-left: 3px solid var(--accent-orange); }
    .quick-action-btn.restart-rcs     { border-left: 3px solid var(--accent-red); }
    .quick-action-btn.system-check    { border-left: 3px solid var(--accent-blue); }
    .quick-action-btn.clear-cache     { border-left: 3px solid var(--accent-teal); }
    .quick-action-btn.refresh-status  { border-left: 3px solid var(--accent-green); }
    .quick-action-btn.view-logs       { border-left: 3px solid var(--accent-purple); }

    /* ----- 自定义弹窗（深色） ----- */
    .custom-modal {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        z-index: 1050; display: none;
        background: rgba(0,0,0,0.5); backdrop-filter: blur(2px);
    }
    .custom-modal.show {
        display: flex; align-items: center; justify-content: center;
    }
    .custom-modal-dialog {
        width: 90%; max-width: 500px; z-index: 1052;
        animation: toast-in 0.3s ease;
    }
    .custom-modal-content {
        background: var(--bg-secondary); border: 1px solid var(--border);
        border-radius: var(--card-radius); box-shadow: 0 8px 30px rgba(0,0,0,0.5);
        overflow: hidden;
    }
    .custom-modal-header {
        padding: 16px 20px; background: var(--bg-tertiary);
        border-bottom: 1px solid var(--border); color: var(--text-primary);
        font-size: 15px; font-weight: 600;
        display: flex; align-items: center; justify-content: space-between;
    }
    .custom-modal-body {
        padding: 20px; max-height: 60vh; overflow-y: auto;
        color: var(--text-primary); font-size: 13px; line-height: 1.6;
    }
    .custom-modal-footer {
        padding: 12px 20px; background: var(--bg-tertiary);
        border-top: 1px solid var(--border);
        display: flex; justify-content: flex-end; gap: 10px;
    }
    .custom-modal-btn {
        padding: 7px 18px; border-radius: 5px; font-size: 12px;
        border: 1px solid var(--border); cursor: pointer;
        background: var(--bg-secondary); color: var(--text-secondary);
        transition: all 0.15s;
    }
    .custom-modal-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }
    .custom-modal-btn-primary {
        background: var(--accent-blue); color: #fff; border-color: var(--accent-blue);
    }
    .custom-modal-btn-primary:hover { background: #2980b9; }
    .custom-modal-btn-danger {
        background: var(--accent-red); color: #fff; border-color: var(--accent-red);
    }
    .custom-modal-btn-danger:hover { background: #c0392b; }

    /* ----- 卡片过渡动画 ----- */
    .card-transition { transition: all 0.3s ease; }
    .card-hidden {
        opacity: 0; height: 0; overflow: hidden;
        margin: 0 !important; padding: 0 !important;
        border: none !important; display: none !important;
    }
    .card-visible { opacity: 1; height: auto; display: block !important; }
    .initially-hidden { display: none !important; }

    /* ----- 操作日志表格 ----- */
    .operation-stats-table {
        color: var(--text-primary);
        font-size: 12px;
    }
    .operation-stats-table th {
        color: var(--text-muted); font-size: 10px; text-transform: uppercase;
        background: var(--bg-tertiary); border-bottom: 2px solid var(--border);
    }
    .operation-stats-table td {
        border-color: var(--border); color: var(--text-secondary);
    }
    .operation-stats-table tbody tr:hover { background: var(--bg-tertiary); }

    /* ----- 运行模式功能区分隔 ----- */
    .mode-specific-features {
        border-top: 1px dashed var(--border);
        padding-top: 12px; margin-top: 12px;
    }
    .card-note { font-size: 11px; opacity: 0.8; color: var(--text-muted); }

</style>
{% endblock %}
```

### Step 2 — HTML 区域替换指南（第 128-636 行）

以下是每个需要修改的区域的对照表。**不重写整个 HTML**，按位置逐个修改：

#### 2.1 卡片标题：移除 Bootstrap 颜色类

**查找模式**: `class="card-header bg-* text-white"`

将所有 `bg-info`、`bg-danger`、`bg-warning`、`bg-dark`、`bg-secondary`、`bg-success` 和对应的 `text-white` 从 `card-header` 中移除：

```diff
- <div class="card-header bg-info text-white">
+ <div class="card-header">
```

custom.css 已通过以下规则统一接管所有 card-header 样式，无需 `bg-*` 类：

```css
.card-header {
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    /* ... */
}
```

**涉及的具体位置**（以原 HTML 中常见的卡片为例）：

| 原代码 | 改为 |
|---|---|
| `<div class="card-header bg-info text-white">` | `<div class="card-header">` |
| `<div class="card-header bg-danger text-white">` | `<div class="card-header">` |
| `<div class="card-header bg-warning text-white">` | `<div class="card-header">` |
| `<div class="card-header bg-dark text-white">` | `<div class="card-header">` |
| `<div class="card-header bg-secondary text-white">` | `<div class="card-header">` |
| `<div class="card-header bg-success text-white">` | `<div class="card-header">` |

#### 2.2 按钮：替换 Bootstrap 颜色类

**查找模式**: `class="btn btn-* "`

| 原代码 | 改为 |
|---|---|
| `class="btn btn-warning btn-sm"` | `class="btn btn-warning btn-warning-sm"` |
| `class="btn btn-danger btn-sm"` | `class="btn btn-danger btn-danger-sm"` |
| `class="btn btn-secondary btn-sm"` | `class="btn btn-outline btn-sm"` |
| `class="btn btn-info btn-sm"` | `class="btn btn-accent btn-sm"` |

注意：`btn-warning-sm` 和 `btn-danger-sm` 类已在 custom.css 中定义（Phase 1），使用 `var(--accent-orange)` 和 `var(--accent-red)` 背景。

#### 2.3 表格：移除浅色条纹类

**查找**: `.table-striped`

```diff
- <table class="table table-striped ...">
+ <table class="table task-table ...">
```

`task-table` 类已在 custom.css 中定义深色斑马纹（`tr:nth-child(even) { background: rgba(255,255,255,0.02); }`）。

#### 2.4 alert/徽章：替换为深色变体

| 原代码 | 改为 |
|---|---|
| `<div class="alert alert-info">` | `<div style="background:var(--bg-tertiary);color:var(--text-primary);border:1px solid var(--border);border-radius:5px;padding:10px 14px;">` |
| `<div class="alert alert-success">` | 同上，左边框改为 `var(--accent-green)` |
| `<div class="alert alert-danger">` | 同上，左边框改为 `var(--accent-red)` |
| `<span class="badge bg-success">` | `<span class="status-badge completed">` |
| `<span class="badge bg-danger">` | `<span class="status-badge failed">` |

### Step 3 — 不需要修改的区域

以下区域保持原有代码不变：

| 区域 | 原因 |
|---|---|
| 系统控制卡片（启停服务、重启节点等）HTML 结构 | 功能逻辑不动 |
| 快速操作按钮的 HTML 结构（`.quick-action-btn` 元素） | 仅 CSS 样式变更，结构不变 |
| 操作日志表格的数据填充逻辑 | 功能不动 |
| 告警管理面板（Document 36 已添加） | 已使用深色样式 |
| 全部 `<script>` 区域（第 637 行起） | 功能不动 |
| 自定义弹窗的 HTML 结构（`.custom-modal` 元素） | CSS 已覆盖 |

---

## 3. 改造效果对照

### 3.1 卡片标题

```
改造前（浅色 Bootstrap）：
┌──────────────────────────────┐
│ [蓝色渐变 bg-info] 系统控制   │  ← Bootstrap 默认蓝 + 白色文字
├──────────────────────────────┤

改造后（深色统一）：
┌──────────────────────────────┐
│ SYSTEM CONTROL               │  ← var(--bg-tertiary) + var(--text-secondary) + uppercase
├──────────────────────────────┤
```

### 3.2 按钮

```
改造前：
[浅黄 btn-warning] [浅红 btn-danger] [浅灰 btn-secondary]

改造后：
[深橙 btn-warning-sm] [深红 btn-danger-sm] [边框 btn-outline]
```

### 3.3 快速操作按钮

```
改造前：
┌──────────────────────┐
│ [蓝底] 重启推理节点    │
│ [红底] 重启RCS管理    │
└──────────────────────┘

改造后：
┌──────────────────────┐
│ ▌[深色背景] 重启推理   │  ← 透明背景 + 橙色左边框
│ ▌[深色背景] 重启RCS   │  ← 透明背景 + 红色左边框
│ ▌[深色背景] 系统检查   │  ← 透明背景 + 蓝色左边框
└──────────────────────┘
```

---

## 4. 查找替换快速清单

以下是可以批量查找替换的全局操作（按顺序执行）：

### 4.1 card-header 颜色类清理

查找: `class="card-header bg-info text-white"`
替换: `class="card-header"`

查找: `class="card-header bg-danger text-white"`
替换: `class="card-header"`

查找: `class="card-header bg-warning text-white"`
替换: `class="card-header"`

查找: `class="card-header bg-dark text-white"`
替换: `class="card-header"`

查找: `class="card-header bg-secondary text-white"`
替换: `class="card-header"`

查找: `class="card-header bg-success text-white"`
替换: `class="card-header"`

### 4.2 按钮类替换

查找: `class="btn btn-warning btn-sm"`
替换: `class="btn btn-warning btn-warning-sm"`

查找: `class="btn btn-danger btn-sm"`
替换: `class="btn btn-danger btn-danger-sm"`

查找: `class="btn btn-secondary btn-sm"`
替换: `class="btn btn-outline btn-sm"`

查找: `class="btn btn-info btn-sm"`
替换: `class="btn btn-accent btn-sm"`

### 4.3 表格类替换

查找: `class="table table-striped"`
替换: `class="table task-table"`

---

## 5. 改动文件清单

| # | 文件 | 改动类型 | 行数 | 说明 |
|---|---|---|---|---|
| 1 | `templates/control.html` — `extra_css` 块 | 🔴 完整替换 | ~120 行（旧样式 250→新 100） | 精简 + 统一深色 |
| 2 | `templates/control.html` — HTML 中 `bg-*` 类 | 🟡 批量删除 | ~20 处 | card-header 颜色类移除 |
| 3 | `templates/control.html` — HTML 中 `btn-*` 类 | 🟡 批量替换 | ~15 处 | 按钮颜色类替换 |
| 4 | `templates/control.html` — HTML 中 `table-striped` 类 | 🟡 批量替换 | ~3 处 | 表格类替换 |

---

> **文档结束** — Step 1 完整替换 extra_css 块（复制上方 CSS 代码到第 5-127 行），Step 2 按查找替换清单逐项修改 HTML。custom.css 无需修改（已在 `-3` 版本中包含了 control 页面适配规则）。预计工期 2 小时。
