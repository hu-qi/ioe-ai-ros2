import { createRouter, createWebHistory } from 'vue-router'

// P7 方案A: history 模式, base=/ui/；未匹配路由由平台侧 SPA fallback 回落 index.html
// doc/04.1 三页核心 + 独立详情页（学员详情/报告详情/设置）
// 懒加载 chunk 失败(发布后旧入口引用已删 chunk)时自动整页刷新一次兜底陈旧缓存
const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/students', name: 'students', component: () => import('../views/StudentsView.vue') },
  { path: '/students/:id', name: 'studentDetail', component: () => import('../views/StudentDetailView.vue') },
  { path: '/reports', name: 'reports', component: () => import('../views/ReportsView.vue') },
  { path: '/reports/:id', name: 'reportDetail', component: () => import('../views/ReportDetailView.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
  { path: '/screen', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory('/ui/'),
  routes,
})

router.onError((error, to) => {
  // chunk 加载失败(陈旧缓存/发版切换): 强制整页加载目标路由, 拿到最新入口
  const isChunkErr = /dynamically imported module|Importing a module script failed|Loading chunk/i.test(String(error?.message || error))
  if (isChunkErr && !sessionStorage.getItem('ui_chunk_reload')) {
    sessionStorage.setItem('ui_chunk_reload', '1')
    window.location.href = to?.fullPath ? `/ui${to.fullPath === '/' ? '' : to.fullPath}` : '/ui/'
  }
})

export default router
