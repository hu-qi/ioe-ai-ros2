// ECharts 按需注册（doc/02 §6.2 前端轻量化：首屏 gzip <500KB）
// 全项目仅用 line/bar 图 + tooltip/legend/grid 组件，CanvasRenderer 体积最小。
// 视图统一从本模块导入 { echarts }，禁止直接 `import * as echarts from 'echarts'`。
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, BarChart, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

export { echarts }
