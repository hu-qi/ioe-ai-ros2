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
  }),
  getters: {
    /** analysis 域通用过滤参数（date_start/date_end/process_name） */
    analysisParams(state) {
      const r = rangeToMs(state.rangeDays)
      return { date_start: r.date_start, date_end: r.date_end, process_name: state.process }
    },
  },
  actions: {
    setProcess(p) { this.process = p || '' },
    setRange(days) { this.rangeDays = days },
    toggleMetric(key) { this.activeMetric = this.activeMetric === key ? '' : key },
    openDrawer(name, payload = null) { this.drawer = name; this.drawerPayload = payload },
    closeDrawer() { this.drawer = ''; this.drawerPayload = null },
  },
})
