import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import compression from 'vite-plugin-compression'

// P7 方案A: 构建产物挂载到平台 /ui 路径（9183 单入口，见 doc/决策-P7前端重构方案A实施排期.md）
export default defineConfig({
  plugins: [
    vue(),
    // 产出 .gz 预压缩文件（doc/02 §1.2/§6.2 前端轻量化；服务端另挂 GZipMiddleware 兜底）
    compression({ algorithm: 'gzip', threshold: 1024, deleteOriginFile: false })
  ],
  base: '/ui/',
  build: {
    outDir: '../../app_mgr_object/components/web/ui_dist',
    emptyOutDir: true
  },
  server: {
    port: 5183,
    proxy: {
      // 开发期代理到平台（生产同源无需代理）
      '/api': 'http://localhost:9183',
      '/ws': { target: 'ws://localhost:9183', ws: true }
    }
  }
})
