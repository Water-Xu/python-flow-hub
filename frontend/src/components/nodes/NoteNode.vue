<script setup lang="ts">
import { computed } from 'vue'
import { useVueFlow } from '@vue-flow/core'

/**
 * 注释便签节点（纯视觉，不参与 DAG 执行）。
 * 无任何 Handle，不连入也不连出，仅用于在画布上添加说明文字。
 */
const props = defineProps<{
  id: string
  data: {
    /** 便签文字内容 */
    text: string
    /** 便签颜色主题：yellow（默认）| blue | green | red | purple */
    color?: string
  }
  selected?: boolean
}>()

const { removeNodes } = useVueFlow()

/** 颜色主题映射 */
const colorMap: Record<string, { bg: string; border: string; text: string; handle: string }> = {
  yellow: { bg: '#fffde7', border: '#f59e0b', text: '#78350f', handle: '#f59e0b' },
  blue:   { bg: '#eff6ff', border: '#3b82f6', text: '#1e3a8a', handle: '#3b82f6' },
  green:  { bg: '#f0fdf4', border: '#22c55e', text: '#14532d', handle: '#22c55e' },
  red:    { bg: '#fff1f2', border: '#f43f5e', text: '#881337', handle: '#f43f5e' },
  purple: { bg: '#faf5ff', border: '#a855f7', text: '#581c87', handle: '#a855f7' },
}

const theme = computed(() => colorMap[props.data.color || 'yellow'])
</script>

<template>
  <div
    class="note-node"
    :class="{ 'is-selected': selected }"
    :style="{
      '--note-bg':     theme.bg,
      '--note-border': theme.border,
      '--note-text':   theme.text,
    }"
  >
    <!-- 便签头部：图钉图标 + 颜色选择点 -->
    <div class="note-head nodrag">
      <span class="note-pin">📌</span>
      <div class="note-colors">
        <button
          v-for="(val, key) in colorMap"
          :key="key"
          class="note-color-dot"
          :style="{ background: val.border }"
          :class="{ active: (data.color || 'yellow') === key }"
          @click.stop="data.color = key"
        />
      </div>
    </div>

    <!-- 可编辑文字区域 -->
    <textarea
      v-model="data.text"
      class="note-text nodrag"
      placeholder="在此输入注释…"
      rows="4"
      @mousedown.stop
    />

    <!-- 删除按钮 -->
    <button class="delete-btn nodrag" title="删除便签" @click.stop="removeNodes([props.id])">×</button>
  </div>
</template>

<style scoped>
.note-node {
  position: relative;
  min-width: 180px;
  max-width: 280px;
  background: var(--note-bg);
  border: 1.5px solid var(--note-border);
  border-top: 4px solid var(--note-border);
  border-radius: 8px;
  box-shadow: 3px 3px 10px rgba(0,0,0,.08), 0 1px 3px rgba(0,0,0,.06);
  transition: transform .18s ease, box-shadow .18s ease;
  /* 模拟便签微旋转效果 */
  transform: rotate(-0.5deg);
}
.note-node:hover {
  transform: rotate(0deg) scale(1.02);
  box-shadow: 5px 5px 18px rgba(0,0,0,.14);
}
.note-node.is-selected {
  transform: rotate(0deg) scale(1.02);
  box-shadow: 0 0 0 2px var(--note-border), 5px 5px 18px rgba(0,0,0,.14);
}

/* ─── 头部 ───────────────────────────────────────────── */
.note-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px 4px;
}
.note-pin {
  font-size: 13px;
  user-select: none;
}

/* 颜色选择点 */
.note-colors {
  display: flex;
  gap: 4px;
}
.note-color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid transparent;
  cursor: pointer;
  padding: 0;
  transition: transform .15s ease, border-color .15s ease;
}
.note-color-dot:hover { transform: scale(1.3); }
.note-color-dot.active {
  border-color: rgba(0,0,0,.35);
  transform: scale(1.2);
}

/* ─── 文字区域 ───────────────────────────────────────── */
.note-text {
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 4px 10px 10px;
  background: transparent;
  border: none;
  outline: none;
  resize: vertical;
  font-size: 13px;
  line-height: 1.6;
  color: var(--note-text);
  font-family: inherit;
  min-height: 72px;
}
.note-text::placeholder {
  color: color-mix(in srgb, var(--note-text) 40%, transparent);
  font-style: italic;
}

/* ─── 删除按钮 ───────────────────────────────────────── */
.delete-btn {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #ef4444;
  color: #fff;
  border: 2px solid var(--note-bg);
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transform: scale(0.6);
  transition: opacity .15s ease, transform .15s ease;
  padding: 0;
  z-index: 10;
}
.note-node:hover .delete-btn,
.note-node.is-selected .delete-btn {
  opacity: 1;
  transform: scale(1);
}
.delete-btn:hover {
  background: #dc2626;
  transform: scale(1.15) !important;
}
</style>
