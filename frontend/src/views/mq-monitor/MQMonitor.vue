<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mqApi, apiPortalApi, type PublishedApi } from '@/api'

const consumers = ref<any[]>([])
const mode = ref('local')
const mqApis = ref<PublishedApi[]>([])
const loading = ref(false)
const polling = ref<ReturnType<typeof setInterval>>()
const clockTimer = ref<ReturnType<typeof setInterval>>()
const autoRefresh = ref(true)
const lastUpdated = ref(Date.now())
const nowTs = ref(Date.now())

// DLQ 运维抽屉
const dlqDrawer = ref(false)
const dlqTarget = ref<{ api_id: string; api_name: string } | null>(null)
const dlqMessages = ref<any[]>([])
const dlqLoading = ref(false)
const dlqActing = ref(false)

// 测试执行弹窗
const publishDialogVisible = ref(false)
const publishTarget = ref<{ api_id: string; api_name: string } | null>(null)
const publishPayload = ref('{\n  "value": 1\n}')
const snowflakeId = ref('')
const publishing = ref(false)
const runResult = ref<any>(null)   // 执行返回值
const showResult = ref(false)

let _loadInFlight = false

async function load() {
  // 防止 8s 轮询与手动/动作后刷新叠加：上一次未完成时直接跳过本次
  if (_loadInFlight) return
  _loadInFlight = true
  loading.value = true
  try {
    const [status, allApis] = await Promise.all([
      mqApi.getStatus(),
      apiPortalApi.list(),
    ])
    mode.value = status.mode
    mqApis.value = allApis.filter((a: PublishedApi) => ['mq', 'both'].includes(a.trigger_type))

    // 合并消费者状态与队列深度（按 api_id 维度）
    const consumerMap = Object.fromEntries(
      (status.consumers || []).map((c: any) => [c.api_id, c])
    )

    const enriched = await Promise.all(
      mqApis.value.map(async (a: PublishedApi) => {
        const consumer = consumerMap[a.id] || null
        let depth = { main: 0, dlq: 0 }
        try {
          depth = await mqApi.getDepth(a.id)
        } catch {}
        return { api: a, consumer, depth }
      })
    )
    consumers.value = enriched
    lastUpdated.value = Date.now()
  } finally {
    loading.value = false
    _loadInFlight = false
  }
}

async function startConsumer(apiId: string) {
  try {
    const res = await mqApi.start(apiId)
    ElMessage.success(res.started ? '消费者已启动' : res.message || '已请求启动')
    setTimeout(load, 800)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动失败')
  }
}

async function stopConsumer(apiId: string) {
  try {
    await mqApi.stop(apiId)
    ElMessage.success('已停止')
    setTimeout(load, 400)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '停止失败')
  }
}

async function restartConsumer(apiId: string) {
  try {
    await mqApi.restart(apiId)
    ElMessage.success('已重启')
    setTimeout(load, 800)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重启失败')
  }
}

async function startAll() {
  loading.value = true
  try {
    const res = await mqApi.startAll()
    ElMessage.success(`已启动 ${res.total} 个消费者`)
    setTimeout(load, 1000)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '批量启动失败')
  } finally {
    loading.value = false
  }
}

async function stopAll() {
  await ElMessageBox.confirm('确认停止所有消费者？', '停止确认', { type: 'warning' })
  try {
    await mqApi.stopAll()
    ElMessage.success('已停止所有消费者')
    setTimeout(load, 400)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '停止失败')
  }
}

function openPublish(item: any) {
  publishTarget.value = { api_id: item.api.id, api_name: item.api.name }
  publishPayload.value = '{\n  "value": 1\n}'
  snowflakeId.value = ''
  runResult.value = null
  showResult.value = false
  publishDialogVisible.value = true
}

async function doPublish() {
  let payload: object = {}
  try {
    payload = JSON.parse(publishPayload.value || '{}')
  } catch {
    return ElMessage.error('消息体必须是合法 JSON')
  }
  publishing.value = true
  runResult.value = null
  showResult.value = false
  try {
    const res = await mqApi.testRun(publishTarget.value!.api_id, {
      payload,
      snowflake_id: snowflakeId.value || undefined,
    })
    if (res.error) {
      ElMessage.error(res.error)
    } else {
      runResult.value = res
      showResult.value = true
      setTimeout(load, 500)
    }
  } finally {
    publishing.value = false
  }
}

// ── DLQ 运维（查看死信 / 重投 / 清空）─────────────────────────────────────────
async function openDlq(item: any) {
  dlqTarget.value = { api_id: item.api.id, api_name: item.api.name }
  dlqMessages.value = []
  dlqDrawer.value = true
  await loadDlq()
}

async function loadDlq() {
  if (!dlqTarget.value) return
  dlqLoading.value = true
  try {
    const res = await mqApi.peekDlq(dlqTarget.value.api_id, 20)
    dlqMessages.value = res.messages || []
  } catch {
    dlqMessages.value = []
  } finally {
    dlqLoading.value = false
  }
}

async function requeueDlq() {
  if (!dlqTarget.value) return
  try {
    await ElMessageBox.confirm(
      '确认将该接口所有死信重投回主队列？将重置 x-retry-count 重新计数。',
      '重投死信', { type: 'warning' },
    )
  } catch {
    return
  }
  dlqActing.value = true
  try {
    const res = await mqApi.requeueDlq(dlqTarget.value.api_id)
    ElMessage.success(`已重投 ${res.requeued} 条死信`)
    await loadDlq()
    setTimeout(load, 600)
  } finally {
    dlqActing.value = false
  }
}

async function purgeDlq() {
  if (!dlqTarget.value) return
  try {
    await ElMessageBox.confirm(
      '确认清空该接口 DLQ？死信将被永久删除，不可恢复。',
      '清空死信', { type: 'warning', confirmButtonText: '清空', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  dlqActing.value = true
  try {
    const res = await mqApi.purgeDlq(dlqTarget.value.api_id)
    ElMessage.success(`已清空 ${res.purged} 条死信`)
    await loadDlq()
    setTimeout(load, 600)
  } finally {
    dlqActing.value = false
  }
}

const updatedAgo = computed(() => {
  const sec = Math.max(0, Math.floor((nowTs.value - lastUpdated.value) / 1000))
  if (sec < 5) return '刚刚更新'
  if (sec < 60) return `${sec}s 前更新`
  return `${Math.floor(sec / 60)}m 前更新`
})

const statusType: Record<string, string> = {
  running: 'success',
  connecting: 'warning',
  stopped: 'info',
  error: 'danger',
}

const triggerTypeLabel: Record<string, string> = {
  http: 'HTTP', mq: 'MQ', both: 'HTTP+MQ',
}

const totalRunning = computed(() =>
  consumers.value.filter(c => c.consumer?.status === 'running').length
)
const totalDlq = computed(() =>
  consumers.value.reduce((sum, c) => {
    const dlq = c.depth?.dlq ?? 0
    return sum + (dlq > 0 ? dlq : 0)   // -1（不可达）不计入
  }, 0)
)

/** -1 表示 RabbitMQ Management API 不可达，显示 N/A */
function depthLabel(val: number): string {
  return val === -1 ? 'N/A' : String(val)
}
function depthHidden(val: number): boolean {
  return val <= 0   // 0 和 -1 都隐藏 badge
}

function formatDuration(startedAt: number): string {
  const sec = Math.floor(Date.now() / 1000 - startedAt)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m${sec % 60}s`
  return `${Math.floor(sec / 3600)}h${Math.floor((sec % 3600) / 60)}m`
}

function tick() {
  // 自动刷新开关 + 后台标签暂停轮询（省资源，降低无谓请求）
  if (autoRefresh.value && !document.hidden) load()
}
function onVisibility() {
  if (!document.hidden && autoRefresh.value) load()
}

onMounted(() => {
  load()
  polling.value = setInterval(tick, 8000)
  // 后台标签暂停时钟刷新，避免无谓的每秒响应式更新
  clockTimer.value = setInterval(() => {
    if (!document.hidden) nowTs.value = Date.now()
  }, 1000)
  document.addEventListener('visibilitychange', onVisibility)
})
onUnmounted(() => {
  clearInterval(polling.value)
  clearInterval(clockTimer.value)
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>MQ 消费者监控</h2>
        <p class="dim">
          Phase 2 — RabbitMQ 异步触发 · TTL+DLX 重试 · Redis 幂等锁
          <el-tag size="small" :type="mode === 'local' ? 'info' : 'success'" style="margin-left:8px">
            {{ mode === 'local' ? 'dev-local' : 'K8s' }}
          </el-tag>
        </p>
      </div>
      <div class="head-actions">
        <div class="auto-refresh">
          <el-switch v-model="autoRefresh" size="small" />
          <span class="dim ar-label">自动刷新</span>
          <span class="dim ar-time">{{ updatedAgo }}</span>
        </div>
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button type="success" @click="startAll" :disabled="mode !== 'local'">
          <el-icon><VideoPlay /></el-icon> 全部启动
        </el-button>
        <el-button type="danger" @click="stopAll">
          <el-icon><VideoPause /></el-icon> 全部停止
        </el-button>
      </div>
    </header>

    <!-- 概览 -->
    <div class="overview-row">
      <div class="pf-card ov-card" style="animation-delay:0ms">
        <div class="ov-icon green"><el-icon size="22"><Connection /></el-icon></div>
        <div><span class="ov-val">{{ totalRunning }}</span><span class="ov-label"> 运行中</span></div>
      </div>
      <div class="pf-card ov-card" style="animation-delay:60ms">
        <div class="ov-icon blue"><el-icon size="22"><Collection /></el-icon></div>
        <div><span class="ov-val">{{ mqApis.length }}</span><span class="ov-label"> MQ 接口</span></div>
      </div>
      <div class="pf-card ov-card" :class="{'ov-warn': totalDlq > 0}" style="animation-delay:120ms">
        <div class="ov-icon" :class="totalDlq > 0 ? 'red' : 'dim-icon'">
          <el-icon size="22"><Warning /></el-icon>
        </div>
        <div>
          <span class="ov-val" :class="{'text-danger': totalDlq > 0}">{{ totalDlq }}</span>
          <span class="ov-label"> DLQ 积压</span>
        </div>
      </div>
    </div>

    <!-- 消费者列表（按接口/Flow 维度） -->
    <transition-group name="list" tag="div" class="consumer-list">
      <div v-for="item in consumers" :key="item.api.id" class="pf-card consumer-card">
        <div class="cc-header">
          <div class="cc-name-row">
            <span class="cc-name">{{ item.api.name }}</span>
            <el-tag :type="item.api.trigger_type === 'mq' ? 'primary' : 'warning'" size="small" effect="plain">
              {{ triggerTypeLabel[item.api.trigger_type] || item.api.trigger_type }}
            </el-tag>
            <el-tag
              :type="statusType[item.consumer?.status || 'stopped']"
              size="small"
              :class="{ 'pf-running': item.consumer?.status === 'connecting' }"
            >
              {{ item.consumer?.status || 'stopped' }}
            </el-tag>
          </div>

          <!-- 队列深度 -->
          <div class="depth-badges">
            <el-badge :value="item.depth.main" :hidden="depthHidden(item.depth.main)" type="primary">
              <el-tooltip :content="item.depth.main === -1 ? 'RabbitMQ Management 不可达' : `主队列: ${item.depth.main}`">
                <el-tag size="small" effect="plain">
                  主队列 {{ item.depth.main === -1 ? 'N/A' : '' }}
                </el-tag>
              </el-tooltip>
            </el-badge>
            <el-badge :value="item.depth.dlq" :hidden="depthHidden(item.depth.dlq)" type="danger">
              <el-tooltip :content="item.depth.dlq === -1 ? 'RabbitMQ Management 不可达' : `DLQ: ${item.depth.dlq}`">
                <el-tag size="small" effect="plain" :type="item.depth.dlq > 0 ? 'danger' : 'info'">
                  DLQ {{ item.depth.dlq === -1 ? 'N/A' : '' }}
                </el-tag>
              </el-tooltip>
            </el-badge>
          </div>
        </div>

        <!-- 消费者统计 -->
        <div class="cc-stats" v-if="item.consumer">
          <div class="stat">
            <span class="st-label">已处理</span>
            <span class="st-val">{{ item.consumer.processed }}</span>
          </div>
          <div class="stat">
            <span class="st-label">失败</span>
            <span class="st-val" :class="{ 'text-danger': item.consumer.errors > 0 }">
              {{ item.consumer.errors }}
            </span>
          </div>
          <div class="stat" v-if="item.consumer.started_at">
            <span class="st-label">运行时长</span>
            <span class="st-val">{{ formatDuration(item.consumer.started_at) }}</span>
          </div>
          <div class="stat error-detail" v-if="item.consumer.last_error">
            <span class="st-label">最近错误</span>
            <span class="st-val text-danger" :title="item.consumer.last_error">
              {{ item.consumer.last_error.slice(0, 60) }}…
            </span>
          </div>
        </div>

        <!-- MQ 配置摘要 -->
        <div class="mq-config-summary">
          <el-icon><MessageBox /></el-icon>
          <code>{{ item.api.mq_config?.queue || `flow.${item.api.id}.queue` }}</code>
          <span class="dim" v-if="item.api.mq_config?.condition_expression">
            条件: {{ item.api.mq_config.condition_expression.slice(0, 40) }}
          </span>
          <el-tag v-if="item.api.mq_config?.reply_enabled" size="small" type="success" effect="plain">
            有回复
          </el-tag>
          <span class="dim">重试 {{ item.api.mq_config?.max_retry || 3 }}x / {{ item.api.mq_config?.retry_delay_ms || 5000 }}ms</span>
        </div>

        <div class="cc-actions">
          <el-button
            v-if="item.consumer?.status !== 'running'"
            type="success"
            size="small"
            :disabled="mode !== 'local'"
            @click="startConsumer(item.api.id)"
          >
            <el-icon><VideoPlay /></el-icon> 启动
          </el-button>
          <el-button
            v-else
            type="warning"
            size="small"
            @click="stopConsumer(item.api.id)"
          >
            <el-icon><VideoPause /></el-icon> 停止
          </el-button>
          <el-button size="small" @click="restartConsumer(item.api.id)">
            <el-icon><RefreshRight /></el-icon> 重启
          </el-button>
          <el-button size="small" type="primary" @click="openPublish(item)">
            <el-icon><Promotion /></el-icon> 发布测试消息
          </el-button>
          <el-button
            size="small"
            :type="item.depth.dlq > 0 ? 'danger' : 'default'"
            plain
            @click="openDlq(item)"
          >
            <el-icon><Warning /></el-icon>
            DLQ 运维<span v-if="item.depth.dlq > 0"> ({{ item.depth.dlq }})</span>
          </el-button>
        </div>
      </div>
    </transition-group>

    <el-empty
      v-if="!loading && consumers.length === 0"
      description="暂无 MQ / both 触发方式的接口，请先在「接口管理」中为接口配置 MQ 触发"
    />

    <!-- 测试执行 Dialog -->
    <el-dialog v-model="publishDialogVisible" title="MQ 消息测试执行" width="600px" destroy-on-close>
      <el-form label-width="90px" v-if="publishTarget">
        <el-form-item label="目标接口">
          <strong>{{ publishTarget.api_name }}</strong>
        </el-form-item>
        <el-form-item label="消息体 JSON">
          <el-input
            v-model="publishPayload"
            type="textarea"
            :rows="6"
            style="font-family:monospace;font-size:12px"
            placeholder='{"value": 1}'
          />
          <div class="form-hint">将经过接口的 input_mapping 规则提取 inputs，再同步驱动整条 Flow</div>
        </el-form-item>
        <el-form-item label="snowflakeId">
          <el-input v-model="snowflakeId" placeholder="留空自动生成（幂等键）" />
        </el-form-item>
      </el-form>

      <!-- 执行结果区 -->
      <transition name="fade">
        <div v-if="showResult && runResult" class="run-result">
          <div class="res-header">
            <el-tag :type="runResult.status === 'succeeded' ? 'success' : 'danger'" size="large">
              {{ runResult.status === 'succeeded' ? '✓ 执行成功' : '✗ 执行失败' }}
            </el-tag>
            <span class="res-id dim">snowflake_id: {{ runResult.snowflake_id }}</span>
          </div>

          <div class="res-section" v-if="runResult.inputs_used && Object.keys(runResult.inputs_used).length">
            <div class="res-label">实际 inputs（经 input_mapping 提取后）</div>
            <pre class="res-pre">{{ JSON.stringify(runResult.inputs_used, null, 2) }}</pre>
          </div>

          <div class="res-section" v-if="runResult.outputs !== null && runResult.outputs !== undefined">
            <div class="res-label">流程输出 outputs</div>
            <pre class="res-pre res-output">{{ JSON.stringify(runResult.outputs, null, 2) }}</pre>
          </div>
        </div>
      </transition>

      <template #footer>
        <el-button @click="publishDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="publishing" @click="doPublish">
          <el-icon><VideoPlay /></el-icon>
          {{ showResult ? '重新执行' : '执行' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- DLQ 运维抽屉 -->
    <el-drawer v-model="dlqDrawer" size="520px" :with-header="true">
      <template #header>
        <div class="dlq-head">
          <el-icon color="#ef4444"><Warning /></el-icon>
          <span>DLQ 运维 · {{ dlqTarget?.api_name }}</span>
        </div>
      </template>
      <div class="dlq-body">
        <div class="dlq-actions">
          <el-button size="small" :loading="dlqLoading" @click="loadDlq">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-button size="small" type="primary" :loading="dlqActing" @click="requeueDlq">
            <el-icon><RefreshRight /></el-icon> 全部重投回主队列
          </el-button>
          <el-button size="small" type="danger" plain :loading="dlqActing" @click="purgeDlq">
            <el-icon><Delete /></el-icon> 清空死信
          </el-button>
        </div>
        <p class="dim dlq-tip">
          下方为死信样本预览（最多 20 条，预览不消费）。重投会重置 x-retry-count 并回到主队列重新处理。
        </p>

        <el-empty v-if="!dlqLoading && dlqMessages.length === 0" description="DLQ 为空 🎉" :image-size="80" />

        <transition-group name="list" tag="div" class="dlq-list">
          <div v-for="(m, i) in dlqMessages" :key="i" class="pf-card dlq-item">
            <div class="dlq-item-head">
              <el-tag size="small" type="danger" effect="plain">死信 #{{ i + 1 }}</el-tag>
              <span class="dim">retry: {{ m.x_retry_count ?? 'N/A' }}</span>
              <el-tag v-if="m.redelivered" size="small" type="warning" effect="plain">redelivered</el-tag>
            </div>
            <pre class="dlq-payload">{{ m.payload }}</pre>
          </div>
        </transition-group>
      </div>
    </el-drawer>
  </div>
</template>


<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.page-head h2 { margin: 0; font-size: 22px; }
.dim { color: var(--pf-text-dim); font-size: 13px; margin: 4px 0 0; }
.head-actions { display: flex; gap: 8px; }

/* 概览行 */
.overview-row {
  display: flex;
  gap: 14px;
  margin-bottom: 24px;
}
.ov-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  min-width: 160px;
  animation: slide-up 0.35s ease both;
}
@keyframes slide-up {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
.ov-icon {
  width: 40px; height: 40px;
  border-radius: 10px;
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.ov-icon.green  { background: rgba(34,197,94,0.12); color: #22c55e; }
.ov-icon.blue   { background: rgba(8,145,178,0.12); color: #0891b2; }
.ov-icon.red    { background: rgba(239,68,68,0.12); color: #ef4444; }
.ov-icon.dim-icon { background: var(--pf-panel-2); color: var(--pf-text-dim); }
.ov-val  { font-size: 22px; font-weight: 700; }
.ov-label{ font-size: 13px; color: var(--pf-text-dim); }
.ov-warn { border-color: rgba(239,68,68,0.4); }
.text-danger { color: #ef4444; }

/* 消费者卡片 */
.consumer-list { display: flex; flex-direction: column; gap: 14px; }
.consumer-card {
  padding: 16px 20px;
  animation: slide-up 0.3s ease both;
}
.cc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.cc-name-row { display: flex; align-items: center; gap: 8px; }
.cc-name { font-size: 15px; font-weight: 600; }
.depth-badges { display: flex; gap: 10px; align-items: center; }
.cc-stats {
  display: flex;
  gap: 20px;
  background: var(--pf-panel-2);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.stat { display: flex; flex-direction: column; gap: 2px; }
.st-label { font-size: 11px; color: var(--pf-text-dim); }
.st-val { font-size: 14px; font-weight: 600; }
.error-detail { flex: 1; min-width: 200px; }
.mq-config-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--pf-text-dim);
  background: var(--pf-panel-2);
  padding: 6px 10px;
  border-radius: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.mq-config-summary code {
  color: var(--pf-accent);
  background: var(--pf-accent-soft);
  padding: 1px 5px;
  border-radius: 3px;
}
.cc-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* 表单提示 */
.form-hint { font-size: 12px; color: var(--pf-text-dim); margin-top: 4px; }

/* 执行结果面板 */
.run-result {
  margin-top: 16px;
  border-top: 1px solid var(--pf-border);
  padding-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  animation: slide-up 0.25s ease;
}
.res-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.res-dur { font-size: 13px; color: var(--pf-text-dim); }
.res-id  { font-size: 11px; }
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
  max-height: 180px;
  overflow-y: auto;
  margin: 0;
}
.res-output { color: #4ade80; }
.res-stdout { color: var(--pf-text); }
.res-stderr { color: #f87171; }

/* 淡入动画 */
.fade-enter-active { transition: opacity 0.3s, transform 0.3s; }
.fade-enter-from   { opacity: 0; transform: translateY(6px); }

/* 自动刷新控件 */
.auto-refresh {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-right: 10px;
  margin-right: 4px;
  border-right: 1px solid var(--pf-border);
}
.ar-label { margin: 0; }
.ar-time { margin: 0; min-width: 76px; transition: color 0.3s; }

/* DLQ 抽屉 */
.dlq-head { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.dlq-body { display: flex; flex-direction: column; gap: 12px; }
.dlq-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.dlq-tip { margin: 0; line-height: 1.6; }
.dlq-list { display: flex; flex-direction: column; gap: 10px; }
.dlq-item { padding: 10px 12px; animation: slide-up 0.25s ease both; }
.dlq-item-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.dlq-payload {
  margin: 0;
  background: var(--pf-panel-2);
  border: 1px solid var(--pf-border);
  border-radius: 6px;
  padding: 8px 10px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow-y: auto;
}

/* 列表过渡 */
.list-enter-active, .list-leave-active { transition: all 0.3s ease; }
.list-enter-from { opacity: 0; transform: translateX(-10px); }
.list-leave-to { opacity: 0; transform: translateX(10px); }
</style>
