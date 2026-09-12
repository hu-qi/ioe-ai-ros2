/**
 * ws.js — WebSocket 复用封装（S2）
 * 复用旧版 websocket.js 的协议约定：连接 /ws/realtime（同源），自动重连 + 消息分发。
 * 旧版实现见 app_mgr_object/components/web/static/js/websocket.js。
 */
import { ElMessage } from 'element-plus'

export function createRealtimeWS({ onMessage, url }) {
  let ws = null
  let closed = false
  let retry = 0
  const MAX_RETRY = 6

  function connect() {
    if (closed) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const target = url || `${proto}://${location.host}/ws`
    try {
      ws = new WebSocket(target)
    } catch (e) {
      scheduleRetry()
      return
    }
    ws.onopen = () => { retry = 0 }
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        if (onMessage) onMessage(msg)
      } catch { /* 非 JSON 消息忽略 */ }
    }
    ws.onclose = () => scheduleRetry()
    ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
  }

  function scheduleRetry() {
    if (closed) return
    if (retry >= MAX_RETRY) {
      ElMessage.warning('实时推送连接已断开，数据为手动刷新模式')
      return
    }
    retry += 1
    setTimeout(connect, Math.min(3000 * retry, 10000))
  }

  connect()
  return {
    close() { closed = true; try { ws && ws.close() } catch { /* noop */ } },
    get connected() { return ws && ws.readyState === 1 },
  }
}
