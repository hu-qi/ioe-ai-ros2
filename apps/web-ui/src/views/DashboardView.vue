<template>
  <div class="page-wrap">
    <!-- ===== 第一行：① 实时训练动态（40%） + ② 概览（60%） ===== -->
    <div class="row-top">
      <!-- ① 实时训练动态（doc/04 §3.2 / doc/05.1 §6.1） -->
      <section class="card rt-panel">
        <div class="card-title">
          <span class="live-dot" :class="hasActive ? 'on' : 'off'"></span>实时训练动态
          <span class="title-extra">{{ rt.devices.length }} 台设备</span>
        </div>

        <div v-if="!rt.devices.length" class="rt-empty">
          <div class="rt-empty-icon"></div>
          <div class="rt-empty-title">暂无进行中的训练</div>
          <div class="rt-empty-sub">设备开始考试后，此处实时刷新进度</div>
        </div>

        <div v-else class="rt-devices">
          <div v-for="d in rt.devices" :key="d.device_id" class="rt-device">
            <div class="rt-head">
              <b class="rt-student link" @click="openStudent(d)">{{ d.student_name || '未绑定学员' }}</b>
              <span class="rt-device-id ts">{{ d.device_id }}</span>
            </div>
            <div class="rt-progress">
              <div class="rt-bar">
                <div class="rt-fill" :style="{ width: progPct(d) + '%' }"></div>
              </div>
              <span class="rt-frac">{{ d.done ?? 0 }}/{{ d.total ?? 0 }}</span>
            </div>
            <div class="rt-current">
              当前：{{ d.current || '-' }}
              <span class="rt-elapsed" :class="{ overtime: isOvertime(d) }">
                已用 {{ fmtDuration(d.process_elapsed_ms) }}
              </span>
            </div>
            <!-- 实时事件流（最新 10 条，新事件置顶） -->
            <div v-if="eventsOf(d.device_id).length" class="rt-events">
              <div v-for="(ev, i) in eventsOf(d.device_id)" :key="i" class="rt-ev">
                <span class="ts">{{ evClock(d, ev) }}</span>
                <span class="rt-ev-icon" :class="kindStyle(ev.kind).cls">{{ kindStyle(ev.kind).icon }}</span>
                <span class="rt-ev-text">{{ kindStyle(ev.kind).label }} {{ ev.sub ? `子步骤${ev.sub}` : '' }}</span>
              </div>
            </div>
            <!-- 最新抓拍缩略图（doc/05.1 §6.1 区域①底部：120×90，悬停放大，点击 Lightbox） -->
            <div v-if="latestSnap(d.device_id)" class="rt-snap">
              <span class="rt-snap-label ts">最新抓拍</span>
              <EvidenceThumb :item="latestSnap(d.device_id)" :width="120" :height="90" />
            </div>
          </div>
        </div>
      </section>

      <!-- ② 今日概览（doc/04 §3.3 / doc/05.1 §6.2：点击原地联动，不跳页） -->
      <section class="ov-panel">
        <div class="ov-grid">
          <MetricCard label="考试人数" :value="ov.exam_count" color="#2B5CE6"
            :selected="ws.activeMetric === 'exam'" @click="ws.toggleMetric('exam')" />
          <MetricCard label="平均分" :value="ov.avg_score" :decimals="1" color="#27AE60"
            :selected="ws.activeMetric === 'score'" @click="ws.toggleMetric('score')" />
          <MetricCard label="通过率" :value="passRate" :decimals="1" suffix="%" color="#F5A623"
            :selected="ws.activeMetric === 'pass'" @click="ws.toggleMetric('pass')" />
          <MetricCard label="待辅导学员" :value="ov.pending_tutor_count" color="#E74C3C" value-color="#E74C3C"
            hint="需关注" :selected="ws.activeMetric === 'attention'" @click="ws.toggleMetric('attention')" />
        </div>
      </section>
    </div>

    <!-- ===== 第二行：③ 五维诊断热点（60%） + ④ 需关注学员（40%） ===== -->
    <div class="row-mid">
      <!-- ③ 五维诊断热点 Top3（doc/04 §3.4） -->
      <section class="card diag-panel">
        <div class="card-title">
          五维诊断热点
          <span class="title-extra">
            <span class="link" @click="goReportsDiagnosis">查看更多 →</span>
          </span>
        </div>
        <div v-if="diagLoading" class="diag-loading">
          <div class="skel-line" style="height:52px;margin-bottom:8px"></div>
          <div class="skel-line" style="height:52px;margin-bottom:8px"></div>
          <div class="skel-line" style="height:52px"></div>
        </div>
        <el-empty v-else-if="!diagTop.length" description="暂无诊断结果，完成训练后自动生成" :image-size="72" />
        <div v-else class="diag-list">
          <DiagnosisItem v-for="(d, i) in diagTop" :key="i" :item="d" @click.stop="openDiagnosis(d)" />
        </div>
      </section>

      <!-- ④ 需关注学员（doc/04 §3.5：点击开 StudentDrawer，不跳页） -->
      <section class="card att-panel">
        <div class="card-title">需关注学员 <span class="title-extra">共 {{ filteredAttention.length }} 人</span></div>
        <el-empty v-if="!filteredAttention.length" description="暂无需关注学员" :image-size="72" />
        <div v-else class="att-list">
          <div v-for="s in filteredAttention" :key="s.student_id" class="att-row">
            <b class="att-name link" @click="openStudent(s)">{{ s.student_name || s.student_id }}</b>
            <span class="att-cls">{{ s.student_cls || '-' }}</span>
            <el-tag size="small" :type="attentionTag(s.reason).type">{{ attentionTag(s.reason).text }}</el-tag>
            <span class="att-detail ts" :title="s.detail">{{ s.detail }}</span>
            <span class="link" @click="openStudent(s)">查看</span>
          </div>
        </div>
      </section>
    </div>

    <!-- ===== 第三行：⑤ 最近完成轮次（表格，doc/04 §3.6） ===== -->
    <section class="card recent-panel">
      <div class="card-title">最近完成轮次
        <span class="title-extra"><span class="link" @click="go('/reports')">查看更多 →</span></span>
      </div>
      <el-table :data="filteredRecent" size="default" @row-click="(r) => openReport(r)">
        <el-table-column label="学员" min-width="110">
          <template #default="{ row }">
            <span class="link" @click.stop="openStudent(row)">{{ row.student_name || row.student_id || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="工序" width="90">
          <template #default="{ row }">{{ row.process_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="110">
          <template #default="{ row }">{{ fromNow(row.ts_upload_ms) }}</template>
        </el-table-column>
        <el-table-column label="用时" width="90" align="right">
          <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="得分" width="150">
          <template #default="{ row }"><ScoreTag :score="row.total_score" /></template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default><span class="link">查看详情</span></template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!filteredRecent.length" description="暂无完成的训练轮次" :image-size="72" />
    </section>
  </div>
</template>

<script setup>
/**
 * DashboardView.vue — 首页驾驶舱（doc/04 §三 / doc/05.1 §5.2 §六）
 * ①实时训练动态 ②今日概览（原地联动） ③五维诊断热点Top3 ④需关注学员 ⑤最近完成轮次。
 * 指标卡片/诊断/学员/轮次 → 原地联动 + Drawer；Route 切换仅"查看更多"入口。
 */
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElTable, ElTableColumn, ElTag, ElEmpty } from 'element-plus'
import { api } from '../api'
import { createRealtimeWS } from '../api/ws'
import { useWorkspaceStore, PROCESS_OPTIONS } from '../stores/workspace'
import { fmtDuration, fromNow, attentionTag, EVENT_KIND_STYLE, fmtClock } from '../utils/format'
import MetricCard from '../components/MetricCard.vue'
import ScoreTag from '../components/ScoreTag.vue'
import DiagnosisItem from '../components/DiagnosisItem.vue'
import EvidenceThumb from '../components/EvidenceThumb.vue'

const router = useRouter()
const ws = useWorkspaceStore()
const go = (p) => router.push(p)

// ---- 数据 ----
const ov = ref({})                                   // today_summary
const rt = reactive({ devices: [] })                 // realtime_progress
const eventsByDevice = reactive({})                  // device_id → 最近10条事件（WS 增量）
const attention = ref([])                            // 需关注学员
const diagTop = ref([])                              // 诊断热点 Top3
const diagLoading = ref(true)
const recent = ref([])                               // 最近完成轮次（10 条，前端联动过滤后展示 5）
const hasActive = computed(() => rt.devices.some((d) => (d.total ?? 0) > (d.done ?? 0)))

// ---- 工序/指标联动过滤（doc/05.1 §2.4 工作台联动） ----
const filteredAttention = computed(() => {
  let list = attention.value
  if (ws.process) list = list.filter((s) => !s.process_name || s.process_name === ws.process)
  if (ws.activeMetric === 'attention') return list.slice(0, 5)
  return list
})
const filteredRecent = computed(() => {
  let list = recent.value
  if (ws.process) list = list.filter((r) => !r.process_name || r.process_name === ws.process)
  if (ws.activeMetric === 'pass') list = list.filter((r) => r.total_score >= 60)
  if (ws.activeMetric === 'score') list = [...list].sort((a, b) => (b.total_score ?? 0) - (a.total_score ?? 0))
  if (ws.activeMetric === 'exam') list = list.slice(0, 10)
  return list.slice(0, 5)
})
const passRate = computed(() => (ov.value.pass_rate != null ? ov.value.pass_rate * 100 : null))

// ---- 概览联动到报告列表（点考试人数→报告列表，doc/04 §3.3 保留跳转语义） ----
watch(() => ws.activeMetric, (m) => {
  if (m === 'exam' || m === 'score' || m === 'pass') {
    // 概览点击即过滤本页区域；如需完整列表可再点"查看更多"
  }
})

// ---- 加载 ----
async function loadOverview() {
  ov.value = await api.todaySummary({ process_name: ws.process }).catch(() => ({}))
}
async function loadRealtime() {
  const d = await api.realtimeProgress().catch(() => null)
  rt.devices = d?.devices || d || []
}
async function loadAttention() {
  const a = await api.attentionStudents().catch(() => null)
  attention.value = a?.students || a || []
}
async function loadDiagnosis() {
  diagLoading.value = true
  try {
    const d = await api.diagnosis({ scope: 'class', ...ws.analysisParams }).catch(() => null)
    // 仅步骤级诊断进热点（student 级在区域④呈现），按 metric/threshold 偏差排序取 Top3
    const list = (d?.diagnoses || []).filter((x) => (x.target_id || '').startsWith('step_'))
    list.sort((a, b) => {
      const ra = a.threshold_value ? a.metric_value / a.threshold_value : 0
      const rb = b.threshold_value ? b.metric_value / b.threshold_value : 0
      return rb - ra
    })
    diagTop.value = list.slice(0, 3)
  } finally {
    diagLoading.value = false
  }
}
async function loadRecent() {
  const d = await api.listReports({ page: 1, page_size: 10 }).catch(() => null)
  recent.value = d?.list || []
}

function loadAll() {
  loadOverview(); loadAttention(); loadDiagnosis(); loadRecent()
}

// ---- 工序切换 → 重新拉取（联动刷新） ----
watch(() => ws.process, () => { loadAll() })

// ---- 实时推送：WS 增量 → 事件流 + 进度（断线兜底轮询 5s） ----
let wsConn = null
const timers = []
function onWsMessage(msg) {
  if (msg.type === 'realtime_progress' && msg.data) {
    const { device_id, progress, events } = msg.data
    if (device_id && events?.length) {
      // 引擎单调 ts → 墙钟近似：以本批到达时刻为锚，批内最大 ts 对齐 now（05.1 §6.1 事件流时间戳）
      const nowMs = Date.now()
      const maxTs = Math.max(...events.map((e) => e.ts || 0))
      const stamped = events.map((e) => ({ ...e, _wall: nowMs - (maxTs - (e.ts || 0)) }))
      const list = eventsByDevice[device_id] || []
      eventsByDevice[device_id] = [...stamped, ...list].slice(0, 10)
    }
    loadRealtime()
  }
}
onMounted(() => {
  loadAll(); loadRealtime()
  wsConn = createRealtimeWS({ onMessage: onWsMessage })
  timers.push(setInterval(loadRealtime, 5000))       // doc/04 §3.2 每 2~5s 轮询兜底
  timers.push(setInterval(loadOverview, 60000))
})
onUnmounted(() => {
  timers.forEach(clearInterval)
  wsConn && wsConn.close()
})

// ---- 展示辅助 ----
function progPct(d) {
  if (!d.total) return 0
  return Math.min(100, Math.max(0, Math.round((d.done / d.total) * 100)))
}
function isOvertime(d) {
  return false // 标准用时对比需子步骤数据，实时流只给已用时长；超时事件在事件流中以 ⚠ 呈现
}
function eventsOf(deviceId) { return eventsByDevice[deviceId] || [] }
/** 最新抓拍缩略图（doc/05.1 §6.1 区域①底部）：取该设备最新一条证据（缓存，避免每帧请求） */
const snapCache = {}
function latestSnap(deviceId) {
  if (snapCache[deviceId] !== undefined) return snapCache[deviceId]
  snapCache[deviceId] = null
  api.listEvidence({ device_id: deviceId, limit: 1 })
    .then((res) => {
      const list = res?.evidence || res?.list || []
      snapCache[deviceId] = (list[0]?.jpg_path || list[0]?.thumb_path) ? list[0] : null
    })
    .catch(() => { snapCache[deviceId] = null })
  return null
}
function evClock(d, ev) {
  return ev?._wall ? fmtClock(ev._wall) : '--:--:--'
}
function kindStyle(kind) {
  return EVENT_KIND_STYLE[kind] || { icon: '·', cls: 'ev-finish', label: '事件' }
}

// ---- Drawer 入口 ----
function openStudent(s) {
  ws.openDrawer('student', {
    student_id: s.student_id || '',
    student_name: s.student_name, student_cls: s.student_cls,
    reason: s.reason, detail: s.detail,
  })
}
function openReport(r) { ws.openDrawer('report', { report_id: r.report_id }) }
function openDiagnosis(d) { ws.openDrawer('diagnosis', d) }
function goReportsDiagnosis() { go('/reports') }
</script>

<style scoped>
/* ===== 第一行 40/60 ===== */
.row-top { display: grid; grid-template-columns: 2fr 3fr; gap: 16px; align-items: stretch; }
.row-top + .row-mid { margin-top: 16px; }

/* ① 实时训练动态 */
.rt-panel { min-height: 300px; display: flex; flex-direction: column; }
.rt-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 32px 0; }
.rt-empty-icon { width: 44px; height: 44px; border-radius: 50%; background: var(--c-primary-light);
  box-shadow: inset 0 0 0 6px rgba(43, 92, 230, .06); }
.rt-empty-title { color: var(--c-text-sub); }
.rt-empty-sub { font-size: var(--fs-aux); color: var(--c-text-weak); }
.rt-devices { display: flex; flex-direction: column; gap: 14px; margin-top: 12px; overflow: auto; }
.rt-device { padding: 10px 12px; border-radius: var(--radius-sm);
  background: var(--c-bg); transition: background var(--t-fast); }
.rt-device:hover { background: var(--c-bg-deep); }
.rt-head { display: flex; align-items: center; gap: 8px; }
.rt-student { font-size: var(--fs-h3); }
.rt-device-id { margin-left: auto; }
.rt-progress { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
.rt-bar { flex: 1; height: 8px; border-radius: 4px; background: var(--c-bg-deep); overflow: hidden; }
.rt-fill { height: 100%; border-radius: 4px; transition: width .4s ease; background: var(--c-primary); }
.rt-frac { font-size: var(--fs-aux); color: var(--c-text-sub); font-variant-numeric: tabular-nums; }
.rt-current { margin-top: 4px; font-size: var(--fs-body); color: var(--c-text-sub); }
.rt-elapsed { margin-left: 8px; font-size: var(--fs-aux); color: var(--c-text-weak); }
.rt-elapsed.overtime { color: var(--c-warning); font-weight: 600; }
.rt-events { margin-top: 8px; border-top: 1px dashed var(--c-divider); padding-top: 6px; max-height: 150px; overflow: auto; }
.rt-snap { margin-top: 8px; display: flex; align-items: flex-end; gap: 8px; }
.rt-snap-label { line-height: 90px; }
.rt-ev { display: flex; align-items: center; gap: 8px; padding: 2px 0; font-size: var(--fs-aux); }
.rt-ev-icon { width: 14px; text-align: center; }
.rt-ev-text { color: var(--c-text-sub); }

/* ② 概览（doc/04.1 §3.1：区域② 高 160px；用户反馈：4 卡 2×2 网格，等高对齐左栏） */
.ov-panel { display: flex; min-height: 160px; height: 100%; }
.ov-grid { flex: 1; display: grid; grid-template-columns: repeat(2, 1fr); grid-template-rows: repeat(2, 1fr); gap: 12px; }
.ov-grid .metric-card { min-height: 0; height: 100%; }
.ov-grid .metric-card .metric-body { padding: 10px 18px; gap: 2px; }
.ov-grid .metric-card .metric-num { font-size: 24px; line-height: 32px; }

/* ===== 第二行 60/40 ===== */
.row-mid { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; }
.diag-panel { min-height: 320px; }
.diag-loading, .diag-list { margin-top: 12px; display: flex; flex-direction: column; gap: 10px; }
.att-panel { min-height: 320px; }
.att-list { margin-top: 8px; display: flex; flex-direction: column; }
.att-row { display: flex; align-items: center; gap: 10px; padding: 10px 6px; border-radius: var(--radius-sm);
  border-bottom: 1px solid var(--c-divider); transition: background var(--t-fast); }
.att-row:hover { background: var(--c-bg); }
.att-row:last-child { border-bottom: none; }
.att-name { font-size: var(--fs-h3); flex: none; }
.att-cls { color: var(--c-text-sub); font-size: var(--fs-aux); }
.att-detail { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ⑤ 最近完成轮次 */
.recent-panel { margin-top: 16px; }
.recent-panel .el-table { margin-top: 8px; }
.recent-panel :deep(.el-table__row) { cursor: pointer; }
</style>
