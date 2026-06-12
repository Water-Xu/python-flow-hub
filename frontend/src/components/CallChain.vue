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

const emit = defineEmits<{ nodeClick: [node: ChainNode] }>()

const expanded = ref<Record<string, boolean>>({})

function toggle(id: string) {
  expanded.value[id] = !expanded.value[id]
}
function onNodeClick(node: ChainNode) {
  toggle(node.id)
  emit('nodeClick', node)
}

// ─── 节点类型元数据 ───
const NODE_META: Record<string, { label: string; iconBg: string; iconColor: string; icon: string }> = {
  client:       { label: '客户端',   iconBg: '#f0f4ff', iconColor: '#4f46e5', icon: 'C' },
  network:      { label: '网络',     iconBg: '#ecfeff', iconColor: '#0891b2', icon: 'N' },
  gateway:      { label: '网关',     iconBg: '#f5f3ff', iconColor: '#7c3aed', icon: 'G' },
  service:      { label: '服务',     iconBg: '#eff6ff', iconColor: '#2563eb', icon: 'S' },
  auth:         { label: '鉴权',     iconBg: '#fffbeb', iconColor: '#d97706', icon: 'A' },
  orchestrator: { label: '编排',     iconBg: '#eff6ff', iconColor: '#2563eb', icon: 'O' },
  block:        { label: '调用块',   iconBg: '#f0fdf4', iconColor: '#16a34a', icon: 'B' },
  mq_broker:    { label: 'MQ 代理', iconBg: '#fff7ed', iconColor: '#ea580c', icon: 'R' },
  mq_exchange:  { label: '交换机',   iconBg: '#fff7ed', iconColor: '#ea580c', icon: 'E' },
  mq_route:     { label: '路由',     iconBg: '#fefce8', iconColor: '#ca8a04', icon: '→' },
  mq_queue:     { label: '队列',     iconBg: '#fff7ed', iconColor: '#ea580c', icon: 'Q' },
  filter:       { label: '过滤',     iconBg: '#f0fdfa', iconColor: '#0d9488', icon: 'F' },
  response:     { label: '响应',     iconBg: '#f0fdf4', iconColor: '#16a34a', icon: '✓' },
}

// ─── 状态配置 ───
const STATUS: Record<string, { color: string; bg: string; text: string; dot: string }> = {
  ok:        { color: '#16a34a', bg: '#dcfce7', text: '正常', dot: '#22c55e' },
  done:      { color: '#16a34a', bg: '#dcfce7', text: '完成', dot: '#22c55e' },
  succeeded: { color: '#16a34a', bg: '#dcfce7', text: '成功', dot: '#22c55e' },
  success:   { color: '#16a34a', bg: '#dcfce7', text: '成功', dot: '#22c55e' },
  failed:    { color: '#dc2626', bg: '#fee2e2', text: '失败', dot: '#ef4444' },
  error:     { color: '#dc2626', bg: '#fee2e2', text: '错误', dot: '#ef4444' },
  nack:      { color: '#dc2626', bg: '#fee2e2', text: 'NACK', dot: '#ef4444' },
  running:   { color: '#d97706', bg: '#fef3c7', text: '运行中', dot: '#f59e0b' },
  warning:   { color: '#d97706', bg: '#fef3c7', text: '警告',  dot: '#f59e0b' },
  skipped:   { color: '#6b7280', bg: '#f3f4f6', text: '跳过',  dot: '#9ca3af' },
  unknown:   { color: '#6b7280', bg: '#f3f4f6', text: '未知',  dot: '#9ca3af' },
}

const TRIGGER: Record<string, { label: string; color: string; bg: string }> = {
  http:   { label: 'HTTP API 调用',   color: '#2563eb', bg: '#eff6ff' },
  stream: { label: 'HTTP SSE 流式',  color: '#0891b2', bg: '#ecfeff' },
  mq:     { label: 'MQ 消息触发',    color: '#ea580c', bg: '#fff7ed' },
  manual: { label: '手动触发',       color: '#6b7280', bg: '#f9fafb' },
}

function getMeta(type: string) { return NODE_META[type] || NODE_META['service'] }
function getStatus(s?: string) { return STATUS[s || 'ok'] || STATUS['unknown'] }
function isErr(s?: string) { return s === 'failed' || s === 'error' || s === 'nack' }
function fmtMs(ms?: number | null) {
  if (ms == null || ms === 0) return null
  return ms >= 1000 ? (ms / 1000).toFixed(2) + 's' : ms + 'ms'
}

const triggerInfo = computed(() => TRIGGER[props.chain.type] || TRIGGER['manual'])

const maxDur = computed(() => {
  let m = 1
  const walk = (nodes: ChainNode[]) => {
    for (const n of nodes) {
      if (n.duration_ms) m = Math.max(m, n.duration_ms)
      if (n.children) walk(n.children)
    }
  }
  walk(props.chain.nodes)
  return m
})

function pct(ms?: number | null) { return ms ? Math.min(100, (ms / maxDur.value) * 100) : 0 }

const chainStats = computed(() => {
  const orch = props.chain.nodes.find(n => n.type === 'orchestrator')
  if (!orch?.children?.length) return null
  const total = orch.children.length
  const ok = orch.children.filter(c => ['done','succeeded','success','ok'].includes(c.status || '')).length
  const err = orch.children.filter(c => isErr(c.status)).length
  const skip = orch.children.filter(c => c.status === 'skipped').length
  return { total, ok, err, skip }
})

const timelineNodes = computed(() => {
  const items: ChainNode[] = []
  for (const n of props.chain.nodes) {
    if (n.type === 'orchestrator') {
      if (n.children?.length) items.push(...n.children.filter(c => c.duration_ms != null))
    } else if (n.duration_ms != null) {
      items.push(n)
    }
  }
  return items
})
</script>

<template>
  <div class="cc">
    <!-- ── 顶部摘要条 ── -->
    <div class="cc-bar">
      <span class="cc-trigger" :style="{ color: triggerInfo.color, background: triggerInfo.bg }">
        {{ triggerInfo.label }}
      </span>
      <div class="cc-bar-stats">
        <template v-if="chain.total_ms != null">
          <span class="cc-stat-label">总耗时</span>
          <span class="cc-stat-val" :class="{ 'cc-slow': chain.total_ms > 5000 }">{{ fmtMs(chain.total_ms) }}</span>
        </template>
        <template v-if="chainStats">
          <span class="cc-stat-sep">·</span>
          <span class="cc-stat-label">节点</span>
          <span class="cc-stat-val">
            <span class="cc-ok">{{ chainStats.ok }}</span>/<span>{{ chainStats.total }}</span>
            <span v-if="chainStats.err" class="cc-err"> · {{ chainStats.err }} 失败</span>
            <span v-if="chainStats.skip" class="cc-dim"> · {{ chainStats.skip }} 跳过</span>
          </span>
        </template>
        <template v-if="chain.status">
          <span class="cc-stat-sep">·</span>
          <span class="cc-status-pill" :style="{ color: getStatus(chain.status).color, background: getStatus(chain.status).bg }">
            {{ getStatus(chain.status).text }}
          </span>
        </template>
      </div>
    </div>

    <!-- ── 竖向链路 ── -->
    <div class="cc-chain">
      <template v-for="(node, i) in chain.nodes" :key="node.id">
        <!-- ── 普通节点 ── -->
        <template v-if="node.type !== 'orchestrator'">
          <div
            class="cc-card"
            :class="{ 'cc-card--err': isErr(node.status), 'cc-card--open': expanded[node.id] }"
            :style="{ '--ic': getMeta(node.type).iconColor, animationDelay: `${i * 50}ms` }"
            @click="onNodeClick(node)"
          >
            <!-- 彩色头条 -->
            <div class="cc-card-head" :style="{ background: getMeta(node.type).iconBg }">
              <div class="cc-icon" :style="{ background: getMeta(node.type).iconColor, color: '#fff' }">
                {{ getMeta(node.type).icon }}
              </div>
              <div class="cc-head-content">
                <span class="cc-node-label">{{ node.label }}</span>
                <span v-if="node.detail" class="cc-node-detail">{{ node.detail }}</span>
              </div>
              <div class="cc-head-right">
                <span v-if="node.sub" class="cc-node-sub">{{ node.sub }}</span>
                <span v-if="fmtMs(node.duration_ms)" class="cc-dur" :class="{ 'cc-slow': (node.duration_ms || 0) > 3000 }">
                  {{ fmtMs(node.duration_ms) }}
                </span>
                <span
                  class="cc-dot"
                  :style="{ background: getStatus(node.status).dot }"
                  :class="{ 'cc-dot--pulse': node.status === 'running' }"
                />
              </div>
            </div>

            <!-- 进度条（有耗时时展示） -->
            <div v-if="node.duration_ms != null && node.duration_ms > 0" class="cc-progress">
              <div class="cc-progress-fill" :style="{ width: pct(node.duration_ms) + '%', background: getMeta(node.type).iconColor }" />
            </div>

            <!-- 展开详情（独立行，不参与 flex） -->
            <Transition name="cc-expand">
              <div v-if="expanded[node.id]" class="cc-detail-panel" @click.stop>
                <div v-if="node.detail" class="cc-dp-row">
                  <span class="cc-dp-key">路径</span><span class="cc-dp-val">{{ node.detail }}</span>
                </div>
                <div v-if="fmtMs(node.duration_ms)" class="cc-dp-row">
                  <span class="cc-dp-key">耗时</span><span class="cc-dp-val cc-mono">{{ fmtMs(node.duration_ms) }}</span>
                </div>
                <div v-if="node.hit_port" class="cc-dp-row">
                  <span class="cc-dp-key">端口</span><span class="cc-dp-val">{{ node.hit_port }}</span>
                </div>
                <div v-if="node.error" class="cc-dp-row cc-dp-err">
                  <span class="cc-dp-key">错误</span><span class="cc-dp-val">{{ node.error }}</span>
                </div>
              </div>
            </Transition>
          </div>
        </template>

        <!-- ── Orchestrator 容器 ── -->
        <template v-else>
          <div
            class="cc-orch"
            :class="{ 'cc-orch--err': isErr(node.status) }"
            :style="{ animationDelay: `${i * 50}ms` }"
          >
            <!-- 容器头部 -->
            <div class="cc-orch-head" @click="onNodeClick(node)">
              <div class="cc-icon cc-icon--sm" :style="{ background: '#2563eb', color: '#fff' }">O</div>
              <span class="cc-orch-label">{{ node.label }}</span>
              <span v-if="node.detail" class="cc-orch-detail">{{ node.detail }}</span>
              <div class="cc-orch-right">
                <span v-if="fmtMs(node.duration_ms)" class="cc-dur">{{ fmtMs(node.duration_ms) }}</span>
                <span v-if="node.status" class="cc-status-pill" :style="{ color: getStatus(node.status).color, background: getStatus(node.status).bg }">
                  {{ getStatus(node.status).text }}
                </span>
              </div>
            </div>

            <!-- 子节点列表 -->
            <div v-if="node.children?.length" class="cc-blocks">
              <template v-for="(child, ci) in node.children" :key="child.id">
                <div
                  class="cc-block"
                  :class="{
                    'cc-block--err': isErr(child.status),
                    'cc-block--skip': child.status === 'skipped',
                    'cc-block--open': expanded[child.id],
                  }"
                  :style="{ '--bc': getStatus(child.status).dot, animationDelay: `${i * 50 + ci * 55 + 60}ms` }"
                  @click.stop="onNodeClick(child)"
                >
                  <!-- 块头部 -->
                  <div class="cc-block-head">
                    <div class="cc-block-seq">{{ ci + 1 }}</div>
                    <div class="cc-block-info">
                      <span class="cc-block-label">{{ child.label }}</span>
                    </div>
                    <div class="cc-block-right">
                      <span v-if="child.hit_port" class="cc-port">{{ child.hit_port }}</span>
                      <span v-if="fmtMs(child.duration_ms)" class="cc-dur cc-mono" :class="{ 'cc-slow': (child.duration_ms || 0) > 3000 }">
                        {{ fmtMs(child.duration_ms) }}
                      </span>
                      <span class="cc-status-pill cc-status-pill--sm" :style="{ color: getStatus(child.status).color, background: getStatus(child.status).bg }">
                        {{ getStatus(child.status).text }}
                      </span>
                    </div>
                  </div>

                  <!-- 进度条 -->
                  <div v-if="child.duration_ms != null && child.duration_ms > 0" class="cc-progress">
                    <div class="cc-progress-fill" :style="{ width: pct(child.duration_ms) + '%', background: getStatus(child.status).dot }" />
                  </div>

                  <!-- 展开详情 -->
                  <Transition name="cc-expand">
                    <div v-if="expanded[child.id]" class="cc-detail-panel" @click.stop>
                      <div v-if="child.node_id" class="cc-dp-row">
                        <span class="cc-dp-key">节点 ID</span><code class="cc-dp-code">{{ child.node_id.slice(0,12) }}…</code>
                      </div>
                      <div v-if="child.block_id" class="cc-dp-row">
                        <span class="cc-dp-key">块 ID</span><code class="cc-dp-code">{{ child.block_id.slice(0,12) }}…</code>
                      </div>
                      <div v-if="fmtMs(child.duration_ms)" class="cc-dp-row">
                        <span class="cc-dp-key">执行耗时</span><span class="cc-dp-val cc-mono">{{ fmtMs(child.duration_ms) }}</span>
                      </div>
                      <div v-if="child.hit_port" class="cc-dp-row">
                        <span class="cc-dp-key">激活端口</span><span class="cc-dp-val">{{ child.hit_port }}</span>
                      </div>
                      <div v-if="child.error" class="cc-dp-row cc-dp-err">
                        <span class="cc-dp-key">错误</span><span class="cc-dp-val">{{ child.error }}</span>
                      </div>
                    </div>
                  </Transition>
                </div>

                <!-- 块间连接 -->
                <div v-if="ci < (node.children?.length ?? 0) - 1" class="cc-mini-connector">
                  <div class="cc-mini-line" />
                  <div class="cc-mini-arrow" />
                </div>
              </template>
            </div>

            <div v-else class="cc-orch-empty">
              <span>Flow 内部执行步骤暂未采集</span>
            </div>
          </div>
        </template>

        <!-- ── 节点间连接线 ── -->
        <div v-if="i < chain.nodes.length - 1" class="cc-connector" :style="{ animationDelay: `${i * 50 + 25}ms` }">
          <div class="cc-conn-line" />
          <div class="cc-conn-arrow" />
        </div>
      </template>
    </div>

    <!-- ── 耗时分布 ── -->
    <div v-if="timelineNodes.length >= 2" class="cc-timeline">
      <div class="cc-tl-title">耗时分布</div>
      <div class="cc-tl-list">
        <div v-for="n in timelineNodes" :key="`tl-${n.id}`" class="cc-tl-row">
          <div class="cc-tl-name">{{ n.label }}</div>
          <div class="cc-tl-track">
            <div class="cc-tl-fill" :style="{ width: pct(n.duration_ms) + '%', background: getStatus(n.status).dot }" />
          </div>
          <div class="cc-tl-val cc-mono">{{ fmtMs(n.duration_ms) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── 动画 ── */
@keyframes cc-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes cc-progress-in {
  from { width: 0 !important; }
}
@keyframes cc-err-ring {
  0%,100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.12); }
  50%     { box-shadow: 0 0 0 6px rgba(220,38,38,0); }
}
@keyframes cc-dot-pulse {
  0%,100% { opacity: 1; transform: scale(1); }
  50%     { opacity: 0.6; transform: scale(0.8); }
}

.cc-expand-enter-active { animation: cc-in 0.2s ease; }
.cc-expand-leave-active { animation: cc-in 0.15s ease reverse; }

/* ── 根容器 ── */
.cc {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ── 摘要条 ── */
.cc-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.cc-trigger {
  font-size: 12px; font-weight: 600;
  padding: 3px 10px; border-radius: 20px;
  white-space: nowrap;
}
.cc-bar-stats {
  display: flex; align-items: center;
  gap: 6px; margin-left: auto;
  flex-wrap: wrap;
}
.cc-stat-label { font-size: 12px; color: #9ca3af; }
.cc-stat-val   { font-size: 12px; color: #374151; font-weight: 500; }
.cc-stat-sep   { color: #d1d5db; font-size: 12px; }
.cc-ok  { color: #16a34a; font-weight: 600; }
.cc-err { color: #dc2626; font-weight: 600; }
.cc-dim { color: #9ca3af; }
.cc-slow { color: #d97706 !important; }
.cc-mono { font-family: 'SF Mono','Fira Code',ui-monospace,monospace; }

/* ── 竖向链路 ── */
.cc-chain {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

/* ── 卡片通用 ── */
.cc-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;
  animation: cc-in 0.35s ease both;
}
.cc-card:hover {
  border-color: var(--ic, #2563eb);
  box-shadow: 0 4px 12px rgba(0,0,0,0.07);
  transform: translateY(-1px);
}
.cc-card--open {
  border-color: var(--ic, #2563eb);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.1);
}
.cc-card--err {
  border-color: rgba(220,38,38,0.3);
  animation: cc-in 0.35s ease both, cc-err-ring 2.4s ease infinite 0.6s;
}

/* ── 卡片彩色头条 ── */
.cc-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
}
.cc-icon {
  width: 32px; height: 32px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 800;
  flex-shrink: 0;
  letter-spacing: -0.5px;
}
.cc-icon--sm { width: 26px; height: 26px; font-size: 11px; border-radius: 6px; }

.cc-head-content {
  display: flex; flex-direction: column;
  gap: 1px; flex: 1; min-width: 0;
}
.cc-node-label  { font-size: 13px; font-weight: 600; color: #1f2329; }
.cc-node-detail { font-size: 11px; color: #6b7280; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cc-head-right  { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.cc-node-sub    { font-size: 11px; color: #6b7280; }
.cc-dur         { font-size: 12px; color: #374151; font-weight: 600; font-family: 'SF Mono','Fira Code',ui-monospace,monospace; }

.cc-dot {
  width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0;
}
.cc-dot--pulse { animation: cc-dot-pulse 1.2s ease-in-out infinite; }

/* ── 进度条 ── */
.cc-progress {
  height: 3px;
  background: #f3f4f6;
  margin: 0;
}
.cc-progress-fill {
  height: 100%;
  animation: cc-progress-in 0.8s ease both;
  transition: width 0.3s ease;
}

/* ── 展开详情面板（全宽，不参与 card-head flex）── */
.cc-detail-panel {
  padding: 10px 14px 12px;
  background: #f9fafb;
  border-top: 1px solid #f0f2f5;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cc-dp-row {
  display: flex; align-items: flex-start;
  gap: 10px; font-size: 12px;
}
.cc-dp-err .cc-dp-key { color: #dc2626; }
.cc-dp-err .cc-dp-val { color: #dc2626; }
.cc-dp-key {
  font-size: 11px; font-weight: 600; color: #9ca3af;
  min-width: 60px; flex-shrink: 0; padding-top: 1px;
}
.cc-dp-val { color: #374151; word-break: break-all; }
.cc-dp-code {
  font-family: 'SF Mono','Fira Code',ui-monospace,monospace;
  font-size: 11px; color: #374151;
  background: #fff; padding: 1px 5px;
  border-radius: 4px; border: 1px solid #e5e7eb;
}

/* ── 连接线 ── */
.cc-connector {
  display: flex; flex-direction: column; align-items: center;
  padding: 4px 0;
  animation: cc-in 0.25s ease both;
}
.cc-conn-line {
  width: 2px; height: 20px;
  background: linear-gradient(180deg, #e5e7eb 0%, #dbeafe 100%);
}
.cc-conn-arrow {
  width: 0; height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid #bfdbfe;
  margin-top: -1px;
}

/* ── Orchestrator 容器 ── */
.cc-orch {
  border: 1.5px dashed #bfdbfe;
  border-radius: 12px;
  overflow: hidden;
  background: #f8faff;
  animation: cc-in 0.38s ease both;
  transition: border-color 0.16s, box-shadow 0.16s;
}
.cc-orch:hover { border-color: #93c5fd; box-shadow: 0 2px 8px rgba(37,99,235,0.08); }
.cc-orch--err  { border-color: #fca5a5; background: #fff8f8; }

.cc-orch-head {
  display: flex; align-items: center;
  gap: 10px; padding: 12px 14px;
  background: #eff6ff;
  cursor: pointer;
  border-bottom: 1px dashed #bfdbfe;
  transition: background 0.15s;
}
.cc-orch-head:hover { background: #dbeafe; }
.cc-orch-label  { font-size: 13px; font-weight: 700; color: #1e40af; }
.cc-orch-detail { font-size: 11px; color: #3b82f6; font-family: 'SF Mono','Fira Code',ui-monospace,monospace; }
.cc-orch-right  { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.cc-orch-empty  { padding: 14px; text-align: center; font-size: 12px; color: #9ca3af; }

/* ── 块列表 ── */
.cc-blocks {
  display: flex; flex-direction: column;
  padding: 10px 12px 12px;
  gap: 0;
}

/* ── 单个块 ── */
.cc-block {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-left: 3px solid var(--bc, #22c55e);
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.14s, box-shadow 0.14s, transform 0.14s;
  animation: cc-in 0.32s ease both;
}
.cc-block:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  transform: translateX(2px);
}
.cc-block--open  { box-shadow: 0 0 0 2px rgba(37,99,235,0.15); }
.cc-block--err   { border-left-color: #ef4444; animation: cc-in 0.32s ease both, cc-err-ring 2s ease infinite 0.5s; }
.cc-block--skip  { opacity: 0.55; }

.cc-block-head {
  display: flex; align-items: center;
  gap: 10px; padding: 9px 12px;
}
.cc-block-seq {
  width: 22px; height: 22px; border-radius: 50%;
  background: #f3f4f6; border: 1px solid #e5e7eb;
  font-size: 11px; font-weight: 700; color: #6b7280;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.cc-block-info { flex: 1; min-width: 0; }
.cc-block-label { font-size: 13px; font-weight: 600; color: #1f2329; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.cc-block-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.cc-port {
  font-size: 10px; color: #6b7280;
  background: #f3f4f6; padding: 1px 6px;
  border-radius: 4px; border: 1px solid #e5e7eb;
}

/* 块间连接 */
.cc-mini-connector {
  display: flex; flex-direction: column; align-items: flex-start;
  padding: 2px 0 2px 22px; /* 对齐序号中心 */
}
.cc-mini-line {
  width: 2px; height: 10px;
  background: #e5e7eb;
  margin-left: 10px;
}
.cc-mini-arrow {
  width: 0; height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid #d1d5db;
  margin-left: 8px; margin-top: -1px;
}

/* ── 状态标签 ── */
.cc-status-pill {
  font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 10px;
  white-space: nowrap; flex-shrink: 0;
}
.cc-status-pill--sm { font-size: 10px; padding: 1px 6px; }

/* ── 耗时分布 ── */
.cc-timeline {
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.cc-tl-title {
  font-size: 11px; font-weight: 600; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.7px;
  margin-bottom: 10px;
}
.cc-tl-list { display: flex; flex-direction: column; gap: 7px; }
.cc-tl-row  { display: flex; align-items: center; gap: 10px; }
.cc-tl-name { font-size: 12px; color: #374151; width: 100px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cc-tl-track { flex: 1; height: 6px; background: #f3f4f6; border-radius: 3px; overflow: hidden; }
.cc-tl-fill  { height: 100%; border-radius: 3px; animation: cc-progress-in 0.9s ease both; }
.cc-tl-val   { font-size: 11px; color: #6b7280; width: 50px; flex-shrink: 0; text-align: right; }
</style>
