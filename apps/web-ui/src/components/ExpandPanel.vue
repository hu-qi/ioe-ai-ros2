<template>
  <div class="expand-panel" v-show="visible">
    <div class="expand-head">
      <span class="expand-title">{{ title }}</span>
      <span class="expand-close link" @click="$emit('close')">收起</span>
    </div>
    <div class="expand-body">
      <slot />
    </div>
  </div>
</template>

<script setup>
/**
 * ExpandPanel.vue — 通用内嵌展开容器（doc/04 §8.3 ExpandPanel）
 * 列表条目详情、诊断详情、证据大图的就地展开承载。
 */
defineProps({
  visible: { type: Boolean, default: false },
  title: { type: String, default: '详情' },
})
defineEmits(['close'])
</script>

<style scoped>
.expand-panel {
  border-top: 1px dashed var(--c-divider);
  margin-top: 10px; padding-top: 10px;
}
.expand-head { display: flex; align-items: center; margin-bottom: 8px; }
.expand-title { font-size: var(--fs-h3); font-weight: 600; color: var(--c-text-sub); }
.expand-close { margin-left: auto; font-size: var(--fs-aux); }
.expand-body { font-size: var(--fs-body); color: var(--c-text-main); }
</style>
