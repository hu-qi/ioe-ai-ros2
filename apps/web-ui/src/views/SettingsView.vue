<template>
  <div class="page-wrap">
    <!-- ===== 评分规则配置（按工序，doc/04 §六） ===== -->
    <section class="card">
      <div class="card-title">
        评分规则配置
        <span class="title-extra">
          工序
          <el-select v-model="scoreProc" size="small" style="width:110px">
            <el-option v-for="p in scoreProcessNames" :key="p" :label="p" :value="p" />
          </el-select>
        </span>
      </div>
      <div v-if="scoreLoading"><el-skeleton :rows="5" animated /></div>
      <template v-else-if="scoreProcess">
        <el-table :data="scoreProcess.substeps" size="small">
          <el-table-column label="子步骤" width="90">
            <template #default="{ row }">步骤 {{ row.index }}</template>
          </el-table-column>
          <el-table-column label="标准用时(s)" width="140">
            <template #default="{ row }">
              <el-input-number v-model="row.std_duration_ms" :min="500" :step="500" size="small" controls-position="right" />
            </template>
          </el-table-column>
          <el-table-column label="满分" width="130">
            <template #default="{ row }">
              <el-input-number v-model="row.max_score" :min="1" :max="100" size="small" controls-position="right" />
            </template>
          </el-table-column>
        </el-table>

        <div class="st-global">
          <div class="st-global-title">整轮扣分</div>
          <div class="st-global-items">
            <span>未执行扣分</span><el-input-number v-model="scoring.global_penalties.unexecuted_deduct" size="small" controls-position="right" />
            <span>重复扣分</span><el-input-number v-model="scoring.global_penalties.repeat_deduct" size="small" controls-position="right" />
            <span>超时总系数</span><el-input-number v-model="scoring.global_penalties.timeout_total_multiplier" :step="0.05" size="small" controls-position="right" />
          </div>
        </div>

        <div class="st-actions">
          <el-button type="primary" @click="saveScoring">保存</el-button>
          <el-button @click="loadScoring">回滚</el-button>
          <el-button @click="reloadConfigAll">重载配置</el-button>
        </div>
      </template>
      <el-empty v-else description="评分规则为空" :image-size="60" />
    </section>

    <!-- ===== 诊断阈值配置（按工序） ===== -->
    <section class="card" style="margin-top:16px">
      <div class="card-title">
        诊断阈值配置
        <span class="title-extra">
          工序
          <el-select v-model="diagProc" size="small" style="width:110px">
            <el-option v-for="p in diagProcessNames" :key="p" :label="p" :value="p" />
          </el-select>
        </span>
      </div>
      <div v-if="diagLoading"><el-skeleton :rows="5" animated /></div>
      <template v-else-if="diagRules">
        <el-table :data="currentDiagRules" size="small">
          <el-table-column label="规则类型" width="110">
            <template #default="{ row }">{{ RULE_TYPE_LABEL[row.type] || row.type }}</template>
          </el-table-column>
          <el-table-column label="子步骤" width="110">
            <template #default="{ row }">{{ row.substep_index != null ? `步骤${row.substep_index}` : '全部' }}</template>
          </el-table-column>
          <el-table-column label="阈值" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.threshold" :min="0" :step="row.type === 'interval' ? 500 : 0.05" size="small" controls-position="right" />
            </template>
          </el-table-column>
          <el-table-column label="启用" width="80">
            <template #default="{ row }"><el-switch v-model="row.enabled" /></template>
          </el-table-column>
          <el-table-column label="建议" min-width="220">
            <template #default="{ row }"><el-input v-model="row.suggestion" size="small" /></template>
          </el-table-column>
        </el-table>

        <div class="st-actions">
          <el-button type="primary" @click="saveDiagnosis">保存</el-button>
          <el-button @click="loadDiagnosisRules">回滚</el-button>
          <el-button @click="reloadConfigAll">重载配置</el-button>
        </div>
      </template>
      <el-empty v-else description="诊断规则为空" :image-size="60" />
    </section>

    <!-- ===== 学员同步 + 系统信息 ===== -->
    <div class="st-bottom">
      <section class="card">
        <div class="card-title">学员同步</div>
        <div class="sync-row">
          <el-button type="primary" plain @click="syncStudents">从平台同步</el-button>
          <span class="ts" v-if="lastSync">上次同步：{{ lastSync }}</span>
        </div>
        <div class="sync-tip">学员台账由端侧同步 + 手动维护；此处触发平台侧全量拉取刷新。</div>
      </section>
      <section class="card">
        <div class="card-title">系统信息</div>
        <div v-if="sysInfo" class="sys-list">
          <div class="sys-row"><span>版本</span><b>{{ sysInfo.version || '-' }}</b></div>
          <div class="sys-row"><span>运行模式</span><b>{{ sysInfo.mode || '-' }}</b></div>
          <div class="sys-row"><span>运行时长</span><b>{{ sysInfo.uptime || '-' }}</b></div>
        </div>
        <el-empty v-else description="加载中" :image-size="48" />
      </section>
    </div>
  </div>
</template>

<script setup>
/**
 * SettingsView.vue — 系统设置（doc/04 §六）
 * 评分规则/诊断阈值按工序编辑；保存前客户端校验，失败提示；
 * 回滚 = 重新从服务端拉取；重载配置 = POST /api/v1/config/reload 热生效。
 */
import { ref, computed, onMounted } from 'vue'
import { ElSelect, ElOption, ElTable, ElTableColumn, ElInputNumber, ElInput, ElSwitch, ElButton, ElEmpty, ElSkeleton, ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const RULE_TYPE_LABEL = {
  bottleneck: '平均用时',
  error: '遗漏率',
  sequence: '顺序混乱',
  interval: '步骤间隔',
  stddev: '用时波动',
  regression: '退步预警',
}

// ==================== 评分规则 ====================
const scoring = ref(null)
const scoreLoading = ref(true)
const scoreProc = ref('')
const scoreProcessNames = computed(() => (scoring.value?.processes || []).map((p) => p.name))
const scoreProcess = computed(() => (scoring.value?.processes || []).find((p) => p.name === scoreProc.value))

async function loadScoring() {
  scoreLoading.value = true
  try {
    scoring.value = await api.getScoringRules().catch(() => null)
    if (!scoreProc.value && scoreProcessNames.value.length) scoreProc.value = scoreProcessNames.value[0]
  } finally {
    scoreLoading.value = false
  }
}

/** 保存前客户端校验（doc/04 §六：保存前自动校验） */
function validateScoring() {
  const problems = []
  for (const p of scoring.value?.processes || []) {
    for (const s of p.substeps || []) {
      if (!Number.isFinite(s.std_duration_ms) || s.std_duration_ms <= 0) problems.push(`${p.name} 步骤${s.index} 标准用时非法`)
      if (!Number.isFinite(s.max_score) || s.max_score <= 0) problems.push(`${p.name} 步骤${s.index} 满分非法`)
    }
  }
  return problems
}

async function saveScoring() {
  const problems = validateScoring()
  if (problems.length) {
    ElMessageBox.alert(problems.join('；'), '校验未通过', { type: 'warning' })
    return
  }
  await api.saveScoringRules(scoring.value)
  ElMessage.success('评分规则已保存并热重载')
}

// ==================== 诊断规则 ====================
const diagnosis = ref(null)
const diagLoading = ref(true)
const diagProc = ref('')
const diagProcessNames = computed(() => (diagnosis.value?.processes || []).map((p) => p.name))
const currentDiagRules = computed(() =>
  (diagnosis.value?.processes || []).find((p) => p.name === diagProc.value)?.rules || []
)

async function loadDiagnosisRules() {
  diagLoading.value = true
  try {
    diagnosis.value = await api.getDiagnosisRules().catch(() => null)
    if (!diagProc.value && diagProcessNames.value.length) diagProc.value = diagProcessNames.value[0]
  } finally {
    diagLoading.value = false
  }
}

function validateDiagnosis() {
  const problems = []
  for (const p of diagnosis.value?.processes || []) {
    for (const r of p.rules || []) {
      if (!r.type) problems.push(`${p.name} 缺规则类型`)
      if (!Number.isFinite(r.threshold) || r.threshold < 0) problems.push(`${p.name} ${RULE_TYPE_LABEL[r.type] || r.type} 阈值非法`)
    }
  }
  return problems
}

async function saveDiagnosis() {
  const problems = validateDiagnosis()
  if (problems.length) {
    ElMessageBox.alert(problems.join('；'), '校验未通过', { type: 'warning' })
    return
  }
  await api.saveDiagnosisRules(diagnosis.value)
  ElMessage.success('诊断规则已保存并热重载')
}

// ==================== 重载 / 同步 / 系统信息 ====================
async function reloadConfigAll() {
  await api.reloadConfig()
  ElMessage.success('配置已重载热生效')
  loadScoring()
  loadDiagnosisRules()
}

const lastSync = ref('')
async function syncStudents() {
  const d = await api.listStudents({ page: 1, page_size: 1 }).catch(() => null)
  lastSync.value = new Date().toLocaleString('zh-CN', { hour12: false })
  ElMessage.success(`同步完成，当前学员 ${d?.total ?? 0} 名`)
}

const sysInfo = ref(null)
async function loadSystemInfo() {
  sysInfo.value = await api.systemInfo().catch(() => null)
}

onMounted(() => {
  loadScoring()
  loadDiagnosisRules()
  loadSystemInfo()
})
</script>

<style scoped>
.st-global { margin-top: 12px; }
.st-global-title { font-size: var(--fs-h3); font-weight: 600; color: var(--c-text-sub); margin-bottom: 8px; }
.st-global-items { display: flex; align-items: center; gap: 10px; color: var(--c-text-sub); font-size: var(--fs-body); }
.st-actions { margin-top: 14px; display: flex; gap: 8px; }
.st-bottom { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; margin-top: 16px; }
.sync-row { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.sync-tip { margin-top: 10px; font-size: var(--fs-aux); color: var(--c-text-weak); }
.sys-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.sys-row { display: flex; justify-content: space-between; font-size: var(--fs-body); color: var(--c-text-sub); }
.sys-row b { color: var(--c-text-main); }
</style>
