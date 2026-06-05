<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position, useVueFlow } from '@vue-flow/core'

/** 单个分支定义 */
export interface SwitchBranch {
  /** 匹配值（字符串比较） */
  value: string
  /** 对应的出边端口 ID，需与画布连线 sourceHandle 一致 */
  port: string
  /** 可选展示标签 */
  label?: string
}

const props = defineProps<{
  id: string
  data: {
    label: string
    /** jsonpath/jmespath 字段路径，如 $.header.type 或 header.type */
    switch_field?: string
    /** jmespath | jsonpath，默认 jsonpath */
    condition_language?: string
    /** 分支列表，顺序决定端口垂直排列顺序 */
    branches?: SwitchBranch[]
    /** 无分支命中时走的默认端口 */
    default_port?: string
  }
  selected?: boolean
}>()

const { removeNodes } = useVueFlow()

/** 组合所有出边端口（分支 + 默认） */
const allPorts = computed(() => {
  const result = (props.data.branches || []).map((b) => ({
    port: b.port,
    label: b.label || b.value,
    isDefault: false,
  }))
  result.push({
    port: props.data.default_port || 'default',
    label: '默认',
    isDefault: true,
  })
  return result
})

/** 字段路径截断显示 */
const fieldLabel = computed(() => {
  const f = props.data.switch_field || ''
  return f.length > 20 ? f.slice(0, 20) + '…' : f
})

const hasField = computed(() => !!props.data.switch_field)

/** 每个端口的垂直位置（百分比），均匀分布 */
function portTop(idx: number, total: number): string {
  return `${((idx + 1) / (total + 1)) * 100}%`
}
</script>

<template>
  <div class="sw-node" :class="{ 'is-selected': selected }">
    <!-- 左侧：唯一入边 -->
    <Handle type="target" :position="Position.Left" class="sw-port-target" />

    <!-- 节点主体 -->
    <div class="sw-body">
      <!-- 头部：图标 + 标题 -->
      <div class="sw-head">
        <span class="sw-icon">⇄</span>
        <span class="sw-label">{{ data.label || 'Switch' }}</span>
        <span class="sw-lang-badge">{{ data.condition_language || 'jsonpath' }}</span>
      </div>

      <!-- 字段路径 -->
      <div class="sw-field">
        <span class="sw-field-key">字段：</span>
        <span v-if="hasField" class="sw-field-val">{{ fieldLabel }}</span>
        <span v-else class="sw-field-empty">双击配置</span>
      </div>

      <!-- 分支预览列表 -->
      <div class="sw-branches">
        <div
          v-for="b in data.branches || []"
          :key="b.port"
          class="sw-branch-item"
        >
          <span class="sw-branch-val">"{{ b.value }}"</span>
          <span class="sw-branch-arrow">→</span>
          <span class="sw-branch-port">{{ b.label || b.port }}</span>
        </div>
        <div class="sw-branch-item sw-branch-default">
          <span class="sw-branch-val">其他</span>
          <span class="sw-branch-arrow">→</span>
          <span class="sw-branch-port">{{ data.default_port || 'default' }}</span>
        </div>
      </div>
    </div>

    <!-- 右侧动态出边端口（每个分支 + 默认各一个） -->
    <Handle
      v-for="(p, idx) in allPorts"
      :key="p.port"
      :id="p.port"
      type="source"
      :position="Position.Right"
      :style="{ top: portTop(idx, allPorts.length) }"
      :class="['sw-port-source', p.isDefault ? 'sw-port-default' : 'sw-port-case']"
    />

    <!-- 右侧端口标签（浮在节点外） -->
    <div
      v-for="(p, idx) in allPorts"
      :key="`lbl-${p.port}`"
      class="sw-port-label"
      :class="{ 'sw-port-label-default': p.isDefault }"
      :style="{ top: portTop(idx, allPorts.length) }"
    >
      {{ p.label }}
    </div>

    <!-- 删除按钮 -->
    <button class="delete-btn nodrag" title="删除节点" @click.stop="removeNodes([props.id])">×</button>
  </div>
</template>

<style scoped>
.sw-node {
  position: relative;
  min-width: 200px;
  max-width: 240px;
  background: var(--pf-panel, #fff);
  border: 1.5px solid #8b5cf6;
  border-left: 4px solid #7c3aed;
  border-radius: 12px;
  box-shadow: 0 2px 10px rgba(124,58,237,.1);
  /* 右侧预留端口标签空间 */
  padding-right: 52px;
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.sw-node:hover {
  transform: scale(1.025);
  box-shadow: 0 6px 20px rgba(124,58,237,.18);
}
.sw-node.is-selected {
  border-color: #6d28d9;
  box-shadow: 0 0 0 2px rgba(124,58,237,.3), 0 6px 20px rgba(124,58,237,.2);
}

/* ─── 主体内容 ───────────────────────────────────────── */
.sw-body {
  padding: 10px 8px 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sw-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sw-icon {
  font-size: 16px;
  color: #7c3aed;
}
.sw-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--pf-text, #1e293b);
  flex: 1;
}
.sw-lang-badge {
  font-size: 9px;
  font-weight: 600;
  color: #6d28d9;
  background: rgba(124,58,237,.12);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: .03em;
}

/* 字段路径行 */
.sw-field {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 3px 6px;
  background: rgba(124,58,237,.06);
  border-radius: 6px;
}
.sw-field-key { color: #7c3aed; font-weight: 600; }
.sw-field-val { color: #4c1d95; font-family: 'JetBrains Mono', monospace; }
.sw-field-empty { color: #a78bfa; font-style: italic; }

/* 分支列表 */
.sw-branches {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.sw-branch-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 4px;
  border-radius: 4px;
  background: rgba(124,58,237,.04);
}
.sw-branch-default {
  background: rgba(124,58,237,.1);
}
.sw-branch-val  { color: #4c1d95; font-family: 'JetBrains Mono', monospace; flex: 1; }
.sw-branch-arrow { color: #a78bfa; }
.sw-branch-port { color: #7c3aed; font-weight: 600; font-size: 10px; }

/* ─── 端口 ───────────────────────────────────────────── */
.sw-port-source {
  background: #8b5cf6 !important;
  border-color: #7c3aed !important;
  width: 10px !important;
  height: 10px !important;
  transition: transform .15s ease, background .15s ease;
}
.sw-port-source:hover {
  transform: scale(1.4) !important;
  background: #6d28d9 !important;
}
.sw-port-default {
  background: #a78bfa !important;
  border-color: #8b5cf6 !important;
}
.sw-port-target {
  background: #8b5cf6 !important;
  border-color: #7c3aed !important;
}

/* 端口标签（浮在节点右侧边框外） */
.sw-port-label {
  position: absolute;
  right: 18px;
  transform: translateY(-50%);
  font-size: 10px;
  font-weight: 600;
  color: #6d28d9;
  background: rgba(124,58,237,.1);
  border-radius: 4px;
  padding: 1px 5px;
  pointer-events: none;
  white-space: nowrap;
}
.sw-port-label-default {
  color: #7c3aed;
  background: rgba(124,58,237,.18);
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
  border: 2px solid var(--pf-panel, #fff);
  font-size: 13px;
  line-height: 1;
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
.sw-node:hover .delete-btn,
.sw-node.is-selected .delete-btn {
  opacity: 1;
  transform: scale(1);
}
.delete-btn:hover {
  background: #dc2626;
  transform: scale(1.15) !important;
}
</style>
