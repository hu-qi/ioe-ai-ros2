<template>
  <el-drawer
    :model-value="visible"
    title="诊断详情"
    size="560px"
    :destroy-on-close="true"
    @close="ws.closeDrawer()"
  >
    <template v-if="item">
      <!-- 问题描述 + 指标偏差 + 建议（doc/05.1 §九 DiagnosisDrawer） -->
      <div class="dg-head card">
        <div class="dg-title">⚠ {{ item.metric_label || descText }}</div>
        <div class="dg-advice">💡 建议：{{ item.advice_text || '结合课堂表现调整教学重点' }}</div>
      </div>

      <div class="dg-facts">
        <div class="dg-fact"><div class="df-k">诊断类型</div><div class="df-v">{{ typeLabel }}</div></div>
        <div class="dg-fact"><div class="df-k">涉及对象</div><div class="df-v">{{ item.target_id || '-' }}</div></div>
        <div class="dg-fact"><div class="df-k">指标值</div><div class="df-v">{{ fmtMetric }}</div></div>
        <div class="dg-fact"><div class="df-k">阈值</div><div class="df-v">{{ item.threshold_value ?? '-' }}</div></div>
      </div>

      <!-- 关键证据 -->
      <div v-if="evidence.length" class="dg-section">关键证据</div>
      <div v-if="evidence.length" class="dg-evidence">
        <EvidenceThumb v-for="ev in evidence" :key="ev.id" :item="ev" :width="120" :height="90" />
      </div>

      <!-- 相关训练轮次（同步骤最近报告） -->
      <div v-if="relatedReports.length" class="dg-section">相关训练轮次</div>
      <div v-if="relatedReports.length" class="dg-reports">
        <div v-for="r in relatedReports" :key="r.report_id" class="dg-report-row" @click="openReport(r)">
          <span class="ts">{{ fmtDate(r.ts_upload_ms) }}</span>
          <span class="dg-name">{{ r.student_name || r.student_id || '-' }}</span>
          <span class="dg-proc">{{ r.process_name || '-' }}</span>
          <ScoreTag :score="r.total_score" />
        </div>
      </div>
    </template>
    <el-empty v-else description="诊断数据不可用" />
  </el-drawer>
</template>

<script setup>
/**
 * DiagnosisDrawer.vue — 单条诊断详情抽屉（doc/05.1 §九）
 * 问题描述/指标偏差/建议/关键证据/相关训练轮次；点击轮次切换 ReportDrawer（不套 Drawer）。
 */
import { computed, ref, watch } from 'vue'
import { ElDrawer, ElTag, ElEmpty } from 'element-plus'
import { useWorkspaceStore } from '../stores/workspace'
import { api } from '../api'
import { fmtDate, fmtDuration, DIAG_TYPE_LABEL } from '../utils/format'
import EvidenceThumb from './EvidenceThumb.vue'
import ScoreTag from './ScoreTag.vue'

const ws = useWorkspaceStore()

const visible = computed(() => ws.drawer === 'diagnosis')
const item = computed(() => (ws.drawer === 'diagnosis' ? ws.drawerPayload : null))

const relatedReports = ref([])
const evidence = computed(() => item.value?.evidence || [])

const typeLabel = computed(() => DIAG_TYPE_LABEL[item.value?.diagnosis_type] || item.value?.diagnosis_type || '-')
const descText = computed(() => {
  const t = item.value?.target_id || ''
  const step = t.startsWith('step_') ? `步骤${t.slice(5)} ` : ''
  return `${step}${typeLabel.value}异常`
})
const fmtMetric = computed(() => {
  const v = item.value?.metric_value
  if (v == null) return '-'
  if (['bottleneck', 'interval', 'stddev'].includes(item.value.diagnosis_type)) return fmtDuration(v)
  return v <= 1 ? `${(v * 100).toFixed(1)}%` : String(v)
})

async function load() {
  relatedReports.value = []
  const it = item.value
  if (!it) return
  // step 级诊断 → 下钻该步骤最近 5 份相关报告（doc/04 §3.4 涉及学员列表）
  const t = it.target_id || ''
  if (t.startsWith('step_')) {
    const idx = parseInt(t.slice(5), 10)
    if (!Number.isNaN(idx)) {
      const rep = await api.listReports({ step_index: idx, page: 1, page_size: 5 }).catch(() => null)
      relatedReports.value = rep?.list || []
    }
  }
}
watch(visible, (v) => { if (v) load() })

function openReport(r) {
  ws.openDrawer('report', { report_id: r.report_id })
}
</script>

<style scoped>
.dg-head { padding: 14px 16px; }
.dg-title { font-size: var(--fs-h3); font-weight: 600; color: var(--c-text-main); }
.dg-advice { margin-top: 8px; font-size: var(--fs-body); color: var(--c-text-sub); background: #FFF8E8; border-radius: 4px; padding: 6px 10px; }
.dg-facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }
.dg-fact { background: var(--c-bg); border-radius: 6px; padding: 8px 10px; }
.df-k { font-size: var(--fs-aux); color: var(--c-text-weak); }
.df-v { font-size: var(--fs-h3); font-weight: 600; margin-top: 2px; }
.dg-section { font-size: var(--fs-h3); font-weight: 600; margin: 16px 0 8px; padding-left: 8px; border-left: 3px solid var(--c-primary); }
.dg-evidence { display: flex; flex-wrap: wrap; gap: 8px; }
.dg-reports { display: flex; flex-direction: column; }
.dg-report-row { display: flex; align-items: center; gap: 12px; padding: 8px 4px; border-bottom: 1px solid var(--c-divider); cursor: pointer; border-radius: 4px; }
.dg-report-row:hover { background: var(--c-bg); }
.dg-name { font-weight: 600; }
.dg-proc { flex: 1; color: var(--c-text-sub); }
</style>
