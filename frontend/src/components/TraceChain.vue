<script setup lang="ts">
defineProps<{
  steps: any[]
  executions?: any[]
  triggerSource?: string
  triggerInfo?: { api_name?: string; api_path?: string; mq_topic?: string }
}>()

const statusColor: Record<string, string> = {
  done: '#22c55e',
  failed: '#ef4444',
  skipped: '#94a3b8',
  running: '#f59e0b',
}
const statusBg: Record<string, string> = {
  done: 'rgba(34,197,94,0.08)',
  failed: 'rgba(239,68,68,0.1)',
  skipped: 'rgba(148,163,184,0.06)',
  running: 'rgba(245,158,11,0.08)',
}

function shortId(id: string) {
  return (id || '').slice(0, 8)
}
</script>

<template>
  <div class="trace-chain">
    <!-- 触发源节点 -->
    <div class="chain-node-wrap" style="animation-delay:0ms">
      <div class="trigger-node" :class="`trigger-${triggerSource || 'manual'}`">
        <span class="trigger-label">
          <template v-if="triggerSource === 'http'">API</template>
          <template v-else-if="triggerSource === 'stream'">SSE</template>
          <template v-else-if="triggerSource === 'mq'">MQ</template>
          <template v-else>手动</template>
        </span>
      </div>
      <div class="node-name-under" v-if="triggerInfo?.api_name">
        {{ triggerInfo.api_name }}
      </div>
      <div class="node-name-under dim" v-else-if="triggerInfo?.mq_topic">
        {{ triggerInfo.mq_topic }}
      </div>
    </div>

    <!-- 步骤节点 -->
    <template v-for="(step, i) in steps" :key="i">
      <!-- 箭头 -->
      <div class="chain-arrow" :style="{ animationDelay: `${i * 60 + 80}ms` }">
        <div class="arrow-line" />
        <span v-if="step.hit_port" class="arrow-port">{{ step.hit_port }}</span>
        <div class="arrow-tip">▶</div>
      </div>

      <!-- 步骤节点卡片 -->
      <div
        class="chain-node-wrap"
        :style="{ animationDelay: `${i * 60 + 100}ms` }"
      >
        <div
          class="step-node"
          :class="{ 'node-fail': step.status === 'failed', 'node-skip': step.status === 'skipped' }"
          :style="{
            borderColor: statusColor[step.status] || '#334155',
            background: statusBg[step.status] || 'rgba(30,41,59,0.5)',
          }"
        >
          <div class="node-status-bar" :style="{ background: statusColor[step.status] || '#475569' }" />
          <div class="node-inner">
            <div class="node-title">{{ step.node_name || shortId(step.node_id) }}</div>
            <div class="node-footer">
              <span class="node-status-txt" :style="{ color: statusColor[step.status] || '#94a3b8' }">
                {{ step.status }}
              </span>
              <span class="node-dur dim" v-if="step.duration_ms != null">{{ step.duration_ms }}ms</span>
            </div>
          </div>
        </div>
        <div class="node-name-under dim" v-if="step.node_name">
          <code>{{ shortId(step.node_id) }}</code>
        </div>
      </div>
    </template>

    <!-- 末端箭头 + END 节点 -->
    <template v-if="steps.length">
      <div class="chain-arrow" :style="{ animationDelay: `${steps.length * 60 + 80}ms` }">
        <div class="arrow-line" />
        <div class="arrow-tip">▶</div>
      </div>
      <div class="chain-node-wrap" :style="{ animationDelay: `${steps.length * 60 + 120}ms` }">
        <div class="end-node">END</div>
      </div>
    </template>

    <div class="chain-empty dim" v-if="!steps.length">暂无执行步骤</div>
  </div>
</template>

<style scoped>
@keyframes chain-appear {
  from { opacity: 0; transform: translateY(6px) scale(0.96); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

.trace-chain {
  display: flex;
  align-items: flex-start;
  gap: 0;
  padding: 14px 4px;
  overflow-x: auto;
  min-height: 92px;
  /* 自定义滚动条 */
  scrollbar-width: thin;
  scrollbar-color: var(--pf-border) transparent;
}

.chain-node-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  animation: chain-appear 0.35s ease both;
}

/* 触发源节点 */
.trigger-node {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
}
.trigger-http {
  background: rgba(79,70,229,0.12);
  border: 2px solid rgba(99,102,241,0.45);
  box-shadow: 0 0 10px rgba(79,70,229,0.15);
}
.trigger-stream {
  background: rgba(8,145,178,0.12);
  border: 2px solid rgba(6,182,212,0.45);
  box-shadow: 0 0 10px rgba(8,145,178,0.15);
}
.trigger-mq {
  background: rgba(245,158,11,0.12);
  border: 2px solid rgba(251,191,36,0.45);
  box-shadow: 0 0 10px rgba(245,158,11,0.15);
}
.trigger-manual {
  background: rgba(148,163,184,0.1);
  border: 2px dashed rgba(148,163,184,0.35);
}
.trigger-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.trigger-http .trigger-label { color: #818cf8; }
.trigger-stream .trigger-label { color: #22d3ee; }
.trigger-mq .trigger-label { color: #fbbf24; }
.trigger-manual .trigger-label { color: #94a3b8; }

/* 箭头 */
.chain-arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: 19px;
  padding: 19px 2px 0;
  flex-shrink: 0;
  width: 48px;
  position: relative;
  animation: chain-appear 0.3s ease both;
}
.arrow-line {
  height: 2px;
  width: 32px;
  background: linear-gradient(90deg, var(--pf-border), rgba(99,102,241,0.4));
  border-radius: 1px;
}
.arrow-tip {
  position: absolute;
  right: 2px;
  top: 18px;
  font-size: 9px;
  color: rgba(99,102,241,0.6);
  transform: translateY(-50%);
}
.arrow-port {
  position: absolute;
  top: 4px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  color: var(--pf-accent);
  background: var(--pf-panel-2);
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid var(--pf-border);
  white-space: nowrap;
  max-width: 70px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 步骤节点 */
.step-node {
  width: 116px;
  border-radius: 10px;
  border: 1.5px solid;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.step-node:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 18px rgba(0,0,0,0.25);
}
.node-fail {
  animation: fail-pulse 0.4s ease;
}
.node-fail:hover { box-shadow: 0 6px 18px rgba(239,68,68,0.2); }
@keyframes fail-pulse {
  0%,100% { transform: translateX(0); }
  25% { transform: translateX(-3px); }
  75% { transform: translateX(3px); }
}
.node-skip { opacity: 0.55; }

.node-status-bar { height: 3px; width: 100%; }
.node-inner { padding: 7px 9px; }
.node-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--pf-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.node-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
}
.node-status-txt {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.node-dur { font-size: 10px; font-family: monospace; }

/* END 节点 */
.end-node {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(148,163,184,0.08);
  border: 2px dashed rgba(148,163,184,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  color: var(--pf-text-dim);
  font-weight: 700;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

/* 节点下方 */
.node-name-under {
  font-size: 10px;
  max-width: 116px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-name-under code {
  font-size: 10px;
  color: var(--pf-accent);
  opacity: 0.7;
}

.chain-empty { font-size: 13px; padding: 8px 4px; }
.dim { color: var(--pf-text-dim); }
</style>
