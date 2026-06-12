<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiPortalApi, type PublishedApi } from '@/api'

const apis = ref<PublishedApi[]>([])
const loading = ref(false)
const searchQuery = ref('')
const docsDrawerVisible = ref(false)
const selectedApi = ref<PublishedApi | null>(null)
const docsData = ref<any>(null)
const docsLoading = ref(false)

// ── 在线测试 ─────────────────────────────────────────
const testPanelOpen = ref(false)
const testPayload = ref('{\n  "inputs": {}\n}')
const testResult = ref<{ status: number; data: any; elapsed: number } | null>(null)
const testRunning = ref(false)
const testError = ref('')

async function runTest() {
  if (!selectedApi.value) return
  testRunning.value = true
  testResult.value = null
  testError.value = ''
  let payload: any = {}
  try {
    payload = JSON.parse(testPayload.value || '{}')
  } catch {
    testError.value = '请求体 JSON 格式有误'
    testRunning.value = false
    return
  }
  const t0 = Date.now()
  try {
    // path 去掉前缀斜杠，对齐 invoke API
    const apiPath = (selectedApi.value.path || '').replace(/^\//, '')
    const resp = await apiPortalApi.invoke(apiPath, payload)
    testResult.value = { status: resp.status, data: resp.data, elapsed: Date.now() - t0 }
  } catch (e: any) {
    testError.value = e?.message || '调用失败'
  } finally {
    testRunning.value = false
  }
}

async function load() {
  loading.value = true
  try {
    apis.value = await apiPortalApi.browse()
  } finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return apis.value
  return apis.value.filter(
    (a) =>
      a.name.toLowerCase().includes(q) ||
      a.path.toLowerCase().includes(q) ||
      (a.description || '').toLowerCase().includes(q) ||
      (a.remarks || '').toLowerCase().includes(q) ||
      (a.tags || '').toLowerCase().includes(q),
  )
})

async function openDocs(api: PublishedApi, openTest = false) {
  selectedApi.value = api
  docsDrawerVisible.value = true
  testPanelOpen.value = openTest
  testResult.value = null
  testError.value = ''
  docsLoading.value = true
  docsData.value = null
  try {
    docsData.value = await apiPortalApi.getDocs(api.id)
  } finally {
    docsLoading.value = false
  }
}

async function copyPath(api: PublishedApi) {
  const url = `${window.location.origin}${api.invoke_path}`
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('调用地址已复制')
  } catch {
    ElMessage.warning(`请手动复制：${url}`)
  }
}

function tagList(api: PublishedApi) {
  return (api.tags || '').split(',').map((t) => t.trim()).filter(Boolean)
}

function statusIcon(status: string) {
  return { active: '●', paused: '◎', deprecated: '×' }[status] ?? '●'
}

function statusColor(status: string) {
  return { active: 'var(--pf-green)', paused: 'var(--pf-amber)', deprecated: 'var(--pf-red)' }[status] ?? '#6b7280'
}

function triggerBadge(t: string) {
  return { http: { label: 'HTTP', color: '#2563eb' }, mq: { label: 'MQ', color: '#7c3aed' }, both: { label: 'HTTP+MQ', color: '#0891b2' } }[t] ?? { label: t, color: '#6b7280' }
}

function successRate(api: PublishedApi) {
  return api.total_calls > 0 ? ((api.success_calls / api.total_calls) * 100).toFixed(1) + '%' : '—'
}

function fmtDate(s?: string) {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', year: '2-digit' })
}

const testStatusColor = computed(() => {
  const s = testResult.value?.status
  if (!s) return '#6b7280'
  if (s < 300) return 'var(--pf-green)'
  if (s < 500) return 'var(--pf-amber)'
  return 'var(--pf-red)'
})

onMounted(load)
</script>

<template>
  <div class="portal-page">
    <!-- ── 页头 ──────────────────────────────────────── -->
    <header class="portal-head">
      <div>
        <h2 class="portal-title">接口门户</h2>
        <p class="portal-sub">浏览平台已发布的开放接口，查看文档与调用规范</p>
      </div>
      <el-input
        v-model="searchQuery"
        placeholder="搜索接口名、URI、文档..."
        clearable
        style="width: 300px"
        class="portal-search"
      >
        <template #prefix>
          <el-icon style="color:#9ca3af"><Search /></el-icon>
        </template>
      </el-input>
    </header>

    <!-- ── 统计条 ─────────────────────────────────────── -->
    <div v-if="!loading" class="portal-stats">
      <span class="ps-item"><span class="ps-num">{{ apis.length }}</span> 个接口</span>
      <span class="ps-dot">·</span>
      <span class="ps-item">
        <span class="ps-dot-green">●</span>
        <span class="ps-num">{{ apis.filter(a => a.status === 'active').length }}</span> 个运行中
      </span>
      <template v-if="searchQuery && filtered.length !== apis.length">
        <span class="ps-dot">·</span>
        <span class="ps-item">匹配 <span class="ps-num">{{ filtered.length }}</span> 个</span>
      </template>
    </div>

    <!-- ── 卡片网格 ───────────────────────────────────── -->
    <div v-loading="loading" class="portal-grid-wrap">
      <transition-group name="pf-card-list" tag="div" class="portal-grid">
        <article
          v-for="api in filtered"
          :key="api.id"
          class="api-card pf-card"
        >
          <!-- 卡片顶部：方法徽章 + 状态 + 触发类型 -->
          <div class="card-top">
            <span class="method-badge">POST</span>
            <span class="status-dot" :style="{ color: statusColor(api.status) }">
              {{ statusIcon(api.status) }} {{ { active:'运行中', paused:'暂停', deprecated:'废弃' }[api.status] ?? api.status }}
            </span>
            <span
              class="trigger-pill"
              :style="{ background: triggerBadge(api.trigger_type).color + '18', color: triggerBadge(api.trigger_type).color, borderColor: triggerBadge(api.trigger_type).color + '40' }"
            >{{ triggerBadge(api.trigger_type).label }}</span>
            <span v-if="api.encryption_enabled" class="enc-pill">
              <el-icon style="font-size:10px"><Lock /></el-icon> 加密
            </span>
          </div>

          <!-- 接口名 + 描述 -->
          <div class="card-name">{{ api.name }}</div>
          <p class="card-desc">{{ api.description || '暂无描述' }}</p>

          <!-- URI 路径（完整展示，横向滚动） -->
          <div class="card-uri">
            <code class="uri-code">{{ api.invoke_path || `/lhy-styon-pyflow/api/public/${api.path}` }}</code>
            <button class="uri-copy-btn" @click.stop="copyPath(api)" title="复制地址">
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>

          <!-- 元信息行 -->
          <div class="card-meta">
            <span class="meta-item" v-if="api.total_calls >= 0">
              <el-icon><Histogram /></el-icon>
              {{ api.total_calls.toLocaleString() }} 次
            </span>
            <span class="meta-item" v-if="api.total_calls > 0">
              <el-icon><TrendCharts /></el-icon>
              {{ successRate(api) }}
            </span>
            <span class="meta-item" v-if="api.avg_latency_ms > 0">
              <el-icon><Timer /></el-icon>
              {{ api.avg_latency_ms.toFixed(0) }}ms
            </span>
          </div>

          <!-- 标签 -->
          <div v-if="tagList(api).length" class="card-tags">
            <span v-for="tag in tagList(api)" :key="tag" class="tag-chip">{{ tag }}</span>
          </div>

          <!-- 卡片底部按钮 -->
          <div class="card-footer">
            <button class="card-btn card-btn-test" @click="openDocs(api, true)">
              <el-icon><VideoPlay /></el-icon> 测试
            </button>
            <button class="card-btn card-btn-docs" @click="openDocs(api, false)">
              <el-icon><Document /></el-icon> 查看文档
            </button>
          </div>

          <!-- hover 边框光效 -->
          <div class="card-shine" />
        </article>
      </transition-group>

      <el-empty
        v-if="!loading && filtered.length === 0"
        :description="searchQuery ? '未找到匹配的接口' : '暂无可用接口'"
        style="margin: 80px 0"
      />
    </div>

    <!-- ── 文档 + 测试 Drawer ────────────────────────── -->
    <el-drawer
      v-model="docsDrawerVisible"
      :title="selectedApi?.name || '接口文档'"
      size="640px"
      direction="rtl"
      class="api-drawer"
      @close="testResult = null"
    >
      <div v-loading="docsLoading" class="drawer-body">
        <template v-if="docsData">

          <!-- ① 基本信息 -->
          <section class="ds">
            <div class="ds-title"><el-icon><InfoFilled /></el-icon>基本信息</div>
            <div class="info-grid">
              <div class="ig-row">
                <span class="ig-label">接口名称</span>
                <span class="ig-val fw">{{ docsData.name }}</span>
              </div>
              <div class="ig-row">
                <span class="ig-label">调用地址</span>
                <div class="ig-uri">
                  <span class="method-badge-sm">POST</span>
                  <code class="uri-full">{{ docsData.invoke_path || docsData.path }}</code>
                  <button class="copy-xs" @click="copyPath(selectedApi!)"><el-icon><CopyDocument /></el-icon></button>
                </div>
              </div>
              <div class="ig-row">
                <span class="ig-label">状态</span>
                <span :style="{ color: statusColor(docsData.status), fontWeight: 600 }">
                  {{ statusIcon(docsData.status) }} {{ ({ active:'运行中', paused:'已暂停', deprecated:'已废弃' } as Record<string,string>)[docsData.status] ?? docsData.status }}
                </span>
              </div>
              <div class="ig-row">
                <span class="ig-label">触发方式</span>
                <span
                  class="trigger-pill"
                  :style="{ background: triggerBadge(docsData.trigger_type).color + '18', color: triggerBadge(docsData.trigger_type).color, borderColor: triggerBadge(docsData.trigger_type).color + '40' }"
                >{{ triggerBadge(docsData.trigger_type).label }}</span>
              </div>
              <div class="ig-row" v-if="docsData.description">
                <span class="ig-label">描述</span>
                <span class="ig-val">{{ docsData.description }}</span>
              </div>
              <div class="ig-row">
                <span class="ig-label">加密保护</span>
                <span>
                  <span v-if="docsData.encryption_enabled" style="color:#d97706;font-weight:600">
                    <el-icon><Lock /></el-icon> AES-256-GCM
                    <span v-if="docsData.require_encrypted_request" style="font-size:12px;color:#6b7280">（强制加密请求）</span>
                  </span>
                  <span v-else style="color:#6b7280">明文传输</span>
                </span>
              </div>
              <div class="ig-row" v-if="docsData.flow_name">
                <span class="ig-label">关联流程</span>
                <span class="ig-val"><el-icon><Connection /></el-icon> {{ docsData.flow_name }}</span>
              </div>
            </div>
          </section>

          <!-- ② 在线测试 -->
          <section class="ds ds-test">
            <div class="ds-title ds-title-test" @click="testPanelOpen = !testPanelOpen" style="cursor:pointer">
              <el-icon><VideoPlay /></el-icon>在线测试
              <span class="test-toggle">{{ testPanelOpen ? '收起 ▲' : '展开 ▼' }}</span>
            </div>
            <transition name="test-panel">
              <div v-if="testPanelOpen" class="test-panel">
                <div class="test-label">请求体（JSON）</div>
                <textarea
                  v-model="testPayload"
                  class="test-textarea"
                  spellcheck="false"
                  placeholder='{"inputs": {}}'
                  rows="6"
                />
                <div class="test-actions">
                  <button class="test-run-btn" :disabled="testRunning" @click="runTest">
                    <el-icon><VideoPlay /></el-icon>
                    {{ testRunning ? '调用中...' : '发送请求' }}
                  </button>
                  <span v-if="testResult" class="test-status" :style="{ color: testStatusColor }">
                    HTTP {{ testResult.status }} · {{ testResult.elapsed }}ms
                  </span>
                </div>
                <div v-if="testError" class="test-err">{{ testError }}</div>
                <div v-if="testResult" class="test-result">
                  <div class="test-result-label">响应</div>
                  <pre class="test-code">{{ JSON.stringify(testResult.data, null, 2) }}</pre>
                </div>
              </div>
            </transition>
          </section>

          <!-- ③ 开发者备注 -->
          <section v-if="docsData.remarks" class="ds">
            <div class="ds-title"><el-icon><EditPen /></el-icon>开发者备注</div>
            <div class="remarks-box">{{ docsData.remarks }}</div>
          </section>

          <!-- ④ 请求示例 -->
          <section class="ds">
            <div class="ds-title"><el-icon><Upload /></el-icon>请求示例</div>
            <pre class="code-block">{{ docsData.sample_request || JSON.stringify(docsData.request_example, null, 2) }}</pre>
          </section>

          <!-- ⑤ 响应示例 -->
          <section class="ds">
            <div class="ds-title"><el-icon><Download /></el-icon>响应示例</div>
            <pre class="code-block">{{ docsData.sample_response || JSON.stringify(docsData.response_example, null, 2) }}</pre>
          </section>

          <!-- ⑥ 调用链 -->
          <section v-if="docsData.blocks?.length" class="ds">
            <div class="ds-title"><el-icon><Grid /></el-icon>调用链（{{ docsData.blocks.length }} 个块）</div>
            <div class="chain-list">
              <div v-for="(b, idx) in docsData.blocks" :key="b.node_id" class="chain-item">
                <div class="chain-num">{{ idx + 1 }}</div>
                <div class="chain-info">
                  <span class="chain-name">{{ b.block_name }}</span>
                  <span class="chain-sub">入口: <code>{{ b.entrypoint || 'run' }}</code></span>
                  <span v-if="b.source_flow_name" class="chain-sub">导入自 {{ b.source_flow_name }}</span>
                </div>
              </div>
            </div>
          </section>

          <!-- ⑦ MQ 触发 -->
          <section v-if="docsData.mq_supported" class="ds">
            <div class="ds-title"><el-icon><MessageBox /></el-icon>MQ 触发（异步）</div>
            <div v-if="docsData.mq_invocation" class="mq-grid">
              <div class="mq-kv"><span class="mq-k">主队列</span><code>{{ docsData.mq_invocation.queue }}</code></div>
              <div class="mq-kv"><span class="mq-k">交换机</span><code>{{ docsData.mq_invocation.exchange }}</code></div>
              <div class="mq-kv"><span class="mq-k">路由键</span><code>{{ docsData.mq_invocation.routing_key }}</code></div>
              <div class="mq-kv"><span class="mq-k">重试</span><span>{{ docsData.mq_invocation.max_retry }} 次</span></div>
              <div class="mq-kv" v-if="docsData.mq_invocation.message_example">
                <span class="mq-k">消息示例</span>
                <pre class="code-block" style="margin:4px 0 0">{{ JSON.stringify(docsData.mq_invocation.message_example, null, 2) }}</pre>
              </div>
            </div>
          </section>

          <!-- ⑧ 变更日志 -->
          <section v-if="docsData.changelog" class="ds">
            <div class="ds-title"><el-icon><Clock /></el-icon>变更日志</div>
            <pre class="remarks-box" style="white-space:pre-wrap">{{ docsData.changelog }}</pre>
          </section>

          <!-- ⑨ 流量统计 -->
          <section class="ds">
            <div class="ds-title"><el-icon><TrendCharts /></el-icon>流量统计</div>
            <div class="stat-chips">
              <div class="sc">
                <span class="sc-v">{{ docsData.stats?.total_calls?.toLocaleString() ?? 0 }}</span>
                <span class="sc-l">总调用</span>
              </div>
              <div class="sc">
                <span class="sc-v" :style="{ color: 'var(--pf-green)' }">{{ docsData.stats?.success_rate ?? '—' }}%</span>
                <span class="sc-l">成功率</span>
              </div>
              <div class="sc">
                <span class="sc-v">{{ docsData.stats?.avg_latency_ms ?? '—' }}ms</span>
                <span class="sc-l">均延迟</span>
              </div>
              <div class="sc">
                <span class="sc-v">{{ docsData.stats?.error_calls?.toLocaleString() ?? 0 }}</span>
                <span class="sc-l">错误次</span>
              </div>
            </div>
          </section>

        </template>
        <el-empty v-else-if="!docsLoading" description="暂无文档数据" style="margin:60px 0" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
/* ── 变量补充（Light theme） ──────────────────────── */
.portal-page {
  --pf-green: #16a34a;
  --pf-amber: #d97706;
  --pf-red:   #dc2626;
  --card-radius: 12px;
}

/* ── 页头 ───────────────────────────────────────── */
.portal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.portal-title { margin: 0; font-size: 22px; font-weight: 700; color: var(--pf-text); }
.portal-sub   { margin: 4px 0 0; font-size: 13px; color: var(--pf-text-dim); }
.portal-search :deep(.el-input__wrapper) {
  border-radius: 20px;
  border: 1px solid var(--pf-border-strong);
  box-shadow: none;
  transition: border-color .2s, box-shadow .2s;
}
.portal-search :deep(.el-input__wrapper:focus-within) {
  border-color: var(--pf-accent);
  box-shadow: 0 0 0 3px rgba(37,99,235,.12);
}

/* ── 统计条 ─────────────────────────────────────── */
.portal-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  font-size: 13px;
  color: var(--pf-text-dim);
}
.ps-num { font-weight: 700; color: var(--pf-accent); }
.ps-dot { opacity: .4; }
.ps-dot-green { color: var(--pf-green); font-size: 10px; }

/* ── 网格 ───────────────────────────────────────── */
.portal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
  align-items: start;
}
.portal-grid-wrap { padding-bottom: 32px; }

/* ── 卡片 ───────────────────────────────────────── */
.api-card {
  padding: 18px 20px 16px;
  cursor: default;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 0;
  border-radius: var(--card-radius);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.api-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 30px rgba(37, 99, 235, .10);
  border-color: var(--pf-accent);
}
.api-card:hover .card-shine { opacity: 1; }
.card-shine {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(135deg, rgba(37,99,235,.04) 0%, transparent 60%);
  opacity: 0;
  transition: opacity .25s;
}

/* 卡片顶部 */
.card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.method-badge {
  background: #dcfce7;
  color: #15803d;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: .04em;
  font-family: monospace;
  border: 1px solid #bbf7d0;
  flex-shrink: 0;
}
.method-badge-sm {
  background: #dcfce7;
  color: #15803d;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: .04em;
  font-family: monospace;
  border: 1px solid #bbf7d0;
  flex-shrink: 0;
}
.status-dot {
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 3px;
}
.trigger-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 20px;
  border: 1px solid;
  letter-spacing: .02em;
}
.enc-pill {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: #d97706;
  background: #fef3c7;
  border: 1px solid #fde68a;
  padding: 2px 7px;
  border-radius: 20px;
  font-weight: 600;
}

/* 名称 + 描述 */
.card-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--pf-text);
  margin-bottom: 4px;
  line-height: 1.3;
}
.card-desc {
  font-size: 13px;
  color: var(--pf-text-dim);
  margin: 0 0 10px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 36px;
}

/* URI 行 */
.card-uri {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--pf-code-bg);
  border-radius: 7px;
  padding: 7px 10px;
  margin-bottom: 10px;
  overflow: hidden;
}
.uri-code {
  font-size: 12px;
  font-family: 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  color: #86efac;
  flex: 1;
  overflow-x: auto;
  white-space: nowrap;
  scrollbar-width: none;
}
.uri-code::-webkit-scrollbar { display: none; }
.uri-copy-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #9ca3af;
  padding: 2px;
  display: flex;
  align-items: center;
  border-radius: 4px;
  flex-shrink: 0;
  transition: color .15s, background .15s;
}
.uri-copy-btn:hover { color: #fff; background: rgba(255,255,255,.1); }

/* 元信息 */
.card-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--pf-text-dim);
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 3px;
}

/* 标签 */
.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 12px;
}
.tag-chip {
  font-size: 11px;
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  border: 1px solid rgba(37,99,235,.2);
  padding: 2px 8px;
  border-radius: 20px;
  font-weight: 500;
}

/* 卡片底部按钮 */
.card-footer {
  display: flex;
  gap: 8px;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--pf-border);
}
.card-btn {
  flex: 1;
  border: none;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  padding: 7px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  transition: all .15s;
}
.card-btn-test {
  background: #fef9c3;
  color: #854d0e;
  border: 1px solid #fde68a;
}
.card-btn-test:hover {
  background: #fde68a;
  transform: translateY(-1px);
}
.card-btn-docs {
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  border: 1px solid rgba(37,99,235,.25);
}
.card-btn-docs:hover {
  background: rgba(37,99,235,.15);
  transform: translateY(-1px);
}

/* 卡片动画 */
.pf-card-list-enter-active,
.pf-card-list-leave-active { transition: all .22s ease; }
.pf-card-list-enter-from,
.pf-card-list-leave-to { opacity: 0; transform: translateY(12px); }

/* ── Drawer ──────────────────────────────────────── */
.drawer-body { padding: 4px 0 32px; }

.ds {
  margin-bottom: 24px;
  animation: ds-in .22s ease both;
}
@keyframes ds-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
.ds:nth-child(1)  { animation-delay: 0ms; }
.ds:nth-child(2)  { animation-delay: 40ms; }
.ds:nth-child(3)  { animation-delay: 80ms; }
.ds:nth-child(4)  { animation-delay: 120ms; }
.ds:nth-child(5)  { animation-delay: 160ms; }
.ds:nth-child(6)  { animation-delay: 200ms; }

.ds-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--pf-accent);
  margin-bottom: 10px;
}

/* 信息格 */
.info-grid { display: flex; flex-direction: column; gap: 1px; border: 1px solid var(--pf-border); border-radius: 10px; overflow: hidden; }
.ig-row {
  display: flex;
  gap: 12px;
  padding: 9px 14px;
  background: var(--pf-panel);
  font-size: 13px;
  transition: background .15s;
}
.ig-row:not(:last-child) { border-bottom: 1px solid var(--pf-border); }
.ig-row:hover { background: var(--pf-panel-2); }
.ig-label {
  width: 76px;
  flex-shrink: 0;
  color: var(--pf-text-dim);
  font-size: 12px;
  padding-top: 1px;
}
.ig-val { flex: 1; word-break: break-all; }
.fw { font-weight: 700; }
.ig-uri {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--pf-code-bg);
  border-radius: 6px;
  padding: 4px 8px;
  overflow: hidden;
}
.uri-full {
  font-size: 12px;
  font-family: 'Fira Code', monospace;
  color: #86efac;
  flex: 1;
  overflow-x: auto;
  white-space: nowrap;
  scrollbar-width: none;
}
.uri-full::-webkit-scrollbar { display: none; }
.copy-xs {
  background: none;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  padding: 2px;
  border-radius: 3px;
  flex-shrink: 0;
  transition: color .15s;
}
.copy-xs:hover { color: #fff; }

/* ── 测试面板 ──────────────────────────────────── */
.ds-test { border: 1px solid #fde68a; border-radius: 10px; padding: 12px 16px; background: #fffbeb; }
.ds-title-test { color: #b45309; justify-content: space-between; }
.test-toggle { font-size: 11px; font-weight: 500; color: #92400e; }
.test-panel {
  padding-top: 10px;
}
.test-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--pf-text-dim);
  margin-bottom: 6px;
}
.test-textarea {
  width: 100%;
  font-size: 12px;
  font-family: 'Fira Code', monospace;
  border: 1px solid var(--pf-border-strong);
  border-radius: 7px;
  padding: 10px 12px;
  background: var(--pf-code-bg);
  color: var(--pf-code-text);
  resize: vertical;
  box-sizing: border-box;
  outline: none;
  transition: border-color .15s;
}
.test-textarea:focus { border-color: var(--pf-accent); }
.test-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
.test-run-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #b45309;
  color: #fff;
  border: none;
  border-radius: 7px;
  padding: 7px 18px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background .15s, transform .15s;
}
.test-run-btn:hover:not(:disabled) { background: #92400e; transform: translateY(-1px); }
.test-run-btn:disabled { opacity: .6; cursor: not-allowed; }
.test-status { font-size: 13px; font-weight: 700; }
.test-err { font-size: 12px; color: var(--pf-red); margin-top: 6px; background: #fee2e2; border-radius: 6px; padding: 6px 10px; }
.test-result { margin-top: 10px; }
.test-result-label { font-size: 12px; font-weight: 600; color: var(--pf-text-dim); margin-bottom: 4px; }
.test-code {
  background: var(--pf-code-bg);
  color: #86efac;
  font-family: 'Fira Code', monospace;
  font-size: 12px;
  border-radius: 7px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 0;
  max-height: 280px;
  overflow-y: auto;
}
.test-panel-enter-active,
.test-panel-leave-active { transition: all .2s ease; }
.test-panel-enter-from,
.test-panel-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── 其余 Drawer 子元素 ─────────────────────────── */
.remarks-box {
  background: var(--pf-panel-2);
  border-left: 3px solid var(--pf-accent);
  border-radius: 0 8px 8px 0;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
}
.code-block {
  background: var(--pf-code-bg);
  color: #a5d6ff;
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  font-size: 12px;
  border-radius: 8px;
  padding: 12px 14px;
  overflow-x: auto;
  margin: 0;
  white-space: pre;
}

.chain-list { display: flex; flex-direction: column; gap: 6px; }
.chain-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  background: var(--pf-panel-2);
  border-radius: 8px;
  padding: 10px 12px;
  border: 1px solid var(--pf-border);
  transition: border-color .15s;
}
.chain-item:hover { border-color: var(--pf-accent); }
.chain-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--pf-accent);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.chain-info { display: flex; flex-direction: column; gap: 2px; }
.chain-name { font-weight: 600; font-size: 13px; }
.chain-sub { font-size: 12px; color: var(--pf-text-dim); }

.mq-grid { display: flex; flex-direction: column; gap: 6px; }
.mq-kv { display: flex; gap: 10px; font-size: 13px; align-items: baseline; }
.mq-k { width: 68px; flex-shrink: 0; color: var(--pf-text-dim); font-size: 12px; }

.stat-chips { display: flex; gap: 12px; flex-wrap: wrap; }
.sc {
  flex: 1;
  min-width: 80px;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--pf-panel-2);
  border: 1px solid var(--pf-border);
  border-radius: 10px;
  padding: 12px 8px;
}
.sc-v { font-size: 20px; font-weight: 700; line-height: 1; }
.sc-l { font-size: 11px; color: var(--pf-text-dim); margin-top: 4px; }
</style>
