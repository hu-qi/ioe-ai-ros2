<template>
  <div>
    <el-card>
      <template #header>
        <div class="bar">
          <b>系统设置</b>
          <el-tag :type="dirty ? 'warning' : 'info'" size="small">
            {{ dirty ? '有未保存修改' : '与配置文件一致' }}
          </el-tag>
        </div>
      </template>

      <el-tabs v-model="tab" @tab-change="onTabChange">
        <!-- ================= 诊断规则 ================= -->
        <el-tab-pane label="诊断规则" name="diag">
          <div class="bar" style="margin-bottom:10px">
            <el-button size="small" @click="resetDiag" :disabled="saving">重置（丢弃修改）</el-button>
            <el-button type="primary" size="small" @click="saveDiag" :loading="saving" :disabled="!dirty">
              保存并生效
            </el-button>
          </div>
          <el-alert type="info" :closable="false" style="margin-bottom:12px"
            title="规则类型：bottleneck 用时瓶颈(×SOP倍数) · error 遗漏率 · sequence 顺序错误率 · interval 步骤间隔(ms) · stddev 用时标准差(×均值) · regression 退步预警(最近/历史分比)。保存后立即热重载，无需重启。" />
          <el-tabs v-model="diagTab">
            <el-tab-pane v-for="grp in diagGroups" :key="grp.key" :label="grp.label" :name="grp.key">
              <el-table :data="grp.rows" size="small" stripe>
                <el-table-column label="类型" width="120">
                  <template #default="{ row }">
                    <el-tag size="small">{{ typeLabel(row.type) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="阈值" width="170">
                  <template #default="{ row }">
                    <el-input-number v-model="row.threshold" size="small" :controls="false"
                      style="width:120px" @change="dirty = true" />
                    <span class="unit">{{ unitOf(row.type) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="启用" width="80">
                  <template #default="{ row }">
                    <el-switch v-model="row.enabled" @change="dirty = true" />
                  </template>
                </el-table-column>
                <el-table-column label="窗口" width="190">
                  <template #default="{ row }">
                    <template v-if="row.type === 'regression'">
                      近 <el-input-number v-model="row.window_recent" size="small" :min="1" :controls="false"
                        style="width:56px" @change="dirty = true" /> 次 /
                      前 <el-input-number v-model="row.window_history" size="small" :min="1" :controls="false"
                        style="width:56px" @change="dirty = true" /> 次
                    </template>
                    <span v-else class="unit">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="建议文案" min-width="240">
                  <template #default="{ row }">
                    <el-input v-model="row.suggestion" size="small" @input="dirty = true" />
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <!-- ================= 评分规则 ================= -->
        <el-tab-pane label="评分规则" name="scoring">
          <div class="bar" style="margin-bottom:10px">
            <el-button size="small" @click="resetScoring" :disabled="saving">重置（丢弃修改）</el-button>
            <el-button type="primary" size="small" @click="saveScoring" :loading="saving" :disabled="!dirty">
              保存并生效
            </el-button>
          </div>
          <template v-if="scoring">
            <el-descriptions :column="3" size="small" border style="margin-bottom:12px">
              <el-descriptions-item label="每步基础分">
                <el-input-number v-model="scoring.default.max_score" size="small" :min="0.5" :step="0.5"
                  :controls="false" style="width:80px" @change="dirty = true" />
              </el-descriptions-item>
              <el-descriptions-item label="超时扣分系数">
                <el-input-number v-model="scoring.default.timeout_penalty" size="small" :min="0" :max="1" :step="0.05"
                  :controls="false" style="width:80px" @change="dirty = true" />
              </el-descriptions-item>
              <el-descriptions-item label="轮次超时总分×">
                <el-input-number v-model="scoring.global_penalties.timeout_total_multiplier" size="small" :min="0" :max="1" :step="0.05"
                  :controls="false" style="width:80px" @change="dirty = true" />
              </el-descriptions-item>
              <el-descriptions-item label="未执行每步扣分">
                <el-input-number v-model="scoring.global_penalties.unexecuted_deduct" size="small" :min="0" :step="0.5"
                  :controls="false" style="width:80px" @change="dirty = true" />
              </el-descriptions-item>
              <el-descriptions-item label="重复每次扣分">
                <el-input-number v-model="scoring.global_penalties.repeat_deduct" size="small" :min="0" :step="0.5"
                  :controls="false" style="width:80px" @change="dirty = true" />
              </el-descriptions-item>
            </el-descriptions>

            <el-tabs v-model="scoringTab">
              <el-tab-pane v-for="p in scoringProcesses" :key="p.key" :label="p.label" :name="p.key">
                <el-table :data="p.rows" size="small" stripe>
                  <el-table-column label="子步骤" width="90">
                    <template #default="{ row }">第 {{ row.index }} 步</template>
                  </el-table-column>
                  <el-table-column label="SOP 标准用时 (ms)" width="200">
                    <template #default="{ row }">
                      <el-input-number v-model="row.std_duration_ms" size="small" :min="500" :step="500"
                        :controls="false" style="width:130px" @change="dirty = true" />
                    </template>
                  </el-table-column>
                  <el-table-column label="满分" width="150">
                    <template #default="{ row }">
                      <el-input-number v-model="row.max_score" size="small" :min="0.5" :step="0.5"
                        :controls="false" style="width:90px" @change="dirty = true" />
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>
            </el-tabs>
          </template>
          <el-empty v-else :image-size="50" description="评分规则加载中" />
        </el-tab-pane>

        <!-- ================= 系统信息 ================= -->
        <el-tab-pane label="系统信息" name="sysinfo">
          <el-descriptions v-if="sysinfo" :column="2" size="small" border>
            <el-descriptions-item label="数据库路径">{{ sysinfo.db_path }}</el-descriptions-item>
            <el-descriptions-item label="数据库状态">
              <el-tag :type="sysinfo.db_exists ? 'success' : 'danger'" size="small">
                {{ sysinfo.db_exists ? '正常' : '缺失' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="备份目录">{{ sysinfo.backup_dir }}</el-descriptions-item>
            <el-descriptions-item label="每日备份时刻">{{ sysinfo.backup_time }}</el-descriptions-item>
            <el-descriptions-item label="备份保留天数">{{ sysinfo.backup_keep_days }} 天</el-descriptions-item>
            <el-descriptions-item label="配置热重载">
              <el-button size="small" text type="primary" :loading="reloading" @click="doReload">
                立即重载全部配置
              </el-button>
            </el-descriptions-item>
          </el-descriptions>
          <template v-if="sysinfo && (sysinfo.backups || []).length">
            <h4 style="margin:14px 0 8px">现有备份（最近 20 份）</h4>
            <el-table :data="sysinfo.backups" size="small" stripe max-height="320">
              <el-table-column prop="name" label="文件名" min-width="180" />
              <el-table-column label="大小" width="100">
                <template #default="{ row }">{{ row.size_kb }} KB</template>
              </el-table-column>
              <el-table-column label="时间" width="170">
                <template #default="{ row }">{{ fmtDateTime(row.mtime) }}</template>
              </el-table-column>
            </el-table>
          </template>
          <el-empty v-else-if="sysinfo" :image-size="50" description="暂无备份文件（每日备份时刻自动生成）" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const tab = ref('diag')
const diagTab = ref('common')
const scoringTab = ref('')
const dirty = ref(false)
const saving = ref(false)
const reloading = ref(false)

// ========== 诊断规则 ==========
const TYPE_LABELS = {
  bottleneck: '用时瓶颈', error: '遗漏率', sequence: '顺序混乱',
  interval: '步骤间隔', stddev: '用时差异', regression: '退步预警',
}
const TYPE_UNITS = { bottleneck: '×SOP', error: '', sequence: '', interval: 'ms', stddev: '×均值', regression: '×历史' }
const typeLabel = (t) => TYPE_LABELS[t] || t
const unitOf = (t) => TYPE_UNITS[t] || ''

const diagData = ref(null)
const diagGroups = computed(() => {
  if (!diagData.value) return []
  const out = [{ key: 'common', label: '通用规则', rows: (diagData.value.common_rules || []).map(r => ({ ...r })) }]
  for (const p of diagData.value.processes || []) {
    const seen = new Set()
    const rows = []
    for (const r of (p.rules || [])) {
      if (seen.has(r.type)) continue
      seen.add(r.type)
      rows.push({ ...r })
    }
    out.push({ key: 'proc:' + p.name, label: '工序·' + p.name, rows })
  }
  return out
})

function loadDiag() {
  return api.getDiagnosisRules().then((d) => {
    diagData.value = d
  })
}

function resetDiag() {
  loadDiag().then(() => {
    dirty.value = false
    ElMessage.success('已重置为配置文件当前内容')
  })
}

function buildDiagPayload() {
  const payload = JSON.parse(JSON.stringify(diagData.value))
  const byKey = {}
  for (const grp of diagGroups.value) byKey[grp.key] = grp.rows
  payload.common_rules = byKey['common'] || []
  payload.processes = (payload.processes || []).map(p => ({
    ...p,
    rules: (byKey['proc:' + p.name] || []).map(r => {
      const item = { type: r.type, threshold: r.threshold, enabled: r.enabled, suggestion: r.suggestion }
      if (r.substep_index !== undefined && r.substep_index !== null) item.substep_index = r.substep_index
      if (r.type === 'regression') {
        item.window_recent = r.window_recent
        item.window_history = r.window_history
      }
      return item
    }),
  }))
  return payload
}

async function saveDiag() {
  saving.value = true
  try {
    const res = await api.saveDiagnosisRules(buildDiagPayload())
    await loadDiag()          // 保存后回显：重新拉取文件落盘结果
    dirty.value = false
    ElMessage.success('已保存并生效，热重载: ' + (res?.reload === true ? '成功' : String(res?.reload || '未知')))
  } finally {
    saving.value = false
  }
}

// ========== 评分规则 ==========
const scoring = ref(null)
const scoringProcesses = computed(() => {
  if (!scoring.value) return []
  return (scoring.value.processes || []).map(p => ({
    key: 'sp:' + p.name, label: '工序·' + p.name,
    rows: (p.substeps || []).map(s => ({ ...s })),
  }))
})

function loadScoring() {
  return api.getScoringRules().then((d) => {
    scoring.value = d
    if (!scoringTab.value && d?.processes?.length) scoringTab.value = 'sp:' + d.processes[0].name
  })
}

function resetScoring() {
  loadScoring().then(() => {
    dirty.value = false
    ElMessage.success('已重置为配置文件当前内容')
  })
}

function buildScoringPayload() {
  const payload = JSON.parse(JSON.stringify(scoring.value))
  const byKey = {}
  for (const p of scoringProcesses.value) byKey[p.key] = p.rows
  payload.processes = (payload.processes || []).map(p => ({
    ...p,
    substeps: (byKey['sp:' + p.name] || []).map(s => ({
      index: s.index, std_duration_ms: s.std_duration_ms, max_score: s.max_score,
    })),
  }))
  return payload
}

async function saveScoring() {
  saving.value = true
  try {
    const res = await api.saveScoringRules(buildScoringPayload())
    await loadScoring()       // 保存后回显
    dirty.value = false
    ElMessage.success('已保存并生效，热重载: ' + (res?.reload === true ? '成功' : String(res?.reload || '未知')))
  } finally {
    saving.value = false
  }
}

// ========== 系统信息 ==========
const sysinfo = ref(null)
function loadSysinfo() {
  return api.systemInfo().then((d) => { sysinfo.value = d })
}
async function doReload() {
  reloading.value = true
  try {
    const res = await api.reloadConfig()
    ElMessage.success('配置已重载: ' + JSON.stringify(res?.data || res || {}))
  } finally {
    reloading.value = false
  }
}

const fmtDateTime = (ms) => ms ? new Date(ms).toLocaleString('zh-CN', { hour12: false }) : '-'

function onTabChange(name) {
  // 切到系统信息时刷新备份列表
  if (name === 'sysinfo') loadSysinfo().catch(() => {})
}

onMounted(() => {
  loadDiag().then(() => { if (tab.value === 'diag') dirty.value = false }).catch(() => {})
  loadScoring().catch(() => {})
})
</script>

<style scoped>
.bar { display: flex; justify-content: space-between; align-items: center; }
.unit { color: #909399; font-size: 12px; margin-left: 6px; }
</style>
