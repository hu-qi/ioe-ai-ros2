<template>
  <div class="page-header">
    <div class="ph-left">
      <h2 class="ph-title">
        {{ title }}
        <span v-if="subtitle" class="ph-sub">{{ subtitle }}</span>
      </h2>
    </div>
    <div v-if="$slots.actions" class="ph-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
/**
 * PageHeader — 各模块页统一页头：页面标题 + 副标题（左），主操作按钮（右）
 * 用法：
 *   <PageHeader title="学员管理" subtitle="学籍档案 · 批量导入导出">
 *     <template #actions><el-button type="primary">新增学员</el-button></template>
 *   </PageHeader>
 */
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px; }
.ph-title { margin: 0; font-size: 20px; font-weight: 700; color: #303133; display: flex; align-items: baseline; gap: 10px; }
.ph-sub { font-size: 13px; font-weight: 400; color: #909399; }
.ph-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
</style>
