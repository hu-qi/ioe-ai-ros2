<template>
  <div class="page-wrap">
    <div class="rp-tabs-bar card">
      <el-tabs v-model="tab">
        <el-tab-pane label="报告列表" name="list" />
        <el-tab-pane label="五维诊断" name="diagnosis" />
        <el-tab-pane label="教学闭环" name="teaching" />
      </el-tabs>
    </div>

    <!-- ===== Tab 1：报告列表（doc/04 §5.1） ===== -->
    <section v-show="tab === 'list'" class="card tab-body">
      <div class="filter-bar">
        <el-select v-model="q.student_id" placeholder="学员：全部" clearable filterable style="width:150px" @change="loadReports">
          <el-option v-for="s in studentOptions" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-select v-model="q.finish_reason" placeholder="结束方式" clearable style="width:130px" @change="loadReports">
          <el-option label="正常完成" value="completed" />
          <el-option label="人工结束" value="manual" />
          <el-option label="轮次超时" value="timeout" />
          <el-option label="重置" value="reset" />
        </el-select>
        <el-select v-model="q.rangeDays" placeholder="时间" style="width:110px" @change="loadReports">
          <el-option v-for="r in RANGE_OPTIONS" :key="r.days" :label="r.label" :value="r.days" />
        </el-select>
        <el-select v-model="q.grade" placeholder="等级：全部" clearable style="width:120px" @change="loadReports">
          <el-option v-for="g in ['优秀', '良好', '合格', '不合格']" :key="g" :label="g" :value="g" />
        </el-select>
        <el-button type="primary" @click="loadReports">查询</el-button>
      </div>
      <el-table :data="filteredReports" v-loading="repLoading" @row-click="(r) => goDetail(r.report_id)">
        <el-table-column label="日期" width="110">
          <template #default="{ row }">{{ fmtDate(row.ts_upload_ms) }}</template>
        </el-table-column>
        <el-table-column label="学员" min-width="100">
          <template #default="{ row }">{{ row.student_name || row.student_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="工序" width="80">
          <template #default="{ row }">{{ row.process_name || '-' }}</template>
        </el-table-column>
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
      <div class="pager">
        <el-pagination
          v-model:current-page="q.page"
          :page-size="q.page_size"
          :total="repTotal"
          layout="total, prev, pager, next"
          @current-change="loadReports"
        />
      </div>
    </section>

    <!-- ===== Tab 2：五维诊断（doc/04 §5.2：雷达图 + 诊断列表） ===== -->
    <section v-show="tab === 'diagnosis'" class="card tab-body">
      <div class="filter-bar">
        <span class="fb-label">工序</span>
        <el-radio-group v-model="ws.process" size="small">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button v-for="p in PROCESS_OPTIONS" :key="p" :label="p">{{ p }}</el-radio-button>
        </el-radio-group>
        <el-select v-model="ws.rangeDays" style="width:110px" @change="loadDiagnosis">
          <el-option v-for="r in RANGE_OPTIONS" :key="r.days" :label="r.label" :value="r.days" />
        </el-select>
        <div style="flex:1"></div>
        <el-button @click="exportDiagnosis">导出报告</el-button>
      </div>

      <div class="dx-top">
        <div class="card dx-radar-card">
          <div class="card-title">五维诊断总览</div>
          <div ref="radarEl" class="dx-radar"></div>
        </div>
        <div class="card dx-summary">
          <div class="card-title">训练规模</div>
          <div class="dx-stat"><span>报告数</span><b>{{ diagSummary.report_count }}</b></div>
          <div class="dx-stat"><span>诊断条数</span><b>{{ diagnoses.length }}</b></div>
          <div class="dx-stat"><span>涉及步骤</span><b>{{ diagSummary.step_count }}</b></div>
          <div class="dx-tip">💡 五维：平均用时 / 操作错误 / 顺序错误 / 步骤间隔 / 用时波动</div>
        </div>
      </div>

      <div class="card-title" style="margin:16px 0 8px">诊断结果列表</div>
      <el-empty v-if="!diagnoses.length" description="暂无诊断结果，完成训练后自动生成" :image-size="80" />
      <div v-else class="dx-list">
        <DiagnosisItem v-for="(d, i) in diagnoses" :key="i" :item="d" />
      </div>
    </section>

    <!-- ===== Tab 3：教学闭环（doc/04 §5.3） ===== -->
    <section v-show="tab === 'teaching'" class="card tab-body">
      <div class="filter-bar">
        <el-select v-model="ta.cls" placeholder="班级：全部" clearable style="width:130px" @change="loadActions">
          <el-option v-for="c in classOptions" :key="c" :label="'班级：' + c" :value="c" />
        </el-select>
        <div style="flex:1"></div>
        <el-button type="primary" @click="formVisible = !formVisible">+ 新增教学调整</el-button>
      </div>

      <!-- 内嵌展开表单（页面顶部展开，非弹窗） -->
      <ExpandPanel :visible="formVisible" title="新增教学调整" @close="formVisible = false">
        <el-form inline>
          <el-form-item label="班级" required><el-input v-model="form.class_name" style="width:120px" placeholder="如 一班" /></el-form-item>
          <el-form-item label="工序">
            <el-select v-model="form.process_name" clearable style="width:110px">
              <el-option v-for="p in PROCESS_OPTIONS" :key="p" :label="p" :value="p" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标子步骤"><el-input v-model="form.target_substep" style="width:110px" placeholder="如 步骤3" /></el-form-item>
          <el-form-item label="描述" required style="flex:1">
            <el-input v-model="form.description" placeholder="如 调整步骤3讲解方法" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveAction">保存</el-button>
          </el-form-item>
        </el-form>
      </ExpandPanel>

      <!-- 闭环统计 -->
      <div class="ta-stats">
        <span>共 {{ actions.length }} 项调整</span>
        <el-tag size="small" type="success">已改善 {{ statCount('improved') }}</el-tag>
        <el-tag size="small" type="danger">无改善 {{ statCount('declined') }}</el-tag>
        <el-tag size="small" type="info">其他 {{ statCount('other') }}</el-tag>
      </div>

      <el-table :data="actions" v-loading="taLoading">
        <el-table-column label="日期" width="110">
          <template #default="{ row }">{{ fmtDate(row.action_date) }}</template>
        </el-table-column>
        <el-table-column label="班级" prop="class_name" width="90" />
        <el-table-column label="工序" width="80">
          <template #default="{ row }">{{ row.process_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="描述" min-width="200">
          <template #default="{ row }">{{ row.description }}</template>
        </el-table-column>
        <el-table-column label="目标子步骤" width="110">
          <template #default="{ row }">{{ row.target_substep || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.trend === 'improved'" size="small" type="success">已改善</el-tag>
            <el-tag v-else-if="row.trend === 'declined'" size="small" type="danger">无改善</el-tag>
            <el-tag v-else size="small" type="info">待验证</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <span class="link" @click.stop="toggleVerify(row)">查看效果</span>
          </template>
        </el-table-column>
      </el-table>

      <!-- 内嵌展开：改进效果对比（doc/04 §5.3） -->
      <ExpandPanel :visible="!!verifyRow" title="改进效果对比（前后各30天窗口）" @close="verifyRow = null">
        <div v-if="verifyData" class="vf-grid">
          <div class="vf-col">
            <div class="vf-title">调整前</div>
            <div class="vf-row"><span>平均分</span><b>{{ verifyData.before?.avg_score ?? '-' }}</b></div>
            <div class="vf-row"><span>完成率</span><b>{{ pct(verifyData.before?.completion_rate) }}</b></div>
            <div class="vf-row"><span>通过率</span><b>{{ pct(verifyData.before?.pass_rate) }}</b></div>
            <div class="vf-row"><span>报告数</span><b>{{ verifyData.before?.report_count ?? '-' }}</b></div>
          </div>
          <div class="vf-col">
            <div class="vf-title">调整后</div>
            <div class="vf-row"><span>平均分</span><b>{{ verifyData.after?.avg_score ?? '-' }}</b></div>
            <div class="vf-row"><span>完成率</span><b>{{ pct(verifyData.after?.completion_rate) }}</b></div>
            <div class="vf-row"><span>通过率</span><b>{{ pct(verifyData.after?.pass_rate) }}</b></div>
            <div class="vf-row"><span>报告数</span><b>{{ verifyData.after?.report_count ?? '-' }}</b></div>
          </div>
          <div class="vf-col vf-delta">
            <div class="vf-title">变化</div>
            <div class="vf-row"><span>平均分</span><b :class="deltaCls(verifyData.delta?.avg_score)">{{ signed(verifyData.delta?.avg_score) }}</b></div>
            <div class="vf-row"><span>通过率</span><b :class="deltaCls(verifyData.delta?.pass_rate)">{{ signedPct(verifyData.delta?.pass_rate) }}</b></div>
            <div class="vf-trend">
              <el-tag v-if="verifyData.trend === 'improved'" type="success">已改善</el-tag>
              <el-tag v-else-if="verifyData.trend === 'declined'" type="danger">无改善</el-tag>
              <el-tag v-else-if="verifyData.trend === 'mixed'" type="warning">效果混合</el-tag>
              <el-tag v-else type="info">数据不足</el-tag>
            </div>
          </div>
        </div>
        <el-skeleton v-else :rows="3" animated />
      </ExpandPanel>
    </section>
  </div>
</template>

<script setup>
/**
 * ReportsView.vue — 报告页（doc/04 §五：Tab 切换整合诊断与闭环）
 * Tab1 报告列表（筛选/分页） Tab2 五维诊断（雷达图+条目内嵌展开）
 * Tab3 教学闭环（顶部内嵌表单 + 查看效果内嵌对比）。
 */
import { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElTabs, ElTabPane, ElTable, ElTableColumn, ElTag, ElButton, ElInput, ElSelect, ElOption, ElForm, ElFormItem, ElRadioGroup, ElRadioButton, ElPagination, ElEmpty, ElSkeleton, ElMessage } from 'element-plus'
import { api } from '../api'
import { useWorkspaceStore, PROCESS_OPTIONS, RANGE_OPTIONS, rangeToMs } from '../stores/workspace'
import { fmtDate, fmtDuration, FINISH_REASON_LABEL, gradeOf } from '../utils/format'
import ScoreTag from '../components/ScoreTag.vue'
import DiagnosisItem from '../components/DiagnosisItem.vue'
import ExpandPanel from '../components/ExpandPanel.vue'
import { echarts } from '../echarts'

const router = useRouter()
const ws = useWorkspaceStore()
const tab = ref('list')

// ==================== Tab1 报告列表 ====================
const q = reactive({ student_id: '', finish_reason: '', rangeDays: 30, grade: '', page: 1, page_size: 20 })
const reports = ref([])
const repTotal = ref(0)
const repLoading = ref(false)
const studentOptions = ref([])

const filteredReports = computed(() => {
  if (!q.grade) return reports.value
  return reports.value.filter((r) => gradeOf(r.total_score).text === q.grade)
})

async function loadReports() {
  repLoading.value = true
  try {
    const r = rangeToMs(q.rangeDays)
    const params = {
      page: q.page, page_size: q.page_size,
      start_ms: r.date_start, end_ms: r.date_end,
    }
    if (q.student_id) params.student_id = q.student_id
    if (q.finish_reason) params.finish_reason = q.finish_reason
    const d = await api.listReports(params)
    reports.value = d?.list || []
    repTotal.value = d?.total || 0
  } finally {
    repLoading.value = false
  }
}

async function loadStudentOptions() {
  const d = await api.listStudents({ page: 1, page_size: 100 }).catch(() => null)
  studentOptions.value = d?.list || []
}

function goDetail(id) { router.push(`/reports/${encodeURIComponent(id)}`) }

// ==================== Tab2 五维诊断 ====================
const diagnoses = ref([])
const diagLoading = ref(false)
const radarEl = ref(null)
let radarInst = null
const diagSummary = computed(() => ({
  report_count: diagMeta.report_count,
  step_count: new Set(diagnoses.value.map((d) => d.target_id)).size,
}))
const diagMeta = reactive({ report_count: 0 })

/** 五维聚合：各维度计数（雷达图数据源） */
const radarData = computed(() => {
  const cnt = { bottleneck: 0, persistent_error: 0, sequence_chaos: 0, interval: 0, stddev: 0 }
  diagnoses.value.forEach((d) => { if (cnt[d.diagnosis_type] != null) cnt[d.diagnosis_type] += 1 })
  return cnt
})

async function loadDiagnosis() {
  diagLoading.value = true
  try {
    const d = await api.diagnosis({ scope: 'class', ...ws.analysisParams }).catch(() => null)
    diagnoses.value = d?.diagnoses || []
    const sd = await api.stepDuration(ws.analysisParams).catch(() => null)
    diagMeta.report_count = sd?.report_count || 0
    await nextTick()
    renderRadar()
  } finally {
    diagLoading.value = false
  }
}

function renderRadar() {
  if (!radarEl.value) return
  const c = radarData.value
  const max = Math.max(3, ...Object.values(c))
  radarInst = radarInst || echarts.init(radarEl.value)
  radarInst.setOption({
    radar: {
      indicator: [
        { name: '平均用时', max }, { name: '操作错误', max }, { name: '顺序错误', max },
        { name: '步骤间隔', max }, { name: '用时波动', max },
      ],
      radius: '65%',
      splitArea: { areaStyle: { color: ['#fff', '#F5F7FA'] } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: [c.bottleneck, c.persistent_error, c.sequence_chaos, c.interval, c.stddev],
        name: '诊断条数',
        itemStyle: { color: '#2B5CE6' },
        areaStyle: { color: 'rgba(43,92,230,.18)' },
      }],
    }],
  }, true)
}

function exportDiagnosis() {
  // 导出当前诊断列表为 CSV（轻量实现，浏览器端生成）
  const rows = [['诊断类型', '对象', '指标值', '阈值', '建议']]
  const list = diagnoses.value.map((d) => [
    d.diagnosis_type, d.target_id, d.metric_value, d.threshold_value, (d.advice_text || '').replace(/[\n,]/g, ' '),
  ])
  const csv = '\uFEFF' + [...rows, ...list].map((r) => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `五维诊断_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('已导出 CSV（浏览器端生成）')
}

// ==================== Tab3 教学闭环 ====================
const actions = ref([])
const taLoading = ref(false)
const formVisible = ref(false)
const form = reactive({ class_name: '', process_name: '', target_substep: '', description: '' })
const classOptions = ref(['一班', '二班', '三班'])
const verifyRow = ref(null)
const verifyData = ref(null)

async function loadActions() {
  taLoading.value = true
  try {
    const d = await api.listTeachingActions({ class_name: taClsParam.value, limit: 100 }).catch(() => null)
    actions.value = d?.actions || []
  } finally {
    taLoading.value = false
  }
}
const taClsParam = computed(() => '')

function statCount(kind) {
  // 已验证状态存前端会话内（后端 action 表无 trend 字段，验证时临时获取）
  return verified.value.filter((v) => v.trend === kind).length +
    (kind === 'other'
      ? actions.value.filter((a) => !verified.value.some((v) => v.action_id === a.id)).length
      : verified.value.filter((v) => v.trend === kind).length)
}

const verified = ref([])   // {action_id, trend, before, after, delta}

async function toggleVerify(row) {
  if (verifyRow.value?.id === row.id) { verifyRow.value = null; verifyData.value = null; return }
  verifyRow.value = row
  verifyData.value = null
  const d = await api.verifyTeachingAction(row.id).catch(() => null)
  if (d) {
    verifyData.value = d
    const idx = verified.value.findIndex((v) => v.action_id === row.id)
    if (idx >= 0) verified.value[idx] = { action_id: row.id, trend: d.trend }
    else verified.value.push({ action_id: row.id, trend: d.trend })
  }
}

async function saveAction() {
  if (!form.class_name || !form.description) { ElMessage.warning('班级与描述必填'); return }
  await api.createTeachingAction({ ...form, action_date: Date.now() })
  ElMessage.success('教学调整已记录')
  Object.assign(form, { class_name: '', process_name: '', target_substep: '', description: '' })
  formVisible.value = false
  loadActions()
}

function pct(v) { return v == null ? '-' : (v * 100).toFixed(1) + '%' }
function signed(v) { return v == null ? '-' : (v > 0 ? '+' : '') + v }
function signedPct(v) { return v == null ? '-' : (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%' }
function deltaCls(v) { return v == null ? '' : v > 0 ? 'd-up' : v < 0 ? 'd-down' : '' }

// ==================== 联动 ====================
watch(() => ws.process, () => {
  if (tab.value === 'diagnosis') loadDiagnosis()
  if (tab.value === 'list') { q.page = 1; loadReports() }
})
watch(tab, (t) => {
  if (t === 'diagnosis' && !diagnoses.value.length) loadDiagnosis()
  if (t === 'teaching' && !actions.value.length) loadActions()
})

function onResize() { radarInst && radarInst.resize() }
onMounted(() => {
  loadReports()
  loadStudentOptions()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.rp-tabs-bar { padding: 4px 16px 0; }
.rp-tabs-bar :deep(.el-tabs__item) { font-size: var(--fs-body); transition: color var(--t-fast); }
.rp-tabs-bar :deep(.el-tabs__active-bar) { height: 3px; border-radius: 2px; }
.tab-body { margin-top: 16px; }
.pager { display: flex; justify-content: flex-end; padding-top: 12px; }
.fb-label { color: var(--c-text-sub); font-size: var(--fs-body); }
.dx-top { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; margin-top: 12px; }
.dx-radar { width: 100%; height: 260px; }
.dx-summary { display: flex; flex-direction: column; gap: 10px; }
.dx-stat { display: flex; justify-content: space-between; font-size: var(--fs-body); color: var(--c-text-sub); }
.dx-stat b { font-size: var(--fs-num2); color: var(--c-text-main); font-variant-numeric: tabular-nums; }
.dx-tip { margin-top: auto; font-size: var(--fs-aux); color: var(--c-text-weak); }
.dx-list { display: flex; flex-direction: column; gap: 10px; }
.ta-stats { display: flex; align-items: center; gap: 10px; margin: 12px 0; color: var(--c-text-sub); font-size: var(--fs-body); }
.vf-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
.vf-col { background: var(--c-bg); border-radius: 6px; padding: 12px 16px; }
.vf-title { font-weight: 600; margin-bottom: 8px; }
.vf-row { display: flex; justify-content: space-between; padding: 3px 0; color: var(--c-text-sub); }
.vf-row b { font-variant-numeric: tabular-nums; }
.d-up { color: var(--c-success); }
.d-down { color: var(--c-danger); }
.vf-trend { margin-top: 10px; }
</style>
