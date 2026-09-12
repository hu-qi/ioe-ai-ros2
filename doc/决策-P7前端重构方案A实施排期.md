# AI智能教学分析平台（教官操作端）——P7 前端重构架构决策与实施排期

> 日期：2026-09-12
> 决策状态：**已定案（方案 A）**
> 决策人：产品/开发共同确认（2026-09-12 会话）
> 关联文档：《010203文档变更评估报告-详细版》§四 P7、《P3-P6开发交付详细报告》§九

---

## 一、决策结论

**P7（Vue3 前端重构）采用方案 A：同端口、路径隔离、API 复用——不新建独立端口/入口。**

| 项 | 结论 |
|---|---|
| 入口 | 维持现有 **9183 单入口**（FastAPI），不新增进程/端口 |
| 新前端挂载 | Vue3 SPA 构建产物挂载于 **`/ui`** 路径前缀 |
| API | 新旧页面**共用现有 `/api/v1/*` 全部端点，零改动、零 CORS** |
| 灰度 | 路径级共存（旧 `/reports` vs 新 `/ui/reports`），逐页切换，每步可独立回退 |
| 淘汰旧前端 | 全部页面迁移并稳定运行后，下线 `templates/` 旧页（保留回滚分支） |

### 1.1 否决方案 B（独立端口）的理由

现场为**单进程 FastAPI + 无 nginx/网关 + 离线部署**形态，独立端口（如 9184）将引入三重成本而无收益：

1. **CORS**：跨端口即跨域，必须为全部 API 配 CORS 或引入反向代理（现场无 nginx，需额外装包开端口）；
2. **运维**：多 1 个进程 + systemd 自启 + 防火墙端口，离线部署面（deploy-app-mgr 流程）多一份出错点；
3. **回滚**：两套入口并存易混淆，回退需改入口配置；而方案 A 路径级共存可即时切回。

02 技术方案仅规定前端技术栈（Vue3 + Element Plus + ECharts + Vite 5），**未规定独立端口**——方案 A 与文档完全兼容。

---

## 二、目标架构（运行期）

```
9183 (现有 FastAPI，唯一入口，systemd 单服务不变)
├── /static          现有 JS/图片资源（不动，旧页面继续使用）
├── /ui              Vue3 SPA 入口（dist/ 挂载，history 路由 fallback 到 /ui/index.html）
├── /ui/assets/*     Vite 打包静态资源（hash 文件名，长缓存）
└── /api/v1/*        现有全部 API（新旧共用）+ WebSocket（同源 ws://host:9183）
```

### 2.1 工程结构

```
apps/web-ui/            # Vite 工程源码（开发期用，现场不需要 Node）
├── src/
│   ├── api/            # API 封装（axios 实例，baseURL=/api/v1，同源相对路径）
│   ├── router/         # vue-router（history 模式，base=/ui/）
│   ├── views/          # 页面：reports/ students/ dashboard/ diagnosis/ teaching/
│   └── main.js
├── vite.config.js      # build.outDir 指向挂载目录; dev server proxy → localhost:9183
└── package.json
app_mgr_object/components/web/ui_dist/   # 构建产物（部署物，现场直接挂载）
```

### 2.2 挂载实现要点（约 20 行代码）

- `app.mount("/ui/assets", StaticFiles(directory=ui_dist/assets))`；
- SPA fallback：`GET /ui/{path}` 未命中静态文件时返回 `ui_dist/index.html`（Vue history 路由必需）；
- 导航模板加"新版体验"入口链接到 `/ui/`。

---

## 三、实施排期（5 步灰度，每步独立可验证/可回退）

| 步骤 | 内容 | 交付/验证 | 预估 |
|---|---|---|---|
| **S1 工程骨架** | Vite + Vue3 + vue-router + Element Plus + ECharts 按需引入；`/ui` 挂载 + SPA fallback；导航入口 | 访问 `/ui/` 出空壳首页；`GET /ui/reports` 刷新不 404 | 1 天 |
| **S2 API 层与登录态** | axios 封装（同源 baseURL、错误统一 Toast、401 处理）；复用现有 WS 封装 | 用真实 9183 联调 reports 列表接口通 | 1 天 |
| **S3 首批页面：报告域** | 报告列表 + 详情（等级徽章/得分/顺序列/**证据图墙**）——功能最重、旧版最弱的页 | 与旧页并排验证数据一致性；证据缩略图/原图可用 | 2 天 |
| **S4 二批页面：诊断与闭环** | 诊断中心（六类卡片+证据）、教学闭环（记录+验证报告）、学员累计 | 诊断 API 六类结果渲染；verify 趋势展示 | 2 天 |
| **S5 三批页面：看板与学员 + 切换** | 教学看板（今日概览/TOP5/需关注/实时进度 WS）、学员管理；旧页路由重定向到 `/ui`；旧模板归档 | 全页回归 checklist（双主题→新版主题统一）；WS 实时推送验证 | 2 天 |
| 合计 | — | — | **~8 个工作日** |

**验收标准**（每步通用）：功能与旧页对齐；`test/` 全量 142 项不回退（后端未动的保证）；新增前端用例以手动 checklist + 关键接口 smoke 脚本记录到文档。

## 四、技术栈定版

| 项 | 选型 | 说明 |
|---|---|---|
| 框架 | Vue 3.4+（Composition API，`<script setup>`） | 02 方案 |
| 构建 | Vite 5 | 02 方案；产物 hash 化利于缓存 |
| UI 库 | Element Plus（按需自动导入 unplugin） | 02 方案 |
| 图表 | ECharts 5（按需注册，与看板现有图表对齐） | 02 方案 |
| 路由 | vue-router 4（history，base=/ui/） | — |
| HTTP | axios（同源相对路径，无跨域配置） | 方案 A 关键收益 |
| 状态 | Pinia（仅主题/用户偏好等轻状态） | 避免过度设计 |
| 适配 | 触屏（Element 尺寸 + 点击目标 ≥44px）；深浅主题 CSS 变量沿用现有色板 | doc/37/66 成果迁移 |

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| Node 构建环境在开发机之外不可得 | 构建仅开发期需要；CI/本地构建后提交 `ui_dist/` 产物，现场零 Node 依赖 |
| `/ui` 与现有 `/static`、页面路由冲突 | 挂载前缀隔离；FastAPI 路由注册顺序把 `/ui` mount 放在页面路由之后 |
| WS 推送在新页面重复接入踩坑 | S2 先做 WS 复用验证，dashboard 页直接迁移现有 `websocket.js` 协议 |
| 双主题视觉回归量大 | 新版统一用 Element Plus 主题 + 现有 CSS 变量映射表，深浅两套各过一遍 checklist |
| 旧页长期共存造成维护负担 | S5 完成即冻结旧模板（只修致命 bug），一个版本周期后删除 |
| 证据图接口依赖（/api/v1/evidence/*） | S3 前该接口已上线并有 5 项测试兜底（P3 交付），无阻塞 |

## 六、本期不做

- 独立前端站点/CDN（决策 B 否决）；
- SSR/Nuxt（内网工具页无 SEO/首屏诉求）；
- 微前端（单团队单应用，复杂度不划算）；
- 移动端 App 化（触屏 Web 已覆盖教官场景）。
