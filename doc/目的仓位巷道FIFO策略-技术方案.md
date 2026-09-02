# 始发→目的仓位映射 + 巷道 FIFO/FILO 放置策略-技术规划方案

> 状态：规划中（2026-08-27 提交审核，未实施）
> 工程：app_mgr_object-0.2.0(标准版)

## 一、真实需求
1. **映射表**：指定编号的始发仓位 → 允许的目的仓位范围（类型或编号/巷道）；
2. **生产实际**：始发固定 24 仓按类型放货；目的仓数量多于始发；相应类型的货物只能搬运到目的区域对应仓位；
3. **巷道放置规则（关键）**：搬运到目的仓位按**巷道先进先出（FIFO）**逐个放置——**不是有空位就放**（巷道中间有货时，其深处空位进不去，必须按巷道顺序放置）；
4. **可编辑策略**：目的仓位类型/编号采用 **FIFO（先进先出）或 FILO（先进后出）** 策略，配对时按策略约束实现始发↔目的匹配；
5. **配置化 + 前端化**：通过 config YAML 配置区域策略机制；前端「目的编排」弹窗显示当前策略、编辑设置策略及规则。

## 二、现状实勘（app_mgr_object-0.2.0(标准版)）
- **配对**：batch_matcher.greedy_scan_type：显式 pair_overrides（smart_trigger.yaml，src→dst 固定映射）优先，剩余按类型 `get_empty_bays_of_type(cargo_type)` **任意空位+字典序**配对——无巷道/顺序概念，即当前「有空位就放」；
- **目的仓配置**：status_poller.yaml `dest_bay_configs: {bay: {cargo_type, floor}}`（18 仓 T2001~T4006，前端 destArrangeModal 编辑热加载）；
- **目的仓状态**：status_poller 每 10s 调 RCS `query_pod_berth_and_mat` 更新 `dest_cache.is_empty`（实时空/占用可用）；
- **始发仓状态**：bay_status_fusion BayCache（绑定/类型/任务）；类型定义 bay_configs（yaml 热加载）；
- **前端**：destArrangeModal（index.html L267+）= 名称/类型/楼层 表格；btn-arrange-dest 打开（dashboard.js L716+）；保存 setConfigDest → config_manager handler `_apply_dest_configs` → DestBayCache.reload_config + trigger._config_cache.set_dest_mapping（热加载）；
- **配置热加载框架**：web_monitor_plugin._register_reload_handlers 已注册 bay_configs/dest_bay_configs/work_schedule/pair_overrides/cargo_priority 五个 handler，新增策略段可复用同一机制。

## 三、概念模型（通用机制设计）

### 3.1 巷道（Lane）模型
- 巷道 = 目的仓位的**有序分组**（逻辑巷/排）：`lane = {id, floor, strategy, bays[]}`，bays 顺序即巷道顺序（索引 0 = 巷道入口侧）；
- 示例：`2F-L1 = [T2001, T2002, T2003]`、`2F-L2 = [T2004, T2005, T2006]`；
- 巷道可跨类型（一条巷可能放多种类型）或不跨（每类型独立巷）——由配置决定；
- 巷道状态 = 各 slot 的 is_empty（来自 RCS 轮询，实时）。

### 3.2 放置策略（StrategyPolicy）
- **fifo（先进先出）**：巷道内放置选**索引最小（入口侧）的空位**——从头逐个放，前方有货时深处空位视为不可达（不进巷道）；
- **filo（先进后出）**：巷道内放置选**索引最大（深处侧）的空位**——从尾逐个放；
- **any（兼容现状）**：巷道内任意空位（保留当前行为，缺省策略不配置时回退）；
- 策略为可扩展枚举（新增策略只需实现 select_slot 函数）。

### 3.3 始发→目的映射规则（三级回退）
- **L1 精确规则**（src_bay → lane_ids / cargo_types / strategy）：如 A1001 → 巷道 [2F-L1]，策略 fifo；
- **L2 类型规则**（cargo_type → lane_ids / strategy）：如类型 1 → 巷道 [2F-L1]；
- **L3 默认规则**（default_strategy + 类型匹配回退）：未配置时按现有 `dest_bay_configs.cargo_type` 匹配 + default_strategy；
- 优先级 L1 > L2 > L3；显式 pair_overrides 仍最高优先。

## 四、YAML 配置设计
新增配置段（建议放 status_poller.yaml，与 dest_bay_configs 同文件便于运维；亦可独立 pairing_policy.yaml 由 config_manager 统一加载）：
```yaml
# ── 目的仓巷道/放置策略（doc/目的仓位巷道FIFO策略-技术方案）──
pairing_policy:
  default_strategy: fifo        # fifo | filo | any（未配置巷道/规则时的默认）
  lanes:                        # 巷道定义（顺序即巷道顺序）
    - id: 2F-L1
      floor: 2
      strategy: fifo            # 可选，覆盖 default_strategy
      bays: [T2001, T2002, T2003]
    - id: 2F-L2
      floor: 2
      strategy: fifo
      bays: [T2004, T2005, T2006]
    - id: 3F-L1
      floor: 3
      strategy: filo
      bays: [T3001, T3002, T3003, T3004]
  type_rules:                   # 类型规则（L2）
    1: { lanes: [2F-L1], strategy: fifo }
    2: { lanes: [2F-L2], strategy: fifo }
    3: { lanes: [3F-L1], strategy: filo }
  bay_rules:                    # 始发仓位精确规则（L1，可选）
    A1001: { lanes: [2F-L1], strategy: fifo }
```
说明：bays 可省略（缺省=该 floor 下 cargo_type 匹配的目的仓按编号排序成巷）；rules 中 lanes/strategy 均可选，缺省回退上一级。

## 五、后端改造
### 5.1 DestBayCache 扩展（components/task_cache/dest_bay_cache.py）
- 新增巷道索引：`_lanes: {lane_id: {floor, strategy, bay_ids[]}}` + `_bay_lane: {bay_id: (lane_id, slot_index)}`（reload 时构建）；
- `set_pairing_policy(policy)`：热加载巷道/策略（含 reload_config 联动）；
- `select_by_strategy(cargo_type, src_bay, policy) -> Optional[str]`：按 L1→L2→L3 确定巷道集，每巷道按策略（fifo=最小空 slot 索引 / filo=最大空 slot 索引）取候选，多巷道按巷道顺序取第一个有可用空位的；返回 dst_bay（无则 None）；
- 保留 `get_empty_bays_of_type` 供 any 策略/兼容。

### 5.2 batch_matcher 策略配对（components/trigger/batch_matcher.py）
- `greedy_scan_type` 第②步（剩余贪婪配对）改为：对每个 src_bay 调 `select_by_strategy`（而非全局类型空位字典序）；
- TaskCandidate 增加可选 `lane_id/strategy` 字段（日志/前端展示）；
- 显式 pair_overrides 保持最高优先；未配置 pairing_policy 时行为与现状一致（向后兼容）。

### 5.3 配置热加载（plugins/web_monitor_plugin.py）
- _register_reload_handlers 注册 `pairing_policy` handler → `_apply_pairing_policy`：DestBayCache.set_pairing_policy + trigger（batch_matcher）传递；
- web_server.py 新增 /api/config/pairing_policy（GET/POST，读写 status_poller.yaml pairing_policy 段，走 config_manager 热加载）。

## 六、前端改造（目的编排弹窗 destArrangeModal）
### 6.1 策略区（index.html + dashboard.js）
- 弹窗上部新增**策略配置区**：
  1. 当前策略显示（只读摘要）：默认策略 + 巷道列表（id/楼层/仓位/策略）+ 类型规则映射；
  2. 编辑：巷道行（id/楼层/strategy 下拉 fifo|filo|any/仓位编号列表）、类型规则行（cargo_type → 巷道多选/strategy）、默认策略下拉；
  3. 保存 → `API.setPairingPolicy` → yaml 热加载 → 刷新策略显示；
- 原有名称/类型/楼层表格保留（dest_bay_configs 仍可编辑）；
- api.js 新增 getPairingPolicy/setPairingPolicy。

## 七、通用性设计要点
- 策略抽象：StrategyPolicy 枚举 + 每策略 select_slot(lane_empty_slots) 函数——新增策略零侵入；
- 巷道模型与仓位解耦（配置驱动，可跨类型/跨楼层）；
- 映射规则三级回退（bay_rules > type_rules > 类型匹配+default_strategy）——精确到通用；
- pair_overrides（固定映射）仍可叠加（运维兜底）；
- 配置热加载复用既有 config_manager handler 机制（零新框架）；
- 未配置 pairing_policy 时完全向后兼容（any 行为）。

## 八、边界与失败模式
- 巷道内中间空位（FIFO 规则被破坏，如人工取货）：fifo 从头找第一个空位，前方有货即视为不可达——该巷道暂停放置，告警提示检查巷道；
- 巷道满/全部不可达：select_by_strategy 返回 None → 该类型/源仓暂不配对（等 RCS 轮询更新释放），不降级到任意空位（保证巷道约束）；
- RCS 轮询 10s 延迟：放置判定基于最近一次轮询快照，短暂滞后可接受（轮询间隔可配置）；
- 配置错误（巷道仓位不存在/重复/未匹配类型）：reload 时校验并日志告警，回退上一级规则；
- 并发配对：batch_scan_all 单线程，select_by_strategy 持 dest_cache 锁；
- 跨巷道多源同类型：按巷道顺序分配（先 L1 后 L2），避免饿死。

## 九、文件改动清单
| 文件 | 改动 |
|------|------|
| config/plugin_configs/status_poller.yaml | 新增 pairing_policy 段（lanes/type_rules/bay_rules/default_strategy） |
| components/task_cache/dest_bay_cache.py | 巷道索引 + set_pairing_policy + select_by_strategy |
| components/trigger/batch_matcher.py | greedy_scan_type 第②步策略化目的选择 + TaskCandidate 扩展 |
| plugins/web_monitor_plugin.py | 注册 pairing_policy handler |
| components/web/web_server.py | /api/config/pairing_policy GET/POST |
| components/web/static/js/api.js | getPairingPolicy/setPairingPolicy |
| components/web/static/js/dashboard.js | destArrangeModal 策略显示/编辑/保存 |
| components/web/templates/index.html | 弹窗策略配置区 UI |
| doc/目的仓位巷道FIFO策略-技术方案.md | 本方案落盘 |

## 十、测试与验证
**单元测试**：
1. DestBayCache.select_by_strategy：fifo 从头取空位、filo 从尾取空位、中间有货不可达、巷道满返回 None；
2. 规则回退：bay_rules > type_rules > 默认；pair_overrides 最高；
3. batch_matcher 策略配对输出（含 lane_id）；未配置策略时行为不变；
4. py_compile + node --check。
**板端回归**：
1. 配置巷道+策略后，配对按巷道 FIFO 逐个放置（模拟巷道中间有货：深处空位不被选）；
2. FILO 巷道从尾放置；
3. 前端弹窗显示当前策略/巷道/规则，编辑保存热加载生效；
4. 未配置策略时行为与现状一致；pair_overrides 仍有效。

## 十一、执行步骤（审核后）
1. 本方案落盘 doc/目的仓位巷道FIFO策略-技术方案.md；
2. DestBayCache 巷道索引 + 策略选择（单测先行）；
3. batch_matcher 策略化配对；
4. 后端配置 API + handler 热加载；
5. 前端弹窗策略区（显示/编辑/保存）；
6. yaml 默认配置（含示例巷道）；
7. 全量测试 + 板端回归清单交付。

## 十二、假设
- 巷道顺序（入口侧=索引0）由现场确认；FIFO 放置=从入口侧逐个放，中间有货视为不可达；
- 目的仓 is_empty 以 RCS 轮询为准（现状）；轮询间隔可配；
- 始发仓类型固定（bay_configs），不随本方案改动；
- 板端部署版本 = 工作区 app_mgr_object-0.2.0(标准版)。

---

# 附：详细设计（2026-08-27 追加，审核中，未实施）

> 基于已实勘代码（app_mgr_object-0.2.0(标准版)）：config_manager.apply_config 机制、TaskBatchMatcher.greedy_scan_type、DestBayCache、/api/config/* API 模式、destArrangeModal 结构。

## 十三、YAML 配置完整定义

### 13.1 配置段（status_poller.yaml 新增 pairing_policy）

```yaml
# ── 目的仓巷道/放置策略（doc/目的仓位巷道FIFO策略）──
pairing_policy:
  default_strategy: fifo          # fifo | filo | any（巷道/规则未指定时的回退）
  lanes:                          # 巷道定义，顺序无关（按 bays 顺序定巷道内顺序）
    - id: 2F-L1
      floor: 2
      strategy: fifo              # 可选，覆盖 default_strategy
      bays: [T2001, T2002, T2003] # 顺序=巷道顺序（索引0=入口侧）
    - id: 2F-L2
      floor: 2
      strategy: fifo
      bays: [T2004, T2005, T2006]
    - id: 3F-L1
      floor: 3
      strategy: filo
      bays: [T3001, T3002, T3003, T3004]
  type_rules:                     # 类型规则（L2）：cargo_type -> {lanes, strategy}
    1: { lanes: [2F-L1], strategy: fifo }
    2: { lanes: [2F-L2], strategy: fifo }
    3: { lanes: [3F-L1], strategy: filo }
  bay_rules:                      # 始发仓位精确规则（L1）：src_bay -> {lanes, strategy}
    A1001: { lanes: [2F-L1], strategy: fifo }
```

### 13.2 校验规则（config_manager._validate_section 新增 pairing_policy）

- value 必须为 dict；default_strategy ∈ {fifo, filo, any}；
- lanes 为 list：每条含 id(非空唯一)/bays(list 非空、引用存在的 dest_bay_configs 键、跨巷道不重复)；
- type_rules/bay_rules 为 dict：lanes 引用已定义巷道 id；strategy 合法；
- 校验失败返回错误串（沿用 apply_config 错误通道，前端 toast）。

## 十四、策略定义

### 14.1 StrategyPolicy 枚举（components/trigger/pairing_policy.py 新建）

```python
class StrategyPolicy(Enum):
    FIFO = 'fifo'   # 巷道内选索引最小空位（从头放，前方有货深处不可达）
    FILO = 'filo'   # 巷道内选索引最大空位（从尾放）
    ANY  = 'any'    # 任意空位（现状兼容）

def select_slot(strategy, empty_indexes: List[int]) -> Optional[int]:
    # empty_indexes = 巷道内空位 slot 索引列表（升序）
    if strategy == StrategyPolicy.FIFO:
        return empty_indexes[0] if empty_indexes else None
    if strategy == StrategyPolicy.FILO:
        return empty_indexes[-1] if empty_indexes else None
    if strategy == StrategyPolicy.ANY:
        return empty_indexes[0] if empty_indexes else None
    return None
```

### 14.2 Lane 数据结构（DestBayCache 内）

```python
# _lanes: {lane_id: Lane(lane_id, floor, strategy, bay_ids: List[str])}
# _bay_lane: {bay_id: (lane_id, slot_index)}   # slot_index=巷道内顺序
# 构建时机：set_pairing_policy(policy)/reload_config 联动时重建
```

### 14.3 规则解析（三级回退）

```python
def resolve_rule(src_bay, cargo_type) -> Rule:
    # L1: bay_rules.get(src_bay)   L2: type_rules.get(cargo_type)
    # L3: 未配置 → lanes=该 cargo_type 匹配的全部巷道(按 id 排序), strategy=default_strategy
    # 每级 lanes/strategy 可部分缺省（缺省补 default_strategy / 回退下一级）
```

## 十五、后端实现

### 15.1 DestBayCache（components/task_cache/dest_bay_cache.py）

```python
def set_pairing_policy(self, policy: Optional[dict]):
    # 解析 lanes/type_rules/bay_rules/default_strategy → 重建 _lanes/_bay_lane
    # 校验：bays 引用存在的缓存键；无效则 logger.warning 并忽略该巷道

def select_by_strategy(self, cargo_type: int, src_bay: str = None) -> Optional[str]:
    # 1) resolve_rule(src_bay, cargo_type) → (lane_ids, strategy)
    # 2) 对 lane_ids 顺序：
    #    empty = [i for i, b in enumerate(lane.bay_ids)
    #             if self._bays.get(b) and self._bays[b].is_empty]
    #    idx = select_slot(strategy, empty)；命中返回 lane.bay_ids[idx]
    # 3) 全巷道无可用 → None（不降级任意空位）

def get_lane_summary(self) -> List[dict]:
    # 供前端策略显示：{id, floor, strategy, bays, occupied_count}

# reload_config 尾部调用 _rebuild_lanes()（保持巷道索引与仓位集同步）
```

### 15.2 TaskBatchMatcher（components/trigger/batch_matcher.py）

- 构造参数追加 `pairing_policy: Optional[dict] = None` → 传给 dest_cache.set_pairing_policy；
- 新增 `set_pairing_policy(policy)` 热加载方法；
- `greedy_scan_type` 第②步改造：对每个 src_bay 调 `dest_cache.select_by_strategy(cargo_type, src_bay)`（跳过 used_dst），不再全局字典序；
- TaskCandidate 追加 `lane_id: Optional[str] = None`、`strategy: Optional[str] = None`（key() 不变，兼容排序）；
- 显式 pair_overrides 保持最高优先；未配置 pairing_policy 时 select_by_strategy 回退 any（行为与现状一致）。

### 15.3 配置层

- config_manager.py：path_map 加 `'pairing_policy': ['status_poller', 'pairing_policy']`；新增 `get_pairing_policy()`；_validate_section 加校验（§13.2）；
- web_server.py：新增 `GET /api/config/policy`（cm.get_pairing_policy）、`PUT /api/config/policy`（cm.apply_config('pairing_policy', data.get('policy', {}))）——沿用 /api/config/bay 模式；
- web_monitor_plugin.py：register_handler('pairing_policy', _apply_pairing_policy)：poller.dest_cache.set_pairing_policy(v) + trigger._trigger_engine.set_pairing_policy(v)；
- trigger_engine.py：`set_pairing_policy(policy)` → self._batch_matcher.set_pairing_policy(policy)。

## 十六、前端实现

### 16.1 index.html（destArrangeModal body 顶部插入策略区）

- 只读摘要区 `<div id="pairing-policy-summary">`：默认策略 + 巷道表（id/楼层/strategy/仓位/空位占用）+ 类型规则 + 始发规则；
- 编辑区（折叠 details）：默认策略下拉；巷道行（id 输入/floor 输入/strategy 下拉/bays 逗号分隔）；类型规则行（type 数字/lanes 逗号分隔/strategy 下拉）；增删行按钮；
- 保存按钮 `btn-save-policy`（与 btn-save-dest 并列）。

### 16.2 dashboard.js

- 弹窗打开时：`API.getPairingPolicy()` → 渲染摘要 + 编辑表单；
- `btn-save-policy` → 收集表单 → `API.setPairingPolicy(policy)` → toast + 重渲染摘要 + loadAllData；
- 保留现有 dest 表格逻辑（名称/类型/楼层）。

### 16.3 api.js

- `getPairingPolicy: () => this._get('/api/config/policy')`；
- `setPairingPolicy: (policy) => this._put('/api/config/policy', {policy})`（参照 _put 现有封装）。

## 十七、测试用例

**单测（dest_bay_cache）**：
1. fifo：T2001 空 → 返回 T2001（从头第一个空位）；
2. fifo：T2001/T2002 占用、T2003 空 → None（前方有货深处不可达，巷道暂停）；
3. filo：T2003 空选 T2003；T2003 占用选 T2002（从尾）；
4. any：任意空位（字典序最小）；
5. 规则回退：bay_rules > type_rules > 默认；pair_overrides 不受影响；
6. 巷道满 → None；无效配置（仓位不存在/重复）→ 告警并跳过该巷道。

**集成（batch_matcher）**：策略下 greedy_scan_type 输出 dst 满足巷道约束；未配置策略行为与现状一致。

**前端**：node --check；策略区显示/编辑/保存链路。

**板端回归**：模拟巷道中间有货（RCS 轮询）→ 配对不选深处空位；FILO 从尾放置；前端弹窗策略显示/编辑/保存热加载；未配置策略时行为不变。

## 十八、实施步骤（分阶段，审核后）

| 阶段 | 内容 | 验证 |
|------|------|------|
| 1 | 新建 components/trigger/pairing_policy.py（枚举+select_slot）；DestBayCache 巷道索引/set_pairing_policy/select_by_strategy | 单测 §17 1-6 |
| 2 | batch_matcher 策略化配对 + TaskCandidate 扩展 | 集成测试 |
| 3 | config_manager（path_map/validate/get_pairing_policy）+ web_server /api/config/policy + web_monitor handler + trigger_engine 透传 | py_compile + API 手测 |
| 4 | 前端策略区（index.html/dashboard.js/api.js） | node --check + 页面手测 |
| 5 | status_poller.yaml 加默认 pairing_policy 示例；全量回归 + 板端清单 | 板端回归 |

## 关联文件（完整清单）

- config/plugin_configs/status_poller.yaml（新增 pairing_policy 段）
- components/trigger/pairing_policy.py（新建：策略枚举+选择函数）
- components/task_cache/dest_bay_cache.py（巷道索引+策略选择）
- components/trigger/batch_matcher.py（策略化配对+TaskCandidate）
- components/trigger/trigger_engine.py（set_pairing_policy 透传）
- components/web/config_manager.py（path_map/validate/get_pairing_policy）
- components/web/web_server.py（/api/config/policy GET/PUT）
- plugins/web_monitor_plugin.py（handler 注册）
- components/web/static/js/api.js、dashboard.js、templates/index.html（前端策略区）
- doc/目的仓位巷道FIFO策略-技术方案.md（本详细设计）

## 假设与边界（沿用 §八/§十二）

- 巷道入口侧=索引0，现场确认；FIFO 语义=入口连续占用时深处不可达（巷道暂停），不降级任意空位；
- 目的仓 is_empty 以 RCS 10s 轮询为准；
- 未配置 pairing_policy 时行为与现状完全一致（向后兼容）。

---

# 十九、前端弹窗策略查看/编辑-详细设计（2026-08-27 审查补充）

> 审查结论：技术方案 §16 仅有策略区概要；当前前端 destArrangeModal（index.html L267+ / dashboard.js L715-772）只有 dest_bay_configs 表格（名称/类型/楼层），**无策略功能**；且用户核心诉求「始发仓位↔目的仓位对应调整」（bay_rules 始发规则）缺少详细编辑交互设计。本节约定完整前端设计，供审核后实施（实施依赖 §15 后端 API 先行）。

## 19.1 弹窗整体布局（destArrangeModal 改造为双 Tab）

| Tab | 内容 | 状态 |
|-----|------|------|
| ① 目的仓位 | 现有 dest_bay_configs 表格（名称/类型/楼层，增删行/保存 btn-save-dest） | 保留现状 |
| ② 配对策略 | 策略查看（只读摘要）+ 策略编辑（表单，btn-save-policy） | 新增 |

- 复用页面已有 tab 样式（.tab-bar-inline / .tab），零新样式；modal-lg 尺寸不变。

## 19.2 Tab②「配对策略」- 查看区（只读，弹窗打开即渲染）

- **默认策略**：badge 显示 default_strategy（fifo / filo / any）；
- **巷道表**：列 = 巷道ID / 楼层 / 策略 / 仓位序列（bays 箭头连接显示入口→深处）/ 占用数（n/m，来自 RCS is_empty 实时）；
- **类型规则表**：列 = 类型(1~6) / 绑定巷道 / 策略；
- **始发规则表（核心）**：列 = 始发仓位 / 绑定巷道 / 策略——展示「始发仓位与目的仓位的对应关系」（bay_rules 生效项）；
- 数据源：API.getPairingPolicy() → {policy} + API.getDestStatus()（占用统计）；
- 空态：未配置 pairing_policy 时显示「未配置（默认 any 兼容行为）」。

## 19.3 Tab②「配对策略」- 编辑区（表单）

### 19.3.1 默认策略
- 下拉 fifo | filo | any（缺省 any）。

### 19.3.2 巷道编辑（行列表，可增删）
1. 巷道ID：文本，校验非空/唯一；
2. 楼层：数字；
3. 策略：下拉 fifo|filo|any，缺省继承默认；
4. 仓位序列：**从当前目的仓多选勾选**（checkbox 组，按楼层分组）或逗号分隔输入；**顺序=勾选顺序=巷道顺序（索引0=入口侧）**；校验非空/跨巷道不重复；提供「逆序」按钮调整入口侧。

### 19.3.3 类型规则编辑（行列表，可增删）
- type 下拉(1~6) → 巷道多选 + strategy 下拉（缺省继承默认）。

### 19.3.4 始发规则编辑（核心，行列表，可增删）——「始发仓位与目的仓位对应调整」
1. 始发仓位下拉：**从 24 个起始仓选择**（数据源 API.getConfigBay() 键，即 bay_configs）；
2. 绑定巷道多选：从已定义巷道中选，校验引用存在；
3. strategy 下拉：缺省继承默认；
4. 说明文案：「始发仓位 A1001 的货物只能搬运到所选巷道的对应目的仓位」；
5. 一个始发仓一行，新增时下拉排除已用仓。

### 19.3.5 操作按钮
- 「新增巷道 / 新增类型规则 / 新增始发规则」三个添加按钮；
- 每行右侧删除按钮（删除巷道被 type_rules/bay_rules 引用时前端阻止并提示先解除引用）；
- 「恢复默认」按钮：重置为后端当前已保存配置（放弃未保存修改）。

## 19.4 保存与反馈

- 「保存策略」btn-save-policy → 前端预校验（id 唯一 / bays 非空 / lanes 引用存在 / strategy 合法）→ API.setPairingPolicy(policy)；
- 后端 apply_config 校验失败 → toast 显示错误（沿用现有错误通道）；成功 → toast + 重渲染查看区 + loadAllData（配对实时生效）。

## 19.5 与后端接口映射

- GET /api/config/policy → {success, policy: {default_strategy, lanes, type_rules, bay_rules}}；
- PUT /api/config/policy {policy} → apply_config('pairing_policy', policy)（§15.3，热加载 DestBayCache + trigger）；
- 始发仓下拉数据源：API.getConfigBay()（bay_configs 键）；目的仓勾选数据源：API.getConfigDest() 键；占用统计：API.getDestStatus()。

## 19.6 边界与交互细节

- 编辑未保存切换 Tab：AppDialog 确认提示（不丢失修改）；
- 巷道仓位勾选顺序即巷道顺序（记录点击顺序；「逆序」按钮调整入口侧）；
- 始发仓在 bay_rules 中一行一仓，新增下拉排除已用；
- 删除巷道被引用时阻止并提示；
- 所有下拉/多选默认回填当前已保存值；保存成功立即刷新查看区。

## 19.7 前端代码改动清单（审核后实施）

| 文件 | 改动 |
|------|------|
| templates/index.html | destArrangeModal 改双 Tab；②策略区（查看容器 pairing-policy-summary + 编辑表单容器 + btn-save-policy + 恢复默认） |
| static/js/dashboard.js | 弹窗打开加载策略；renderPairingPolicySummary() / renderPairingPolicyForm() / collectPairingPolicy()；btn-save-policy 保存；始发仓下拉数据源；Tab 切换未保存确认 |
| static/js/api.js | getPairingPolicy / setPairingPolicy |

## 19.8 测试验证

- node --check；弹窗双 Tab 切换正常；
- 策略查看：默认策略/巷道/类型规则/始发规则渲染正确（含占用数）；
- 策略编辑：增删巷道/类型规则/始发规则、勾选顺序、校验拦截（重复 id/空 bays/未引用巷道）、保存成功 toast + 热加载；
- 未配置策略空态；恢复默认按钮；未保存切换 Tab 确认；
- 板端：弹窗编辑保存后配对按新策略实时生效（与 §17 回归联动）。