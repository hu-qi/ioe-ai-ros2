<template>
  <div class="page-wrap">
    <!-- 头部：返回 + 学员信息 + 工序筛选（doc/04 §4.2） -->
    <div class="dt-head card">
      <span class="link dt-back" @click="goBack">← 返回</span>
      <b class="dt-name">{{ student?.name || studentId }}</b>
      <el-tag size="small" type="info">{{ student?.cls || '-' }}</el-tag>
      <el-tag size="small">{{ studentId }}</el-tag>
      <div class="dt-proc">
        <el-radio-group v-model="ws.process" size="small">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button v-for="p in PROCESS_OPTIONS" :key="p" :label="p">{{ p }}</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <!-- 指标卡片 ×4 -->
    <div class="dt-metrics">
      <MetricCard label="考试次数" :value="cum.exam_count" color="#2B5CE6" />
      <MetricCard label="平均分" :value="cum.avg_score" :decimals="1" color="#27AE60" />
      <MetricCard label="最高分" :value="cum.max_score != null ? Number(cum.max_score) : null" :decimals="1" color="#F5A623" />
      <MetricCard label="最低分" :value="cum.min_score != null ? Number(cum.min_score) : null" :decimals="1" color="#E74C3C" />
    </div>

    <!-- 成绩趋势（折线图，按工序筛选联动） -->
    <section class="card dt-chart-card">
      <div class="card-title">成绩趋势</div>
      <div ref="trendEl" class="dt-chart"></div>
      <el-empty v-if="!scores.length" description="暂无考试记录" :image-size="72" />
    </section>

    <!-- 薄弱步骤 TOP3 + 退步预警 -->
    <div class="row-two">
      <section class="card">
        <div class="card-title">薄弱步骤 TOP3</div>
        <el-empty v-if="!cum.weak_steps?.length" description="暂无数据" :image-size="60" />
        <div v-else class="weak-list">
          <div v-for="(w, i) in cum.weak_steps" :key="i" class="weak-row" @click="toggleWeak(w)">
            <span class="weak-rank" :class="'r' + (i + 1)">{{ i + 1 }}</span>
            <span class="weak-name">{{ w.name }}</span>
            <span class="weak-meta ts">均值 {{ (w.avg_duration_ms / 1000).toFixed(1) }}s × {{ w.sample_count }}次</span>
          </div>
          <!-- 内嵌展开：该步骤相关报告（doc/04 §4.2 点击薄弱步骤展开） -->
          <ExpandPanel :visible="!!weakOpen" title="相关报告与证据" @close="weakOpen = null">
            <div v-if="weakReports.length" class="weak-reports">
              <div v-for="r in weakReports" :key="r.report_id" class="weak-report">
                <span class="ts">{{ fmtDate(r.ts_upload_ms) }}</span>
                <span class="wr-name">{{ r.student_name || r.student_id }}</span>
                <ScoreTag :score="r.total_score" />
                <span class="link" @click.stop="openReport(r)">查看</span>
              </div>
              <div v-if="weakEvidence.length" class="weak-evidence">
                <EvidenceThumb v-for="ev in weakEvidence" :key="ev.id" :item="ev" :width="80" :height="60" />
              </div>
            </div>
            <el-skeleton v-else :rows="2" animated />
          </ExpandPanel>
        </div>
      </section>

      <section class="card">
        <div class="card-title">退步预警</div>
        <template v-if="regression">
          <div class="reg-card">
            <div class="reg-row"><span>最近{{ regWin.recent }}次平均分</span><b>{{ regression.metric_value }}</b></div>
            <div class="reg-row"><span>阈值(前{{ regWin.history }}次×{{ regThreshold }})</span><b>{{ regression.threshold_value }}</b></div>
            <div class="reg-warn">⚠ 成绩退步，建议安排辅导</div>
          </div>
        </template>
        <el-empty v-else description="暂无退步预警" :image-size="60" />
        <div class="card-title" style="margin-top:16px">诊断建议</div>
        <div v-if="regression" class="reg-advice">💡 {{ regression.advice_text }}</div>
        <div v-else class="reg-advice">💡 当前成绩保持稳定</div>
      </section>
    </div>

    <!-- 历史报告列表 -->
    <section class="card dt-reports">
      <div class="card-title">历史报告</div>
      <el-table :data="reports" v-loading="repLoading" @row-click="(r) => openReport(r)">
        <el-table-column label="日期" width="110">
          <template #default="{ row }">{{ fmtDate(row.ts_upload_ms) }}</template>
        </el-table-column>
        <el-table-column label="工序" prop="process_name" width="90" />
        <el-table-column label="用时" width="90" align="right">
          <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="结束方式" width="100">
          <template #default="{ row }">{{ FINISH_REASON_LABEL[row.finish_reason] || row.finish_reason || '-' }}</template>
        </el-table-column>
        <el-table-column label="得分" width="150">
          <template #default="{ row }"><ScoreTag :score="row.total_score" /></template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default><span class="link">查看报告</span></template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
/**
 * StudentDetailView.vue — 学员详情（doc/04 §4.2 个体追踪）
 * 指标×4 + 成绩趋势折线 + 薄弱步骤TOP3(内嵌展开) + 退步预警 + 历史报告。
 * 工序筛选联动全部数据。
 */
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElTag, ElTable, ElTableColumn, ElEmpty, ElRadioGroup, ElRadioButton, ElSkeleton } from 'element-plus'
import { api } from '../api'
import { useWorkspaceStore, PROCESS_OPTIONS } from '../stores/workspace'
import { fmtDate, fmtDuration, gradeOf, FINISH_REASON_LABEL } from '../utils/format'
import MetricCard from '../components/MetricCard.vue'
import ScoreTag from '../components/ScoreTag.vue'
import EvidenceThumb from '../components/EvidenceThumb.vue'
import ExpandPanel from '../components/ExpandPanel.vue'
import { echarts } from '../echarts'

const route = useRoute()
const router = useRouter()
const ws = useWorkspaceStore()
const studentId = computed(() => decodeURIComponent(route.params.id || ''))

const student = ref(null)
const cum = ref({})
const reports = ref([])
const repLoading = ref(false)
const regression = ref(null)

const trendEl = ref(null)
let trendInst = null

const regWin = { recent: 3, history: 5 }
const regThreshold = computed(() => {
  if (!regression.value?.metric_value || !regression.value?.threshold_value) return 0.85
  return (regression.value.threshold_value / regression.value.metric_value).toFixed(2)
})

const scores = computed(() => cum.value.scores || [])

// ---- 薄弱步骤内嵌展开 ----
const weakOpen = ref(null)          // {idx, name}
const weakReports = ref([])
const weakEvidence = ref([])

function scoreCls(v) { return v == null ? '' : 'g-' + gradeOf(Number(v)).type }

async function load() {
  const sid = studentId.value
  if (!sid) return
  const params = { student_id: sid, process_name: ws.process }
  const [info, stats] = await Promise.all([
    api.getStudent(sid).catch(() => null),
    api.studentCumulative(params).catch(() => null),
  ])
  student.value = info?.student || null
  cum.value = stats || {}
  loadReports()
  loadRegression()
  await nextTick()
  renderTrend()
}

async function loadReports() {
  repLoading.value = true
  try {
    const d = await api.listReports({ student_id: studentId.value, page: 1, page_size: 50 }).catch(() => null)
    let list = d?.list || []
    if (ws.process) list = list.filter((r) => !r.process_name || r.process_name === ws.process)
    reports.value = list
  } finally {
    repLoading.value = false
  }
}

/** 学员退步预警（student 维度诊断） */
async function loadRegression() {
  const d = await api.diagnosis({
    scope: 'student', student_id: studentId.value, process_name: ws.process,
  }).catch(() => null)
  regression.value = (d?.diagnoses || []).find((x) => x.diagnosis_type === 'student_regression') || null
}

function renderTrend() {
  if (!trendEl.value || !scores.value.length) return
  trendInst = trendInst || echarts.init(trendEl.value)
  trendInst.setOption({
    grid: { left: 44, right: 20, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: scores.value.map((s) => fmtDate(s.ts_upload_ms).slice(5)) },
    yAxis: { type: 'value', min: 0, max: 100 },
    series: [{
      name: '得分', type: 'line', smooth: true,
      data: scores.value.map((s) => s.score),
      itemStyle: { color: '#2B5CE6' },
      areaStyle: { color: 'rgba(43,92,230,.12)' },
    }],
  }, true)
}

function toggleWeak(w) {
  if (weakOpen.value?.idx === w.idx) { weakOpen.value = null; return }
  weakOpen.value = w
  weakReports.value = []
  weakEvidence.value = []
  // 下钻：该学员该步骤的报告 + 证据
  api.listReports({ student_id: studentId.value, step_index: w.idx, page: 1, page_size: 5 })
    .then((d) => { weakReports.value = d?.list || [] })
    .catch(() => {})
  api.listEvidence({ device_id: reports.value[0]?.device_id || '', sub: w.idx, limit: 3 })
    .then((d) => { weakEvidence.value = d?.evidence || [] })
    .catch(() => {})
}

function openReport(r) {
  router.push(`/reports/${encodeURIComponent(r.report_id)}`)
}
function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/students')
}

// resize 重绘
function onResize() { trendInst && trendInst.resize() }
onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  trendInst && trendInst.dispose()
})
watch(() => ws.process, load)
</script>

<style scoped>
.dt-head { display: flex; align-items: center; gap: 12px; }
.dt-back { font-size: var(--fs-body); }
.dt-name { font-size: var(--fs-h2); }
.dt-proc { margin-left: auto; }
.dt-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 16px; }
.dt-chart-card { margin-top: 16px; }
.dt-chart { width: 100%; height: 240px; }
.row-two { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; margin-top: 16px; }
.weak-list { display: flex; flex-direction: column; }
.weak-row { display: flex; align-items: center; gap: 10px; padding: 10px 4px; border-bottom: 1px solid var(--c-divider); cursor: pointer; }
.weak-rank { width: 22px; height: 22px; border-radius: 50%; color: #fff; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; background: var(--c-accent); }
.weak-rank.r1 { background: var(--c-danger); }
.weak-rank.r2 { background: var(--c-warning); }
.weak-rank.r3 { background: var(--c-accent); }
.weak-name { font-weight: 600; }
.weak-meta { margin-left: auto; }
.weak-report { display: flex; align-items: center; gap: 12px; padding: 6px 0; }
.wr-name { flex: 1; }
.weak-evidence { display: flex; gap: 8px; margin-top: 8px; }
.reg-card { display: flex; flex-direction: column; gap: 8px; }
.reg-row { display: flex; justify-content: space-between; font-size: var(--fs-body); color: var(--c-text-sub); }
.reg-row b { color: var(--c-danger); font-variant-numeric: tabular-nums; }
.reg-warn { background: rgba(231, 76, 60, .08); border: 1px solid rgba(231, 76, 60, .3); color: var(--c-danger); border-radius: 6px; padding: 8px 12px; font-weight: 600; }
.reg-advice { font-size: var(--fs-body); color: var(--c-text-sub); background: #FFF8E8; border-radius: 4px; padding: 8px 12px; }
.dt-reports { margin-top: 16px; }
.g-success { color: var(--c-success); }
.g-primary { color: var(--c-primary); }
.g-warning { color: var(--c-accent); }
.g-danger { color: var(--c-danger); }
</style>
