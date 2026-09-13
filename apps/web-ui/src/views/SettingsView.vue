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
          <div class="sys-row">
            <span>版本</span>
            <!-- 连点 7 次进入开发者模式（Android 彩蛋惯例），查看实时上报日志 -->
            <b class="ver-num" @click="onVersionClick">{{ sysInfo.version || '-' }}</b>
          </div>
          <div class="sys-row"><span>运行模式</span><b>{{ sysInfo.mode || '-' }}</b></div>
          <div class="sys-row"><span>运行时长</span><b>{{ sysInfo.uptime || '-' }}</b></div>
        </div>
        <el-empty v-else description="加载中" :image-size="48" />
      </section>

      <!-- ===== 开发者模式：实时日志（连点版本号 7 次开启） ===== -->
      <section v-if="devMode" class="card dev-card">
        <div class="card-title">
          实时日志 <span class="dev-badge">开发者模式</span>
          <span class="title-extra">
            <span class="ts">边缘上报与平台入库日志（与 journalctl -u app_mgr 同源）</span>
            <el-radio-group v-model="logWindow" size="small" style="margin-left:12px" @change="onWindowChange">
              <el-radio-button :value="5">近5分</el-radio-button>
              <el-radio-button :value="10">近10分</el-radio-button>
              <el-radio-button :value="30">近30分</el-radio-button>
            </el-radio-group>
            <el-switch v-model="autoScroll" size="small" active-text="自动刷新" style="margin-left:12px" />
          </span>
        </div>
        <div ref="logBox" class="dev-log">
          <div v-for="(l, i) in logLines" :key="i" class="dev-line" :class="lineCls(l)">{{ l }}</div>
          <div v-if="!logLines.length" class="dev-line ts">暂无日志…</div>
        </div>
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
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
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

// ==================== 开发者模式：连点版本号 7 次 → 实时日志 ====================
// 状态持久化到 sessionStorage：刷新页面不丢（调试场景），关标签页/会话结束自动退出
const devMode = ref(sessionStorage.getItem('ui_dev_mode') === '1')
const logLines = ref([])
const autoScroll = ref(true)
const logWindow = ref(5) // 回看窗口（分钟）：5/10/30
const logBox = ref(null)
let verClicks = 0
let verClickTimer = null
let logCursor = '' // journal 游标（--show-cursor），空串 = 按时间窗拉取
let logTimer = null

/** 版本号连点 7 次（2s 内）进入开发者模式，再连点 7 次退出 */
function onVersionClick() {
  clearTimeout(verClickTimer)
  verClickTimer = setTimeout(() => { verClicks = 0 }, 2000)
  verClicks += 1
  if (verClicks >= 7) {
    verClicks = 0
    devMode.value = !devMode.value
    sessionStorage.setItem('ui_dev_mode', devMode.value ? '1' : '0')
    if (devMode.value) {
      ElMessage.success('开发者模式已开启')
      restartLogStream()
    } else {
      clearInterval(logTimer)
      ElMessage.info('开发者模式已关闭')
    }
  }
}

/** 时间窗切换：清空缓冲，按新窗口重新回看 */
function onWindowChange() {
  restartLogStream()
}

/** 重置日志流：清空 + 按当前窗口拉取 + 重启 2s 轮询 */
function restartLogStream() {
  clearInterval(logTimer)
  logCursor = ''
  logLines.value = []
  pullLogs()
  logTimer = setInterval(pullLogs, 2000)
}

/** 增量拉取日志（journal 游标；拦截器已解包，返回的就是 data） */
async function pullLogs() {
  try {
    const params = logCursor ? { cursor: logCursor, limit: 300 } : { minutes: logWindow, limit: 300 }
    const d = await api.getDevLogs(params)
    if (!d) return
    if (d.reset || (d.cursor === '' && logCursor)) {
      // 游标失效（journal 轮转/清理）：回退时间窗模式重新回看
      logCursor = ''
      return
    }
    if (!Array.isArray(d.lines)) return
    logCursor = d.cursor ?? logCursor
    if (!d.lines.length) return
    logLines.value.push(...d.lines)
    // 上限 3000 行, 防长驻膨胀
    if (logLines.value.length > 3000) logLines.value = logLines.value.slice(-3000)
    nextTick(() => {
      if (autoScroll.value && logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
    })
  } catch { /* 忽略轮询错误, 下轮重试 */ }
}

/** 日志行按级别着色 */
function lineCls(l) {
  if (/ERROR|Traceback|失败/.test(l)) return 'lv-err'
  if (/WARN/.test(l)) return 'lv-warn'
  if (/POST|PUT \/api|入库/.test(l)) return 'lv-api'
  return ''
}

onUnmounted(() => { clearInterval(logTimer); clearTimeout(verClickTimer) })

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
  // 刷新后开发者模式仍开启(sessionStorage持久化): 恢复日志轮询
  if (devMode.value) {
    restartLogStream()
  }
})
</script>

<style scoped>
.st-global { margin-top: 12px; }
.st-global-title { font-size: var(--fs-h3); font-weight: 600; color: var(--c-text-sub); margin-bottom: 8px; }
.st-global-items { display: flex; align-items: center; gap: 10px; color: var(--c-text-sub); font-size: var(--fs-body); }
.st-actions { margin-top: 14px; display: flex; gap: 8px; }
.st-bottom { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; margin-top: 16px; }
/* 开发者模式日志卡跨满两列(3fr+2fr+gap), 避免挤在窄列里换行错乱 */
.dev-card { grid-column: 1 / -1; }
.sync-row { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.sync-tip { margin-top: 10px; font-size: var(--fs-aux); color: var(--c-text-weak); }
.sys-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.sys-row { display: flex; justify-content: space-between; font-size: var(--fs-body); color: var(--c-text-sub); }
.sys-row b { color: var(--c-text-main); }
.ver-num { cursor: pointer; user-select: none; }
.dev-badge {
  font-size: var(--fs-aux); color: #fff; background: var(--c-primary);
  border-radius: 3px; padding: 1px 6px; margin-left: 8px;
}
.dev-log {
  margin-top: 10px; height: 360px; overflow: auto; background: #0F172A;
  border-radius: 6px; padding: 10px 12px; font-family: ui-monospace, Consolas, monospace;
  font-size: 12px; line-height: 1.7;
}
.dev-line { color: #CBD5E1; word-break: break-all; white-space: pre-wrap; }
.dev-line.lv-err { color: #F87171; }
.dev-line.lv-warn { color: #FBBF24; }
.dev-line.lv-api { color: #60A5FA; }
</style>
