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

    <div class="grid-2">
      <!-- 最近整流链路 -->
      <div class="pf-card list-card">
        <div class="card-title"><el-icon><Share /></el-icon> 最近整流链路（点击查看 trace）</div>
        <transition-group name="list" tag="div" class="run-list">
          <div
            v-for="run in recentRuns"
            :key="run.id"
            class="run-item"
            @click="openTrace(run)"
          >
            <div class="run-head">
              <code class="run-id">{{ shortId(run.id) }}</code>
              <el-tag :type="runStatusType[run.status] || 'info'" size="small" effect="dark">{{ run.status }}</el-tag>
            </div>
            <div class="run-progress">
              <div class="rp-bar">
                <div
                  class="rp-fill"
                  :style="{ width: `${run.node_total ? (run.node_done / run.node_total) * 100 : 0}%` }"
                />
              </div>
              <span class="rp-text">{{ run.node_done }}/{{ run.node_total }} 节点</span>
            </div>
            <div class="run-meta dim">
              <span>{{ fmtTime(run.created_at) }}</span>
              <span v-if="run.owner_pod" class="run-pod">{{ run.owner_pod }}</span>
            </div>
          </div>
        </transition-group>
        <el-empty v-if="!recentRuns.length" description="暂无整流执行" :image-size="60" />
      </div>

      <!-- 最近单块执行 -->
      <div class="pf-card list-card">
        <div class="card-title"><el-icon><Histogram /></el-icon> 最近块执行</div>
        <el-table :data="recentExec" size="small" class="exec-table">
          <el-table-column label="块" min-width="110">
            <template #default="{ row }"><code>{{ shortId(row.block_id) }}</code></template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="execStatusType[row.status] || 'info'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">{{ row.duration_ms }}ms</template>
          </el-table-column>
          <el-table-column label="时间" min-width="150">
            <template #default="{ row }"><span class="dim">{{ fmtTime(row.created_at) }}</span></template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 链路 trace 抽屉 -->
    <el-drawer v-model="traceDrawer" size="560px" :with-header="true">
      <template #header>
        <div class="trace-head">
          <el-icon color="var(--pf-accent)"><Share /></el-icon>
          <span>链路 trace · {{ shortId(traceRunId) }}</span>
        </div>
      </template>
      <div v-loading="traceLoading" class="trace-body">
        <template v-if="trace">
          <div class="trace-summary">
            <el-tag :type="runStatusType[trace.run.status] || 'info'" effect="dark">{{ trace.run.status }}</el-tag>
            <span class="dim">flow: {{ shortId(trace.run.flow_id) }}</span>
            <span class="dim">fence: {{ trace.run.fence_token }}</span>
          </div>

          <div class="timeline">
            <div v-for="(step, i) in trace.steps" :key="i" class="tl-item" :style="{ animationDelay: `${i * 50}ms` }">
              <div class="tl-dot" :style="{ background: stepStatusColor[step.status] || '#94a3b8' }" />
              <div class="tl-content">
                <div class="tl-row">
                  <code>{{ shortId(step.node_id) }}</code>
                  <el-tag size="small" :style="{ color: stepStatusColor[step.status] }">{{ step.status }}</el-tag>
                  <span v-if="step.hit_port" class="dim">→ {{ step.hit_port }}</span>
                </div>
                <pre v-if="step.has_output" class="tl-output">{{ JSON.stringify(step.output, null, 2) }}</pre>
                <pre v-if="step.error" class="tl-error">{{ step.error }}</pre>
              </div>
            </div>
          </div>

          <div v-if="trace.executions?.length" class="trace-exec">
            <div class="card-title">关联块执行</div>
            <div v-for="ex in trace.executions" :key="ex.id" class="te-item">
              <el-tag :type="execStatusType[ex.status] || 'info'" size="small">{{ ex.status }}</el-tag>
              <code>{{ shortId(ex.block_id) }}</code>
              <span class="dim">{{ ex.duration_ms }}ms</span>
              <pre v-if="ex.stderr" class="tl-error">{{ ex.stderr }}</pre>
            </div>
          </div>
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

/* 两栏 */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 1100px) { .grid-2 { grid-template-columns: 1fr; } }
.list-card { padding: 16px 20px; animation: slide-up 0.55s ease both; }
.run-list { display: flex; flex-direction: column; gap: 8px; max-height: 420px; overflow-y: auto; }
.run-item {
  padding: 10px 12px; border-radius: 10px;
  background: var(--pf-panel-2); border: 1px solid var(--pf-border);
  cursor: pointer; transition: transform 0.15s ease, box-shadow 0.2s ease;
}
.run-item:hover { transform: translateX(3px); box-shadow: var(--pf-shadow-sm); }
.run-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.run-id { color: var(--pf-accent); font-size: 13px; }
.run-progress { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.rp-bar { flex: 1; height: 6px; background: var(--pf-border); border-radius: 3px; overflow: hidden; }
.rp-fill { height: 100%; background: linear-gradient(90deg, #4f46e5, #22c55e); border-radius: 3px; transition: width 0.6s ease; }
.rp-text { font-size: 11px; color: var(--pf-text-dim); white-space: nowrap; }
.run-meta { display: flex; gap: 12px; font-size: 11px; }
.run-pod { font-family: monospace; }

.exec-table { background: transparent; }

/* trace 抽屉 */
.trace-head { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.trace-body { display: flex; flex-direction: column; gap: 16px; }
.trace-summary { display: flex; align-items: center; gap: 12px; }
.timeline { display: flex; flex-direction: column; gap: 2px; position: relative; padding-left: 4px; }
.tl-item { display: flex; gap: 12px; animation: slide-up 0.3s ease both; }
.tl-dot {
  width: 12px; height: 12px; border-radius: 50%; margin-top: 4px; flex-shrink: 0;
  position: relative; z-index: 1;
}
.tl-item:not(:last-child) .tl-dot::after {
  content: ''; position: absolute; left: 50%; top: 12px; transform: translateX(-50%);
  width: 2px; height: calc(100% + 6px); background: var(--pf-border);
}
.tl-content { flex: 1; padding-bottom: 14px; min-width: 0; }
.tl-row { display: flex; align-items: center; gap: 8px; }
.tl-row code { color: var(--pf-accent); font-size: 12px; }
.tl-output, .tl-error {
  margin: 6px 0 0; padding: 8px 10px; border-radius: 6px;
  font-family: monospace; font-size: 11px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-all; max-height: 140px; overflow-y: auto;
}
.tl-output { background: var(--pf-panel-2); color: #4ade80; }
.tl-error { background: rgba(239,68,68,0.08); color: #f87171; }
.trace-exec { display: flex; flex-direction: column; gap: 8px; }
.te-item {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 10px; background: var(--pf-panel-2); border-radius: 8px;
}
.te-item code { color: var(--pf-accent); font-size: 12px; }

.list-enter-active, .list-leave-active { transition: all 0.3s ease; }
.list-enter-from { opacity: 0; transform: translateX(-10px); }
.list-leave-to { opacity: 0; transform: translateX(10px); }
</style>
