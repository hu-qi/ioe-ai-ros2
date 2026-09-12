/**
 * workspace.js — 工作台全局筛选状态（doc/05.1 §2.4 工作台联动 / §10.4 状态保持）
 * 全局工序/班级/时间筛选 + Drawer 状态，供首页/报告/学员页联动。
 */
import { defineStore } from 'pinia'

/** 工序选项（doc/04 §一：三种科目拆解/组装 + 全部） */
export const PROCESS_OPTIONS = ['拆解', '组装']

/** 时间范围选项（近 N 天） */
export const RANGE_OPTIONS = [
  { label: '今日', days: 1 },
  { label: '近7天', days: 7 },
  { label: '近30天', days: 30 },
  { label: '近90天', days: 90 },
]

export function rangeToMs(days) {
  if (!days) return { date_start: 0, date_end: 0 }
  return { date_start: Date.now() - days * 86400000, date_end: 0 }
}

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    process: '',        // ''=全部工序；'拆解'/'组装'
    rangeDays: 30,      // 时间范围（天），0=全部
    // 指标卡片选中态（首页联动过滤，doc/05.1 §6.2）：''/attention/…
    activeMetric: '',
    // Drawer 状态（同一时刻至多一个）
    drawer: '',         // ''/student/report/diagnosis
    drawerPayload: null,
    // Drawer 对象切换上下文（05.1 §10.4：连续查看支持上一条/下一条）
    drawerContext: null, // {items: [payload...], index}
  }),
  getters: {
    /** analysis 域通用过滤参数（date_start/date_end/process_name） */
    analysisParams(state) {
      const r = rangeToMs(state.rangeDays)
      return { date_start: r.date_start, date_end: r.date_end, process_name: state.process }
    },
    /** Drawer 是否可切换上/下一条（05.1 §10.4） */
    hasDrawerPrev(state) { return !!state.drawerContext && state.drawerContext.index > 0 },
    hasDrawerNext(state) {
      return !!state.drawerContext && state.drawerContext.index < state.drawerContext.items.length - 1
    },
  },
  actions: {
    setProcess(p) {
      this.process = p || ''
      this.syncQuery()
    },
    setRange(days) {
      this.rangeDays = days
      this.syncQuery()
    },
    toggleMetric(key) { this.activeMetric = this.activeMetric === key ? '' : key },
    /** 打开 Drawer；context = {items:[payload...], index} 时支持上一条/下一条切换 */
    openDrawer(name, payload = null, context = null) {
      this.drawer = name
      this.drawerPayload = payload
      this.drawerContext = context
    },
    closeDrawer() {
      this.drawer = ''
      this.drawerPayload = null
      this.drawerContext = null
    },
    /** Drawer 内切换上(-1)/下(+1)一个对象（不关抽屉、局部刷新） */
    drawerStep(delta) {
      const ctx = this.drawerContext
      if (!ctx || !ctx.items?.length) return
      const next = Math.min(Math.max(0, ctx.index + delta), ctx.items.length - 1)
      if (next === ctx.index) return
      ctx.index = next
      this.drawerPayload = ctx.items[next]
    },
    get hasDrawerPrev() { return !!this.drawerContext && this.drawerContext.index > 0 },
    get hasDrawerNext() {
      return !!this.drawerContext && this.drawerContext.index < this.drawerContext.items.length - 1
    },
    /** 筛选条件写入 URL Query（doc/05.1 §10.4 状态保持：刷新后可恢复主要筛选） */
    syncQuery() {
      const q = new URLSearchParams(window.location.search)
      q.set('process', this.process || '')
      q.set('range', String(this.rangeDays))
      const s = q.toString() ? `?${q.toString()}` : window.location.pathname
      window.history.replaceState(window.history.state, '', s)
    },
    /** 从 URL Query 恢复（App 挂载时调用一次） */
    restoreFromQuery() {
      const q = new URLSearchParams(window.location.search)
      const p = q.get('process')
      if (p && PROCESS_OPTIONS.includes(p)) this.process = p
      const r = parseInt(q.get('range'), 10)
      if (RANGE_OPTIONS.some((o) => o.days === r)) this.rangeDays = r
    },
  },
})
