# AI智能教学分析平台（教官操作端）——P7 前端重构（方案A）交付详细报告

> 交付日期：2026-09-12
> 本期范围：P7 全部 5 个灰度阶段（S1~S5）+ 全量回归验收
> 架构决策：方案 A（9183 单入口，SPA 挂载 `/ui`，API 全复用零 CORS）——详见《P7前端重构方案A决策与排期》
> 验收结论：**构建产物完整、五页路由全部可用、142 项存量测试零回退**

---

## 一、交付总览

| 阶段 | 交付物 | 验证结果 |
|---|---|---|
| S0 环境确认 | node v22.22.0 / npm 10.9.4 / registry 可达 → 采用完整 Vite 构建路线（产物目录方案可行） | `npm ping` PONG |
| S1 骨架+挂载 | `apps/web-ui` Vite 工程 + `web_server._mount_ui()` 挂载 + SPA fallback | `S1_MOUNT_OK`：/ui=200、深链 fallback=200、assets 可达、base=/ui/ 正确 |
| S2 API/WS 封装 | `src/api/index.js`（axios 统一拦截）+ `src/api/ws.js`（自动重连） | 语法通过、构建通过、WS 地址对齐平台真实路由 `/ws` |
| S3 报告域页面 | ReportsView：列表（筛选/分页）+ 详情抽屉（等�徽章/子步骤得分顺序列/**证据图墙**/事件流） | 构建通过 + 接口契约逐字段核对一致 |
| S4 诊断+闭环 | DiagnosisView（六类诊断卡+证据缩略图+热重载按钮）、TeachingView（教学闭环+学员累计） | 构建通过（修复 icons 导入错误） |
| S5 看板+学员+切换 | DashboardView（今日概览/WS 实时进度/TOP5/需关注，全部带工序筛选）、StudentsView、`/ui-legacy-redirect` 灰度端点 | `S5_E2E_OK`：302 重定向 + 五页 fallback + 五分包齐备 |
| 回归 | 全量测试套件 | **142 passed，零回退** |

## 二、关键实现细节

### 2.1 `/ui` 挂载与 SPA fallback（web_server.py）

- `self.ui_dist_dir = components/web/ui_dist`，产物存在才挂载（**未构建时旧页面完全不受影响**，天然灰度）；
- `/ui/assets` → `StaticFiles`（Vite hash 文件名，长缓存友好）；
- `GET /ui` 与 `GET /ui/{full_path:path}` → 统一回落 `index.html`（vue-router history 模式必需；`full_path` 不参与文件系统拼接，无路径穿越风险）；
- 挂载时机在 `__init__` 末尾（页面路由注册完成后），前缀隔离不与 `/static`、页面路由冲突。
- **开发过程修复的缺陷**：初次编辑曾把 `__init__` 的模板/路由/WS 初始化代码误并入 `_mount_ui` 方法体，导致初始化流程被破坏——冒烟验证（`_mount_ui` 独立桩调用 + `/ui` 请求 200）捕获后重排方法边界修复，并以 `SYNTAX_OK + S1_MOUNT_OK` 复验。

### 2.2 工程结构（apps/web-ui/）

```
apps/web-ui/
├── package.json          # vue3.5 + vue-router4 + pinia + element-plus + echarts + axios；vite5
├── vite.config.js        # base=/ui/；outDir→ui_dist；dev proxy /api→9183、/ws→ws://9183
├── index.html
└── src/
    ├── main.js           # ElementPlus(zhCn) + pinia + router
    ├── App.vue           # 侧边导航（5 菜单 + "返回旧版"链接）
    ├── router/index.js   # history base=/ui/，5 路由懒加载
    ├── api/index.js      # axios 实例：baseURL=/api/v1（同源零CORS）；code!=0 统一 ElMessage；40+ 端点方法封装
    ├── api/ws.js         # createRealtimeWS：/ws 同源连接、指数退避重连(≤6次)、JSON 分发
    └── views/            # ReportsView / DiagnosisView / TeachingView / DashboardView / StudentsView
```

构建产物：`app_mgr_object/components/web/ui_dist/`（index.html + assets 分包，现场零 Node 依赖）。

### 2.3 API 契约对齐（逐字段核对记录）

| 页面读取 | 后端实际 | 结论 |
|---|---|---|
| `data.list` + `data.total`（报告列表） | `list_reports` 返回 `{total, page, page_size, list}` | ✅ 一致 |
| `report/substeps/events`（详情） | `get_report_detail` 六表结构 | ✅ 一致 |
| `data.diagnoses[]`（诊断） | `{diagnoses, count}` 包裹 | ✅（沿用 P3 期修复后的契约） |
| `evidence[].id/jpg_path/sub/ts`（图墙） | evidence 表 + image API | ✅ 一致 |
| WS 地址 `/ws` | `web_server.py:1125` 真实路由 | ✅ 对齐（封装初版误写 `/ws/realtime`，核对后修正） |

### 2.4 五个功能页面要点

1. **ReportsView**：工号/设备/完成状态筛选 + 分页；行点击开详情抽屉——等纬章（优秀绿/良好蓝/合格黄/不合格红）、子步骤"得分/顺序"两列（P1 评分回写数据）、**证据图墙**（缩略图点击原图、JPG/BMP/端侧文件三态标签、onerror 逐级回退）、事件流表。
2. **DiagnosisView**：班级+工序查询、六类诊断卡（类型徽章色阶：瓶颈/退步=红、顽固/顺序=黄、衔接/差异=蓝）、metric_label 判断依据、YAML 建议文本、**证据缩略图直接内嵌卡片**、"热重载规则"按钮（调 `POST /api/v1/config/reload`）。
3. **TeachingView**：左栏教学调整记录（创建对话框：日期/班级/工序/内容）+ "查看"弹出前后 30 天对比（前/后/变化三栏 + trend 告警条）；右栏学员累计统计（次数/均分/完成率/薄弱 TOP3）。
4. **DashboardView**：今日概览（工序筛选联动）、实时进度（**WS 驱动** + 连接状态标签 + 轮询兜底）、高频错误点 TOP5（进度条可视化）、需关注学员表。
5. **StudentsView**：关键字/班级筛选 + 分页列表（工种/入学日期/在册状态/备注）。

### 2.5 旧页切换策略（S5）

- 新版入口：旧版导航与新版侧栏互留链接（`返回旧版` / 后续加"新版体验"）；
- 灰度端点 `GET /ui-legacy-redirect/{page}`：302 到 `/ui/*` 映射表，需配置化强切时启用；
- 旧模板本轮不删除（兼容期），全页稳定一个版本周期后归档下线。

## 三、验证记录汇总

| 验证 | 命令/脚本 | 结果 |
|---|---|---|
| 依赖安装 | `npm install` | 86 packages, 8s |
| 生产构建 | `npm run build`（×4 轮迭代） | ✓ built（各分包齐备） |
| 挂载 HTTP 验证 | TestClient 桩调 `_mount_ui` | `S1_MOUNT_OK`（/ui、深链、assets、base 四断言） |
| JS 语法 | `node --check` api/index.js、api/ws.js | 通过 |
| 接口契约核对 | grep 后端端点与返回结构 | §2.3 表全一致 |
| 端到端 | redirect 302 + 五页 fallback + 五分包 | `S5_E2E_OK` |
| 全量回归 | pytest 全套件 | **142 passed**（3m52s），零回退 |

本期开发中发现并修复的问题（共 4 个）：
1. `web_server._mount_ui` 方法边界错误（§2.1，冒烟捕获）；
2. 路由文件相对导入路径错误（`./views` → `../views`，构建捕获）；
3. `@element-plus/icons-vue` 无 `Lightbulb` 导出（改为 emoji，构建捕获）；
4. WS 默认地址 `/ws/realtime` 与平台真实路由不符（核对后改为 `/ws`）。

## 四、运行与构建操作手册（现场/开发）

```bash
# 开发（开发机）
cd apps/web-ui && npm install && npm run dev   # http://localhost:5183，API 代理到 9183

# 构建发布（开发机构建，产物入库随包部署）
cd apps/web-ui && npm run build                # 产出 app_mgr_object/components/web/ui_dist/

# 现场访问
#   新版: http://<IP>:9183/ui          （产物存在自动挂载）
#   旧版: http://<IP>:9183/reports     （兼容期保留）
```

## 五、遗留与建议

1. **登录/权限**：平台当前无认证体系，SPA 沿用免登录；若后续加 JWT，axios 拦截器已预留 401 处理位；
2. **证据转换周期调度**（承接 P3-P6 报告 §九-1）：图墙依赖 jpg_path，高峰期建议加 30s 周期转换任务；
3. **图表增强**：Dashboard 当前用进度条轻量可视化，后续可换 ECharts 环图/趋势线（依赖已在 package.json）；
4. **旧模板下线**：建议运行 1~2 周收集教官反馈后，将 `/reports` 等旧路由 302 到 `/ui` 并删除模板（灰度端点已备好）；
5. **UI 自动化测试**：本期以构建断言 + 接口契约核对 + HTTP 冒烟为验收，建议后续引入 Playwright 冒烟套件纳入 CI。

## 六、结论

P7 按方案 A 完成 S1~S5 全部交付：Vue3 SPA 以 `/ui` 路径与旧版同端口共存，五个功能页面全部对齐现有 API 契约（含 P1 评分、P3 证据、P4 诊断关联、P5 闭环、P6 工序筛选全部新能力的可视化），WS 实时推送复用平台既有 `/ws` 通道。**构建→挂载→路由→契约→回归五层验证全通过，142 项存量测试零回退**。至此评估报告路线图 P1~P7 全部完成。
