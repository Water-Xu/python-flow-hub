<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CodeEditor from '@/components/CodeEditor.vue'
import ExecutionTerminal from '@/components/ExecutionTerminal.vue'
import { blockApi, type Block } from '@/api'

const route = useRoute()
const router = useRouter()
const blockId = route.params.id as string

const block = ref<Block | null>(null)
const code = ref('')
const inputsText = ref('{\n  "value": 1\n}')
const running = ref(false)
const saving = ref(false)
const lastExecId = ref<string | undefined>()
const result = ref<any>(null)
const term = ref<InstanceType<typeof ExecutionTerminal>>()

async function load() {
  block.value = await blockApi.get(blockId)
  code.value = block.value.draft_code
}

async function save() {
  saving.value = true
  try {
    await blockApi.update(blockId, { draft_code: code.value })
    ElMessage.success('已保存草稿')
  } finally {
    saving.value = false
  }
}

async function run() {
  running.value = true
  result.value = null
  term.value?.clear()
  try {
    await blockApi.update(blockId, { draft_code: code.value })
    let inputs = {}
    try {
      inputs = JSON.parse(inputsText.value)
    } catch {
      ElMessage.warning('输入不是合法 JSON')
      running.value = false
      return
    }
    const res: any = await blockApi.run(blockId, inputs)
    lastExecId.value = res.execution_id
    result.value = res
    term.value?.writeLine(res.stdout || '', '')
    if (res.stderr) term.value?.writeLine(res.stderr, '31')
    term.value?.writeLine(`— ${res.status} (${res.duration_ms}ms) —`, '36')
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-if="block">
    <header class="page-head">
      <div class="head-left">
        <el-button text :icon="'ArrowLeft'" @click="router.push('/blocks')">返回</el-button>
        <h2>{{ block.name }}</h2>
        <el-tag size="small" effect="dark">{{ block.type }}</el-tag>
      </div>
      <div>
        <el-button :loading="saving" @click="save">保存草稿</el-button>
        <el-button type="primary" :loading="running" :icon="'VideoPlay'" @click="run">
          运行（Docker 沙箱）
        </el-button>
      </div>
    </header>

    <div class="editor-grid">
      <div class="editor-pane pf-card">
        <div class="pane-title">代码（须定义 <code>def run(inputs)</code>）</div>
        <CodeEditor v-model="code" language="python" class="editor-body" />
      </div>

      <div class="side-pane">
        <div class="pf-card input-card">
          <div class="pane-title">输入 JSON</div>
          <el-input v-model="inputsText" type="textarea" :rows="5" class="mono" />
        </div>
        <div class="pf-card term-card" :class="{ 'pf-running': running }">
          <div class="pane-title">执行输出</div>
          <ExecutionTerminal ref="term" :execution-id="lastExecId" class="term-body" />
        </div>
        <transition name="fade">
          <div v-if="result" class="pf-card result-card">
            <div class="pane-title">返回值</div>
            <pre>{{ JSON.stringify(result.output, null, 2) }}</pre>
          </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.head-left h2 {
  margin: 0;
}
.editor-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 16px;
  height: calc(100vh - 130px);
}
.editor-pane {
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.editor-body {
  flex: 1;
  margin-top: 8px;
}
.side-pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: auto;
}
.pane-title {
  font-size: 13px;
  color: var(--pf-text-dim);
  margin-bottom: 8px;
}
.input-card,
.result-card {
  padding: 12px;
}
.term-card {
  padding: 12px;
  flex: 1;
  min-height: 260px;
  display: flex;
  flex-direction: column;
}
.term-body {
  flex: 1;
}
.result-card pre {
  margin: 0;
  font-size: 12px;
  color: var(--pf-accent-2);
  white-space: pre-wrap;
}
.mono :deep(textarea) {
  font-family: 'JetBrains Mono', monospace;
}
</style>
