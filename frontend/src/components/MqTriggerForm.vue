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

const showOverview = ref(false)

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

    <!-- ── 整体说明面板 ─────────────────────────────────────── -->
    <div class="help-banner" @click="showOverview = !showOverview">
      <el-icon><QuestionFilled /></el-icon>
      <span>MQ 触发是什么？怎么用？</span>
      <span class="help-toggle">{{ showOverview ? '收起 ▲' : '展开 ▼' }}</span>
    </div>
    <transition name="mq-fade">
      <div v-if="showOverview" class="overview-panel">
        <div class="ov-title">📦 核心概念</div>
        <p class="ov-text">MQ 触发让你的 Flow 接入 RabbitMQ 消息队列，上游系统发消息 → Flow 自动执行 → 可选回复结果。
          整个过程完全异步，上游不需要等待 Flow 执行完成。</p>
        <div class="ov-scenarios">
          <div class="ov-scene">
            <div class="ov-scene-title">🛒 场景 1：订单异步处理</div>
            <div class="ov-scene-desc">下单系统发消息到队列，Flow 消费后做风控检查、库存扣减、发短信，无需阻塞下单主流程</div>
          </div>
          <div class="ov-scene">
            <div class="ov-scene-title">📊 场景 2：数据 ETL 管道</div>
            <div class="ov-scene-desc">数据写入后发通知，Flow 消费消息做清洗/转换/入库，天然支持削峰填谷</div>
          </div>
          <div class="ov-scene">
            <div class="ov-scene-title">🤖 场景 3：AI 批量推理</div>
            <div class="ov-scene-desc">批量向量化/文本分类任务投入队列，多个 Pod 并行消费，KEDA 根据队列深度自动扩缩</div>
          </div>
        </div>
        <div class="ov-flow">
          <span class="ov-node">上游系统发消息</span>
          <span class="ov-arrow">→</span>
          <span class="ov-node ov-node-mq">RabbitMQ 队列</span>
          <span class="ov-arrow">→</span>
          <span class="ov-node ov-node-flow">Flow 执行</span>
          <span class="ov-arrow">→</span>
          <span class="ov-node ov-node-reply">（可选）回复结果</span>
        </div>
      </div>
    </transition>

    <!-- ── 触发方式 ─────────────────────────────────────────── -->
    <el-form-item label="触发方式">
      <el-radio-group v-model="form.trigger_type">
        <el-radio-button value="http">仅 HTTP</el-radio-button>
        <el-radio-button value="mq">仅 MQ</el-radio-button>
        <el-radio-button value="both">HTTP + MQ</el-radio-button>
      </el-radio-group>
      <div class="trigger-tips">
        <span v-if="form.trigger_type === 'http'" class="tip-badge tip-blue">同步调用，实时返回结果，适合需要立即拿到响应的场景</span>
        <span v-else-if="form.trigger_type === 'mq'" class="tip-badge tip-purple">异步消费，上游发完消息即可返回，适合耗时任务 / 削峰 / AI 推理</span>
        <span v-else class="tip-badge tip-teal">两种方式都支持，HTTP 用于在线查询，MQ 用于批量异步处理</span>
      </div>
    </el-form-item>

    <!-- ── HTTP 输入映射 ───────────────────────────────────── -->
    <transition name="mq-fade">
      <div v-if="httpEnabled">
        <el-divider content-position="left"><span class="divider-label">HTTP 输入映射</span></el-divider>
        <el-form-item label="HTTP input_mapping" :class="{ 'has-err': !httpInputMappingValid }">
          <div class="field-wrap">
            <el-input
              v-model="form.http_input_mapping"
              type="textarea"
              :rows="4"
              placeholder='{"flow字段名": "$.请求体路径"}'
              style="font-family:monospace;font-size:12px"
            />
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span v-if="httpInputMappingValid">
                <strong>作用：</strong>调用方直接发原始请求体，服务端按映射提取字段注入 Flow。
                <strong>留空</strong>则要求调用方把参数包在 <code>inputs</code> 字段里。
              </span>
              <span v-else class="err-text">⚠ 必须是合法 JSON 对象</span>
            </div>
            <div class="example-block">
              <div class="example-title">示例：订单请求不包 inputs 直接发</div>
              <pre class="example-code">// 调用方发送（无需包 inputs）
{ "orderId": "O123", "userId": "U456", "amount": 99.9 }

// input_mapping 配置
{
  "order_id": "$.orderId",
  "user_id":  "$.userId",
  "amount":   "$.amount"
}
// Flow 收到 → inputs = { order_id: "O123", user_id: "U456", amount: 99.9 }</pre>
            </div>
          </div>
        </el-form-item>
      </div>
    </transition>

    <!-- ── MQ 配置区域 ─────────────────────────────────────── -->
    <transition name="mq-fade">
      <div v-if="mqEnabled">
        <el-divider content-position="left"><span class="divider-label">MQ 队列配置</span></el-divider>

        <el-form-item label="Queue（主队列）">
          <div class="field-wrap">
            <el-input v-model="form.queue" :placeholder="`flow.${apiId}.queue`" />
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span>消费者监听的 RabbitMQ 队列名。<strong>通常使用默认值</strong>即可，上游往这个队列发消息 Flow 就会执行。</span>
            </div>
            <div class="example-block">
              <div class="example-title">上游 Java 发消息示例</div>
              <pre class="example-code">rabbitTemplate.convertAndSend(
    "",  // default exchange
    "{{ form.queue || `flow.${apiId}.queue` }}",  // 队列名
    Map.of("texts", List.of("待向量化文本"), "collection_name", "demo_kb")
);</pre>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="Exchange">
          <div class="field-wrap">
            <el-input v-model="form.exchange" placeholder="留空 = 使用 default exchange" />
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span><strong>留空即可（推荐）</strong>—— 使用 RabbitMQ default exchange，消息按 routing key 直接路由到同名队列，最简单。
              如果你的公司有统一的 exchange（如 topic exchange），填对应名称。</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="Routing Key">
          <div class="field-wrap">
            <el-input v-model="form.routing_key" placeholder="留空 = 与队列名相同" />
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span>使用 default exchange 时，<strong>routing key 必须等于队列名</strong>（RabbitMQ 规定）。留空则自动使用队列名，不需要手动填。</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="Prefetch（并发）">
          <div class="field-wrap">
            <div style="display:flex;align-items:center;gap:8px">
              <el-input-number v-model="form.prefetch_count" :min="1" :max="100" />
              <el-tag v-if="form.prefetch_count === 1" type="success" size="small">推荐</el-tag>
            </div>
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span><strong>每个消费者 Pod 同时处理几条消息。</strong>
              通常保持 <strong>1</strong>（一次处理一条，处理完再取下一条），配合 KEDA 自动扩 Pod 来提升吞吐，
              比单 Pod 多并发更容易控制错误和重试。
              只有 Flow 执行非常快（&lt;100ms）且无副作用才考虑调大。</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item v-if="hasMqEntrypointChoice || availableEntrypoints?.length" label="入口函数">
          <div class="field-wrap">
            <el-select v-model="form.entrypoint" style="width:100%" clearable placeholder="继承 API 级设置（或默认 run）">
              <el-option v-for="ep in (availableEntrypoints ?? [])" :key="ep" :label="ep" :value="ep" />
            </el-select>
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span v-if="apiEntrypoint">API 级已绑定 <code>{{ apiEntrypoint }}</code>；此处只覆盖 MQ 触发路径，留空沿用 API 级。</span>
              <span v-else>Flow 块里可以定义多个函数（<code>run_text</code>/<code>run_image</code>），在此选择 MQ 触发时调哪个。留空使用 <code>run</code>。</span>
            </div>
          </div>
        </el-form-item>

        <!-- ── 条件过滤 ──────────────────────────────────── -->
        <el-divider content-position="left">
          <span class="divider-label">条件过滤</span>
          <span class="divider-sub">— 不满足条件的消息直接 ack 跳过，不执行 Flow</span>
        </el-divider>

        <el-form-item label="条件语言">
          <el-radio-group v-model="form.condition_language">
            <el-radio-button value="jmespath">JMESPath（推荐）</el-radio-button>
            <el-radio-button value="jsonpath">JSONPath</el-radio-button>
          </el-radio-group>
          <div class="field-help" style="margin-top:4px">
            <el-icon class="help-icon"><InfoFilled /></el-icon>
            <span>两者都用于从 JSON 中提取/判断字段。JMESPath 语法更简洁，推荐使用。</span>
          </div>
        </el-form-item>

        <el-form-item label="条件表达式">
          <div class="field-wrap">
            <el-input v-model="form.condition_expression" placeholder="留空 = 所有消息都执行" />
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span><strong>应用场景：</strong>同一个队列里混有多种消息，只想处理特定类型。
              表达式返回 <strong>true</strong> 才执行，false 直接 ack 跳过。</span>
            </div>
            <div class="example-block">
              <div class="example-title">常用示例（JMESPath）</div>
              <pre class="example-code">// 只处理 type = "order_created" 的消息
header.type == 'order_created'

// 只处理金额 > 100 的消息
body.amount > `100`

// 只处理指定来源
header.source == 'app' || header.source == 'web'</pre>
            </div>
          </div>
        </el-form-item>

        <!-- ── MQ 输入映射 ──────────────────────────────── -->
        <el-divider content-position="left">
          <span class="divider-label">MQ 输入映射</span>
          <span class="divider-sub">— 把消息体字段映射到 Flow 的输入参数</span>
        </el-divider>

        <el-form-item label="MQ input_mapping" :class="{ 'has-err': !inputMappingValid }">
          <div class="field-wrap">
            <el-input
              v-model="form.input_mapping"
              type="textarea"
              :rows="5"
              placeholder='{"flow参数名": "$.消息体路径"}'
              style="font-family:monospace;font-size:12px"
            />
            <div class="field-help">
              <el-icon class="help-icon" :class="{'err-icon': !inputMappingValid}"><InfoFilled /></el-icon>
              <span v-if="inputMappingValid">
                <strong>作用：</strong>把 MQ 消息体的字段提取出来，重命名后注入 Flow。
                <strong>留空</strong>则把整条消息体原样传给 Flow（消息体字段名 = Flow 参数名）。
              </span>
              <span v-else class="err-text">⚠ 必须是合法 JSON 对象，格式 {"Flow参数名": "$.消息体路径"}</span>
            </div>
            <div class="example-block">
              <div class="example-title">示例：消息体字段名和 Flow 参数名不一致时</div>
              <pre class="example-code">// 消息体（上游 Java 发出）
{ "orderNo": "O123", "createdBy": "admin", "goods": [...] }

// input_mapping 配置
{
  "order_id":  "$.orderNo",
  "login_id":  "$.createdBy",
  "items":     "$.goods"
}
// Flow 收到 → inputs = { order_id: "O123", login_id: "admin", items: [...] }</pre>
            </div>
          </div>
        </el-form-item>

        <!-- ── 回复配置 ──────────────────────────────────── -->
        <el-divider content-position="left">
          <span class="divider-label">回复配置（Request-Reply 模式）</span>
          <span class="divider-sub">— Flow 执行完后把结果发回给调用方</span>
        </el-divider>

        <el-form-item label="启用回复">
          <div class="field-wrap">
            <el-switch v-model="form.reply_enabled" active-text="开启" inactive-text="关闭" />
            <div class="field-help" style="margin-top:4px">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span><strong>应用场景：</strong>上游系统需要知道 Flow 的执行结果（如 AI 推理输出、处理状态）。
              Flow 执行完后，结果会发到指定队列，上游监听该队列即可收到回复。</span>
            </div>
          </div>
        </el-form-item>

        <template v-if="form.reply_enabled">
          <el-form-item label="Reply Exchange">
            <div class="field-wrap">
              <el-input v-model="form.reply_exchange" placeholder="留空 = default exchange" />
              <div class="field-help">
                <el-icon class="help-icon"><InfoFilled /></el-icon>
                <span>回复消息发往哪个 Exchange。留空使用 default exchange（按 routing key 直达队列）。</span>
              </div>
            </div>
          </el-form-item>

          <el-form-item label="Reply Routing Key">
            <div class="field-wrap">
              <el-input v-model="form.reply_routing_key_template" placeholder="如 reply.order.result 或 reply.{api_id}" />
              <div class="field-help">
                <el-icon class="help-icon"><InfoFilled /></el-icon>
                <span>上游监听这个队列名就能收到 Flow 的执行结果。支持 <code>{api_id}</code> 占位符自动替换。</span>
              </div>
              <div class="example-block">
                <div class="example-title">上游 Java 监听回复示例</div>
                <pre class="example-code">@RabbitListener(queues = "{{ form.reply_routing_key_template || 'reply.flow.result' }}")
public void onReply(Map&lt;String, Object&gt; result) {
    // result 包含 Flow 的完整输出
    log.info("Flow 结果: {}", result);
}</pre>
              </div>
            </div>
          </el-form-item>

          <el-form-item label="透传字段（carry）">
            <div class="field-wrap">
              <div class="field-help" style="margin-bottom:8px">
                <el-icon class="help-icon"><InfoFilled /></el-icon>
                <span><strong>作用：</strong>把原始请求消息里的字段原样复制到回复消息里，方便上游做关联（如 snowflakeId、traceId、订单号）。
                这样上游收到回复时就知道这条回复对应的是哪条原始请求。</span>
              </div>
              <div class="example-block" style="margin-bottom:8px">
                <div class="example-title">示例：透传请求消息里的业务 ID</div>
                <pre class="example-code">// 原始请求消息
{ "header": { "snowflakeId": "1234567890" }, "body": {...} }

// 配置透传字段：$.header.snowflakeId → snowflakeId
// 回复消息会包含：{ "outputs": {...}, "snowflakeId": "1234567890" }</pre>
              </div>
              <div class="carry-table">
                <div class="carry-header">
                  <span style="flex:1">消息体来源路径（JSONPath）</span>
                  <span style="width:20px"></span>
                  <span style="flex:1">回复消息中的字段名</span>
                  <span style="width:60px">必填</span>
                  <span style="width:32px"></span>
                </div>
                <div v-for="(f, idx) in form.carry_fields" :key="idx" class="carry-row">
                  <el-input v-model="f.source_path" placeholder="$.header.snowflakeId" style="flex:1" />
                  <el-icon><Right /></el-icon>
                  <el-input v-model="f.target_field" placeholder="snowflakeId" style="flex:1" />
                  <el-checkbox v-model="f.required" label="必填" style="width:60px" />
                  <el-button type="danger" text size="small" @click="removeCarryField(idx)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
                <el-button size="small" @click="addCarryField" style="margin-top:4px">
                  <el-icon><Plus /></el-icon> 添加透传字段
                </el-button>
              </div>
            </div>
          </el-form-item>
        </template>

        <!-- ── 重试策略 ──────────────────────────────────── -->
        <el-divider content-position="left">
          <span class="divider-label">失败重试策略</span>
          <span class="divider-sub">— Flow 执行失败时自动重试，超限后转死信队列</span>
        </el-divider>

        <el-form-item label="最大重试次数">
          <div class="field-wrap">
            <div style="display:flex;align-items:center;gap:8px">
              <el-input-number v-model="form.max_retry" :min="0" :max="10" />
              <el-tag v-if="form.max_retry === 0" type="info" size="small">不重试，失败直接转死信</el-tag>
              <el-tag v-else-if="form.max_retry <= 3" type="success" size="small">推荐范围</el-tag>
              <el-tag v-else type="warning" size="small">重试次数较多</el-tag>
            </div>
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span>Flow 执行抛异常时自动重试。超过此次数后，消息进入<strong>死信队列</strong>（DLQ），
              可在接口管理的 MQ 监控里查看并手动重投。</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="重试延迟（ms）">
          <div class="field-wrap">
            <div style="display:flex;align-items:center;gap:8px">
              <el-input-number v-model="form.retry_delay_ms" :min="100" :max="60000" :step="500" />
              <span class="dim">= {{ (form.retry_delay_ms / 1000).toFixed(1) }} 秒后重试</span>
            </div>
            <div class="field-help">
              <el-icon class="help-icon"><InfoFilled /></el-icon>
              <span>失败后等多久再重试（通过 DLQ TTL 实现延迟）。建议 <strong>5000ms（5秒）</strong>起，
              避免下游服务临时不可用时频繁重试打满。</span>
            </div>
          </div>
        </el-form-item>

        <!-- 重试流程图 -->
        <div class="retry-flow">
          <span class="rf-node">Flow 执行失败</span>
          <span class="rf-arrow">→</span>
          <span class="rf-node rf-dlq">DLQ 等待 {{ (form.retry_delay_ms/1000).toFixed(0) }}s</span>
          <span class="rf-arrow">→</span>
          <span class="rf-node">重回主队列重试</span>
          <span class="rf-arrow rf-loop">× {{ form.max_retry }} 次</span>
          <span class="rf-arrow">→</span>
          <span class="rf-node rf-dead">死信归档</span>
        </div>

      </div>
    </transition>

    <!-- 错误提示 -->
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
.mq-trigger-form .el-form-item { margin-bottom: 18px; }
.dim { color: var(--pf-text-dim); font-size: 12px; }

/* ── 帮助横幅 ─────────────────────────── */
.help-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--pf-accent-soft, rgba(37,99,235,.06));
  border: 1px solid rgba(37,99,235,.2);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 16px;
  cursor: pointer;
  font-size: 13px;
  color: var(--pf-accent, #2563eb);
  font-weight: 600;
  transition: background .15s;
}
.help-banner:hover { background: rgba(37,99,235,.1); }
.help-toggle { margin-left: auto; font-size: 11px; font-weight: 400; }

/* ── 概览面板 ─────────────────────────── */
.overview-panel {
  background: var(--pf-panel, #f8fafc);
  border: 1px solid var(--pf-border, #e2e8f0);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
  animation: slide-in .2s ease;
}
@keyframes slide-in { from { opacity:0; transform:translateY(-4px); } to { opacity:1; transform:translateY(0); } }
.ov-title { font-weight: 700; font-size: 13px; margin-bottom: 8px; color: var(--pf-text); }
.ov-text { font-size: 12px; color: var(--pf-text-dim); line-height: 1.7; margin-bottom: 12px; }
.ov-scenarios { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; }
.ov-scene {
  background: var(--pf-panel-2, #f1f5f9);
  border-radius: 8px;
  padding: 10px 12px;
  border: 1px solid var(--pf-border);
}
.ov-scene-title { font-size: 12px; font-weight: 700; margin-bottom: 4px; color: var(--pf-text); }
.ov-scene-desc { font-size: 11px; color: var(--pf-text-dim); line-height: 1.5; }
.ov-flow {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px;
  background: var(--pf-code-bg, #1e293b);
  border-radius: 8px;
}
.ov-node {
  background: rgba(255,255,255,.08);
  color: #e2e8f0;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 20px;
  white-space: nowrap;
}
.ov-node-mq { background: rgba(124,58,237,.3); color: #c4b5fd; }
.ov-node-flow { background: rgba(37,99,235,.3); color: #93c5fd; }
.ov-node-reply { background: rgba(5,150,105,.3); color: #6ee7b7; }
.ov-arrow { color: #64748b; font-size: 14px; }

/* ── 触发方式提示 ─────────────────────── */
.trigger-tips { margin-top: 6px; }
.tip-badge { font-size: 12px; padding: 3px 10px; border-radius: 20px; }
.tip-blue   { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
.tip-purple { background: #f5f3ff; color: #7c3aed; border: 1px solid #ddd6fe; }
.tip-teal   { background: #f0fdfa; color: #0d9488; border: 1px solid #99f6e4; }

/* ── 分隔线 ──────────────────────────── */
.divider-label { font-weight: 700; font-size: 12px; color: var(--pf-accent); }
.divider-sub { font-size: 11px; color: var(--pf-text-dim); margin-left: 6px; }

/* ── 字段帮助 ─────────────────────────── */
.field-wrap { width: 100%; display: flex; flex-direction: column; gap: 6px; }
.field-help {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  font-size: 12px;
  color: var(--pf-text-dim);
  line-height: 1.6;
}
.help-icon { color: #60a5fa; flex-shrink: 0; margin-top: 2px; }
.err-icon { color: #ef4444; }

/* ── 示例代码块 ───────────────────────── */
.example-block {
  background: var(--pf-code-bg, #1e293b);
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,.06);
}
.example-title {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  padding: 6px 12px 4px;
  border-bottom: 1px solid rgba(255,255,255,.06);
  background: rgba(0,0,0,.15);
}
.example-code {
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  font-size: 11px;
  color: #86efac;
  padding: 10px 12px;
  margin: 0;
  white-space: pre;
  overflow-x: auto;
  line-height: 1.6;
}

/* ── 透传字段 ─────────────────────────── */
.carry-table { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.carry-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--pf-text-dim);
  padding: 0 4px;
}
.carry-row { display: flex; align-items: center; gap: 8px; }

/* ── 重试流程图 ───────────────────────── */
.retry-flow {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 14px;
  background: var(--pf-panel-2, #f1f5f9);
  border-radius: 8px;
  margin: 0 0 16px;
  border: 1px solid var(--pf-border);
  font-size: 12px;
}
.rf-node { background: var(--pf-panel); border: 1px solid var(--pf-border); border-radius: 6px; padding: 4px 10px; color: var(--pf-text); }
.rf-dlq  { border-color: #fbbf24; color: #d97706; background: #fef9c3; }
.rf-dead { border-color: #f87171; color: #dc2626; background: #fee2e2; }
.rf-arrow { color: var(--pf-text-dim); }
.rf-loop { font-size: 11px; color: #7c3aed; font-style: italic; }

/* ── 错误 ─────────────────────────────── */
.err-text { color: var(--el-color-error, #ef4444); }
.has-err :deep(.el-textarea__inner) { border-color: var(--el-color-error, #ef4444); }
.err-list { margin: 4px 0 0; padding-left: 18px; font-size: 12px; }
.err-list li { line-height: 1.6; }
code { background: rgba(0,0,0,.06); padding: 1px 5px; border-radius: 3px; font-family: monospace; font-size: 11px; }

/* ── 过渡 ─────────────────────────────── */
.mq-fade-enter-active, .mq-fade-leave-active { transition: opacity 0.25s ease; }
.mq-fade-enter-from, .mq-fade-leave-to { opacity: 0; }
</style>
