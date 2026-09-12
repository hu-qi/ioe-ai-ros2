<template>
  <el-drawer
    :model-value="visible"
    title="训练报告速览"
    size="680px"
    :destroy-on-close="true"
    @close="ws.closeDrawer()"
  >
    <div v-if="loading" class="dw-loading"><el-skeleton :rows="8" animated /></div>
    <template v-else-if="detail">
      <!-- 头部信息条：总分 28px + 等级 + 用时 + 完成率（doc/05.1 §七） -->
      <div class="rp-head card">
        <div class="rp-id">
          <b>{{ detail.report.student_name || detail.report.student_id || '未知学员' }}</b>
          <el-tag size="small" type="info">{{ detail.report.student_cls || '-' }}</el-tag>
          <el-tag size="small">{{ detail.report.process_name || '-' }}</el-tag>
          <span class="ts">{{ fmtDateTime(detail.report.ts_upload_ms) }}</span>
        </div>
        <div class="rp-score-row">
          <div class="rp-total" :class="scoreCls(detail.report.total_score)">
            {{ detail.report.total_score ?? '-' }}
          </div>
          <div class="rp-grade" :class="scoreCls(detail.report.total_score)">{{ gradeText }}</div>
          <div class="rp-meta">
            <div>用时 <b>{{ fmtDuration(detail.report.duration_ms) }}</b></div>
            <div>结束方式 <b>{{ finishLabel }}</b></div>
          </div>
        </div>
      </div>

      <!-- 异常步骤（超时/中断子步骤） -->
      <template v-if="abnormalSubs.length">
        <div class="dw-section">异常步骤</div>
        <div class="rp-abnormal">
          <span v-for="s in abnormalSubs" :key="s.idx" class="rp-ab-item" :class="s.timeout ? 'a-timeout' : 'a-interrupt'">
            {{ s.timeout ? '⚠' : '✕' }} {{ s.name || `子步骤${s.idx}` }} {{ fmtDuration(s.duration_ms) }}
          </span>
        </div>
      </template>

      <!-- 子步骤得分明细 -->
      <div class="dw-section">子步骤得分明细</div>
      <el-table :data="detail.substeps" size="small" max-height="280">
        <el-table-column label="#" prop="idx" width="44" />
        <el-table-column label="子步骤" min-width="110">
          <template #default="{ row }">{{ row.name || `子步骤${row.idx}` }}</template>
        </el-table-column>
        <el-table-column label="用时" width="80" align="right">
          <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="标准" width="80" align="right">
          <template #default="{ row }">{{ row.std_duration_ms ? fmtDuration(row.std_duration_ms) : '-' }}</template>
        </el-table-column>
        <el-table-column label="得分" width="70" align="right">
          <template #default="{ row }">
            <span :class="scoreCls(row.score)">{{ row.score != null ? row.score.toFixed(1) : '-' }}</span>
          </template>
        </el-table-column>
      </el-table>

      <!-- 关键时间线（最近 8 条） -->
      <div class="dw-section">关键时间线</div>
      <div v-if="timeline.length" class="rp-timeline">
        <div v-for="(ev, i) in timeline" :key="i" class="rp-ev">
          <span class="ts">{{ evClock(ev) }}</span>
          <span class="rp-ev-icon" :class="kindStyle(ev.kind).cls">{{ kindStyle(ev.kind).icon }}</span>
          <span>{{ kindStyle(ev.kind).label }} {{ ev.sub ? `子步骤${ev.sub}` : '' }}</span>
        </div>
      </div>
      <el-empty v-else description="无事件记录" :image-size="60" />
    </template>
    <el-empty v-else description="报告不存在" />
    <template #footer>
      <el-button type="primary" @click="goFull">查看完整报告</el-button>
    </template>
  </el-drawer>
</template>

<script setup>
/**
 * ReportDrawer.vue — 报告速览抽屉（doc/05.1 §七 ReportDrawer）
 * 总分/等级/异常步骤/时间线摘要/子步骤得分；"查看完整报告"才进独立报告页。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElDrawer, ElSkeleton, ElTag, ElButton, ElEmpty, ElTable, ElTableColumn } from 'element-plus'
import { useWorkspaceStore } from '../stores/workspace'
import { api } from '../api'
import { fmtDateTime, fmtDuration, fmtClock, gradeOf, FINISH_REASON_LABEL, EVENT_KIND_STYLE } from '../utils/format'

const ws = useWorkspaceStore()
const router = useRouter()

const visible = computed(() => ws.drawer === 'report')
const payload = computed(() => (ws.drawer === 'report' ? ws.drawerPayload : null))

const loading = ref(false)
const detail = ref(null)

const gradeText = computed(() => gradeOf(detail.value?.report?.total_score ?? null).text)
const finishLabel = computed(() => FINISH_REASON_LABEL[detail.value?.report?.finish_reason] || detail.value?.report?.finish_reason || '-')
const abnormalSubs = computed(() =>
  (detail.value?.substeps || []).filter((s) => s.timeout || s.state === 3).slice(0, 8)
)
const timeline = computed(() => (detail.value?.events || []).slice(0, 8))

function scoreCls(v) {
  if (v == null || v === '') return ''
  return 'g-' + gradeOf(Number(v)).type
}
function kindStyle(kind) {
  return EVENT_KIND_STYLE[kind] || { icon: '·', cls: 'ev-finish', label: '事件' }
}
/** 事件 ts 为引擎单调 ms（相对 round_start），用报告 start_ms + ts 换算墙钟近似值 */
function evClock(ev) {
  const start = detail.value?.report?.start_ms
  if (start && ev.ts != null) return fmtClock(start + ev.ts)
  return '-'
}

async function load() {
  const rid = payload.value?.report_id
  if (!rid) { detail.value = null; return }
  loading.value = true
  try {
    detail.value = await api.getReport(rid).catch(() => null)
  } finally {
    loading.value = false
  }
}
watch(visible, (v) => { if (v) load() })

function goFull() {
  ws.closeDrawer()
  router.push(`/reports/${encodeURIComponent(payload.value.report_id)}`)
}
</script>

<style scoped>
.dw-loading { padding: 8px 0; }
.rp-head { padding: 14px 16px; margin-bottom: 4px; }
.rp-id { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.rp-score-row { display: flex; align-items: baseline; gap: 14px; }
.rp-total { font-size: var(--fs-num); font-weight: 700; line-height: var(--lh-num); font-variant-numeric: tabular-nums; }
.rp-grade { font-size: var(--fs-num2); font-weight: 700; }
.g-success { color: var(--c-success); }
.g-primary { color: var(--c-primary); }
.g-warning { color: var(--c-accent); }
.g-danger { color: var(--c-danger); }
.rp-meta { margin-left: auto; font-size: var(--fs-aux); color: var(--c-text-weak); display: flex; flex-direction: column; gap: 2px; text-align: right; }
.rp-meta b { color: var(--c-text-main); }
.dw-section { font-size: var(--fs-h3); font-weight: 600; margin: 14px 0 8px; padding-left: 8px; border-left: 3px solid var(--c-primary); }
.rp-abnormal { display: flex; flex-wrap: wrap; gap: 8px; }
.rp-ab-item { font-size: var(--fs-aux); border-radius: 4px; padding: 3px 10px; }
.a-timeout { background: rgba(230, 126, 34, .12); color: var(--c-warning); }
.a-interrupt { background: rgba(231, 76, 60, .1); color: var(--c-danger); }
.rp-timeline { display: flex; flex-direction: column; gap: 4px; }
.rp-ev { display: flex; align-items: center; gap: 10px; padding: 3px 0; }
.rp-ev-icon { width: 16px; text-align: center; font-size: 12px; }
</style>
