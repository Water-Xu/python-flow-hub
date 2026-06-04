<script setup lang="ts">
import { Handle, Position, useVueFlow } from '@vue-flow/core'

const props = defineProps<{ id: string; data: { key: string; value: string }; selected?: boolean }>()
const { removeNodes } = useVueFlow()
</script>

<template>
  <div class="input-node" :class="{ 'is-selected': selected }">
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
    <button class="delete-btn nodrag" title="删除节点" @click.stop="removeNodes([props.id])">×</button>
  </div>
</template>

<style scoped>
.input-node {
  position: relative;
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
.input-node.is-selected {
  border-color: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.25), var(--pf-shadow-md);
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
.input-node:hover .delete-btn,
.input-node.is-selected .delete-btn {
  opacity: 1;
  transform: scale(1);
}
.delete-btn:hover {
  background: #dc2626;
  transform: scale(1.15) !important;
}
</style>
