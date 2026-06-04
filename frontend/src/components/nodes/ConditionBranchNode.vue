<script setup lang="ts">
import { Handle, Position, useVueFlow } from '@vue-flow/core'

const props = defineProps<{ id: string; data: { label: string; expression?: string }; selected?: boolean }>()
const { removeNodes } = useVueFlow()
</script>

<template>
  <div class="cond-wrap" :class="{ 'is-selected': selected }">
    <Handle type="target" :position="Position.Left" />
    <div class="diamond">
      <div class="diamond-text">{{ data.label || '条件' }}</div>
    </div>
    <Handle id="true" type="source" :position="Position.Right" style="top: 30%" />
    <Handle id="false" type="source" :position="Position.Right" style="top: 70%" />
    <button class="delete-btn nodrag" title="删除节点" @click.stop="removeNodes([props.id])">×</button>
  </div>
</template>

<style scoped>
.cond-wrap {
  position: relative;
  width: 120px;
  height: 120px;
}
.diamond {
  width: 86px;
  height: 86px;
  margin: 17px;
  transform: rotate(45deg);
  background: #fff7ed;
  border: 1px solid #f59e0b;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  box-shadow: var(--pf-shadow-sm);
}
.diamond:hover {
  transform: rotate(45deg) scale(1.05);
  box-shadow: var(--pf-shadow-md);
}
.cond-wrap.is-selected .diamond {
  border-color: #d97706;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.3), var(--pf-shadow-md);
}
.diamond-text {
  transform: rotate(-45deg);
  font-size: 12px;
  font-weight: 600;
  color: #b45309;
}

.delete-btn {
  position: absolute;
  top: -4px;
  right: -4px;
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
.cond-wrap:hover .delete-btn,
.cond-wrap.is-selected .delete-btn {
  opacity: 1;
  transform: scale(1);
}
.delete-btn:hover {
  background: #dc2626;
  transform: scale(1.15) !important;
}
</style>
