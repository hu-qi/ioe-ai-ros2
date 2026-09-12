<template>
  <el-drawer
    :model-value="visible"
    title="学员速览"
    size="480px"
    :destroy-on-close="true"
    @close="ws.closeDrawer()"
  >
    <div v-if="loading" class="dw-loading"><el-skeleton :rows="6" animated /></div>
    <template v-else-if="student">
      <!-- 头部：为什么需要关注 / 最近表现 / 薄弱步骤（doc/05.1 §八） -->
      <div class="dw-head">
        <div class="dw-name">
          <b>{{ student.name }}</b>
          <el-tag size="small" type="info">{{ student.cls || '-' }}</el-tag>
          <el-tag size="small">{{ student.id }}</el-tag>
          <el-tag v-if="reason" size="small" :type="reason.type">{{ reason.text }}</el-tag>
        </div>
        <div v-if="detail" class="dw-reason">{{ detail }}</div>
      </div>

      <div class="dw-metrics">
        <div class="dw-metric"><div class="dm-num">{{ cum.exam_count ?? '-' }}</div><div class="dm-label">考试次数</div></div>
        <div class="dw-metric"><div class="dm-num" :class="scoreCls(cum.avg_score)">{{ cum.avg_score ?? '-' }}</div><div class="dm-label">平均分</div></div>
        <div class="dw-metric"><div class="dm-num">{{ cum.max_score ?? '-' }}</div><div class="dm-label">最高分</div></div>
        <div class="dw-metric"><div class="dm-num">{{ cum.min_score ?? '-' }}</div><div class="dm-label">最低分</div></div>
      </div>

      <template v-if="recentScores.length">
        <div class="dw-section">最近成绩</div>
        <div class="dw-scores">
          <span v-for="(s, i) in recentScores" :key="i" class="dw-score" :class="scoreCls(s.score)">{{ s.score ?? '-' }}</span>
        </div>
      </template>

      <div v-if="cum.weak_steps?.length" class="dw-section">薄弱步骤 TOP3</div>
      <div v-if="cum.weak_steps?.length" class="dw-weak">
        <div v-for="(w, i) in cum.weak_steps" :key="i" class="dw-weak-row">
          <span class="dw-weak-rank" :class="'r' + (i + 1)">{{ i + 1 }}</span>
          <span>{{ w.name }}</span>
          <span class="ts" style="margin-left:auto">均值 {{ (w.avg_duration_ms / 1000).toFixed(1) }}s × {{ w.sample_count }}次</span>
        </div>
      </div>

      <div v-if="reports.length" class="dw-section">最近 5 次训练</div>
      <div v-if="reports.length" class="dw-reports">
        <div v-for="r in reports" :key="r.report_id" class="dw-report-row" @click="openReport(r)">
          <span class="ts">{{ fmtDate(r.ts_upload_ms) }}</span>
          <span class="dw-proc">{{ r.process_name || '-' }}</span>
          <ScoreTag :score="r.total_score" />
        </div>
      </div>

      </template>
      <el-empty v-else description="学员数据不可用" />
      <template #footer>
        <div class="dw-footer">
          <el-button size="small" :disabled="!ws.hasDrawerPrev" @click="ws.drawerStep(-1)">← 上一条</el-button>
          <el-button size="small" :disabled="!ws.hasDrawerNext" @click="ws.drawerStep(1)">下一条 →</el-button>
          <el-button type="primary" plain class="dw-footer-main" @click="goDetail">查看长期分析</el-button>
        </div>
      </template>
    </el-drawer>
  </template>

  <script setup>
/**
 * StudentDrawer.vue — 学员速览抽屉（doc/05.1 §八）
 * 首屏回答三问：为什么关注 / 最近表现如何 / 薄弱步骤是什么。
 * 不改变 Route；"查看长期分析"才进入独立学员详情页。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElDrawer, ElSkeleton, ElTag, ElButton, ElEmpty } from 'element-plus'
import { useWorkspaceStore } from '../stores/workspace'
import { api } from '../api'
import { fmtDate, attentionTag, gradeOf } from '../utils/format'
import ScoreTag from './ScoreTag.vue'

const ws = useWorkspaceStore()
const router = useRouter()

const visible = computed(() => ws.drawer === 'student')
const payload = computed(() => (ws.drawer === 'student' ? ws.drawerPayload : null))

const loading = ref(false)
const student = ref(null)
const cum = ref({})
const reports = ref([])

const reason = computed(() => (payload.value?.reason ? attentionTag(payload.value.reason) : null))
const detail = computed(() => payload.value?.detail || '')
const recentScores = computed(() => (cum.value.scores || []).slice(-5))

function scoreCls(v) {
  if (v == null) return ''
  return 'g-' + gradeOf(Number(v)).type
}

async function load() {
  const sid = payload.value?.student_id
  if (!sid) { student.value = null; return }
  loading.value = true
  try {
    // 并行拉取：学员基本信息 + 累计统计 + 最近报告
    const [info, stats, rep] = await Promise.all([
      api.getStudent(sid).catch(() => null),
      api.studentCumulative({ student_id: sid }).catch(() => null),
      api.listReports({ student_id: sid, page: 1, page_size: 5 }).catch(() => null),
    ])
    student.value = info?.student || { id: sid, name: payload.value?.student_name, cls: payload.value?.student_cls }
    cum.value = stats || {}
    reports.value = rep?.list || []
  } finally {
    loading.value = false
  }
}

watch(visible, (v) => { if (v) load() })

function openReport(r) {
  ws.openDrawer('report', { report_id: r.report_id })
}
function goDetail() {
  ws.closeDrawer()
  router.push(`/students/${encodeURIComponent(payload.value.student_id)}`)
}
</script>

<style scoped>
.dw-loading { padding: 8px 0; }
.dw-head { margin-bottom: 12px; }
.dw-name { display: flex; align-items: center; gap: 8px; font-size: var(--fs-h2); }
.dw-reason { margin-top: 8px; font-size: var(--fs-body); color: var(--c-warning); background: #FFF8E8; border-radius: 4px; padding: 6px 10px; }
.dw-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 16px; }
.dw-metric { background: var(--c-bg); border-radius: 6px; padding: 10px 0; text-align: center; }
.dm-num { font-size: var(--fs-num2); font-weight: 700; line-height: var(--lh-num2); font-variant-numeric: tabular-nums; }
.dm-label { font-size: var(--fs-aux); color: var(--c-text-weak); }
.g-success { color: var(--c-success); }
.g-primary { color: var(--c-primary); }
.g-warning { color: var(--c-accent); }
.g-danger { color: var(--c-danger); }
.dw-section { font-size: var(--fs-h3); font-weight: 600; letter-spacing: -0.01em; margin: 14px 0 8px; line-height: var(--lh-h3); color: var(--c-text-main); }
.dw-scores { display: flex; gap: 8px; }
.dw-score { background: var(--c-bg); border-radius: 6px; padding: 4px 10px; font-weight: 700; }
.dw-weak { display: flex; flex-direction: column; gap: 6px; }
.dw-weak-row { display: flex; align-items: center; gap: 8px; }
.dw-weak-rank { width: 20px; height: 20px; border-radius: 50%; background: var(--c-accent); color: #fff; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; }
.dw-reports { display: flex; flex-direction: column; }
.dw-report-row { display: flex; align-items: center; gap: 12px; padding: 8px 4px; border-bottom: 1px solid var(--c-divider); cursor: pointer; border-radius: 4px; }
.dw-report-row:hover { background: var(--c-bg); }
.dw-proc { flex: 1; }
.dw-footer { display: flex; align-items: center; gap: 8px; }
.dw-footer-main { margin-left: auto; }
</style>
