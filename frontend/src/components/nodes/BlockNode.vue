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
  background: linear-gradient(135deg, #1e2230, #262b3d);
  border: 1px solid var(--pf-accent);
  border-radius: 12px;
  color: var(--pf-text);
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.2);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.block-node:hover {
  transform: scale(1.03);
  box-shadow: 0 8px 22px rgba(99, 102, 241, 0.4);
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
