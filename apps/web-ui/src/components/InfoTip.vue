<template>
  <el-tooltip :content="text" placement="top" :show-after="150" effect="dark">
    <el-icon class="info-tip" :size="14"><QuestionFilled /></el-icon>
  </el-tooltip>
</template>

<script setup>
/**
 * InfoTip.vue — 标题旁问号提示（hover 显示模块功能点说明）
 * 用于首页各区域 card-title；无点击行为，纯 hover，不打断浏览。
 */
import { QuestionFilled } from '@element-plus/icons-vue'

defineProps({
  /** hover 显示的说明文本 */
  text: { type: String, required: true },
})
</script>

<style scoped>
.info-tip {
  color: var(--c-text-weak);
  cursor: help;
  flex: none;
  transition: color var(--t-fast);
}
.info-tip:hover { color: var(--c-primary); }
</style>
