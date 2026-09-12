<template>
  <div>
    <!-- 工序筛选 -->
    <el-card>
      <template #header>
        <div class="bar">
          <b>教学分析看板</b>
          <el-select v-model="proc" size="small" style="width:120px" clearable placeholder="全部工序" @change="loadAll">
            <el-option label="拆解" value="拆解" /><el-option label="组装" value="组装" />
          </el-select>
        </div>
      </template>
      <el-alert type="info" :closable="false"
        title="实时态势与高频错误、需关注学员见数据大屏（侧边栏「数据大屏」）；本页聚焦阶段分析与改进验证。" />
    </el-card>

    <!-- 近 7 天趋势 -->
    <el-card style="margin-top:12px">
      <template #header><b>近 7 天成绩趋势（平均分 / 通过率）</b></template>
      <div ref="trendChart" class="chart-box" v-loading="loading"></div>
    </el-card>

    <!-- 班级对比 -->
    <el-card style="margin-top:12px">
      <template #header><b>近 30 天班级对比（平均分 / 通过率）</b></template>
      <div ref="clsChart" class="chart-box" v-loading="loading"></div>
    </el-card>

    <!-- 最近教学调整 + 改进验证 -->
    <el-card class="fill-card" style="margin-top:12px">
      <template #header>
        <div class="bar">
          <b>最近教学调整与改进验证</b>
          <el-button size="small" text type="primary" @click="$router.push('/teaching')">进入教学闭环 →</el-button>
        </div>
      </template>
      <el-empty v-if="!actions.length" :image-size="50" description="暂无教学调整记录" />
      <el-table v-else :data="actions" size="small" stripe>
        <el-table-column prop="action_date" label="日期" width="110">
          <template #default="{ row }">{{ fmtDate(row.action_date) }}</template>
        </el-table-column>
        <el-table-column prop="class_name" label="班级" width="90" />
        <el-table-column prop="process_name" label="工序" width="80" />
        <el-table-column prop="description" label="调整内容" min-width="200" show-overflow-tooltip />
        <el-table-column label="效果验证" width="110">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="verify(row.id)">对比验证</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 验证结果对话框 -->
    <el-dialog v-model="vDlg" title="改进效果验证" width="520px">
      <template v-if="verifyData">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="班级">{{ verifyData.cls }}</el-descriptions-item>
          <el-descriptions-item label="趋势">
            <el-tag size="small" :type="trendTag">{{ trendText }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="调整前均分">{{ verifyData.before?.avg_score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="调整后均分">{{ verifyData.after?.avg_score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="调整前通过率">{{ pct(verifyData.before?.pass_rate) }}</el-descriptions-item>
          <el-descriptions-item label="调整后通过率">{{ pct(verifyData.after?.pass_rate) }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <el-empty v-else :image-size="50" description="加载中" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { echarts } from '../echarts'
import { api } from '../api'

const proc = ref('')
const loading = ref(false)
const actions = ref([])
const vDlg = ref(false)
const verifyData = ref(null)
const trendChart = ref(null)
const clsChart = ref(null)
let trendInst = null
let clsInst = null
const timers = []

const pct = (v) => (v === null || v === undefined) ? '-' : (v * 100).toFixed(1) + '%'
const fmtDate = (ms) => ms ? new Date(ms).toLocaleDateString('zh-CN') : '-'
const trendText = computed(() => ({ improved: '改善', declined: '下降', mixed: '互有涨跌', no_data: '数据不足' }[verifyData.value?.trend] || '-'))
const trendTag = computed(() => ({ improved: 'success', declined: 'danger', mixed: 'warning', no_data: 'info' }[verifyData.value?.trend] || 'info'))

// 浅色主题公共轴样式（管理页浅色底）
const axisStyle = {
  axisLine: { lineStyle: { color: '#dcdfe6' } },
  axisLabel: { color: '#606266' },
  splitLine: { lineStyle: { color: '#ebeef5' } },
}

function renderTrend(trend) {
  if (!trendChart.value) return
  // 近 N 天窗口补齐：无报告的日期填 0，保证 x 轴始终显示完整日期序列
  const map = Object.fromEntries((trend || []).map(t => [t.date, t]))
  const days = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    days.push(map[key] || { date: key, report_count: 0, avg_score: 0, pass_rate: 0 })
  }
  trendInst = trendInst || echarts.init(trendChart.value)
  trendInst.setOption({
    grid: { left: 50, right: 56, top: 36, bottom: 30 },
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    xAxis: { type: 'category', data: days.map(t => t.date?.slice(5)), ...axisStyle },
    yAxis: [
      { type: 'value', name: '平均分', nameTextStyle: { color: '#606266' }, ...axisStyle },
      { type: 'value', name: '通过率', max: 1, axisLabel: { color: '#606266', formatter: v => (v * 100) + '%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '平均分', type: 'line', smooth: true, data: days.map(t => t.avg_score), itemStyle: { color: '#409eff' }, areaStyle: { color: 'rgba(64,158,255,.12)' } },
      { name: '通过率', type: 'bar', yAxisIndex: 1, data: days.map(t => t.pass_rate), itemStyle: { color: 'rgba(103,194,58,.7)' }, barWidth: 14 },
    ],
  })
}

function renderCls(classes) {
  if (!clsChart.value) return
  clsInst = clsInst || echarts.init(clsChart.value)
  clsInst.setOption({
    grid: { left: 50, right: 56, top: 36, bottom: 30 },
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    xAxis: { type: 'category', data: classes.map(c => c.cls), ...axisStyle },
    yAxis: [
      { type: 'value', name: '平均分', nameTextStyle: { color: '#606266' }, ...axisStyle },
      { type: 'value', name: '通过率', max: 1, axisLabel: { color: '#606266', formatter: v => (v * 100) + '%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '平均分', type: 'bar', data: classes.map(c => c.avg_score), itemStyle: { color: '#409eff' }, barWidth: 28 },
      { name: '通过率', type: 'line', yAxisIndex: 1, smooth: true, data: classes.map(c => c.pass_rate), itemStyle: { color: '#e6a23c' } },
    ],
  })
}

async function loadAll() {
  loading.value = true
  try {
    const params = proc.value ? { process_name: proc.value } : {}
    const t = await api.scoreTrend({ days: 7, ...params }).catch(() => null)
    const c = await api.classComparison({ days: 30, ...params }).catch(() => null)
    actions.value = await api.listTeachingActions().catch(() => [])
    await nextTick()
    renderTrend(t?.trend || [])
    renderCls(c?.classes || [])
  } finally {
    loading.value = false
  }
}

async function verify(id) {
  verifyData.value = await api.verifyTeachingAction(id).catch(() => null)
  vDlg.value = true
}

onMounted(() => {
  loadAll()
  const t = setInterval(() => {
    trendInst && trendInst.resize()
    clsInst && clsInst.resize()
  }, 1000)
  timers.push(t)
})
onUnmounted(() => {
  timers.forEach(clearInterval)
  trendInst && trendInst.dispose()
  clsInst && clsInst.dispose()
})
</script>

<style scoped>
.bar { display: flex; justify-content: space-between; align-items: center; }
.chart-box { width: 100%; height: 300px; }
</style>
