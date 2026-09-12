/**
 * e2e-smoke.cjs — 新版前端 E2E 冒烟测试(doc/79 最终验证)
 * 真实浏览器(Playwright Chromium)加载 http://localhost:9183/ui/,
 * 按 04.1 界面规划与 05.1 交互规范逐页断言 DOM 真实渲染。
 * 运行: node e2e-smoke.cjs  (结果输出 stdout, 截图存 /tmp/e2e-ui/)
 */
const { chromium } = require('playwright')
const fs = require('fs')

const BASE = 'http://localhost:9183'
const SHOT_DIR = '/tmp/e2e-ui'
let pass = 0, fail = 0
const lines = []

function ck(name, ok, extra = '') {
  if (ok) { pass++; lines.push(`PASS | ${name}`) }
  else { fail++; lines.push(`FAIL | ${name} ${extra}`) }
}

;(async () => {
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const browser = await chromium.launch({ chromiumSandbox: false, args: ['--no-sandbox', '--disable-dev-shm-usage'] })
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
  const errors = []
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()) })

  // ============ 首页驾驶舱(04.1 §三 5区域 + 05.1 §6) ============
  await page.goto(`${BASE}/ui/`, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('.top-nav', { timeout: 15000 })
  await page.waitForTimeout(1500)

  // 05.1 §5.1: 56px 白底顶栏 + 三页导航 + 设置入口
  ck('顶栏存在', await page.locator('.top-nav').count() === 1)
  const navH = await page.locator('.top-nav').evaluate((el) => el.offsetHeight)
  ck('顶栏高56px(05.1§5.1)', navH === 56, `got ${navH}`)
  ck('白底导航(Corporate Clean)', await page.locator('.top-nav').evaluate((el) => getComputedStyle(el).backgroundColor).then((c) => c.includes('255, 255, 255') || c.includes('rgb(255')))
  for (const t of ['首页', '学员', '报告']) ck(`导航项「${t}」`, await page.locator('.nav-item', { hasText: t }).count() >= 1)
  ck('设置入口⚙', await page.locator('.nav-icon').count() >= 1)
  // 04.1§一: 全局工序筛选
  ck('全局工序筛选(04.1§一)', await page.locator('.proc-select').count() === 1)

  // 04.1§3.2 区域① 实时训练动态
  ck('①实时训练动态面板', await page.locator('.rt-panel').count() === 1)
  ck('①面板标题「实时训练动态」', (await page.locator('.rt-panel .card-title').innerText()).includes('实时训练动态'))
  // 04.1§3.3 区域② 概览4指标卡(用户反馈: 2×2)
  const metrics = await page.locator('.ov-grid .metric-card').count()
  ck('②概览4指标卡', metrics === 4, `got ${metrics}`)
  const ovLabel = await page.locator('.ov-panel').evaluate((el) => el.offsetHeight)
  ck('②概览区高≥160px(04.1§3.1下限)', ovLabel >= 160, `got ${ovLabel}`)
  const ovGridCols = await page.locator('.ov-grid').evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length)
  ck('②指标卡2×2网格', ovGridCols === 2, `cols=${ovGridCols}`)
  const ovH = await page.locator('.rt-panel').evaluate((el) => el.offsetHeight)
  const ovH2 = await page.locator('.ov-panel').evaluate((el) => el.offsetHeight)
  ck('②与左栏等高(用户反馈)', Math.abs(ovH - ovH2) <= 2, `rt=${ovH} ov=${ovH2}`)
  // 04.1§3.4 区域③ 五维诊断热点
  ck('③五维诊断热点面板', (await page.locator('.diag-panel .card-title').innerText()).includes('五维诊断热点'))
  // 04.1§3.5 区域④ 需关注学员
  ck('④需关注学员面板', (await page.locator('.att-panel .card-title').innerText()).includes('需关注学员'))
  // 04.1§3.6 区域⑤ 最近完成轮次
  ck('⑤最近完成轮次面板', (await page.locator('.recent-panel .card-title').innerText()).includes('最近完成轮次'))

  // ---- 05.1 §2.4 工作台联动: 点指标卡 → 选中态(不跳转) ----
  const urlBefore = page.url()
  await page.locator('.ov-grid .metric-card').nth(3).click()
  await page.waitForTimeout(400)
  ck('指标卡点击不跳转(05.1§6.2)', page.url() === urlBefore)
  ck('指标卡选中态生效', await page.locator('.ov-grid .metric-card.selected').count() === 1)
  await page.locator('.ov-grid .metric-card').nth(3).click() // 取消

  // ---- 05.1 §八 StudentDrawer: 点需关注学员 → Drawer(不跳页) ----
  const attRow = page.locator('.att-row').first()
  if (await attRow.count()) {
    await attRow.locator('.att-name').click()
    await page.waitForTimeout(800)
    ck('StudentDrawer打开(05.1§八)', await page.locator('.el-drawer').count() >= 1)
    ck('Drawer含学员速览内容', (await page.locator('.el-drawer__header').first().innerText()).includes('学员速览'))
    // 05.1 §10.5 Esc 关 Drawer（等关闭动画结束再断言）
    await page.keyboard.press('Escape')
    await page.waitForTimeout(1000)
    ck('Esc关闭Drawer(05.1§10.5)', await page.locator('.el-overlay:visible').count() === 0)
  } else {
    ck('需关注学员有数据(演示数据)', false, 'att-row为空')
  }

  // ---- 05.1 §七 ReportDrawer: 最近轮次整行点击 ----
  const row1 = page.locator('.recent-panel .el-table__row').first()
  if (await row1.count()) {
    await row1.click()
    await page.waitForTimeout(900)
    ck('ReportDrawer打开(05.1§七)', await page.locator('.el-drawer').count() >= 1)
    ck('Drawer含完整报告入口', await page.locator('.el-drawer').getByText('查看完整报告').count() >= 1)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(400)
  } else {
    ck('最近轮次有数据', false, '表格为空')
  }
  await page.screenshot({ path: `${SHOT_DIR}/01-dashboard.png`, fullPage: true })

  // ============ 05.1 §10.5 Ctrl+F 全局搜索 ============
  await page.keyboard.press('Control+f')
  await page.waitForTimeout(400)
  ck('Ctrl+F打开全局搜索(05.1§10.5)', await page.locator('.el-dialog').getByText('全局搜索').count() >= 1)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // ============ 学员页(04.1 §四) ============
  await page.goto(`${BASE}/ui/students`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  ck('学员页:搜索框', await page.locator('input[placeholder="姓名/学号"]').count() === 1)
  const stuRows = await page.locator('.el-table__row').count()
  ck('学员列表有数据', stuRows >= 1, `rows=${stuRows}`)
  // 04.1§4.1 行点击 → 学员详情页
  await page.locator('.el-table__row').first().click()
  await page.waitForTimeout(1000)
  ck('跳转学员详情页(04.1§4.2)', page.url().includes('/students/'))
  // 04.1§4.2 详情页: 4指标卡+趋势图+薄弱步骤+历史报告
  ck('详情页4指标卡', await page.locator('.dt-metrics .metric-card').count() === 4)
  ck('详情页趋势图容器', await page.locator('.dt-chart').count() === 1)
  const trendRendered = await page.locator('.dt-chart canvas').count()
  ck('趋势图ECharts真实渲染', trendRendered >= 1, `canvas=${trendRendered}`)
  ck('详情页薄弱步骤区', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('薄弱步骤')))
  ck('详情页退步预警区', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('退步预警')))
  ck('详情页历史报告表', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('历史报告')))
  await page.screenshot({ path: `${SHOT_DIR}/02-student-detail.png`, fullPage: true })

  // ============ 报告页(04.1 §五 3Tab) ============
  await page.goto(`${BASE}/ui/reports`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  for (const t of ['报告列表', '五维诊断', '教学闭环']) ck(`Tab「${t}」(04.1§五)`, await page.locator('.el-tabs__item', { hasText: t }).count() === 1)
  const repRows = await page.locator('.el-table__row').count()
  ck('报告列表有数据', repRows >= 1, `rows=${repRows}`)
  // Tab2 五维诊断: 雷达图真实渲染(诊断计算需1~2s,显式等待条目出现)
  await page.locator('.el-tabs__item', { hasText: '五维诊断' }).click()
  await page.waitForSelector('.diag-item', { timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(800)
  ck('五维诊断雷达图渲染', await page.locator('.dx-radar canvas').count() >= 1)
  ck('诊断条目渲染', await page.locator('.diag-item').count() >= 1, `count=${await page.locator('.diag-item').count()}`)
  // 04.1§5.2 诊断条目点击内嵌展开
  await page.locator('.diag-item .diag-row').first().click()
  await page.waitForTimeout(400)
  ck('诊断条目内嵌展开(04.1§5.2)', await page.locator('.diag-item .expand-panel:visible').count() >= 1)
  // Tab3 教学闭环
  await page.locator('.el-tabs__item', { hasText: '教学闭环' }).click()
  await page.waitForTimeout(800)
  ck('教学闭环表格', await page.locator('.el-table__row').count() >= 1)
  ck('闭环新增按钮', await page.getByText('+ 新增教学调整').count() >= 1)
  await page.screenshot({ path: `${SHOT_DIR}/03-reports.png`, fullPage: true })

  // ============ 报告详情页(04.1 §5.4) ============
  await page.locator('.el-tabs__item', { hasText: '报告列表' }).click()
  await page.waitForTimeout(600)
  await page.locator('.el-table__row').first().click()
  await page.waitForTimeout(1200)
  ck('跳转报告详情页(04.1§5.4)', page.url().includes('/reports/'))
  ck('详情页:操作时间线', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('操作时间线')))
  ck('详情页:子步骤得分明细', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('子步骤得分明细')))
  ck('详情页:证据图墙', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('证据图墙')))
  // 04.1§5.4 时间线类型筛选
  ck('时间线筛选(全部/超时/中断)', await page.locator('.el-radio-button').count() >= 3)
  await page.screenshot({ path: `${SHOT_DIR}/04-report-detail.png`, fullPage: true })

  // ============ 设置页(04.1 §六) ============
  await page.goto(`${BASE}/ui/settings`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1000)
  ck('设置:评分规则配置', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('评分规则配置')))
  ck('设置:诊断阈值配置', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('诊断阈值配置')))
  ck('设置:学员同步', (await page.locator('.card-title').allInnerTexts()).some((t) => t.includes('学员同步')))
  ck('设置:按工序切换下拉', await page.locator('.card-title .el-select').count() >= 2)
  await page.screenshot({ path: `${SHOT_DIR}/05-settings.png`, fullPage: true })

  // ============ URL 状态保持(05.1 §10.4) ============
  await page.goto(`${BASE}/ui/`, { waitUntil: 'domcontentloaded' })
  await page.locator('.proc-select').click()
  await page.waitForTimeout(300)
  await page.locator('.el-select-dropdown__item', { hasText: '工序：拆解' }).click()
  await page.waitForTimeout(600)
  ck('工序筛选写入URL(05.1§10.4)', page.url().includes('process='))
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  const procText = await page.locator('.proc-select').innerText()
  ck('刷新后筛选恢复(05.1§10.4)', procText.includes('拆解'), `got=${procText.trim()}`)

  // ============ 运行时错误 ============
  const realErrors = errors.filter((e) =>
    !e.includes('favicon') &&
    !e.includes('Failed to load resource') &&
    !e.includes('evidence'))
  ck('无JS运行时错误', realErrors.length === 0, realErrors.slice(0, 2).join(' | '))

  await browser.close()
  lines.push('')
  lines.push(`==== E2E 汇总: PASS=${pass} FAIL=${fail} ====`)
  console.log(lines.join('\n'))
  fs.writeFileSync('/tmp/e2e-ui/result.txt', lines.join('\n'))
  process.exit(fail > 0 ? 1 : 0)
})().catch((e) => { console.error('E2E 崩溃:', e); process.exit(2) })
