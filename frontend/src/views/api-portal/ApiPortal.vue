<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiPortalApi, flowApi, type PublishedApi } from '@/api'
import MqMockTestDialog from '@/components/MqMockTestDialog.vue'

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

// ── MQ Mock 测试 ──────────────────────────────────────────────────────────
const mqTestVisible = ref(false)
const mqTestBlock = ref<{ id: string; name: string; preset: Record<string, any> | null }>({
  id: '',
  name: '',
  preset: null,
})

function openMqTest(block: any) {
  mqTestBlock.value = {
    id: block.mq_invocation?.block_id || block.block_id,
    name: block.block_name,
    preset: block.mq_invocation?.message_example || null,
  }
  mqTestVisible.value = true
}

const form = ref({
  name: '',
  description: '',
  path: '',
  tags: '',
  flow_id: '',
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
    await apiPortalApi.publish(form.value)
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
  form.value = { name: '', description: '', path: '', tags: '', flow_id: '' }
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
          <el-tag v-if="api.rate_limit_enabled" size="small" type="warning" effect="plain">
            限流 {{ api.rate_limit_per_minute }}/min
          </el-tag>
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
    <el-dialog v-model="publishDialogVisible" title="发布流程为接口" width="520px" :close-on-click-modal="false">
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
                {{ docsData.mq_block_count }} 个块支持 MQ 调用
              </el-tag>
            </div>
          </div>

          <el-divider />

          <div class="docs-section">
            <h4>流程信息</h4>
            <p>流程名称：<strong>{{ docsData.flow_name }}</strong>（{{ docsData.node_count }} 块 / {{ docsData.edge_count }} 条边）</p>
          </div>

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
                  <el-tag
                    v-if="block.mq_invocation"
                    size="small"
                    type="primary"
                    effect="plain"
                    style="margin-left:8px"
                  >
                    <el-icon style="margin-right:3px"><MessageBox /></el-icon>支持 MQ 调用
                  </el-tag>
                </template>
                <p class="dim" style="margin:0 0 8px">{{ block.description || '暂无描述' }}</p>
                <p style="margin:0 0 8px">
                  <strong>入口函数：</strong>
                  <code>{{ block.entrypoint || 'run' }}</code>
                  <el-tag size="small" type="info" effect="plain" style="margin-left:8px">
                    {{ block.execution_mode }}
                  </el-tag>
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

                <!-- 通过 MQ 调用 -->
                <transition name="mq-section">
                  <div v-if="block.mq_invocation" class="mq-invoke">
                    <div class="mq-invoke-head">
                      <el-icon><MessageBox /></el-icon>
                      <span>通过 MQ 调用（RabbitMQ 异步触发）</span>
                      <el-button
                        size="small"
                        type="primary"
                        plain
                        class="mq-test-btn"
                        @click="openMqTest(block)"
                      >
                        <el-icon style="margin-right:4px"><VideoPlay /></el-icon>Mock 测试
                      </el-button>
                    </div>

                    <div class="mq-kv-grid">
                      <div class="mq-kv">
                        <span class="mq-k">主队列</span>
                        <code>{{ block.mq_invocation.queue }}</code>
                      </div>
                      <div class="mq-kv">
                        <span class="mq-k">交换机</span>
                        <code>{{ block.mq_invocation.exchange }}</code>
                      </div>
                      <div class="mq-kv">
                        <span class="mq-k">路由键</span>
                        <code>{{ block.mq_invocation.routing_key }}</code>
                      </div>
                      <div class="mq-kv">
                        <span class="mq-k">死信队列</span>
                        <code>{{ block.mq_invocation.dlq_queue }}</code>
                      </div>
                      <div class="mq-kv">
                        <span class="mq-k">重试</span>
                        <span>{{ block.mq_invocation.max_retry }} 次 / {{ block.mq_invocation.retry_delay_ms }}ms</span>
                      </div>
                      <div class="mq-kv">
                        <span class="mq-k">回复</span>
                        <el-tag size="small" :type="block.mq_invocation.reply_enabled ? 'success' : 'info'" effect="plain">
                          {{ block.mq_invocation.reply_enabled ? '开启' : '关闭' }}
                        </el-tag>
                      </div>
                    </div>

                    <div v-if="block.mq_invocation.condition_expression" class="mq-line">
                      <span class="mq-k">条件订阅</span>
                      <code>{{ block.mq_invocation.condition_language }}: {{ block.mq_invocation.condition_expression }}</code>
                    </div>

                    <div v-if="Object.keys(block.mq_invocation.input_mapping || {}).length" class="mq-line mq-mapping">
                      <span class="mq-k">字段映射（输入字段 ← 消息路径）</span>
                      <ul class="port-list">
                        <li v-for="(src, target) in block.mq_invocation.input_mapping" :key="target">
                          <code>{{ target }}</code>
                          <span class="dim">←</span>
                          <code>{{ src }}</code>
                        </li>
                      </ul>
                    </div>

                    <div class="mq-line">
                      <span class="mq-k">示例消息体</span>
                      <pre class="code-block" style="margin:6px 0 0">{{ JSON.stringify(block.mq_invocation.message_example, null, 2) }}</pre>
                    </div>
                  </div>
                </transition>
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
            type="primary"
            :loading="testSending"
            @click="sendTest"
          >
            <el-icon v-if="!testSending" style="margin-right:6px"><Promotion /></el-icon>
            {{ testSending ? '请求中…' : '发送测试请求' }}
          </el-button>
          <span class="dim" style="margin-left:12px">将真实调用接口，结果计入调用统计</span>
        </div>

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
        <el-button @click="testDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- MQ Mock 测试 Dialog（复用组件） -->
    <MqMockTestDialog
      v-model="mqTestVisible"
      :block-id="mqTestBlock.id"
      :block-name="mqTestBlock.name"
      :preset-payload="mqTestBlock.preset"
    />
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
  margin-bottom: 4px;
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
</style>
