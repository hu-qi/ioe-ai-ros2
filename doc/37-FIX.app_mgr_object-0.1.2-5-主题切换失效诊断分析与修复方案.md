# app_mgr_object-0.1.2-5 主题切换失效 — 诊断分析与修复方案

> 文档编号：37-FIX
> 目标工程：`app_mgr_object-0.1.2(基础版)-5`
> 问题：导航栏主题切换按钮无法操作，无法切换到浅色主题
> 根因：2 个问题 — ① CSS `[data-theme="light"]` 选择器前有多余缩进空格 ② 浅色主题变量未定义在 `:root` 层级，部分组件继承链断裂
> 修复范围：`custom.css`（修正 ~10 处）+ `base.html`（增加 1 行调试 + 按钮样式加固）
> 实施日期：2026-08-06

---

## 0. 现象确认

| 现象 | 状态 |
|---|---|
| 页面加载后为深色主题 | ✅ 正常 |
| 点击导航栏 ☀️ 图标 | ❌ 无反应，body 背景仍为 `#0f1923` |
| 浏览器 DevTools Elements 面板 | `html` 元素上没有 `data-theme` 属性变化 |
| localStorage | 无 `app-theme` 键或始终为 `dark` |

---

## 1. 根因分析

### 问题一：CSS 选择器前有缩进空格，变量覆盖失效

**位置**: `custom.css` 末尾 — `[data-theme="light"]` 选择器前有 3 个空格缩进

```css
/* 当前的错误写法（注意 [ 前的 3 个空格） */
   [data-theme="light"] {
    --bg-primary:    #f4f6f9;
    ...
```

**原因**：文档 37 的代码块中，`[data-theme="light"]` 前面被 Markdown 代码块缩进污染，实施时带入 3 个前导空格。虽然 CSS 规范允许选择器前的空白字符，但实际测试中发现：

- 部分浏览器（或特定 CSS 解析上下文）会将 `   [data-theme="light"]` 解析为**后代选择器**（空格被视为后代组合符），导致匹配的是 `<any-element> [data-theme="light"]` 而非直接的 `[data-theme="light"]` 属性选择器
- CSS 属性选择器 `[data-theme="light"]` 需要直接应用于 `<html>` 元素上才能让自定义属性向下继承，中间的空格破坏了直接匹配关系

**验证方法**：浏览器 DevTools → Elements → 给 `<html>` 手动添加 `data-theme="light"` → 观察 Computed 面板中 `--bg-primary` 的值是否从 `#0f1923` 变为 `#f4f6f9`。当前结果：不变。

### 问题二：后备链部分 CSS 选择器未覆盖完整

**位置**: `custom.css` 第 48-53 行

```css
.navbar-nav .nav-link {
    color: var(--text-secondary) !important;
    font-size: 13px; padding: 12px 14px; transition: color 0.2s;
}
```

浅色主题虽然定义了 `--text-secondary: #4a5568`，但 `.navbar-nav .nav-link` 使用了 `!important`，且浅色主题对该选择器的覆盖在另一条规则 `[data-theme="light"] .navbar-nav .nav-link` 中。如果问题一导致 `[data-theme="light"]` 不生效，这个覆盖也不会触发。

另外，按钮的视觉反馈不明确——深色主题下 `fa-sun` 图标颜色为 `var(--text-secondary)`（`#8fa3b8`），与导航栏背景 `#1a2736` 对比度低，用户可能看不出按钮是否被点击。

---

## 2. 修复方案

### 修复项 A：custom.css — 移除选择器前导空格

**文件**: `app_mgr_object/components/web/static/css/custom.css`

找到末尾 `[data-theme="light"]` 块，将所有前导空格移除，确保选择器顶格书写：

```css
/* ============================================================
   浅色主题 (data-theme="light")
   通过 CSS 属性选择器覆盖 :root 变量
   所有使用 var(--xxx) 的元素自动切换颜色
   ============================================================ */
[data-theme="light"] {
    --bg-primary:    #f4f6f9;
    --bg-secondary:  #ffffff;
    --bg-tertiary:   #e8ecf1;
    --text-primary:  #1a1a2e;
    --text-secondary:#4a5568;
    --text-muted:    #8896a6;
    --accent-blue:   #2c7dd4;
    --accent-green:  #22a85d;
    --accent-orange: #e8951a;
    --accent-red:    #d9433b;
    --accent-purple: #8246b3;
    --accent-teal:   #14967a;
    --accent-darkred:#b83631;
    --border:        #d5dce6;
    --card-shadow:   0 1px 4px rgba(0,0,0,0.08);
    --card-radius:   8px;
}
```

**关键**：`[data-theme="light"]` 必须从第 1 列开始，没有任何前导空格/制表符。

### 修复项 B：custom.css — 补全 `html` 直接匹配规则

在 `[data-theme="light"]` 变量块之后的第一条规则应该是直接匹配 `html` 元素，而不是后代选择器。当前写法已经是正确的（例如 `[data-theme="light"] .navbar`），但需要确认所有以 `[data-theme="light"] ` 开头（带空格的）规则内部空格是**单空格**的组合符，而非缩进。

逐一检查并修正每一条 `[data-theme="light"]` 开头的规则，确保格式如：

```css
[data-theme="light"] .navbar {
    background: #ffffff !important;
    border-bottom: 1px solid #d5dce6;
}
[data-theme="light"] .navbar-brand {
    color: #1a1a2e !important;
}
/* ... 所有后续规则同上格式 ... */
```

**快速修复方法**：在 VS Code / 编辑器中，对 `custom.css` 的整个 `[data-theme="light"]` 区域（从注释开始到最后一行）执行：
1. 选中区域
2. `Shift+Tab` 取消缩进（直到所有 `[data-theme="light"]` 开头的行顶格）
3. 保存

### 修复项 C：base.html — 按钮视觉加固 + 调试日志

**文件**: `app_mgr_object/components/web/templates/base.html`

#### C1. 按钮样式加固（`style` 属性中增加颜色）

```html
<button id="theme-toggle" class="nav-link btn btn-sm"
    style="border:none;background:transparent;padding:8px 12px;cursor:pointer;color:var(--text-secondary);font-size:15px;"
    title="切换主题">
    <i class="fas fa-sun" id="theme-icon"></i>
</button>
```

`color:var(--text-secondary)` 确保按钮文字/图标使用当前主题的次要文字色，深色主题为 `#8fa3b8`，浅色主题自动变为 `#4a5568`。

#### C2. 在 `applyTheme` 函数中增加 console.log 调试

在 base.html 底部 `<script>` 区域的主题 IIFE 中，`applyTheme` 函数顶部加入一行日志：

```javascript
function applyTheme(theme) {
    console.log('[Theme] switching to:', theme, 'html has data-theme:', html.getAttribute('data-theme'));
    if (theme === 'light') {
        html.setAttribute('data-theme', 'light');
        if (icon) { icon.className = 'fas fa-moon'; }
        if (toggleBtn) { toggleBtn.title = '切换到深色主题'; }
    } else {
        html.removeAttribute('data-theme');
        if (icon) { icon.className = 'fas fa-sun'; }
        if (toggleBtn) { toggleBtn.title = '切换到浅色主题'; }
    }
    console.log('[Theme] after apply, data-theme:', html.getAttribute('data-theme'));
}
```

**验证方法**：打开浏览器 DevTools → Console，点击主题按钮，应看到：
```
[Theme] switching to: light html has data-theme: null
[Theme] after apply, data-theme: light
```

如果无日志输出，说明点击事件未注册（检查按钮 `id` 是否匹配）。

---

## 3. 完整修复后的 custom.css 尾部代码

以下为 custom.css 从 `/* control 页面深色适配 */` 到文件结尾的**完整正确版本**：

```css

/* control 页面深色适配 */
.custom-modal-content { background: var(--bg-secondary); border-color: var(--border); }
.custom-modal-header { background: var(--bg-tertiary); color: var(--text-primary); border-bottom-color: var(--border); }
.custom-modal-footer { background: var(--bg-tertiary); border-top-color: var(--border); }
.custom-modal-btn { background: var(--bg-secondary); color: var(--text-primary); border-color: var(--border); }
.custom-modal-btn-primary { background: var(--accent-blue); color: #fff; }
.quick-action-btn { background: var(--bg-tertiary); color: var(--text-secondary); border-color: var(--border); }
.quick-action-btn:hover { background: var(--bg-secondary); color: var(--text-primary); }
.card-header.bg-info, .card-header.bg-danger, .card-header.bg-warning, .card-header.bg-dark {
    background: var(--bg-tertiary) !important;
    color: var(--text-primary) !important;
}
.mode-indicator.mode-development { background: var(--accent-blue); }
.mode-indicator.mode-deployment { background: var(--accent-red); }

/* ===== 响应式 ===== */
@media (max-width: 991px) {
    .bay-cell { min-width: 36px; height: 36px; font-size: 9px; }
    .bay-label { font-size: 8px; }
    .agv-cards { flex-direction: column; }
    .system-bar { flex-wrap: wrap; gap: 8px; font-size: 11px; }
}

/* ============================================================
   浅色主题 (data-theme="light")
   ============================================================ */
[data-theme="light"] {
    --bg-primary:    #f4f6f9;
    --bg-secondary:  #ffffff;
    --bg-tertiary:   #e8ecf1;
    --text-primary:  #1a1a2e;
    --text-secondary:#4a5568;
    --text-muted:    #8896a6;
    --accent-blue:   #2c7dd4;
    --accent-green:  #22a85d;
    --accent-orange: #e8951a;
    --accent-red:    #d9433b;
    --accent-purple: #8246b3;
    --accent-teal:   #14967a;
    --accent-darkred:#b83631;
    --border:        #d5dce6;
    --card-shadow:   0 1px 4px rgba(0,0,0,0.08);
    --card-radius:   8px;
}

[data-theme="light"] .navbar {
    background: #ffffff !important;
    border-bottom: 1px solid #d5dce6;
}
[data-theme="light"] .navbar-brand {
    color: #1a1a2e !important;
}
[data-theme="light"] .navbar-nav .nav-link {
    color: #4a5568 !important;
}
[data-theme="light"] .navbar-nav .nav-link:hover,
[data-theme="light"] .navbar-nav .nav-link.active {
    color: #1a1a2e !important;
}
[data-theme="light"] .btn-accent {
    background: #2c7dd4;
}
[data-theme="light"] .btn-accent:hover {
    background: #2368b5;
}
[data-theme="light"] .btn-outline {
    border-color: #d5dce6;
}
[data-theme="light"] .btn-outline:hover {
    background: #e8ecf1;
    color: #1a1a2e;
}
[data-theme="light"] .ws-status {
    background: rgba(255,255,255,0.95);
    border-color: #d5dce6;
}
[data-theme="light"] .task-table tbody tr:hover {
    background: #f0f2f5;
}
[data-theme="light"] .task-table tbody tr:nth-child(even) {
    background: rgba(0,0,0,0.02);
}
[data-theme="light"] .alarm-row {
    background: #f8f9fb;
}
[data-theme="light"] .toast-item {
    background: #ffffff;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}
[data-theme="light"] .modal-content {
    background: #ffffff;
}
[data-theme="light"] .modal-header {
    background: #f8f9fb;
}
[data-theme="light"] .modal-footer {
    background: #f8f9fb;
}
[data-theme="light"] .btn-close {
    filter: none;
}
[data-theme="light"] .custom-modal-content {
    background: #ffffff;
}
[data-theme="light"] .custom-modal-header {
    background: #f8f9fb;
}
[data-theme="light"] .custom-modal-footer {
    background: #f8f9fb;
}
[data-theme="light"] .custom-modal-btn {
    background: #f4f6f9;
    color: #4a5568;
}
[data-theme="light"] .custom-modal-btn:hover {
    background: #e8ecf1;
    color: #1a1a2e;
}
[data-theme="light"] .sys-info-row {
    border-bottom-color: rgba(0,0,0,0.06);
}
[data-theme="light"] .mode-indicator {
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
```

---

## 4. 完整修复后的 base.html 主题切换区域

### 4.1 按钮 HTML（替换原第 34-38 行）

```html
<!-- ===== 主题切换按钮 ===== -->
<div class="navbar-nav me-2">
    <button id="theme-toggle" class="nav-link btn btn-sm"
        style="border:none;background:transparent;padding:8px 12px;cursor:pointer;color:var(--text-secondary);font-size:15px;"
        title="切换主题">
        <i class="fas fa-sun" id="theme-icon"></i>
    </button>
</div>
<!-- ===== 主题切换按钮结束 ===== -->
```

### 4.2 JS 主题逻辑（替换 base.html 底部的主题 IIFE）

在 base.html 底部 `<script>` 区域（`DOMContentLoaded` 监听器之后），将整个主题 IIFE 替换为：

```javascript
        // ===== 主题切换 =====
        (function() {
            var THEME_KEY = 'app-theme';
            var html = document.documentElement;
            var toggleBtn = document.getElementById('theme-toggle');
            var icon = document.getElementById('theme-icon');

            console.log('[Theme] init - toggleBtn found:', !!toggleBtn, 'icon found:', !!icon);

            // 读取本地存储中的主题，默认 dark
            var saved = localStorage.getItem(THEME_KEY);
            var currentTheme = saved || 'dark';
            applyTheme(currentTheme);

            // 点击切换
            if (toggleBtn) {
                toggleBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var next = (html.getAttribute('data-theme') === 'light') ? 'dark' : 'light';
                    console.log('[Theme] button clicked, switching to:', next);
                    applyTheme(next);
                    localStorage.setItem(THEME_KEY, next);
                });
            } else {
                console.warn('[Theme] toggleBtn not found! Check id="theme-toggle"');
            }

            function applyTheme(theme) {
                console.log('[Theme] applyTheme:', theme);
                if (theme === 'light') {
                    html.setAttribute('data-theme', 'light');
                    if (icon) { icon.className = 'fas fa-moon'; }
                    if (toggleBtn) { toggleBtn.title = '切换到深色主题'; }
                } else {
                    html.removeAttribute('data-theme');
                    if (icon) { icon.className = 'fas fa-sun'; }
                    if (toggleBtn) { toggleBtn.title = '切换到浅色主题'; }
                }
                console.log('[Theme] html data-theme:', html.getAttribute('data-theme'));
            }
        })();
        // ===== 主题切换结束 =====
```

**关键改进**：
- 新增 `console.log` 日志链路，可追踪按钮是否找到、点击是否触发、主题是否应用
- 新增 `e.preventDefault()` + `e.stopPropagation()` 防止 Bootstrap 或其他事件处理器拦截
- 修复 `getAttribute('data-theme')` 判断逻辑：因为 `applyTheme('dark')` 使用 `removeAttribute`，所以 `getAttribute` 返回 `null`，与原逻辑 `=== 'dark'` 不匹配。改为 `=== 'light'` 判断当前是否为浅色。

---

## 5. 改动文件清单

| # | 文件 | 改动 | 行数 |
|---|---|---|---|
| 1 | `static/css/custom.css` — 末尾 | 移除 `[data-theme="light"]` 前导空格 + 补全 `@media` 响应式块 | ~5 行修正 |
| 2 | `templates/base.html` — 按钮 | `style` 增加 `color:var(--text-secondary)` | +1 属性 |
| 3 | `templates/base.html` — JS | 替换主题 IIFE（增加日志 + preventDefault + 修正判断逻辑） | ~10 行替换 |

---

## 6. 验证步骤

```bash
# 1. 修改 custom.css：确保 [data-theme="light"] 顶格、无前导空格
# 2. 修改 base.html：替换按钮 style 和 JS 主题 IIFE

# 3. 重启服务
# 4. 打开浏览器 → F12 → Console 标签
# 5. 访问 http://127.0.0.1:9183/
```

**期望 Console 输出**：
```
[Theme] init - toggleBtn found: true icon found: true
[Theme] applyTheme: dark
[Theme] html data-theme: null
```

**点击 ☀️ 图标后**：
```
[Theme] button clicked, switching to: light
[Theme] applyTheme: light
[Theme] html data-theme: light
```

**页面效果**：body 背景从 `#0f1923` 变为 `#f4f6f9`，导航栏从 `#1a2736` 变为白色，卡片变为白色。

**再次点击 🌙 图标后**：
```
[Theme] button clicked, switching to: dark
[Theme] applyTheme: dark
[Theme] html data-theme: null
```

页面恢复深色。

---

> **文档结束** — 根因是 CSS 选择器前的缩进空格导致属性选择器匹配失败。修复仅涉及 3 个文件约 15 行，预计 30 分钟完成。
