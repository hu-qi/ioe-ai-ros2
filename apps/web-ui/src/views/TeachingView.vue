<template>
  <div>
    <!-- 页头 -->
    <PageHeader title="教学闭环" subtitle="调整记录 · 前后对比验证 · 学员累计">
      <template #actions>
        <el-button type="primary" @click="dlg = true">记录教学调整</el-button>
      </template>
    </PageHeader>

    <!-- 统计概览 -->
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-num tone-primary">{{ actions.length }}</div>
        <div class="stat-label">调整记录（近 50 条）</div>
      </div>
      <div class="stat-card">
        <div class="stat-num tone-success">{{ improvedCount }}</div>
        <div class="stat-label">验证改善</div>
      </div>
      <div class="stat-card">
        <div class="stat-num tone-warning">{{ declinedCount }}</div>
        <div class="stat-label">验证下降</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ unverifiedCount }}</div>
        <div class="stat-label">待验证</div>
      </div>
    </div>

    <el-row :gutter="12" class="eq-row fill-row">
      <!-- 教学闭环 -->
      <el-col :span="14">
        <el-card>
          <template #header>
            <div class="bar"><b>教学改进闭环</b></div>
          </template>

          <el-table :data="actions" v-loading="loading" stripe>
            <el-table-column prop="action_date" label="日期" width="100">
              <template #default="{ row }">{{ fmtDate(row.action_date) }}</template>
            </el-table-column>
            <el-table-column prop="class_name" label="班级" width="80" />
            <el-table-column prop="process_name" label="工序" width="70">
              <template #default="{ row }">{{ row.process_name || '通用' }}</template>
            </el-table-column>
            <el-table-column prop="description" label="调整内容" min-width="180" show-overflow-tooltip />
            <el-table-column label="效果验证" width="100">
              <template #default="{ row }">
                <el-button text type="primary" @click="verify(row.id)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!actions.length && !loading" description="暂无教学调整记录" :image-size="60" />
        </el-card>
      </el-col>

      <!-- 学员累计 -->
      <el-col :span="10">
        <el-card>
          <template #header><b>学员累计统计</b></template>
          <div class="cum-filters">
            <el-input v-model="sid" placeholder="学员工号" clearable @keyup.enter="loadCum" />
            <el-button type="primary" @click="loadCum">查询</el-button>
          </div>
          <el-descriptions v-if="cum" :column="2" size="small" border class="cum-desc">
            <el-descriptions-item label="考试次数">{{ cum.exam_count ?? cum.report_count ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="平均分">{{ cum.avg_score ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="完成率">{{ pct(cum.completion_rate) }}</el-descriptions-item>
            <el-descriptions-item label="最高分">{{ cum.max_score ?? '-' }}</el-descriptions-item>
          </el-descriptions>
          <template v-if="cum && (cum.weak_steps || cum.top_weak || []).length">
            <div class="section-title">薄弱步骤 TOP3</div>
            <el-table :data="cum.weak_steps || cum.top_weak" size="small" border>
              <el-table-column label="步骤" min-width="120">
                <template #default="{ row }">{{ row.name || ('步骤 ' + row.idx) }}</template>
              </el-table-column>
              <el-table-column label="错误率" width="90">
                <template #default="{ row }">
                  <span v-if="row.error_rate != null" class="danger">{{ (row.error_rate * 100).toFixed(0) }}%</span>
                  <span v-else>-</span>
                </template>
              </el-table-column>
            </el-table>
          </template>
          <el-empty v-else-if="!cum" description="输入工号查询学员累计表现" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 创建对话框 -->
    <el-dialog v-model="dlg" title="记录教学调整" width="480px">
      <el-form label-width="80px">
        <el-form-item label="日期"><el-date-picker v-model="form.action_date" type="datetime" value-format="x" style="width:100%" /></el-form-item>
        <el-form-item label="班级" required><el-input v-model="form.class_name" placeholder="如：一班" /></el-form-item>
        <el-form-item label="工序">
          <el-select v-model="form.process_name" style="width:100%" clearable placeholder="通用">
            <el-option label="拆解" value="拆解" /><el-option label="组装" value="组装" />
          </el-select>
        </el-form-item>
        <el-form-item label="调整内容" required><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createAction">保存</el-button>
      </template>
    </el-dialog>

    <!-- 验证结果对话框 -->
    <el-dialog v-model="vDlg" title="改进效果验证" width="540px">
      <template v-if="verifyData">
        <el-alert v-if="verifyData.trend === 'no_data'" title="窗口内无数据" type="info" :closable="false" />
        <template v-else>
          <el-descriptions :column="3" size="small" border>
            <el-descriptions-item label="">
              <b>前</b><br />均分 {{ verifyData.before?.avg_score ?? '-' }}<br />完成率 {{ pct(verifyData.before?.completion_rate) }}
            </el-descriptions-item>
            <el-descriptions-item label="">
              <b>后</b><br />均分 {{ verifyData.after?.avg_score ?? '-' }}<br />完成率 {{ pct(verifyData.after?.completion_rate) }}
            </el-descriptions-item>
            <el-descriptions-item label="">
              <b>变化</b><br />均分 {{ fmtDelta(verifyData.delta?.avg_score) }}<br />完成率 {{ fmtDelta((verifyData.delta?.completion_rate ?? 0) * 100) }}
            </el-descriptions-item>
          </el-descriptions>
          <el-alert :title="TREND_TEXT[verifyData.trend] || verifyData.trend"
                    :type="verifyData.trend === 'improved' ? 'success' : verifyData.trend === 'declined' ? 'error' : 'warning'"
                    :closable="false" style="margin-top:10px" />
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/PageHeader.vue'
import { api } from '../api'

const TREND_TEXT = { improved: '趋势：改进 ✅', declined: '趋势：下降 ⚠', mixed: '趋势：混合' }

const actions = ref([])
const loading = ref(false)
const saving = ref(false)
const dlg = ref(false)
const form = ref({ action_date: Date.now(), class_name: '', process_name: '', description: '' })
const vDlg = ref(false)
const verifyData = ref(null)
const sid = ref('')
const cum = ref(null)

// 验证状态概览（基于已验证过的缓存结果）
const verifiedMap = ref({})
const improvedCount = computed(() => Object.values(verifiedMap.value).filter(t => t === 'improved').length)
const declinedCount = computed(() => Object.values(verifiedMap.value).filter(t => t === 'declined').length)
const unverifiedCount = computed(() => actions.value.filter(a => !(a.id in verifiedMap.value)).length)

async function loadActions() {
  loading.value = true
  try {
    const data = await api.listTeachingActions({ limit: 50 })
    actions.value = data.actions || []
  } finally {
    loading.value = false
  }
}

async function createAction() {
  if (!form.value.class_name || !form.value.description) {
    ElMessage.warning('班级与调整内容为必填')
    return
  }
  saving.value = true
  try {
    await api.createTeachingAction({ ...form.value })
    ElMessage.success('已记录教学调整')
    dlg.value = false
    form.value = { action_date: Date.now(), class_name: '', process_name: '', description: '' }
    loadActions()
  } finally {
    saving.value = false
  }
}

async function verify(id) {
  verifyData.value = await api.verifyTeachingAction(id)
  verifiedMap.value[id] = verifyData.value?.trend
  vDlg.value = true
}

async function loadCum() {
  if (!sid.value) { ElMessage.warning('请输入工号'); return }
  cum.value = await api.studentCumulative({ student_id: sid.value })
}

const pct = (v) => (v === null || v === undefined) ? '-' : (v * 100).toFixed(1) + '%'
const fmtDelta = (v) => (v > 0 ? '+' : '') + (v ?? 0)
const fmtDate = (ms) => ms ? new Date(ms).toLocaleDateString('zh-CN') : '-'

loadActions()
</script>

<style scoped>
.bar { display: flex; justify-content: space-between; align-items: center; }
/* 左右两模块等高对齐：列拉伸，卡片填满列高 */
.eq-row { align-items: stretch; }
.eq-row :deep(.el-col) { display: flex; }
.eq-row :deep(.el-col > .el-card) { flex: 1; width: 100%; }
.cum-filters { display: flex; gap: 8px; margin-bottom: 10px; }
.cum-filters .el-input { flex: 1; }
.cum-desc { margin-top: 4px; }
.danger { color: #f56c6c; font-weight: 600; }
</style>
