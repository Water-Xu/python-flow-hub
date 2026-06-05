<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position, useVueFlow } from '@vue-flow/core'

const props = defineProps<{
  id: string
  data: {
    label: string
    /** jmespath | jsonpath，默认 jmespath */
    condition_language?: string
    /** 求值表达式，如 value、header.type == 'order' */
    condition_expression?: string
    /** 表达式为真时激活的端口，固定为 "true" */
    true_port?: string
    /** 表达式为假时激活的端口，固定为 "false" */
    false_port?: string
  }
  selected?: boolean
}>()

const { removeNodes } = useVueFlow()

/** 截断显示用的表达式文本，超出 22 字符加省略号 */
const exprLabel = computed(() => {
  const e = props.data.condition_expression || ''
  return e.length > 22 ? e.slice(0, 22) + '…' : e
})

const hasExpr = computed(() => !!props.data.condition_expression)
const lang = computed(() => props.data.condition_language || 'jmespath')
</script>

<template>
  <div class="cond-wrap" :class="{ 'is-selected': selected }">
    <!-- 左侧：唯一入边 -->
    <Handle type="target" :position="Position.Left" class="port-target" />

    <!-- 菱形主体 -->
    <div class="diamond">
      <div class="diamond-inner">
        <div class="diamond-label">{{ data.label || '条件分支' }}</div>
        <!-- 语言徽章，无表达式时不显示 -->
        <transition name="badge-pop">
          <span v-if="hasExpr" class="lang-badge">{{ lang }}</span>
        </transition>
      </div>
    </div>

    <!-- 右侧 true 端口（直接在容器内，VueFlow 按 top 百分比定位） -->
    <Handle id="true" type="source" :position="Position.Right" style="top: 28%" />
    <!-- 端口标签：绝对定位浮在 handle 旁 -->
    <span class="port-label port-label-true">✓ True</span>

    <!-- 右侧 false 端口 -->
    <Handle id="false" type="source" :position="Position.Right" style="top: 72%" />
    <span class="port-label port-label-false">✗ False</span>

    <!-- 表达式预览（节点展开区域） -->
    <transition name="expr-slide">
      <div v-if="hasExpr" class="expr-preview">
        <span class="expr-icon">ƒ</span>
        <span class="expr-text">{{ exprLabel }}</span>
      </div>
    </transition>

    <!-- 未配置表达式时的提示 -->
    <transition name="expr-slide">
      <div v-if="!hasExpr" class="expr-hint">双击配置表达式</div>
    </transition>

    <!-- 删除按钮 -->
    <button class="delete-btn nodrag" title="删除节点" @click.stop="removeNodes([props.id])">×</button>
  </div>
</template>

<style scoped>
.cond-wrap {
  position: relative;
  width: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  /* 让 Handle 的 absolute 定位从容器计算 */
  padding: 4px 0 2px;
}

/* ─── 菱形 ─────────────────────────────────────────── */
.diamond {
  width: 90px;
  height: 90px;
  flex-shrink: 0;
  transform: rotate(45deg);
  background: #fff7ed;
  border: 1.5px solid #f59e0b;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.22s cubic-bezier(.34,1.56,.64,1),
              box-shadow 0.2s ease,
              border-color 0.2s ease,
              background 0.2s ease;
  box-shadow: 0 2px 8px rgba(245,158,11,.12);
}
.diamond:hover {
  transform: rotate(45deg) scale(1.07);
  box-shadow: 0 6px 18px rgba(245,158,11,.22);
}
.cond-wrap.is-selected .diamond {
  border-color: #d97706;
  background: #fffbeb;
  box-shadow: 0 0 0 2px rgba(245,158,11,.35), 0 6px 18px rgba(245,158,11,.2);
}
.diamond-inner {
  transform: rotate(-45deg);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.diamond-label {
  font-size: 12px;
  font-weight: 700;
  color: #b45309;
  text-align: center;
  line-height: 1.3;
  max-width: 62px;
  word-break: break-all;
}
.lang-badge {
  font-size: 9px;
  font-weight: 600;
  color: #92400e;
  background: rgba(245,158,11,.18);
  border-radius: 4px;
  padding: 1px 5px;
  letter-spacing: .03em;
  font-family: 'JetBrains Mono', monospace;
}

/* ─── 端口标签（绝对定位在节点右侧，对齐各 Handle） ─ */
.port-label {
  position: absolute;
  right: 16px;  /* 紧靠右侧 handle 左边 */
  font-size: 10px;
  font-weight: 600;
  padding: 2px 5px;
  border-radius: 4px;
  pointer-events: none;
  white-space: nowrap;
  transform: translateY(-50%);
}
.port-label-true  { top: 28%; color: #16a34a; background: rgba(22,163,74,.1); }
.port-label-false { top: 72%; color: #dc2626; background: rgba(220,38,38,.1); }

/* ─── 表达式预览 ─────────────────────────────────────── */
.expr-preview,
.expr-hint {
  margin-top: 6px;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(245,158,11,.08);
  border: 1px solid rgba(245,158,11,.2);
  border-radius: 6px;
  font-size: 11px;
  box-sizing: border-box;
}
.expr-icon {
  font-weight: 700;
  color: #b45309;
  font-family: 'JetBrains Mono', monospace;
  flex-shrink: 0;
}
.expr-text {
  color: #78350f;
  font-family: 'JetBrains Mono', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.expr-hint {
  color: #d97706;
  font-style: italic;
  justify-content: center;
  background: transparent;
  border-style: dashed;
}

/* ─── 删除按钮 ───────────────────────────────────────── */
.delete-btn {
  position: absolute;
  top: -4px;
  right: -4px;
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
  transition: opacity 0.15s ease, transform 0.15s ease;
  padding: 0;
  z-index: 10;
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

/* ─── 动画 ───────────────────────────────────────────── */
.badge-pop-enter-active { transition: opacity .2s ease, transform .2s cubic-bezier(.34,1.56,.64,1); }
.badge-pop-enter-from  { opacity: 0; transform: scale(0.5); }

.expr-slide-enter-active { transition: opacity .22s ease, transform .22s ease; }
.expr-slide-leave-active { transition: opacity .15s ease; }
.expr-slide-enter-from   { opacity: 0; transform: translateY(-4px); }
.expr-slide-leave-to     { opacity: 0; }
</style>
