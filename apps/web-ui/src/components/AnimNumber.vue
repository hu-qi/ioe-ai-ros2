<template>
  <span class="anim-num">{{ display }}</span>
</template>

<script setup>
/**
 * AnimNumber — KPI 数字滚动动画（500ms easeOutCubic 过渡）
 * value 为 null/undefined 时显示 '-'；数值变化时从当前显示值滚动到新值。
 */
import { ref, watch, onUnmounted } from 'vue'

const props = defineProps({
  value: { type: Number, default: null },
  decimals: { type: Number, default: 0 },
  suffix: { type: String, default: '' },
})

const DURATION = 500
const display = ref(fmt(props.value))
let raf = null

function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return Number(v).toFixed(props.decimals) + props.suffix
}

watch(() => props.value, (nv, ov) => {
  // 从非数字（'-'）进入数字时不做滚动，直接落值
  if (nv === null || nv === undefined) { display.value = '-'; return }
  const from = parseFloat(display.value)
  const startVal = Number.isFinite(from) ? from : 0
  const to = Number(nv)
  const start = performance.now()
  cancelAnimationFrame(raf)
  const step = (t) => {
    const p = Math.min(1, (t - start) / DURATION)
    const ease = 1 - Math.pow(1 - p, 3)
    display.value = (startVal + (to - startVal) * ease).toFixed(props.decimals) + props.suffix
    if (p < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
})

onUnmounted(() => cancelAnimationFrame(raf))
</script>
