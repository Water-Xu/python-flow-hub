<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'

const props = defineProps<{ executionId?: string }>()

const el = ref<HTMLElement>()
let term: Terminal | null = null
let fit: FitAddon | null = null
let ws: WebSocket | null = null

// WS 断线指数退避重连状态（决策 5：中间层静默断开防护）
let currentExecId: string | undefined
let reconnectAttempt = 0
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let manualClose = false
let finished = false
const MAX_RECONNECT_DELAY = 15000

function writeLine(text: string, color = '') {
  if (!term) return
  const prefix = color ? `\x1b[${color}m` : ''
  const suffix = color ? '\x1b[0m' : ''
  text.split('\n').forEach((l) => term!.writeln(prefix + l + suffix))
}

function scheduleReconnect() {
  if (manualClose || finished || !currentExecId) return
  reconnectAttempt += 1
  // 指数退避 + 抖动：1s, 2s, 4s ... 上限 15s
  const delay = Math.min(MAX_RECONNECT_DELAY, 2 ** (reconnectAttempt - 1) * 1000)
    + Math.floor(Math.random() * 400)
  writeLine(`\x1b[90m连接断开，${Math.round(delay / 1000)}s 后重连（第 ${reconnectAttempt} 次）...\x1b[0m`)
  reconnectTimer = setTimeout(() => currentExecId && openSocket(currentExecId), delay)
}

function openSocket(executionId: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const base = import.meta.env.VITE_BASE_SERVER_URL || ''
  ws = new WebSocket(`${proto}://${location.host}${base}/ws/exec/${executionId}`)

  ws.onopen = () => {
    if (reconnectAttempt > 0) writeLine('\x1b[32m— 已重连，恢复订阅 —\x1b[0m')
    reconnectAttempt = 0
  }
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.stream === 'ping') return
      if (msg.stream === 'control' && msg.line === '__PYFLOW_DONE__') {
        finished = true
        writeLine('— 执行结束 —', '36')
        return
      }
      writeLine(msg.line, msg.stream === 'stderr' ? '31' : '')
    } catch {
      writeLine(ev.data)
    }
  }
  ws.onclose = () => scheduleReconnect()
  ws.onerror = () => ws?.close()
}

function connect(executionId: string) {
  manualClose = true
  ws?.close()
  if (reconnectTimer) clearTimeout(reconnectTimer)
  // 新一次执行：重置重连/完成状态，凭新 execution_id 重新订阅
  manualClose = false
  finished = false
  reconnectAttempt = 0
  currentExecId = executionId
  openSocket(executionId)
}

function disconnect() {
  manualClose = true
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws?.close()
}

defineExpose({ writeLine, clear: () => term?.clear() })

onMounted(() => {
  if (!el.value) return
  term = new Terminal({
    theme: { background: '#1e293b', foreground: '#e5e7eb' },
    fontSize: 13,
    cursorBlink: false,
    convertEol: true,
  })
  fit = new FitAddon()
  term.loadAddon(fit)
  term.open(el.value)
  fit.fit()
  term.writeln('\x1b[90m等待执行输出...\x1b[0m')
  window.addEventListener('resize', () => fit?.fit())
  if (props.executionId) connect(props.executionId)
})

watch(
  () => props.executionId,
  (id) => {
    if (id) connect(id)
  },
)

onBeforeUnmount(() => {
  disconnect()
  term?.dispose()
})
</script>

<template>
  <div ref="el" class="terminal" />
</template>

<style scoped>
.terminal {
  width: 100%;
  height: 100%;
  background: var(--pf-code-bg);
  border: 1px solid var(--pf-border-strong);
  border-radius: 10px;
  padding: 8px;
}
</style>
