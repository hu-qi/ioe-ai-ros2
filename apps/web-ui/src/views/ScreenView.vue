<template>
  <div class="screen-viewport">
    <div class="screen-stage" :style="stageStyle">
      <!-- 头部 -->
      <header class="scr-header">
        <div class="scr-title">AI 智能教学分析平台</div>
        <div class="scr-sub">教学数据大屏 · 教官端</div>
        <div class="scr-fresh">
          <span class="ws-dot" :class="wsStatus ? 'on' : 'off'"></span>
          <span>{{ wsStatus ? '实时' : '轮询' }} · 更新于 {{ lastUpdate }}</span>
        </div>
        <div class="scr-clock">{{ clock }}</div>
      </header>

      <div class="scr-body">
        <!-- 左栏 -->
        <section class="scr-col">
          <div class="scr-panel" @click="go('/teaching')">
            <div class="panel-title">实时训练进度 <span class="panel-hint">{{ devices.length }} 台设备</span></div>
            <div v-if="st.progress === 'loading'" class="panel-skel"><i></i><i></i><i></i></div>
            <div v-else-if="st.progress === 'failed'" class="panel-error">加载失败 · 自动重试中</div>
            <div v-else-if="!devices.length" class="panel-empty">
              <div class="pe-icon"></div>
              <div class="pe-title">暂无进行中的训练</div>
              <div class="pe-sub">设备开始考试后，此处实时刷新进度</div>
            </div>
            <template v-else>
            <div v-for="p in devices.slice(0, 6)" :key="p.device_id" class="prog-item">
              <div class="prog-head">
                <b>{{ p.device_id }}</b>
                <span class="dim">{{ p.student_name || '未绑定' }}</span>
              </div>
              <div class="prog-bar">
                <div class="prog-fill" :style="{ width: progPct(p) + '%' }"></div>
              </div>
              <div class="prog-foot dim">{{ p.current || '-' }} · {{ fmtElapsed(p.process_elapsed_ms) }}</div>
            </div>
            </template>
          </div>

          <div class="scr-panel grow" @click="go('/diagnosis')">
            <div class="panel-title">预警滚动 <span class="panel-hint">近 {{ alertHours }} 小时</span></div>
            <div v-if="st.alerts === 'loading'" class="panel-skel"><i></i><i></i><i></i></div>
            <div v-else-if="st.alerts === 'failed'" class="panel-error">加载失败 · 自动重试中</div>
            <div v-else-if="!alerts.length" class="panel-empty">
              <div class="pe-icon"></div>
              <div class="pe-title">暂无预警</div>
              <div class="pe-sub">近 {{ alertHours }} 小时教学运行平稳</div>
            </div>
            <div v-else class="alert-scroll">
              <div v-for="(a, i) in alerts" :key="i" class="alert-item">
                <span class="alert-tag" :class="'lv-' + a.kind">{{ a.type_label }}</span>
                <span class="alert-target">{{ a.target }}</span>
                <span class="dim alert-time">{{ fmtTime(a.ts) }}</span>
              </div>
            </div>
          </div>
        </section>

        <!-- 中央区 -->
        <section class="scr-col mid">
          <div class="scr-panel chart-panel" @click="go('/reports')">
            <div class="panel-title">近 {{ trendDays }} 天成绩趋势 <span class="panel-hint">平均分 / 通过率</span></div>
            <div ref="trendChart" class="chart-box"></div>
          </div>
        </section>

        <!-- 右栏 -->
        <section class="scr-col">
          <div class="scr-panel" @click="go('/diagnosis')">
            <div class="panel-title">高频错误点 TOP5</div>
            <div v-if="st.errors === 'loading'" class="panel-skel"><i></i><i></i><i></i></div>
            <div v-else-if="st.errors === 'failed'" class="panel-error">加载失败 · 自动重试中</div>
            <div v-else-if="!errors.length" class="panel-empty">
              <div class="pe-icon"></div>
              <div class="pe-title">暂无高频错误</div>
              <div class="pe-sub">产生考试报告后自动统计错误步骤</div>
            </div>
            <template v-else>
            <div v-for="(e, i) in errors" :key="i" class="err-item">
              <span class="rank" :class="'r' + (i + 1)">{{ i + 1 }}</span>
              <span class="err-name">{{ e.name || ('步骤' + e.idx) }}</span>
              <div class="err-bar">
                <div class="err-fill" :style="{ width: errPct(e) + '%' }"></div>
              </div>
              <span class="err-score">{{ (e.composite_score ?? 0).toFixed(2) }}</span>
            </div>
            </template>
          </div>

          <div class="scr-panel grow" @click="go('/students')">
            <div class="panel-title">需关注学员 <span class="panel-hint">{{ attention.length }} 人</span></div>
            <div v-if="st.attention === 'loading'" class="panel-skel"><i></i><i></i><i></i></div>
            <div v-else-if="st.attention === 'failed'" class="panel-error">加载失败 · 自动重试中</div>
            <div v-else-if="!attention.length" class="panel-empty">
              <div class="pe-icon"></div>
              <div class="pe-title">暂无需关注学员</div>
              <div class="pe-sub">出现退步或成绩波动时自动列入</div>
            </div>
            <div v-for="(s, i) in attention.slice(0, 8)" :key="i" class="att-item">
              <b class="att-name">{{ s.student_name || s.student_id }}</b>
              <span class="att-cls dim">{{ s.student_cls || '-' }}</span>
              <span class="att-reason dim">{{ s.detail || s.reason }}</span>
            </div>
          </div>
        </section>
      </div>

      <!-- 底部 KPI 横条 -->
      <footer class="scr-footer">
        <div class="kpi" @click="go('/reports')">
          <div class="kpi-num"><AnimNumber :value="summary?.exam_count" /></div>
          <div class="kpi-label">今日考试人数</div>
        </div>
        <div class="kpi" @click="go('/reports')">
          <div class="kpi-num"><AnimNumber :value="summary?.avg_score" /></div>
          <div class="kpi-label">今日平均分</div>
        </div>
        <div class="kpi" @click="go('/reports')">
          <div class="kpi-num"><AnimNumber :value="summary?.pass_rate" :decimals="1" suffix="%" /></div>
          <div class="kpi-label">今日通过率</div>
        </div>
        <div class="kpi warn" @click="go('/diagnosis?type=student_regression')">
          <div class="kpi-num"><AnimNumber :value="summary?.pending_tutor_count ?? summary?.attention_count" /></div>
          <div class="kpi-label">待辅导学员</div>
        </div>
        <div class="kpi">
          <div class="kpi-num"><AnimNumber :value="summary?.total_reports" /></div>
          <div class="kpi-label">今日报告总数</div>
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { echarts } from '../echarts'
import { api } from '../api'
import { createRealtimeWS } from '../api/ws'
import AnimNumber from '../components/AnimNumber.vue'

const router = useRouter()

// ========== 状态 ==========
const summary = ref(null)
const devices = ref([])
const alerts = ref([])
const errors = ref([])
const attention = ref([])
const trendDays = 7
const alertHours = 72
const clock = ref('')
const lastUpdate = ref('--:--:--')
const wsStatus = ref(false)
// 各面板数据状态: loading / ok / failed（failed 时显式提示，避免误显"暂无数据"）
const st = ref({ progress: 'loading', alerts: 'loading', errors: 'loading', attention: 'loading' })
const trendChart = ref(null)
let trendInst = null
let ws = null
const timers = []

// 1920×1080 设计稿等比缩放（副屏/投屏适配）
const stageStyle = ref({})
function fitStage() {
  const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080)
  stageStyle.value = {
    transform: `scale(${s})`,
    transformOrigin: 'left top',
    width: '1920px',
    height: '1080px',
  }
}

// ========== 工具 ==========
const pct = (v) => (v === null || v === undefined) ? '-' : (v * 100).toFixed(1) + '%'
const progPct = (p) => {
  const d = p.done, t = p.total
  if (!t) return 0
  return Math.min(100, Math.max(0, Math.round((d / t) * 100)))
}
const errPct = (e) => {
  const max = errors.value[0]?.composite_score || 1
  return Math.min(100, Math.round(((e.composite_score || 0) / max) * 100))
}
const fmtTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const fmtElapsed = (ms) => {
  if (ms == null) return '-'
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)}分${s % 60}秒`
}
const go = (path) => router.push(path)

// echarts 深色公共配置
const axisStyle = {
  axisLine: { lineStyle: { color: 'rgba(140,180,255,.3)' } },
  axisLabel: { color: '#9db8d9', fontSize: 14 },
  splitLine: { lineStyle: { color: 'rgba(140,180,255,.12)' } },
}

function renderTrend(trend) {
  if (!trendChart.value) return
  // 近 N 天窗口补齐：无报告的日期填 0，保证 x 轴始终显示完整日期序列
  const map = Object.fromEntries((trend || []).map(t => [t.date, t]))
  const days = []
  for (let i = trendDays - 1; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    days.push(map[key] || { date: key, report_count: 0, avg_score: 0, pass_rate: 0 })
  }
  trendInst = trendInst || echarts.init(trendChart.value)
  trendInst.setOption({
    grid: { left: 60, right: 60, top: 40, bottom: 36 },
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#cfe3ff' }, top: 0 },
    xAxis: { type: 'category', data: days.map(t => t.date?.slice(5)), ...axisStyle },
    yAxis: [
      { type: 'value', name: '平均分', nameTextStyle: { color: '#9db8d9' }, ...axisStyle },
      { type: 'value', name: '通过率', max: 1, axisLabel: { color: '#9db8d9', formatter: v => (v * 100) + '%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '平均分', type: 'line', smooth: true, data: days.map(t => t.avg_score), itemStyle: { color: '#4dd2ff' }, areaStyle: { color: 'rgba(77,210,255,.15)' } },
      { name: '通过率', type: 'bar', yAxisIndex: 1, data: days.map(t => t.pass_rate), itemStyle: { color: 'rgba(74,222,128,.65)' }, barWidth: 12 },
    ],
  })
}

// ========== 数据加载 ==========
function markUpdate() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  lastUpdate.value = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function loadAll() {
  summary.value = await api.todaySummary().catch(() => null)
  const e = await api.topErrorPoints().catch(() => null)
  st.value.errors = e ? 'ok' : 'failed'
  errors.value = e?.points || []
  const a = await api.attentionStudents().catch(() => null)
  st.value.attention = a ? 'ok' : 'failed'
  attention.value = a?.students || a || []
  const al = await api.recentAlerts({ limit: 30, hours: alertHours }).catch(() => null)
  st.value.alerts = al ? 'ok' : 'failed'
  alerts.value = al?.alerts || []
  const t = await api.scoreTrend({ days: trendDays }).catch(() => null)
  await nextTick()
  renderTrend(t?.trend || [])
  markUpdate()
}

async function refreshProgress() {
  try {
    const d = await api.realtimeProgress()
    devices.value = d?.devices || d || []
    st.value.progress = 'ok'
    markUpdate()
  } catch {
    devices.value = []
    st.value.progress = 'failed'
  }
}

// ========== 生命周期 ==========
onMounted(() => {
  fitStage()
  window.addEventListener('resize', fitStage)
  loadAll()
  refreshProgress()

  const clockTimer = setInterval(() => {
    clock.value = new Date().toLocaleString('zh-CN', { hour12: false })
  }, 1000)
  timers.push(clockTimer)

  // WS 实时刷新进度；断线兜底 30s 轮询
  ws = createRealtimeWS({
    onMessage: (msg) => {
      if (msg.type === 'realtime_progress' || msg.type === 'report.realtime_delta') {
        refreshProgress()
      }
    },
  })
  // 跟踪 WS 连接状态供头部"实时/轮询"标识
  const wsWatch = setInterval(() => { wsStatus.value = !!(ws && ws.connected) }, 2000)
  timers.push(wsWatch)
  const poll = setInterval(refreshProgress, 30000)
  timers.push(poll)
})

onUnmounted(() => {
  timers.forEach(clearInterval)
  ws && ws.close()
  window.removeEventListener('resize', fitStage)
  trendInst && trendInst.dispose()
})
</script>

<style scoped>
.screen-viewport { width: 100vw; height: 100vh; overflow: hidden; background: #0a1428; }
.screen-stage { display: flex; flex-direction: column; color: #d7e6ff; font-size: 16px; }

/* 头部 */
.scr-header { position: relative; height: 76px; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(180deg, rgba(38,80,150,.55), rgba(10,20,40,0)); border-bottom: 1px solid rgba(90,150,255,.25); }
.scr-title { font-size: 34px; font-weight: 700; letter-spacing: 6px; color: #eaf4ff;
  text-shadow: 0 0 18px rgba(77,178,255,.8); }
.scr-sub { position: absolute; left: 28px; font-size: 16px; color: #7f9cc4; }
.scr-clock { position: absolute; right: 28px; font-size: 20px; color: #9db8d9; font-variant-numeric: tabular-nums; }
.scr-fresh { position: absolute; left: 28px; bottom: 8px; font-size: 13px; color: #7f9cc4;
  display: flex; align-items: center; gap: 6px; }
.ws-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.ws-dot.on { background: #4ade80; box-shadow: 0 0 6px rgba(74,222,128,.8); }
.ws-dot.off { background: #ffb054; box-shadow: 0 0 6px rgba(255,176,84,.6); }

/* 三栏 */
.scr-body { flex: 1; display: flex; gap: 14px; padding: 14px 16px; min-height: 0; }
.scr-col { flex: 1; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.scr-col.mid { flex: 1.6; }
.scr-panel { background: rgba(20,42,80,.45); border: 1px solid rgba(90,150,255,.22); border-radius: 10px;
  padding: 14px 16px; display: flex; flex-direction: column; cursor: pointer; transition: border-color .2s, box-shadow .2s;
  flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.scr-panel:hover { border-color: rgba(120,190,255,.6); box-shadow: 0 0 14px rgba(77,178,255,.25); }
.scr-panel::-webkit-scrollbar { width: 6px; }
.scr-panel::-webkit-scrollbar-thumb { background: rgba(90,150,255,.35); border-radius: 3px; }
.scr-panel::-webkit-scrollbar-track { background: transparent; }
.panel-title { font-size: 19px; font-weight: 600; color: #cfe3ff; margin-bottom: 10px;
  border-left: 4px solid #4dd2ff; padding-left: 10px; }
.panel-hint { font-size: 13px; color: #7f9cc4; font-weight: 400; margin-left: 8px; }
/* 空态：图标 + 标题 + 上下文提示（深色大屏专业空态） */
.panel-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 24px 0; text-align: center; }
.pe-icon { width: 44px; height: 44px; border-radius: 50%;
  background: radial-gradient(circle, rgba(77,178,255,.18) 0%, rgba(77,178,255,.05) 70%);
  border: 1px solid rgba(90,150,255,.35); position: relative; }
.pe-icon::after { content: ''; position: absolute; inset: 14px; border-radius: 50%;
  background: rgba(127,156,196,.5); }
.pe-title { color: #9db8d9; font-size: 16px; }
.pe-sub { color: #5f7ba0; font-size: 13px; }
/* 加载骨架：三行占位条 */
.panel-skel { padding: 6px 0; }
.panel-skel i { display: block; height: 14px; margin: 12px 0; border-radius: 4px;
  background: linear-gradient(90deg, rgba(90,150,255,.10) 25%, rgba(90,150,255,.28) 50%, rgba(90,150,255,.10) 75%);
  background-size: 400% 100%; animation: skel 1.4s ease infinite; }
.panel-skel i:nth-child(2) { width: 82%; }
.panel-skel i:nth-child(3) { width: 64%; }
@keyframes skel { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }
/* 加载失败：显式提示（区别于"暂无数据"） */
.panel-error { color: #ff8a8a; padding: 16px 0; text-align: center; font-size: 15px;
  border: 1px dashed rgba(255,107,107,.45); border-radius: 6px; margin-top: 4px; }

/* 实时进度 */
.prog-item { margin-bottom: 12px; }
.prog-head { display: flex; justify-content: space-between; font-size: 16px; }
.prog-bar { height: 10px; background: rgba(90,150,255,.15); border-radius: 5px; margin: 6px 0 4px; overflow: hidden; }
.prog-fill { height: 100%; border-radius: 5px; background: linear-gradient(90deg, #2f7ef0, #4dd2ff); transition: width .6s; }
.dim { color: #8aa6c8; font-size: 13px; }

/* 预警滚动 */
.alert-scroll { flex: 1; overflow: hidden; }
.alert-item { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px dashed rgba(90,150,255,.15); }
.alert-tag { flex-shrink: 0; font-size: 12px; padding: 2px 8px; border-radius: 3px; color: #0a1428; font-weight: 600; }
.alert-tag.lv-diagnosis { background: #ffb054; }
.alert-tag.lv-report { background: #ff6b6b; color: #fff; }
.alert-target { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.alert-time { flex-shrink: 0; }

/* 错误点 TOP5 */
.err-item { display: flex; align-items: center; gap: 10px; margin-bottom: 11px; }
.rank { width: 24px; height: 24px; border-radius: 4px; display: flex; align-items: center; justify-content: center;
  background: rgba(90,150,255,.2); font-size: 14px; flex-shrink: 0; }
.rank.r1 { background: #ff6b6b; color: #fff; }
.rank.r2 { background: #ffb054; color: #0a1428; }
.rank.r3 { background: #f6e05e; color: #0a1428; }
.err-name { width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }
.err-bar { flex: 1; height: 8px; background: rgba(90,150,255,.15); border-radius: 4px; overflow: hidden; }
.err-fill { height: 100%; background: linear-gradient(90deg, #ff8a4d, #ff6b6b); border-radius: 4px; }
.err-score { width: 46px; text-align: right; color: #ffb054; font-size: 14px; font-variant-numeric: tabular-nums; }

/* 需关注学员 */
.att-item { display: flex; align-items: baseline; gap: 10px; padding: 6px 0; border-bottom: 1px dashed rgba(90,150,255,.15); }
.att-name { font-size: 16px; }
.att-cls { flex-shrink: 0; }
.att-reason { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 图表 */
.chart-panel { flex: 1; min-height: 0; }
.chart-box { flex: 1; min-height: 0; }

/* 底部 KPI */
.scr-footer { height: 110px; display: flex; border-top: 1px solid rgba(90,150,255,.25);
  background: linear-gradient(0deg, rgba(38,80,150,.4), rgba(10,20,40,0)); }
.kpi { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; cursor: pointer; }
.kpi + .kpi { border-left: 1px solid rgba(90,150,255,.15); }
.kpi:hover { background: rgba(77,178,255,.08); }
.kpi-num { font-size: 40px; font-weight: 700; color: #4dd2ff; font-variant-numeric: tabular-nums;
  text-shadow: 0 0 12px rgba(77,210,255,.5); }
.kpi.warn .kpi-num { color: #ffb054; text-shadow: 0 0 12px rgba(255,176,84,.5); }
.kpi-label { font-size: 15px; color: #8aa6c8; margin-top: 2px; }
</style>
