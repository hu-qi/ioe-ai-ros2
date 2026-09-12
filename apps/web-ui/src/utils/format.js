/**
 * format.js — 通用格式化工具（doc/05.1 §4 字号排版 / 时间相对化）
 */

/** 相对时间：5分钟前 / 2小时前 / 3天前 / 兜底日期 */
export function fromNow(tsMs) {
  if (!tsMs) return '-'
  const diff = Date.now() - tsMs
  if (diff < 0) return '刚刚'
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m}分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}小时前`
  const d = Math.floor(h / 24)
  if (d < 30) return `${d}天前`
  return fmtDate(tsMs)
}

/** yyyy-MM-dd HH:mm */
export function fmtDateTime(tsMs) {
  if (!tsMs) return '-'
  const d = new Date(tsMs)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** HH:mm:ss（时间线用） */
export function fmtClock(tsMs) {
  if (!tsMs) return '-'
  const d = new Date(tsMs)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** yyyy-MM-dd */
export function fmtDate(tsMs) {
  if (!tsMs) return '-'
  const d = new Date(tsMs)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 毫秒 → 12m30s（秒 < 60 时显示 45s） */
export function fmtDuration(ms) {
  if (ms == null || ms < 0) return '-'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m${String(s % 60).padStart(2, '0')}s`
}

/** 得分 → 等级（评分规则 grade_levels: 优秀≥90/良好≥75/合格≥60/不合格<60） */
export function gradeOf(score) {
  if (score == null) return { text: '-', type: 'info' }
  if (score >= 90) return { text: '优秀', type: 'success' }
  if (score >= 75) return { text: '良好', type: 'primary' }
  if (score >= 60) return { text: '合格', type: 'warning' }
  return { text: '不合格', type: 'danger' }
}

/** 完成原因 → 中文 */
export const FINISH_REASON_LABEL = {
  completed: '正常完成',
  manual: '人工结束',
  timeout: '轮次超时',
  reset: '重置',
}

/** 事件 kind → 图标与颜色类（doc/05.1 §6.1：▶蓝/✓绿/⚠橙/✕红） */
export const EVENT_KIND_STYLE = {
  0: { icon: '▶', cls: 'ev-start', label: '开始' },
  1: { icon: '✓', cls: 'ev-done', label: '完成' },
  2: { icon: '✕', cls: 'ev-interrupt', label: '中断' },
  3: { icon: '⚠', cls: 'ev-timeout', label: '超时' },
  4: { icon: '■', cls: 'ev-finish', label: '正常结束' },
  5: { icon: '■', cls: 'ev-finish', label: '异常结束' },
}

/** 关注原因 → 标签（退步红/波动橙/薄弱蓝） */
export function attentionTag(reason) {
  switch (reason) {
    case 'student_regression': return { text: '退步预警', type: 'danger' }
    case 'volatility': return { text: '波动较大', type: 'warning' }
    case 'weak_step': return { text: '薄弱步骤', type: 'primary' }
    default: return { text: reason || '关注', type: 'info' }
  }
}

/** 诊断类型 → 中文名（doc/05.1 §五维） */
export const DIAG_TYPE_LABEL = {
  bottleneck: '平均用时',
  persistent_error: '操作错误',
  sequence_chaos: '顺序错误',
  interval: '步骤间隔',
  stddev: '用时波动',
  student_regression: '成绩退步',
}
