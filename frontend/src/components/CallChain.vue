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

const expandedId = ref<string | null>(null)

const nodeMeta: Record<string, { icon: string; accentColor: string; bgColor: string }> = {
  client:       { icon: 'M', accentColor: '#6b7280', bgColor: 'rgba(107,114,128,0.06)' },
  network:      { icon: 'N', accentColor: '#0891b2', bgColor: 'rgba(8,145,178,0.06)' },
  gateway:      { icon: 'G', accentColor: '#7c3aed', bgColor: 'rgba(124,58,237,0.06)' },
  service:      { icon: 'S', accentColor: '#2563eb', bgColor: 'rgba(37,99,235,0.06)' },
  auth:         { icon: 'A', accentColor: '#d97706', bgColor: 'rgba(217,119,6,0.06)' },
  orchestrator: { icon: 'O', accentColor: '#2563eb', bgColor: 'rgba(37,99,235,0.04)' },
  block:        { icon: 'B', accentColor: '#2563eb', bgColor: 'rgba(37,99,235,0.05)' },
  mq_broker:    { icon: 'R', accentColor: '#d97706', bgColor: 'rgba(217,119,6,0.06)' },
  mq_exchange:  { icon: 'E', accentColor: '#ea580c', bgColor: 'rgba(234,88,12,0.06)' },
  mq_route:     { icon: '→', accentColor: '#f59e0b', bgColor: 'rgba(245,158,11,0.05)' },
  mq_queue:     { icon: 'Q', accentColor: '#d97706', bgColor: 'rgba(217,119,6,0.06)' },
  filter:       { icon: 'F', accentColor: '#0d9488', bgColor: 'rgba(13,148,136,0.06)' },
  response:     { icon: '✓', accentColor: '#16a34a', bgColor: 'rgba(22,163,74,0.06)' },
}

const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  ok:        { color: '#16a34a', bg: 'rgba(22,163,74,0.08)',   label: 'OK' },
  done:      { color: '#16a34a', bg: 'rgba(22,163,74,0.08)',   label: '完成' },
  succeeded: { color: '#16a34a', bg: 'rgba(22,163,74,0.08)',   label: '成功' },
  success:   { color: '#16a34a', bg: 'rgba(22,163,74,0.08)',   label: '成功' },
  failed:    { color: '#dc2626', bg: 'rgba(220,38,38,0.08)',   label: '失败' },
  error:     { color: '#dc2626', bg: 'rgba(220,38,38,0.08)',   label: '错误' },
  nack:      { color: '#dc2626', bg: 'rgba(220,38,38,0.08)',   label: 'NACK' },
  running:   { color: '#d97706', bg: 'rgba(217,119,6,0.08)',   label: '运行中' },
  warning:   { color: '#d97706', bg: 'rgba(217,119,6,0.08)',   label: '警告' },
  skipped:   { color: '#9ca3af', bg: 'rgba(156,163,175,0.08)', label: '跳过' },
  unknown:   { color: '#9ca3af', bg: 'rgba(156,163,175,0.08)', label: '未知' },
}

const triggerInfo: Record<string, { label: string; color: string; icon: string }> = {
  http:   { label: 'HTTP API 调用',   color: '#2563eb', icon: 'H' },
  stream: { label: 'HTTP SSE 流式',  color: '#0891b2', icon: 'S' },
  mq:     { label: 'MQ 消息触发',    color: '#d97706', icon: 'M' },
  manual: { label: '手动触发',       color: '#6b7280', icon: '✦' },
}

function getMeta(type: string) {
  return nodeMeta[type] || nodeMeta['service']
}

function getStatus(status?: string) {
  return statusConfig[status || 'ok'] || statusConfig['unknown']
}

function isError(node: ChainNode) {
  return node.status === 'error' || node.status === 'failed' || node.status === 'nack'
}

function fmtDur(ms: number | null | undefined): string {
  if (ms == null) return ''
  if (ms >= 1000) return (ms / 1000).toFixed(2) + 's'
  return ms + 'ms'
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function onNodeClick(node: ChainNode) {
  toggleExpand(node.id)
  emit('nodeClick', node)
}

const maxDur = computed(() => {
  let m = 0
  for (const node of props.chain.nodes) {
    if (node.duration_ms) m = Math.max(m, node.duration_ms)
    if (node.children) for (const c of node.children) if (c.duration_ms) m = Math.max(m, c.duration_ms)
  }
  return m || 1
})

function durPct(ms: number | null | undefined) {
  return ms ? Math.min(100, (ms / maxDur.value) * 100) : 0
}

const tInfo = computed(() => triggerInfo[props.chain.type] || triggerInfo['manual'])

const childStats = computed(() => {
  const orch = props.chain.nodes.find(n => n.type === 'orchestrator')
  if (!orch?.children?.length) return null
  const total = orch.children.length
  const done = orch.children.filter(c => ['done','succeeded','success','ok'].includes(c.status||'')).length
  const failed = orch.children.filter(c => ['failed','error','nack'].includes(c.status||'')).length
  const skipped = orch.children.filter(c => c.status === 'skipped').length
  return { total, done, failed, skipped }
})

const timelineNodes = computed(() => {
  const items: ChainNode[] = []
  for (const n of props.chain.nodes) {
    if (n.type === 'orchestrator' && n.children?.length) items.push(...n.children)
    else if (n.duration_ms != null && n.type !== 'orchestrator') items.push(n)
  }
  return items.filter(n => n.duration_ms != null)
})
</script>

<template>
  <div class="cc-root">
    <!-- ── 顶部摘要栏 ── -->
    <div class="cc-summary-bar">
      <div class="cc-trigger-badge" :style="{ color: tInfo.color, borderColor: tInfo.color + '33', background: tInfo.color + '0d' }">
        <span class="trigger-icon">{{ tInfo.icon }}</span>
        <span>{{ tInfo.label }}</span>
      </div>

      <div class="cc-stats">
        <div v-if="chain.total_ms != null" class="stat-item">
          <span class="stat-label">总耗时</span>
          <span class="stat-value mono" :class="{ 'val-slow': (chain.total_ms || 0) > 5000 }">{{ fmtDur(chain.total_ms) }}</span>
        </div>
        <div v-if="childStats" class="stat-item">
          <span class="stat-label">节点</span>
          <span class="stat-value">
            <span class="val-ok">{{ childStats.done }}</span>
            <span class="stat-sep"> / </span>
            <span>{{ childStats.total }}</span>
            <span v-if="childStats.failed" class="val-err"> · {{ childStats.failed }} 失败</span>
            <span v-if="childStats.skipped" class="val-dim"> · {{ childStats.skipped }} 跳过</span>
          </span>
        </div>
        <div v-if="chain.status" class="stat-item">
          <span
            class="status-pill"
            :style="{ color: getStatus(chain.status).color, background: getStatus(chain.status).bg }"
          >{{ getStatus(chain.status).label }}</span>
        </div>
      </div>
    </div>

    <!-- ── 竖向链路 ── -->
    <div class="cc-chain">
      <template v-for="(node, i) in chain.nodes" :key="node.id">

        <!-- 普通节点卡片 -->
        <template v-if="node.type !== 'orchestrator'">
          <div
            class="cc-node"
            :class="{ 'cc-node--error': isError(node), 'cc-node--expanded': expandedId === node.id }"
            :style="{ '--accent': getMeta(node.type).accentColor, animationDelay: `${i * 55}ms` }"
            @click="onNodeClick(node)"
          >
            <!-- 左侧彩色竖条 -->
            <div class="node-accent-bar" />

            <!-- 图标区 -->
            <div class="node-icon-col">
              <div
                class="node-icon-circle"
                :style="{ background: getMeta(node.type).bgColor, color: getMeta(node.type).accentColor, borderColor: getMeta(node.type).accentColor + '40' }"
              >{{ getMeta(node.type).icon }}</div>
            </div>

            <!-- 内容区 -->
            <div class="node-content">
              <div class="node-main-row">
                <span class="node-label">{{ node.label }}</span>
                <div class="node-right">
                  <span v-if="node.note" class="node-note">{{ node.note }}</span>
                  <span v-if="node.duration_ms != null" class="node-dur mono" :class="{ 'val-slow': node.duration_ms > 3000 }">{{ fmtDur(node.duration_ms) }}</span>
                  <span
                    v-if="node.status"
                    class="status-dot"
                    :style="{ background: getStatus(node.status).color }"
                    :title="getStatus(node.status).label"
                  />
                </div>
              </div>
              <div class="node-detail-row" v-if="node.detail || node.sub">
                <span v-if="node.detail" class="node-detail">{{ node.detail }}</span>
                <span v-if="node.sub" class="node-sub">{{ node.sub }}</span>
              </div>
              <!-- 耗时进度条 -->
              <div v-if="node.duration_ms != null" class="node-progress">
                <div class="progress-fill" :style="{ width: durPct(node.duration_ms) + '%', background: getMeta(node.type).accentColor }" />
              </div>
            </div>

            <!-- 展开详情面板 -->
            <Transition name="expand">
              <div v-if="expandedId === node.id" class="node-expand-panel" @click.stop>
                <div class="ep-row" v-if="node.detail"><span class="ep-key">路径</span><span class="ep-val">{{ node.detail }}</span></div>
                <div class="ep-row" v-if="node.note"><span class="ep-key">备注</span><span class="ep-val">{{ node.note }}</span></div>
                <div class="ep-row" v-if="node.duration_ms != null"><span class="ep-key">耗时</span><span class="ep-val mono">{{ fmtDur(node.duration_ms) }}</span></div>
                <div class="ep-row" v-if="node.hit_port"><span class="ep-key">端口</span><span class="ep-val">{{ node.hit_port }}</span></div>
                <div class="ep-row ep-row--err" v-if="node.error"><span class="ep-key">错误</span><span class="ep-val">{{ node.error }}</span></div>
              </div>
            </Transition>
          </div>

          <!-- 竖向连接线 -->
          <div v-if="i < chain.nodes.length - 1" class="cc-connector" :style="{ animationDelay: `${i * 55 + 28}ms` }">
            <div class="connector-line" />
            <div class="connector-arrow" />
          </div>
        </template>

        <!-- Orchestrator 容器 -->
        <template v-else>
          <div
            class="cc-orch"
            :class="{ 'cc-orch--error': node.status === 'failed' }"
            :style="{ animationDelay: `${i * 55}ms` }"
          >
            <!-- 容器头部 -->
            <div class="orch-header" @click="onNodeClick(node)">
              <div
                class="node-icon-circle orch-icon"
                :style="{ background: 'rgba(37,99,235,0.08)', color: '#2563eb', borderColor: 'rgba(37,99,235,0.25)' }"
              >O</div>
              <span class="orch-label">{{ node.label }}</span>
              <span v-if="node.detail" class="orch-detail">{{ node.detail }}</span>
              <div class="orch-right">
                <span v-if="node.duration_ms != null" class="node-dur mono">{{ fmtDur(node.duration_ms) }}</span>
                <span v-if="node.status" class="status-pill" :style="{ color: getStatus(node.status).color, background: getStatus(node.status).bg }">{{ getStatus(node.status).label }}</span>
                <span class="orch-toggle" :class="{ rotated: expandedId === node.id }" @click.stop="toggleExpand(node.id)">›</span>
              </div>
            </div>

            <!-- 子节点列表（竖向排列） -->
            <div v-if="node.children?.length" class="orch-blocks">
              <template v-for="(child, ci) in node.children" :key="child.id">
                <div
                  class="block-node"
                  :class="{
                    'block-node--error': child.status === 'failed' || child.status === 'error',
                    'block-node--skip': child.status === 'skipped',
                    'block-node--expanded': expandedId === child.id,
                  }"
                  :style="{ '--accent': getStatus(child.status).color, animationDelay: `${i * 55 + ci * 60 + 80}ms` }"
                  @click="onNodeClick(child)"
                >
                  <!-- 序号 -->
                  <div class="block-seq">{{ ci + 1 }}</div>

                  <!-- 内容 -->
                  <div class="block-content">
                    <div class="block-main-row">
                      <span class="block-label">{{ child.label }}</span>
                      <div class="block-right">
                        <span v-if="child.hit_port" class="block-port">{{ child.hit_port }}</span>
                        <span v-if="child.duration_ms != null" class="node-dur mono" :class="{ 'val-slow': child.duration_ms > 3000 }">{{ fmtDur(child.duration_ms) }}</span>
                        <span
                          class="status-pill status-pill--sm"
                          :style="{ color: getStatus(child.status).color, background: getStatus(child.status).bg }"
                        >{{ getStatus(child.status).label }}</span>
                      </div>
                    </div>

                    <!-- 进度条 -->
                    <div v-if="child.duration_ms != null" class="node-progress" style="margin-top:6px">
                      <div class="progress-fill" :style="{ width: durPct(child.duration_ms) + '%', background: getStatus(child.status).color }" />
                    </div>

                    <!-- 错误信息 -->
                    <div v-if="isError(child) && child.error" class="block-error-msg">{{ child.error }}</div>
                  </div>

                  <!-- 展开详情 -->
                  <Transition name="expand">
                    <div v-if="expandedId === child.id" class="node-expand-panel" @click.stop>
                      <div class="ep-row" v-if="child.node_id"><span class="ep-key">节点 ID</span><code class="ep-code">{{ child.node_id.slice(0, 12) }}…</code></div>
                      <div class="ep-row" v-if="child.block_id"><span class="ep-key">块 ID</span><code class="ep-code">{{ child.block_id.slice(0, 12) }}…</code></div>
                      <div class="ep-row" v-if="child.duration_ms != null"><span class="ep-key">执行耗时</span><span class="ep-val mono">{{ fmtDur(child.duration_ms) }}</span></div>
                      <div class="ep-row" v-if="child.hit_port"><span class="ep-key">激活端口</span><span class="ep-val">{{ child.hit_port }}</span></div>
                      <div class="ep-row ep-row--err" v-if="child.error"><span class="ep-key">错误</span><span class="ep-val">{{ child.error }}</span></div>
                    </div>
                  </Transition>
                </div>

                <!-- 块间连接线 -->
                <div v-if="ci < (node.children?.length ?? 0) - 1" class="block-connector" :style="{ animationDelay: `${i * 55 + ci * 60 + 110}ms` }">
                  <div class="connector-line" style="height: 16px" />
                  <div class="connector-arrow" />
                </div>
              </template>
            </div>
            <div v-else class="orch-empty">暂无执行步骤</div>
          </div>

          <!-- Orchestrator 后连接线 -->
          <div v-if="i < chain.nodes.length - 1" class="cc-connector" :style="{ animationDelay: `${i * 55 + 28}ms` }">
            <div class="connector-line" />
            <div class="connector-arrow" />
          </div>
        </template>

      </template>
    </div>

    <!-- ── 耗时分布（甘特图） ── -->
    <div v-if="timelineNodes.length > 1" class="cc-timeline">
      <div class="tl-title">耗时分布</div>
      <div class="tl-list">
        <div v-for="n in timelineNodes" :key="`tl-${n.id}`" class="tl-row">
          <div class="tl-name">{{ n.label }}</div>
          <div class="tl-track">
            <div
              class="tl-fill"
              :style="{ width: durPct(n.duration_ms) + '%', background: getStatus(n.status).color }"
            />
          </div>
          <div class="tl-val mono">{{ fmtDur(n.duration_ms) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── 动画 ── */
@keyframes cc-fade-in {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes progress-grow {
  from { width: 0 !important; }
  to   { /* 由 style 决定 */ }
}
@keyframes connector-grow {
  from { opacity: 0; transform: scaleY(0.4); }
  to   { opacity: 1; transform: scaleY(1); }
}
@keyframes err-ring {
  0%,100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.15); }
  50%     { box-shadow: 0 0 0 5px rgba(220,38,38,0); }
}

.expand-enter-active { animation: cc-fade-in 0.2s ease; }
.expand-leave-active { animation: cc-fade-in 0.15s ease reverse; }

/* ── 根容器 ── */
.cc-root {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 2px;
}

/* ── 摘要栏 ── */
.cc-summary-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 16px;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border);
  border-radius: 10px;
  box-shadow: var(--pf-shadow-sm);
}
.cc-trigger-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 20px;
  border: 1px solid;
  letter-spacing: 0.2px;
}
.trigger-icon {
  font-size: 11px;
  font-weight: 800;
  font-style: normal;
}
.cc-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-left: auto;
  flex-wrap: wrap;
}
.stat-item { display: flex; align-items: center; gap: 6px; }
.stat-label { font-size: 12px; color: var(--pf-text-dim); }
.stat-value { font-size: 12px; color: var(--pf-text); font-weight: 500; }
.stat-sep { color: var(--pf-text-dim); }
.val-ok  { color: #16a34a; font-weight: 600; }
.val-err { color: #dc2626; font-weight: 600; }
.val-dim { color: #9ca3af; }
.val-slow { color: #d97706 !important; }
.mono { font-family: 'SF Mono', 'Fira Code', monospace; }

/* ── 竖向主链路容器 ── */
.cc-chain {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0;
}

/* ── 通用节点卡片 ── */
.cc-node {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border);
  border-radius: 10px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition: border-color 0.18s, box-shadow 0.18s, transform 0.18s;
  animation: cc-fade-in 0.38s ease both;
}
.cc-node:hover {
  border-color: var(--accent, var(--pf-accent));
  box-shadow: var(--pf-shadow-md);
  transform: translateY(-1px);
}
.cc-node--expanded {
  border-color: var(--pf-accent);
  box-shadow: 0 0 0 3px var(--pf-accent-soft);
}
.cc-node--error {
  border-color: rgba(220,38,38,0.35);
  animation: cc-fade-in 0.38s ease both, err-ring 2.2s ease infinite 0.5s;
}

/* 左侧彩色竖条 */
.node-accent-bar {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--accent, var(--pf-accent));
  border-radius: 10px 0 0 10px;
}

/* 图标圆圈 */
.node-icon-col { flex-shrink: 0; padding-top: 2px; }
.node-icon-circle {
  width: 32px; height: 32px;
  border-radius: 8px;
  border: 1px solid;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700;
  flex-shrink: 0;
  transition: transform 0.15s;
}
.cc-node:hover .node-icon-circle { transform: scale(1.05); }

/* 内容区 */
.node-content { flex: 1; min-width: 0; }
.node-main-row {
  display: flex; align-items: center;
  gap: 8px;
}
.node-label {
  font-size: 13px; font-weight: 600;
  color: var(--pf-text);
  flex: 1; min-width: 0;
}
.node-right {
  display: flex; align-items: center; gap: 8px;
  flex-shrink: 0;
}
.node-note {
  font-size: 11px; color: var(--pf-text-dim);
  background: var(--pf-panel-2);
  padding: 2px 6px; border-radius: 4px;
}
.node-dur {
  font-size: 12px; color: var(--pf-text-dim);
  font-weight: 500;
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  flex-shrink: 0;
}
.node-detail-row {
  margin-top: 4px;
  display: flex; gap: 8px;
}
.node-detail {
  font-size: 11px; color: var(--pf-text-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.node-sub {
  font-size: 11px; color: var(--pf-text-dim);
}

/* 进度条 */
.node-progress {
  height: 3px;
  background: var(--pf-border);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 8px;
}
.progress-fill {
  height: 100%; border-radius: 2px;
  animation: progress-grow 0.9s ease both;
  transition: width 0.3s ease;
}

/* 展开面板 */
.node-expand-panel {
  width: 100%;
  margin-top: 12px;
  padding: 10px 12px;
  background: var(--pf-panel-2);
  border-radius: 8px;
  display: flex; flex-direction: column; gap: 6px;
  grid-column: 1 / -1;
}
.ep-row {
  display: flex; align-items: flex-start; gap: 10px;
  font-size: 12px;
}
.ep-row--err .ep-key { color: #dc2626; }
.ep-row--err .ep-val { color: #dc2626; }
.ep-key {
  font-weight: 600; color: var(--pf-text-dim);
  min-width: 64px; flex-shrink: 0;
  font-size: 11px;
}
.ep-val { color: var(--pf-text); word-break: break-all; }
.ep-code {
  font-family: 'SF Mono','Fira Code',monospace;
  font-size: 11px; color: var(--pf-text);
  background: var(--pf-panel);
  padding: 1px 5px; border-radius: 4px;
  border: 1px solid var(--pf-border);
}

/* ── 竖向连接线 ── */
.cc-connector {
  display: flex; flex-direction: column; align-items: center;
  padding: 2px 0;
  animation: connector-grow 0.3s ease both;
  flex-shrink: 0;
}
.connector-line {
  width: 2px; height: 20px;
  background: linear-gradient(180deg, var(--pf-border) 0%, var(--pf-accent-soft) 100%);
  border-radius: 1px;
}
.connector-arrow {
  width: 0; height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid rgba(37,99,235,0.3);
  margin-top: -1px;
}

/* ── Orchestrator 容器 ── */
.cc-orch {
  border: 1.5px dashed rgba(37,99,235,0.25);
  border-radius: 12px;
  background: rgba(37,99,235,0.02);
  overflow: hidden;
  animation: cc-fade-in 0.4s ease both;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.cc-orch:hover { border-color: rgba(37,99,235,0.45); box-shadow: var(--pf-shadow-sm); }
.cc-orch--error { border-color: rgba(220,38,38,0.35); background: rgba(220,38,38,0.02); }

.orch-header {
  display: flex; align-items: center;
  gap: 10px; padding: 14px 16px 10px;
  cursor: pointer; border-bottom: 1px solid rgba(37,99,235,0.1);
  transition: background 0.15s;
}
.orch-header:hover { background: rgba(37,99,235,0.04); }
.orch-icon { flex-shrink: 0; }
.orch-label { font-size: 13px; font-weight: 600; color: var(--pf-text); }
.orch-detail { font-size: 11px; color: var(--pf-text-dim); }
.orch-right { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.orch-toggle {
  font-size: 18px; color: var(--pf-text-dim); font-weight: 300;
  transition: transform 0.2s; display: inline-block;
  cursor: pointer; user-select: none; line-height: 1;
}
.orch-toggle.rotated { transform: rotate(90deg); }
.orch-empty { padding: 16px; font-size: 12px; color: var(--pf-text-dim); text-align: center; }

/* 子节点列表 */
.orch-blocks {
  display: flex; flex-direction: column;
  padding: 12px 16px 14px;
  gap: 0;
}

/* Block 子节点 */
.block-node {
  display: flex; align-items: flex-start;
  gap: 10px; padding: 10px 14px;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border);
  border-radius: 8px;
  cursor: pointer;
  position: relative; overflow: hidden;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
  animation: cc-fade-in 0.35s ease both;
}
.block-node::before {
  content: '';
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 3px; border-radius: 8px 0 0 8px;
  background: var(--accent, #16a34a);
}
.block-node:hover {
  border-color: var(--accent, var(--pf-accent));
  box-shadow: var(--pf-shadow-sm);
  transform: translateY(-1px);
}
.block-node--expanded {
  border-color: var(--pf-accent);
  box-shadow: 0 0 0 2px var(--pf-accent-soft);
}
.block-node--error {
  border-color: rgba(220,38,38,0.3);
  animation: cc-fade-in 0.35s ease both, err-ring 2s ease infinite 0.5s;
}
.block-node--skip { opacity: 0.55; }

/* 序号 */
.block-seq {
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--pf-panel-2); border: 1px solid var(--pf-border);
  font-size: 11px; font-weight: 600; color: var(--pf-text-dim);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 1px;
}

.block-content { flex: 1; min-width: 0; }
.block-main-row { display: flex; align-items: center; gap: 8px; }
.block-label {
  font-size: 13px; font-weight: 600; color: var(--pf-text);
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.block-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.block-port {
  font-size: 11px; color: var(--pf-text-dim);
  background: var(--pf-panel-2); padding: 1px 6px;
  border-radius: 4px; border: 1px solid var(--pf-border);
  white-space: nowrap;
}
.block-error-msg {
  margin-top: 6px; padding: 6px 8px;
  background: rgba(220,38,38,0.05);
  border-left: 2px solid #dc2626;
  border-radius: 0 4px 4px 0;
  font-size: 11px; color: #dc2626;
  word-break: break-all;
}

/* 块间连接线（比外部连接线短一些） */
.block-connector {
  display: flex; flex-direction: column; align-items: center;
  padding: 0;
  animation: connector-grow 0.25s ease both;
}

/* 状态标签 */
.status-pill {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 10px;
  white-space: nowrap;
}
.status-pill--sm { font-size: 10px; padding: 1px 6px; }

/* ── 耗时分布 ── */
.cc-timeline {
  padding: 14px 16px;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border);
  border-radius: 10px;
  box-shadow: var(--pf-shadow-sm);
}
.tl-title {
  font-size: 11px; font-weight: 600;
  color: var(--pf-text-dim);
  text-transform: uppercase; letter-spacing: 0.6px;
  margin-bottom: 12px;
}
.tl-list { display: flex; flex-direction: column; gap: 8px; }
.tl-row { display: flex; align-items: center; gap: 10px; }
.tl-name {
  font-size: 12px; color: var(--pf-text);
  width: 110px; flex-shrink: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tl-track {
  flex: 1; height: 6px;
  background: var(--pf-panel-2);
  border-radius: 3px; overflow: hidden;
}
.tl-fill {
  height: 100%; border-radius: 3px;
  animation: progress-grow 0.9s ease both;
}
.tl-val {
  font-size: 11px; color: var(--pf-text-dim);
  width: 50px; flex-shrink: 0; text-align: right;
}
</style>
