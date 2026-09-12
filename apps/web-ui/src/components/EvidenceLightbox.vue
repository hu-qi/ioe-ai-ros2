<template>
  <Teleport to="body">
    <div v-if="state.list.length" class="lb-mask" @click.self="close">
      <div class="lb-header">
        <span class="lb-title">
          {{ current?.sub != null ? `子步骤 ${current.sub} 证据` : '证据查看' }}
          <span class="ts" style="margin-left:8px">{{ current ? fmtDateTime(current.ts || current.created_at) : '' }}</span>
        </span>
        <span class="lb-count">{{ state.index + 1 }} / {{ state.list.length }}</span>
        <span class="lb-close" @click="close">✕</span>
      </div>
      <div class="lb-body">
        <span class="lb-arrow" :class="{ disabled: state.index <= 0 }" @click.stop="prev">‹</span>
        <img :src="fullUrl" alt="证据大图" @click.stop />
        <span class="lb-arrow" :class="{ disabled: state.index >= state.list.length - 1 }" @click.stop="next">›</span>
      </div>
      <div class="lb-hint">← / → 切换 · Esc 关闭</div>
    </div>
  </Teleport>
</template>

<script setup>
/**
 * EvidenceLightbox.vue — 证据大图查看器（doc/05.1 §12.2）
 * 全屏遮罩 + 左右切换 + 键盘 ←/→/Esc；仅承载证据图片，不承载业务信息。
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { fmtDateTime } from '../utils/format'
import { useLightbox } from './lightbox'

const lb = useLightbox()
const state = lb.state

const current = computed(() => state.list[state.index] || null)
const fullUrl = computed(() =>
  current.value?.id != null ? api.evidenceImageUrl(current.value.id, false) : ''
)

function open(list, idx = 0) {
  state.list = list || []
  state.index = Math.min(Math.max(0, idx), state.list.length - 1)
}
function close() { state.list = []; state.index = 0 }
function prev() { if (state.index > 0) state.index -= 1 }
function next() { if (state.index < state.list.length - 1) state.index += 1 }

function onKey(e) {
  if (!state.list.length) return
  if (e.key === 'Escape') close()
  else if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))

defineExpose({ open })
</script>

<style scoped>
.lb-mask {
  position: fixed; inset: 0; z-index: 2000;
  background: rgba(15, 23, 42, .82);
  display: flex; flex-direction: column;
}
.lb-header {
  height: 48px; display: flex; align-items: center; gap: 16px;
  padding: 0 20px; color: #fff; font-size: var(--fs-body);
}
.lb-count { color: rgba(255,255,255,.7); font-size: var(--fs-aux); }
.lb-close { margin-left: auto; cursor: pointer; font-size: 18px; }
.lb-close:hover { opacity: .8; }
.lb-body { flex: 1; display: flex; align-items: center; justify-content: center; gap: 16px; min-height: 0; }
.lb-body img { max-width: 86%; max-height: 82%; object-fit: contain; border-radius: 4px; background: #fff; }
.lb-arrow {
  width: 44px; height: 44px; border-radius: 50%; background: rgba(255,255,255,.12);
  color: #fff; font-size: 28px; display: flex; align-items: center; justify-content: center;
  cursor: pointer; user-select: none; flex: none;
}
.lb-arrow:hover { background: rgba(255,255,255,.22); }
.lb-arrow.disabled { opacity: .3; cursor: default; }
.lb-hint { text-align: center; color: rgba(255,255,255,.5); font-size: var(--fs-aux); padding: 10px 0 16px; }
</style>
