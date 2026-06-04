<script setup lang="ts">
import { Handle, Position, useVueFlow } from '@vue-flow/core'

const props = defineProps<{ id: string; data: { label: string; mode?: string }; selected?: boolean }>()
const { removeNodes } = useVueFlow()
</script>

<template>
  <div class="block-node" :class="{ 'is-selected': selected }">
    <Handle type="target" :position="Position.Left" />
    <div class="node-icon">⬢</div>
    <div class="node-body">
      <div class="node-label">{{ data.label }}</div>
      <div class="node-mode">{{ data.mode || 'sync_http' }}</div>
    </div>
    <Handle type="source" :position="Position.Right" />
    <button class="delete-btn nodrag" title="删除节点" @click.stop="removeNodes([props.id])">×</button>
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
.node-icon {
  font-size: 18px;
  color: var(--pf-accent);
}
.node-label {
  font-weight: 600;
}
.node-mode {
  font-size: 11px;
  color: var(--pf-text-dim);
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
