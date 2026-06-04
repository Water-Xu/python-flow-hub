<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'

defineProps<{ data: { label: string; expression?: string } }>()
</script>

<template>
  <div class="cond-wrap">
    <Handle type="target" :position="Position.Left" />
    <div class="diamond">
      <div class="diamond-text">{{ data.label || '条件' }}</div>
    </div>
    <Handle id="true" type="source" :position="Position.Right" style="top: 30%" />
    <Handle id="false" type="source" :position="Position.Right" style="top: 70%" />
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
  background: linear-gradient(135deg, #3a2a1e, #4a3526);
  border: 1px solid #f59e0b;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.25);
}
.diamond:hover {
  transform: rotate(45deg) scale(1.05);
  box-shadow: 0 8px 22px rgba(245, 158, 11, 0.45);
}
.diamond-text {
  transform: rotate(-45deg);
  font-size: 12px;
  font-weight: 600;
  color: #fbbf24;
}
</style>
