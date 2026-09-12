<template>
  <el-config-provider :locale="zhCn">
    <!-- 数据大屏（根路由）：全屏渲染，无侧边栏 -->
    <router-view v-if="isScreen" />
    <el-container v-else class="app-shell">
      <el-aside width="200px" class="app-aside">
        <div class="app-logo">AI 教学分析</div>
        <el-menu :default-active="$route.path" router class="app-menu">
          <el-menu-item index="/"><el-icon><Monitor /></el-icon>数据大屏</el-menu-item>
          <el-menu-item index="/students"><el-icon><User /></el-icon>学员管理</el-menu-item>
          <el-menu-item index="/reports"><el-icon><Document /></el-icon>报告管理</el-menu-item>
          <el-menu-item index="/diagnosis"><el-icon><FirstAidKit /></el-icon>诊断中心</el-menu-item>
          <el-menu-item index="/teaching"><el-icon><Notebook /></el-icon>教学闭环</el-menu-item>
          <el-menu-item index="/dashboard"><el-icon><DataBoard /></el-icon>教学分析</el-menu-item>
          <el-menu-item index="/settings"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
        </el-menu>
      </el-aside>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Document, FirstAidKit, Notebook, DataBoard, User, Monitor, Setting } from '@element-plus/icons-vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

const route = useRoute()
const isScreen = computed(() => route.path === '/')
</script>

<style>
html, body, #app { height: 100%; margin: 0; }
.app-shell { height: 100%; }
.app-aside { border-right: 1px solid #e4e7ed; display: flex; flex-direction: column; }
.app-logo { font-weight: 700; padding: 16px; text-align: center; color: #409eff; }
.app-menu { border-right: none; flex: 1; }
.app-main { background: #f5f7fa; padding: 16px; overflow: auto; }

/* ===== 全局布局统一（各子模块页面） ===== */
/* 卡片圆角与阴影统一，垂直堆叠的卡片留出呼吸间距 */
.app-main .el-card { border-radius: 8px; box-shadow: 0 1px 4px rgba(0, 21, 41, .06) !important; }
.app-main .el-card + .el-card { margin-top: 12px; }
/* 卡片头部统一节奏 */
.app-main .el-card__header { padding: 12px 16px; }
/* 标题栏（.bar）内筛选控件统一间距与垂直对齐 */
.app-main .bar { gap: 8px; flex-wrap: wrap; row-gap: 6px; }
.app-main .bar .el-input, .app-main .bar .el-select { margin-left: 0; }
/* 表格斑马纹更浅、行悬停高亮统一 */
.app-main .el-table { --el-table-row-hover-bg-color: #ecf5ff; }
/* 空态与描述列表统一小间距 */
.app-main .el-empty { padding: 24px 0; }

/* ===== 统计卡片行（各模块页头下方的概览数字） ===== */
.stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 14px; }
.stat-card { background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; padding: 14px 16px;
  display: flex; flex-direction: column; gap: 4px; box-shadow: 0 1px 4px rgba(0, 21, 41, .04); }
.stat-card .stat-num { font-size: 26px; font-weight: 700; color: #303133; line-height: 1.2; font-variant-numeric: tabular-nums; }
.stat-card .stat-label { font-size: 13px; color: #909399; }
.stat-card.clickable { cursor: pointer; transition: border-color .2s, transform .15s; }
.stat-card.clickable:hover { border-color: #409eff; transform: translateY(-2px); }
.stat-card .stat-num.tone-primary { color: #409eff; }
.stat-card .stat-num.tone-success { color: #67c23a; }
.stat-card .stat-num.tone-warning { color: #e6a23c; }
.stat-card .stat-num.tone-danger { color: #f56c6c; }

/* ===== 筛选栏（独立于卡片 header 的横向工具条） ===== */
.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filter-bar .el-input, .filter-bar .el-select { width: 150px; }

/* ===== 小节标题（卡片内分组标题，替代裸 h4） ===== */
.app-main .section-title { font-size: 14px; font-weight: 600; color: #303133; margin: 16px 0 8px;
  padding-left: 8px; border-left: 3px solid #409eff; line-height: 1.4; }
.app-main .section-title:first-child { margin-top: 0; }

/* ===== 列表填满页面空余高度（全站统一骨架） ===== */
/* 页面根容器占满主区：页头/统计行为固定高，标记 .fill-card 的列表卡弹性填充
   （不用 :last-child —— 对话框/抽屉 overlay 是后面的兄弟节点，会破坏匹配） */
.app-main > div { display: flex; flex-direction: column; min-height: calc(100vh - 32px); }
.app-main .fill-card { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.app-main .fill-card > .el-card__body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
/* 表格区弹性填充，行数少时以表格底色补齐空余区域 */
.app-main .fill-card > .el-card__body > .el-table { flex: 1; }
.app-main .fill-card > .el-card__body > .el-table .el-table__inner-wrapper { height: 100%; }
/* 左右分栏页（教学闭环）：行占满剩余高度 */
.app-main .fill-row { flex: 1; min-height: 0; }
/* 操作列不换行、按钮间距收紧（默认尺寸文字按钮间的 12px 间距过大易溢出） */
.app-main .op-col .cell { white-space: nowrap; padding: 0 8px; }
.app-main .op-col .op-btns { display: inline-flex; align-items: center; }
.app-main .op-col .op-btns .el-button { margin-left: 0; padding: 5px 6px; }
.app-main .op-col .op-btns .el-button + .el-button { margin-left: 4px; }
/* 分页条贴底 */
.app-main .pager { margin-top: auto; padding-top: 12px; }
</style>
