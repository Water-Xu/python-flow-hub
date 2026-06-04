<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import CodeEditor from './CodeEditor.vue'
import { jupyterApi } from '../api'

const props = defineProps<{ blockId: string }>()

interface Cell {
  id: number
  code: string
  output: { stdout: string; stderr: string; result: string; error: any } | null
  running: boolean
}

let seq = 0
const cells = ref<Cell[]>([{ id: ++seq, code: 'print("hello from kernel")', output: null, running: false }])
const status = ref<{ running: boolean; enabled: boolean }>({ running: false, enabled: true })
const busy = ref(false)

async function refreshStatus() {
  try {
    status.value = await jupyterApi.status(props.blockId)
  } catch {
    status.value = { running: false, enabled: false }
  }
}

function addCell() {
  cells.value.push({ id: ++seq, code: '', output: null, running: false })
}

function removeCell(id: number) {
  cells.value = cells.value.filter((c) => c.id !== id)
}

async function runCell(cell: Cell) {
  if (!status.value.enabled) {
    ElMessage.warning('Jupyter 仅在 local 开发模式可用（决策 9）')
    return
  }
  cell.running = true
  try {
    cell.output = await jupyterApi.execute(props.blockId, cell.code)
  } catch (e: any) {
    cell.output = { stdout: '', stderr: String(e?.message || e), result: '', error: null }
  } finally {
    cell.running = false
    refreshStatus()
  }
}

async function interrupt() {
  await jupyterApi.interrupt(props.blockId)
  ElMessage.info('已发送中断信号')
}

async function shutdown() {
  busy.value = true
  try {
    await jupyterApi.shutdown(props.blockId)
    ElMessage.success('内核已关闭')
    refreshStatus()
  } finally {
    busy.value = false
  }
}

onMounted(refreshStatus)
onBeforeUnmount(() => {
  // 切走时不强制关闭内核，保留会话状态（开发体验）
})
</script>

<template>
  <div class="jupyter">
    <div class="jp-bar">
      <el-tag :type="status.running ? 'success' : 'info'" effect="dark" size="small">
        内核{{ status.running ? '运行中' : '未启动' }}
      </el-tag>
      <el-tag v-if="!status.enabled" type="warning" size="small">仅 local 模式可用</el-tag>
      <div class="jp-actions">
        <el-button size="small" @click="addCell"><el-icon><Plus /></el-icon>新增 Cell</el-button>
        <el-button size="small" @click="interrupt" :disabled="!status.running">中断</el-button>
        <el-button size="small" type="danger" plain :loading="busy" @click="shutdown" :disabled="!status.running"
          >关闭内核</el-button
        >
      </div>
    </div>

    <transition-group name="cell" tag="div">
      <div v-for="cell in cells" :key="cell.id" class="jp-cell">
        <div class="jp-cell-head">
          <span class="jp-cell-idx">[{{ cell.id }}]</span>
          <el-button size="small" type="primary" :loading="cell.running" @click="runCell(cell)">
            <el-icon><VideoPlay /></el-icon> 运行
          </el-button>
          <el-button size="small" text type="danger" @click="removeCell(cell.id)">删除</el-button>
        </div>
        <div class="jp-editor">
          <CodeEditor v-model="cell.code" language="python" />
        </div>
        <div v-if="cell.output" class="jp-output">
          <pre v-if="cell.output.stdout" class="out">{{ cell.output.stdout }}</pre>
          <pre v-if="cell.output.result" class="res">{{ cell.output.result }}</pre>
          <pre v-if="cell.output.stderr" class="err">{{ cell.output.stderr }}</pre>
          <pre v-if="cell.output.error" class="err">{{ (cell.output.error.traceback || []).join('\n') }}</pre>
        </div>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.jupyter {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.jp-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.jp-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}
.jp-cell {
  border: 1px solid var(--pf-border);
  border-radius: 10px;
  padding: 10px;
  background: var(--pf-bg-soft, #fafafa);
}
.jp-cell-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.jp-cell-idx {
  color: var(--pf-text-dim);
  font-family: monospace;
}
.jp-editor {
  height: 160px;
}
.jp-output {
  margin-top: 8px;
}
.jp-output pre {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.out {
  background: #f0f2f5;
}
.res {
  background: #e8f5e9;
}
.err {
  background: #fdecea;
  color: #c0392b;
}
.cell-enter-active,
.cell-leave-active {
  transition: all 0.28s ease;
}
.cell-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.cell-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
</style>
