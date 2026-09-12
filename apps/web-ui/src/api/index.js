/**
 * api.js — 统一 API 封装（P7 方案A: 同源相对路径，零 CORS）
 * 后端响应契约: {code:0|非0, message, data}；HTTP 4xx/5xx 也返回包裹体。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

// 响应拦截: code!=0 统一 Toast，并 reject
http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        ElMessage.error(body.message || `请求失败 (${body.code})`)
        return Promise.reject(new Error(body.message || `code=${body.code}`))
      }
      return body.data
    }
    return body
  },
  (err) => {
    const status = err.response?.status
    const msg = err.response?.data?.message || err.message
    ElMessage.error(status ? `请求失败 (${status}): ${msg}` : `网络错误: ${msg}`)
    return Promise.reject(err)
  }
)

/** 平台 API（P1~P6 交付的端点） */
export const api = {
  // 报告域
  listReports(params) { return http.get('/reports', { params }) },
  getReport(reportId) { return http.get(`/reports/${encodeURIComponent(reportId)}`) },
  // 证据（P3）
  listEvidence(params) { return http.get('/evidence', { params }) },
  evidenceImageUrl(id, thumb = true) {
    return `/api/v1/evidence/${id}/image${thumb ? '?thumb=1' : ''}`
  },
  // 诊断（P2/P4）
  diagnosis(params) { return http.get('/analysis/diagnosis', { params }) },
  // 教学闭环（P5）
  createTeachingAction(payload) { return http.post('/teaching_actions', payload) },
  listTeachingActions(params) { return http.get('/teaching_actions', { params }) },
  verifyTeachingAction(id) { return http.get(`/teaching_actions/${id}/verify`) },
  // 统计（P6）
  classSummary(params) { return http.get('/analysis/class_summary', { params }) },
  stepDuration(params) { return http.get('/analysis/step_duration', { params }) },
  studentCumulative(params) { return http.get('/analysis/student_cumulative', { params }) },
  // 看板（P6）
  todaySummary(params) { return http.get('/dashboard/today_summary', { params }) },
  topErrorPoints(params) { return http.get('/dashboard/top_error_points', { params }) },
  attentionStudents(params) { return http.get('/dashboard/attention_students', { params }) },
  realtimeProgress() { return http.get('/dashboard/realtime_progress') },
  // 数据大屏
  recentAlerts(params) { return http.get('/dashboard/recent_alerts', { params }) },
  scoreTrend(params) { return http.get('/dashboard/score_trend', { params }) },
  classComparison(params) { return http.get('/dashboard/class_comparison', { params }) },
  // 学员（端侧同步双模式：带分页参数 → 管理分页格式）
  listStudents(params) { return http.get('/students', { params }) },
  getStudent(id) { return http.get(`/students/${encodeURIComponent(id)}`) },
  createStudent(payload) { return http.post('/students', payload) },
  updateStudent(id, payload) { return http.put(`/students/${encodeURIComponent(id)}`, payload) },
  deleteStudent(id) { return http.delete(`/students/${encodeURIComponent(id)}`) },
  studentExportUrl(params) { return `/api/v1/students/export${params ? '?' + new URLSearchParams(params) : ''}` },
  // 配置热重载
  reloadConfig() { return http.post('/config/reload') },
  // 系统设置（诊断规则读写）
  getDiagnosisRules() { return http.get('/settings/diagnosis_rules') },
  saveDiagnosisRules(payload) { return http.put('/settings/diagnosis_rules', payload) },
  // 系统设置（评分规则读写 + 系统信息）
  getScoringRules() { return http.get('/settings/scoring_rules') },
  saveScoringRules(payload) { return http.put('/settings/scoring_rules', payload) },
  systemInfo() { return http.get('/settings/system_info') },
}

export default http
