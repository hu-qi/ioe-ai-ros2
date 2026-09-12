<template>
  <div>
    <!-- 页头 -->
    <PageHeader title="学员管理" subtitle="学籍档案 · 批量导入导出">
      <template #actions>
        <el-button type="success" @click="openCreate">新增学员</el-button>
        <el-button @click="importDlg = true">批量导入</el-button>
        <el-button @click="doExport">导出 CSV</el-button>
      </template>
    </PageHeader>

    <!-- 统计概览 -->
    <div class="stat-row">
      <div class="stat-card clickable" @click="router.push('/reports')">
        <div class="stat-num tone-primary">{{ stats.todayExam }}</div>
        <div class="stat-label">今日考试人次</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ stats.avgScore }}</div>
        <div class="stat-label">今日平均分</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ total }}</div>
        <div class="stat-label">学员总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ classes.length }}</div>
        <div class="stat-label">在册班级</div>
      </div>
    </div>

    <!-- 查询 + 列表 -->
    <el-card class="fill-card">
      <div class="filter-bar" style="margin-bottom:12px">
        <el-input v-model="q.keyword" placeholder="姓名 / 工号 / 班级" clearable @keyup.enter="load(1)" />
        <el-select v-model="q.cls" placeholder="全部班级" clearable @change="load(1)">
          <el-option v-for="c in classes" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button text @click="resetQuery">重置</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="id" label="工号" width="110" />
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column prop="cls" label="班级" width="90" />
        <el-table-column prop="trade" label="工种" width="110">
          <template #default="{ row }">{{ row.trade || '-' }}</template>
        </el-table-column>
        <el-table-column prop="enroll_date" label="入学日期" width="110">
          <template #default="{ row }">{{ row.enroll_date || '-' }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="250" fixed="right" class-name="op-col">
          <template #default="{ row }">
            <div class="op-btns">
              <el-button text type="primary" @click="showDetail(row)">详情</el-button>
              <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button text type="danger" @click="confirmDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total"
          layout="total, prev, pager, next, sizes" :page-sizes="[20, 50, 100]"
          background @current-change="load" @size-change="load(1)" />
      </div>
    </el-card>

    <!-- 学员详情抽屉（档案 + 最近考试记录） -->
    <el-drawer v-model="detailDrawer" :title="'学员详情 · ' + (detail?.student?.name || detail?.student?.id || '')" size="52%">
      <template v-if="detail">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="工号">{{ detail.student.id }}</el-descriptions-item>
          <el-descriptions-item label="姓名">{{ detail.student.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="班级">{{ detail.student.cls || '-' }}</el-descriptions-item>
          <el-descriptions-item label="工种">{{ detail.student.trade || '-' }}</el-descriptions-item>
          <el-descriptions-item label="入学日期">{{ detail.student.enroll_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="detail.student.status === 'active' ? 'success' : 'info'" size="small">
              {{ detail.student.status === 'active' ? '在册' : (detail.student.status || '-') }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ detail.student.remark || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="section-title">累计统计</div>
        <el-descriptions v-if="cum" :column="4" size="small" border>
          <el-descriptions-item label="考试次数">{{ cum.exam_count ?? cum.report_count ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="平均分">{{ cum.avg_score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="最高分">{{ cum.max_score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="最低分">{{ cum.min_score ?? '-' }}</el-descriptions-item>
        </el-descriptions>
        <div v-else class="muted">累计统计加载中…</div>

        <div class="section-title">最近考试记录</div>
        <el-empty v-if="!(detail.recent_reports || []).length" description="暂无考试记录" :image-size="60" />
        <el-table v-else :data="detail.recent_reports" size="small" border>
          <el-table-column prop="report_id" label="报告 ID" min-width="160" show-overflow-tooltip />
          <el-table-column prop="device_id" label="设备" width="80" />
          <el-table-column label="用时" width="80">
            <template #default="{ row }">{{ row.duration_ms != null ? Math.round(row.duration_ms / 1000) + 's' : '-' }}</template>
          </el-table-column>
          <el-table-column label="得分" width="70">
            <template #default="{ row }">{{ row.total_score ?? '-' }}</template>
          </el-table-column>
          <el-table-column label="上报时间" width="150">
            <template #default="{ row }">{{ fmtTs(row.ts_upload_ms) }}</template>
          </el-table-column>
        </el-table>
        <div style="margin-top:8px">
          <a :href="'/ui/reports?student_id=' + encodeURIComponent(detail.student.id)" class="muted">在报告管理中查看该学员全部报告 →</a>
        </div>
      </template>
    </el-drawer>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="dlg" :title="editId ? '编辑学员 · ' + editId : '新增学员'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="工号" required>
          <el-input v-model="form.id" :disabled="!!editId" placeholder="如 S2024001" />
        </el-form-item>
        <el-form-item label="姓名" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="班级">
          <el-select v-model="form.cls" style="width:100%" clearable filterable allow-create placeholder="选择或输入新班级">
            <el-option v-for="c in classes" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="工种"><el-input v-model="form.trade" placeholder="如 机修" /></el-form-item>
        <el-form-item label="入学日期">
          <el-date-picker v-model="form.enroll_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入对话框 -->
    <el-dialog v-model="importDlg" title="批量导入学员" width="440px">
      <el-alert type="info" :closable="false" style="margin-bottom:12px"
                title="支持 CSV/Excel 文件，列：工号、姓名、班级、工种、入学日期、备注" />
      <el-upload drag :auto-upload="false" :limit="1" accept=".csv,.xlsx,.xls"
                 :on-change="onFileChange" :on-remove="() => importFile = null">
        <el-icon style="font-size:36px;color:#c0c4cc"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em></div>
      </el-upload>
      <template #footer>
        <el-button @click="importDlg = false">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!importFile" @click="doImport">上传导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import PageHeader from '../components/PageHeader.vue'
import http, { api } from '../api'

const router = useRouter()

const q = ref({ keyword: '', cls: '' })
const rows = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const classes = ref(['一班', '二班', '三班'])
const stats = ref({ todayExam: '-', avgScore: '-' })

const dlg = ref(false)
const editId = ref('')
const saving = ref(false)
const emptyForm = () => ({ id: '', name: '', cls: '', trade: '', enroll_date: '', remark: '' })
const form = ref(emptyForm())

const importDlg = ref(false)
const importing = ref(false)
const importFile = ref(null)
const onFileChange = (file) => { importFile.value = file.raw }

// 学员详情（档案 + 累计统计 + 最近考试记录）
const detailDrawer = ref(false)
const detail = ref(null)
const cum = ref(null)

async function showDetail(row) {
  detailDrawer.value = true
  detail.value = null
  cum.value = null
  detail.value = await api.getStudent(row.id)
  api.studentCumulative({ student_id: row.id })
    .then((d) => { cum.value = d })
    .catch(() => { cum.value = null })
}

async function load(p = 1) {
  loading.value = true
  page.value = p
  try {
    const params = { page: p, page_size: pageSize.value, status: 'all' }
    if (q.value.keyword) params.keyword = q.value.keyword
    if (q.value.cls) params.cls = q.value.cls
    const data = await api.listStudents(params)
    rows.value = data.list || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  q.value = { keyword: '', cls: '' }
  load(1)
}

async function loadStats() {
  try {
    const d = await api.todaySummary()
    stats.value = {
      todayExam: d?.exam_count ?? '-',
      avgScore: d?.avg_score ?? '-',
    }
  } catch { /* 概览失败不阻塞主列表 */ }
}

function openCreate() {
  editId.value = ''
  form.value = emptyForm()
  dlg.value = true
}

function openEdit(row) {
  editId.value = row.id
  form.value = {
    id: row.id, name: row.name || '', cls: row.cls || '', trade: row.trade || '',
    enroll_date: row.enroll_date || '', remark: row.remark || '',
  }
  dlg.value = true
}

async function save() {
  if (!form.value.id.trim() || !form.value.name.trim()) {
    ElMessage.warning('工号与姓名为必填')
    return
  }
  saving.value = true
  try {
    if (editId.value) {
      await api.updateStudent(editId.value, form.value)
      ElMessage.success('学员已更新')
    } else {
      await api.createStudent(form.value)
      ElMessage.success('学员已创建')
    }
    dlg.value = false
    load(page.value)
  } finally {
    saving.value = false
  }
}

async function confirmDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除学员「${row.name || row.id}」？删除后端侧同步将不再下发该学员。`, '删除确认', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  await api.deleteStudent(row.id)
  ElMessage.success('已删除')
  load(page.value)
}

function doExport() {
  const params = {}
  if (q.value.keyword) params.keyword = q.value.keyword
  if (q.value.cls) params.cls = q.value.cls
  // 导出为文件下载（走原生地址，非 axios）
  location.href = api.studentExportUrl(params)
}

async function doImport() {
  if (!importFile.value) { ElMessage.warning('请先选择文件'); return }
  importing.value = true
  const fd = new FormData()
  fd.append('file', importFile.value)
  try {
    const data = await http.post('/students/import', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success(`导入完成：${JSON.stringify(data)}`)
    importDlg.value = false
    importFile.value = null
    load(1)
  } finally {
    importing.value = false
  }
}

load(1)
loadStats()

function fmtTs(ms) {
  if (!ms) return '-'
  return new Date(ms).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.muted { color: #909399; font-size: 12px; }
</style>
