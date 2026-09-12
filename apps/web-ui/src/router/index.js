import { createRouter, createWebHistory } from 'vue-router'

// P7 方案A: history 模式, base=/ui/；未匹配路由由平台侧 SPA fallback 回落 index.html
const routes = [
  { path: '/', name: 'screen', component: () => import('../views/ScreenView.vue') },
  { path: '/screen', redirect: '/' },
  { path: '/reports', component: () => import('../views/ReportsView.vue') },
  { path: '/diagnosis', component: () => import('../views/DiagnosisView.vue') },
  { path: '/teaching', component: () => import('../views/TeachingView.vue') },
  { path: '/dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/students', component: () => import('../views/StudentsView.vue') },
  { path: '/settings', component: () => import('../views/SettingsView.vue') },
]

export default createRouter({
  history: createWebHistory('/ui/'),
  routes,
})
