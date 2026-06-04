<script setup lang="ts">
import { computed, markRaw, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElMessage } from 'element-plus'
import BlockNode from '@/components/nodes/BlockNode.vue'
import ConditionBranchNode from '@/components/nodes/ConditionBranchNode.vue'
import InputNode from '@/components/nodes/InputNode.vue'
import CodeEditor from '@/components/CodeEditor.vue'
import { blockApi, flowApi, type Block, type Entrypoint } from '@/api'

const route = useRoute()
const router = useRouter()
const flowId = route.params.id as string

// 自定义节点类型；input 与 VueFlow 内置保留键同名，需放宽类型
const nodeTypes: any = {
  block: markRaw(BlockNode),
  condition_branch: markRaw(ConditionBranchNode),
  input: markRaw(InputNode),
}

const {
  addNodes,
  addEdges,
  toObject,
  onConnect,
  removeNodes,
  removeEdges,
  getSelectedNodes,
  getSelectedEdges,
  onEdgeContextMenu,
  onPaneClick,
  onNodeDoubleClick,
  findNode,
} = useVueFlow()

const flowName = ref('')
const blocks = ref<Block[]>([])
const running = ref(false)
const elements = ref<any[]>([])

// 右键菜单
const ctxMenu = ref<{ visible: boolean; x: number; y: number; edgeId: string | null }>({
  visible: false,
  x: 0,
  y: 0,
  edgeId: null,
})

function hideCtxMenu() {
  ctxMenu.value.visible = false
}

onEdgeContextMenu(({ event, edge }) => {
  event.preventDefault()
  const e = event as MouseEvent
  ctxMenu.value = { visible: true, x: e.clientX, y: e.clientY, edgeId: edge.id }
})

onPaneClick(() => hideCtxMenu())

function deleteCtxEdge() {
  if (ctxMenu.value.edgeId) removeEdges([ctxMenu.value.edgeId])
  hideCtxMenu()
}

function deleteSelected() {
  const nodes = getSelectedNodes.value
  const edges = getSelectedEdges.value
  if (nodes.length) removeNodes(nodes.map((n: any) => n.id))
  if (edges.length) removeEdges(edges.map((e: any) => e.id))
}

// 文件夹树 / 资源
const tree = ref<any | null>(null)
const resources = ref<Record<string, string>>({})
const treePanelOpen = ref(true)

// 资源抽屉
const resourceDrawer = ref(false)
const resourceName = ref('')
const resourceContent = ref('')

// 块代码抽屉
const codeDrawer = ref(false)
const codeBlock = ref<Block | null>(null)
const codeDraft = ref('')
const codeSaving = ref(false)

// 节点配置抽屉（选择该节点调用脚本里的哪个入口函数）
const nodeCfgDrawer = ref(false)
const cfgNodeId = ref<string | null>(null)
const cfgNodeLabel = ref('')
const cfgEntrypoint = ref('run')
const cfgEntrypoints = ref<Entrypoint[]>([])
const cfgLoadingFns = ref(false)

const treeProps = { children: 'children', label: 'name' }
const treeData = computed(() => (tree.value?.children ?? []))
const hasTree = computed(() => treeData.value.length > 0)

onConnect((conn) => addEdges([{ ...conn, animated: true }]))

// 双击块节点 → 打开节点配置（选择入口函数）
onNodeDoubleClick(({ node }) => {
  if (node.type !== 'block') return
  openNodeConfig(node)
})

async function openNodeConfig(node: any) {
  cfgNodeId.value = node.id
  cfgNodeLabel.value = node.data?.label || '节点'
  cfgEntrypoint.value = node.data?.entrypoint || 'run'
  cfgEntrypoints.value = []
  nodeCfgDrawer.value = true

  const blockId = node.data?.block_id
  if (!blockId) return
  const block = blocks.value.find((b) => b.id === blockId)
  if (block?.entrypoints?.length) {
    cfgEntrypoints.value = block.entrypoints
    return
  }
  // 列表里没有入口信息时，按需静态扫描脚本
  cfgLoadingFns.value = true
  try {
    const res = await blockApi.discoverEntrypoints(blockId)
    cfgEntrypoints.value = res.entrypoints || []
  } catch {
    cfgEntrypoints.value = []
  } finally {
    cfgLoadingFns.value = false
  }
}

function applyNodeConfig() {
  if (!cfgNodeId.value) return
  const node = findNode(cfgNodeId.value)
  if (node) {
    node.data = { ...node.data, entrypoint: cfgEntrypoint.value || 'run' }
  }
  nodeCfgDrawer.value = false
  ElMessage.success(`已设置入口函数：${cfgEntrypoint.value || 'run'}`)
}

async function load() {
  const [flow, blockList]: any = await Promise.all([flowApi.get(flowId), blockApi.list()])
  flowName.value = flow.name
  blocks.value = blockList
  tree.value = flow.tree && Object.keys(flow.tree).length ? flow.tree : null
  resources.value = flow.resources || {}

  const nodes = (flow.nodes || []).map((n: any) => {
    if (n.node_type === 'input') {
      return {
        id: n.id,
        type: 'input',
        position: n.position?.x != null ? n.position : { x: 80, y: 80 },
        data: { key: n.config?.key || 'value', value: stringifyValue(n.config?.value) },
      }
    }
    return {
      id: n.id,
      type: n.node_type,
      position: n.position?.x != null ? n.position : { x: 100, y: 100 },
      data: {
        label: n.config?.label || n.block_id || '节点',
        mode: n.config?.mode,
        block_id: n.block_id,
        entrypoint: n.config?.entrypoint || 'run',
      },
    }
  })
  const edges = (flow.edges || []).map((e: any) => ({
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    sourceHandle: e.source_port,
    targetHandle: e.target_port,
    animated: true,
  }))
  elements.value = [...nodes, ...edges]
}

function stringifyValue(v: any): string {
  if (v == null) return ''
  return typeof v === 'string' ? v : JSON.stringify(v, null, 2)
}

function parseValue(text: string): any {
  const t = (text ?? '').trim()
  if (t === '') return ''
  try {
    return JSON.parse(t)
  } catch {
    return text
  }
}

function addBlockNode(block: Block) {
  addNodes([
    {
      id: `n-${Date.now()}`,
      type: 'block',
      position: { x: 120 + Math.random() * 200, y: 120 + Math.random() * 160 },
      data: { label: block.name, mode: block.execution_mode, block_id: block.id, entrypoint: 'run' },
    },
  ])
}

function addConditionNode() {
  addNodes([
    {
      id: `c-${Date.now()}`,
      type: 'condition_branch',
      position: { x: 300, y: 200 },
      data: { label: '条件分支' },
    },
  ])
}

function addInputNode() {
  addNodes([
    {
      id: `in-${Date.now()}`,
      type: 'input',
      position: { x: 40, y: 120 + Math.random() * 160 },
      data: { key: 'value', value: '1' },
    },
  ])
  ElMessage.success('已添加测试输入，拖动右侧端点连到任意调用块')
}

async function onTreeClick(node: any) {
  if (node.kind === 'resource') {
    resourceName.value = node.path
    resourceContent.value = resources.value[node.path] ?? '（资源内容为空）'
    resourceDrawer.value = true
  } else if (node.kind === 'block' && node.block_id) {
    const block: any = await blockApi.get(node.block_id)
    codeBlock.value = block
    codeDraft.value = block.draft_code || ''
    codeDrawer.value = true
  }
}

async function saveBlockCode() {
  if (!codeBlock.value) return
  codeSaving.value = true
  try {
    await blockApi.update(codeBlock.value.id, { draft_code: codeDraft.value })
    ElMessage.success('已保存调用块代码')
    codeDrawer.value = false
  } finally {
    codeSaving.value = false
  }
}

async function save() {
  const obj = toObject()
  const nodes = obj.nodes.map((n: any) => {
    if (n.type === 'input') {
      return {
        id: n.id,
        node_type: 'input',
        block_id: null,
        config: { key: n.data?.key || 'value', value: parseValue(n.data?.value) },
        position: n.position,
      }
    }
    return {
      id: n.id,
      node_type: n.type,
      block_id: n.data?.block_id || null,
      config: {
        label: n.data?.label,
        mode: n.data?.mode,
        entrypoint: n.data?.entrypoint || 'run',
        ...(n.data?.config || {}),
      },
      position: n.position,
    }
  })
  const edges = obj.edges.map((e: any) => ({
    source_node_id: e.source,
    target_node_id: e.target,
    source_port: e.sourceHandle || 'output',
    target_port: e.targetHandle || 'input',
  }))
  await flowApi.saveGraph(flowId, nodes, edges)
  ElMessage.success('已保存（DAG 无环校验通过）')
}

async function run() {
  running.value = true
  try {
    await save()
    const res: any = await flowApi.run(flowId, {})
    ElMessage.success(`整流执行 ${res.status}`)
  } finally {
    running.value = false
  }
}

function treeIcon(kind: string): string {
  return kind === 'folder' ? '📁' : kind === 'block' ? '🧩' : '📄'
}

onMounted(load)
</script>

<template>
  <div class="flow-page">
    <header class="toolbar">
      <div class="head-left">
        <el-button text :icon="'ArrowLeft'" @click="router.push('/flows')">返回</el-button>
        <h3>{{ flowName }}</h3>
        <el-button
          v-if="hasTree"
          text
          :icon="treePanelOpen ? 'Fold' : 'Expand'"
          @click="treePanelOpen = !treePanelOpen"
        >
          {{ treePanelOpen ? '收起目录' : '展开目录' }}
        </el-button>
      </div>
      <div class="actions">
        <el-dropdown @command="addBlockNode">
          <el-button :icon="'Plus'">添加块节点</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="b in blocks" :key="b.id" :command="b">{{ b.name }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button :icon="'Switch'" @click="addConditionNode">条件分支</el-button>
        <el-button type="success" :icon="'EditPen'" @click="addInputNode">添加输入</el-button>
        <el-button @click="save">保存</el-button>
        <el-button type="danger" plain :icon="'Delete'" @click="deleteSelected">删除选中</el-button>
        <el-button type="primary" :loading="running" :icon="'VideoPlay'" @click="run">运行整流</el-button>
      </div>
    </header>

    <div class="body">
      <transition name="slide-panel">
        <aside v-if="hasTree && treePanelOpen" class="tree-panel pf-card">
          <div class="tree-title">📦 项目结构</div>
          <p class="tree-hint">脚本为调用块，其余文件为资源</p>
          <el-tree
            :data="treeData"
            :props="treeProps"
            node-key="path"
            default-expand-all
            :expand-on-click-node="false"
            @node-click="onTreeClick"
          >
            <template #default="{ data }">
              <span class="tree-node" :class="`kind-${data.kind}`">
                <span class="tree-emoji">{{ treeIcon(data.kind) }}</span>
                <span class="tree-name">{{ data.name }}</span>
                <el-tag v-if="data.kind === 'block'" size="small" effect="plain" type="primary">块</el-tag>
                <el-tag v-else-if="data.kind === 'resource'" size="small" effect="plain" type="info">资源</el-tag>
              </span>
            </template>
          </el-tree>
        </aside>
      </transition>

      <div class="canvas">
        <VueFlow
          v-model="elements"
          :node-types="nodeTypes"
          fit-view-on-init
          :default-edge-options="{ animated: true }"
          delete-key-code="Delete"
          @click="hideCtxMenu"
        >
          <Background :gap="18" pattern-color="#d8dce3" />
          <Controls />
          <MiniMap pannable zoomable />
        </VueFlow>
        <!-- 连线右键菜单 -->
        <transition name="ctx-fade">
          <div
            v-if="ctxMenu.visible"
            class="ctx-menu"
            :style="{ top: ctxMenu.y + 'px', left: ctxMenu.x + 'px' }"
            @click.stop
          >
            <div class="ctx-item ctx-delete" @click="deleteCtxEdge">
              <span class="ctx-icon">🗑</span> 删除连线
            </div>
          </div>
        </transition>
      </div>
    </div>

    <el-drawer v-model="resourceDrawer" :title="resourceName" size="46%" direction="rtl">
      <pre class="resource-view">{{ resourceContent }}</pre>
    </el-drawer>

    <el-drawer v-model="codeDrawer" :title="codeBlock?.name" size="58%" direction="rtl">
      <div class="code-drawer">
        <CodeEditor v-model="codeDraft" language="python" class="code-drawer-body" />
        <div class="code-drawer-foot">
          <el-button @click="codeDrawer = false">关闭</el-button>
          <el-button type="primary" :loading="codeSaving" @click="saveBlockCode">保存代码</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="nodeCfgDrawer" :title="`节点配置 · ${cfgNodeLabel}`" size="34%" direction="rtl">
      <div class="node-cfg">
        <el-form label-position="top">
          <el-form-item label="入口函数（entrypoint）">
            <el-select
              v-model="cfgEntrypoint"
              :loading="cfgLoadingFns"
              filterable
              allow-create
              default-first-option
              placeholder="选择该节点调用脚本里的哪个函数"
              class="fn-select"
            >
              <el-option
                v-for="fn in cfgEntrypoints"
                :key="fn.name"
                :value="fn.name"
                :label="fn.name"
              >
                <div class="fn-option">
                  <span class="fn-option-name">ƒ {{ fn.name }}</span>
                  <span v-if="fn.params?.length" class="fn-option-params">
                    ({{ fn.params.join(', ') }})
                  </span>
                </div>
                <div v-if="fn.description" class="fn-option-desc">{{ fn.description }}</div>
              </el-option>
            </el-select>
          </el-form-item>
          <transition name="fade-in">
            <p v-if="!cfgEntrypoints.length && !cfgLoadingFns" class="cfg-hint">
              该脚本未识别到入口函数，将默认调用 <code>run(inputs)</code>。
              一个脚本可定义多个 <code>def 函数名(inputs): ...</code>，把同一块拖成多个节点、各选不同函数即可映射多个接口。
            </p>
          </transition>
          <p v-if="cfgEntrypoints.length" class="cfg-hint">
            共识别到 {{ cfgEntrypoints.length }} 个入口函数。同一块可在不同节点选用不同函数。
          </p>
        </el-form>
        <div class="node-cfg-foot">
          <el-button @click="nodeCfgDrawer = false">取消</el-button>
          <el-button type="primary" :icon="'Check'" @click="applyNodeConfig">应用</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.flow-page {
  height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.head-left h3 {
  margin: 0;
}
.actions {
  display: flex;
  gap: 8px;
}
.body {
  flex: 1;
  display: flex;
  gap: 12px;
  min-height: 0;
}
.tree-panel {
  width: 280px;
  flex-shrink: 0;
  padding: 14px;
  overflow: auto;
}
.tree-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.tree-hint {
  font-size: 12px;
  color: var(--pf-text-dim);
  margin: 0 0 12px;
}
.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.tree-emoji {
  font-size: 14px;
}
.tree-name {
  flex: 1;
}
.kind-block .tree-name {
  color: var(--pf-accent);
}
.canvas {
  position: relative;
  flex: 1;
  min-width: 0;
  border: 1px solid var(--pf-border);
  border-radius: 12px;
  overflow: hidden;
}
.resource-view {
  margin: 0;
  padding: 12px;
  background: var(--pf-panel-2);
  border: 1px solid var(--pf-border);
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--pf-text);
  line-height: 1.6;
}
.code-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.code-drawer-body {
  flex: 1;
  min-height: 0;
}
.code-drawer-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
}
.node-cfg {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.fn-select {
  width: 100%;
}
.fn-option {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.fn-option-name {
  font-weight: 600;
  color: var(--pf-accent);
  font-family: 'JetBrains Mono', monospace;
}
.fn-option-params {
  font-size: 12px;
  color: var(--pf-text-dim);
  font-family: 'JetBrains Mono', monospace;
}
.fn-option-desc {
  font-size: 12px;
  color: var(--pf-text-dim);
  line-height: 1.4;
  white-space: normal;
}
.cfg-hint {
  font-size: 12px;
  color: var(--pf-text-dim);
  line-height: 1.6;
  margin: 4px 0 0;
}
.cfg-hint code {
  background: var(--pf-panel-2);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: 'JetBrains Mono', monospace;
}
.node-cfg-foot {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
}
.fade-in-enter-active {
  transition: opacity 0.25s ease;
}
.fade-in-enter-from {
  opacity: 0;
}
.slide-panel-enter-active,
.slide-panel-leave-active {
  transition: transform 0.28s ease, opacity 0.28s ease;
}
.slide-panel-enter-from,
.slide-panel-leave-to {
  transform: translateX(-14px);
  opacity: 0;
}

/* 右键菜单 */
.ctx-menu {
  position: fixed;
  z-index: 9999;
  background: var(--pf-panel);
  border: 1px solid var(--pf-border-strong);
  border-radius: 8px;
  box-shadow: var(--pf-shadow-md);
  padding: 4px 0;
  min-width: 130px;
  user-select: none;
}
.ctx-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}
.ctx-item:hover {
  background: var(--pf-panel-2);
}
.ctx-delete {
  color: #ef4444;
}
.ctx-delete:hover {
  background: #fef2f2;
  color: #dc2626;
}
.ctx-icon {
  font-size: 14px;
}
.ctx-fade-enter-active,
.ctx-fade-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.ctx-fade-enter-from,
.ctx-fade-leave-to {
  opacity: 0;
  transform: scale(0.92);
}
</style>
