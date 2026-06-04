<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CodeEditor from '@/components/CodeEditor.vue'
import ExecutionTerminal from '@/components/ExecutionTerminal.vue'
import VersionDrawer from '@/components/VersionDrawer.vue'
import JupyterCell from '@/components/JupyterCell.vue'
import { blockApi, mqApi, type Block } from '@/api'

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
const activeTab = ref('code')
const versionDrawer = ref(false)

// 入口函数（一脚本多函数）：测试运行时选择调用哪个函数
const runEntrypoint = ref('run')
const discovering = ref(false)
const entrypoints = computed(() => block.value?.entrypoints || [])

// MQ 配置
const mqForm = ref({
  enabled: false,
  exchange: '',
  queue: '',
  routing_key: '',
  prefetch_count: 1,
  condition_expression: '',
  condition_language: 'jmespath',
  input_mapping: '{}',
  reply_enabled: false,
  reply_exchange: '',
  reply_routing_key_template: '',
  max_retry: 3,
  retry_delay_ms: 5000,
  carry_fields: [] as Array<{ source_path: string; target_field: string; required: boolean }>,
})
const mqSaving = ref(false)
const consumerStatus = ref<any>(null)
const consumerLoading = ref(false)

async function load() {
  block.value = await blockApi.get(blockId)
  code.value = block.value.draft_code
  // 初始化 MQ 表单
  const cfg = block.value.mq_config || {}
  mqForm.value = {
    enabled: block.value.execution_mode !== 'sync_http',
    exchange: cfg.exchange || '',
    queue: cfg.queue || `block.${blockId}.queue`,
    routing_key: cfg.routing_key || '',
    prefetch_count: cfg.prefetch_count || 1,
    condition_expression: cfg.condition_expression || '',
    condition_language: cfg.condition_language || 'jmespath',
    input_mapping: JSON.stringify(cfg.input_mapping || {}, null, 2),
    reply_enabled: cfg.reply_enabled || false,
    reply_exchange: cfg.reply_exchange || '',
    reply_routing_key_template: cfg.reply_routing_key_template || '',
    max_retry: cfg.max_retry ?? 3,
    retry_delay_ms: cfg.retry_delay_ms ?? 5000,
    carry_fields: cfg.carry_fields || [],
  }
  await loadConsumerStatus()
}

async function loadConsumerStatus() {
  if (!block.value) return
  if (!['async_mq', 'both'].includes(block.value.execution_mode)) return
  consumerLoading.value = true
  try {
    consumerStatus.value = await mqApi.getBlockStatus(blockId)
  } catch {
    consumerStatus.value = null
  } finally {
    consumerLoading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    block.value = await blockApi.update(blockId, { draft_code: code.value })
    ElMessage.success('已保存草稿')
  } finally {
    saving.value = false
  }
}

async function discoverFns() {
  discovering.value = true
  try {
    // 先存代码，再静态扫描入口函数
    await blockApi.update(blockId, { draft_code: code.value })
    const res = await blockApi.discoverEntrypoints(blockId)
    if (block.value) block.value.entrypoints = res.entrypoints || []
    ElMessage.success(`识别到 ${res.entrypoints?.length || 0} 个入口函数`)
  } finally {
    discovering.value = false
  }
}

const inputMappingValid = computed(() => {
  try {
    const v = JSON.parse(mqForm.value.input_mapping || '{}')
    return v && typeof v === 'object' && !Array.isArray(v)
  } catch {
    return false
  }
})

// 客户端 MQ 配置校验（与后端 validate_mq_config 对齐，决策 1/6/10）
const mqConfigErrors = computed<string[]>(() => {
  const e: string[] = []
  if (!mqForm.value.enabled) return e
  if (!mqForm.value.queue?.trim()) e.push('主队列名不能为空')
  if (!inputMappingValid.value) e.push('input_mapping 必须是合法 JSON 对象 {目标字段: 源路径}')
  if ((mqForm.value.condition_expression || '').length > 4096) e.push('条件表达式过长（上限 4096）')
  if (mqForm.value.reply_enabled
      && !mqForm.value.reply_routing_key_template?.trim()
      && !mqForm.value.reply_exchange?.trim()) {
    e.push('启用回复时需填写 Reply Routing Key 或 Reply Exchange')
  }
  if (mqForm.value.reply_enabled) {
    for (const f of mqForm.value.carry_fields) {
      if (!f.source_path?.trim() || !f.target_field?.trim()) {
        e.push('透传字段的 source_path 与 target_field 不能为空')
        break
      }
    }
  }
  if (![0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].includes(mqForm.value.max_retry)) {
    e.push('最大重试次数必须是 0~10')
  }
  return e
})

async function saveMqConfig() {
  if (mqConfigErrors.value.length) {
    return ElMessage.error(mqConfigErrors.value[0])
  }
  mqSaving.value = true
  try {
    let input_mapping: object = {}
    try {
      input_mapping = JSON.parse(mqForm.value.input_mapping || '{}')
    } catch {
      mqSaving.value = false
      return ElMessage.error('输入映射必须是合法 JSON')
    }

    const execMode = mqForm.value.enabled ? 'async_mq' : 'sync_http'
    const mqConfig = mqForm.value.enabled ? {
      enabled: true,
      exchange: mqForm.value.exchange,
      queue: mqForm.value.queue || `block.${blockId}.queue`,
      routing_key: mqForm.value.routing_key,
      prefetch_count: mqForm.value.prefetch_count,
      condition_expression: mqForm.value.condition_expression,
      condition_language: mqForm.value.condition_language,
      input_mapping,
      reply_enabled: mqForm.value.reply_enabled,
      reply_exchange: mqForm.value.reply_exchange,
      reply_routing_key_template: mqForm.value.reply_routing_key_template,
      max_retry: mqForm.value.max_retry,
      retry_delay_ms: mqForm.value.retry_delay_ms,
      carry_fields: mqForm.value.carry_fields,
    } : {}

    await blockApi.update(blockId, {
      execution_mode: execMode,
      mq_config: mqConfig,
    })
    block.value = await blockApi.get(blockId)
    ElMessage.success('MQ 配置已保存')
  } finally {
    mqSaving.value = false
  }
}

async function run() {
  running.value = true
  result.value = null
  term.value?.clear()
  try {
    const updated = await blockApi.update(blockId, { draft_code: code.value })
    if (block.value) block.value.entrypoints = updated.entrypoints || []
    let inputs = {}
    try {
      inputs = JSON.parse(inputsText.value)
    } catch {
      ElMessage.warning('输入不是合法 JSON')
      running.value = false
      return
    }
    const res: any = await blockApi.run(blockId, inputs, runEntrypoint.value || 'run')
    lastExecId.value = res.execution_id
    result.value = res
    term.value?.writeLine(res.stdout || '', '')
    if (res.stderr) term.value?.writeLine(res.stderr, '31')
    term.value?.writeLine(`— ${res.status} (${res.duration_ms}ms) —`, '36')
  } finally {
    running.value = false
  }
}

async function startConsumer() {
  try {
    await mqApi.start(blockId)
    ElMessage.success('消费者已启动')
    setTimeout(loadConsumerStatus, 800)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动失败')
  }
}

async function stopConsumer() {
  try {
    await mqApi.stop(blockId)
    ElMessage.success('消费者已停止')
    setTimeout(loadConsumerStatus, 400)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '停止失败')
  }
}

function addCarryField() {
  mqForm.value.carry_fields.push({ source_path: '$.header.snowflakeId', target_field: 'snowflakeId', required: true })
}

function removeCarryField(idx: number) {
  mqForm.value.carry_fields.splice(idx, 1)
}

const isMqMode = computed(() => mqForm.value.enabled)
const statusType: Record<string, string> = {
  running: 'success', connecting: 'warning', stopped: 'info', error: 'danger',
}

onMounted(load)
</script>

<template>
  <div class="page" v-if="block">
    <header class="page-head">
      <div class="head-left">
        <el-button text @click="router.push('/blocks')">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
        <h2>{{ block.name }}</h2>
        <el-tag size="small" effect="dark">{{ block.type }}</el-tag>
        <el-tag size="small" :type="block.execution_mode === 'async_mq' ? 'warning' : 'success'" effect="plain">
          {{ block.execution_mode }}
        </el-tag>
      </div>
      <div>
        <el-button :loading="saving" @click="save">保存草稿</el-button>
        <el-button @click="versionDrawer = true">
          <el-icon><Files /></el-icon> 版本
        </el-button>
        <el-button type="primary" :loading="running" @click="run">
          <el-icon><VideoPlay /></el-icon> 运行
        </el-button>
      </div>
    </header>

    <VersionDrawer
      v-model="versionDrawer"
      resource-type="block"
      :resource-id="blockId"
      :resource-name="block?.name"
      @stable-changed="load"
    />

    <el-tabs v-model="activeTab" class="block-tabs">
      <!-- 代码 Tab -->
      <el-tab-pane label="代码编辑" name="code">
        <div class="editor-grid">
          <div class="editor-pane pf-card">
            <div class="pane-title">
              代码（至少定义一个 <code>def run(inputs)</code>；可定义多个入口函数）
            </div>
            <CodeEditor v-model="code" language="python" class="editor-body" />
          </div>
          <div class="side-pane">
            <div class="pf-card entry-card">
              <div class="pane-head">
                <span class="pane-title" style="margin:0">入口函数</span>
                <el-button size="small" text :loading="discovering" :icon="'Refresh'" @click="discoverFns">
                  重新扫描
                </el-button>
              </div>
              <transition-group name="fn-list" tag="div" class="fn-list">
                <el-tag
                  v-for="fn in entrypoints"
                  :key="fn.name"
                  class="fn-tag"
                  :type="fn.name === runEntrypoint ? 'primary' : 'info'"
                  :effect="fn.name === runEntrypoint ? 'dark' : 'plain'"
                  @click="runEntrypoint = fn.name"
                >
                  ƒ {{ fn.name }}<span v-if="fn.params?.length" class="fn-tag-params">({{ fn.params.join(', ') }})</span>
                </el-tag>
              </transition-group>
              <p v-if="!entrypoints.length" class="dim" style="margin:6px 0 0">
                保存或扫描后显示脚本暴露的入口函数；多函数时可在流程编排中为每个节点选择不同函数。
              </p>
            </div>
            <div class="pf-card input-card">
              <div class="pane-head">
                <span class="pane-title" style="margin:0">输入 JSON</span>
                <el-select v-model="runEntrypoint" size="small" class="run-fn-select" placeholder="run">
                  <el-option
                    v-for="fn in entrypoints"
                    :key="fn.name"
                    :value="fn.name"
                    :label="`ƒ ${fn.name}`"
                  />
                  <el-option v-if="!entrypoints.length" value="run" label="ƒ run" />
                </el-select>
              </div>
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
      </el-tab-pane>

      <!-- Jupyter 调试执行 Tab（决策 9：仅 local 模式，与生产执行链路隔离） -->
      <el-tab-pane label="调试执行 (Jupyter)" name="jupyter">
        <JupyterCell :block-id="blockId" />
      </el-tab-pane>

      <!-- MQ 配置 Tab -->
      <el-tab-pane name="mq">
        <template #label>
          <span>
            MQ 触发配置
            <el-badge v-if="isMqMode" is-dot type="warning" style="margin-left:4px" />
          </span>
        </template>
        <div class="mq-config-panel">
          <!-- 消费者状态 -->
          <div class="pf-card consumer-status-card" v-if="block.execution_mode !== 'sync_http'">
            <div class="cs-header">
              <span class="cs-title">消费者状态</span>
              <div class="cs-actions">
                <el-button size="small" :icon="'Refresh'" @click="loadConsumerStatus" :loading="consumerLoading">刷新</el-button>
                <el-button
                  v-if="consumerStatus?.consumer?.status !== 'running'"
                  type="success"
                  size="small"
                  @click="startConsumer"
                >
                  <el-icon><VideoPlay /></el-icon> 启动
                </el-button>
                <el-button v-else type="warning" size="small" @click="stopConsumer">
                  <el-icon><VideoPause /></el-icon> 停止
                </el-button>
              </div>
            </div>
            <div v-if="consumerStatus?.consumer" class="cs-stats">
              <el-tag :type="statusType[consumerStatus.consumer.status]">
                {{ consumerStatus.consumer.status }}
              </el-tag>
              <span class="dim">已处理 {{ consumerStatus.consumer.processed }}</span>
              <span class="dim">失败 {{ consumerStatus.consumer.errors }}</span>
              <el-badge :value="consumerStatus.queue_depth?.main || 0" type="primary">
                <span class="dim">主队列</span>
              </el-badge>
              <el-badge :value="consumerStatus.queue_depth?.dlq || 0" type="danger">
                <span class="dim">DLQ</span>
              </el-badge>
            </div>
            <div v-else class="dim" style="padding:8px 0">消费者未启动</div>
          </div>

          <el-form :model="mqForm" label-width="130px" class="mq-form">
            <el-divider content-position="left">基础</el-divider>

            <el-form-item label="启用 MQ 触发">
              <el-switch v-model="mqForm.enabled" />
              <span class="dim" style="margin-left:10px">开启后执行模式切换为 async_mq</span>
            </el-form-item>

            <template v-if="mqForm.enabled">
              <el-form-item label="Queue（主队列）">
                <el-input v-model="mqForm.queue" :placeholder="`block.${blockId}.queue`" />
              </el-form-item>
              <el-form-item label="Exchange">
                <el-input v-model="mqForm.exchange" placeholder="默认 default exchange" />
              </el-form-item>
              <el-form-item label="Routing Key">
                <el-input v-model="mqForm.routing_key" placeholder="与 queue 同名" />
              </el-form-item>
              <el-form-item label="Prefetch">
                <el-input-number v-model="mqForm.prefetch_count" :min="1" :max="100" />
                <span class="dim" style="margin-left:8px">防 KEDA 误扩，建议保持 1</span>
              </el-form-item>

              <el-divider content-position="left">条件过滤（仅 jmespath / jsonpath）</el-divider>

              <el-form-item label="条件语言">
                <el-radio-group v-model="mqForm.condition_language">
                  <el-radio-button value="jmespath">JMESPath</el-radio-button>
                  <el-radio-button value="jsonpath">JSONPath</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="条件表达式">
                <el-input
                  v-model="mqForm.condition_expression"
                  placeholder="留空 = 无条件执行；如 header.type == 'order'"
                />
                <p class="dim">命中才执行，未命中直接 ack 跳过</p>
              </el-form-item>

              <el-divider content-position="left">输入映射</el-divider>

              <el-form-item label="input_mapping" :class="{ 'has-err': !inputMappingValid }">
                <el-input
                  v-model="mqForm.input_mapping"
                  type="textarea"
                  :rows="4"
                  placeholder='{"target_field": "$.source.path"}'
                  style="font-family:monospace;font-size:12px"
                />
                <p class="dim" :class="{ 'err-text': !inputMappingValid }">
                  {{ inputMappingValid
                    ? 'JSON 格式：{目标字段名: JSONPath 来源路径}；留空 = 直接透传整条消息体'
                    : '⚠ 当前不是合法 JSON 对象' }}
                </p>
              </el-form-item>

              <el-divider content-position="left">回复配置（至少一次，下游去重）</el-divider>

              <el-form-item label="启用回复">
                <el-switch v-model="mqForm.reply_enabled" />
              </el-form-item>
              <template v-if="mqForm.reply_enabled">
                <el-form-item label="Reply Exchange">
                  <el-input v-model="mqForm.reply_exchange" placeholder="回复交换机" />
                </el-form-item>
                <el-form-item label="Reply Routing Key">
                  <el-input v-model="mqForm.reply_routing_key_template" placeholder="模板，如 reply.{block_id}" />
                </el-form-item>
                <el-form-item label="透传字段 (carry)">
                  <div class="carry-table">
                    <div v-for="(f, idx) in mqForm.carry_fields" :key="idx" class="carry-row">
                      <el-input v-model="f.source_path" placeholder="$.header.snowflakeId" style="flex:1" />
                      <el-icon><Right /></el-icon>
                      <el-input v-model="f.target_field" placeholder="snowflakeId" style="flex:1" />
                      <el-checkbox v-model="f.required" label="必填" />
                      <el-button type="danger" text :icon="'Delete'" @click="removeCarryField(idx)" />
                    </div>
                    <el-button size="small" @click="addCarryField">
                      <el-icon><Plus /></el-icon> 添加透传字段
                    </el-button>
                  </div>
                </el-form-item>
              </template>

              <el-divider content-position="left">重试（TTL+DLX 模式，决策 6）</el-divider>

              <el-form-item label="最大重试次数">
                <el-input-number v-model="mqForm.max_retry" :min="0" :max="10" />
              </el-form-item>
              <el-form-item label="重试延迟 (ms)">
                <el-input-number v-model="mqForm.retry_delay_ms" :min="100" :max="60000" :step="500" />
                <span class="dim" style="margin-left:8px">DLQ 的 x-message-ttl</span>
              </el-form-item>
            </template>

            <transition name="fade">
              <el-alert
                v-if="mqConfigErrors.length"
                type="error"
                :closable="false"
                show-icon
                title="配置存在问题，请修正后再保存"
                style="margin-bottom:12px"
              >
                <ul class="err-list">
                  <li v-for="(msg, i) in mqConfigErrors" :key="i">{{ msg }}</li>
                </ul>
              </el-alert>
            </transition>

            <el-form-item>
              <el-button
                type="primary"
                :loading="mqSaving"
                :disabled="mqConfigErrors.length > 0"
                @click="saveMqConfig"
              >
                保存 MQ 配置
              </el-button>
              <span class="dim" style="margin-left:12px" v-if="!mqForm.enabled">
                已切换为 sync_http 模式
              </span>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>
    </el-tabs>
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
.head-left h2 { margin: 0; }

.block-tabs :deep(.el-tabs__content) { overflow: visible; }

/* 代码编辑 */
.editor-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 16px;
  height: calc(100vh - 180px);
}
.editor-pane {
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.editor-body { flex: 1; margin-top: 8px; }
.side-pane { display: flex; flex-direction: column; gap: 16px; overflow: auto; }
.pane-title { font-size: 13px; color: var(--pf-text-dim); margin-bottom: 8px; }
.input-card, .result-card { padding: 12px; }
.term-card { padding: 12px; flex: 1; min-height: 260px; display: flex; flex-direction: column; }
.term-body { flex: 1; }
.result-card pre { margin: 0; font-size: 12px; color: var(--pf-accent-2); white-space: pre-wrap; }
.mono :deep(textarea) { font-family: 'JetBrains Mono', monospace; }

/* MQ 配置 */
.mq-config-panel {
  max-width: 800px;
  padding: 4px 0;
}
.consumer-status-card {
  padding: 14px 18px;
  margin-bottom: 20px;
}
.cs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.cs-title { font-weight: 600; font-size: 14px; }
.cs-actions { display: flex; gap: 8px; }
.cs-stats { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.mq-form { padding-top: 4px; }
.mq-form .el-form-item { margin-bottom: 16px; }
.dim { color: var(--pf-text-dim); font-size: 12px; }
.carry-table { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.carry-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.err-text { color: var(--el-color-error, #ef4444); }
.has-err :deep(.el-textarea__inner) { border-color: var(--el-color-error, #ef4444); }
.err-list { margin: 4px 0 0; padding-left: 18px; font-size: 12px; }
.err-list li { line-height: 1.6; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.25s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* 入口函数 */
.entry-card { padding: 12px; }
.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.fn-list { display: flex; flex-wrap: wrap; gap: 8px; }
.fn-tag {
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.fn-tag:hover { transform: translateY(-2px); box-shadow: var(--pf-shadow-sm); }
.fn-tag-params { opacity: 0.7; margin-left: 2px; }
.run-fn-select { width: 130px; }
.fn-list-enter-active, .fn-list-leave-active { transition: all 0.25s ease; }
.fn-list-enter-from, .fn-list-leave-to { opacity: 0; transform: scale(0.8); }
</style>
