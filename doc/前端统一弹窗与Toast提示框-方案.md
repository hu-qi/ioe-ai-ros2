# 前端统一弹窗与 Toast 提示框改造方案

- 日期：2026-08-26
- 状态：规划（已批准实施）
- 工程：app_mgr_object-0.2.0(标准版)

---

## 一、现状分析（代码实勘）

### 1.1 已有组件
- **Toast（已统一）**：base.html 全局 `showToast(message, type)`（L90-100）——深色 .toast-item 样式 + 四色左边框（success/error/warning/info），5s 自动消失，`#toast-container` 容器；dashboard.js / control.js 已使用；**alarms.html 未用**；
- **Modal（已有深色样式）**：custom.css `.modal-content/.modal-header/.modal-body/.modal-footer/.btn-close` 已用 CSS 变量深色适配（`--bg-secondary/--border/--card-radius` 等）；
- **control.html 私有弹窗**：`showResultModal(title, content, type)`（L2662，resultModal）、`showConfirmationModal(...)`（L2705）、`showCustomModal(title, content, buttons)`（动态按钮 customModal）——**页面私有，非全局**；
- **alarms.html 隐患**：调用 `showResultModal`（7 处）但**自身无定义**（定义仅在 control.html）→ 触发即 ReferenceError。

### 1.2 原生弹窗清单（需替换，共 8 处）

| 文件:行 | 调用 | 场景 | 替换为 |
|---|---|---|---|
| dashboard.js:700 | `window.confirm(confirmMsg)` | 强制触发任务二次确认（多行：起始仓/目的仓/AGV/货物类型） | AppDialog.confirm（danger） |
| dashboard.js:750 | `alert('任务查询结果：\n' + lines.join('\n'))` | 任务查询结果展示（lines 含 HTML `<b>`） | AppDialog.alert（HTML 内容） |
| dashboard.js:795 | `window.confirm(confirmText)` | confirmTaskControl（取消/重试任务确认） | AppDialog.confirm（异步） |
| alarms.html:462 | `confirm('确定要标记此告警为已解决吗？')` | 解决告警确认 | AppDialog.confirm |
| alarms.html:529 | `confirm('确定要清空所有告警吗？此操作不可恢复！')` | 清空告警确认（危险操作） | AppDialog.confirm（danger） |
| alarms.html:552 | `alert('导出告警功能待实现...')` | 导出告警提示 | AppDialog.alert |
| control.html:1343 | `alert('暂不支持重启 <node>')`（模板字符串生成 onclick） | 节点重启不支持提示 | AppDialog.alert |
| control.html:2229 | `alert('请先选择服务')` | 服务选择校验提示 | AppDialog.alert |

## 二、统一方案

### 2.1 全局弹窗组件 AppDialog（base.html 注入，Promise 风格）

```js
// AppDialog.confirm(opts) -> Promise<boolean>
AppDialog.confirm({ title, message, confirmText, cancelText, danger, icon })
// AppDialog.alert(opts)   -> Promise
AppDialog.alert({ title, message, type: 'info'|'success'|'warning'|'error' })
// AppDialog.prompt(opts)  -> Promise<string|null>
AppDialog.prompt({ title, message, defaultValue, placeholder, confirmText })
```

- 实现：base.html 静态 `#app-dialog` 容器（Bootstrap modal fade 结构）+ 内联 `AppDialog` 对象（单例 Modal 实例复用，`hidden.bs.modal` 触发 resolve）；
- 深色风格：复用现有 modal CSS 变量 + 现有按钮（btn-accent 确认 / btn-outline 取消）；danger 用深色适配的红色按钮；
- 内容区 `\n` → `<br>` 渲染，支持 HTML（任务查询结果）；
- 标题按 type 着色（success/error/warning/info 图标 + 文字色）；
- **同时把 `showResultModal` / `showConfirmationModal` 提升为全局**（base.html），修复 alarms.html 未定义隐患（control.html 保留兼容）。

### 2.2 替换明细（8 处）
- **dashboard.js**：
  - L700 强制触发：`AppDialog.confirm({title:'强制触发任务', message:多行, confirmText:'确认触发', danger:true}).then(ok => { if(!ok){ showToast('操作已取消','info'); 恢复按钮; return; } 执行下发 })`——原同步 return 改为异步 .then 包裹；
  - L750 查询结果：`AppDialog.alert({title:'任务查询结果', message: lines.join('<br>'), type:'info'})`；
  - L795 confirmTaskControl：`AppDialog.confirm({title: 操作名, message: confirmText}).then(ok => { if(!ok){ showToast('操作已取消','info'); return; } API.taskControl(...) })`；
- **alarms.html**：L462/L529 → AppDialog.confirm（L529 danger:true，清空不可恢复）；L552 → AppDialog.alert；
- **control.html**：L1343 模板字符串内 `alert(...)` → `AppDialog.alert({title:'提示', message:'暂不支持重启 '+node.name})`（onclick 字符串引用全局）；L2229 → AppDialog.alert。

### 2.3 Toast 统一规范
- 保持全局 `showToast(message, type)`（深色风格已统一）；
- alarms.html 补用 showToast（部分提示）；纯提示优先 showToast，需要用户确认/重要信息用 AppDialog；
- **约束**：全工程禁止新增原生 `alert/confirm/prompt`（评审把关）。

### 2.4 样式
- 复用现有深色 modal CSS 变量；AppDialog 标题/图标按 type 着色；
- 危险操作按钮：custom.css 补充 `.btn-danger` 深色适配（若当前缺失），确认按钮红色。

## 三、文件改动清单

| 文件 | 改动 |
|---|---|
| templates/base.html | 注入 `#app-dialog` 容器 + `AppDialog` 全局对象（confirm/alert/prompt）+ 提升 showResultModal 全局 |
| static/js/dashboard.js | 3 处原生弹窗 → AppDialog（异步改造 confirmTaskControl/强制触发） |
| templates/alarms.html | 3 处原生弹窗 → AppDialog；showResultModal 未定义由全局注入解决 |
| templates/control.html | 2 处原生弹窗 → AppDialog；showResultModal 保留（兼容） |
| static/css/custom.css | .btn-danger 深色适配（若缺）+ AppDialog 微调 |
| doc/前端统一弹窗与Toast提示框-方案.md | 本文件 |

## 四、验证清单

1. `node --check dashboard.js`；各页面加载无 JS 报错；
2. 逐个触发 8 处场景：确认弹窗（双按钮）/ 信息弹窗（单按钮）/ 危险操作（红色按钮）/ 多行 HTML 内容（任务查询结果）——全部统一深色 modal；
3. alarms 页操作不再 ReferenceError（showResultModal 全局化）；
4. 全页面 grep 无残留原生 alert/confirm/prompt（除注释/字符串模板）→ 板端回归抽查。

## 五、约束与假设

- Bootstrap 5.3 bundle 已含 Modal/Toast，无新依赖；
- confirm 替换为异步 Promise，调用处需 .then 改造（同步 return 语义变化）；
- AppDialog 与现有 showResultModal/showConfirmationModal 并存（兼容），新代码统一用 AppDialog。


---

## 六、实施记录（2026-08-26）

### 已完成改动
| 文件 | 改动 |
|---|---|
| templates/base.html | 注入 `#app-dialog` 容器 + `AppDialog` 全局对象（confirm/alert/prompt，Promise 风格，hidden.bs.modal 兜底 resolve）+ 全局 `showResultModal`（AppDialog.alert 包装，修复 alarms 页无定义隐患） |
| static/js/dashboard.js | ① 强制触发确认 → `AppDialog.confirm`（danger，异步包裹下发）；② 任务查询结果 → `AppDialog.alert`（HTML 内容 lines.join('<br>')）；③ confirmTaskControl → `AppDialog.confirm`（异步） |
| templates/alarms.html | ① 解决告警 → `AppDialog.confirm`；② 清空告警 → `AppDialog.confirm`（danger）；③ 导出提示 → `AppDialog.alert`；showResultModal 由 base 全局注入修复 |
| templates/control.html | ① L1343 模板字符串 alert → `AppDialog.alert`（onclick 生成引用全局）；② L2229 服务选择提示 → `AppDialog.alert` |
| static/css/custom.css | 新增 `.btn-danger` 深色适配（--accent-red，对齐 btn-accent 风格） |

### 验证结果
- `node --check dashboard.js`：OK；
- alarms.html / control.html inline scripts 语法：OK（闭包修复后）；
- 原生弹窗残留：templates 仅剩 base.html 注释中的 API 文档字样（无害），js 零残留；
- .btn-danger 深色样式已补（--accent-red #e74c3c）。

### 板端回归清单（待执行）
1. 部署 5 文件（base.html/dashboard.js/alarms.html/control.html/custom.css），刷新页面无 JS 报错；
2. 逐个触发：强制触发任务确认（红色确认按钮）、任务查询结果（多行 HTML）、取消/重试任务确认、解决/清空告警确认（清空红色）、导出提示、服务选择提示、节点重启不支持提示——全部统一深色 modal；
3. alarms 页解决/清空操作不再 ReferenceError；
4. 各页面 toast（showToast）样式一致。