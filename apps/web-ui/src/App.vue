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
  </el-config-provider>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Setting } from '@element-plus/icons-vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useWorkspaceStore, PROCESS_OPTIONS } from './stores/workspace'
import StudentDrawer from './components/StudentDrawer.vue'
import ReportDrawer from './components/ReportDrawer.vue'
import DiagnosisDrawer from './components/DiagnosisDrawer.vue'
import EvidenceLightbox from './components/EvidenceLightbox.vue'
import { useLightbox } from './components/lightbox'

const route = useRoute()
const router = useRouter()
const ws = useWorkspaceStore()

const isActive = (prefix) =>
  prefix === '/' ? route.path === '/' : route.path.startsWith(prefix)
const go = (path) => router.push(path)

// ---- EvidenceLightbox 全局单例（EvidenceThumb 通过 useLightbox() 调用） ----
const lightboxRef = ref(null)
useLightbox().bind(lightboxRef)

// ---- Esc 关闭 Drawer（doc/05.1 §10.5 键盘快捷键） ----
function onKeydown(e) {
  if (e.key === 'Escape' && ws.drawer) ws.closeDrawer()
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style>
@import './styles/design.css';

.app-shell { min-height: 100%; display: flex; flex-direction: column; }

/* ===== 顶部导航 ===== */
.top-nav {
  height: var(--nav-h);
  background: var(--c-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.nav-left { display: flex; align-items: center; gap: 32px; }
.nav-logo { font-size: 16px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 8px; }
.logo-dot { width: 10px; height: 10px; border-radius: 2px; background: var(--c-accent); display: inline-block; }
.nav-menu { display: flex; gap: 8px; }
.nav-item {
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: var(--fs-body);
  color: rgba(255, 255, 255, 0.85);
  transition: background .15s, color .15s;
}
.nav-item:hover { background: rgba(255, 255, 255, 0.12); color: #fff; }
.nav-item.active { background: rgba(255, 255, 255, 0.2); color: #fff; font-weight: 600; }

.nav-right { display: flex; align-items: center; gap: 16px; }
.proc-select { width: 130px; }
.proc-select .el-select__wrapper { background: rgba(255,255,255,.15); box-shadow: none; color: #fff; }
.proc-select .el-select__placeholder { color: rgba(255,255,255,.75); }
.proc-select .el-select__selected-item { color: #fff; }
.proc-select .el-select__caret { color: rgba(255,255,255,.8); }
.nav-icon { cursor: pointer; font-size: 18px; display: flex; color: rgba(255,255,255,.9); }
.nav-icon:hover { color: #fff; }

/* ===== 内容区 ===== */
.app-content { flex: 1; }

/* ===== 事件流图标色（doc/05.1 §6.1） ===== */
.ev-start { color: var(--c-primary); }
.ev-done { color: var(--c-success); }
.ev-timeout { color: var(--c-warning); }
.ev-interrupt { color: var(--c-danger); }
.ev-finish { color: var(--c-text-sub); }
</style>
