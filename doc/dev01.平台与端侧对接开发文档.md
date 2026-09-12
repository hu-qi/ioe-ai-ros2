# dev01. 平台与端侧对接开发文档（v2：取消订阅前提 / 接口定义格式说明）

> 适用：**端侧** touch_ui_plugin-v0.0.1（一体机，数据上报方，默认 `realtime_gate=auto`、上报总闸默认关）
>        **平台**（教官端/服务端，接收方；可参考 mock：wh-rcs_server/training_mock.py:8183）
> 上游：rtsp_multi_yolov_plugin-0.0.6（/disass_status、/disass_report、/disass_evidence、超时抓拍 BMP）
> 关联：rtsp doc/45/38/56-59/69-78、touch doc/72-82、dev02/dev03/dev05
> 定位：供**平台开发工程师**开发/联调/测试使用（含接口定义格式说明）。

## 版本记录（面向平台的重要语义变更）
| 版本 | 变更 |
|---|---|
| v1 | 订阅驱动实时（平台 POST 订阅后 touch 才实时上报） |
| **v2（doc/80/81）** | **取消"订阅作为上报前提"**：① 默认 `realtime_gate=auto`——端侧上报总闸开 + 平台地址就绪即实时上报，**无需平台订阅**；② 上报总闸 `report_enabled` 默认 **false**（端侧部署/调试期零外发，需在设置页开总闸）；③ 订阅接口**保留为可选能力**（`realtime_gate=subscribed` 控流 / 平台统计展示），不再决定 auto 端侧是否上报 |
| **v3（doc/83/84）** | **订阅彻底取消**：订阅接口（subscriptions）移出对接清单，平台无需实现；设置页只填「平台地址(baseURL)」（如 `http://192.168.31.191:8183`），应用后自动展开写入四 URL（reports/events/evidence/students），并**持久化到 params.yaml**（免重启热改、重启保留）；`report_enabled` 默认关不变 |

---

## 1. 通讯模型与上报触发（平台工程师视角）
```
端侧一体机（touch_ui_plugin，内网仅能主动外发 HTTP）
  ├─ report_enabled(默认关) ∧ 平台地址已配 → 上报开启（auto）
  │    ├─ 轮次进行中步骤变化        → POST {base}/api/v1/events      每 realtime_upload_sec(2s) 攒批
  │    ├─ rtsp 超时抓拍(写盘~1s后)   → POST {base}/api/v1/evidence     实时证据（multipart）
  │    ├─ 轮次结束(完成/手动/超时)   → POST {base}/api/v1/reports      整包
  │    └─ 轮次结束未实时送出的证据   → POST {base}/api/v1/evidence     兜底（按 file 与实时去重）
  ├─ 学员（可选）                 ← GET {base}/api/v1/students       「从平台同步」拉取
  └─ 订阅状态（可选）             → GET  {base}/api/v1/subscriptions/{device_id}  轮询（仅 subscribed 模式/统计）
```
- **平台是接收方**：被动接收 reports/events/evidence；平台**不需要**先调用任何"开启"接口，端侧配好即报；
- 平台可选实现 `GET /api/v1/subscriptions/*`、`GET /api/v1/devices` 用于**统计与展示**（不影响端侧上报）。

## 2. 接口定义格式说明（所有接口通用）
### 2.1 请求/响应包裹
- JSON 接口统一包裹：`{"code": 0, "message": "ok", "data": {...}}`（code=0 成功；非 0 失败）
- 错误示例：`{"code": 400, "message": "missing top-level field: round", "data": {}}`
- HTTP 状态：2xx=业务成功；4xx/5xx=传输/校验失败（平台应同时返回包裹体便于端侧/联调解析）
- 文件接口用 multipart/form-data（evidence）；**无需鉴权头**（mock 免认证；若平台开启认证见 §11-6）

### 2.2 字段类型记号
| 记号 | 含义 | 示例 |
|---|---|---|
| int / int64 | 整数（64 位毫秒时间戳等） | `ts_upload_ms` |
| str | 字符串 | `device_id` |
| bool | 布尔 | `active` |
| array | 对象数组 | `events` |
| obj | 嵌套对象 | `progress` / `student` |

### 2.3 时钟与幂等（务必遵守）
- 仅 `ts_upload_ms` 为墙钟（epoch ms）；`events[].ts`、`round.*ms`、evidence `ts` 均为**引擎单调 ms**——**禁止与墙钟混减/换算**；
- 幂等键：增量 `device_id + round_start_ms + events[].ts`；整包 `device_id + round.start_ms`；证据 `device_id + round_start_ms + sub + ts`；
- 重试容忍：端侧整包重试 3 次、实时证据重试 ≤3 次后丢弃（整包兜底补发）、增量当批失败即丢（下周期全量 diff 自愈）——**平台需按幂等键去重/追加，勿拒绝重复到达**。

### 2.4 端侧默认与配置（平台侧需知会现场；doc/83/84 后）
| 参数 | 默认 | 说明 |
|---|---|---|
| `device_id` | dev01 | 上报/归档键（多设备唯一） |
| `report_enabled` | **false** | 上报总闸：false=零外发（默认关；设置页开闸即报） |
| `report_upload` | http-post | 整包自动上报模式 |
| 平台地址(baseURL) | 空 | 设置页填 `http://IP:8183` → 应用自动展开写：`report_upload_url`、`realtime_events_api`、`evidence_forward_url`、`students_sync_api`（+ `/api/v1/{reports,events,evidence,students}`），并持久化 params.yaml |
| `report_upload_url` 等四 URL | 空 | 由 baseURL 应用写入；也可单独参数/ros2 覆盖（兼容老完整路径归一化） |
| `evidence_forward` / `evidence_realtime` | true / true | 证据两通道默认开（受总闸+URL 门控） |
| `realtime_gate` | **auto** | auto 唯一（订阅已取消 doc/83） |
| ~~`report_subscribe_api`~~ | ~~—~~ | **已取消（doc/83/84）** |
| `students_sync_api` | 空 | 学员分发（随 baseURL 自动写入） |

---

## 3. 整包上报接口（POST /api/v1/reports）
- 端点：`POST {base}/api/v1/reports`；触发：轮次结束（`/disass_report`，finish_reason=completed/manual/timeout/reset）
- 格式：application/json，payload：
```json
{
  "schema_version": "1.0", "device_id": "dev01", "edge_node": "touch_ui_plugin",
  "ts_upload_ms": 1788407910000,
  "student": {"id":"S2024001","name":"张明","cls":"一班","source":"manual"},
  "round": {
    "process_name":"拆解","finish_reason":"completed",
    "start_ms":0,"end_ms":910000,"duration_ms":910000,"process_elapsed_ms":910000,
    "events":[], "steps":[...], "substeps":[...], "unexecuted":[], "evidence":[...],
    "substep_counts":[3,2,6,2,1,2,2,1], "interval_ms":[...]
  }
}
```
- 说明：`round`=引擎 JSON 原样（最全）+ touch 补 `substep_counts`；子步骤字段含 start/end/duration、timeout/over_std/omitted（rtsp doc/38 v1.1、doc/76）；`round.evidence[]`=`[{sub,ts,file}]`（file 为端侧绝对路径，平台无需拉取，由 evidence 接口收件）
- 响应示例：`{code:0,data:{report_id:"R<ts>_dev01",device_id:"dev01",finish_reason:"completed",evidence:0}}`

## 4. 实时增量接口（POST /api/v1/events）
- 端点：`POST {base}/api/v1/events`；触发：auto 模式下总闸开+地址就绪即上报（**无需订阅**）
- payload `event_delta`（schema 1.1）：
```json
{
  "schema_version":"1.1","type":"event_delta","device_id":"dev01","edge_node":"touch_ui_plugin",
  "ts_upload_ms":1788407910000,"round_start_ms":1788407000000,"process_elapsed_ms":910000,
  "student":{"id":"S2024001","name":"张明","cls":"一班","source":"manual"},
  "events":[{"ts":12000,"kind":0,"step":1,"sub":2},{"ts":18500,"kind":1,"step":1,"sub":2}],
  "progress":{"done":2,"total":19,"current":"装扣机","current_sub_index":5}
}
```
- 字段：kind=0 START/1 COMPLETE/2 INTERRUPT/3 TIMEOUT/4 FINISH_EOF/5 FINISH_EIO；`events[].ts` **相对 round_start_ms 偏移**；step/sub 全局序号 1..M
- 门控：`realtime_gate=auto`（默认）→ `report_enabled ∧ 端点可推`；`subscribed` → 再加平台订阅态
- 响应示例：`{code:0,data:{device_id:"dev01",delta_events:2}}`
- 平台建议：按 `device_id+round_start_ms` 追加事件流；与整包 events 同幂等键合并；墙钟参考 `approx_start_wall=ts_upload_ms−process_elapsed_ms`

## 5. 证据图接口（POST /api/v1/evidence，multipart）
- 端点：`POST {base}/api/v1/evidence`；格式 multipart/form-data
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | 附件 | 是 | BMP 图（rtsp BMP 直写；jpg 编码器板端不可用） |
| `sub` | str(int) | 是 | 子步骤序号 1..M |
| `ts` | str(int64) | 是 | 引擎单调 ms（与整包 evidence.ts 同口径） |
| `device_id` | str | 是 | 设备键 |
| `round_start_ms` | str(int64) | 否 | 轮次起点（推荐平台据此归属轮次） |
- 两通道：**实时证据**（抓拍~1s 后，auto/subscribed 视门控）与**整包兜底**（轮次结束按 report.round.evidence 补发未实时送出的）；按 file 绝对路径端侧去重
- 响应示例：`{code:0,data:{saved:"data/training/evidence/dev01/sub01_t12345.bmp",device_id:"dev01",sub:"1",ts:"12345",round_start_ms:"..."}}`
- mock 参考签名见 dev02；落盘 `evidence/<device_id>/sub%02d_t<ts>.bmp`

## 6. 订阅/状态接口（可选能力，v2 不再作为 auto 上报前提）
> auto（默认）端侧**无需平台订阅**也会实时上报。以下接口用于：
> a) `realtime_gate=subscribed` 的端侧（平台订阅才实时）；b) 平台按设备统计/展示"在收/未收"状态。
| 方法 | 路径 | 请求体 | 响应 data |
|---|---|---|---|
| POST | `/api/v1/subscriptions` | `{"device_id":"dev01","note":"可选"}` | `{device_id,active:true,subscribed_at_ms}` |
| GET | `/api/v1/subscriptions/{device_id}` | — | `{device_id,active,subscribed_at_ms?}` |
| DELETE | `/api/v1/subscriptions/{device_id}` | — | `{device_id,active:false,was_active}` |
| GET | `/api/v1/subscriptions` | — | `{devices:{device_id:{active,…}}}` |
- 重复 POST=更新 note 保持 active；端侧轮询周期 `subscribe_poll_sec`(默认5s，可热设)；多设备逐台
- 端侧日志观测（subscribed 模式）：`Service subscribed; realtime report ON` / `…OFF`

## 7. 学员分发接口（GET /api/v1/students，平台需实现）
- 端点：`GET {base}/api/v1/students[?cls=<班级>&keyword=<关键字>]`
- 响应：`{"code":0,"data":{"total":n,"students":[{"tid":"S2024001","name":"张明","cls":"一班"},…]}}`
- 端侧行为：设置页「从平台同步」→ merge 本地 CSV；新增/更新 source=platform 行；本地手工(非 platform)同 tid **保留本地**；只增不删

## 8. 辅助/检索接口（平台开发参考）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/devices` | 设备汇总（订阅状态/报告数/事件数/最新进度） |
| GET | `/api/v1/analysis/{device_id}` | 单设备详情 |
| GET | `/api/v1/reports?device_id=&student_id=&limit=` | 整包检索（元信息） |
| GET | `/api/v1/reports/{report_id}` | 整包详情 |
| GET | `/api/v1/debug/training_summary` | mock 落盘汇总（联调） |

---

## 9. 联调测试步骤（mock :8183）
### 9.1 准备
1. 平台启动 mock：`cd wh-rcs_server && python3 training_mock.py`（含 reports/evidence/subscriptions/events/students/devices/analysis）；
2. 端侧 params.yaml：`report_upload_url: "http://<平台IP>:8183/api/v1/reports"`（或留空后设置页填/改 IP）；
3. 端侧设置页开「**上报总闸**」（默认关）→ toast「已开启…」；`realtime_gate=auto`（默认）。
### 9.2 自动上报链路（无订阅，v2 主路径）
1. 开总闸 + 地址就绪 → UI「开始」→ 推步骤 → 平台收 `POST /api/v1/events`（2s 批，touch 日志 `[delta]`）；
2. 结束本轮 → 平台收 `POST /api/v1/reports`（touch `[report] ok HTTP 200`）；
3. rtsp 超时抓拍 → 平台收 `POST /api/v1/evidence`（touch `Evidence realtime ok`）；
4. 平台核对：`curl …/api/v1/devices`、落盘 `data/training/{reports,events,evidence}/dev01/`。
### 9.3 subscribed 模式（已取消，doc/83/84——本节仅留档，平台无需实现订阅）
> 订阅机制已从端侧移除/废弃；`realtime_gate=subscribed` 与 subscriptions 接口不再需要，回归验证无需执行本节。

---

## 10. 未尽对接问题与建议（平台/端侧 TODO）
| # | 项 | 现状 | 建议 |
|---|---|---|---|
| 1 | `GET /api/v1/students` | 端侧就绪（fetch/按钮/merge），mock 已实现 | 正式平台按 §7 实现（只读） |
| 2 | 证据 BMP | doc/73 定案 | 平台解析 BMP 或转 jpg 展示 |
| 3 | students_sync_sec 周期同步 | 端侧仅手动 | 后续加周期（防 CSV 并发写） |
| 4 | 学员来源联动 | 未做 | 选中 platform 学员时 source 置 platform |
| 5 | 认证 | mock 免认证 | 平台启用认证时：读 Bearer/x-ops-token；写操作 CSRF——建议对端侧外发接口放行或提供 token 下发机制 |
| 6 | 实时时效 | auto 常开 2s 批 | 如需秒级被动推送可演进 SSE/WS（另议） |
| 7 | 订阅统计口径 | subscriptions 状态保留 | 平台可作"在收/离线"展示，不阻塞上报 |

## 11. 参考文档索引
| 主题 | 文档 |
|---|---|
| 协议/订阅/增量/整包/时钟（协议基线） | rtsp doc/45；整包 doc/38；计时 doc/56-59 |
| 证据链路/BMP/面板 | rtsp doc/69-78 |
| 端侧方案/落地 | touch doc/72-82（72 分析、73-76 证据与日志、77-78 订阅热设、80 gate、81 默认关/徽标） |
| mock 与联调 | dev02；免订阅操作 dev03（auto）；去订阅化方案 dev05 |
| mock 服务端 | wh-rcs_server/training_mock.py |
