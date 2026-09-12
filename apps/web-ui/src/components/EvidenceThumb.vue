<template>
  <div class="ev-thumb" :style="{ width: width + 'px', height: height + 'px' }" @click.stop="open" v-if="url">
    <img :src="url" loading="lazy" alt="证据" />
    <span class="ev-tip">点击查看</span>
  </div>
  <div v-else class="ev-thumb ev-empty" :style="{ width: width + 'px', height: height + 'px' }">
    <span>无图</span>
  </div>
</template>

<script setup>
/**
 * EvidenceThumb.vue — 证据缩略图（doc/05.1 §12.2 EvidenceThumb）
 * 悬停放大 1.05 + "点击查看"提示；点击打开全局 Lightbox 大图（不弹窗跳页）。
 */
import { computed } from 'vue'
import { api } from '../api'
import { useLightbox } from './lightbox'

const props = defineProps({
  /** 证据记录（evidence 表行：含 id/jpg_path 等） */
  item: { type: Object, required: true },
  width: { type: Number, default: 96 },
  height: { type: Number, default: 72 },
})
const url = computed(() =>
  props.item?.id != null ? api.evidenceImageUrl(props.item.id, true) : ''
)

function open() {
  // 单图打开也走 Lightbox，支持 ←/→ 切换
  useLightbox().open([props.item], 0)
}
</script>

<style scoped>
.ev-thumb {
  position: relative; border-radius: 4px; overflow: hidden; cursor: pointer;
  background: #EEF1F5; flex: none;
}
.ev-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform .15s; }
.ev-thumb:hover img { transform: scale(1.05); }
.ev-tip {
  position: absolute; left: 0; right: 0; bottom: 0; padding: 1px 0;
  background: rgba(0,0,0,.45); color: #fff; font-size: 11px; text-align: center;
  opacity: 0; transition: opacity .15s;
}
.ev-thumb:hover .ev-tip { opacity: 1; }
.ev-empty { display: flex; align-items: center; justify-content: center; color: var(--c-text-weak); font-size: 12px; }
</style>
