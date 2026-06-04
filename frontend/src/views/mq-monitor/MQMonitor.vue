<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mqApi, blockApi, type Block } from '@/api'

const consumers = ref<any[]>([])
const mode = ref('local')
const blocks = ref<Block[]>([])
const loading = ref(false)
const polling = ref<ReturnType<typeof setInterval>>()

// 测试发布弹窗
const publishDialogVisible = ref(false)
const publishTarget = ref<{ block_id: string; block_name: string } | null>(null)
const publishPayload = ref('{\n  "value": 1\n}')
const snowflakeId = ref('')
const publishing = ref(false)

async function load() {
  loading.value = true
  try {
    const [status, allBlocks] = await Promise.all([
      mqApi.getStatus(),
      blockApi.list(),
    ])
    mode.value = status.mode
    blocks.value = allBlocks.filter((b: Block) => ['async_mq', 'both'].includes(b.execution_mode))

    // 合并消费者状态与队列深度
    const consumerMap = Object.fromEntries(
      (status.consumers || []).map((c: any) => [c.block_id, c])
    )

    // 对每个 async_mq 块补充深度信息
    const enriched = await Promise.all(
      blocks.value.map(async (b: Block) => {
        const consumer = consumerMap[b.id] || null
        let depth = { main: 0, dlq: 0 }
        try {
          depth = await mqApi.getDepth(b.id)
        } catch {}
        return { block: b, consumer, depth }
      })
    )
    consumers.value = enriched
  } finally {
    loading.value = false
  }
}

async function startConsumer(blockId: string) {
  try {
    const res = await mqApi.start(blockId)
    ElMessage.success(res.started ? '消费者已启动' : res.message || '已请求启动')
    setTimeout(load, 800)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动失败')
  }
}

async function stopConsumer(blockId: string) {
  try {
    await mqApi.stop(blockId)
    ElMessage.success('已停止')
    setTimeout(load, 400)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '停止失败')
  }
}

async function restartConsumer(blockId: string) {
  try {
    await mqApi.restart(blockId)
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
  publishTarget.value = { block_id: item.block.id, block_name: item.block.name }
  publishPayload.value = '{\n  "value": 1\n}'
  snowflakeId.value = ''
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
  try {
    const res = await mqApi.publish(publishTarget.value!.block_id, {
      payload,
      snowflake_id: snowflakeId.value || undefined,
    })
    if (res.error) {
      ElMessage.error(res.error)
    } else {
      ElMessage.success(`消息已发布 snowflakeId: ${res.snowflake_id}`)
      publishDialogVisible.value = false
      setTimeout(load, 500)
    }
  } finally {
    publishing.value = false
  }
}

const statusType: Record<string, string> = {
  running: 'success',
  connecting: 'warning',
  stopped: 'info',
  error: 'danger',
}

const totalRunning = computed(() =>
  consumers.value.filter(c => c.consumer?.status === 'running').length
)
const totalDlq = computed(() =>
  consumers.value.reduce((sum, c) => sum + (c.depth?.dlq || 0), 0)
)

function formatDuration(startedAt: number): string {
  const sec = Math.floor(Date.now() / 1000 - startedAt)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m${sec % 60}s`
  return `${Math.floor(sec / 3600)}h${Math.floor((sec % 3600) / 60)}m`
}

onMounted(() => {
  load()
  polling.value = setInterval(load, 8000)
})
onUnmounted(() => clearInterval(polling.value))
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
        <div><span class="ov-val">{{ blocks.length }}</span><span class="ov-label"> async_mq 块</span></div>
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

    <!-- 消费者列表 -->
    <transition-group name="list" tag="div" class="consumer-list">
      <div v-for="item in consumers" :key="item.block.id" class="pf-card consumer-card">
        <div class="cc-header">
          <div class="cc-name-row">
            <span class="cc-name">{{ item.block.name }}</span>
            <el-tag :type="item.block.execution_mode === 'async_mq' ? 'primary' : 'warning'" size="small" effect="plain">
              {{ item.block.execution_mode }}
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
            <el-badge :value="item.depth.main" :hidden="item.depth.main === 0" type="primary">
              <el-tag size="small" effect="plain">主队列</el-tag>
            </el-badge>
            <el-badge :value="item.depth.dlq" :hidden="item.depth.dlq === 0" type="danger">
              <el-tag size="small" effect="plain" :type="item.depth.dlq > 0 ? 'danger' : 'info'">
                DLQ
              </el-tag>
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
        <div class="mq-config-summary" v-if="item.block.mq_config?.queue">
          <el-icon><MessageBox /></el-icon>
          <code>{{ item.block.mq_config.queue }}</code>
          <span class="dim" v-if="item.block.mq_config.condition_expression">
            条件: {{ item.block.mq_config.condition_expression.slice(0, 40) }}
          </span>
          <el-tag v-if="item.block.mq_config.reply_enabled" size="small" type="success" effect="plain">
            有回复
          </el-tag>
          <span class="dim">重试 {{ item.block.mq_config.max_retry || 3 }}x / {{ item.block.mq_config.retry_delay_ms || 5000 }}ms</span>
        </div>

        <div class="cc-actions">
          <el-button
            v-if="item.consumer?.status !== 'running'"
            type="success"
            size="small"
            :disabled="mode !== 'local'"
            @click="startConsumer(item.block.id)"
          >
            <el-icon><VideoPlay /></el-icon> 启动
          </el-button>
          <el-button
            v-else
            type="warning"
            size="small"
            @click="stopConsumer(item.block.id)"
          >
            <el-icon><VideoPause /></el-icon> 停止
          </el-button>
          <el-button size="small" @click="restartConsumer(item.block.id)">
            <el-icon><RefreshRight /></el-icon> 重启
          </el-button>
          <el-button size="small" type="primary" @click="openPublish(item)">
            <el-icon><Promotion /></el-icon> 发布测试消息
          </el-button>
        </div>
      </div>
    </transition-group>

    <el-empty
      v-if="!loading && consumers.length === 0"
      description="暂无 async_mq / both 模式的调用块，请先在块编辑器中配置 MQ 触发"
    />

    <!-- 发布测试消息 Dialog -->
    <el-dialog v-model="publishDialogVisible" title="发布测试消息" width="520px">
      <el-form label-width="100px" v-if="publishTarget">
        <el-form-item label="目标块">
          <strong>{{ publishTarget.block_name }}</strong>
          <code style="margin-left:8px;font-size:12px">block.{{ publishTarget.block_id.slice(0,8) }}....queue</code>
        </el-form-item>
        <el-form-item label="消息体 JSON">
          <el-input
            v-model="publishPayload"
            type="textarea"
            :rows="6"
            style="font-family:monospace;font-size:12px"
          />
        </el-form-item>
        <el-form-item label="snowflakeId">
          <el-input v-model="snowflakeId" placeholder="留空自动生成" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="publishDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="publishing" @click="doPublish">发布</el-button>
      </template>
    </el-dialog>
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
</style>
