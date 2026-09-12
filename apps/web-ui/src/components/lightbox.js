/**
 * lightbox.js — 证据大图查看器全局单例注册（doc/05.1 §10.2 Lightbox）
 * App.vue 挂载 EvidenceLightbox 并 bind；任意组件 useLightbox().open(list, index) 打开。
 */
import { reactive } from 'vue'

const state = reactive({
  bindFn: null,
  list: [],   // 当前展示的证据列表([{id, sub, ts, ...}])
  index: 0,   // 当前下标
})

export function useLightbox() {
  return {
    state,
    bind(refComp) { state.bindFn = (list, idx) => refComp?.open?.(list, idx) },
    /** list: [{url, sub, ts}]，idx: 起始下标 */
    open(list, idx = 0) {
      if (state.bindFn) state.bindFn(list, idx)
    },
  }
}
