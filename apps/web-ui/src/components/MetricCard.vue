<template>
  <div class="card metric-card hoverable" :class="{ selected }" @click="$emit('click')">
    <div class="metric-body">
      <div class="metric-label"><span class="metric-dot" :style="{ background: color }"></span>{{ label }}</div>
      <div class="metric-num" :style="{ color: valueColor || color }">
        {{ display }}<span v-if="suffix" class="metric-suffix">{{ suffix }}</span>
      </div>
      <div class="metric-aux">
        <span v-if="delta != null" :class="delta >= 0 ? 'up' : 'down'">
          {{ delta >= 0 ? '↑' : '↓' }} {{ Math.abs(delta) }}{{ deltaUnit }}
        </span>
        <span v-else>&nbsp;</span>
        <span v-if="hint" class="aux-hint">{{ hint }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * MetricCard.vue — 指标卡片（doc/05.1 §6.2 / §12.2）
 * 白底圆角 + 左侧 4px 色条 + 数值 28px + 环比辅助文字。
 * 点击不跳页：由父级切换工作台筛选上下文（selected 为选中态）。
 */
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  decimals: { type: Number, default: 0 },
  suffix: { type: String, default: '' },
  color: { type: String, default: '#2B5CE6' },
  valueColor: { type: String, default: '' },
  delta: { type: Number, default: null },      // 环比变化数值
  deltaUnit: { type: String, default: '' },    // 如 '%' / '分'
  hint: { type: String, default: '' },         // 右侧固定提示（如"需关注"）
  selected: { type: Boolean, default: false },
})
defineEmits(['click'])

const display = computed(() => {
  if (props.value == null || props.value === '-') return '-'
  return typeof props.value === 'number' ? props.value.toFixed(props.decimals) : props.value
})
</script>

<style scoped>
/* Corporate Clean:去掉单侧粗色条,改为标题前小圆点;卡片本身由 .card 提供 border+shadow-sm */
.metric-card { display: flex; min-height: 128px; }
.metric-body { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.metric-label { font-size: var(--fs-h3); color: var(--c-text-sub); font-weight: 500; display: flex; align-items: center; gap: 6px; transition: color var(--t-fast); }
.metric-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.metric-card:hover .metric-label { color: var(--c-text-main); }
.metric-num { font-size: var(--fs-num); font-weight: 600; letter-spacing: -0.01em; line-height: var(--lh-num); font-variant-numeric: tabular-nums; }
.metric-suffix { font-size: 16px; font-weight: 500; margin-left: 2px; }
.metric-aux { font-size: var(--fs-aux); color: var(--c-text-weak); display: flex; gap: 8px; margin-top: auto; }
.metric-aux .up { color: var(--c-success); }
.metric-aux .down { color: var(--c-danger); }
/* 选中态:焦点环(含 offset)分离焦点指示,符合 WCAG */
.metric-card.selected { box-shadow: var(--ring-focus), var(--shadow-card); border-color: transparent; }
</style>
