import { createRouter, createWebHistory } from 'vue-router'

// P7 方案A: history 模式, base=/ui/；未匹配路由由平台侧 SPA fallback 回落 index.html
// doc/04.1 三页核心 + 独立详情页（学员详情/报告详情/设置）
const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/students', name: 'students', component: () => import('../views/StudentsView.vue') },
  { path: '/students/:id', name: 'studentDetail', component: () => import('../views/StudentDetailView.vue') },
  { path: '/reports', name: 'reports', component: () => import('../views/ReportsView.vue') },
  { path: '/reports/:id', name: 'reportDetail', component: () => import('../views/ReportDetailView.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
  { path: '/screen', redirect: '/' },
]

export default createRouter({
  history: createWebHistory('/ui/'),
  routes,
})
