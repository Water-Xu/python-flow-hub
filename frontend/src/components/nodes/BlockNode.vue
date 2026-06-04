<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'

defineProps<{ data: { label: string; mode?: string } }>()
</script>

<template>
  <div class="block-node">
    <Handle type="target" :position="Position.Left" />
    <div class="node-icon">⬢</div>
    <div class="node-body">
      <div class="node-label">{{ data.label }}</div>
      <div class="node-mode">{{ data.mode || 'sync_http' }}</div>
    </div>
    <Handle type="source" :position="Position.Right" />
  </div>
</template>

<style scoped>
.block-node {
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
</style>
