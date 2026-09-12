<template>
  <span class="score-tag" :class="'t-' + type">
    <span class="score-num">{{ score != null ? score.toFixed(1) : '-' }}</span>
    <span class="score-grade">{{ grade }}</span>
  </span>
</template>

<script setup>
/**
 * ScoreTag.vue — 得分 + 等级标签（doc/05.1 §12.2）
 * 状态色按评分等级：优秀≥90 绿 / 良好≥75 蓝 / 合格≥60 橙 / 不合格<60 红
 */
import { computed } from 'vue'
import { gradeOf } from '../utils/format'

const props = defineProps({
  score: { type: [Number, String], default: null },
})
const g = computed(() => gradeOf(props.score == null || props.score === '' ? null : Number(props.score)))
const type = computed(() => g.value.type)
const grade = computed(() => g.value.text)
</script>

<style scoped>
.score-tag { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.score-num { font-weight: 700; font-variant-numeric: tabular-nums; }
.t-success .score-num, .t-success .score-grade { color: var(--c-success); }
.t-primary .score-num, .t-primary .score-grade { color: var(--c-primary); }
.t-warning .score-num, .t-warning .score-grade { color: var(--c-accent); }
.t-danger .score-num, .t-danger .score-grade { color: var(--c-danger); }
.t-info .score-num, .t-info .score-grade { color: var(--c-text-weak); }
.score-grade {
  font-size: 12px; padding: 1px 8px; border-radius: 4px; line-height: 18px;
}
.t-success .score-grade { background: rgba(39, 174, 96, .12); }
.t-primary .score-grade { background: var(--c-primary-light); }
.t-warning .score-grade { background: rgba(245, 166, 35, .14); }
.t-danger .score-grade { background: rgba(231, 76, 60, .12); }
.t-info .score-grade { background: #EEF1F5; }
</style>
