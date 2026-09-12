/**
 * diag.js — 诊断域展示辅助（doc/04 §3.4 / doc/05.1 §6.3）
 */
export const DIAG_TYPE_LABEL = {
  bottleneck: '平均用时',
  persistent_error: '操作错误',
  sequence_chaos: '顺序错误',
  interval: '步骤间隔',
  stddev: '用时波动',
  student_regression: '成绩退步',
}

/** 毫秒数值格式化（诊断 metric_value 展示用） */
export function fmtDurationFromMetric(ms) {
  if (ms == null) return '-'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}
