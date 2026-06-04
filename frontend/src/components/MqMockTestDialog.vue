<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { mqApi } from '@/api'

const props = defineProps<{
  modelValue: boolean
  apiId: string
  apiName: string
  /** 预填的 Mock 消息体（来自接口文档 mq_invocation.message_example） */
  presetPayload?: Record<string, any> | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
}>()

const payload = ref('{\n  "value": 1\n}')
const snowflakeId = ref('')
const running = ref(false)
const result = ref<any>(null)

function resetEditor() {
  payload.value = props.presetPayload
    ? JSON.stringify(props.presetPayload, null, 2)
    : '{\n  "value": 1\n}'
  snowflakeId.value = ''
  result.value = null
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) resetEditor()
  },
)

function close() {
  emit('update:modelValue', false)
}

function formatPayload() {
  try {
    payload.value = JSON.stringify(JSON.parse(payload.value), null, 2)
  } catch {
    ElMessage.warning('消息体不是合法 JSON，无法格式化')
  }
}

async function run() {
  if (!props.apiId) return
  let body: object
  try {
    body = payload.value.trim() ? JSON.parse(payload.value) : {}
  } catch {
    return ElMessage.error('消息体必须是合法 JSON')
  }
  running.value = true
  result.value = null
  try {
    const res = await mqApi.testRun(props.apiId, {
      payload: body,
      snowflake_id: snowflakeId.value || undefined,
    })
    if (res?.error) {
      ElMessage.error(res.error)
    } else {
      result.value = res
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'MQ Mock 执行失败')
  } finally {
    running.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="MQ 消息 Mock 测试"
    width="640px"
    top="6vh"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
    @close="close"
  >
    <div class="mq-test-target">
      <el-icon><MessageBox /></el-icon>
      <span class="tgt-label">目标接口</span>
      <strong>{{ apiName }}</strong>
      <el-tag size="small" type="primary" effect="plain">MQ 触发</el-tag>
    </div>

    <div class="mq-test-section">
      <div class="mq-test-head">
        <h4>Mock 消息体（JSON）</h4>
        <el-button text size="small" @click="formatPayload">
          <el-icon style="margin-right:4px"><MagicStick /></el-icon>格式化
        </el-button>
      </div>
      <el-input
        v-model="payload"
        type="textarea"
        :rows="7"
        spellcheck="false"
        class="mq-editor"
        placeholder='{ "value": 1 }'
      />
      <div class="mq-hint">将经过接口的 input_mapping 规则提取 inputs，再同步驱动整条流程（不入队，结果实时返回）</div>
    </div>

    <div class="mq-test-section">
      <div class="mq-test-head">
        <h4>snowflakeId（幂等键）</h4>
      </div>
      <el-input v-model="snowflakeId" placeholder="留空自动生成" />
    </div>

    <transition name="mq-fade">
      <div v-if="result" class="mq-result">
        <div class="res-header">
          <el-tag :type="result.status === 'succeeded' ? 'success' : 'danger'" effect="dark">
            <el-icon style="margin-right:4px">
              <CircleCheck v-if="result.status === 'succeeded'" />
              <CircleClose v-else />
            </el-icon>
            {{ result.status === 'succeeded' ? '流程执行成功' : '流程执行失败' }}
          </el-tag>
          <span class="res-id dim" v-if="result.snowflake_id">snowflakeId: {{ result.snowflake_id }}</span>
        </div>

        <div class="res-section" v-if="result.inputs_used && Object.keys(result.inputs_used).length">
          <div class="res-label">实际 inputs（经 input_mapping 提取）</div>
          <pre class="res-pre">{{ JSON.stringify(result.inputs_used, null, 2) }}</pre>
        </div>
        <div class="res-section" v-if="result.outputs !== null && result.outputs !== undefined">
          <div class="res-label">流程输出 outputs（按节点）</div>
          <pre class="res-pre res-output">{{ JSON.stringify(result.outputs, null, 2) }}</pre>
        </div>
      </div>
    </transition>

    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button type="primary" :loading="running" @click="run">
        <el-icon v-if="!running" style="margin-right:6px"><VideoPlay /></el-icon>
        {{ result ? '重新执行' : '执行 Mock 测试' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dim { color: var(--pf-text-dim); }
.mq-test-target {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--pf-panel-2);
  border-radius: 8px;
  margin-bottom: 16px;
  animation: mq-in 0.3s ease;
}
.tgt-label { font-size: 12px; color: var(--pf-text-dim); }
.mq-test-section { margin-bottom: 16px; }
.mq-test-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.mq-test-head h4 { margin: 0; }
.mq-editor :deep(.el-textarea__inner) {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}
.mq-hint { font-size: 12px; color: var(--pf-text-dim); margin-top: 4px; }
.mq-result {
  margin-top: 16px;
  border-top: 1px solid var(--pf-border);
  padding-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.res-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.res-id { font-size: 11px; }
.res-section { display: flex; flex-direction: column; gap: 4px; }
.res-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--pf-text-dim);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.res-err-label { color: #ef4444; }
.res-pre {
  background: var(--pf-panel-2);
  border: 1px solid var(--pf-border);
  border-radius: 6px;
  padding: 10px 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  margin: 0;
}
.res-output { color: #4ade80; }
.res-stderr { color: #f87171; }
@keyframes mq-in {
  from { opacity: 0; transform: translateY(-6px); }
  to   { opacity: 1; transform: translateY(0); }
}
.mq-fade-enter-active { transition: opacity 0.3s, transform 0.3s; }
.mq-fade-enter-from { opacity: 0; transform: translateY(10px); }
</style>
