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

async function load() {
  loading.value = true
  try {
    apis.value = await apiPortalApi.browse()
  } finally {
    loading.value = false
  }
}

/** 客户端模糊过滤：接口名、URI 路径、备注/文档 */
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

async function openDocs(api: PublishedApi) {
  selectedApi.value = api
  docsDrawerVisible.value = true
  docsLoading.value = true
  docsData.value = null
  try {
    docsData.value = await apiPortalApi.getDocs(api.id)
  } finally {
    docsLoading.value = false
  }
}

async function copyUrl(api: PublishedApi) {
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

const triggerLabel: Record<string, string> = { http: 'HTTP', mq: 'MQ', both: 'HTTP+MQ' }
const triggerType: Record<string, string> = { http: 'info', mq: 'primary', both: 'success' }
const statusLabel: Record<string, string> = { active: '运行中', paused: '已暂停', deprecated: '已废弃' }
const statusType: Record<string, string> = { active: 'success', paused: 'warning', deprecated: 'danger' }

function successRate(api: PublishedApi) {
  return api.total_calls > 0 ? ((api.success_calls / api.total_calls) * 100).toFixed(1) + '%' : '—'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="head-left">
        <h2>接口门户</h2>
        <p class="dim">浏览平台已发布的开放接口，查看文档与调用规范</p>
      </div>
      <div class="head-right">
        <el-input
          v-model="searchQuery"
          placeholder="搜索接口名、URI 路径、备注文档..."
          :prefix-icon="'Search'"
          clearable
          style="width: 340px"
          class="search-input"
        />
      </div>
    </header>

    <!-- 统计条 -->
    <div class="stat-bar" v-if="!loading">
      <span class="stat-item">
        <span class="stat-num">{{ apis.length }}</span> 个接口
      </span>
      <span class="stat-sep">·</span>
      <span class="stat-item">
        <span class="stat-num">{{ apis.filter(a => a.status === 'active').length }}</span> 个运行中
      </span>
      <template v-if="searchQuery">
        <span class="stat-sep">·</span>
        <span class="stat-item">匹配 <span class="stat-num">{{ filtered.length }}</span> 个结果</span>
      </template>
    </div>

    <!-- 卡片列表 -->
    <div v-loading="loading" class="api-list">
      <transition-group name="card-list" tag="div" class="api-grid">
        <div
          v-for="api in filtered"
          :key="api.id"
          class="api-card pf-card"
          @click="openDocs(api)"
        >
          <!-- 卡片顶部 -->
          <div class="card-header">
            <div class="card-title-row">
              <span class="api-name">{{ api.name }}</span>
              <div class="card-badges">
                <el-tag :type="statusType[api.status] || 'info'" size="small" effect="light">
                  {{ statusLabel[api.status] || api.status }}
                </el-tag>
                <el-tag :type="triggerType[api.trigger_type] || 'info'" size="small" effect="plain">
                  {{ triggerLabel[api.trigger_type] || api.trigger_type }}
                </el-tag>
                <el-tag v-if="api.encryption_enabled" type="warning" size="small" effect="plain">
                  <el-icon style="margin-right:2px"><Lock /></el-icon>加密
                </el-tag>
              </div>
            </div>
            <p class="api-desc">{{ api.description || '暂无描述' }}</p>
          </div>

          <!-- 调用路径 -->
          <div class="card-path" @click.stop>
            <code class="path-code">POST {{ api.path }}</code>
            <el-button text size="small" :icon="'CopyDocument'" class="copy-btn" @click.stop="copyUrl(api)">
              复制地址
            </el-button>
          </div>

          <!-- 标签 -->
          <div v-if="tagList(api).length" class="card-tags">
            <el-tag v-for="tag in tagList(api)" :key="tag" size="small" effect="plain" type="info" class="api-tag">
              {{ tag }}
            </el-tag>
          </div>

          <!-- 卡片底部：统计 + 查看文档 -->
          <div class="card-footer">
            <div class="card-stats">
              <span class="stat-chip">
                <el-icon><Histogram /></el-icon>
                {{ api.total_calls.toLocaleString() }} 次调用
              </span>
              <span class="stat-chip" v-if="api.total_calls > 0">
                成功率 {{ successRate(api) }}
              </span>
              <span class="stat-chip" v-if="api.avg_latency_ms > 0">
                {{ api.avg_latency_ms.toFixed(0) }}ms
              </span>
            </div>
            <el-button type="primary" size="small" plain class="docs-btn">
              <el-icon style="margin-right:4px"><Document /></el-icon>
              查看文档
            </el-button>
          </div>

          <!-- 悬停光晕 -->
          <div class="card-glow" />
        </div>
      </transition-group>

      <el-empty
        v-if="!loading && filtered.length === 0"
        :description="searchQuery ? '未找到匹配的接口，请尝试其他关键词' : '暂无可用接口'"
        style="margin: 60px 0"
      />
    </div>

    <!-- 接口文档 Drawer -->
    <el-drawer
      v-model="docsDrawerVisible"
      :title="selectedApi?.name || '接口文档'"
      size="600px"
      direction="rtl"
      class="docs-drawer"
    >
      <div v-loading="docsLoading" class="docs-content">
        <template v-if="docsData">
          <!-- 基本信息 -->
          <section class="docs-section">
            <div class="section-title">
              <el-icon><InfoFilled /></el-icon>基本信息
            </div>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="接口名称">
                <strong>{{ docsData.name }}</strong>
              </el-descriptions-item>
              <el-descriptions-item label="调用地址">
                <div class="path-row">
                  <code class="path-code">POST {{ docsData.path }}</code>
                  <el-button text size="small" @click="copyUrl(selectedApi!)">复制</el-button>
                </div>
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="statusType[docsData.status] || 'info'" effect="light">
                  {{ statusLabel[docsData.status] || docsData.status }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="触发方式">
                <el-tag :type="triggerType[docsData.trigger_type] || 'info'" effect="light">
                  {{ triggerLabel[docsData.trigger_type] || docsData.trigger_type }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item v-if="docsData.description" label="描述">
                {{ docsData.description }}
              </el-descriptions-item>
              <el-descriptions-item label="加密保护">
                <el-tag :type="docsData.encryption_enabled ? 'warning' : 'info'" effect="plain">
                  {{ docsData.encryption_enabled ? 'AES-256-GCM 加密' : '明文' }}
                </el-tag>
                <span v-if="docsData.require_encrypted_request" class="dim" style="margin-left:6px">
                  （强制加密请求）
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="关联流程">{{ docsData.flow_name }}</el-descriptions-item>
            </el-descriptions>
          </section>

          <!-- 开发者备注 -->
          <section v-if="docsData.remarks" class="docs-section">
            <div class="section-title">
              <el-icon><EditPen /></el-icon>开发者备注
            </div>
            <div class="remarks-box">{{ docsData.remarks }}</div>
          </section>

          <!-- 请求示例 -->
          <section class="docs-section">
            <div class="section-title">
              <el-icon><Upload /></el-icon>请求示例
            </div>
            <pre class="code-block">{{ docsData.sample_request || JSON.stringify(docsData.request_example, null, 2) }}</pre>
          </section>

          <!-- 响应示例 -->
          <section class="docs-section">
            <div class="section-title">
              <el-icon><Download /></el-icon>响应示例
            </div>
            <pre class="code-block">{{ docsData.sample_response || JSON.stringify(docsData.response_example, null, 2) }}</pre>
          </section>

          <!-- 调用块列表 -->
          <section v-if="docsData.blocks?.length" class="docs-section">
            <div class="section-title">
              <el-icon><Grid /></el-icon>调用链（{{ docsData.blocks.length }} 个块）
            </div>
            <div class="blocks-list">
              <div v-for="(b, idx) in docsData.blocks" :key="b.node_id" class="block-item">
                <div class="block-num">{{ idx + 1 }}</div>
                <div class="block-info">
                  <span class="block-name">{{ b.block_name }}</span>
                  <span class="dim" style="font-size:12px">入口: {{ b.entrypoint || 'run' }}</span>
                  <p v-if="b.description" class="block-desc-text">{{ b.description }}</p>
                </div>
              </div>
            </div>
          </section>

          <!-- MQ 触发说明 -->
          <section v-if="docsData.mq_supported" class="docs-section">
            <div class="section-title">
              <el-icon><MessageBox /></el-icon>MQ 触发（异步）
            </div>
            <el-descriptions v-if="docsData.mq_invocation" :column="1" border size="small">
              <el-descriptions-item
                v-for="(v, k) in docsData.mq_invocation"
                :key="k"
                :label="String(k)"
              >
                <code v-if="typeof v === 'object'">{{ JSON.stringify(v) }}</code>
                <span v-else>{{ v }}</span>
              </el-descriptions-item>
            </el-descriptions>
          </section>

          <!-- 变更日志 -->
          <section v-if="docsData.changelog" class="docs-section">
            <div class="section-title">
              <el-icon><Clock /></el-icon>变更日志
            </div>
            <pre class="remarks-box" style="white-space: pre-wrap">{{ docsData.changelog }}</pre>
          </section>

          <!-- 流量统计 -->
          <section class="docs-section">
            <div class="section-title">
              <el-icon><TrendCharts /></el-icon>流量统计
            </div>
            <div class="stats-row">
              <div class="stats-chip">
                <span class="sc-val">{{ docsData.stats?.total_calls?.toLocaleString() ?? 0 }}</span>
                <span class="sc-label">总调用</span>
              </div>
              <div class="stats-chip">
                <span class="sc-val text-ok">{{ docsData.stats?.success_rate ?? '—' }}%</span>
                <span class="sc-label">成功率</span>
              </div>
              <div class="stats-chip">
                <span class="sc-val">{{ docsData.stats?.avg_latency_ms ?? '—' }}ms</span>
                <span class="sc-label">均延迟</span>
              </div>
            </div>
          </section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
/* ── 页头 ───────────────────────────────────────── */
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}
.page-head h2 { margin: 0; }
.dim { color: var(--pf-text-dim); font-size: 13px; margin: 4px 0 0; }
.search-input :deep(.el-input__wrapper) {
  border-radius: 20px;
  transition: box-shadow .2s;
}
.search-input :deep(.el-input__wrapper:focus-within) {
  box-shadow: 0 0 0 2px var(--el-color-primary-light-5);
}

/* ── 统计条 ─────────────────────────────────────── */
.stat-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
  font-size: 13px;
  color: var(--pf-text-dim);
}
.stat-num { color: var(--el-color-primary); font-weight: 600; }
.stat-sep { opacity: .4; }

/* ── 卡片网格 ───────────────────────────────────── */
.api-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}
.api-card {
  padding: 20px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition: transform .2s, box-shadow .2s;
}
.api-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 30px rgba(0,0,0,.25);
}
.api-card:hover .card-glow {
  opacity: 1;
}
.card-glow {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(ellipse at 50% 0%, rgba(59,130,246,.06) 0%, transparent 70%);
  opacity: 0;
  transition: opacity .25s;
}

.card-header { margin-bottom: 10px; }
.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.api-name {
  font-weight: 700;
  font-size: 15px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-badges { display: flex; gap: 4px; flex-shrink: 0; }
.api-desc {
  font-size: 13px;
  color: var(--pf-text-dim);
  margin: 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 36px;
}

/* 路径行 */
.card-path {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(0,0,0,.2);
  border-radius: 6px;
  padding: 6px 10px;
  margin-bottom: 10px;
}
.path-code {
  font-size: 12px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-color-primary-light-3);
  font-family: 'Fira Code', monospace;
}
.copy-btn { flex-shrink: 0; font-size: 12px; }

/* 标签 */
.card-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 12px; }
.api-tag { font-size: 11px; }

/* 底部 */
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-stats { display: flex; gap: 10px; flex-wrap: wrap; }
.stat-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--pf-text-dim);
}
.docs-btn { flex-shrink: 0; }

/* 卡片动画 */
.card-list-enter-active,
.card-list-leave-active {
  transition: all .22s ease;
}
.card-list-enter-from,
.card-list-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* ── 文档 Drawer ───────────────────────────────── */
.docs-content { padding: 4px 0; }
.docs-section {
  margin-bottom: 24px;
  animation: fade-up .25s ease both;
}
@keyframes fade-up {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
.docs-section:nth-child(1) { animation-delay: 0ms; }
.docs-section:nth-child(2) { animation-delay: 40ms; }
.docs-section:nth-child(3) { animation-delay: 80ms; }
.docs-section:nth-child(4) { animation-delay: 120ms; }
.docs-section:nth-child(5) { animation-delay: 160ms; }
.docs-section:nth-child(6) { animation-delay: 200ms; }

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--el-color-primary-light-3);
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: .04em;
}
.remarks-box {
  background: rgba(0,0,0,.18);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--pf-text-main);
  white-space: pre-wrap;
  word-break: break-word;
  border-left: 3px solid var(--el-color-primary);
}
.code-block {
  background: rgba(0,0,0,.25);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 12px;
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  color: #a5d6ff;
  overflow-x: auto;
  white-space: pre;
  margin: 0;
}
.path-row { display: flex; align-items: center; gap: 8px; }

/* 调用块列表 */
.blocks-list { display: flex; flex-direction: column; gap: 8px; }
.block-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: rgba(0,0,0,.15);
  border-radius: 8px;
  padding: 10px 12px;
}
.block-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.block-info { display: flex; flex-direction: column; gap: 2px; }
.block-name { font-weight: 600; font-size: 13px; }
.block-desc-text { font-size: 12px; color: var(--pf-text-dim); margin: 2px 0 0; }

/* 统计 */
.stats-row { display: flex; gap: 16px; flex-wrap: wrap; }
.stats-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: rgba(0,0,0,.18);
  border-radius: 8px;
  padding: 10px 20px;
  min-width: 80px;
}
.sc-val { font-size: 18px; font-weight: 700; }
.sc-label { font-size: 12px; color: var(--pf-text-dim); margin-top: 2px; }
.text-ok { color: #34d399; }
</style>
