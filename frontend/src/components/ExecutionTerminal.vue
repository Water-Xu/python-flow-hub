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

function writeLine(text: string, color = '') {
  if (!term) return
  const prefix = color ? `\x1b[${color}m` : ''
  const suffix = color ? '\x1b[0m' : ''
  text.split('\n').forEach((l) => term!.writeln(prefix + l + suffix))
}

function connect(executionId: string) {
  ws?.close()
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const base = import.meta.env.VITE_BASE_SERVER_URL || ''
  ws = new WebSocket(`${proto}://${location.host}${base}/ws/exec/${executionId}`)
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.stream === 'ping') return
      if (msg.stream === 'control' && msg.line === '__PYFLOW_DONE__') {
        writeLine('— 执行结束 —', '36')
        return
      }
      writeLine(msg.line, msg.stream === 'stderr' ? '31' : '')
    } catch {
      writeLine(ev.data)
    }
  }
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
  ws?.close()
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
