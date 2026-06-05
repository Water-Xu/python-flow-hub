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
import SwitchCaseNode from '@/components/nodes/SwitchCaseNode.vue'
import NoteNode from '@/components/nodes/NoteNode.vue'
import InputNode from '@/components/nodes/InputNode.vue'
import CodeEditor from '@/components/CodeEditor.vue'
import { blockApi, flowApi, type Block, type Entrypoint } from '@/api'

const route = useRoute()
const router = useRouter()
const flowId = route.params.id as string

/**
 * 自定义节点类型注册表。
 * note / input 与 VueFlow 内置名称无冲突，但 input 需放宽类型绕过 TS 检查。
 * switch_case 前端类型对应后端 node_type=condition_branch + subtype=switch_case。
 */
const nodeTypes: any = {
  block:            markRaw(BlockNode),
  condition_branch: markRaw(ConditionBranchNode),
  switch_case:      markRaw(SwitchCaseNode),
  note:             markRaw(NoteNode),
  input:            markRaw(InputNode),
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

// ─── 右键菜单（连线删除） ─────────────────────────────
const ctxMenu = ref<{ visible: boolean; x: number; y: number; edgeId: string | null }>({
  visible: false, x: 0, y: 0, edgeId: null,
})
function hideCtxMenu() { ctxMenu.value.visible = false }
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

// ─── 文件树 / 资源 ───────────────────────────────────
const tree = ref<any | null>(null)
const resources = ref<Record<string, string>>({})
const treePanelOpen = ref(true)
const resourceDrawer = ref(false)
const resourceName = ref('')
const resourceContent = ref('')

// ─── 块代码抽屉 ──────────────────────────────────────
const codeDrawer = ref(false)
const codeBlock = ref<Block | null>(null)
const codeDraft = ref('')
const codeSaving = ref(false)

// ─── 块节点入口函数配置抽屉 ──────────────────────────
const nodeCfgDrawer = ref(false)
const cfgNodeId = ref<string | null>(null)
const cfgNodeLabel = ref('')
const cfgEntrypoint = ref('run')
const cfgEntrypoints = ref<Entrypoint[]>([])
const cfgLoadingFns = ref(false)

// ─── 条件分支（if_else）配置抽屉 ────────────────────
const condDrawer = ref(false)
const condNodeId = ref<string | null>(null)
const condLabel = ref('')
const condLang = ref<'jmespath' | 'jsonpath'>('jmespath')
const condExpr = ref('')

/**
 * 打开 if_else 条件分支的配置抽屉，从节点 data 中还原当前值。
 */
function openConditionConfig(node: any) {
  condNodeId.value = node.id
  condLabel.value = node.data?.label || '条件分支'
  condLang.value = node.data?.condition_language || 'jmespath'
  condExpr.value = node.data?.condition_expression || ''
  condDrawer.value = true
}

/** 应用 if_else 配置到节点 data（true_port/false_port 固定为 "true"/"false"） */
function applyConditionConfig() {
  if (!condNodeId.value) return
  const node = findNode(condNodeId.value)
  if (node) {
    node.data = {
      ...node.data,
      label: condLabel.value || '条件分支',
      condition_language: condLang.value,
      condition_expression: condExpr.value,
      true_port: 'true',
      false_port: 'false',
    }
  }
  condDrawer.value = false
  ElMessage.success('条件分支已配置')
}

// ─── Switch/Case 配置抽屉 ────────────────────────────
const switchDrawer = ref(false)
const swNodeId = ref<string | null>(null)
const swLabel = ref('')
const swLang = ref<'jmespath' | 'jsonpath'>('jsonpath')
const swField = ref('')
const swBranches = ref<{ value: string; port: string; label: string }[]>([])
const swDefault = ref('default')

/** 打开 switch_case 配置抽屉 */
function openSwitchConfig(node: any) {
  swNodeId.value = node.id
  swLabel.value = node.data?.label || 'Switch'
  swLang.value = node.data?.condition_language || 'jsonpath'
  swField.value = node.data?.switch_field || ''
  swBranches.value = (node.data?.branches || []).map((b: any) => ({ ...b }))
  swDefault.value = node.data?.default_port || 'default'
  switchDrawer.value = true
}

function addSwitchBranch() {
  swBranches.value.push({ value: '', port: `p${swBranches.value.length + 1}`, label: '' })
}

function removeSwitchBranch(idx: number) {
  swBranches.value.splice(idx, 1)
}

/**
 * 应用 switch_case 配置到节点 data。
 * 注意：修改分支端口后，画布上已有的连线 sourceHandle 不会自动更新，
 * 需用户在画布重新连线。
 */
function applySwitchConfig() {
  if (!swNodeId.value) return
  const node = findNode(swNodeId.value)
  if (node) {
    node.data = {
      ...node.data,
      label: swLabel.value || 'Switch',
      condition_language: swLang.value,
      switch_field: swField.value,
      branches: swBranches.value.map((b) => ({ ...b })),
      default_port: swDefault.value || 'default',
    }
  }
  switchDrawer.value = false
  ElMessage.success('Switch/Case 已配置，如变更了端口名请重新连线')
}

const treeProps = { children: 'children', label: 'name' }
const treeData = computed(() => tree.value?.children ?? [])
const hasTree = computed(() => treeData.value.length > 0)

onConnect((conn) => addEdges([{ ...conn, animated: true }]))

/**
 * 双击节点路由到对应配置抽屉：
 *   block           → 选择入口函数
 *   condition_branch → if_else 条件配置
 *   switch_case      → switch/case 配置
 *   note / input    → 无配置（直接在节点内编辑）
 */
onNodeDoubleClick(({ node }) => {
  if (node.type === 'block') {
    openNodeConfig(node)
  } else if (node.type === 'condition_branch') {
    openConditionConfig(node)
  } else if (node.type === 'switch_case') {
    openSwitchConfig(node)
  }
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
  // 列表里没有入口信息时，按需静态扫描脚本（不执行用户代码）
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

// ─── 加载流程 ────────────────────────────────────────
async function load() {
  const [flow, blockList]: any = await Promise.all([flowApi.get(flowId), blockApi.list()])
  flowName.value = flow.name
  blocks.value = blockList
  tree.value = flow.tree && Object.keys(flow.tree).length ? flow.tree : null
  resources.value = flow.resources || {}

  const nodes = (flow.nodes || []).map((n: any) => {
    // 测试输入节点
    if (n.node_type === 'input') {
      return {
        id: n.id, type: 'input',
        position: n.position?.x != null ? n.position : { x: 80, y: 80 },
        data: { key: n.config?.key || 'value', value: stringifyValue(n.config?.value) },
      }
    }
    // 注释便签节点（纯视觉，无连线）
    if (n.node_type === 'note') {
      return {
        id: n.id, type: 'note',
        position: n.position?.x != null ? n.position : { x: 200, y: 200 },
        data: { text: n.config?.text || '', color: n.config?.color || 'yellow' },
      }
    }
    // 条件分支 → 根据 subtype 还原为 if_else 或 switch_case 前端类型
    if (n.node_type === 'condition_branch') {
      const isSwitch = n.config?.subtype === 'switch_case'
      return {
        id: n.id,
        type: isSwitch ? 'switch_case' : 'condition_branch',
        position: n.position?.x != null ? n.position : { x: 300, y: 200 },
        data: isSwitch
          ? {
              label:              n.config?.label || 'Switch',
              condition_language: n.config?.condition_language || 'jsonpath',
              switch_field:       n.config?.switch_field || '',
              branches:           n.config?.branches || [],
              default_port:       n.config?.default_port || 'default',
            }
          : {
              label:               n.config?.label || '条件分支',
              condition_language:  n.config?.condition_language || 'jmespath',
              condition_expression:n.config?.condition_expression || '',
              true_port:           n.config?.true_port || 'true',
              false_port:          n.config?.false_port || 'false',
            },
      }
    }
    // 普通块节点
    return {
      id: n.id, type: n.node_type,
      position: n.position?.x != null ? n.position : { x: 100, y: 100 },
      data: {
        label:      n.config?.label || n.block_id || '节点',
        mode:       n.config?.mode,
        block_id:   n.block_id,
        entrypoint: n.config?.entrypoint || 'run',
      },
    }
  })
  const edges = (flow.edges || []).map((e: any) => ({
    id: e.id,
    source: e.source_node_id, target: e.target_node_id,
    sourceHandle: e.source_port, targetHandle: e.target_port,
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
  try { return JSON.parse(t) } catch { return text }
}

// ─── 添加节点 ────────────────────────────────────────
function addBlockNode(block: Block) {
  addNodes([{
    id: `n-${Date.now()}`,
    type: 'block',
    position: { x: 120 + Math.random() * 200, y: 120 + Math.random() * 160 },
    data: { label: block.name, block_id: block.id, entrypoint: 'run' },
  }])
}

/** 添加 if_else 条件分支（双击后可配置表达式） */
function addConditionNode() {
  addNodes([{
    id: `c-${Date.now()}`,
    type: 'condition_branch',
    position: { x: 300 + Math.random() * 80, y: 200 + Math.random() * 80 },
    data: {
      label: '条件分支',
      condition_language: 'jmespath',
      condition_expression: '',
      true_port: 'true',
      false_port: 'false',
    },
  }])
  ElMessage.info('双击节点可配置判断表达式')
}

/** 添加 switch/case 多路分支（双击后可配置字段路径与分支列表） */
function addSwitchNode() {
  addNodes([{
    id: `sw-${Date.now()}`,
    type: 'switch_case',
    position: { x: 300 + Math.random() * 80, y: 250 + Math.random() * 80 },
    data: {
      label: 'Switch',
      condition_language: 'jsonpath',
      switch_field: '',
      branches: [],
      default_port: 'default',
    },
  }])
  ElMessage.info('双击节点可配置匹配字段与分支列表')
}

/** 添加测试输入节点 */
function addInputNode() {
  addNodes([{
    id: `in-${Date.now()}`,
    type: 'input',
    position: { x: 40, y: 120 + Math.random() * 160 },
    data: { key: 'value', value: '1' },
  }])
  ElMessage.success('已添加测试输入，拖动右侧端点连到任意调用块')
}

/** 添加注释便签（纯视觉，不参与执行） */
function addNoteNode() {
  addNodes([{
    id: `note-${Date.now()}`,
    type: 'note',
    position: { x: 100 + Math.random() * 200, y: 50 + Math.random() * 100 },
    data: { text: '', color: 'yellow' },
  }])
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

// ─── 保存画布 ────────────────────────────────────────
async function save() {
  const obj = toObject()
  const nodes = obj.nodes.map((n: any) => {
    // 测试输入
    if (n.type === 'input') {
      return {
        id: n.id, node_type: 'input', block_id: null,
        config: { key: n.data?.key || 'value', value: parseValue(n.data?.value) },
        position: n.position,
      }
    }
    // 注释便签（node_type=note，后端执行时跳过）
    if (n.type === 'note') {
      return {
        id: n.id, node_type: 'note', block_id: null,
        config: { text: n.data?.text || '', color: n.data?.color || 'yellow' },
        position: n.position,
      }
    }
    // if_else 条件分支：写入完整配置，确保 true_port/false_port 与连线 handle 对齐
    if (n.type === 'condition_branch') {
      return {
        id: n.id, node_type: 'condition_branch', block_id: null,
        config: {
          label:                n.data?.label || '条件分支',
          subtype:              'if_else',
          condition_language:   n.data?.condition_language || 'jmespath',
          condition_expression: n.data?.condition_expression || '',
          true_port:            'true',   // 与 ConditionBranchNode Handle id="true" 对应
          false_port:           'false',  // 与 ConditionBranchNode Handle id="false" 对应
        },
        position: n.position,
      }
    }
    // switch_case 多路分支：保存为 condition_branch + subtype=switch_case
    if (n.type === 'switch_case') {
      return {
        id: n.id, node_type: 'condition_branch', block_id: null,
        config: {
          label:              n.data?.label || 'Switch',
          subtype:            'switch_case',
          condition_language: n.data?.condition_language || 'jsonpath',
          switch_field:       n.data?.switch_field || '',
          branches:           n.data?.branches || [],
          default_port:       n.data?.default_port || 'default',
        },
        position: n.position,
      }
    }
    // 普通块节点
    return {
      id: n.id, node_type: n.type, block_id: n.data?.block_id || null,
      config: {
        label:      n.data?.label,
        mode:       n.data?.mode,
        entrypoint: n.data?.entrypoint || 'run',
        ...(n.data?.config || {}),
      },
      position: n.position,
    }
  })
  const edges = obj.edges.map((e: any) => ({
    source_node_id: e.source, target_node_id: e.target,
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
    <!-- ─── 顶部工具栏 ──────────────────────────────── -->
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
        <!-- 添加块节点下拉 -->
        <el-dropdown @command="addBlockNode">
          <el-button :icon="'Plus'">添加块节点</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="b in blocks" :key="b.id" :command="b">{{ b.name }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <!-- 流程控制节点下拉 -->
        <el-dropdown>
          <el-button :icon="'Switch'">流程控制 ▾</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="addConditionNode">
                <span class="menu-item-icon">◇</span>
                <span>
                  <strong>条件分支（if/else）</strong><br />
                  <small style="color:#999">根据表达式走 true 或 false</small>
                </span>
              </el-dropdown-item>
              <el-dropdown-item @click="addSwitchNode">
                <span class="menu-item-icon">⇄</span>
                <span>
                  <strong>Switch / Case 多路分支</strong><br />
                  <small style="color:#999">按字段值匹配多个分支端口</small>
                </span>
              </el-dropdown-item>
              <el-dropdown-item divided @click="addNoteNode">
                <span class="menu-item-icon">📌</span>
                <span>
                  <strong>注释便签</strong><br />
                  <small style="color:#999">画布说明，不参与执行</small>
                </span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-button type="success" :icon="'EditPen'" @click="addInputNode">添加输入</el-button>
        <el-button @click="save">保存</el-button>
        <el-button type="danger" plain :icon="'Delete'" @click="deleteSelected">删除选中</el-button>
        <el-button type="primary" :loading="running" :icon="'VideoPlay'" @click="run">运行整流</el-button>
      </div>
    </header>

    <!-- ─── 主体区域 ────────────────────────────────── -->
    <div class="body">
      <!-- 文件树面板 -->
      <transition name="slide-panel">
        <aside v-if="hasTree && treePanelOpen" class="tree-panel pf-card">
          <div class="tree-title">📦 项目结构</div>
          <p class="tree-hint">脚本为调用块，其余文件为资源</p>
          <el-tree
            :data="treeData" :props="treeProps" node-key="path"
            default-expand-all :expand-on-click-node="false"
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

      <!-- 画布 -->
      <div class="canvas">
        <VueFlow
          v-model="elements" :node-types="nodeTypes"
          fit-view-on-init :default-edge-options="{ animated: true }"
          delete-key-code="Delete" @click="hideCtxMenu"
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

    <!-- ─── 资源查看抽屉 ────────────────────────────── -->
    <el-drawer v-model="resourceDrawer" :title="resourceName" size="46%" direction="rtl">
      <pre class="resource-view">{{ resourceContent }}</pre>
    </el-drawer>

    <!-- ─── 块代码编辑抽屉 ─────────────────────────── -->
    <el-drawer v-model="codeDrawer" :title="codeBlock?.name" size="58%" direction="rtl">
      <div class="code-drawer">
        <CodeEditor v-model="codeDraft" language="python" class="code-drawer-body" />
        <div class="code-drawer-foot">
          <el-button @click="codeDrawer = false">关闭</el-button>
          <el-button type="primary" :loading="codeSaving" @click="saveBlockCode">保存代码</el-button>
        </div>
      </div>
    </el-drawer>

    <!-- ─── 块节点入口函数配置抽屉 ──────────────────── -->
    <el-drawer v-model="nodeCfgDrawer" :title="`节点配置 · ${cfgNodeLabel}`" size="34%" direction="rtl">
      <div class="node-cfg">
        <el-form label-position="top">
          <el-form-item label="入口函数（entrypoint）">
            <el-select
              v-model="cfgEntrypoint" :loading="cfgLoadingFns"
              filterable allow-create default-first-option
              placeholder="选择该节点调用脚本里的哪个函数"
              class="fn-select"
            >
              <el-option v-for="fn in cfgEntrypoints" :key="fn.name" :value="fn.name" :label="fn.name">
                <div class="fn-option">
                  <span class="fn-option-name">ƒ {{ fn.name }}</span>
                  <span v-if="fn.params?.length" class="fn-option-params">({{ fn.params.join(', ') }})</span>
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

    <!-- ─── 条件分支（if_else）配置抽屉 ──────────────
         双击 ConditionBranchNode 触发
    ─────────────────────────────────────────────────── -->
    <el-drawer
      v-model="condDrawer"
      :title="`条件分支配置 · ${condLabel}`"
      size="38%"
      direction="rtl"
    >
      <div class="node-cfg">
        <el-form label-position="top">
          <!-- 节点标签 -->
          <el-form-item label="节点标签">
            <el-input v-model="condLabel" placeholder="如：检查订单类型" />
          </el-form-item>

          <!-- 求值语言 -->
          <el-form-item label="表达式语言">
            <el-radio-group v-model="condLang">
              <el-radio-button value="jmespath">JMESPath</el-radio-button>
              <el-radio-button value="jsonpath">JSONPath</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <!-- 条件表达式 -->
          <el-form-item label="条件表达式">
            <el-input
              v-model="condExpr"
              type="textarea"
              :rows="3"
              placeholder="留空则始终走 true 分支"
              style="font-family: 'JetBrains Mono', monospace; font-size: 13px"
            />
          </el-form-item>

          <!-- 语法示例说明 -->
          <div class="cond-syntax-box">
            <div class="cond-syntax-title">{{ condLang === 'jmespath' ? 'JMESPath' : 'JSONPath' }} 常用写法</div>
            <template v-if="condLang === 'jmespath'">
              <div class="cond-syntax-row"><code>value</code><span>取根字段 value，非空/非 false 即为真</span></div>
              <div class="cond-syntax-row"><code>header.type</code><span>取嵌套字段</span></div>
              <div class="cond-syntax-row"><code>status == 'active'</code><span>字符串比较</span></div>
              <div class="cond-syntax-row"><code>length(items) > 0</code><span>列表非空判断</span></div>
              <div class="cond-syntax-row"><code>flag</code><span>布尔字段（true/false）</span></div>
            </template>
            <template v-else>
              <div class="cond-syntax-row"><code>$.value</code><span>取根字段 value</span></div>
              <div class="cond-syntax-row"><code>$.header.type</code><span>取嵌套字段</span></div>
              <div class="cond-syntax-row"><code>$.items[*]</code><span>列表非空为真</span></div>
              <div class="cond-syntax-row"><code>$.flag</code><span>布尔字段</span></div>
            </template>
          </div>

          <!-- 端口说明 -->
          <div class="cond-ports">
            <div class="cond-port-item cond-port-true">
              <span class="cond-port-dot" style="background:#16a34a" /> ✓ True 端口 <code>"true"</code>
              <span class="cond-port-tip">表达式为真时激活</span>
            </div>
            <div class="cond-port-item cond-port-false">
              <span class="cond-port-dot" style="background:#dc2626" /> ✗ False 端口 <code>"false"</code>
              <span class="cond-port-tip">表达式为假或异常时激活</span>
            </div>
          </div>
        </el-form>
        <div class="node-cfg-foot">
          <el-button @click="condDrawer = false">取消</el-button>
          <el-button type="primary" :icon="'Check'" @click="applyConditionConfig">应用</el-button>
        </div>
      </div>
    </el-drawer>

    <!-- ─── Switch/Case 配置抽屉 ──────────────────────
         双击 SwitchCaseNode 触发
    ─────────────────────────────────────────────────── -->
    <el-drawer
      v-model="switchDrawer"
      :title="`Switch/Case 配置 · ${swLabel}`"
      size="42%"
      direction="rtl"
    >
      <div class="node-cfg">
        <el-form label-position="top">
          <!-- 节点标签 -->
          <el-form-item label="节点标签">
            <el-input v-model="swLabel" placeholder="如：按订单类型分流" />
          </el-form-item>

          <!-- 路径语言 -->
          <el-form-item label="表达式语言">
            <el-radio-group v-model="swLang">
              <el-radio-button value="jsonpath">JSONPath</el-radio-button>
              <el-radio-button value="jmespath">JMESPath</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <!-- 字段路径 -->
          <el-form-item label="匹配字段路径">
            <el-input
              v-model="swField"
              :placeholder="swLang === 'jsonpath' ? '$.header.type' : 'header.type'"
              style="font-family: 'JetBrains Mono', monospace"
            />
            <div class="cfg-hint" style="margin-top:4px">
              从上游 payload 中取该字段的值，与下方分支的「匹配值」逐一字符串比较。
            </div>
          </el-form-item>

          <!-- 分支列表 -->
          <el-form-item label="分支列表">
            <div class="sw-branch-list">
              <transition-group name="branch-list" tag="div">
                <div
                  v-for="(b, idx) in swBranches"
                  :key="idx"
                  class="sw-branch-row"
                >
                  <el-input
                    v-model="b.value"
                    placeholder="匹配值（如 order）"
                    class="sw-input-val"
                    style="font-family:'JetBrains Mono',monospace"
                  />
                  <span class="sw-arrow-label">→ 端口</span>
                  <el-input
                    v-model="b.port"
                    placeholder="端口ID"
                    class="sw-input-port"
                    style="font-family:'JetBrains Mono',monospace"
                  />
                  <el-input
                    v-model="b.label"
                    placeholder="显示标签（可选）"
                    class="sw-input-label"
                  />
                  <el-button
                    type="danger" plain size="small" :icon="'Close'"
                    @click="removeSwitchBranch(idx)"
                  />
                </div>
              </transition-group>
              <el-button class="sw-add-btn" :icon="'Plus'" @click="addSwitchBranch">添加分支</el-button>
            </div>
          </el-form-item>

          <!-- 默认端口 -->
          <el-form-item label="默认端口（无匹配时走此端口）">
            <el-input
              v-model="swDefault"
              placeholder="default"
              style="font-family:'JetBrains Mono',monospace; max-width:180px"
            />
          </el-form-item>

          <!-- 端口提示 -->
          <div class="cond-syntax-box">
            <div class="cond-syntax-title">注意事项</div>
            <div class="cond-syntax-row" style="flex-direction:column;align-items:flex-start;gap:2px">
              <span>• 「端口 ID」需与画布上的连线 sourceHandle 完全一致（大小写敏感）。</span>
              <span>• 修改端口名后，已有连线需重新拖拽连接。</span>
              <span>• 匹配值均转为字符串后比较，如数字 1 需填 "1"。</span>
            </div>
          </div>
        </el-form>
        <div class="node-cfg-foot">
          <el-button @click="switchDrawer = false">取消</el-button>
          <el-button type="primary" :icon="'Check'" @click="applySwitchConfig">应用</el-button>
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
.head-left h3 { margin: 0; }
.actions { display: flex; gap: 8px; }

/* 下拉菜单图标 */
.menu-item-icon {
  display: inline-block;
  width: 20px;
  text-align: center;
  font-size: 15px;
  margin-right: 6px;
}

/* ─── 布局 ───────────────────────────────────────── */
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
.tree-title { font-weight: 600; margin-bottom: 4px; }
.tree-hint { font-size: 12px; color: var(--pf-text-dim); margin: 0 0 12px; }
.tree-node { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.tree-emoji { font-size: 14px; }
.tree-name { flex: 1; }
.kind-block .tree-name { color: var(--pf-accent); }

.canvas {
  position: relative;
  flex: 1;
  min-width: 0;
  border: 1px solid var(--pf-border);
  border-radius: 12px;
  overflow: hidden;
}

/* ─── 资源查看 ───────────────────────────────────── */
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

/* ─── 代码抽屉 ───────────────────────────────────── */
.code-drawer { display: flex; flex-direction: column; height: 100%; }
.code-drawer-body { flex: 1; min-height: 0; }
.code-drawer-foot { display: flex; justify-content: flex-end; gap: 8px; padding-top: 12px; }

/* ─── 通用配置抽屉 ───────────────────────────────── */
.node-cfg { display: flex; flex-direction: column; height: 100%; }
.node-cfg-foot { margin-top: auto; display: flex; justify-content: flex-end; gap: 8px; padding-top: 12px; }
.fn-select { width: 100%; }
.fn-option { display: flex; align-items: baseline; gap: 6px; }
.fn-option-name { font-weight: 600; color: var(--pf-accent); font-family: 'JetBrains Mono', monospace; }
.fn-option-params { font-size: 12px; color: var(--pf-text-dim); font-family: 'JetBrains Mono', monospace; }
.fn-option-desc { font-size: 12px; color: var(--pf-text-dim); line-height: 1.4; white-space: normal; }
.cfg-hint { font-size: 12px; color: var(--pf-text-dim); line-height: 1.6; margin: 4px 0 0; }
.cfg-hint code { background: var(--pf-panel-2); border-radius: 4px; padding: 1px 5px; font-family: 'JetBrains Mono', monospace; }

/* ─── 条件分支配置专属 ───────────────────────────── */
.cond-syntax-box {
  background: var(--pf-panel-2, #f8fafc);
  border: 1px solid var(--pf-border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-top: 4px;
  margin-bottom: 12px;
}
.cond-syntax-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--pf-text-dim);
  text-transform: uppercase;
  letter-spacing: .06em;
  margin-bottom: 8px;
}
.cond-syntax-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 5px;
  font-size: 12px;
}
.cond-syntax-row code {
  font-family: 'JetBrains Mono', monospace;
  color: #0369a1;
  background: rgba(3,105,161,.08);
  border-radius: 4px;
  padding: 1px 6px;
  white-space: nowrap;
  flex-shrink: 0;
}
.cond-syntax-row span { color: var(--pf-text-dim); }

.cond-ports { display: flex; flex-direction: column; gap: 6px; margin-top: 2px; }
.cond-port-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 6px;
}
.cond-port-true  { background: rgba(22,163,74,.07); color: #14532d; }
.cond-port-false { background: rgba(220,38,38,.07); color: #7f1d1d; }
.cond-port-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.cond-port-item code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: rgba(0,0,0,.06);
  border-radius: 4px;
  padding: 1px 5px;
}
.cond-port-tip { color: var(--pf-text-dim); margin-left: auto; font-size: 11px; }

/* ─── Switch/Case 分支列表 ───────────────────────── */
.sw-branch-list { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.sw-branch-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: var(--pf-panel-2, #f8fafc);
  border: 1px solid var(--pf-border);
  border-radius: 8px;
  transition: background .15s ease;
}
.sw-branch-row:hover { background: var(--pf-panel, #fff); }
.sw-input-val   { flex: 2; min-width: 0; }
.sw-input-port  { flex: 1.5; min-width: 0; }
.sw-input-label { flex: 2; min-width: 0; }
.sw-arrow-label { font-size: 12px; color: var(--pf-text-dim); white-space: nowrap; flex-shrink: 0; }
.sw-add-btn { width: 100%; margin-top: 4px; }

/* 分支列表进出动画 */
.branch-list-enter-active { transition: opacity .2s ease, transform .2s ease; }
.branch-list-leave-active { transition: opacity .15s ease; }
.branch-list-enter-from  { opacity: 0; transform: translateX(-8px); }
.branch-list-leave-to    { opacity: 0; }

/* ─── 右键菜单 ───────────────────────────────────── */
.ctx-menu {
  position: fixed; z-index: 9999;
  background: var(--pf-panel); border: 1px solid var(--pf-border-strong);
  border-radius: 8px; box-shadow: var(--pf-shadow-md);
  padding: 4px 0; min-width: 130px; user-select: none;
}
.ctx-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px; font-size: 13px; cursor: pointer;
  transition: background .12s ease, color .12s ease;
}
.ctx-item:hover { background: var(--pf-panel-2); }
.ctx-delete { color: #ef4444; }
.ctx-delete:hover { background: #fef2f2; color: #dc2626; }
.ctx-icon { font-size: 14px; }

/* ─── 面板 / 元素过渡动画 ────────────────────────── */
.fade-in-enter-active { transition: opacity .25s ease; }
.fade-in-enter-from   { opacity: 0; }
.slide-panel-enter-active,
.slide-panel-leave-active  { transition: transform .28s ease, opacity .28s ease; }
.slide-panel-enter-from,
.slide-panel-leave-to { transform: translateX(-14px); opacity: 0; }
.ctx-fade-enter-active,
.ctx-fade-leave-active { transition: opacity .12s ease, transform .12s ease; }
.ctx-fade-enter-from,
.ctx-fade-leave-to { opacity: 0; transform: scale(0.92); }
</style>
