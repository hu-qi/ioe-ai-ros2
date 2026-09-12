<template>
  <div>
    <!-- 页头 -->
    <PageHeader title="诊断中心" subtitle="五维诊断 · 退步预警 · 证据关联">
      <template #actions>
        <el-button type="primary" :loading="loading" @click="run">执行诊断</el-button>
        <el-button :loading="reloading" @click="reloadRules">热重载规则</el-button>
      </template>
    </PageHeader>

    <!-- 类型统计（点击过滤对应类型） -->
    <div class="stat-row">
      <div class="stat-card clickable" v-for="s in typeStats" :key="s.type"
           :class="{ active: filterType === s.type }" @click="toggleType(s.type)">
        <div class="stat-num" :class="s.tone">{{ s.count }}</div>
        <div class="stat-label">{{ s.label }}</div>
      </div>
      <div class="stat-card" v-if="!typeStats.length && !loading">
        <div class="stat-num">0</div>
        <div class="stat-label">执行诊断后显示分类统计</div>
      </div>
    </div>

    <!-- 筛选 + 结果 -->
    <el-card class="fill-card">
      <div class="filter-bar" style="margin-bottom:12px">
        <el-input v-model="q.cls" placeholder="班级（空 = 全部）" clearable @keyup.enter="run" />
        <el-select v-model="q.process_name" placeholder="全部工序" clearable>
          <el-option label="拆解" value="拆解" />
          <el-option label="组装" value="组装" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="run">执行诊断</el-button>
        <el-button text @click="resetQuery">重置</el-button>
        <span v-if="filterType" class="muted">已过滤：{{ TYPE_META[filterType]?.label || filterType }}
          <el-button text type="primary" size="small" @click="filterType = ''">取消</el-button></span>
      </div>

      <div v-loading="loading">
        <el-empty v-if="!filtered.length && !loading"
                  description="无诊断结果（指标均未超阈值，或所选范围无数据）" />
        <div v-for="(r, i) in filtered" :key="i" class="diag-item">
          <div class="diag-head">
            <span class="diag-tags">
              <el-tag :type="meta(r).type" size="small">{{ meta(r).label }}</el-tag>
              <b class="target">{{ r.target_id }}</b>
              <el-tag v-if="r.process_name" type="info" size="small">{{ r.process_name }}</el-tag>
            </span>
            <span class="muted">{{ r.metric_label }}</span>
          </div>
          <div class="advice">💡 {{ r.advice_text }}</div>
          <div v-if="(r.evidence || []).length" class="ev-row">
            <template v-for="ev in r.evidence" :key="ev.id ?? ev.ts">
              <a v-if="ev.id" :href="api.evidenceImageUrl(ev.id, false)" target="_blank">
                <img :src="api.evidenceImageUrl(ev.id, true)" loading="lazy" @error="$event.target.style.display='none'" />
              </a>
              <el-tag v-else type="info" size="small">证据 sub{{ ev.sub }}（端侧文件）</el-tag>
            </template>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/PageHeader.vue'
import { api } from '../api'

const TYPE_META = {
  bottleneck:         { label: '全班瓶颈',   type: 'danger',  tone: 'tone-danger' },
  persistent_error:   { label: '顽固错误',   type: 'warning', tone: 'tone-warning' },
  sequence_chaos:     { label: '顺序混乱',   type: 'warning', tone: 'tone-warning' },
  interval:           { label: '衔接卡壳',   type: 'primary', tone: 'tone-primary' },
  stddev:             { label: '用时差异大', type: 'primary', tone: 'tone-primary' },
  student_regression: { label: '学员退步',   type: 'danger',  tone: 'tone-danger' },
}
const meta = (r) => TYPE_META[r.diagnosis_type] || { label: r.diagnosis_type, type: 'info', tone: '' }

const q = ref({ cls: '', process_name: '' })
const results = ref([])
const loading = ref(false)
const reloading = ref(false)
const filterType = ref('')

// 按类型聚合统计（点击卡片过滤）
const typeStats = computed(() => {
  const counts = {}
  for (const r of results.value) {
    counts[r.diagnosis_type] = (counts[r.diagnosis_type] || 0) + 1
  }
  return Object.entries(counts)
    .map(([type, count]) => ({ type, count, label: TYPE_META[type]?.label || type, tone: TYPE_META[type]?.tone || '' }))
    .sort((a, b) => b.count - a.count)
})

// 类型过滤后的结果
const filtered = computed(() =>
  filterType.value ? results.value.filter(r => r.diagnosis_type === filterType.value) : results.value
)

function toggleType(type) {
  filterType.value = filterType.value === type ? '' : type
}

async function run() {
  loading.value = true
  filterType.value = ''
  try {
    const params = {}
    if (q.value.cls) params.cls = q.value.cls
    if (q.value.process_name) params.process_name = q.value.process_name
    const data = await api.diagnosis(params)
    results.value = data.diagnoses || []
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  q.value = { cls: '', process_name: '' }
  filterType.value = ''
  run()
}

async function reloadRules() {
  reloading.value = true
  try {
    await api.reloadConfig()
    ElMessage.success('评分/诊断规则已热重载')
  } finally {
    reloading.value = false
  }
}
</script>

<style scoped>
.muted { color: #909399; font-size: 12px; }
.stat-card.active { border-color: #409eff; box-shadow: 0 0 0 1px #409eff inset; }
.diag-item { border: 1px solid #ebeef5; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px;
  transition: border-color .2s; }
.diag-item:hover { border-color: #c6e2ff; }
.diag-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.diag-tags { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.target { font-size: 15px; }
.advice { margin-top: 6px; color: #606266; font-size: 13px; }
.ev-row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.ev-row img { height: 72px; border-radius: 4px; border: 1px solid #dcdfe6; display: block; }
</style>
