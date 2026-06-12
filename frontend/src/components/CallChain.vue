<script setup lang="ts">
import { computed, ref } from 'vue'

interface ChainNode {
  id: string
  type: string
  label: string
  detail?: string
  sub?: string
  note?: string
  status?: string
  duration_ms?: number | null
  hit_port?: string
  error?: string
  has_output?: boolean
  node_id?: string
  block_id?: string
  children?: ChainNode[]
}

interface CallChain {
  type: string
  nodes: ChainNode[]
  total_ms?: number | null
  status?: string
}

const props = defineProps<{
  chain: CallChain
}>()

const emit = defineEmits<{
  nodeClick: [node: ChainNode]
}>()

const selectedNode = ref<ChainNode | null>(null)

// 节点类型元数据
const nodeMeta: Record<string, { icon: string; colorClass: string; shape: string }> = {
  client:       { icon: '💻', colorClass: 'n-client',      shape: 'rect' },
  network:      { icon: '🌐', colorClass: 'n-network',     shape: 'rect' },
  gateway:      { icon: '🔀', colorClass: 'n-gateway',     shape: 'diamond' },
  service:      { icon: '⚙️', colorClass: 'n-service',     shape: 'rect' },
  auth:         { icon: '🔑', colorClass: 'n-auth',        shape: 'rect' },
  orchestrator: { icon: '🎛️', colorClass: 'n-orchestrator', shape: 'container' },
  block:        { icon: '📦', colorClass: 'n-block',       shape: 'rect' },
  mq_broker:    { icon: '📨', colorClass: 'n-mq',         shape: 'cylinder' },
  mq_exchange:  { icon: '🔄', colorClass: 'n-mq',         shape: 'rect' },
  mq_route:     { icon: '➡️', colorClass: 'n-mq-route',   shape: 'rect' },
  mq_queue:     { icon: '📥', colorClass: 'n-mq',         shape: 'cylinder' },
  filter:       { icon: '🔍', colorClass: 'n-filter',     shape: 'rect' },
  response:     { icon: '📤', colorClass: 'n-response',   shape: 'rect' },
}

const statusColor: Record<string, string> = {
  ok: '#22c55e',
  done: '#22c55e',
  succeeded: '#22c55e',
  error: '#ef4444',
  failed: '#ef4444',
  nack: '#ef4444',
  warning: '#f59e0b',
  running: '#f59e0b',
  skipped: '#94a3b8',
  unknown: '#64748b',
}

const triggerLabel: Record<string, string> = {
  http:   'HTTP API 调用',
  stream: 'HTTP SSE 流式调用',
  mq:     'MQ 消息触发',
  manual: '手动触发',
}

function getStatusColor(node: ChainNode): string {
  return statusColor[node.status || 'ok'] || '#22c55e'
}

function getMeta(type: string) {
  return nodeMeta[type] || nodeMeta['service']
}

function isError(node: ChainNode): boolean {
  return node.status === 'error' || node.status === 'failed' || node.status === 'nack'
}

function fmtDur(ms: number | null | undefined): string {
  if (ms == null) return ''
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return ms + 'ms'
}

function selectNode(node: ChainNode) {
  selectedNode.value = selectedNode.value?.id === node.id ? null : node
  emit('nodeClick', node)
}

// 找到整个链路中最高的总耗时（用于进度条比例）
const maxDur = computed(() => {
  let m = 0
  for (const node of props.chain.nodes) {
    if (node.duration_ms) m = Math.max(m, node.duration_ms)
    if (node.children) {
      for (const c of node.children) {
        if (c.duration_ms) m = Math.max(m, c.duration_ms)
      }
    }
  }
  return m || 1
})

function durPercent(ms: number | null | undefined): number {
  if (!ms) return 0
  return Math.min(100, (ms / maxDur.value) * 100)
}

// 统计子节点
const childStats = computed(() => {
  const orchestrator = props.chain.nodes.find(n => n.type === 'orchestrator')
  if (!orchestrator?.children) return null
  const total = orchestrator.children.length
  const done = orchestrator.children.filter(c => c.status === 'done' || c.status === 'succeeded').length
  const failed = orchestrator.children.filter(c => c.status === 'failed').length
  const skipped = orchestrator.children.filter(c => c.status === 'skipped').length
  return { total, done, failed, skipped }
})
</script>

<template>
  <div class="call-chain-root">
    <!-- 标题 -->
    <div class="chain-header">
      <div class="chain-type-badge" :class="`badge-${chain.type}`">
        <span v-if="chain.type === 'http'">🌐 HTTP</span>
        <span v-else-if="chain.type === 'stream'">📡 SSE 流式</span>
        <span v-else-if="chain.type === 'mq'">📨 MQ 消息</span>
        <span v-else>🖱️ 手动</span>
      </div>
      <span class="chain-title-text">{{ triggerLabel[chain.type] || chain.type }}</span>
      <div class="chain-summary" v-if="chain.total_ms != null">
        <span class="dur-total" :class="chain.total_ms > 5000 ? 'dur-slow' : ''">
          ⏱ {{ fmtDur(chain.total_ms) }}
        </span>
        <el-tag
          :type="chain.status === 'succeeded' ? 'success' : chain.status === 'failed' ? 'danger' : 'warning'"
          size="small" effect="dark"
        >{{ chain.status }}</el-tag>
      </div>
      <div class="chain-node-stat" v-if="childStats">
        <span class="stat-ok">✓ {{ childStats.done }}</span>
        <span v-if="childStats.failed" class="stat-err">✗ {{ childStats.failed }}</span>
        <span v-if="childStats.skipped" class="stat-skip">⊘ {{ childStats.skipped }}</span>
        <span class="stat-total dim">/ {{ childStats.total }} 节点</span>
      </div>
    </div>

    <!-- 主链路滚动区 -->
    <div class="chain-scroll">
      <div class="chain-row">
        <template v-for="(node, i) in chain.nodes" :key="node.id">
          <!-- 非 orchestrator 节点 -->
          <template v-if="node.type !== 'orchestrator'">
            <div
              class="chain-node"
              :class="[getMeta(node.type).colorClass, { 'node-error': isError(node), 'node-selected': selectedNode?.id === node.id }]"
              :style="{ animationDelay: `${i * 60}ms` }"
              @click="selectNode(node)"
            >
              <!-- 状态指示线 -->
              <div class="node-status-line" :style="{ background: getStatusColor(node) }" />
              <div class="node-body">
                <div class="node-icon-row">
                  <span class="node-icon">{{ getMeta(node.type).icon }}</span>
                  <span v-if="node.note" class="node-note">{{ node.note }}</span>
                </div>
                <div class="node-label">{{ node.label }}</div>
                <div class="node-detail dim" v-if="node.detail">{{ node.detail }}</div>
                <div class="node-sub dim" v-if="node.sub">{{ node.sub }}</div>
                <!-- 耗时 -->
                <div v-if="node.duration_ms != null" class="node-dur-wrap">
                  <div class="dur-bar-bg">
                    <div class="dur-bar-fill" :style="{ width: durPercent(node.duration_ms) + '%', background: getStatusColor(node) }" />
                  </div>
                  <span class="dur-label" :class="node.duration_ms > 3000 ? 'dur-slow' : ''">
                    {{ fmtDur(node.duration_ms) }}
                  </span>
                </div>
                <!-- 错误标识 -->
                <div v-if="isError(node)" class="node-error-badge">
                  <span>✗</span>
                </div>
              </div>
              <!-- 选中展开 -->
              <div v-if="selectedNode?.id === node.id" class="node-popup">
                <div class="popup-row" v-if="node.detail"><span class="popup-key">路径</span><span>{{ node.detail }}</span></div>
                <div class="popup-row" v-if="node.note"><span class="popup-key">备注</span><span class="dim">{{ node.note }}</span></div>
                <div class="popup-row" v-if="node.duration_ms != null"><span class="popup-key">耗时</span><span>{{ fmtDur(node.duration_ms) }}</span></div>
                <div class="popup-row" v-if="node.error"><span class="popup-key err-key">错误</span><span class="err-txt">{{ node.error }}</span></div>
                <div class="popup-row" v-if="node.hit_port"><span class="popup-key">端口</span><span>{{ node.hit_port }}</span></div>
              </div>
            </div>
            <!-- 箭头（非末位节点，且下一个不是 orchestrator 的子节点） -->
            <div
              v-if="i < chain.nodes.length - 1"
              class="chain-arrow"
              :style="{ animationDelay: `${i * 60 + 30}ms` }"
            >
              <div class="arrow-shaft" />
              <div class="arrow-head">▶</div>
            </div>
          </template>

          <!-- Orchestrator 容器节点（包含 block 子节点） -->
          <template v-else>
            <div
              class="chain-orchestrator"
              :class="{ 'orch-error': node.status === 'failed', 'orch-selected': selectedNode?.id === node.id }"
              :style="{ animationDelay: `${i * 60}ms` }"
            >
              <!-- 容器标题 -->
              <div class="orch-header" @click="selectNode(node)">
                <span class="orch-icon">🎛️</span>
                <span class="orch-label">{{ node.label }}</span>
                <span class="dim orch-detail" v-if="node.detail">{{ node.detail }}</span>
                <span class="orch-dur" v-if="node.duration_ms != null">
                  {{ fmtDur(node.duration_ms) }}
                </span>
                <el-tag
                  v-if="node.status"
                  size="small"
                  :type="node.status === 'done' ? 'success' : node.status === 'failed' ? 'danger' : 'info'"
                  effect="dark"
                >{{ node.status }}</el-tag>
              </div>

              <!-- 子节点链路 -->
              <div class="orch-children" v-if="node.children?.length">
                <template v-for="(child, ci) in node.children" :key="child.id">
                  <div
                    class="block-node"
                    :class="{
                      'block-error': child.status === 'failed',
                      'block-skip': child.status === 'skipped',
                      'block-selected': selectedNode?.id === child.id,
                    }"
                    :style="{
                      borderColor: statusColor[child.status || 'ok'] || '#64748b',
                      animationDelay: `${i * 60 + ci * 80 + 100}ms`,
                    }"
                    @click.stop="selectNode(child)"
                  >
                    <!-- 顶部彩色状态条 -->
                    <div class="block-status-bar" :style="{ background: statusColor[child.status || 'ok'] || '#64748b' }" />
                    <div class="block-body">
                      <div class="block-label">{{ child.label }}</div>
                      <div class="block-meta">
                        <span class="block-status" :style="{ color: statusColor[child.status || 'ok'] || '#64748b' }">
                          {{ child.status }}
                        </span>
                        <span class="block-dur dim" v-if="child.duration_ms != null">{{ fmtDur(child.duration_ms) }}</span>
                      </div>
                      <!-- 耗时进度条 -->
                      <div v-if="child.duration_ms != null" class="block-dur-bar">
                        <div
                          class="block-dur-fill"
                          :style="{
                            width: durPercent(child.duration_ms) + '%',
                            background: statusColor[child.status || 'ok'] || '#64748b',
                          }"
                        />
                      </div>
                      <!-- 失败标记 -->
                      <div v-if="child.status === 'failed'" class="block-err-mark">
                        <span>⚠ 节点失败</span>
                        <span v-if="child.error" class="block-err-msg">{{ child.error }}</span>
                      </div>
                      <!-- hit_port -->
                      <div v-if="child.hit_port" class="block-port dim">→ {{ child.hit_port }}</div>
                    </div>

                    <!-- 节点展开详情 -->
                    <div v-if="selectedNode?.id === child.id" class="node-popup block-popup">
                      <div class="popup-row" v-if="child.node_id"><span class="popup-key">节点 ID</span><code>{{ child.node_id?.slice(0, 12) }}</code></div>
                      <div class="popup-row" v-if="child.block_id"><span class="popup-key">块 ID</span><code>{{ child.block_id?.slice(0, 12) }}</code></div>
                      <div class="popup-row" v-if="child.duration_ms != null"><span class="popup-key">执行耗时</span><span>{{ fmtDur(child.duration_ms) }}</span></div>
                      <div class="popup-row" v-if="child.hit_port"><span class="popup-key">激活端口</span><span>{{ child.hit_port }}</span></div>
                      <div class="popup-row" v-if="child.error"><span class="popup-key err-key">错误信息</span><span class="err-txt">{{ child.error }}</span></div>
                    </div>
                  </div>

                  <!-- 子节点箭头 -->
                  <div
                    v-if="ci < (node.children?.length ?? 0) - 1"
                    class="block-arrow"
                    :style="{ animationDelay: `${i * 60 + ci * 80 + 130}ms` }"
                  >
                    <div class="barrow-shaft" />
                    <div class="barrow-port dim" v-if="child.hit_port">{{ child.hit_port }}</div>
                    <div class="barrow-head">▶</div>
                  </div>
                </template>
              </div>
              <div class="orch-empty dim" v-else>无执行步骤</div>
            </div>

            <!-- Orchestrator 后面的箭头 -->
            <div
              v-if="i < chain.nodes.length - 1"
              class="chain-arrow"
              :style="{ animationDelay: `${i * 60 + 30}ms` }"
            >
              <div class="arrow-shaft" />
              <div class="arrow-head">▶</div>
            </div>
          </template>
        </template>
      </div>
    </div>

    <!-- 耗时时间线（甘特图风格，仅当有耗时数据时） -->
    <div class="timeline-section" v-if="chain.total_ms">
      <div class="tl-label dim">耗时分布</div>
      <div class="timeline-bars">
        <template v-for="node in chain.nodes" :key="`tl-${node.id}`">
          <template v-if="node.type === 'orchestrator' && node.children?.length">
            <div
              v-for="child in node.children"
              :key="`tl-${child.id}`"
              class="tl-bar-row"
            >
              <div class="tl-node-name dim">{{ child.label }}</div>
              <div class="tl-bar-bg">
                <div
                  class="tl-bar-fill"
                  :style="{
                    width: durPercent(child.duration_ms) + '%',
                    background: statusColor[child.status || 'ok'] || '#64748b',
                    animationDelay: '0.3s',
                  }"
                />
              </div>
              <div class="tl-dur dim">{{ fmtDur(child.duration_ms) }}</div>
            </div>
          </template>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes node-appear {
  from { opacity: 0; transform: translateY(8px) scale(0.95); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes tl-grow {
  from { width: 0 !important; }
  to   { /* 宽度由 style 决定 */ }
}

.call-chain-root {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 标题区 */
.chain-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 0 2px;
}
.chain-type-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 20px;
  letter-spacing: 0.3px;
}
.badge-http    { background: rgba(79,70,229,0.15); color: #818cf8; border: 1px solid rgba(99,102,241,0.3); }
.badge-stream  { background: rgba(8,145,178,0.15); color: #22d3ee; border: 1px solid rgba(6,182,212,0.3); }
.badge-mq      { background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3); }
.badge-manual  { background: rgba(148,163,184,0.12); color: #94a3b8; border: 1px solid rgba(148,163,184,0.25); }
.chain-title-text { font-size: 14px; font-weight: 600; color: var(--pf-text); }
.chain-summary { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.dur-total { font-size: 13px; font-weight: 700; color: var(--pf-text); font-family: monospace; }
.dur-slow { color: #f59e0b !important; }
.chain-node-stat { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.stat-ok  { color: #22c55e; font-weight: 600; }
.stat-err { color: #ef4444; font-weight: 600; }
.stat-skip { color: #94a3b8; }
.stat-total { margin-left: 2px; }

/* 滚动容器 */
.chain-scroll {
  overflow-x: auto;
  padding: 16px 4px;
  background: rgba(15, 23, 42, 0.5);
  border-radius: 12px;
  border: 1px solid var(--pf-border);
  scrollbar-width: thin;
  scrollbar-color: var(--pf-border) transparent;
}
.chain-row {
  display: flex;
  align-items: flex-start;
  gap: 0;
  min-width: max-content;
  padding: 0 8px;
}

/* 普通节点 */
.chain-node {
  width: 130px;
  min-height: 100px;
  border-radius: 12px;
  border: 1.5px solid var(--pf-border);
  background: var(--pf-panel);
  overflow: visible;
  cursor: pointer;
  position: relative;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
  animation: node-appear 0.4s ease both;
  flex-shrink: 0;
}
.chain-node:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
.chain-node.node-selected {
  box-shadow: 0 0 0 2px var(--pf-accent), 0 8px 20px rgba(79,70,229,0.2);
  transform: translateY(-4px);
}
.chain-node.node-error {
  border-color: rgba(239,68,68,0.5);
  animation: node-appear 0.4s ease both, error-pulse 2s ease infinite 0.5s;
}
@keyframes error-pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.3); }
  50% { box-shadow: 0 0 0 6px rgba(239,68,68,0); }
}

.node-status-line { height: 3px; width: 100%; border-radius: 2px 2px 0 0; }
.node-body { padding: 8px 10px; }
.node-icon-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.node-icon { font-size: 18px; line-height: 1; }
.node-note { font-size: 9px; color: #64748b; background: rgba(100,116,139,0.1); padding: 1px 4px; border-radius: 4px; }
.node-label { font-size: 12px; font-weight: 700; color: var(--pf-text); line-height: 1.3; word-break: break-word; }
.node-detail { font-size: 10px; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.node-sub { font-size: 10px; margin-top: 1px; }
.node-dur-wrap { margin-top: 6px; display: flex; flex-direction: column; gap: 3px; }
.dur-bar-bg { height: 3px; background: var(--pf-border); border-radius: 2px; overflow: hidden; }
.dur-bar-fill { height: 100%; border-radius: 2px; transition: width 0.8s ease; }
.dur-label { font-size: 10px; font-family: monospace; color: var(--pf-text-dim); }
.node-error-badge {
  position: absolute; top: 4px; right: 4px;
  width: 16px; height: 16px; border-radius: 50%;
  background: #ef4444; color: white;
  font-size: 10px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  animation: badge-bounce 1s ease infinite;
}
@keyframes badge-bounce {
  0%,100% { transform: scale(1); }
  50% { transform: scale(1.2); }
}

/* 节点颜色类 */
.n-client      { border-color: rgba(148,163,184,0.3); }
.n-client .node-status-line { background: #64748b; }
.n-network     { border-color: rgba(6,182,212,0.3); }
.n-network .node-status-line { background: #0891b2; }
.n-gateway     { border-color: rgba(168,85,247,0.35); }
.n-gateway .node-status-line { background: #a855f7; }
.n-service     { border-color: rgba(79,70,229,0.35); }
.n-service .node-status-line { background: #4f46e5; }
.n-auth        { border-color: rgba(245,158,11,0.35); }
.n-auth .node-status-line { background: #f59e0b; }
.n-mq          { border-color: rgba(245,158,11,0.4); }
.n-mq .node-status-line { background: #f59e0b; }
.n-mq-route    { border-color: rgba(251,146,60,0.3); }
.n-mq-route .node-status-line { background: #fb923c; }
.n-filter      { border-color: rgba(20,184,166,0.35); }
.n-filter .node-status-line { background: #14b8a6; }
.n-response    { border-color: rgba(34,197,94,0.3); }
.n-response .node-status-line { background: #22c55e; }
.n-orchestrator{ border-color: rgba(99,102,241,0.35); }

/* 链路箭头 */
.chain-arrow {
  display: flex;
  align-items: center;
  padding: 40px 2px 0;
  width: 36px;
  flex-shrink: 0;
  position: relative;
  animation: node-appear 0.35s ease both;
}
.arrow-shaft {
  height: 2px;
  width: 22px;
  background: linear-gradient(90deg, var(--pf-border), rgba(99,102,241,0.5));
}
.arrow-head { font-size: 9px; color: rgba(99,102,241,0.7); }

/* Orchestrator 容器 */
.chain-orchestrator {
  background: rgba(79,70,229,0.05);
  border: 1.5px solid rgba(99,102,241,0.35);
  border-radius: 14px;
  padding: 10px 12px;
  min-width: 280px;
  max-width: 900px;
  animation: node-appear 0.45s ease both;
  flex-shrink: 0;
  transition: box-shadow 0.18s ease;
}
.chain-orchestrator:hover { box-shadow: 0 4px 16px rgba(79,70,229,0.15); }
.chain-orchestrator.orch-error { border-color: rgba(239,68,68,0.4); background: rgba(239,68,68,0.04); }
.chain-orchestrator.orch-selected { box-shadow: 0 0 0 2px rgba(99,102,241,0.5); }

.orch-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  cursor: pointer;
  padding: 4px 2px;
  border-radius: 6px;
  transition: background 0.15s;
}
.orch-header:hover { background: rgba(99,102,241,0.08); }
.orch-icon { font-size: 16px; }
.orch-label { font-size: 13px; font-weight: 700; color: var(--pf-text); }
.orch-detail { font-size: 11px; }
.orch-dur { font-size: 12px; font-family: monospace; font-weight: 600; color: var(--pf-text-dim); margin-left: auto; }

/* 子节点区域 */
.orch-children {
  display: flex;
  align-items: flex-start;
  gap: 0;
  overflow-x: auto;
  padding: 4px 0 2px;
  scrollbar-width: thin;
}
.orch-empty { font-size: 12px; padding: 8px 4px; }

/* Block 子节点 */
.block-node {
  width: 128px;
  min-height: 88px;
  border-radius: 10px;
  border: 1.5px solid;
  background: var(--pf-panel);
  cursor: pointer;
  position: relative;
  flex-shrink: 0;
  overflow: visible;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  animation: node-appear 0.4s ease both;
}
.block-node:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0,0,0,0.25); }
.block-node.block-selected {
  box-shadow: 0 0 0 2px var(--pf-accent), 0 6px 16px rgba(79,70,229,0.2);
  transform: translateY(-3px);
}
.block-node.block-error {
  animation: node-appear 0.4s ease both, error-pulse 1.8s ease infinite 0.5s;
}
.block-node.block-skip { opacity: 0.5; }

.block-status-bar { height: 3px; border-radius: 2px 2px 0 0; }
.block-body { padding: 7px 9px; }
.block-label { font-size: 12px; font-weight: 600; color: var(--pf-text); word-break: break-word; line-height: 1.3; }
.block-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 4px; }
.block-status { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }
.block-dur { font-size: 10px; font-family: monospace; }
.block-dur-bar { height: 3px; background: var(--pf-border); border-radius: 2px; overflow: hidden; margin-top: 5px; }
.block-dur-fill { height: 100%; border-radius: 2px; animation: tl-grow 0.8s ease both; }
.block-err-mark {
  margin-top: 5px; padding: 3px 5px;
  background: rgba(239,68,68,0.1); border-radius: 4px;
  font-size: 10px; color: #f87171;
  display: flex; flex-direction: column; gap: 2px;
}
.block-err-msg { font-size: 9px; opacity: 0.8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 110px; }
.block-port { font-size: 10px; margin-top: 3px; }

/* Block 箭头 */
.block-arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: 30px;
  width: 36px;
  flex-shrink: 0;
  position: relative;
  animation: node-appear 0.35s ease both;
}
.barrow-shaft { height: 2px; width: 24px; background: linear-gradient(90deg, var(--pf-border), rgba(99,102,241,0.4)); }
.barrow-head { font-size: 9px; color: rgba(99,102,241,0.6); }
.barrow-port {
  position: absolute; top: 14px; left: 50%;
  transform: translateX(-50%);
  font-size: 9px; white-space: nowrap;
  background: var(--pf-panel-2); padding: 1px 4px; border-radius: 3px;
  border: 1px solid var(--pf-border); max-width: 60px; overflow: hidden; text-overflow: ellipsis;
}

/* 弹出详情 */
.node-popup {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 100;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border);
  border-radius: 10px;
  padding: 10px 12px;
  min-width: 200px;
  max-width: 320px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  display: flex;
  flex-direction: column;
  gap: 6px;
  animation: node-appear 0.2s ease both;
}
.block-popup { min-width: 220px; }
.popup-row { display: flex; gap: 8px; font-size: 12px; align-items: flex-start; }
.popup-key { font-weight: 600; color: var(--pf-text-dim); min-width: 60px; flex-shrink: 0; }
.err-key { color: #f87171; }
.err-txt { color: #f87171; font-size: 11px; word-break: break-all; }

/* 时间线（甘特图） */
.timeline-section {
  padding: 10px 14px;
  background: rgba(15, 23, 42, 0.4);
  border-radius: 10px;
  border: 1px solid var(--pf-border);
}
.tl-label { font-size: 11px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.timeline-bars { display: flex; flex-direction: column; gap: 6px; }
.tl-bar-row { display: flex; align-items: center; gap: 8px; }
.tl-node-name { font-size: 11px; width: 100px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl-bar-bg { flex: 1; height: 8px; background: var(--pf-panel-2); border-radius: 4px; overflow: hidden; }
.tl-bar-fill { height: 100%; border-radius: 4px; animation: tl-grow 0.8s ease both; }
.tl-dur { font-size: 10px; font-family: monospace; width: 48px; flex-shrink: 0; text-align: right; }

.dim { color: var(--pf-text-dim); }
</style>
