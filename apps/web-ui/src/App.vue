<template>
  <el-config-provider :locale="zhCn">
    <div class="app-shell">
      <!-- 顶部导航（56px 固定，doc/05.1 §5.1） -->
      <header class="top-nav">
        <div class="nav-left">
          <div class="nav-logo" @click="go('/')">
            <span class="logo-dot"></span>AI 智能教学分析平台
          </div>
          <nav class="nav-menu">
            <span class="nav-item" :class="{ active: isActive('/') }" @click="go('/')">首页</span>
            <span class="nav-item" :class="{ active: isActive('/students') }" @click="go('/students')">学员</span>
            <span class="nav-item" :class="{ active: isActive('/reports') }" @click="go('/reports')">报告</span>
          </nav>
        </div>
        <div class="nav-right">
          <!-- 全局工序筛选（doc/04 §一：所有界面支持工序筛选） -->
          <el-select
            :model-value="ws.process"
            class="proc-select"
            size="small"
            placeholder="工序：全部"
            @change="ws.setProcess"
          >
            <el-option label="工序：全部" value="" />
            <el-option v-for="p in PROCESS_OPTIONS" :key="p" :label="'工序：' + p" :value="p" />
          </el-select>
          <el-tooltip content="系统设置" placement="bottom">
            <span class="nav-icon" @click="go('/settings')"><el-icon><Setting /></el-icon></span>
          </el-tooltip>
        </div>
      </header>

      <!-- 内容区（最大 1600px 居中） -->
      <main class="app-content">
        <router-view />
      </main>
    </div>

    <!-- 全局 Drawer 体系（doc/05.1 §10.3：StudentDrawer / ReportDrawer / DiagnosisDrawer） -->
    <StudentDrawer />
    <ReportDrawer />
    <DiagnosisDrawer />
    <EvidenceLightbox ref="lightboxRef" />

    <!-- 全局搜索（doc/05.1 §10.5：Ctrl+F） -->
    <el-dialog v-model="searchVisible" title="全局搜索（学员 / 报告）" width="520px" @closed="searchKeyword = ''">
      <el-input v-model="searchKeyword" placeholder="输入姓名 / 学号 / 报告号，回车搜索" clearable autofocus @keyup.enter="doSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <div v-if="searching" class="gs-loading"><el-skeleton :rows="2" animated /></div>
      <template v-else-if="searchDone">
        <template v-if="searchResults.students.length">
          <div class="gs-section">学员</div>
          <div v-for="s in searchResults.students" :key="s.id" class="gs-row" @click="goStudent(s.id)">
            <b>{{ s.name }}</b><span class="gs-meta">{{ s.id }} · {{ s.cls || '-' }}</span>
            <span class="link">查看</span>
          </div>
        </template>
        <template v-if="searchResults.reports.length">
          <div class="gs-section">报告</div>
          <div v-for="r in searchResults.reports" :key="r.report_id" class="gs-row" @click="goReport(r.report_id)">
            <span class="ts">{{ r.report_id }}</span><span class="gs-meta">{{ r.student_name || r.student_id }} · {{ r.process_name }}</span>
            <span class="link">查看</span>
          </div>
        </template>
        <el-empty v-if="!searchResults.students.length && !searchResults.reports.length"
          description="无匹配结果" :image-size="60" />
      </template>
    </el-dialog>
  </el-config-provider>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Setting, Search } from '@element-plus/icons-vue'
import { ElDialog, ElInput, ElIcon, ElEmpty, ElSkeleton } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useWorkspaceStore, PROCESS_OPTIONS } from './stores/workspace'
import StudentDrawer from './components/StudentDrawer.vue'
import ReportDrawer from './components/ReportDrawer.vue'
import DiagnosisDrawer from './components/DiagnosisDrawer.vue'
import EvidenceLightbox from './components/EvidenceLightbox.vue'
import { useLightbox } from './components/lightbox'
import { api } from './api'

const route = useRoute()
const router = useRouter()
const ws = useWorkspaceStore()

const isActive = (prefix) =>
  prefix === '/' ? route.path === '/' : route.path.startsWith(prefix)
const go = (path) => router.push(path)

// ---- EvidenceLightbox 全局单例（EvidenceThumb 通过 useLightbox() 调用） ----
const lightboxRef = ref(null)
useLightbox().bind(lightboxRef)

// ---- 键盘：Esc 关 Drawer；Ctrl+F 全局搜索（doc/05.1 §10.5） ----
const searchVisible = ref(false)
const searchKeyword = ref('')
const searching = ref(false)
const searchDone = ref(false)
const searchResults = ref({ students: [], reports: [] })

function onKeydown(e) {
  if (e.key === 'Escape' && ws.drawer) { ws.closeDrawer(); return }
  if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'F')) {
    e.preventDefault()
    searchVisible.value = true
  }
}

/** 浏览器后退优先关闭 Drawer，而不是离开工作台（doc/05.1 §10.3） */
function onPopstate() {
  if (ws.drawer) ws.closeDrawer()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('popstate', onPopstate)
  // 筛选条件从 URL Query 恢复（doc/05.1 §10.4 状态保持）
  ws.restoreFromQuery()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('popstate', onPopstate)
})

// ---- 全局搜索：学员 + 报告并行检索 ----
async function doSearch() {
  const kw = searchKeyword.value.trim()
  if (!kw) return
  searching.value = true
  searchDone.value = false
  try {
    const [stu, rep] = await Promise.all([
      api.listStudents({ keyword: kw, page: 1, page_size: 10 }).catch(() => null),
      api.listReports({ student_id: kw, page: 1, page_size: 10 }).catch(() => null),
    ])
    searchResults.value = {
      students: stu?.list || [],
      reports: rep?.list || [],
    }
    searchDone.value = true
  } finally {
    searching.value = false
  }
}
function goStudent(id) {
  searchVisible.value = false
  router.push(`/students/${encodeURIComponent(id)}`)
}
function goReport(id) {
  searchVisible.value = false
  router.push(`/reports/${encodeURIComponent(id)}`)
}
</script>

<style>
@import './styles/design.css';

.app-shell { min-height: 100%; display: flex; flex-direction: column; }

/* ===== 顶部导航(bg-white + border gray-200,企业导航骨架) ===== */
.top-nav {
  height: var(--nav-h);
  background: var(--c-card);
  color: var(--c-text-main);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 100;
  border-bottom: 1px solid var(--c-divider);
}
.nav-left { display: flex; align-items: center; gap: 32px; }
.nav-logo { font-size: 16px; font-weight: 600; letter-spacing: -0.01em; cursor: pointer; display: flex; align-items: center; gap: 8px; color: var(--c-text-main); }
.logo-dot { width: 10px; height: 10px; border-radius: 3px; background: var(--c-primary); display: inline-block; }
.nav-menu { display: flex; gap: 6px; }
.nav-item {
  position: relative;
  padding: 6px 16px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--fs-body);
  font-weight: 500;
  color: var(--c-text-sub);
  transition: background var(--t-fast), color var(--t-fast);
}
.nav-item:hover { background: var(--c-bg-deep); color: var(--c-text-main); }
.nav-item.active { background: var(--c-primary-light); color: var(--c-primary); font-weight: 600; }

.nav-right { display: flex; align-items: center; gap: 16px; }
.proc-select { width: 130px; }
.proc-select .el-select__wrapper { background: var(--c-bg); box-shadow: 0 0 0 1px var(--c-divider) inset; min-height: 32px; }
.proc-select .el-select__placeholder { color: var(--c-text-weak); }
.proc-select .el-select__selected-item { color: var(--c-text-main); }
.proc-select .el-select__caret { color: var(--c-text-weak); }
.nav-icon { cursor: pointer; font-size: 18px; display: flex; color: var(--c-text-sub); padding: 6px; border-radius: var(--radius-sm); transition: background var(--t-fast), color var(--t-fast); }
.nav-icon:hover { background: var(--c-bg-deep); color: var(--c-primary); }

/* ===== 内容区 ===== */
.app-content { flex: 1; }

/* ===== 事件流图标色（doc/05.1 §6.1） ===== */
.ev-start { color: var(--c-primary); }
.ev-done { color: var(--c-success); }
.ev-timeout { color: var(--c-warning); }
.ev-interrupt { color: var(--c-danger); }
.ev-finish { color: var(--c-text-sub); }

/* ===== 全局搜索（Ctrl+F） ===== */
.gs-loading { padding: 8px 0; }
.gs-section { font-size: var(--fs-h3); font-weight: 600; letter-spacing: -0.01em; color: var(--c-text-main); margin: 10px 0 4px; }
.gs-row { display: flex; align-items: center; gap: 12px; padding: 8px 6px; border-radius: var(--radius-sm, 6px); cursor: pointer; }
.gs-row:hover { background: var(--c-bg, #F5F7FA); }
.gs-row b { font-size: var(--fs-body); }
.gs-meta { flex: 1; color: var(--c-text-weak); font-size: var(--fs-aux); }
</style>
