<template>
  <div class="diag-item card">
    <div class="diag-row" @click="expanded = !expanded">
      <span class="diag-warn">⚠</span>
      <span class="diag-text">{{ item.metric_label || descText }}</span>
      <el-icon class="diag-arrow" :class="{ open: expanded }"><ArrowDown /></el-icon>
    </div>
    <div class="diag-advice">💡 建议：{{ item.advice_text || '结合课堂表现调整教学重点' }}</div>
    <div v-if="evidence.length" class="diag-evidence">
      <EvidenceThumb v-for="ev in evidence" :key="ev.id" :item="ev" :width="80" :height="60" />
    </div>

    <!-- 内嵌展开：该子步骤详情（doc/04 §3.4 点击展开详情） -->
    <ExpandPanel :visible="expanded" title="诊断详情" @close="expanded = false">
      <div class="diag-detail">
        <div class="dd-row"><span class="dd-k">诊断类型</span><span>{{ typeLabel }}</span></div>
        <div class="dd-row"><span class="dd-k">涉及对象</span><span>{{ item.target_id || '-' }}</span></div>
        <div class="dd-row"><span class="dd-k">指标值</span><span>{{ fmtMetric }}</span></div>
        <div class="dd-row"><span class="dd-k">阈值</span><span>{{ item.threshold_value ?? '-' }}</span></div>
        <div v-if="item.process_name" class="dd-row"><span class="dd-k">工序</span><span>{{ item.process_name }}</span></div>
        <slot name="detail" />
      </div>
    </ExpandPanel>
  </div>
</template>

<script setup>
/**
 * DiagnosisItem.vue — 诊断条目（doc/05.1 §6.3）
 * ⚠ 问题描述 + 💡 浅橙建议 + 证据缩略图；点击原地内嵌展开详情。
 */
import { ref, computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import EvidenceThumb from './EvidenceThumb.vue'
import ExpandPanel from './ExpandPanel.vue'
import { DIAG_TYPE_LABEL, fmtDurationFromMetric } from '../utils/diag'

const props = defineProps({
  item: { type: Object, required: true },
})
const expanded = ref(false)

const typeLabel = computed(() => DIAG_TYPE_LABEL[props.item.diagnosis_type] || props.item.diagnosis_type)
const evidence = computed(() => props.item.evidence || [])
const descText = computed(() => {
  const t = props.item.target_id || ''
  const step = t.startsWith('step_') ? `步骤${t.slice(5)} ` : ''
  return `${step}${typeLabel.value}异常`
})
const fmtMetric = computed(() => {
  const v = props.item.metric_value
  if (v == null) return '-'
  // 用时类指标（bottleneck/interval/stddev）为毫秒，格式化为可读时长
  if (['bottleneck', 'interval', 'stddev'].includes(props.item.diagnosis_type)) {
    return `${fmtDurationFromMetric(v)} (${v})`
  }
  // 比率类指标显示百分比
  return v <= 1 ? `${(v * 100).toFixed(1)}%` : String(v)
})
</script>

<style scoped>
.diag-item { padding: 12px 16px; border-left: 4px solid var(--c-warning); transition: border-color var(--t-fast), box-shadow var(--t-fast); }
.diag-item:hover { box-shadow: var(--shadow-hover); }
.diag-row { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.diag-warn { color: var(--c-warning); font-weight: 700; }
.diag-text { font-size: var(--fs-h3); font-weight: 600; color: var(--c-text-main); flex: 1; }
.diag-arrow { color: var(--c-text-weak); transition: transform var(--t-med); }
.diag-arrow.open { transform: rotate(180deg); }
.diag-advice {
  margin-top: 8px; font-size: var(--fs-body); color: var(--c-text-sub);
  background: var(--c-accent-light); border-radius: 4px; padding: 6px 10px;
}
.diag-evidence { display: flex; gap: 8px; margin-top: 8px; }
.diag-detail { display: flex; flex-direction: column; gap: 4px; }
.dd-row { display: flex; gap: 12px; font-size: var(--fs-body); }
.dd-k { color: var(--c-text-weak); width: 64px; flex: none; }
</style>
