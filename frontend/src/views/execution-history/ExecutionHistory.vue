<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { dashboardApi, execApi } from '@/api'
import CallChain from '@/components/CallChain.vue'

const records = ref<any[]>([])
const loading = ref(false)

const filterStatus = ref('')
const filterSource = ref('')
const searchText = ref('')

const drawer = ref(false)
const selectedRun = ref<any>(null)
const trace = ref<any>(null)
const traceLoading = ref(false)
const activeTab = ref('chain')

const statusTypes: Record<string, string> = {
  succeeded: 'success', success: 'success',
  failed: 'danger', timeout: 'danger',
  running: 'warning', pending: 'info', canceled: 'info',
}

const sourceLabel: Record<string, string> = {
  http: 'HTTP API', stream: '流式 API', mq: 'MQ 消息', manual: '手动触发',
}
const sourceClass: Record<string, string> = {
  http: 'src-http', stream: 'src-stream', mq: 'src-mq', manual: 'src-manual',
}
const stepStatusColor: Record<string, string> = {
  done: '#22c55e', skipped: '#94a3b8', failed: '#ef4444', running: '#f59e0b',
}

const filteredRecords = computed(() => {
  let list = records.value
  if (filterStatus.value) {
    list = list.filter((r) => {
      const s = r.status
      if (filterStatus.value === 'succeeded') return s === 'succeeded' || s === 'success'
      return s === filterStatus.value
    })
  }
  if (filterSource.value) {
    list = list.filter((r) => (r.trigger_source || 'manual') === filterSource.value)
  }
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(
      (r) =>
        (r.id || '').toLowerCase().includes(q) ||
        (r.flow_name || '').toLowerCase().includes(q) ||
        (r.api_name || '').toLowerCase().includes(q),
    )
  }
  return list
})

const statSummary = computed(() => {
  const list = records.value
  return {
    total: list.length,
    succeeded: list.filter((r) => r.status === 'succeeded' || r.status === 'success').length,
    failed: list.filter((r) => r.status === 'failed' || r.status === 'timeout').length,
    api: list.filter((r) => r.trigger_source === 'http' || r.trigger_source === 'stream').length,
    mq: list.filter((r) => r.trigger_source === 'mq').length,
  }
})

async function load() {
  loading.value = true
  try {
    records.value = await execApi.flowRuns()
  } finally {
    loading.value = false
  }
}

async function openDetail(row: any) {
  selectedRun.value = row
  trace.value = null
  activeTab.value = 'chain'
  drawer.value = true
  traceLoading.value = true
  try {
    trace.value = await dashboardApi.flowRunTrace(row.id)
  } finally {
    traceLoading.value = false
  }
}

function shortId(id: string) {
  return (id || '').slice(0, 8)
}
function fmtTime(ts: string) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN', { hour12: false })
}
function fmtDuration(ms: number | null) {
  if (ms == null) return '—'
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return ms + 'ms'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>执行历史</h2>
        <p class="dim">以 Flow 为整体的全部调用记录，含 API 接口与 MQ 消息触发</p>
      </div>
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </header>

    <!-- 统计概览 -->
    <div class="stat-row">
      <div class="stat-card" style="animation-delay:0ms">
        <span class="stat-val">{{ statSummary.total }}</span>
        <span class="stat-label dim">全部记录</span>
      </div>
      <div class="stat-card stat-ok" style="animation-delay:60ms">
        <span class="stat-val">{{ statSummary.succeeded }}</span>
        <span class="stat-label dim">成功</span>
      </div>
      <div class="stat-card stat-err" style="animation-delay:120ms">
        <span class="stat-val">{{ statSummary.failed }}</span>
        <span class="stat-label dim">失败</span>
      </div>
      <div class="stat-card stat-api" style="animation-delay:180ms">
        <span class="stat-val">{{ statSummary.api }}</span>
        <span class="stat-label dim">API 触发</span>
      </div>
      <div class="stat-card stat-mq" style="animation-delay:240ms">
        <span class="stat-val">{{ statSummary.mq }}</span>
        <span class="stat-label dim">MQ 触发</span>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-input v-model="searchText" placeholder="搜索流程名 / API 名 / 执行 ID..." clearable class="filter-search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="filterSource" placeholder="全部触发源" clearable class="filter-select">
        <el-option value="http">
          <span class="src-dot src-http" style="margin-right:6px;vertical-align:middle" />HTTP API
        </el-option>
        <el-option value="stream">
          <span class="src-dot src-stream" style="margin-right:6px;vertical-align:middle" />流式 API
        </el-option>
        <el-option value="mq">
          <span class="src-dot src-mq" style="margin-right:6px;vertical-align:middle" />MQ 消息
        </el-option>
        <el-option value="manual">
          <span class="src-dot src-manual" style="margin-right:6px;vertical-align:middle" />手动触发
        </el-option>
      </el-select>
      <el-select v-model="filterStatus" placeholder="全部状态" clearable class="filter-select">
        <el-option label="成功" value="succeeded" />
        <el-option label="失败" value="failed" />
        <el-option label="运行中" value="running" />
        <el-option label="已取消" value="canceled" />
      </el-select>
    </div>

    <!-- 数据表格 -->
    <div class="table-wrap">
      <el-table
        v-loading="loading"
        :data="filteredRecords"
        class="pf-table"
        @row-click="openDetail"
        row-class-name="table-row"
      >
        <el-table-column label="触发源" width="130">
          <template #default="{ row }">
            <div class="src-cell">
              <span class="src-dot" :class="sourceClass[row.trigger_source || 'manual']" />
              <span class="src-text">{{ sourceLabel[row.trigger_source || 'manual'] || row.trigger_source }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="流程 / 接口" min-width="200">
          <template #default="{ row }">
            <div class="name-cell">
              <span class="name-primary">{{ row.api_name || row.flow_name || '未知流程' }}</span>
              <span class="name-sub dim" v-if="row.api_path">
                <el-icon size="10"><Link /></el-icon> /api/public/{{ row.api_path }}
              </span>
              <span class="name-sub dim" v-else-if="row.api_name && row.flow_name">
                <el-icon size="10"><Share /></el-icon> {{ row.flow_name }}
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="执行 ID" width="110">
          <template #default="{ row }">
            <code class="run-id">{{ shortId(row.id) }}</code>
          </template>
        </el-table-column>

        <el-table-column label="节点进度" width="130">
          <template #default="{ row }">
            <div v-if="row.node_total > 0" class="progress-cell">
              <div class="rp-bar">
                <div
                  class="rp-fill"
                  :class="row.status === 'failed' ? 'rp-fill-err' : ''"
                  :style="{ width: `${(row.node_done / row.node_total) * 100}%` }"
                />
              </div>
              <span class="dim prog-txt">{{ row.node_done }}/{{ row.node_total }}</span>
            </div>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="statusTypes[row.status] || 'info'" effect="dark" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="耗时" width="90">
          <template #default="{ row }">
            <span v-if="row.duration_ms != null" class="dur-val" :class="{ 'dur-slow': row.duration_ms > 5000 }">
              {{ fmtDuration(row.duration_ms) }}
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>

        <el-table-column label="时间" width="160">
          <template #default="{ row }">
            <span class="dim time-txt">{{ fmtTime(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && !filteredRecords.length"
        description="暂无符合条件的执行记录"
        :image-size="80"
        style="padding: 40px 0"
      />
    </div>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawer" size="560px" :with-header="true" class="detail-drawer">
      <template #header>
        <div class="drawer-head">
          <div class="drawer-title">
            <span class="src-dot" :class="sourceClass[selectedRun?.trigger_source || 'manual']" />
            <span class="drawer-run-name">{{ selectedRun?.api_name || selectedRun?.flow_name || '执行详情' }}</span>
            <el-tag :type="statusTypes[selectedRun?.status] || 'info'" size="small" effect="dark" style="margin-left:6px">
              {{ selectedRun?.status }}
            </el-tag>
          </div>
          <div class="drawer-meta">
            <span class="dim">⏱ {{ fmtDuration(selectedRun?.duration_ms ?? null) }}</span>
            <span class="dim">{{ fmtTime(selectedRun?.created_at) }}</span>
            <span class="dim">ID：<code class="run-id">{{ shortId(selectedRun?.id || '') }}</code></span>
          </div>
        </div>
      </template>

      <div v-loading="traceLoading" class="drawer-body">
        <template v-if="trace">
          <el-tabs v-model="activeTab" class="detail-tabs">
            <!-- 调用链路图 -->
            <el-tab-pane name="chain">
              <template #label>
                <span>🔗 调用链路图</span>
              </template>
              <div v-if="trace.call_chain" class="chain-tab-content">
                <CallChain :chain="trace.call_chain" />
              </div>
              <el-empty v-else description="无链路数据" :image-size="60" />
            </el-tab-pane>

            <!-- 入参 / 出参 -->
            <el-tab-pane name="io" label="入参 / 出参">
              <div class="io-section">
                <div class="io-block">
                  <div class="io-label">
                    <el-icon size="13"><Download /></el-icon>
                    入参（触发时传入）
                  </div>
                  <pre class="code-pre" v-if="trace.run?.inputs != null">{{ JSON.stringify(trace.run.inputs, null, 2) }}</pre>
                  <div class="io-empty dim" v-else>
                    <template v-if="selectedRun?.trigger_source === 'mq'">MQ 消息体数据请查看 MQ 监控</template>
                    <template v-else>暂无入参记录</template>
                  </div>
                </div>
                <div class="io-block">
                  <div class="io-label">
                    <el-icon size="13"><Upload /></el-icon>
                    出参（流程最终返回值）
                  </div>
                  <pre class="code-pre code-out" v-if="trace.run?.output != null">{{ JSON.stringify(trace.run.output, null, 2) }}</pre>
                  <div class="io-empty dim" v-else>暂无出参记录</div>
                </div>
              </div>
            </el-tab-pane>

            <!-- 节点步骤 -->
            <el-tab-pane name="steps">
              <template #label>
                节点步骤
                <el-badge
                  v-if="trace.steps?.some((s: any) => s.status === 'failed')"
                  value="!" type="danger" class="tab-badge"
                />
              </template>
              <div class="steps-list">
                <div
                  v-for="(step, i) in trace.steps"
                  :key="i"
                  class="step-item"
                  :style="{ animationDelay: `${i * 40}ms` }"
                >
                  <div class="step-header">
                    <div class="step-dot" :style="{ background: stepStatusColor[step.status] || '#94a3b8' }" />
                    <span class="step-name">{{ step.node_name || shortId(step.node_id) }}</span>
                    <el-tag size="small" :style="{ color: stepStatusColor[step.status] || '#94a3b8', borderColor: stepStatusColor[step.status] || '#94a3b8' }">
                      {{ step.status }}
                    </el-tag>
                    <span v-if="step.hit_port" class="dim step-port">→ {{ step.hit_port }}</span>
                    <span class="dim step-dur" v-if="step.duration_ms != null">{{ step.duration_ms }}ms</span>
                  </div>
                  <pre v-if="step.has_output && step.output != null" class="code-pre step-out">{{ JSON.stringify(step.output, null, 2) }}</pre>
                  <pre v-if="step.error" class="code-pre code-err">{{ step.error }}</pre>
                </div>
                <el-empty v-if="!trace.steps?.length" description="无步骤记录" :image-size="50" />
              </div>
            </el-tab-pane>

            <!-- 关联块执行 -->
            <el-tab-pane name="execs" v-if="trace.executions?.length">
              <template #label>
                关联块执行
                <el-badge :value="trace.executions.length" type="info" class="tab-badge" />
              </template>
              <div class="exec-list">
                <div
                  v-for="(ex, i) in trace.executions"
                  :key="ex.id"
                  class="exec-item"
                  :style="{ animationDelay: `${i * 40}ms` }"
                >
                  <div class="exec-head">
                    <el-tag :type="statusTypes[ex.status] || 'info'" size="small" effect="dark">{{ ex.status }}</el-tag>
                    <span class="exec-block-name" v-if="ex.block_name">{{ ex.block_name }}</span>
                    <code class="dim" style="font-size:11px">{{ shortId(ex.block_id) }}</code>
                    <span class="dim">{{ ex.duration_ms }}ms</span>
                  </div>
                  <div class="exec-io-row" v-if="ex.inputs && Object.keys(ex.inputs || {}).length">
                    <span class="io-label-sm">入参</span>
                    <pre class="code-pre">{{ JSON.stringify(ex.inputs, null, 2) }}</pre>
                  </div>
                  <div class="exec-io-row" v-if="ex.output != null">
                    <span class="io-label-sm">出参</span>
                    <pre class="code-pre code-out">{{ JSON.stringify(ex.output, null, 2) }}</pre>
                  </div>
                  <div class="exec-io-row" v-if="ex.stdout">
                    <span class="io-label-sm">stdout</span>
                    <pre class="code-pre code-log">{{ ex.stdout }}</pre>
                  </div>
                  <div class="exec-io-row" v-if="ex.stderr">
                    <span class="io-label-sm err-label">stderr</span>
                    <pre class="code-pre code-err">{{ ex.stderr }}</pre>
                  </div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
        <el-empty v-else-if="!traceLoading" description="暂无 trace 数据" :image-size="80" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
@keyframes slide-up {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.page-head {
  display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px;
}
.page-head h2 { margin: 0; font-size: 22px; }
.dim { color: var(--pf-text-dim); font-size: 13px; }

/* 统计概览 */
.stat-row { display: flex; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.stat-card {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 3px; padding: 12px 20px;
  background: var(--pf-panel); border: 1px solid var(--pf-border); border-radius: 10px;
  min-width: 90px; animation: slide-up 0.35s ease both; transition: transform 0.15s ease;
}
.stat-card:hover { transform: translateY(-2px); }
.stat-val { font-size: 22px; font-weight: 700; color: var(--pf-text); }
.stat-label { font-size: 11px; }
.stat-ok .stat-val { color: #22c55e; }
.stat-err .stat-val { color: #ef4444; }
.stat-api .stat-val { color: #818cf8; }
.stat-mq .stat-val { color: #fbbf24; }

/* 筛选栏 */
.filter-bar { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; animation: fade-in 0.4s ease both; }
.filter-search { flex: 1; min-width: 200px; }
.filter-select { width: 140px; }

/* 表格 */
.table-wrap {
  background: var(--pf-panel); border: 1px solid var(--pf-border);
  border-radius: 12px; overflow: hidden; animation: slide-up 0.4s ease both;
}
.pf-table { background: transparent; cursor: pointer; }
:deep(.table-row) { transition: background 0.15s ease; }
:deep(.table-row:hover > td) { background: var(--pf-panel-2) !important; }

.src-cell { display: flex; align-items: center; gap: 6px; }
.src-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.src-http    { background: #4f46e5; box-shadow: 0 0 6px rgba(79,70,229,0.5); }
.src-stream  { background: #0891b2; box-shadow: 0 0 6px rgba(8,145,178,0.5); }
.src-mq      { background: #f59e0b; box-shadow: 0 0 6px rgba(245,158,11,0.5); }
.src-manual  { background: #475569; }
.src-text { font-size: 12px; }

.name-cell { display: flex; flex-direction: column; gap: 2px; }
.name-primary { font-size: 13px; font-weight: 600; color: var(--pf-text); }
.name-sub { display: flex; align-items: center; gap: 3px; font-size: 11px; margin: 0; }

.run-id { color: var(--pf-accent); font-size: 12px; opacity: 0.85; }

.progress-cell { display: flex; align-items: center; gap: 6px; }
.rp-bar { flex: 1; height: 4px; background: var(--pf-border); border-radius: 2px; overflow: hidden; min-width: 40px; }
.rp-fill { height: 100%; background: linear-gradient(90deg, #4f46e5, #22c55e); border-radius: 2px; transition: width 0.6s ease; }
.rp-fill-err { background: #ef4444; }
.prog-txt { font-size: 11px; }
.dur-val { font-size: 12px; font-weight: 600; font-family: monospace; }
.dur-slow { color: #f59e0b; }
.time-txt { font-size: 12px; }

/* 抽屉 */
.drawer-head { display: flex; flex-direction: column; gap: 5px; }
.drawer-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; }
.drawer-run-name { color: var(--pf-text); }
.drawer-meta { display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--pf-text-dim); }

.drawer-body { display: flex; flex-direction: column; gap: 0; padding-bottom: 30px; }

.chain-tab-content { padding-top: 4px; }

.detail-tabs { animation: fade-in 0.4s ease both; }
.tab-badge { margin-left: 4px; }

/* 入参出参 */
.io-section { display: flex; flex-direction: column; gap: 14px; padding-top: 4px; }
.io-block { display: flex; flex-direction: column; gap: 6px; }
.io-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600; color: var(--pf-text-dim);
  text-transform: uppercase; letter-spacing: 0.5px;
}
.io-empty { font-size: 12px; padding: 10px 0; }

/* 节点步骤 */
.steps-list { display: flex; flex-direction: column; gap: 8px; padding-top: 4px; }
.step-item {
  padding: 10px 12px; background: var(--pf-panel-2); border-radius: 10px;
  border: 1px solid var(--pf-border); display: flex; flex-direction: column; gap: 6px;
  animation: slide-up 0.3s ease both;
}
.step-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.step-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.step-name { font-size: 13px; font-weight: 600; color: var(--pf-text); }
.step-port { font-size: 11px; }
.step-dur { font-size: 11px; font-family: monospace; margin-left: auto; }
.step-out { max-height: 150px; }

/* 块执行 */
.exec-list { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
.exec-item {
  padding: 10px 12px; background: var(--pf-panel-2); border-radius: 10px;
  border: 1px solid var(--pf-border); display: flex; flex-direction: column; gap: 8px;
  animation: slide-up 0.3s ease both;
}
.exec-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.exec-block-name { font-size: 13px; font-weight: 600; color: var(--pf-text); }
.exec-io-row { display: flex; flex-direction: column; gap: 4px; }
.io-label-sm { font-size: 11px; font-weight: 600; color: var(--pf-text-dim); text-transform: uppercase; letter-spacing: 0.5px; }
.err-label { color: #f87171 !important; }

/* 代码块 */
.code-pre {
  background: var(--pf-panel-2); border: 1px solid var(--pf-border);
  border-radius: 7px; padding: 10px 12px;
  font-family: monospace; font-size: 12px; line-height: 1.55;
  white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow-y: auto;
  color: var(--pf-text); scrollbar-width: thin;
}
.code-out { color: #4ade80; }
.code-log { color: var(--pf-text-dim); }
.code-err { color: #f87171; background: rgba(239,68,68,0.06); border-left: 2px solid #ef4444; }
</style>
