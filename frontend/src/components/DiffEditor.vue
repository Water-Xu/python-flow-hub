<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps<{ original: string; modified: string; language?: string }>()

const el = ref<HTMLElement>()
let editor: monaco.editor.IStandaloneDiffEditor | null = null

function setModels() {
  if (!editor) return
  const original = monaco.editor.createModel(props.original || '', props.language || 'python')
  const modified = monaco.editor.createModel(props.modified || '', props.language || 'python')
  const old = editor.getModel()
  editor.setModel({ original, modified })
  old?.original?.dispose()
  old?.modified?.dispose()
}

onMounted(() => {
  if (!el.value) return
  editor = monaco.editor.createDiffEditor(el.value, {
    theme: 'vs',
    automaticLayout: true,
    readOnly: true,
    renderSideBySide: true,
    minimap: { enabled: false },
    fontSize: 13,
  })
  setModels()
})

watch(
  () => [props.original, props.modified],
  () => setModels(),
)

onBeforeUnmount(() => {
  const m = editor?.getModel()
  m?.original?.dispose()
  m?.modified?.dispose()
  editor?.dispose()
})
</script>

<template>
  <div ref="el" class="diff-editor" />
</template>

<style scoped>
.diff-editor {
  width: 100%;
  height: 100%;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--pf-border);
  animation: fade-in 0.25s ease;
}
@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
