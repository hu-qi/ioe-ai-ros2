<template>
  <div>
    <!-- 页头 -->
    <PageHeader title="报告管理" subtitle="考试记录 · 子步骤明细 · 证据抓拍" />

    <!-- 统计概览 -->
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-num tone-primary">{{ stats.examCount }}</div>
        <div class="stat-label">今日考试人次</div>
      </div>
      <div class="stat-card">
        <div class="stat-num tone-success">{{ stats.avgScore }}</div>
        <div class="stat-label">今日平均分</div>
      </div>
      <div class="stat-card">
        <div class="stat-num" :class="stats.passRate >= 60 ? 'tone-success' : 'tone-warning'">{{ stats.passRate }}%</div>
        <div class="stat-label">今日通过率</div>
        <div class="stat-label">及格线 60 分</div>
      </div>
      <div class="stat-card">
        <div class="stat-num tone-warning">{{ stats.abnormal }}</div>
        <div class="stat-label">今日异常结束</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ total }}</div>
        <div class="stat-label">符合筛选的报告</div>
      </div>
    </div>

    <!-- 查询 + 列表 -->
    <el-card class="fill-card">
      <div class="filter-bar" style="margin-bottom:12px">
        <el-input v-model="q.student_id" placeholder="学员工号" clearable @keyup.enter="load(1)" />
        <el-input v-model="q.device_id" placeholder="设备 ID" clearable @keyup.enter="load(1)" />
        <el-select v-model="q.finish_reason" placeholder="完成状态" clearable>
          <el-option label="正常完成" value="completed" />
          <el-option label="手动结束" value="manual" />
          <el-option label="超时结束" value="timeout" />
          <el-option label="中途复位" value="reset" />
        </el-select>
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button text @click="resetQuery">重置</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" stripe @row-click="showDetail" class="click-rows">
        <el-table-column prop="report_id" label="报告 ID" min-width="170" show-overflow-tooltip />
        <el-table-column label="学员" width="130">
          <template #default="{ row }">{{ row.student_name || '-' }}<span v-if="row.student_id" class="muted">({{ row.student_id }})</span></template>
        </el-table-column>
        <el-table-column prop="device_id" label="设备" width="90" />
        <el-table-column prop="process_name" label="工序" width="80" />
        <el-table-column label="完成" width="90">
          <template #default="{ row }">
            <el-tag :type="FINISH_TYPE[row.finish_reason] || 'info'" size="small">{{ FINISH_LABEL[row.finish_reason] || row.finish_reason || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="得分" width="120">
          <template #default="{ row }">
            <span class="score">{{ row.total_score ?? '-' }}</span>
            <el-tag v-if="row.grade_level" :type="GRADE_TYPE[row.grade_level] || 'info'" size="small" style="margin-left:4px">{{ row.grade_level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="用时" width="90">
          <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="上报时间" width="150">
          <template #default="{ row }">{{ fmtTs(row.ts_upload_ms) }}</template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total"
          layout="total, prev, pager, next" background @current-change="load" />
      </div>
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawer" :title="'报告详情 · ' + (detail?.report?.report_id || '')" size="62%">
      <template v-if="detail">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="学员">{{ detail.report.student_name || '-' }}<span v-if="detail.report.student_id" class="muted">({{ detail.report.student_id }})</span></el-descriptions-item>
          <el-descriptions-item label="设备">{{ detail.report.device_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="工序">{{ detail.report.process_name || detail.report.process_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="完成状态">{{ FINISH_LABEL[detail.report.finish_reason] || detail.report.finish_reason || '-' }}</el-descriptions-item>
          <el-descriptions-item label="得分">
            <span class="score">{{ detail.report.total_score ?? '-' }}</span>
            <el-tag v-if="detail.report.grade_level" :type="GRADE_TYPE[detail.report.grade_level] || 'info'" size="small">{{ detail.report.grade_level }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="用时">{{ fmtDuration(detail.report.duration_ms) }}</el-descriptions-item>
        </el-descriptions>

        <div class="section-title">子步骤明细（得分 / 顺序）</div>
        <el-table :data="detail.substeps || []" size="small" border>
          <el-table-column prop="idx" label="#" width="50" />
          <el-table-column prop="name" label="子步骤" min-width="120" />
          <el-table-column prop="count" label="次数" width="60" />
          <el-table-column prop="total_duration_ms" label="总用时(ms)" width="100" />
          <el-table-column label="超时" width="60">
            <template #default="{ row }"><span :class="row.timeout ? 'danger' : ''">{{ row.timeout ? '是' : '否' }}</span></template>
          </el-table-column>
          <el-table-column label="得分" width="70">
            <template #default="{ row }">{{ row.score ?? '-' }}</template>
          </el-table-column>
          <el-table-column label="顺序" width="70">
            <template #default="{ row }">
              <span v-if="row.sequence_error === 1" class="danger">错误</span>
              <span v-else-if="row.sequence_error === 0">正确</span>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>

        <div class="section-title">证据抓拍</div>
        <div v-loading="evLoading" class="ev-wall">
          <template v-if="evidence.length">
            <div v-for="ev in evidence" :key="ev.id" class="ev-item">
              <a v-if="ev.id" :href="api.evidenceImageUrl(ev.id, false)" target="_blank">
                <img :src="api.evidenceImageUrl(ev.id, true)" :alt="'sub' + ev.sub" loading="lazy"
                     @error="onImgError($event, ev)" />
              </a>
              <div class="ev-cap">
                sub{{ ev.sub }} · t{{ ev.ts }}
                <el-tag v-if="ev.jpg_path" type="success" size="small">JPG</el-tag>
                <el-tag v-else-if="ev.id" type="info" size="small">BMP</el-tag>
                <el-tag v-else type="info" size="small">端侧文件</el-tag>
              </div>
            </div>
          </template>
          <el-empty v-else-if="!evLoading" description="无关联证据" :image-size="60" />
        </div>

        <div class="section-title">事件流</div>
        <el-table :data="(detail.events || []).slice(0, 100)" size="small" border max-height="260">
          <el-table-column prop="ts" label="时间戳(ms)" width="110" />
          <el-table-column prop="kind" label="类型" width="70" />
          <el-table-column prop="step" label="步骤" width="70" />
          <el-table-column prop="sub" label="子步骤" width="70" />
          <el-table-column prop="source" label="来源" width="80" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import { api } from '../api'

const FINISH_LABEL = { completed: '正常完成', manual: '手动结束', timeout: '超时结束', reset: '中途复位' }
const FINISH_TYPE = { completed: 'success', manual: 'warning', timeout: 'danger', reset: 'info' }
const GRADE_TYPE = { '优秀': 'success', '良好': 'primary', '合格': 'warning', '不合格': 'danger' }

const q = ref({ student_id: '', device_id: '', finish_reason: '' })
const rows = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const stats = ref({ examCount: '-', avgScore: '-', passRate: '-', abnormal: '-' })

const drawer = ref(false)
const detail = ref(null)
const evidence = ref([])
const evLoading = ref(false)

async function load(p = 1) {
  loading.value = true
  page.value = p
  try {
    const params = { page: p, page_size: pageSize }
    if (q.value.student_id) params.student_id = q.value.student_id
    if (q.value.device_id) params.device_id = q.value.device_id
    if (q.value.finish_reason) params.finish_reason = q.value.finish_reason
    const data = await api.listReports(params)
    rows.value = data.reports || data.list || []
    total.value = data.total || rows.value.length
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  q.value = { student_id: '', device_id: '', finish_reason: '' }
  load(1)
}

async function loadStats() {
  try {
    const d = await api.todaySummary()
    stats.value = {
      examCount: d?.exam_count ?? '-',
      avgScore: d?.avg_score ?? '-',
      passRate: d?.pass_rate != null ? (d.pass_rate * 100).toFixed(1) : '-',
      abnormal: d?.abnormal_count ?? '-',
    }
  } catch { /* 概览失败不阻塞主列表 */ }
}

async function showDetail(row) {
  drawer.value = true
  detail.value = null
  evidence.value = []
  detail.value = await api.getReport(row.report_id)
  loadEvidence(detail.value.report?.device_id, detail.value.report?.start_ms)
}

async function loadEvidence(deviceId, roundStartMs) {
  if (!deviceId || !roundStartMs) { evidence.value = []; return }
  evLoading.value = true
  try {
    const data = await api.listEvidence({ device_id: deviceId, round_start_ms: roundStartMs })
    evidence.value = data.evidence || []
  } catch {
    evidence.value = []
  } finally {
    evLoading.value = false
  }
}

function onImgError(evt, ev) {
  // 缩略图失败 → 尝试 BMP 原图；再失败显示占位
  if (evt.target.dataset.fallback !== '1' && ev.file_path) {
    evt.target.dataset.fallback = '1'
    evt.target.src = `/api/v1/evidence/{id}/image`.replace('{id}', ev.id)
  } else {
    evt.target.style.visibility = 'hidden'
  }
}

function fmtDuration(ms) {
  if (ms === null || ms === undefined) return '-'
  const s = Math.round(ms / 1000)
  return s >= 60 ? `${Math.floor(s / 60)}m${s % 60}s` : `${s}s`
}
function fmtTs(ms) {
  if (!ms) return '-'
  return new Date(ms).toLocaleString('zh-CN', { hour12: false })
}

load(1)
loadStats()
</script>

<style scoped>
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.muted { color: #909399; font-size: 12px; }
.danger { color: #f56c6c; font-weight: 600; }
.score { font-weight: 600; font-variant-numeric: tabular-nums; }
.click-rows { cursor: pointer; }
.ev-wall { display: flex; flex-wrap: wrap; gap: 10px; min-height: 40px; }
.ev-item { text-align: center; }
.ev-item img { height: 96px; border-radius: 4px; border: 1px solid #dcdfe6; display: block; }
.ev-cap { font-size: 12px; color: #909399; margin-top: 4px; }
</style>
