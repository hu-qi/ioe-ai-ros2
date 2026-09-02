# AGV状态卡改造与工作时间/节假日设置-技术规划方案

> 状态：规划中（2026-08-27 提交审核，未实施）
> 产品经理（统计展示建议）+ 开发专家（技术方案）

## 一、需求
1. **顶部 AGV 简单状态**：部署模式下，顶部 AGV 信息区显示**两台 AGV** 的简单状态（可用状态/任务状态）；
2. **仓位区域下方 AGV 状态卡 → 任务信息栏**：统计信息——今日完成任务数 / 执行中任务数 / 异常数量；**数字突出白色加粗、指标名称小号字体**；
3. **工作时间/节假日设置**：AGV 当前见货即执行；需可设置日常与节假日工作；分析触发机制（已含工作时间约束）→ 提供「启用工作时间条件」开关 + 弹窗日历设置节假日与工作日工作范围。

## 二、现状实勘
- **顶部**：system-bar（index.html L18-27）有 sys-dot-agv + sys-agv（仅状态点/数字，无两台 AGV 明细）；sys-mode 显示「开发/部署模式」（dashboard.js L471）；
- **仓位下方 AGV 卡**：index.html L107-112 agv-cards 卡片；dashboard.js renderAgvCards（L230-251）显示每台 AGV 的 id/status/电量/当前任务——将改为任务信息栏；
- **任务统计**：business_collector.get_task_statistics（L206-223）仅返回活动实例 by_status + total；**无今日完成/异常统计**（需从任务历史 DB 统计，get_task_history 含 completed_at/failed）；前端当前无统计卡片；
- **工作时间机制**：schedule_checker.py（day_of_week/start_time/end_time/enabled，无配置默认允许）+ smart_trigger_plugin 扫描门控（L182/L288 is_in_working_window）——**已生效**；work_schedule 在 smart_trigger.yaml（JSON 列表，schedule 级 enabled 已有，无全局开关/节假日）；
- **AGV 状态源**：/api/agv/status 返回 robots[{robot_id, status(AVAILABLE/…), battery, current_task_id}]（L1346 下拉只取 AVAILABLE）；robot_ids 配置 [1001,1002]。

## 三、AGV 状态卡改造方案
### 3.1 顶部部署模式 AGV 信息（两台 AGV 简单状态）
- sys-bar 的 AGV 项扩展为「AGV1 · 可用 | AGV2 · 任务中」双状态（图标 + 状态点 + 文字 + 电量）；
- 仅两台（robot_ids 配置），部署模式显示；开发模式保持现状（sys-agv 数量）；
- 数据源：/api/agv/status → robots 映射 robot_id 1001/1002；状态归一：AVAILABLE=可用（绿点）、非 AVAILABLE/有 current_task=任务中（蓝点）、offline=离线（红点）。

### 3.2 仓位下方任务信息栏（替代 AGV 状态卡）
| 统计项 | 数据源（后端扩展） | 展示 |
|--------|------------------|------|
| 今日完成任务 | 任务历史 DB 按 created_at/completed_at=今日 且 status=completed 计数 | 白色加粗大号数字 |
| 执行中任务 | get_task_statistics by_status（running/calling_rcs/monitoring 等非终态） | 白色加粗大号数字 |
| 异常数量 | 任务历史 DB status=failed（今日）或 recent_failures 计数 | 白色加粗大号数字（红色点缀） |
- **展示样式**：三列统计卡（大数字 20px/700 白色，指标名 11px text-secondary 小号），深色卡片背景；
- 后端：business_collector.get_task_statistics 扩展返回 today_completed / executing / failed（从 workflow_engine DB 查询）；前端 renderTaskStats 渲染；
- 产品经理建议：异常数用琥珀/红色数字区分；执行中数字带脉冲点动画；统计随 WS business_update 刷新。

## 四、工作时间/节假日设置方案
### 4.1 机制确认
- 已存在：work_schedule（smart_trigger.yaml）+ ScheduleChecker.is_in_working_window + 扫描门控（生效）；schedule 级 enabled 已有；
- 缺口：无**全局启用开关**；无**节假日**概念（只按星期几+时段）；无可视化配置界面。

### 4.2 配置扩展（work_schedule）
```yaml
work_schedule:
  enabled: true                # 全局开关：false=不启用工作时间条件（AGV 见货即执行，现状）
  holidays: ["2026-01-01", "2026-10-01"]   # 节假日日期（当天不调度）
  schedules:                   # 工作日/周末时段（既有格式）
    - { day_of_week: mon-fri, start_time: "08:00", end_time: "18:00", enabled: true }
    - { day_of_week: sat,     start_time: "00:00", end_time: "23:59", enabled: true }
```
### 4.3 后端扩展
- ScheduleChecker：
  1. 全局开关：work_schedule.enabled=false → is_in_working_window 恒 True（兼容现状）；
  2. 节假日：holidays 含今天（YYYY-MM-DD）→ 返回 False（不调度）；
  3. 保持 schedule 级 enabled/时段匹配；
- config_manager：work_schedule 校验扩展（enabled bool、holidays 日期列表、schedules 字段保留）；path_map 已指向 smart_trigger.work_schedule；
- smart_trigger.yaml 默认加 enabled: true + holidays: []（保持现行为）；web_monitor _apply_work_schedule 已热加载（set_schedules → 需透传 enabled/holidays 给 ScheduleChecker）。

### 4.4 前端日历弹窗（工作时间设置）
- 入口：任务信息栏或页头「工作时间」按钮；
- 弹窗内容：
  1. **启用开关**：切换「启用工作时间条件」（保存 work_schedule.enabled）；
  2. **日历**（月视图）：可点击标记**节假日**（红色圆点，多选/取消）；
  3. **工作日时段表**：每日（周一~周日）可设 start/end 时段（时间 input）或「休息」（enabled=false）；
  4. 保存 → setWorkSchedule（PUT /api/config/schedule 扩展）→ 热加载 + toast；
- 数据流：getConfigAll 或 getScheduleConfig → 渲染日历/时段表 → 保存写 work_schedule（yaml 热加载 ScheduleChecker）。

## 五、改动清单（审批后实施）
| 文件 | 改动 |
|------|------|
| plugins/smart_trigger_plugin.py | work_schedule 解析透传 enabled/holidays 给 ScheduleChecker（或 set_schedules 扩展参数） |
| components/trigger/schedule_checker.py | 全局开关 + 节假日日期判断 |
| components/web/business_collector.py | get_task_statistics 扩展：today_completed / executing / failed（DB 统计） |
| components/web/config_manager.py | work_schedule 校验扩展（enabled/holidays） |
| config/plugin_configs/smart_trigger.yaml | 默认 work_schedule 加 enabled/holidays |
| templates/index.html | 顶部 sys-bar AGV 双状态；AGV 卡区域 → 任务信息栏（3 统计卡 + 工作时间按钮）；日历弹窗 |
| static/js/dashboard.js | 顶部 AGV 状态渲染；renderTaskStats；日历弹窗逻辑（标记节假日/时段表/保存） |
| static/css/custom.css | 统计卡样式（大数字/小号指标名）、日历样式 |
| doc/AGV状态卡改造与工作时间设置-技术规划方案.md | 本方案 |

## 六、测试验证
**后端**：
1. ScheduleChecker：全局开关 false 恒放行；节假日日期不放行；工作日时段匹配；
2. get_task_statistics：today_completed/executing/failed 计数正确（mock DB）；
3. config_manager work_schedule 校验（enabled bool/holidays 日期格式）；py_compile。
**前端**：
1. 顶部两台 AGV 状态（可用/任务中/离线）渲染正确；
2. 任务信息栏三统计卡显示（数字加粗白/指标名小号灰）；
3. 日历弹窗：标记节假日、设时段、保存热加载；node --check。
**板端回归**：AGV 状态卡变任务信息栏；统计随任务实时刷新；工作时间开关+节假日生效（非工作时段不触发新任务）。

## 七、执行步骤（审批后）
1. 后端：ScheduleChecker 扩展 + smart_trigger 透传 + get_task_statistics 扩展 + config_manager 校验（单测）；
2. 前端：顶部 AGV 双状态 + 任务信息栏统计卡 + 工作时间日历弹窗；
3. CSS；node --check；板端回归清单交付。

## 八、边界与假设
- AGV 固定两台（robot_ids [1001,1002]）；
- 任务历史 DB 提供 created_at/completed_at/status 用于今日统计（get_task_history 已有 completed_at）；
- 工作时间开关默认 enabled=true + holidays=[]（行为与现状一致：schedules 生效）；
- 节假日当天完全不放行（不调度新任务）；执行中的任务不受影响；
- 不改触发引擎配对算法；统计与调度互不影响。