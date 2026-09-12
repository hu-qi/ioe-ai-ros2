# AI智能教学分析平台（教官操作端）——P3~P6 开发交付详细报告

> 交付日期：2026-09-12
> 本期范围：评估报告（详细版）§四路线图的第 3~6 步 + 第 7 步 Web 初版：
> **P3 证据管理增强 / P4 诊断关联证据 / P5 教学改进闭环 / P6 看板工序维度 / Web 初版页面**
> 前置：P1 单轮评分引擎、P2 诊断规则 YAML 化已于上一轮交付（19+12 项测试）。
> 架构路径：决策 1 路径 A（现有平台补齐）；评分模型：决策 2 纯四系数；规则数据源：决策 3 完全 YAML 驱动。

---

## 一、交付总览

| 阶段 | 交付物 | 核心文件 | 测试 |
|---|---|---|---|
| P3 | evidence 元数据表 + 双路幂等写入 + BMP→JPG/缩略图转换 + 证据 API | `reports_schema.sql`、`report_repo.py`、`evidence_converter.py`、`report_recv_plugin.py` | 5 项 |
| P4 | 诊断结果关联证据图 | `analysis_repo.py`、`diagnosis_engine.py` | 并入 P3/P6 验证 |
| P5 | teaching_actions 表 + CRUD/改进验证接口 | `analysis_schema.sql`、`analysis_repo.py`、`report_analysis_plugin.py` | 5 项 |
| P6 | 统计/看板 7 个端点工序筛选 | `analysis_repo.py`、`dashboard_repo.py`、两个插件 | 冒烟 + 回归 |
| Web | 报告详情页增强 + 诊断中心页（初版） | `reports.html/js`、`diagnosis.html/js`、`base.html`、`web_server.py` | 渲染 + API 链路 |
| **合计** | — | — | **全量 142 passed** |

---

## 二、P3 证据管理增强

### 2.1 数据模型（reports_schema.sql 新增 evidence 表）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| device_id / round_start_ms / sub / ts | TEXT/INTEGER | **幂等四元组**（dev01 §2.3），UNIQUE 约束 |
| file_path | TEXT | BMP 原图路径 |
| jpg_path / thumb_path | TEXT | 转换产物路径（空=未转换） |
| file_size | INTEGER | BMP 字节数 |
| keep_forever | INTEGER | 永久保留标记（90 天清理预留，本期未启用清理任务） |
| created_at | INTEGER | 入库时刻 epoch ms |

配套索引：`idx_evidence_round(device_id, round_start_ms)`、`idx_evidence_sub`。
注意：AUTOINCREMENT 引入 SQLite 内部表 `sqlite_sequence`，存量建表断言用例已同步修正（排除 `sqlite_` 前缀内部表）。

### 2.2 双路写入（幂等去重）

| 通道 | 触发 | 实现 |
|---|---|---|
| 实时通道 | `POST /api/v1/evidence` multipart 收件 | `save_evidence` 落盘 BMP → `insert_evidence_meta`（INSERT OR IGNORE），响应含 `new` 标记 |
| 整包兜底 | `POST /api/v1/reports` 的 `round.evidence[]` | 逐条登记元数据（file 为端侧绝对路径，平台不读该文件，仅作关联记录）；异常不阻塞整包入库 |

重复到达（同幂等键）返回成功但不再重复入库/落盘重复元数据——符合 dev01 §2.3"平台须去重但不拒绝"。

### 2.3 BMP→JPG 异步转换（evidence_converter.py）

- `EvidenceConverter.convert_pending(limit)`：批量取 `jpg_path IS NULL` 记录转换，返回 `(converted, skipped, failed)`；
- 产物：`sub_N_ts_T.jpg`（quality=85）+ `sub_N_ts_T_thumb.jpg`（最长边 240px）；
- **端侧路径登记记录**（file_path 不存在）→ 记为 `skipped` 并回写空 jpg_path，避免反复重扫，不计失败；
- Pillow 10.2.0（环境已具备）；同步实现，由调用方决定执行线程（本期在接收后同步触发 + 后续可挂周期任务）。

### 2.4 证据 API（report_recv_plugin，端点总数 9→11）

| 端点 | 说明 |
|---|---|
| `GET /api/v1/evidence?device_id=&round_start_ms=&sub=&limit=` | 元数据列表（limit 上限 500；缺 device_id → 422） |
| `GET /api/v1/evidence/{id}/image?thumb=1` | 图片访问：thumb=1 缩略图，默认 JPG 展示图；未转换回退 BMP 原图（media_type 自适应）；无文件 → 404（端侧登记记录） |

### 2.5 验证记录

- 元数据幂等/回写/待转换列表：`EVIDENCE_META_OK`；
- 转换批次：真实 BMP（640×480）→ JPG(640×480) + 缩略图(240×180)，批次 `1/1/0`；
- HTTP 级：列表/JPG magic(FF D8)/thumb/双 404 全通过；
- 正式测试 `test/scoring/test_evidence_p3.py`：5 passed。

---

## 三、P4 诊断结果关联证据图

### 3.1 关联链设计

```
诊断结果 target_id = "step_N"
    └─ evidence.sub = N
       ∧ evidence.device_id = reports.device_id
       ∧ evidence.round_start_ms = reports.start_ms
       ∧ reports 命中班级/工序/时间过滤
```

### 3.2 实现

- `AnalysisRepo.get_evidence_for_sub(sub, filters, limit=3)`：JOIN 查询 + `DISTINCT` 去重（多报告共享同一 device_id+round 时避免证据重复展开）+ `has_image` 现存性判定；
- `DiagnosisEngine._attach_evidence()`：`diagnose_all` 收尾为全部 step 级结果挂 `evidence` 字段（最多 3 张；无证据 → 空数组而非缺字段；关联异常仅告警不中断诊断）。

### 3.3 验证记录

`P4_EVIDENCE_ATTACH_OK`：bottleneck 结果带图 1 张（has_image=True）；全部结果含 evidence 字段；空班证据为空数组；去重后不重复。

---

## 四、P5 教学改进闭环

### 4.1 数据模型（analysis_schema.sql 新增 teaching_actions 表）

`id / action_date(epoch ms) / description / target_substep(可空) / process_name(空=通用) / class_name / created_at`，索引：class、process。

### 4.2 Repo 层（analysis_repo.py）

- `create_teaching_action` / `get_teaching_action` / `list_teaching_actions`（倒序、班级/工序过滤）；
- `verify_teaching_action(action_id, pass_threshold)`：**前后各 30 天等长窗口**对比班级指标——平均分 / 完成率（finish_reason=completed 占比）/ 通过率（total_score≥线占比）/ 报告数；支持按工序过滤；输出 `{action, before, after, delta, trend}`，trend ∈ `improved / declined / mixed / no_data`（任一侧无数据 → no_data）。

### 4.3 HTTP 接口（report_analysis_plugin，端点 5→8）

| 端点 | 说明 |
|---|---|
| `POST /api/v1/teaching_actions` | 创建（缺 description/class_name → 422） |
| `GET /api/v1/teaching_actions?class_name=&process_name=&limit=` | 列表（limit 上限 200） |
| `GET /api/v1/teaching_actions/{id}/verify` | 改进效果验证（不存在 → 404） |

### 4.4 验证记录

端到端数据链：调整前 3 份低分（timeout/manual，均分 52.3）→ 调整后 3 份高分（completed，均分 79）→ `delta.avg_score=+26.7, trend=improved`；create/list/verify/422/404 全通过；
正式测试 `test/scoring/test_teaching_actions_p5.py`：5 passed（含 no_data、missing action 用例）。

---

## 五、P6 看板/统计工序维度

### 5.1 端点改造（7 个端点新增 `process_name` 查询参数）

| 插件 | 端点 | repo 方法 |
|---|---|---|
| analysis | `GET /api/v1/analysis/step_duration` | filters 透传（缓存 key 自动含工序） |
| analysis | `GET /api/v1/analysis/student_cumulative` | `get_student_cumulative_stats(+process_name)` |
| analysis | `GET /api/v1/analysis/class_summary` | `get_class_summary(+process_name)` |
| analysis | `GET /api/v1/analysis/diagnosis` | （P2 已加） |
| dashboard | `GET /api/v1/dashboard/today_summary` | `get_today_summary(+process_name)`，SQL 参数化 `r.process_name = ?` |
| dashboard | `GET /api/v1/dashboard/top_error_points` | `get_top_error_points(+process_name)`，聚合与总报告数两处均过滤 |
| dashboard | `GET /api/v1/dashboard/improvement_validation` | `get_improvement_validation(+process_name)` |

设计取舍：全部为**可选参数（空=全部工序）**，存量调用零破坏；未引入 APScheduler（现有 TTL 缓存 + WS 推送满足毫秒级读取目标，评估报告 §四 P6 决策维持）。

### 5.2 验证记录

- 分析侧 `P6_ANALYSIS_FILTER_OK`：混合工序 summary 均值 71.2 → 按拆解过滤 52.3 / 组装 90.0；step_duration report_count 6→3；
- 看板侧 `P6_DASHBOARD_FILTER_OK`：today_summary 均值 all=70.8 / 拆解=52.5 / 组装=89.0；improvement_validation 参数化通过；422 校验不回退。

---

## 六、Web 初版页面

### 6.1 报告详情页增强（reports.html / reports.js）

| 增强 | 说明 |
|---|---|
| 等级徽章 | `d-grade`：优秀=绿 / 良好=蓝 / 合格=黄 / 不合格=红，无评分隐藏 |
| 子步骤表 2 新列 | 得分（P1 回写 `score`）、顺序（`sequence_error` 1=红"错误" / 0="正确" / 空="-"） |
| 证据抓拍区 | `d-evidence`：按 device_id + round.start_ms 拉取 `GET /api/v1/evidence`，缩略图(96px)点击看原图；已转 JPG=绿标 / 未转=BMP 灰标 / 端侧登记记录=占位卡；onerror 兜底"图片不可用" |

### 6.2 诊断中心页（新增 /diagnosis）

- `templates/diagnosis.html` + `static/js/diagnosis.js`，base.html 导航新增"诊断中心"（听诊器图标）；
- 查询条件：班级（文本，空=全部）+ 工序（下拉：全部/拆解/组装），回车或按钮触发；
- 结果卡片：类型徽章（六类中英文映射 + 图标 + 颜色分级：bottleneck/regression=红、persistent_error/sequence_chaos=黄、interval/stddev=蓝）+ target + 工序标 + metric_label（判断依据数值）+ advice_text（YAML 建议）+ **关联证据缩略图（72px，点击原图）**；
- 空结果提示条；错误走统一 AppDialog。
- 修复记录：初版 JS 误按裸数组解析 `d.data`，实际端点返回 `{diagnoses, count}` 包裹——验证环节捕获后已修复。

### 6.3 路由与导航

`web_server.py` 新增 `GET /diagnosis` 页面路由（模板渲染，风格与 /dashboard 一致）。

### 6.4 验证记录

`WEB_PAGES_OK`：证据 API 链路（列表 + thumb JPEG）+ 诊断 API（bottleneck 带证据 1 张）+ `diagnosis.html` / `reports.html` / `base.html` Jinja2 渲染断言（关键 DOM id 与 JS 引用齐备）；`node --check` 两份 JS 语法通过。

---

## 七、全量回归验收

| 套件 | 数量 | 结果 |
|---|---|---|
| test/report_recv（接收链路 + 建表断言） | 31 | ✅ |
| test/test_student_api + test_student_repo | 39 | ✅ |
| test/test_diagnosis_engine + test_analysis_repo | 33 | ✅ |
| test/scoring（P1 评分 19 + P2 规则 12 + P3 证据 5 + P5 闭环 5 + 冒烟 2 归并） | 41 | ✅ |
| **合计** | **142** | **全部通过，存量无回退** |

回归期间修复的存量用例适配（非产品缺陷）：
1. `test_six_tables_created`：evidence 表加入 → 表清单期望更新；AUTOINCREMENT 引入 `sqlite_sequence` → 断言排除 `sqlite_` 内部表。

本期开发中发现并修复的产品缺陷：
1. `diagnosis.js` 响应结构解析错误（见 §6.2）；
2. `get_evidence_for_sub` JOIN 重复展开（DISTINCT 去重，见 §3.2）；
3. `diagnosis.html` 一处闭合标签笔误（`</card>` → 移除，渲染断言覆盖）。

---

## 八、接口清单增量（本期新增/变更汇总）

```
新增:
  GET  /api/v1/evidence                                    证据元数据列表
  GET  /api/v1/evidence/{id}/image?thumb=0|1               证据图访问（JPG/缩略图/BMP 兜底）
  POST /api/v1/teaching_actions                            创建教学调整事件
  GET  /api/v1/teaching_actions                            调整事件列表
  GET  /api/v1/teaching_actions/{id}/verify                改进效果验证
  GET  /diagnosis                                          诊断中心页
变更（向后兼容，均新增可选参数 process_name）:
  GET  /api/v1/analysis/step_duration|student_cumulative|class_summary
  GET  /api/v1/dashboard/today_summary|top_error_points|improvement_validation
  GET  /api/v1/analysis/diagnosis                          响应新增 evidence[] 字段
  POST /api/v1/evidence                                   响应语义不变；元数据入库幂等
  POST /api/v1/reports                                    round.evidence[] 元数据登记
```

## 九、遗留与建议

1. **证据转换调度**：当前为收件后同步单批转换；建议后续挂 30s 周期任务（复用现有插件线程池模式）覆盖高峰积压；
2. **90 天证据清理**：表已备 `keep_forever` 字段，清理任务建议下期实现（dry-run 模式先行，评估报告 §七风险条款）；
3. **std_duration_ms 数据源打通**：评分 YAML 中的标准用时已入库 report_substeps，后续可与 report_analysis_plugin 的 SOP 加载器合并为单一来源；
4. **诊断中心页增强方向**：时间范围筛选、诊断结果持久化列表翻页（`diagnosis_results` 表已具备）、学员退步卡片直连学员详情页；
5. **端侧联调**：`/api/v1/evidence` 列表与图片接口建议纳入 dev01 文档"平台辅助接口"一节（§8），供端侧调试核对证据归属。

## 十、结论

本期按评估报告路线图完成第 3~7 步全部交付：证据链路（落盘→元数据→转换→展示）端到端贯通，教学闭环（记录→前后对比→趋势判定）可用，全部统计/看板具备工序维度，Web 初版覆盖教官高频操作（查报告看图、跑诊断、看建议）。**全量 142 项测试通过，存量零回退**。路线图仅剩 P7（Vue3 重构）按既定决策不列入本期。
