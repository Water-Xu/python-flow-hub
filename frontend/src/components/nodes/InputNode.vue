<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'

defineProps<{ data: { key: string; value: string } }>()
</script>

<template>
  <div class="input-node">
    <div class="in-head">
      <span class="in-dot" />
      <span>测试输入</span>
    </div>
    <input
      v-model="data.key"
      class="nodrag in-key"
      placeholder="键名，如 value"
      @mousedown.stop
    />
    <textarea
      v-model="data.value"
      class="nodrag in-val"
      rows="2"
      placeholder="值（JSON 或纯文本）"
      @mousedown.stop
    />
    <Handle type="source" :position="Position.Right" />
  </div>
</template>

<style scoped>
.input-node {
  min-width: 180px;
  padding: 12px;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border-strong);
  border-left: 3px solid #10b981;
  border-radius: 12px;
  color: var(--pf-text);
  box-shadow: var(--pf-shadow-sm);
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}
.input-node:hover {
  transform: scale(1.02);
  border-color: #10b981;
  box-shadow: var(--pf-shadow-md);
}
.in-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #047857;
  margin-bottom: 8px;
}
.in-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}
.in-key,
.in-val {
  width: 100%;
  box-sizing: border-box;
  background: var(--pf-panel-2);
  border: 1px solid var(--pf-border);
  border-radius: 8px;
  color: var(--pf-text);
  padding: 6px 8px;
  font-size: 12px;
  outline: none;
  transition: border-color 0.15s ease;
}
.in-key:focus,
.in-val:focus {
  border-color: #10b981;
}
.in-key {
  margin-bottom: 6px;
}
.in-val {
  resize: vertical;
  font-family: 'JetBrains Mono', monospace;
}
</style>
