# 放置策略弹窗-操作流程梳理与UI规范-技术方案

> 状态：已审批并实施（2026-08-27）
> 角色：开发专家（表格字体 UI 修正）+ 产品经理（配置操作体验流程梳理）

## 一、概述（配置三步操作流）
「放置策略」弹窗将复杂配置拆为**三步递进**操作，遵循「先有仓位 → 再组巷道 → 后定对应」的生产逻辑：
| 步骤 | Tab | 做什么 | 产物（yaml） |
|------|-----|--------|--------------|
| ① 目的仓位 | 目的仓位 | 维护目的仓位（编号/楼层/所属巷道/类型），单个或批量 | dest_bay_configs（含 lane） |
| ② 巷道策略 | 配对策略→编辑 | 按楼层/类型组织巷道，定义放置策略（fifo/filo/any） | pairing_policy.lanes（bays 可缺省按 lane 派生） |
| ③ 始发对应 | 配对策略→编辑 | 始发仓位→目的巷道对应（一组始发可对应多条巷道）+ 类型规则 + 默认策略 | pairing_policy.bay_rules / type_rules / default_strategy |
| 保存 | — | 保存即 yaml 热加载，配对实时生效 | status_poller.yaml |

## 二、操作流程细化
### 2.1 目的仓位（Tab①，仓位基础）
1. 打开弹窗默认展示全部目的仓位（紧凑表格，滚动浏览）；
2. **新增单个**：点「新增仓位」→ 末行出现空行（编号/楼层/所属巷道下拉/类型）→ 填写；
3. **批量添加**：点「批量添加」→ 置顶弹窗输入多行/范围（T2001~T2010,2,2F-L1,1）→ 添加后逐行校验；
4. **编辑**：直接改行内单元格；所属巷道下拉选择（选项=已配置巷道，未分配=留空）；
5. **删除**：行尾删除按钮；
6. **保存**：点「保存」→ 写 dest_bay_configs（含 lane）→ toast + 热加载。

### 2.2 巷道策略（Tab②→编辑模式）
1. Tab② 默认**展示模式**（只读摘要：默认策略/巷道表/类型规则/始发规则）；
2. 点「编辑策略」进入**编辑模式**；
3. 巷道区：增删巷道行（ID/楼层/策略下拉/仓位序列）；仓位序列可留空（按 dest_bay_configs.lane 自动派生，编号升序）——**推荐留空由系统派生，避免双源不一致**；
4. 策略下拉：fifo（入口先进先出）/filo（深处先进后出）/any（任意空位）。

### 2.3 始发对应（Tab②→编辑模式）
1. 类型规则：某货物类型 → 多条巷道（如类型 1 → 2F-L1,4F-L1）；
2. 始发规则：**一组始发仓位 → 多条巷道**（如 A1001 → 2F-L1,2F-L2）——实际生产始发有货即搬运到多条巷道存放；
3. 默认策略下拉（全局回退）；
4. 「保存策略」→ 写 pairing_policy → 热加载 → 自动回展示模式。

## 三、UI 规范（表格文字/字体修正）
### 3.1 现状与差距（对照 42号 UI 指南 + 现有 task-table 设计语言）
| 元素 | 现状 | UI 规范（修正目标） |
|------|------|-------------------|
| 表头 th | task-table 科幻风（渐变/发光/扫描线），未显式字号 | 弹窗内表格 th：font-size 12px、加粗 600、颜色 var(--text-secondary)（保留 task-table 底色但去过度发光，缩小 letter-spacing 至 0.5px） |
| 表体 td | 12px text-primary（符合） | 保持 12px；行高紧凑但不挤压（padding 3px 8px） |
| 表单控件 | form-control-sm 11px；compact-rows 0.8rem | 弹窗内统一 12px（非 11px），compact 行 12px、min-height 26px |
| 字体族 | body 继承（系统字体） | 沿用 body 字体族，不加自定义 |
| 下拉/输入 | - | 背景 var(--bg-tertiary)、边框 var(--border)、focus accent-blue（42号 §2.3.1-6 规范） |

### 3.2 修正方案（CSS，不动结构）
```css
/* 放置策略弹窗表格字体统一（doc/放置策略弹窗-操作流程与UI规范） */
#destArrangeModal .task-table thead th {
    font-size: 12px; font-weight: 600; letter-spacing: 0.5px;
    color: var(--text-secondary);
    text-shadow: none;
    background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border);
}
#destArrangeModal .task-table thead th::after { display: none; }  /* 关扫描线 */
#destArrangeModal .form-control-sm, #destArrangeModal .form-select-sm { font-size: 12px; }
#destArrangeModal .compact-rows .form-control-sm, #destArrangeModal .compact-rows .form-select-sm { font-size: 12px; min-height: 26px; }
#destArrangeModal .compact-rows tbody td { padding: 3px 8px; }
```
说明：弹窗内小表格用简洁表头（对齐 42号规范），主页面大表格保留科幻风格；字体统一 12px 提升可读性。

## 四、操作体验改善（产品经理建议）
1. **默认展示模式**：打开弹窗即见当前配置全貌（决策友好），编辑需显式进入——避免误改；
2. **巷道序列留空=自动派生**：减少手工输入错误，yaml 单一来源（dest_bay_configs.lane）；
3. **始发规则一对多**：一行一始发仓、巷道多选（逗号分隔或勾选），对应关系一目了然；
4. **批量添加范围展开**：T2001~T2010 一次 10 行，适合 100 仓初始化；
5. **保存即生效**：yaml 热加载 + toast + 回展示模式，配置闭环可感知；
6. **未保存提示**：编辑模式切走时确认（后续可加 AppDialog，本期简化）；
7. **表头简洁化**：弹窗小表格去科幻动效，聚焦内容可读性。

## 五、改动清单（已实施）
| 文件 | 改动 |
|------|------|
| static/css/custom.css | 新增 #destArrangeModal 表格/控件字体统一样式（§3.2） |
| doc/放置策略弹窗-操作流程与UI规范-技术方案.md | 本方案 |

## 六、验证
- 弹窗表格表头 12px 简洁风格、表体 12px、表单控件 12px、compact 行 26px；
- 主页面表格科幻风格不受影响（仅 #destArrangeModal 作用域）；
- 操作流程：目的仓位（单/批量）→ 巷道策略（编辑/派生）→ 始发对应（一对多）→ 保存生效，各步可操作。

## 七、实施记录
- 2026-08-27：方案批准；文档落盘；custom.css 新增 #destArrangeModal 字体统一样式；memory 记录。