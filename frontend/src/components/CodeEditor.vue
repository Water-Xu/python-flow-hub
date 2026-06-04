<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps<{ modelValue: string; language?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const el = ref<HTMLElement>()
let editor: monaco.editor.IStandaloneCodeEditor | null = null

onMounted(() => {
  if (!el.value) return
  editor = monaco.editor.create(el.value, {
    value: props.modelValue,
    language: props.language || 'python',
    theme: 'vs',
    automaticLayout: true,
    minimap: { enabled: false },
    fontSize: 14,
    scrollBeyondLastLine: false,
    padding: { top: 12 },
  })
  editor.onDidChangeModelContent(() => {
    emit('update:modelValue', editor!.getValue())
  })
})

watch(
  () => props.modelValue,
  (v) => {
    if (editor && v !== editor.getValue()) editor.setValue(v)
  },
)

onBeforeUnmount(() => editor?.dispose())
</script>

<template>
  <div ref="el" class="code-editor" />
</template>

<style scoped>
.code-editor {
  width: 100%;
  height: 100%;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--pf-border);
}
</style>
