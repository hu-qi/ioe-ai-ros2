<template>
  <div class="page-wrap">
    <!-- 头部：返回 + 标题（doc/04 §5.4） -->
    <div class="rd-head card">
      <span class="link rd-back" @click="goBack">← 返回</span>
      <b class="rd-title">报告详情</b>
      <el-button type="primary" plain size="small" style="margin-left:auto" @click="exportCsv">导出 PDF/CSV</el-button>
    </div>

    <div v-if="loading" class="card" style="margin-top:16px"><el-skeleton :rows="10" animated /></div>
    <template v-else-if="detail">
      <!-- 信息条：总分 28px + 等级 + 用时 + 完成率 -->
      <div class="rd-info card">
        <div class="rd-id">
          <b class="rd-student link" @click="goStudent">{{ detail.report.student_name || detail.report.student_id || '未知学员' }}</b>
          <el-tag size="small" type="info">{{ detail.report.student_cls || '-' }}</el-tag>
          <el-tag size="small">{{ detail.report.process_name || '-' }}</el-tag>
          <span class="ts">{{ fmtDateTime(detail.report.ts_upload_ms) }}</span>
        </div>
        <div class="rd-score-row">
          <div class="rd-total" :class="scoreCls">{{ detail.report.total_score ?? '-' }}</div>
          <div class="rd-grade" :class="scoreCls">{{ gradeText }}</div>
          <div class="rd-meta">
            <span>用时 <b>{{ fmtDuration(detail.report.duration_ms) }}</b></span>
            <span>完成率 <b>{{ completionRate }}</b></span>
            <span>结束方式 <b>{{ finishLabel }}</b></span>
          </div>
        </div>
      </div>

      <!-- 左：操作时间线（可按事件类型筛选） 右：子步骤得分明细 -->
      <div class="rd-cols">
        <section class="card">
          <div class="card-title">操作时间线</div>
          <div class="filter-bar" style="margin:8px 0">
            <el-radio-group v-model="evFilter" size="small">
              <el-radio-button label="all">全部</el-radio-button>
              <el-radio-button label="3">超时</el-radio-button>
              <el-radio-button label="2">中断</el-radio-button>
            </el-radio-group>
          </div>
          <div class="rd-timeline">
            <div v-for="(ev, i) in filteredEvents" :key="i" class="rd-ev">
              <span class="ts">{{ evClock(ev) }}</span>
              <span class="rd-ev-icon" :class="kindStyle(ev.kind).cls">{{ kindStyle(ev.kind).icon }}</span>
              <span class="rd-ev-text">
                {{ kindStyle(ev.kind).label }} {{ ev.sub ? `子步骤${ev.sub}` : (ev.step ? `步骤${ev.step}` : '') }}
              </span>
            </div>
            <el-empty v-if="!filteredEvents.length" description="无事件记录" :image-size="60" />
          </div>
        </section>

        <section class="card">
          <div class="card-title">子步骤得分明细</div>
          <el-table :data="detail.substeps" size="small" max-height="420">
            <el-table-column label="#" prop="idx" width="44" />
            <el-table-column label="子步骤" min-width="100">
              <template #default="{ row }">{{ row.name || `子步骤${row.idx}` }}</template>
            </el-table-column>
            <el-table-column label="用时" width="80" align="right">
              <template #default="{ row }">
                <span :class="{ 'ov-time': row.timeout }">{{ fmtDuration(row.duration_ms) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="标准" width="80" align="right">
              <template #default="{ row }">{{ row.std_duration_ms ? fmtDuration(row.std_duration_ms) : '-' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="72">
              <template #default="{ row }">
                <el-tag v-if="row.omitted" size="small" type="danger">遗漏</el-tag>
                <el-tag v-else-if="row.state === 3" size="small" type="warning">中断</el-tag>
                <el-tag v-else-if="row.state === 2" size="small" type="success">完成</el-tag>
                <el-tag v-else size="small" type="info">未执行</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="得分" width="70" align="right">
              <template #default="{ row }">
                <span :class="rowCls(row.score)">{{ row.score != null ? row.score.toFixed(1) : '-' }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="rd-sum">合计：<b :class="scoreCls">{{ detail.report.total_score ?? '-' }}</b></div>
        </section>
      </div>

      <!-- 证据图墙（按子步骤分组，doc/04 §5.4） -->
      <section class="card" style="margin-top:16px">
        <div class="card-title">证据图墙</div>
        <div v-if="loadingEvidence" class="rd-ev-loading"><el-skeleton :rows="2" animated /></div>
        <el-empty v-else-if="!evidenceGroups.length" description="本轮训练无抓拍证据" :image-size="72" />
        <div v-else class="rd-ev-groups">
          <div v-for="g in evidenceGroups" :key="g.sub" class="rd-ev-group">
            <div class="rd-ev-group-title">子步骤 {{ g.sub }} {{ g.name }}</div>
            <div class="rd-ev-thumbs">
              <EvidenceThumb v-for="ev in g.items" :key="ev.id" :item="ev" :width="120" :height="90"
                @click.stop="openGroup(g, ev)" />
            </div>
          </div>
        </div>
      </section>
    </template>
    <el-empty v-else description="报告不存在" style="margin-top:48px" />
  </div>
</template>

<script setup>
/**
 * ReportDetailView.vue — 报告详情（doc/04 §5.4 独立页面）
 * 信息条 + 时间线(类型筛选) + 子步骤得分明细 + 证据图墙(按子步骤分组)。
 * 抓拍缩略图点击 → Lightbox 内嵌展开大图（组内 ←/→ 切换）。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElTag, ElTable, ElTableColumn, ElRadioGroup, ElRadioButton, ElButton, ElEmpty, ElSkeleton } from 'element-plus'
import { api } from '../api'
import { fmtDateTime, fmtDuration, fmtClock, gradeOf, FINISH_REASON_LABEL, EVENT_KIND_STYLE } from '../utils/format'
import EvidenceThumb from '../components/EvidenceThumb.vue'
import { useLightbox } from '../components/lightbox'
import { echarts } from '../echarts'

const route = useRoute()
const router = useRouter()
const reportId = computed(() => decodeURIComponent(route.params.id || ''))

const loading = ref(true)
const detail = ref(null)
const evFilter = ref('all')

const loadingEvidence = ref(false)
const evidenceGroups = ref([])   // [{sub, name, items: [evidence]}]

const gradeText = computed(() => gradeOf(detail.value?.report?.total_score ?? null).text)
const scoreCls = computed(() => {
  const v = detail.value?.report?.total_score
  return v == null ? '' : 'g-' + gradeOf(Number(v)).type
})
const finishLabel = computed(() => FINISH_REASON_LABEL[detail.value?.report?.finish_reason] || detail.value?.report?.finish_reason || '-')
const completionRate = computed(() => {
  const subs = detail.value?.substeps || []
  if (!subs.length) return '-'
  const done = subs.filter((s) => s.state === 2).length
  return Math.round((done / subs.length) * 100) + '%'
})
const filteredEvents = computed(() => {
  const evs = detail.value?.events || []
  if (evFilter.value === 'all') return evs
  return evs.filter((e) => String(e.kind) === evFilter.value)
})

function rowCls(v) {
  if (v == null) return ''
  return 'g-' + gradeOf(Number(v)).type
}
function kindStyle(kind) {
  return EVENT_KIND_STYLE[kind] || { icon: '·', cls: 'ev-finish', label: '事件' }
}
function evClock(ev) {
  const start = detail.value?.report?.start_ms
  if (start && ev.ts != null) return fmtClock(start + ev.ts)
  return '-'
}

async function load() {
  loading.value = true
  try {
    detail.value = await api.getReport(reportId.value).catch(() => null)
  } finally {
    loading.value = false
  }
  loadEvidence()
}

/** 按子步骤分组拉取证据图 */
async function loadEvidence() {
  const rep = detail.value?.report
  if (!rep?.device_id) return
  loadingEvidence.value = true
  try {
    const d = await api.listEvidence({ device_id: rep.device_id, round_start_ms: rep.start_ms, limit: 200 }).catch(() => null)
    const items = (d?.evidence || []).filter((e) => e.jpg_path || e.thumb_path)
    const map = new Map()
    const nameByIdx = new Map((detail.value?.substeps || []).map((s) => [s.idx, s.name || '']))
    items.forEach((e) => {
      const sub = e.sub || 0
      if (!map.has(sub)) map.set(sub, { sub, name: nameByIdx.get(sub) || '', items: [] })
      map.get(sub).items.push(e)
    })
    evidenceGroups.value = [...map.values()].sort((a, b) => a.sub - b.sub)
  } finally {
    loadingEvidence.value = false
  }
}

/** 打开该组大图（Lightbox 组内切换） */
function openGroup(g, ev) {
  useLightbox().open(g.items, g.items.indexOf(ev))
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/reports')
}
function goStudent() {
  const sid = detail.value?.report?.student_id
  if (sid) router.push(`/students/${encodeURIComponent(sid)}`)
}

/** 导出：浏览器端生成明细 CSV（打印为 PDF 可用浏览器打印） */
function exportCsv() {
  const subs = detail.value?.substeps || []
  const rows = [
    ['报告', reportId.value],
    ['学员', detail.value?.report?.student_name || ''],
    ['工序', detail.value?.report?.process_name || ''],
    ['总分', detail.value?.report?.total_score ?? ''],
    [],
    ['子步骤', '名称', '用时(ms)', '标准(ms)', '得分'],
    ...subs.map((s) => [s.idx, s.name || `子步骤${s.idx}`, s.duration_ms ?? '', s.std_duration_ms ?? '', s.score ?? '']),
  ]
  const csv = '\uFEFF' + rows.map((r) => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `报告_${reportId.value}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

function onResize() { /* 预留图表 resize */ }
onMounted(() => { load(); window.addEventListener('resize', onResize) })
onUnmounted(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.rd-head { display: flex; align-items: center; gap: 12px; }
.rd-back { font-size: var(--fs-body); }
.rd-title { font-size: var(--fs-h1); }
.rd-info { margin-top: 16px; }
.rd-id { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.rd-student { font-size: var(--fs-h2); }
.rd-score-row { display: flex; align-items: baseline; gap: 14px; }
.rd-total { font-size: var(--fs-num); font-weight: 700; font-variant-numeric: tabular-nums; }
.rd-grade { font-size: var(--fs-num2); font-weight: 700; }
.g-success { color: var(--c-success); }
.g-primary { color: var(--c-primary); }
.g-warning { color: var(--c-accent); }
.g-danger { color: var(--c-danger); }
.rd-meta { margin-left: auto; display: flex; gap: 20px; font-size: var(--fs-aux); color: var(--c-text-weak); }
.rd-meta b { color: var(--c-text-main); }
.rd-cols { display: grid; grid-template-columns: 2fr 3fr; gap: 16px; margin-top: 16px; }
.rd-timeline { max-height: 420px; overflow: auto; display: flex; flex-direction: column; gap: 4px; }
.rd-ev { display: flex; align-items: center; gap: 10px; padding: 3px 0; }
.rd-ev-icon { width: 16px; text-align: center; font-size: 12px; }
.ov-time { color: var(--c-warning); font-weight: 600; }
.rd-sum { text-align: right; padding: 10px 8px 0; color: var(--c-text-sub); }
.rd-sum b { font-size: var(--fs-num2); }
.rd-ev-groups { display: flex; flex-direction: column; gap: 14px; margin-top: 8px; }
.rd-ev-group-title { font-size: var(--fs-h3); font-weight: 600; color: var(--c-text-sub); margin-bottom: 8px; }
.rd-ev-thumbs { display: flex; flex-wrap: wrap; gap: 10px; }
.rd-ev-loading { padding: 8px 0; }
</style>
