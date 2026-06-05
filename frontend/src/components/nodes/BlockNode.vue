<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position, useVueFlow } from '@vue-flow/core'

const props = defineProps<{
  id: string
  data: { label: string; mode?: string; entrypoint?: string; invalid?: boolean }
  selected?: boolean
}>()
const { removeNodes } = useVueFlow()

// 无合法入口的脚本（如 pack.py）：置灰且禁用交互，不参与编排
const isInvalid = computed(() => props.data?.invalid === true)
</script>

<template>
  <div
    class="block-node"
    :class="{ 'is-selected': selected, 'is-invalid': isInvalid }"
  >
    <Handle type="target" :position="Position.Left" :connectable="!isInvalid" />
    <div class="node-icon">⬢</div>
    <div class="node-body">
      <div class="node-label">{{ data.label }}</div>
      <div class="node-meta">
        <span class="node-mode">{{ data.mode || 'sync_http' }}</span>
        <transition name="fn-pop">
          <span v-if="isInvalid" class="node-tag-invalid">无入口</span>
        </transition>
        <transition name="fn-pop">
          <span v-if="!isInvalid && data.entrypoint && data.entrypoint !== 'run'" class="node-fn">
            ƒ {{ data.entrypoint }}
          </span>
        </transition>
      </div>
    </div>
    <Handle type="source" :position="Position.Right" :connectable="!isInvalid" />
    <button
      v-if="!isInvalid"
      class="delete-btn nodrag"
      title="删除节点"
      @click.stop="removeNodes([props.id])"
    >×</button>
  </div>
</template>

<style scoped>
.block-node {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 160px;
  padding: 12px 14px;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border-strong);
  border-left: 3px solid var(--pf-accent);
  border-radius: 12px;
  color: var(--pf-text);
  box-shadow: var(--pf-shadow-sm);
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}
.block-node:hover {
  transform: scale(1.03);
  border-color: var(--pf-accent);
  box-shadow: var(--pf-shadow-md);
}
.block-node.is-selected {
  border-color: var(--pf-accent);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.25), var(--pf-shadow-md);
}
.block-node.is-invalid {
  opacity: 0.45;
  filter: grayscale(1);
  border-left-color: var(--pf-text-dim);
  cursor: not-allowed;
  pointer-events: none;
}
.block-node.is-invalid:hover {
  transform: none;
  border-color: var(--pf-border-strong);
  box-shadow: var(--pf-shadow-sm);
}
.node-tag-invalid {
  font-size: 11px;
  font-weight: 600;
  color: var(--pf-text-dim);
  background: rgba(120, 120, 120, 0.18);
  border-radius: 6px;
  padding: 1px 6px;
}
.node-icon {
  font-size: 18px;
  color: var(--pf-accent);
}
.node-label {
  font-weight: 600;
}
.node-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.node-mode {
  font-size: 11px;
  color: var(--pf-text-dim);
}
.node-fn {
  font-size: 11px;
  font-weight: 600;
  color: var(--pf-accent);
  background: rgba(37, 99, 235, 0.1);
  border-radius: 6px;
  padding: 1px 6px;
  font-family: 'JetBrains Mono', monospace;
}
.fn-pop-enter-active,
.fn-pop-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.fn-pop-enter-from,
.fn-pop-leave-to {
  opacity: 0;
  transform: scale(0.7);
}

.delete-btn {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #ef4444;
  color: #fff;
  border: 2px solid var(--pf-panel);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transform: scale(0.6);
  transition: opacity 0.15s ease, transform 0.15s ease;
  padding: 0;
}
.block-node:hover .delete-btn,
.block-node.is-selected .delete-btn {
  opacity: 1;
  transform: scale(1);
}
.delete-btn:hover {
  background: #dc2626;
  transform: scale(1.15) !important;
}
</style>
