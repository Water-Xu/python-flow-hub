<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CodeEditor from '@/components/CodeEditor.vue'
import VersionDrawer from '@/components/VersionDrawer.vue'
import JupyterCell from '@/components/JupyterCell.vue'
import { blockApi, type Block } from '@/api'

const route = useRoute()
const router = useRouter()
const blockId = route.params.id as string

const block = ref<Block | null>(null)
const code = ref('')
const saving = ref(false)
const activeTab = ref('code')
const versionDrawer = ref(false)

// 入口函数（一脚本多函数）：仅展示，调用哪个函数由「流程编排」为各节点选择
const discovering = ref(false)
const entrypoints = computed(() => block.value?.entrypoints || [])

async function load() {
  block.value = await blockApi.get(blockId)
  code.value = block.value.draft_code
}

async function save() {
  saving.value = true
  try {
    block.value = await blockApi.update(blockId, { draft_code: code.value })
    ElMessage.success('已保存草稿')
  } finally {
    saving.value = false
  }
}

async function discoverFns() {
  discovering.value = true
  try {
    // 先存代码，再静态扫描入口函数
    await blockApi.update(blockId, { draft_code: code.value })
    const res = await blockApi.discoverEntrypoints(blockId)
    if (block.value) block.value.entrypoints = res.entrypoints || []
    ElMessage.success(`识别到 ${res.entrypoints?.length || 0} 个入口函数`)
  } finally {
    discovering.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-if="block">
    <header class="page-head">
      <div class="head-left">
        <el-button text @click="router.push('/blocks')">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
        <h2>{{ block.name }}</h2>
        <el-tag size="small" effect="dark">{{ block.type }}</el-tag>
      </div>
      <div>
        <el-button :loading="saving" @click="save">保存草稿</el-button>
        <el-button @click="versionDrawer = true">
          <el-icon><Files /></el-icon> 版本
        </el-button>
      </div>
    </header>

    <VersionDrawer
      v-model="versionDrawer"
      resource-type="block"
      :resource-id="blockId"
      :resource-name="block?.name"
      @stable-changed="load"
    />

    <el-tabs v-model="activeTab" class="block-tabs">
      <!-- 代码 Tab -->
      <el-tab-pane label="代码编辑" name="code">
        <div class="editor-grid">
          <div class="editor-pane pf-card">
            <div class="pane-title">
              代码（至少定义一个 <code>def run(inputs)</code>；可定义多个入口函数）
            </div>
            <CodeEditor v-model="code" language="python" class="editor-body" />
          </div>
          <div class="side-pane">
            <div class="pf-card entry-card">
              <div class="pane-head">
                <span class="pane-title" style="margin:0">入口函数</span>
                <el-button size="small" text :loading="discovering" :icon="'Refresh'" @click="discoverFns">
                  重新扫描
                </el-button>
              </div>
              <transition-group name="fn-list" tag="div" class="fn-list">
                <el-tag
                  v-for="fn in entrypoints"
                  :key="fn.name"
                  class="fn-tag"
                  type="info"
                  effect="plain"
                >
                  ƒ {{ fn.name }}<span v-if="fn.params?.length" class="fn-tag-params">({{ fn.params.join(', ') }})</span>
                </el-tag>
              </transition-group>
              <p v-if="!entrypoints.length" class="dim" style="margin:6px 0 0">
                保存或扫描后显示脚本暴露的入口函数；多函数时在「流程编排」中为每个节点选择调用哪个函数。
              </p>
            </div>
            <div class="pf-card hint-card">
              <div class="pane-title">调试与触发</div>
              <p class="dim" style="margin:0;line-height:1.7">
                块不再单独 HTTP 触发：调试请用「调试执行 (Jupyter)」标签页；要对外提供调用，请在
                「接口管理」把所在流程发布为接口（HTTP / MQ / both）后整流测试。
              </p>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Jupyter 调试执行 Tab（决策 9：仅 local 模式，与生产执行链路隔离） -->
      <el-tab-pane label="调试执行 (Jupyter)" name="jupyter">
        <JupyterCell :block-id="blockId" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.head-left h2 { margin: 0; }

.block-tabs :deep(.el-tabs__content) { overflow: visible; }

/* 代码编辑 */
.editor-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 16px;
  height: calc(100vh - 180px);
}
.editor-pane {
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.editor-body { flex: 1; margin-top: 8px; }
.side-pane { display: flex; flex-direction: column; gap: 16px; overflow: auto; }
.pane-title { font-size: 13px; color: var(--pf-text-dim); margin-bottom: 8px; }
.hint-card { padding: 12px; }
.dim { color: var(--pf-text-dim); font-size: 12px; }

/* 入口函数 */
.entry-card { padding: 12px; }
.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.fn-list { display: flex; flex-wrap: wrap; gap: 8px; }
.fn-tag {
  font-family: 'JetBrains Mono', monospace;
}
.fn-tag-params { opacity: 0.7; margin-left: 2px; }
.fn-list-enter-active, .fn-list-leave-active { transition: all 0.25s ease; }
.fn-list-enter-from, .fn-list-leave-to { opacity: 0; transform: scale(0.8); }
</style>
