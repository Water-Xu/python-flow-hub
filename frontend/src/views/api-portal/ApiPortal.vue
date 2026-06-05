<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiPortalApi, flowApi, type PublishedApi, type FlowEntrypointsInfo, type ApiEncryptionKey } from '@/api'
import MqMockTestDialog from '@/components/MqMockTestDialog.vue'
import MqTriggerForm from '@/components/MqTriggerForm.vue'

const apis = ref<PublishedApi[]>([])
const flows = ref<any[]>([])
const loading = ref(false)
const publishDialogVisible = ref(false)
const docsDialogVisible = ref(false)
const selectedApi = ref<PublishedApi | null>(null)
const docsData = ref<any>(null)
const docsLoading = ref(false)

// ── 接口测试 ──────────────────────────────────────────────────────────────
const testDialogVisible = ref(false)
const testApi = ref<PublishedApi | null>(null)
const testBody = ref('{\n  "inputs": {}\n}')
const testSending = ref(false)
const testResult = ref<{
  ok: boolean
  httpStatus: number
  latencyMs: number
  data: any
} | null>(null)

// ── 流式测试（SSE，真流式：终止节点 yield 实时回显）─────────────────────────
const testStreamMode = ref(false)
const streaming = ref(false)
const streamText = ref('')
const streamError = ref('')
let streamCtrl: AbortController | null = null

// ── MQ Mock 测试（接口/Flow 级）────────────────────────────────────────────
const mqTestVisible = ref(false)
const mqTestApi = ref<{ id: string; name: string; preset: Record<string, any> | null }>({
  id: '',
  name: '',
  preset: null,
})

function openMqTest(api: PublishedApi, preset?: Record<string, any> | null) {
  mqTestApi.value = { id: api.id, name: api.name, preset: preset || null }
  mqTestVisible.value = true
}

// ── 触发配置（http/mq/both，决策 3.1 Flow 级）──────────────────────────────
const triggerDialogVisible = ref(false)
const triggerApi = ref<PublishedApi | null>(null)
const triggerFormRef = ref<InstanceType<typeof MqTriggerForm> | null>(null)
const triggerSaving = ref(false)
const triggerFlowEntrypoints = ref<FlowEntrypointsInfo | null>(null)

async function openTriggerConfig(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已锁定，无法修改触发配置')
  triggerApi.value = api
  triggerDialogVisible.value = true
  triggerFlowEntrypoints.value = null
  const fid = api.active_flow_id || api.flow_id
  if (fid) {
    try {
      triggerFlowEntrypoints.value = await apiPortalApi.getFlowEntrypoints(fid)
    } catch {
      // 获取失败不阻断配置
    }
  }
}

async function saveTrigger() {
  if (!triggerApi.value || !triggerFormRef.value) return
  if (triggerFormRef.value.errors.length) {
    return ElMessage.error(triggerFormRef.value.errors[0])
  }
  triggerSaving.value = true
  try {
    const payload = triggerFormRef.value.collect()
    await apiPortalApi.updateMq(triggerApi.value.id, payload)
    ElMessage.success('触发配置已保存')
    triggerDialogVisible.value = false
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    triggerSaving.value = false
  }
}

const triggerTypeLabel: Record<string, string> = {
  http: 'HTTP', mq: 'MQ', both: 'HTTP+MQ',
}

// ── 加密保护（AES-256-GCM，接口级开关 + 密钥管理）──────────────────────────────
const encryptionDialogVisible = ref(false)
const encryptionApi = ref<PublishedApi | null>(null)
const encryptionInfo = ref<ApiEncryptionKey | null>(null)
const encryptionLoading = ref(false)
const encryptionSaving = ref(false)
// 本地开关状态（与 encryptionInfo 解耦，便于编辑后一次性保存）
const encEnabled = ref(false)
const encRequire = ref(false)

async function openEncryption(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已锁定，无法修改加密配置')
  encryptionApi.value = api
  encryptionInfo.value = null
  encEnabled.value = api.encryption_enabled
  encRequire.value = api.require_encrypted_request
  encryptionDialogVisible.value = true
  encryptionLoading.value = true
  try {
    encryptionInfo.value = await apiPortalApi.getEncryptionKey(api.id)
    encEnabled.value = encryptionInfo.value.encryption_enabled
    encRequire.value = encryptionInfo.value.require_encrypted_request
  } catch {
    // 读取失败不阻断，仍可开启
  } finally {
    encryptionLoading.value = false
  }
}

async function saveEncryption() {
  if (!encryptionApi.value) return
  encryptionSaving.value = true
  try {
    const res = await apiPortalApi.updateEncryption(encryptionApi.value.id, {
      enabled: encEnabled.value,
      require_encrypted_request: encRequire.value,
    })
    // 合并返回（首次开启会带回完整密钥）
    encryptionInfo.value = {
      ...res,
      encryption_key: res.encryption_key ?? encryptionInfo.value?.encryption_key ?? null,
    }
    ElMessage.success(encEnabled.value ? '加密保护已开启' : '加密保护已关闭')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    encryptionSaving.value = false
  }
}

async function rotateKey() {
  if (!encryptionApi.value) return
  await ElMessageBox.confirm(
    '轮转后旧密钥立即失效，所有调用方需同步更新为新密钥，否则解密失败。确认轮转？',
    '轮转密钥',
    { type: 'warning' },
  )
  encryptionSaving.value = true
  try {
    encryptionInfo.value = await apiPortalApi.rotateEncryptionKey(encryptionApi.value.id)
    encEnabled.value = encryptionInfo.value.encryption_enabled
    ElMessage.success('密钥已轮转，请复制并更新到调用方')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '轮转失败')
  } finally {
    encryptionSaving.value = false
  }
}

async function copyKey() {
  const key = encryptionInfo.value?.encryption_key
  if (!key) return ElMessage.warning('当前无可复制的完整密钥，请轮转或重新开启以获取')
  try {
    await navigator.clipboard.writeText(key)
    ElMessage.success('密钥已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

/** Java 调用方配置示例（按当前接口 path 与密钥渲染） */
const javaConfigSnippet = computed(() => {
  const path = encryptionApi.value?.path || 'your-api-path'
  const key = encryptionInfo.value?.encryption_key || '（在此填入上方完整密钥）'
  return [
    'flowhub:',
    '  encryption:',
    '    enabled: true',
    '    path-keys:',
    `      ${path}: "${key}"`,
  ].join('\n')
})

const form = ref({
  name: '',
  description: '',
  path: '',
  tags: '',
  flow_id: '',
  // 节点级入口函数映射 {node_id: entrypoint}，每个调用块分别指定
  entrypoint_map: {} as Record<string, string>,
})

// ── 发布对话框：入口函数选择 ────────────────────────────────────────────────
const flowEntrypointsInfo = ref<FlowEntrypointsInfo | null>(null)
const entrypointsLoading = ref(false)

watch(
  () => form.value.flow_id,
  async (fid) => {
    flowEntrypointsInfo.value = null
    form.value.entrypoint_map = {}
    if (!fid) return
    entrypointsLoading.value = true
    try {
      const info = await apiPortalApi.getFlowEntrypoints(fid)
      flowEntrypointsInfo.value = info
      // 默认沿用各节点画布中已配置的入口函数
      const map: Record<string, string> = {}
      for (const n of info.nodes) {
        map[n.node_id] = n.configured_entrypoint || 'run'
      }
      form.value.entrypoint_map = map
    } catch {
      // 获取失败不阻断发布，保持默认
    } finally {
      entrypointsLoading.value = false
    }
  },
)

/** 当前选中的 flow 是否有多个可用入口函数 */
const showEntrypointSelector = computed(
  () => flowEntrypointsInfo.value?.has_multiple === true,
)

/** 流程已指定的单一 API 入口节点（在流程编辑器中标记），用于发布对话框提示 */
const entryNodeName = computed(() => {
  const info = flowEntrypointsInfo.value
  if (!info?.entry_node_id) return null
  return info.nodes.find((n) => n.node_id === info.entry_node_id)?.block_name ?? null
})

async function load() {
  loading.value = true
  try {
    ;[apis.value, flows.value] = await Promise.all([apiPortalApi.list(), flowApi.list()])
  } finally {
    loading.value = false
  }
}

async function publish() {
  if (!form.value.name || !form.value.path || !form.value.flow_id) {
    return ElMessage.warning('请填写接口名称、路径和关联流程')
  }
  try {
    await apiPortalApi.publish({
      name: form.value.name,
      description: form.value.description,
      path: form.value.path,
      tags: form.value.tags,
      flow_id: form.value.flow_id,
      entrypoint: null,
      entrypoint_map: { ...form.value.entrypoint_map },
    })
    publishDialogVisible.value = false
    ElMessage.success('接口发布成功')
    resetForm()
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '发布失败')
  }
}

async function toggleStatus(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已锁定，无法操作')
  try {
    if (api.status === 'active') {
      await apiPortalApi.pause(api.id)
      ElMessage.success('已暂停')
    } else {
      await apiPortalApi.activate(api.id)
      ElMessage.success('已激活')
    }
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function unpublish(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已被管理员锁定，无法下线')
  await ElMessageBox.confirm(`确认下线接口「${api.name}」？`, '下线确认', { type: 'warning' })
  try {
    await apiPortalApi.unpublish(api.id)
    ElMessage.success('已下线')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function copyFlow(api: PublishedApi) {
  try {
    const res = await apiPortalApi.copyFlow(api.flow_id)
    ElMessage.success(`已创建流程副本：${res.name}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '复制失败')
  }
}

async function viewDocs(api: PublishedApi) {
  selectedApi.value = api
  docsDialogVisible.value = true
  docsLoading.value = true
  try {
    docsData.value = await apiPortalApi.getDocs(api.id)
  } finally {
    docsLoading.value = false
  }
}

function openTest(api: PublishedApi, presetBody?: any) {
  testApi.value = api
  testResult.value = null
  streamText.value = ''
  streamError.value = ''
  stopStream()
  if (presetBody) {
    testBody.value = JSON.stringify(presetBody, null, 2)
  } else {
    testBody.value = '{\n  "inputs": {}\n}'
  }
  testDialogVisible.value = true
}

function formatBody() {
  try {
    testBody.value = JSON.stringify(JSON.parse(testBody.value), null, 2)
  } catch {
    ElMessage.warning('JSON 格式有误，无法格式化')
  }
}

async function sendTest() {
  if (!testApi.value) return
  if (testApi.value.status !== 'active') {
    return ElMessage.warning(`接口当前为「${testApi.value.status}」状态，请先激活后再测试`)
  }
  let payload: any
  try {
    payload = testBody.value.trim() ? JSON.parse(testBody.value) : {}
  } catch {
    return ElMessage.error('请求体不是合法 JSON，请检查后重试')
  }
  testSending.value = true
  testResult.value = null
  const start = performance.now()
  try {
    const res = await apiPortalApi.invoke(testApi.value.path, payload)
    const latency = performance.now() - start
    testResult.value = {
      ok: res.status >= 200 && res.status < 300,
      httpStatus: res.status,
      latencyMs: latency,
      data: res.data,
    }
    // 测试也会计入调用统计，刷新卡片数据
    load()
  } catch (e: any) {
    testResult.value = {
      ok: false,
      httpStatus: e?.response?.status ?? 0,
      latencyMs: performance.now() - start,
      data: e?.response?.data ?? { error: e?.message || '请求失败（网络错误或服务不可达）' },
    }
  } finally {
    testSending.value = false
  }
}

function parseTestPayload(): any | null {
  try {
    return testBody.value.trim() ? JSON.parse(testBody.value) : {}
  } catch {
    ElMessage.error('请求体不是合法 JSON，请检查后重试')
    return null
  }
}

function stopStream() {
  if (streamCtrl) {
    streamCtrl.abort()
    streamCtrl = null
  }
  streaming.value = false
}

function sendStreamTest() {
  if (!testApi.value) return
  if (testApi.value.status !== 'active') {
    return ElMessage.warning(`接口当前为「${testApi.value.status}」状态，请先激活后再测试`)
  }
  const payload = parseTestPayload()
  if (payload === null) return

  testResult.value = null
  streamText.value = ''
  streamError.value = ''
  streaming.value = true
  const start = performance.now()

  streamCtrl = apiPortalApi.invokeStream(testApi.value.path, payload, {
    onChunk: (chunk) => {
      streamText.value += typeof chunk === 'string' ? chunk : JSON.stringify(chunk)
    },
    onResult: (result) => {
      testResult.value = {
        ok: !result?.error,
        httpStatus: 200,
        latencyMs: result?.latency_ms ?? performance.now() - start,
        data: result,
      }
    },
    onError: (err) => {
      streamError.value = err
      testResult.value = {
        ok: false,
        httpStatus: 0,
        latencyMs: performance.now() - start,
        data: { error: err },
      }
    },
    onDone: () => {
      streaming.value = false
      streamCtrl = null
      load()
    },
  })
}

async function copyUrl(api: PublishedApi) {
  const url = `${window.location.origin}${api.invoke_path}`
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success(`已复制调用地址：${url}`)
  } catch {
    ElMessage.warning(`复制失败，请手动复制：${url}`)
  }
}

function resetForm() {
  form.value = { name: '', description: '', path: '', tags: '', flow_id: '', entrypoint_map: {} }
  flowEntrypointsInfo.value = null
}

const statusType: Record<string, string> = {
  active: 'success',
  paused: 'warning',
  deprecated: 'danger',
}

const successRate = (api: PublishedApi) =>
  api.total_calls > 0 ? ((api.success_calls / api.total_calls) * 100).toFixed(1) : '—'

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>接口门户</h2>
        <p class="dim">将流程发布为可调用的 HTTP 接口，支持限流 / 降级 / 版本平滑切换</p>
      </div>
      <el-button type="primary" @click="publishDialogVisible = true">
        <el-icon style="margin-right:6px"><Plus /></el-icon>发布接口
      </el-button>
    </header>

    <transition-group name="list" tag="div" class="api-grid">
      <div v-for="api in apis" :key="api.id" class="pf-card api-card">
        <!-- 锁定角标 -->
        <div v-if="api.is_locked" class="lock-badge">
          <el-icon><Lock /></el-icon> 已锁定
        </div>

        <div class="api-card-header">
          <div>
            <span class="api-name">{{ api.name }}</span>
            <el-tag
              :type="statusType[api.status] || 'info'"
              size="small"
              effect="plain"
              style="margin-left:8px"
            >{{ api.status }}</el-tag>
          </div>
          <div class="header-tags">
            <el-tag
              size="small"
              :type="api.trigger_type === 'http' ? 'info' : 'primary'"
              effect="plain"
            >
              {{ triggerTypeLabel[api.trigger_type] || 'HTTP' }}
            </el-tag>
            <el-tag v-if="api.rate_limit_enabled" size="small" type="warning" effect="plain">
              限流 {{ api.rate_limit_per_minute }}/min
            </el-tag>
            <el-tag v-if="api.encryption_enabled" size="small" type="success" effect="plain">
              <el-icon style="margin-right:3px"><Lock /></el-icon>加密
            </el-tag>
          </div>
        </div>

        <p class="api-path">
          <el-icon><Link /></el-icon>
          <code>POST {{ api.invoke_path }}</code>
          <el-tooltip content="复制完整调用地址" placement="top">
            <el-icon class="copy-icon" @click="copyUrl(api)"><CopyDocument /></el-icon>
          </el-tooltip>
        </p>
        <p class="api-desc">{{ api.description || '—' }}</p>

        <!-- 流量统计 -->
        <div class="stats-row">
          <div class="stat-item">
            <span class="stat-label">总调用</span>
            <span class="stat-val">{{ api.total_calls.toLocaleString() }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">成功率</span>
            <span class="stat-val" :class="{ 'text-success': Number(successRate(api)) >= 99 }">
              {{ successRate(api) }}{{ api.total_calls > 0 ? '%' : '' }}
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-label">均延迟</span>
            <span class="stat-val">{{ api.avg_latency_ms.toFixed(0) }}ms</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">降级</span>
            <span class="stat-val">{{ api.degradation_enabled ? '开' : '关' }}</span>
          </div>
        </div>

        <div class="api-actions">
          <el-button size="small" @click="viewDocs(api)">
            <el-icon><Document /></el-icon> 文档
          </el-button>
          <el-button size="small" type="primary" plain @click="openTest(api)">
            <el-icon><Promotion /></el-icon> 测试
          </el-button>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="api.is_locked"
            @click="openTriggerConfig(api)"
          >
            <el-icon><Setting /></el-icon> 触发配置
          </el-button>
          <el-button
            size="small"
            :type="api.encryption_enabled ? 'success' : 'info'"
            plain
            :disabled="api.is_locked"
            @click="openEncryption(api)"
          >
            <el-icon><Lock /></el-icon> 加密{{ api.encryption_enabled ? '（已开启）' : '' }}
          </el-button>
          <el-button
            size="small"
            :type="api.status === 'active' ? 'warning' : 'success'"
            :disabled="api.is_locked"
            @click="toggleStatus(api)"
          >
            {{ api.status === 'active' ? '暂停' : '激活' }}
          </el-button>
          <el-button size="small" type="info" @click="copyFlow(api)">
            <el-icon><CopyDocument /></el-icon> 复制流程
          </el-button>
          <el-button
            size="small"
            type="danger"
            :disabled="api.is_locked"
            @click="unpublish(api)"
          >
            下线
          </el-button>
        </div>
      </div>
    </transition-group>

    <el-empty v-if="!loading && apis.length === 0" description="暂无已发布接口，点击「发布接口」开始" />

    <!-- 发布接口 Dialog -->
    <el-dialog v-model="publishDialogVisible" title="发布流程为接口" width="560px" :close-on-click-modal="false">
      <el-form label-width="90px" class="publish-form">
        <el-form-item label="接口名称" required>
          <el-input v-model="form.name" placeholder="如：图像识别服务" />
        </el-form-item>
        <el-form-item label="接口路径" required>
          <el-input v-model="form.path" placeholder="如：image-classify（仅字母数字_-）">
            <template #prepend>/api/public/</template>
          </el-input>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tags" placeholder="如：AI,图像（逗号分隔）" />
        </el-form-item>
        <el-form-item label="关联流程" required>
          <el-select v-model="form.flow_id" style="width:100%" placeholder="选择要发布的流程">
            <el-option v-for="f in flows" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </el-form-item>

        <!-- 入口函数选择：逐个调用块分别指定（解决多块含同名函数如 run 的歧义） -->
        <transition name="ep-fade">
          <el-form-item v-if="form.flow_id" label="入口函数">
            <div v-if="entrypointsLoading" class="ep-hint">正在读取流程函数列表…</div>

            <el-alert
              v-else-if="entryNodeName"
              class="ep-entry-banner"
              type="success"
              :closable="false"
              show-icon
            >
              <template #title>
                调用本接口将从入口节点 <strong>{{ entryNodeName }}</strong> 进入，仅执行其下游可达子图（已在流程编辑器中指定）。
              </template>
            </el-alert>
            <div v-else-if="flowEntrypointsInfo" class="ep-hint ep-no-entry">
              未指定单一入口节点：调用将从所有「无上游」的根节点同时进入。可在流程编辑器中双击某节点设为 API 入口。
            </div>

            <template v-if="showEntrypointSelector && flowEntrypointsInfo">
              <div class="ep-hint">
                该流程含 <strong>{{ flowEntrypointsInfo.nodes.length }}</strong> 个调用块，
                可为每个块单独指定要调用的入口函数（默认沿用节点配置）。
              </div>
              <div class="ep-nodes">
                <div
                  v-for="n in flowEntrypointsInfo.nodes"
                  :key="n.node_id"
                  class="ep-node-row"
                >
                  <span class="ep-block-name" :title="n.block_name">{{ n.block_name }}</span>
                  <el-select
                    v-model="form.entrypoint_map[n.node_id]"
                    size="small"
                    class="ep-node-select"
                    placeholder="run"
                  >
                    <el-option
                      v-for="ep in n.available_entrypoints"
                      :key="ep.name"
                      :label="ep.name"
                      :value="ep.name"
                    >
                      <span>{{ ep.name }}</span>
                      <span v-if="ep.description" class="ep-opt-desc">{{ ep.description }}</span>
                    </el-option>
                  </el-select>
                </div>
              </div>
            </template>

            <div v-else-if="flowEntrypointsInfo" class="ep-hint">
              流程仅有默认入口函数 <code>run</code>，无需指定。
            </div>
          </el-form-item>
        </transition>
      </el-form>
      <template #footer>
        <el-button @click="publishDialogVisible = false; resetForm()">取消</el-button>
        <el-button type="primary" @click="publish">发布</el-button>
      </template>
    </el-dialog>

    <!-- 接口文档 Dialog -->
    <el-dialog v-model="docsDialogVisible" title="接口文档" width="680px" top="5vh">
      <div v-loading="docsLoading">
        <template v-if="docsData">
          <div class="docs-section">
            <h3 class="docs-title">{{ docsData.name }}</h3>
            <p class="docs-desc">{{ docsData.description || '暂无描述' }}</p>
            <div class="docs-meta-row">
              <el-tag type="success">{{ docsData.method }}</el-tag>
              <code class="docs-path">{{ docsData.path }}</code>
              <el-tag :type="statusType[docsData.status] || 'info'">{{ docsData.status }}</el-tag>
              <el-tag v-if="docsData.mq_supported" type="primary" effect="plain">
                <el-icon style="margin-right:3px"><MessageBox /></el-icon>
                支持 MQ 触发
              </el-tag>
            </div>
          </div>

          <el-divider />

          <div class="docs-section">
            <h4>流程信息</h4>
            <p>流程名称：<strong>{{ docsData.flow_name }}</strong>（{{ docsData.node_count }} 块 / {{ docsData.edge_count }} 条边）</p>
          </div>

          <!-- 通过 MQ 触发（接口/Flow 级，决策 3.1 重写为 Flow 级模型 A）-->
          <transition name="mq-section">
            <div v-if="docsData.mq_invocation" class="docs-section">
              <div class="mq-invoke">
                <div class="mq-invoke-head">
                  <el-icon><MessageBox /></el-icon>
                  <span>通过 MQ 触发（RabbitMQ 异步驱动整条流程）</span>
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    class="mq-test-btn"
                    v-if="selectedApi"
                    @click="openMqTest(selectedApi, docsData.mq_invocation.message_example)"
                  >
                    <el-icon style="margin-right:4px"><VideoPlay /></el-icon>Mock 测试
                  </el-button>
                </div>
                <div class="mq-kv-grid">
                  <div class="mq-kv"><span class="mq-k">主队列</span><code>{{ docsData.mq_invocation.queue }}</code></div>
                  <div class="mq-kv"><span class="mq-k">交换机</span><code>{{ docsData.mq_invocation.exchange }}</code></div>
                  <div class="mq-kv"><span class="mq-k">路由键</span><code>{{ docsData.mq_invocation.routing_key }}</code></div>
                  <div class="mq-kv"><span class="mq-k">死信队列</span><code>{{ docsData.mq_invocation.dlq_queue }}</code></div>
                  <div class="mq-kv">
                    <span class="mq-k">重试</span>
                    <span>{{ docsData.mq_invocation.max_retry }} 次 / {{ docsData.mq_invocation.retry_delay_ms }}ms</span>
                  </div>
                  <div class="mq-kv">
                    <span class="mq-k">回复</span>
                    <el-tag size="small" :type="docsData.mq_invocation.reply_enabled ? 'success' : 'info'" effect="plain">
                      {{ docsData.mq_invocation.reply_enabled ? '开启' : '关闭' }}
                    </el-tag>
                  </div>
                </div>
                <div v-if="docsData.mq_invocation.condition_expression" class="mq-line">
                  <span class="mq-k">条件订阅</span>
                  <code>{{ docsData.mq_invocation.condition_language }}: {{ docsData.mq_invocation.condition_expression }}</code>
                </div>
                <div v-if="Object.keys(docsData.mq_invocation.input_mapping || {}).length" class="mq-line mq-mapping">
                  <span class="mq-k">字段映射（流程输入 ← 消息路径）</span>
                  <ul class="port-list">
                    <li v-for="(src, target) in docsData.mq_invocation.input_mapping" :key="target">
                      <code>{{ target }}</code><span class="dim">←</span><code>{{ src }}</code>
                    </li>
                  </ul>
                </div>
                <div class="mq-line">
                  <span class="mq-k">示例消息体</span>
                  <pre class="code-block" style="margin:6px 0 0">{{ JSON.stringify(docsData.mq_invocation.message_example, null, 2) }}</pre>
                </div>
              </div>
            </div>
          </transition>

          <div class="docs-section" v-if="docsData.blocks?.length">
            <h4>调用块列表</h4>
            <el-collapse accordion>
              <el-collapse-item
                v-for="block in docsData.blocks"
                :key="block.node_id || block.block_id"
                :title="block.block_name"
              >
                <template #title>
                  <span>{{ block.block_name }}</span>
                </template>
                <p class="dim" style="margin:0 0 8px">{{ block.description || '暂无描述' }}</p>
                <p style="margin:0 0 8px">
                  <strong>入口函数：</strong>
                  <code>{{ block.entrypoint || 'run' }}</code>
                </p>
                <div class="port-grid">
                  <div>
                    <strong>输入端口</strong>
                    <ul class="port-list">
                      <li v-for="p in block.input_ports" :key="p.name">
                        <code>{{ p.name }}</code>
                        <span class="dim">{{ p.type }}</span>
                        <el-tag v-if="p.required" size="small" type="danger">必填</el-tag>
                      </li>
                      <li v-if="!block.input_ports?.length" class="dim">无</li>
                    </ul>
                  </div>
                  <div>
                    <strong>输出端口</strong>
                    <ul class="port-list">
                      <li v-for="p in block.output_ports" :key="p.name">
                        <code>{{ p.name }}</code>
                        <span class="dim">{{ p.type }}</span>
                      </li>
                      <li v-if="!block.output_ports?.length" class="dim">无</li>
                    </ul>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>

          <el-divider />

          <div class="docs-section">
            <h4>示例请求</h4>
            <pre class="code-block">{{ JSON.stringify(docsData.request_example, null, 2) }}</pre>
            <h4>示例响应</h4>
            <pre class="code-block">{{ JSON.stringify(docsData.response_example, null, 2) }}</pre>
          </div>
        </template>
      </div>
      <template #footer v-if="docsData && selectedApi">
        <el-button @click="docsDialogVisible = false">关闭</el-button>
        <el-button
          type="primary"
          @click="docsDialogVisible = false; openTest(selectedApi, docsData.request_example)"
        >
          <el-icon style="margin-right:6px"><Promotion /></el-icon>在线测试
        </el-button>
      </template>
    </el-dialog>

    <!-- 接口测试 Dialog -->
    <el-dialog
      v-model="testDialogVisible"
      title="接口在线测试"
      width="720px"
      top="6vh"
      class="test-dialog"
    >
      <template v-if="testApi">
        <div class="test-target">
          <el-tag type="success" effect="dark">POST</el-tag>
          <code class="test-path">{{ testApi.invoke_path }}</code>
          <el-tag
            :type="statusType[testApi.status] || 'info'"
            size="small"
            effect="plain"
          >{{ testApi.status }}</el-tag>
        </div>

        <div class="test-section">
          <div class="test-section-head">
            <h4>请求体（Mock 数据 · JSON）</h4>
            <el-button text size="small" @click="formatBody">
              <el-icon style="margin-right:4px"><MagicStick /></el-icon>格式化
            </el-button>
          </div>
          <el-input
            v-model="testBody"
            type="textarea"
            :rows="8"
            spellcheck="false"
            class="test-editor"
            placeholder='{ "inputs": { "key": "value" } }'
          />
        </div>

        <div class="test-actions">
          <el-button
            v-if="!streaming"
            type="primary"
            :loading="testSending"
            @click="testStreamMode ? sendStreamTest() : sendTest()"
          >
            <el-icon v-if="!testSending" style="margin-right:6px">
              <VideoPlay v-if="testStreamMode" />
              <Promotion v-else />
            </el-icon>
            {{ testSending ? '请求中…' : testStreamMode ? '发送流式请求' : '发送测试请求' }}
          </el-button>
          <el-button v-else type="danger" plain @click="stopStream">
            <el-icon style="margin-right:6px"><CircleClose /></el-icon>中止流式
          </el-button>

          <div class="stream-switch">
            <span class="dim">流式输出</span>
            <el-switch v-model="testStreamMode" :disabled="streaming || testSending" />
            <el-tooltip
              content="SSE 真流式：终止节点 Python 代码 yield 的内容会实时回传"
              placement="top"
            >
              <el-icon class="stream-hint"><InfoFilled /></el-icon>
            </el-tooltip>
          </div>
          <span class="dim" style="margin-left:auto">将真实调用接口，结果计入统计</span>
        </div>

        <!-- 流式实时输出区 -->
        <transition name="resp-fade">
          <div v-if="testStreamMode && (streaming || streamText || streamError)" class="test-section stream-block">
            <div class="resp-head">
              <h4>实时输出</h4>
              <el-tag v-if="streaming" type="primary" size="small" effect="plain" class="streaming-tag">
                <span class="live-dot" /> 接收中
              </el-tag>
            </div>
            <pre class="code-block stream-output">{{ streamText || (streaming ? '' : '（无流式内容）') }}<span v-if="streaming" class="stream-cursor">▍</span></pre>
            <p v-if="streamError" class="stream-err">
              <el-icon><CircleClose /></el-icon> {{ streamError }}
            </p>
          </div>
        </transition>

        <transition name="resp-fade">
          <div v-if="testResult" class="test-section resp-block">
            <div class="resp-head">
              <h4>响应结果</h4>
              <div class="resp-meta">
                <el-tag
                  :type="testResult.ok ? 'success' : 'danger'"
                  effect="dark"
                  size="small"
                >
                  <el-icon style="margin-right:4px">
                    <CircleCheck v-if="testResult.ok" />
                    <CircleClose v-else />
                  </el-icon>
                  HTTP {{ testResult.httpStatus || '—' }}
                </el-tag>
                <el-tag type="info" size="small" effect="plain">
                  <el-icon style="margin-right:4px"><Timer /></el-icon>
                  {{ testResult.latencyMs.toFixed(0) }} ms
                </el-tag>
              </div>
            </div>
            <pre class="code-block resp-code">{{ JSON.stringify(testResult.data, null, 2) }}</pre>
          </div>
        </transition>
      </template>
      <template #footer>
        <el-button @click="stopStream(); testDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- MQ Mock 测试 Dialog（接口/Flow 级，复用组件） -->
    <MqMockTestDialog
      v-model="mqTestVisible"
      :api-id="mqTestApi.id"
      :api-name="mqTestApi.name"
      :preset-payload="mqTestApi.preset"
    />

    <!-- 加密保护 Dialog（AES-256-GCM，接口级） -->
    <el-dialog
      v-model="encryptionDialogVisible"
      :title="`加密保护 - ${encryptionApi?.name || ''}`"
      width="640px"
      destroy-on-close
    >
      <div v-loading="encryptionLoading" class="enc-body">
        <div class="enc-row">
          <div class="enc-label">
            <span class="enc-title">启用加密保护</span>
            <span class="enc-sub">AES-256-GCM 端到端加密：请求 inputs 加密传输、响应 outputs 加密返回</span>
          </div>
          <el-switch v-model="encEnabled" />
        </div>

        <transition name="enc-fade">
          <div v-if="encEnabled" class="enc-row">
            <div class="enc-label">
              <span class="enc-title">强制加密调用</span>
              <span class="enc-sub">开启后拒绝明文请求（返回加密要求错误）；关闭则兼容明文与密文，便于灰度</span>
            </div>
            <el-switch v-model="encRequire" />
          </div>
        </transition>

        <!-- 密钥展示 -->
        <transition name="enc-fade">
          <div v-if="encEnabled" class="enc-key-block">
            <div class="enc-key-head">
              <span class="enc-title">接口密钥（64 位 hex）</span>
              <div class="enc-key-ops">
                <el-button size="small" text type="primary" @click="copyKey">
                  <el-icon style="margin-right:4px"><CopyDocument /></el-icon>复制完整密钥
                </el-button>
                <el-button size="small" text type="warning" :loading="encryptionSaving" @click="rotateKey">
                  <el-icon style="margin-right:4px"><RefreshRight /></el-icon>轮转密钥
                </el-button>
              </div>
            </div>
            <pre class="enc-key-value">{{ encryptionInfo?.encryption_key || (encryptionInfo?.key_hint ? encryptionInfo.key_hint + '… （完整密钥仅在新生成/轮转时显示，可点轮转重新获取）' : '保存以生成密钥') }}</pre>
            <p class="enc-warn">
              <el-icon><WarningFilled /></el-icon>
              密钥等同访问凭据，请妥善保管；轮转后旧密钥立即失效，需同步更新所有调用方。
            </p>
          </div>
        </transition>

        <!-- 使用说明 -->
        <transition name="enc-fade">
          <div v-if="encEnabled" class="enc-usage">
            <h4>调用方接入说明</h4>
            <ol class="enc-steps">
              <li>复制上方完整密钥（若已隐藏，点击「轮转密钥」重新获取）。</li>
              <li>
                <strong>Java（lhy-styon common）</strong>：在 Nacos / application.yml 配置，业务调用
                <code>flowHubHttpClient.invoke(path, inputs)</code> 无需改动，加解密自动透明：
                <pre class="code-block enc-snippet">{{ javaConfigSnippet }}</pre>
              </li>
              <li>
                <strong>其它语言</strong>：请求体改为
                <code>{ "inputs": "&lt;base64密文&gt;", "encrypted": true }</code>，
                密文为 <code>base64(iv[12B] + ciphertext + tag[16B])</code>；
                响应 <code>encrypted=true</code> 时 <code>outputs</code> 同为密文，用同一密钥解密。
              </li>
            </ol>
          </div>
        </transition>
      </div>
      <template #footer>
        <el-button @click="encryptionDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="encryptionSaving" @click="saveEncryption">保存</el-button>
      </template>
    </el-dialog>

    <!-- 触发配置 Dialog（http/mq/both，Flow 级） -->
    <el-dialog
      v-model="triggerDialogVisible"
      :title="`触发配置 - ${triggerApi?.name || ''}`"
      width="640px"
      destroy-on-close
    >
      <MqTriggerForm
        v-if="triggerApi"
        ref="triggerFormRef"
        :api-id="triggerApi.id"
        :trigger-type="triggerApi.trigger_type"
        :mq-config="triggerApi.mq_config"
        :available-entrypoints="triggerFlowEntrypoints?.all_entrypoints"
        :api-entrypoint="triggerApi.entrypoint"
      />
      <template #footer>
        <el-button @click="triggerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="triggerSaving" @click="saveTrigger">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}
.page-head h2 {
  margin: 0;
  font-size: 22px;
}
.dim {
  color: var(--pf-text-dim);
  font-size: 13px;
  margin: 4px 0 0;
}
.api-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
.api-card {
  padding: 20px;
  position: relative;
  overflow: hidden;
  cursor: default;
  transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
}
.api-card:hover {
  transform: translateY(-3px);
  border-color: var(--pf-accent);
  box-shadow: var(--pf-shadow-md);
}
.lock-badge {
  position: absolute;
  top: 0;
  right: 0;
  background: #facc15;
  color: #78350f;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 0 12px 0 10px;
  display: flex;
  align-items: center;
  gap: 4px;
  animation: badge-in 0.3s ease;
}
@keyframes badge-in {
  from { opacity: 0; transform: translateX(20px); }
  to   { opacity: 1; transform: translateX(0); }
}
.api-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.api-name {
  font-size: 15px;
  font-weight: 600;
}
.api-path {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--pf-accent);
  margin: 0 0 6px;
}
.api-path code {
  background: var(--pf-accent-soft);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.copy-icon {
  cursor: pointer;
  color: var(--pf-text-dim);
  transition: color 0.18s ease, transform 0.18s ease;
}
.copy-icon:hover {
  color: var(--pf-accent);
  transform: scale(1.15);
}
.api-desc {
  font-size: 13px;
  color: var(--pf-text-dim);
  margin: 0 0 14px;
  min-height: 18px;
}
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  background: var(--pf-panel-2);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 14px;
}
.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.stat-label {
  font-size: 11px;
  color: var(--pf-text-dim);
}
.stat-val {
  font-size: 15px;
  font-weight: 600;
  color: var(--pf-text);
}
.text-success {
  color: #22c55e;
}
.api-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.publish-form .el-form-item {
  margin-bottom: 18px;
}
.ep-hint {
  font-size: 12px;
  color: var(--pf-text-dim);
  margin-top: 5px;
  line-height: 1.5;
}
.ep-entry-banner {
  margin-bottom: 8px;
}
.ep-no-entry {
  padding: 6px 10px;
  background: var(--pf-panel-2);
  border-radius: 6px;
}
.ep-hint code {
  background: var(--pf-panel-2);
  padding: 1px 5px;
  border-radius: 3px;
}
.ep-nodes {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  animation: slide-up 0.25s ease;
}
.ep-node-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--pf-panel-2);
  border-radius: 6px;
}
.ep-block-name {
  font-size: 12px;
  color: var(--pf-text);
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'JetBrains Mono', monospace;
}
.ep-node-select {
  flex: 0 0 180px;
}
.ep-opt-desc {
  margin-left: 8px;
  font-size: 11px;
  color: var(--pf-text-dim);
}
.ep-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.ep-tag {
  cursor: default;
  transition: all 0.2s;
}
.ep-fade-enter-active,
.ep-fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.ep-fade-enter-from,
.ep-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
.docs-section {
  margin-bottom: 16px;
}
.docs-title {
  margin: 0 0 4px;
  font-size: 17px;
}
.docs-desc {
  color: var(--pf-text-dim);
  margin: 0 0 10px;
}
.docs-meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.docs-path {
  background: var(--pf-panel-2);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 13px;
}
.port-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.port-list {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.port-list li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.code-block {
  background: var(--pf-code-bg);
  color: var(--pf-code-text);
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 12px;
  overflow-x: auto;
  margin: 8px 0 16px;
}

/* ── MQ 调用方式区 ── */
.mq-invoke {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--pf-accent-soft);
  border-radius: 8px;
  background: var(--pf-accent-soft);
}
.mq-invoke-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13px;
  color: var(--pf-accent);
  margin-bottom: 10px;
}
.mq-test-btn { margin-left: auto; }
.mq-kv-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
}
.mq-kv {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.mq-k {
  color: var(--pf-text-dim);
  font-size: 11px;
  min-width: 64px;
  flex-shrink: 0;
}
.mq-kv code {
  background: var(--pf-panel);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  word-break: break-all;
}
.mq-line {
  margin-top: 10px;
  font-size: 12px;
}
.mq-line code {
  background: var(--pf-panel);
  padding: 1px 6px;
  border-radius: 4px;
}
.mq-mapping .port-list { margin-top: 6px; }
.mq-section-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.mq-section-enter-from { opacity: 0; transform: translateY(8px); }

/* ── 接口测试 ── */
.test-target {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  padding: 10px 14px;
  background: var(--pf-panel-2);
  border-radius: 8px;
  animation: test-in 0.3s ease;
}
.test-path {
  flex: 1;
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 13px;
  word-break: break-all;
}
.test-section {
  margin-bottom: 16px;
}
.test-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.test-section-head h4 {
  margin: 0;
}
.test-editor :deep(.el-textarea__inner) {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}
.test-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}
.stream-switch {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stream-hint {
  color: var(--pf-text-dim);
  cursor: help;
  transition: color 0.18s ease;
}
.stream-hint:hover {
  color: var(--pf-accent);
}
.stream-block {
  margin-top: 16px;
  animation: stream-in 0.3s ease;
}
@keyframes stream-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.streaming-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.live-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--pf-accent);
  animation: live-pulse 1s ease-in-out infinite;
}
@keyframes live-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.3; transform: scale(0.7); }
}
.stream-output {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  min-height: 48px;
}
.stream-cursor {
  display: inline-block;
  color: var(--pf-accent);
  animation: cursor-blink 1s step-end infinite;
}
@keyframes cursor-blink {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0; }
}
.stream-err {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0 0;
  color: #f56c6c;
  font-size: 13px;
}
.resp-block {
  margin-top: 18px;
}
.resp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.resp-head h4 {
  margin: 0;
}
.resp-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.resp-code {
  max-height: 320px;
  overflow: auto;
  margin: 0;
}
@keyframes test-in {
  from { opacity: 0; transform: translateY(-6px); }
  to   { opacity: 1; transform: translateY(0); }
}
/* 响应区淡入上滑动画 */
.resp-fade-enter-active {
  transition: opacity 0.32s ease, transform 0.32s ease;
}
.resp-fade-enter-from {
  opacity: 0;
  transform: translateY(12px);
}

/* ── 加密保护 Dialog ── */
.enc-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 60px;
}
.enc-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  background: var(--pf-panel-2);
  border-radius: 8px;
}
.enc-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.enc-title {
  font-size: 14px;
  font-weight: 600;
}
.enc-sub {
  font-size: 12px;
  color: var(--pf-text-dim);
  line-height: 1.5;
}
.enc-key-block {
  border: 1px solid var(--pf-accent-soft);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--pf-accent-soft);
}
.enc-key-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.enc-key-ops {
  display: flex;
  gap: 4px;
}
.enc-key-value {
  margin: 0;
  padding: 10px 12px;
  background: var(--pf-code-bg);
  color: var(--pf-code-text);
  border-radius: 6px;
  font-size: 12px;
  word-break: break-all;
  white-space: pre-wrap;
}
.enc-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 10px 0 0;
  font-size: 12px;
  color: #e6a23c;
}
.enc-usage h4 {
  margin: 0 0 8px;
}
.enc-steps {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--pf-text);
}
.enc-steps code {
  background: var(--pf-panel-2);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}
.enc-snippet {
  margin: 8px 0 0;
}
.enc-fade-enter-active,
.enc-fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.enc-fade-enter-from,
.enc-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
