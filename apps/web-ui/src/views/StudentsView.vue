<template>
  <div class="page-wrap">
    <!-- 工具条：搜索 + 班级 + 状态 + 新增/导入（doc/04 §4.1） -->
    <section class="card">
      <div class="filter-bar">
        <el-input v-model="query.keyword" placeholder="姓名/学号" clearable style="width:180px" @keyup.enter="load" @clear="load" />
        <el-select v-model="query.cls" placeholder="班级：全部" clearable style="width:130px" @change="load">
          <el-option v-for="c in classOptions" :key="c" :label="'班级：' + c" :value="c" />
        </el-select>
        <el-select v-model="query.status" placeholder="状态" style="width:110px" @change="load">
          <el-option label="状态：全部" value="all" />
          <el-option label="正常" value="active" />
          <el-option label="停用" value="inactive" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <div style="flex:1"></div>
        <el-button @click="importVisible = true">批量导入</el-button>
        <el-button type="primary" plain @click="openCreate">+ 新增</el-button>
      </div>
    </section>

    <!-- 学员列表 -->
    <section class="card list-card">
      <el-table :data="rows" v-loading="loading" @row-click="(r) => goDetail(r.id)">
        <el-table-column label="姓名" prop="name" min-width="110" />
        <el-table-column label="学号" prop="id" width="110" />
        <el-table-column label="班级" prop="cls" width="100" />
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.source === 'auto_sync'" size="small" type="warning" effect="plain">端侧自动建档</el-tag>
            <el-tag v-else-if="row.source === 'import'" size="small" type="info" effect="plain">导入</el-tag>
            <el-tag v-else size="small" effect="plain">手动</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工种" prop="trade" width="110">
          <template #default="{ row }">{{ row.trade || '-' }}</template>
        </el-table-column>
        <el-table-column label="考试次数" width="100" align="right">
          <template #default="{ row }">{{ row.exam_count ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="平均分" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.avg_score != null" :class="scoreCls(row.avg_score)">{{ row.avg_score.toFixed(1) }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '正常' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }"><span class="link">详情</span></template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          :page-size="query.page_size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </div>
    </section>

    <!-- 新增/编辑学员（Dialog 仅限短表单，doc/05.1 §10.3） -->
    <el-dialog v-model="editVisible" :title="editingId ? '编辑学员' : '新增学员'" width="420px">
      <el-form :model="form" label-width="64px">
        <el-form-item label="学号" required><el-input v-model="form.id" :disabled="!!editingId" /></el-form-item>
        <el-form-item label="姓名" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="班级"><el-input v-model="form.cls" /></el-form-item>
        <el-form-item label="工种"><el-input v-model="form.trade" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入 -->
    <el-dialog v-model="importVisible" title="批量导入学员" width="460px">
      <input ref="fileRef" type="file" accept=".csv" />
      <div class="import-tip">CSV 格式：id,name,cls（首行表头）</div>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" @click="doImport">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * StudentsView.vue — 学员列表（doc/04 §4.1）
 * 搜索/筛选/分页 + 新增/批量导入；行点击 → 独立学员详情页。
 */
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElTable, ElTableColumn, ElTag, ElButton, ElInput, ElSelect, ElOption, ElDialog, ElForm, ElFormItem, ElPagination, ElMessage } from 'element-plus'
import { api } from '../api'
import { gradeOf } from '../utils/format'

const router = useRouter()

const query = reactive({ keyword: '', cls: '', status: 'all', page: 1, page_size: 20 })
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const classOptions = ref(['一班', '二班', '三班'])

const editVisible = ref(false)
const editingId = ref('')
const form = reactive({ id: '', name: '', cls: '', trade: '', remark: '' })
const importVisible = ref(false)
const fileRef = ref(null)

function scoreCls(v) { return v == null ? '' : 'g-' + gradeOf(Number(v)).type }

async function load() {
  loading.value = true
  try {
    const d = await api.listStudents({ ...query })
    rows.value = (d.students || []).map((s) => ({ ...s }))
    total.value = d.total || 0
    // 从列表数据提取班级选项
    const set = new Set(rows.value.map((r) => r.cls).filter(Boolean))
    set.forEach((c) => { if (!classOptions.value.includes(c)) classOptions.value.push(c) })
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, { id: '', name: '', cls: '', trade: '', remark: '' })
  editVisible.value = true
}
async function save() {
  if (!form.id || !form.name) { ElMessage.warning('学号与姓名必填'); return }
  if (editingId.value) {
    await api.updateStudent(editingId.value, { ...form })
  } else {
    await api.createStudent({ ...form })
  }
  ElMessage.success('已保存')
  editVisible.value = false
  load()
}

async function doImport() {
  const f = fileRef.value?.files?.[0]
  if (!f) { ElMessage.warning('请选择 CSV 文件'); return }
  const fd = new FormData()
  fd.append('file', f)
  const r = await fetch('/api/v1/students/import', { method: 'POST', body: fd }).then((x) => x.json())
  if (r.code === 0) {
    ElMessage.success(`导入完成：新增 ${r.data.created}，更新 ${r.data.updated}，跳过 ${r.data.skipped}`)
    importVisible.value = false
    load()
  } else {
    ElMessage.error(r.message || '导入失败')
  }
}

function goDetail(id) { router.push(`/students/${encodeURIComponent(id)}`) }

onMounted(load)
</script>

<style scoped>
.list-card { margin-top: 16px; }
.g-success { color: var(--c-success); font-weight: 600; }
.g-primary { color: var(--c-primary); font-weight: 600; }
.g-warning { color: var(--c-accent); font-weight: 600; }
.g-danger { color: var(--c-danger); font-weight: 600; }
.pager { display: flex; justify-content: flex-end; padding-top: 12px; }
.import-tip { font-size: var(--fs-aux); color: var(--c-text-weak); margin-top: 8px; }
</style>
