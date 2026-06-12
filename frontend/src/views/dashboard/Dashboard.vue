<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { dashboardApi } from '@/api'

const data = ref<any>(null)
const loading = ref(false)
const autoRefresh = ref(true)
const lastUpdated = ref(Date.now())
const nowTs = ref(Date.now())
let polling: ReturnType<typeof setInterval> | undefined
let clock: ReturnType<typeof setInterval> | undefined

// 链路 trace 抽屉
const traceDrawer = ref(false)
const traceLoading = ref(false)
const trace = ref<any>(null)
const traceRunId = ref('')

// 执行详情抽屉
const execDrawer = ref(false)
const execLoading = ref(false)
const execDetail = ref<any>(null)
const execActiveTab = ref('io')

async function load() {
  loading.value = true
  try {
    data.value = await dashboardApi.overview()
    lastUpdated.value = Date.now()
  } finally {
    loading.value = false
  }
}

async function openTrace(run: any) {
  traceRunId.value = run.id
  traceDrawer.value = true
  trace.value = null
  traceLoading.value = true
  try {
    trace.value = await dashboardApi.flowRunTrace(run.id)
  } finally {
    traceLoading.value = false
  }
}

async function openExecDetail(exec: any) {
  execDrawer.value = true
  execDetail.value = null
  execActiveTab.value = 'io'
  execLoading.value = true
  try {
    execDetail.value = await dashboardApi.execDetail(exec.id)
  } finally {
    execLoading.value = false
  }
}

function openTraceFromExec(flowRun: any) {
  execDrawer.value = false
  traceRunId.value = flowRun.id
  traceDrawer.value = true
  trace.value = {
    run: {
      id: flowRun.id,
      flow_id: flowRun.flow_id,
      flow_name: flowRun.flow_name,
      status: flowRun.status,
      owner_pod: null,
      fence_token: null,
      created_at: flowRun.created_at,
      finished_at: flowRun.finished_at,
    },
    steps: flowRun.steps || [],
    executions: [],
  }
  // 重新完整加载 trace
  traceLoading.value = true
  dashboardApi.flowRunTrace(flowRun.id).then((t: any) => {
    trace.value = t
  }).finally(() => {
    traceLoading.value = false
  })
}

const counts = computed(() => data.value?.counts || {})
const stats = computed(() => data.value?.exec_stats || {})
const trend = computed<any[]>(() => data.value?.exec_trend || [])
const deps = computed<Record<string, string>>(() => data.value?.deps || {})
const recentRuns = computed<any[]>(() => data.value?.recent_flow_runs || [])
const recentExec = computed<any[]>(() => data.value?.recent_executions || [])

const maxTrend = computed(() => Math.max(1, ...trend.value.map((t) => t.total)))

// 成功率环形进度
const ringDash = computed(() => {
  const rate = stats.value.success_rate ?? 100
  const c = 2 * Math.PI * 52
  return `${(rate / 100) * c} ${c}`
})
const rateColor = computed(() => {
  const r = stats.value.success_rate ?? 100
  if (r >= 99) return '#22c55e'
  if (r >= 90) return '#f59e0b'
  return '#ef4444'
})

const updatedAgo = computed(() => {
  const sec = Math.max(0, Math.floor((nowTs.value - lastUpdated.value) / 1000))
  if (sec < 5) return '刚刚更新'
  if (sec < 60) return `${sec}s 前更新`
  return `${Math.floor(sec / 60)}m 前更新`
})

const depMeta: Record<string, { label: string; icon: string }> = {
  postgres: { label: 'PostgreSQL', icon: 'Coin' },
  redis: { label: 'Redis', icon: 'Cpu' },
  rabbitmq: { label: 'RabbitMQ', icon: 'MessageBox' },
  minio: { label: 'MinIO', icon: 'FolderOpened' },
}

const runStatusType: Record<string, string> = {
  succeeded: 'success', running: 'warning', failed: 'danger', canceled: 'info',
}
const execStatusType: Record<string, string> = {
  success: 'success', running: 'warning', failed: 'danger', timeout: 'danger', pending: 'info',
}
const stepStatusColor: Record<string, string> = {
  done: '#22c55e', skipped: '#94a3b8', failed: '#ef4444', running: '#f59e0b',
}

function fmtTime(ts: string | null): string {
  if (!ts) return '-'
  const d = new Date(ts)
  return d.toLocaleString('zh-CN', { hour12: false })
}
function shortId(id: string): string {
  return (id || '').slice(0, 8)
}
function hourLabel(h: string): string {
  return (h || '').slice(11, 16)
}
function displayName(name: string, id: string): string {
  if (name) return `${name} · ${shortId(id)}`
  return shortId(id)
}

function tick() {
  if (autoRefresh.value && !document.hidden) load()
}

onMounted(() => {
  load()
  polling = setInterval(tick, 10000)
  clock = setInterval(() => (nowTs.value = Date.now()), 1000)
})
onUnmounted(() => {
  clearInterval(polling)
  clearInterval(clock)
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>链路监控看板</h2>
        <p class="dim">Python 调用链路总览 · 执行成功率 / 24h 趋势 / 整流链路 trace / 依赖连通性</p>
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
      </div>
    </header>

    <!-- 概览卡片 -->
    <div class="overview-row">
      <div class="pf-card ov-card" style="animation-delay:0ms">
        <div class="ov-icon blue"><el-icon size="22"><Grid /></el-icon></div>
        <div><span class="ov-val">{{ counts.blocks ?? 0 }}</span><span class="ov-label"> 调用块</span></div>
      </div>
      <div class="pf-card ov-card" style="animation-delay:60ms">
        <div class="ov-icon purple"><el-icon size="22"><Share /></el-icon></div>
        <div><span class="ov-val">{{ counts.flows ?? 0 }}</span><span class="ov-label"> 流程</span></div>
      </div>
      <div class="pf-card ov-card" style="animation-delay:120ms">
        <div class="ov-icon green"><el-icon size="22"><Promotion /></el-icon></div>
        <div><span class="ov-val">{{ counts.deployments_running ?? 0 }}</span><span class="ov-label"> 运行部署</span></div>
      </div>
      <div class="pf-card ov-card" style="animation-delay:180ms">
        <div class="ov-icon orange"><el-icon size="22"><Connection /></el-icon></div>
        <div><span class="ov-val">{{ counts.apis ?? 0 }}</span><span class="ov-label"> 发布接口</span></div>
      </div>
    </div>

    <!-- 执行统计 + 趋势 -->
    <div class="stats-row">
      <div class="pf-card rate-card">
        <div class="rate-ring">
          <svg viewBox="0 0 120 120" width="124" height="124">
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--pf-panel-2)" stroke-width="12" />
            <circle
              cx="60" cy="60" r="52" fill="none" :stroke="rateColor" stroke-width="12"
              stroke-linecap="round" :stroke-dasharray="ringDash" transform="rotate(-90 60 60)"
              class="ring-progress"
            />
            <text x="60" y="56" text-anchor="middle" class="ring-val" :fill="rateColor">
              {{ stats.success_rate ?? 100 }}%
            </text>
            <text x="60" y="76" text-anchor="middle" class="ring-sub">成功率</text>
          </svg>
        </div>
        <div class="rate-meta">
          <div class="rm-item"><span class="rm-label">24h 执行</span><span class="rm-val">{{ stats.total ?? 0 }}</span></div>
          <div class="rm-item"><span class="rm-label">成功</span><span class="rm-val ok">{{ stats.success ?? 0 }}</span></div>
          <div class="rm-item"><span class="rm-label">失败</span><span class="rm-val err">{{ stats.failed ?? 0 }}</span></div>
          <div class="rm-item"><span class="rm-label">平均耗时</span><span class="rm-val">{{ stats.avg_duration_ms ?? 0 }}ms</span></div>
        </div>
      </div>

      <div class="pf-card trend-card">
        <div class="card-title"><el-icon><Histogram /></el-icon> 最近 24h 执行趋势</div>
        <div class="trend-chart" v-if="trend.length">
          <div v-for="(t, i) in trend" :key="i" class="trend-col" :title="`${hourLabel(t.hour)} 执行 ${t.total} / 失败 ${t.failed}`">
            <div class="bar-wrap">
              <div
                class="bar"
                :style="{ height: `${(t.total / maxTrend) * 100}%`, animationDelay: `${i * 20}ms` }"
              >
                <div class="bar-fail" :style="{ height: `${t.total ? (t.failed / t.total) * 100 : 0}%` }" />
              </div>
            </div>
            <span class="bar-label" v-if="i % 3 === 0">{{ hourLabel(t.hour) }}</span>
            <span class="bar-label" v-else>&nbsp;</span>
          </div>
        </div>
        <el-empty v-else description="近 24h 暂无执行记录" :image-size="60" />
      </div>
    </div>

    <!-- 依赖连通性 -->
    <div class="pf-card deps-card">
      <div class="card-title"><el-icon><Link /></el-icon> 中间件依赖连通性</div>
      <div class="deps-row">
        <div
          v-for="(meta, key) in depMeta"
          :key="key"
          class="dep-item"
          :class="deps[key] === 'up' ? 'dep-up' : (deps[key] ? 'dep-down' : 'dep-unknown')"
        >
          <span class="dep-dot" />
          <el-icon><component :is="meta.icon" /></el-icon>
          <span class="dep-name">{{ meta.label }}</span>
          <span class="dep-state">{{ deps[key] || 'N/A' }}</span>
        </div>
      </div>
    </div>

    <!-- 调用记录（整流链路 + 发布 API 调用统一展示） -->
    <div class="pf-card calls-card">
      <div class="calls-head">
        <div class="card-title" style="margin-bottom:0"><el-icon><List /></el-icon> 调用记录（点击查看执行 trace）</div>
        <div class="calls-legend">
          <span class="legend-item"><span class="src-dot src-http" />HTTP</span>
          <span class="legend-item"><span class="src-dot src-stream" />Stream</span>
          <span class="legend-item"><span class="src-dot src-mq" />MQ</span>
          <span class="legend-item"><span class="src-dot src-manual" />手动</span>
        </div>
      </div>
      <transition-group name="list" tag="div" class="calls-list">
        <div
          v-for="(run, i) in recentRuns"
          :key="run.id"
          class="call-row"
          :style="{ animationDelay: `${i * 30}ms` }"
          @click="openTrace(run)"
        >
          <!-- 来源指示点 -->
          <div class="call-src">
            <span class="src-dot" :class="`src-${run.trigger_source || 'manual'}`" :title="run.trigger_source || 'manual'" />
          </div>
          <!-- API 名称 / Flow 名称 -->
          <div class="call-name">
            <span class="call-api-name" v-if="run.api_name">{{ run.api_name }}</span>
            <span class="call-api-name dim" v-else>{{ run.flow_name || '未知流程' }}</span>
            <span class="call-sub dim" v-if="run.api_path">
              <el-icon size="10"><Link /></el-icon> /api/public/{{ run.api_path }}
            </span>
            <span class="call-sub dim" v-else>
              <el-icon size="10"><Share /></el-icon> {{ run.flow_name }}
            </span>
          </div>
          <!-- 节点进度 -->
          <div class="call-nodes" v-if="run.node_total > 0">
            <div class="rp-bar-sm">
              <div
                class="rp-fill-sm"
                :class="run.status === 'failed' ? 'rp-fill-err' : ''"
                :style="{ width: `${run.node_total ? (run.node_done / run.node_total) * 100 : 100}%` }"
              />
            </div>
            <span class="call-node-txt dim">{{ run.node_done }}/{{ run.node_total }}</span>
          </div>
          <div class="call-nodes dim" v-else>—</div>
          <!-- 耗时 -->
          <div class="call-dur">
            <span v-if="run.duration_ms != null" class="dur-val" :class="run.duration_ms > 5000 ? 'dur-slow' : ''">
              {{ run.duration_ms >= 1000 ? (run.duration_ms / 1000).toFixed(1) + 's' : run.duration_ms + 'ms' }}
            </span>
            <span v-else class="dim">—</span>
          </div>
          <!-- 状态 -->
          <div class="call-status">
            <el-tag :type="runStatusType[run.status] || 'info'" size="small" effect="dark">{{ run.status }}</el-tag>
          </div>
          <!-- 时间 -->
          <div class="call-time dim">{{ fmtTime(run.created_at) }}</div>
        </div>
      </transition-group>
      <el-empty v-if="!recentRuns.length" description="暂无调用记录" :image-size="60" />
    </div>

    <!-- 链路 trace 抽屉 -->
    <el-drawer v-model="traceDrawer" size="600px" :with-header="true">
      <template #header>
        <div class="trace-head">
          <el-icon color="var(--pf-accent)"><Share /></el-icon>
          <span>
            链路 trace ·
            <span v-if="trace?.run?.flow_name" class="trace-flow-name">{{ trace.run.flow_name }}</span>
            <code class="trace-run-id">{{ shortId(traceRunId) }}</code>
          </span>
        </div>
      </template>
      <div v-loading="traceLoading" class="trace-body">
        <template v-if="trace">
          <div class="trace-summary">
            <el-tag :type="runStatusType[trace.run.status] || 'info'" effect="dark">{{ trace.run.status }}</el-tag>
            <span class="dim">flow: {{ displayName(trace.run.flow_name, trace.run.flow_id) }}</span>
            <span class="dim" v-if="trace.run.fence_token != null">fence: {{ trace.run.fence_token }}</span>
            <span class="dim" v-if="trace.run.finished_at">
              耗时: {{ Math.round((new Date(trace.run.finished_at).getTime() - new Date(trace.run.created_at).getTime())) }}ms
            </span>
          </div>

          <div class="timeline">
            <div v-for="(step, i) in trace.steps" :key="i" class="tl-item" :style="{ animationDelay: `${i * 50}ms` }">
              <div
                class="tl-dot"
                :class="{ 'tl-dot-fail': step.status === 'failed' }"
                :style="{ background: step.status === 'failed' ? '#ef4444' : (stepStatusColor[step.status] || '#94a3b8') }"
              >
                <span v-if="step.status === 'failed'" class="tl-dot-x">✕</span>
              </div>
              <div class="tl-content">
                <div class="tl-row">
                  <code>{{ shortId(step.node_id) }}</code>
                  <el-tag size="small" :style="{ color: stepStatusColor[step.status] || '#94a3b8', borderColor: stepStatusColor[step.status] || '#94a3b8' }">{{ step.status }}</el-tag>
                  <span v-if="step.hit_port" class="dim">→ {{ step.hit_port }}</span>
                  <span v-if="step.status === 'failed'" class="fail-label">执行失败</span>
                </div>
                <pre v-if="step.has_output" class="tl-output">{{ JSON.stringify(step.output, null, 2) }}</pre>
                <pre v-if="step.error" class="tl-error">{{ step.error }}</pre>
              </div>
            </div>
          </div>

          <div v-if="trace.executions?.length" class="trace-exec">
            <div class="card-title">关联块执行</div>
            <div v-for="ex in trace.executions" :key="ex.id" class="te-item">
              <div class="te-item-head">
                <el-tag :type="execStatusType[ex.status] || 'info'" size="small" effect="dark">{{ ex.status }}</el-tag>
                <span class="te-block-name" v-if="ex.block_name">{{ ex.block_name }}</span>
                <code class="te-block-id">{{ shortId(ex.block_id) }}</code>
                <span class="dim">{{ ex.duration_ms }}ms</span>
              </div>
              <div v-if="ex.inputs && Object.keys(ex.inputs || {}).length" class="te-io-section">
                <span class="te-io-label">入参</span>
                <pre class="tl-output">{{ JSON.stringify(ex.inputs, null, 2) }}</pre>
              </div>
              <div v-if="ex.output != null" class="te-io-section">
                <span class="te-io-label">出参</span>
                <pre class="tl-output">{{ JSON.stringify(ex.output, null, 2) }}</pre>
              </div>
              <div v-if="ex.stdout" class="te-io-section">
                <span class="te-io-label">stdout</span>
                <pre class="tl-log">{{ ex.stdout }}</pre>
              </div>
              <div v-if="ex.stderr" class="te-io-section">
                <span class="te-io-label err-label">stderr</span>
                <pre class="tl-error">{{ ex.stderr }}</pre>
              </div>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 执行详情抽屉 -->
    <el-drawer v-model="execDrawer" size="600px" :with-header="true" class="exec-drawer">
      <template #header>
        <div class="trace-head">
          <el-icon color="var(--pf-accent)"><Histogram /></el-icon>
          <span>
            执行详情 ·
            <span v-if="execDetail?.block_name" class="trace-flow-name">{{ execDetail.block_name }}</span>
            <code class="trace-run-id">{{ shortId(execDetail?.id || '') }}</code>
          </span>
        </div>
      </template>
      <div v-loading="execLoading" class="trace-body">
        <template v-if="execDetail">
          <!-- 基础信息 -->
          <div class="exec-info-row">
            <el-tag :type="execStatusType[execDetail.status] || 'info'" effect="dark">{{ execDetail.status }}</el-tag>
            <span class="dim">{{ execDetail.duration_ms != null ? execDetail.duration_ms + 'ms' : '-' }}</span>
            <span class="dim">{{ fmtTime(execDetail.created_at) }}</span>
            <span class="dim" v-if="execDetail.login_id">by {{ execDetail.login_id }}</span>
          </div>

          <!-- 关联整流 -->
          <div v-if="execDetail.flow_run_id" class="exec-flow-link" @click="openTraceFromExec(execDetail.flow_run)">
            <el-icon><Share /></el-icon>
            <span>关联整流：</span>
            <span v-if="execDetail.flow_run?.flow_name" class="link-name">{{ execDetail.flow_run.flow_name }}</span>
            <code>{{ shortId(execDetail.flow_run_id) }}</code>
            <el-tag :type="runStatusType[execDetail.flow_run?.status] || 'info'" size="small">{{ execDetail.flow_run?.status }}</el-tag>
            <span class="link-hint dim">点击查看完整链路</span>
          </div>

          <!-- tabs -->
          <el-tabs v-model="execActiveTab" class="exec-tabs">
            <el-tab-pane label="入参 / 出参" name="io">
              <div class="io-section">
                <div class="io-block">
                  <div class="io-label">入参 (inputs)</div>
                  <pre class="tl-output io-pre" v-if="execDetail.inputs != null">{{ JSON.stringify(execDetail.inputs, null, 2) }}</pre>
                  <div class="dim io-empty" v-else>无入参</div>
                </div>
                <div class="io-block">
                  <div class="io-label">出参 (output)</div>
                  <pre class="tl-output io-pre" v-if="execDetail.output != null">{{ JSON.stringify(execDetail.output, null, 2) }}</pre>
                  <div class="dim io-empty" v-else>无出参</div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane name="logs">
              <template #label>
                <span>执行日志</span>
                <el-badge v-if="execDetail.stderr" value="!" type="danger" class="log-badge" />
              </template>
              <div class="log-section">
                <div v-if="execDetail.stdout" class="log-block">
                  <div class="io-label">stdout</div>
                  <pre class="tl-log log-pre">{{ execDetail.stdout }}</pre>
                </div>
                <div v-if="execDetail.stderr" class="log-block">
                  <div class="io-label err-label">stderr</div>
                  <pre class="tl-error log-pre">{{ execDetail.stderr }}</pre>
                </div>
                <el-empty v-if="!execDetail.stdout && !execDetail.stderr" description="无执行日志" :image-size="50" />
              </div>
            </el-tab-pane>

            <el-tab-pane v-if="execDetail.flow_run" label="链路 trace" name="trace">
              <div class="inline-trace">
                <div class="trace-summary" style="margin-bottom: 12px">
                  <el-tag :type="runStatusType[execDetail.flow_run.status] || 'info'" effect="dark">{{ execDetail.flow_run.status }}</el-tag>
                  <span class="dim">flow: {{ displayName(execDetail.flow_run.flow_name, execDetail.flow_run.flow_id) }}</span>
                </div>
                <div class="timeline">
                  <div v-for="(step, i) in execDetail.flow_run.steps" :key="i" class="tl-item" :style="{ animationDelay: `${i * 50}ms` }">
                    <div
                      class="tl-dot"
                      :class="{ 'tl-dot-fail': step.status === 'failed' }"
                      :style="{ background: step.status === 'failed' ? '#ef4444' : (stepStatusColor[step.status] || '#94a3b8') }"
                    >
                      <span v-if="step.status === 'failed'" class="tl-dot-x">✕</span>
                    </div>
                    <div class="tl-content">
                      <div class="tl-row">
                        <code>{{ shortId(step.node_id) }}</code>
                        <el-tag size="small" :style="{ color: stepStatusColor[step.status] || '#94a3b8', borderColor: stepStatusColor[step.status] || '#94a3b8' }">{{ step.status }}</el-tag>
                        <span v-if="step.hit_port" class="dim">→ {{ step.hit_port }}</span>
                        <span v-if="step.status === 'failed'" class="fail-label">执行失败</span>
                      </div>
                      <pre v-if="step.has_output" class="tl-output">{{ JSON.stringify(step.output, null, 2) }}</pre>
                      <pre v-if="step.error" class="tl-error">{{ step.error }}</pre>
                    </div>
                  </div>
                </div>
                <div class="trace-open-full" @click="openTraceFromExec(execDetail.flow_run)">
                  <el-icon><Share /></el-icon> 查看完整整流链路（含关联块执行日志）
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
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
.head-actions { display: flex; gap: 8px; align-items: center; }
.auto-refresh {
  display: flex; align-items: center; gap: 6px;
  padding-right: 10px; border-right: 1px solid var(--pf-border);
}
.ar-label { margin: 0; }
.ar-time { margin: 0; min-width: 76px; }

@keyframes slide-up {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 概览 */
.overview-row { display: flex; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
.ov-card {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 20px; min-width: 160px; flex: 1;
  animation: slide-up 0.35s ease both;
}
.ov-icon {
  width: 40px; height: 40px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.ov-icon.blue   { background: rgba(8,145,178,0.12); color: #0891b2; }
.ov-icon.purple { background: rgba(124,58,237,0.12); color: #7c3aed; }
.ov-icon.green  { background: rgba(34,197,94,0.12); color: #22c55e; }
.ov-icon.orange { background: rgba(245,158,11,0.12); color: #f59e0b; }
.ov-val { font-size: 24px; font-weight: 700; }
.ov-label { font-size: 13px; color: var(--pf-text-dim); }

.card-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; margin-bottom: 14px;
}

/* 统计行 */
.stats-row { display: flex; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
.rate-card {
  display: flex; align-items: center; gap: 20px; padding: 18px 22px;
  min-width: 320px; animation: slide-up 0.4s ease both;
}
.ring-progress { transition: stroke-dasharray 0.8s cubic-bezier(0.4,0,0.2,1); }
.ring-val { font-size: 20px; font-weight: 700; }
.ring-sub { font-size: 11px; fill: var(--pf-text-dim); }
.rate-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 22px; }
.rm-item { display: flex; flex-direction: column; gap: 2px; }
.rm-label { font-size: 11px; color: var(--pf-text-dim); }
.rm-val { font-size: 17px; font-weight: 700; }
.rm-val.ok { color: #22c55e; }
.rm-val.err { color: #ef4444; }

.trend-card { flex: 1; min-width: 360px; padding: 18px 22px; animation: slide-up 0.45s ease both; }
.trend-chart { display: flex; align-items: flex-end; gap: 3px; height: 130px; }
.trend-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
.bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; }
.bar {
  width: 100%; min-height: 2px;
  background: linear-gradient(180deg, var(--pf-accent), rgba(79,70,229,0.35));
  border-radius: 3px 3px 0 0;
  position: relative; display: flex; flex-direction: column; justify-content: flex-start;
  animation: bar-grow 0.5s ease both; transform-origin: bottom;
}
@keyframes bar-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
.bar-fail { width: 100%; background: #ef4444; border-radius: 3px 3px 0 0; }
.bar-label { font-size: 9px; color: var(--pf-text-dim); margin-top: 4px; height: 12px; }

/* 依赖 */
.deps-card { padding: 16px 22px; margin-bottom: 16px; animation: slide-up 0.5s ease both; }
.deps-row { display: flex; gap: 12px; flex-wrap: wrap; }
.dep-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px; border-radius: 10px;
  background: var(--pf-panel-2); border: 1px solid var(--pf-border);
  transition: transform 0.2s ease;
}
.dep-item:hover { transform: translateY(-2px); }
.dep-dot { width: 8px; height: 8px; border-radius: 50%; }
.dep-up .dep-dot { background: #22c55e; box-shadow: 0 0 8px #22c55e; animation: pulse 2s infinite; }
.dep-down .dep-dot { background: #ef4444; }
.dep-unknown .dep-dot { background: #94a3b8; }
.dep-up .dep-state { color: #22c55e; }
.dep-down .dep-state { color: #ef4444; }
.dep-name { font-size: 13px; font-weight: 600; }
.dep-state { font-size: 12px; text-transform: uppercase; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

/* 调用记录表格 */
.calls-card { padding: 16px 20px; animation: slide-up 0.55s ease both; }
.calls-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.calls-legend { display: flex; gap: 12px; align-items: center; }
.legend-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--pf-text-dim); }
.calls-list {
  display: flex; flex-direction: column; gap: 0;
  max-height: 500px; overflow-y: auto;
  border: 1px solid var(--pf-border); border-radius: 10px; overflow: hidden;
}
.call-row {
  display: grid;
  grid-template-columns: 20px 1fr 110px 72px 88px 140px;
  align-items: center; gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--pf-border);
  cursor: pointer;
  transition: background 0.15s ease;
  animation: slide-up 0.3s ease both;
}
.call-row:last-child { border-bottom: none; }
.call-row:hover { background: var(--pf-panel-2); }

/* 来源点 */
.call-src { display: flex; align-items: center; justify-content: center; }
.src-dot {
  width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex-shrink: 0;
}
.src-http    { background: #4f46e5; box-shadow: 0 0 5px rgba(79,70,229,0.5); }
.src-stream  { background: #0891b2; box-shadow: 0 0 5px rgba(8,145,178,0.5); }
.src-mq      { background: #f59e0b; box-shadow: 0 0 5px rgba(245,158,11,0.5); }
.src-manual  { background: #94a3b8; }

/* 名称 */
.call-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.call-api-name {
  font-size: 13px; font-weight: 600; color: var(--pf-text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.call-sub {
  display: flex; align-items: center; gap: 3px;
  font-size: 11px; margin: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* 节点进度 */
.call-nodes { display: flex; align-items: center; gap: 6px; }
.rp-bar-sm { flex: 1; height: 4px; background: var(--pf-border); border-radius: 2px; overflow: hidden; min-width: 40px; }
.rp-fill-sm { height: 100%; background: linear-gradient(90deg, #4f46e5, #22c55e); border-radius: 2px; transition: width 0.6s ease; }
.rp-fill-err { background: #ef4444; }
.call-node-txt { font-size: 11px; white-space: nowrap; }

/* 耗时 */
.call-dur { text-align: right; }
.dur-val { font-size: 12px; font-weight: 600; color: var(--pf-text); font-family: monospace; }
.dur-slow { color: #f59e0b; }

/* 状态 */
.call-status { display: flex; justify-content: center; }

/* 时间 */
.call-time { font-size: 11px; text-align: right; }

/* trace 抽屉 */
.trace-head { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.trace-flow-name { color: var(--pf-text); font-weight: 600; margin-right: 4px; }
.trace-run-id { color: var(--pf-accent); font-size: 13px; opacity: 0.8; }
.trace-body { display: flex; flex-direction: column; gap: 16px; }
.trace-summary { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.timeline { display: flex; flex-direction: column; gap: 2px; position: relative; padding-left: 4px; }
.tl-item { display: flex; gap: 12px; animation: slide-up 0.3s ease both; }
.tl-dot {
  width: 14px; height: 14px; border-radius: 50%; margin-top: 3px; flex-shrink: 0;
  position: relative; z-index: 1;
  display: flex; align-items: center; justify-content: center;
}
.tl-dot-fail {
  box-shadow: 0 0 0 3px rgba(239,68,68,0.25);
  animation: fail-pulse 1.5s ease infinite;
}
@keyframes fail-pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(239,68,68,0.25); }
  50% { box-shadow: 0 0 0 5px rgba(239,68,68,0.1); }
}
.tl-dot-x { font-size: 9px; color: #fff; font-weight: 700; line-height: 1; }
.tl-item:not(:last-child) .tl-dot::after {
  content: ''; position: absolute; left: 50%; top: 14px; transform: translateX(-50%);
  width: 2px; height: calc(100% + 4px); background: var(--pf-border);
}
.tl-content { flex: 1; padding-bottom: 14px; min-width: 0; }
.tl-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tl-row code { color: var(--pf-accent); font-size: 12px; }
.fail-label { font-size: 11px; color: #ef4444; font-weight: 600; animation: slide-up 0.2s ease both; }
.tl-output, .tl-error, .tl-log {
  margin: 6px 0 0; padding: 8px 10px; border-radius: 6px;
  font-family: monospace; font-size: 11px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-all; max-height: 180px; overflow-y: auto;
}
.tl-output { background: var(--pf-panel-2); color: #4ade80; }
.tl-error { background: rgba(239,68,68,0.08); color: #f87171; border-left: 2px solid #ef4444; }
.tl-log { background: var(--pf-panel-2); color: var(--pf-text-dim); }

.trace-exec { display: flex; flex-direction: column; gap: 12px; }
.te-item {
  padding: 10px 12px; background: var(--pf-panel-2); border-radius: 10px;
  border: 1px solid var(--pf-border);
  display: flex; flex-direction: column; gap: 8px;
  animation: slide-up 0.25s ease both;
}
.te-item-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.te-block-name { font-size: 13px; font-weight: 600; color: var(--pf-text); }
.te-block-id { color: var(--pf-accent); font-size: 12px; opacity: 0.7; }
.te-io-section { display: flex; flex-direction: column; gap: 4px; }
.te-io-label { font-size: 11px; font-weight: 600; color: var(--pf-text-dim); text-transform: uppercase; letter-spacing: 0.5px; }
.err-label { color: #f87171 !important; }

/* 执行详情抽屉 */
.exec-info-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding-bottom: 4px; }
.exec-flow-link {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; border-radius: 10px;
  background: rgba(79,70,229,0.08); border: 1px solid rgba(79,70,229,0.2);
  cursor: pointer; transition: background 0.2s ease, transform 0.15s ease;
  font-size: 13px; flex-wrap: wrap;
}
.exec-flow-link:hover { background: rgba(79,70,229,0.14); transform: translateY(-1px); }
.link-name { font-weight: 600; color: var(--pf-text); }
.exec-flow-link code { color: var(--pf-accent); font-size: 12px; }
.link-hint { font-size: 11px; margin-left: auto; }

.exec-tabs { --el-tabs-header-height: 36px; }
.io-section { display: flex; flex-direction: column; gap: 14px; }
.io-block { display: flex; flex-direction: column; gap: 6px; }
.io-label { font-size: 12px; font-weight: 600; color: var(--pf-text-dim); text-transform: uppercase; letter-spacing: 0.5px; }
.io-pre { max-height: 220px; }
.io-empty { font-size: 12px; padding: 10px 0; }
.log-section { display: flex; flex-direction: column; gap: 12px; }
.log-block { display: flex; flex-direction: column; gap: 6px; }
.log-pre { max-height: 300px; }
.log-badge { margin-left: 6px; vertical-align: middle; }

.inline-trace { display: flex; flex-direction: column; gap: 12px; }
.trace-open-full {
  display: flex; align-items: center; gap: 6px;
  padding: 10px 14px; border-radius: 8px;
  background: rgba(79,70,229,0.08); border: 1px dashed rgba(79,70,229,0.3);
  color: var(--pf-accent); font-size: 13px; cursor: pointer;
  transition: background 0.2s ease;
}
.trace-open-full:hover { background: rgba(79,70,229,0.14); }

.list-enter-active, .list-leave-active { transition: all 0.3s ease; }
.list-enter-from { opacity: 0; transform: translateX(-10px); }
.list-leave-to { opacity: 0; transform: translateX(10px); }
</style>
