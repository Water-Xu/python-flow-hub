<script setup lang="ts">
import { computed, ref, watch } from 'vue'

/**
 * 接口/Flow 级 MQ 触发配置表单（决策 3.1 重写为 Flow 级模型 A）。
 *
 * 由 BlockEditor 的块级 MQ 表单迁出并泛化，复用于「接口管理」(ApiPortal/ApiAdmin)：
 * 触发方式 http/mq/both + 队列/条件过滤/输入映射/回复/重试配置。
 * 父组件通过 ref 调用 collect() 取 {trigger_type, mq_config}，读取 errors 做提交前校验。
 */
const props = defineProps<{
  apiId: string
  triggerType?: string
  mqConfig?: Record<string, any>
  /** HTTP 触发配置（input_mapping 等） */
  httpConfig?: Record<string, any>
  /** 当前 API 关联 flow 的可用入口函数列表（由父组件传入，空则不展示选择器） */
  availableEntrypoints?: string[]
  /** API 级 entrypoint（只读展示，用于提示用户当前 API 绑定的函数） */
  apiEntrypoint?: string | null
}>()

interface CarryField {
  source_path: string
  target_field: string
  required: boolean
}

const form = ref({
  trigger_type: 'http',
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
  carry_fields: [] as CarryField[],
  // MQ 专属入口函数覆盖（优先级高于 API 级 entrypoint）
  entrypoint: '' as string,
  // HTTP 触发：以整条请求体为源的输入映射（与 MQ input_mapping 独立）
  http_input_mapping: '{}',
})

function reset() {
  const cfg = props.mqConfig || {}
  const hcfg = props.httpConfig || {}
  form.value = {
    trigger_type: props.triggerType || 'http',
    exchange: cfg.exchange || '',
    queue: cfg.queue || `flow.${props.apiId}.queue`,
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
    carry_fields: (cfg.carry_fields || []).map((f: any) => ({ ...f })),
    entrypoint: cfg.entrypoint || '',
    http_input_mapping: JSON.stringify(hcfg.input_mapping || {}, null, 2),
  }
}

/** MQ 配置中是否有多入口可选 */
const hasMqEntrypointChoice = computed(
  () => (props.availableEntrypoints?.length ?? 0) > 1,
)

// 父组件每次打开不同接口会整体替换 mqConfig/httpConfig（引用变化即可触发），无需 deep 深度遍历
watch(() => [props.apiId, props.triggerType, props.mqConfig, props.httpConfig], reset, { immediate: true })

const mqEnabled = computed(() => form.value.trigger_type !== 'http')
const httpEnabled = computed(() => form.value.trigger_type !== 'mq')

const inputMappingValid = computed(() => {
  try {
    const v = JSON.parse(form.value.input_mapping || '{}')
    return v && typeof v === 'object' && !Array.isArray(v)
  } catch {
    return false
  }
})

const httpInputMappingValid = computed(() => {
  try {
    const v = JSON.parse(form.value.http_input_mapping || '{}')
    return v && typeof v === 'object' && !Array.isArray(v)
  } catch {
    return false
  }
})

// 客户端校验（与后端 validate_mq_config 对齐，决策 1/6/10）
const errors = computed<string[]>(() => {
  const e: string[] = []
  if (!mqEnabled.value) return e
  if (!form.value.queue?.trim()) e.push('主队列名不能为空')
  if (!inputMappingValid.value) e.push('input_mapping 必须是合法 JSON 对象 {目标字段: 源路径}')
  if ((form.value.condition_expression || '').length > 4096) e.push('条件表达式过长（上限 4096）')
  if (form.value.reply_enabled
      && !form.value.reply_routing_key_template?.trim()
      && !form.value.reply_exchange?.trim()) {
    e.push('启用回复时需填写 Reply Routing Key 或 Reply Exchange')
  }
  if (form.value.reply_enabled) {
    for (const f of form.value.carry_fields) {
      if (!f.source_path?.trim() || !f.target_field?.trim()) {
        e.push('透传字段的 source_path 与 target_field 不能为空')
        break
      }
    }
  }
  if (![0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].includes(form.value.max_retry)) {
    e.push('最大重试次数必须是 0~10')
  }
  return e
})

function addCarryField() {
  form.value.carry_fields.push({ source_path: '$.header.snowflakeId', target_field: 'snowflakeId', required: true })
}

function removeCarryField(idx: number) {
  form.value.carry_fields.splice(idx, 1)
}

/** 收集为后端 updateMq 入参；包含 trigger_type、mq_config 和 http_config。 */
function collect(): { trigger_type: string; mq_config: Record<string, any>; http_config: Record<string, any> } {
  // HTTP input_mapping（独立于 MQ，始终收集）
  let http_input_mapping: object = {}
  try {
    http_input_mapping = JSON.parse(form.value.http_input_mapping || '{}')
  } catch {
    http_input_mapping = {}
  }
  const http_config: Record<string, any> = { input_mapping: http_input_mapping }

  if (!mqEnabled.value) {
    return { trigger_type: 'http', mq_config: {}, http_config }
  }
  let input_mapping: object = {}
  try {
    input_mapping = JSON.parse(form.value.input_mapping || '{}')
  } catch {
    input_mapping = {}
  }
  const mq_config: Record<string, any> = {
    enabled: true,
    exchange: form.value.exchange,
    queue: form.value.queue || `flow.${props.apiId}.queue`,
    routing_key: form.value.routing_key,
    prefetch_count: form.value.prefetch_count,
    condition_expression: form.value.condition_expression,
    condition_language: form.value.condition_language,
    input_mapping,
    reply_enabled: form.value.reply_enabled,
    reply_exchange: form.value.reply_exchange,
    reply_routing_key_template: form.value.reply_routing_key_template,
    max_retry: form.value.max_retry,
    retry_delay_ms: form.value.retry_delay_ms,
    carry_fields: form.value.carry_fields,
  }
  if (form.value.entrypoint) {
    mq_config.entrypoint = form.value.entrypoint
  }
  return { trigger_type: form.value.trigger_type, mq_config, http_config }
}

defineExpose({ collect, errors, reset })
</script>

<template>
  <el-form :model="form" label-width="140px" class="mq-trigger-form">
    <el-form-item label="触发方式">
      <el-radio-group v-model="form.trigger_type">
        <el-radio-button value="http">仅 HTTP</el-radio-button>
        <el-radio-button value="mq">仅 MQ</el-radio-button>
        <el-radio-button value="both">HTTP + MQ</el-radio-button>
      </el-radio-group>
      <span class="dim" style="margin-left:10px">MQ 触发会消费 flow.{{ apiId }}.queue 驱动整条流程</span>
    </el-form-item>

    <!-- HTTP 输入映射（trigger_type 为 http 或 both 时显示） -->
    <transition name="mq-fade">
      <div v-if="httpEnabled">
        <el-divider content-position="left">HTTP 输入映射</el-divider>
        <el-form-item label="HTTP input_mapping" :class="{ 'has-err': !httpInputMappingValid }">
          <el-input
            v-model="form.http_input_mapping"
            type="textarea"
            :rows="4"
            placeholder='{"flow字段名": "$.请求体路径"}'
            style="font-family:monospace;font-size:12px"
          />
          <p class="dim" :class="{ 'err-text': !httpInputMappingValid }">
            {{ httpInputMappingValid
              ? 'JSON 格式：{目标字段名: JSONPath 来源路径}；留空 = 直接取请求体 inputs 字段（兼容旧调用方）'
              : '⚠ 当前不是合法 JSON 对象' }}
          </p>
        </el-form-item>
        <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px;font-size:12px">
          <template #default>
            配置后，调用方可直接发送<code style="margin:0 4px">{"orderId":"123","amount":100}</code>，
            无需包裹 <code>inputs</code> 字段；服务端按映射规则提取后传入流程。
          </template>
        </el-alert>
      </div>
    </transition>

    <transition name="mq-fade">
      <div v-if="mqEnabled">
        <el-divider content-position="left">MQ 基础</el-divider>
        <el-form-item label="Queue（主队列）">
          <el-input v-model="form.queue" :placeholder="`flow.${apiId}.queue`" />
        </el-form-item>
        <el-form-item label="Exchange">
          <el-input v-model="form.exchange" placeholder="默认 default exchange" />
        </el-form-item>
        <el-form-item label="Routing Key">
          <el-input v-model="form.routing_key" placeholder="与 queue 同名" />
        </el-form-item>
        <el-form-item label="Prefetch">
          <el-input-number v-model="form.prefetch_count" :min="1" :max="100" />
          <span class="dim" style="margin-left:8px">防 KEDA 误扩，建议保持 1</span>
        </el-form-item>

        <!-- MQ 专属入口函数：优先级高于 API 级 entrypoint -->
        <el-form-item label="入口函数">
          <el-select
            v-model="form.entrypoint"
            style="width:100%"
            clearable
            placeholder="继承 API 级设置（或节点默认）"
          >
            <el-option
              v-for="ep in (availableEntrypoints ?? [])"
              :key="ep"
              :label="ep"
              :value="ep"
            />
          </el-select>
          <p class="dim">
            <template v-if="apiEntrypoint">
              API 级已绑定 <code>{{ apiEntrypoint }}</code>；此处设置仅覆盖本 MQ 触发，留空则沿用 API 级。
            </template>
            <template v-else>
              留空则使用节点配置（默认 <code>run</code>）；不同 MQ 触发可绑定不同函数。
            </template>
          </p>
        </el-form-item>

        <el-divider content-position="left">条件过滤（仅 jmespath / jsonpath）</el-divider>
        <el-form-item label="条件语言">
          <el-radio-group v-model="form.condition_language">
            <el-radio-button value="jmespath">JMESPath</el-radio-button>
            <el-radio-button value="jsonpath">JSONPath</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="条件表达式">
          <el-input
            v-model="form.condition_expression"
            placeholder="留空 = 无条件执行；如 header.type == 'order'"
          />
          <p class="dim">命中才执行，未命中直接 ack 跳过</p>
        </el-form-item>

        <el-divider content-position="left">MQ 输入映射</el-divider>
        <el-form-item label="MQ input_mapping" :class="{ 'has-err': !inputMappingValid }">
          <el-input
            v-model="form.input_mapping"
            type="textarea"
            :rows="4"
            placeholder='{"target_field": "$.source.path"}'
            style="font-family:monospace;font-size:12px"
          />
          <p class="dim" :class="{ 'err-text': !inputMappingValid }">
            {{ inputMappingValid
              ? 'JSON 格式：{目标字段名: JSONPath 来源路径}；留空 = 直接透传整条消息体作为流程输入'
              : '⚠ 当前不是合法 JSON 对象' }}
          </p>
        </el-form-item>

        <el-divider content-position="left">回复配置（至少一次，下游去重）</el-divider>
        <el-form-item label="启用回复">
          <el-switch v-model="form.reply_enabled" />
        </el-form-item>
        <template v-if="form.reply_enabled">
          <el-form-item label="Reply Exchange">
            <el-input v-model="form.reply_exchange" placeholder="回复交换机" />
          </el-form-item>
          <el-form-item label="Reply Routing Key">
            <el-input v-model="form.reply_routing_key_template" placeholder="模板，如 reply.{api_id}" />
          </el-form-item>
          <el-form-item label="透传字段 (carry)">
            <div class="carry-table">
              <div v-for="(f, idx) in form.carry_fields" :key="idx" class="carry-row">
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
          <el-input-number v-model="form.max_retry" :min="0" :max="10" />
        </el-form-item>
        <el-form-item label="重试延迟 (ms)">
          <el-input-number v-model="form.retry_delay_ms" :min="100" :max="60000" :step="500" />
          <span class="dim" style="margin-left:8px">DLQ 的 x-message-ttl</span>
        </el-form-item>
      </div>
    </transition>

    <transition name="mq-fade">
      <el-alert
        v-if="errors.length"
        type="error"
        :closable="false"
        show-icon
        title="配置存在问题，请修正后再保存"
        style="margin-bottom:12px"
      >
        <ul class="err-list">
          <li v-for="(msg, i) in errors" :key="i">{{ msg }}</li>
        </ul>
      </el-alert>
    </transition>
  </el-form>
</template>

<style scoped>
.mq-trigger-form { padding-top: 4px; }
.mq-trigger-form .el-form-item { margin-bottom: 16px; }
.dim { color: var(--pf-text-dim); font-size: 12px; }
.carry-table { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.carry-row { display: flex; align-items: center; gap: 8px; }
.err-text { color: var(--el-color-error, #ef4444); }
.has-err :deep(.el-textarea__inner) { border-color: var(--el-color-error, #ef4444); }
.err-list { margin: 4px 0 0; padding-left: 18px; font-size: 12px; }
.err-list li { line-height: 1.6; }
.mq-fade-enter-active, .mq-fade-leave-active { transition: opacity 0.25s ease; }
.mq-fade-enter-from, .mq-fade-leave-to { opacity: 0; }
</style>
