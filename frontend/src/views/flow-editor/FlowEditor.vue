<script setup lang="ts">
import { markRaw, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElMessage } from 'element-plus'
import BlockNode from '@/components/nodes/BlockNode.vue'
import ConditionBranchNode from '@/components/nodes/ConditionBranchNode.vue'
import { blockApi, flowApi, type Block } from '@/api'

const route = useRoute()
const router = useRouter()
const flowId = route.params.id as string

const nodeTypes = {
  block: markRaw(BlockNode),
  condition_branch: markRaw(ConditionBranchNode),
}

const { addNodes, addEdges, toObject, onConnect } = useVueFlow()
const flowName = ref('')
const blocks = ref<Block[]>([])
const running = ref(false)
const elements = ref<any[]>([])

onConnect((conn) => addEdges([{ ...conn, animated: true }]))

async function load() {
  const [flow, blockList]: any = await Promise.all([flowApi.get(flowId), blockApi.list()])
  flowName.value = flow.name
  blocks.value = blockList
  const nodes = (flow.nodes || []).map((n: any) => ({
    id: n.id,
    type: n.node_type,
    position: n.position?.x != null ? n.position : { x: 100, y: 100 },
    data: { label: n.config?.label || n.block_id || '节点', mode: n.config?.mode, block_id: n.block_id },
  }))
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

function addBlockNode(block: Block) {
  addNodes([
    {
      id: `n-${Date.now()}`,
      type: 'block',
      position: { x: 120 + Math.random() * 200, y: 120 + Math.random() * 160 },
      data: { label: block.name, mode: block.execution_mode, block_id: block.id },
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

async function save() {
  const obj = toObject()
  const nodes = obj.nodes.map((n: any) => ({
    id: n.id,
    node_type: n.type,
    block_id: n.data?.block_id || null,
    config: { label: n.data?.label, mode: n.data?.mode, ...(n.data?.config || {}) },
    position: n.position,
  }))
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

onMounted(load)
</script>

<template>
  <div class="flow-page">
    <header class="toolbar">
      <div class="head-left">
        <el-button text :icon="'ArrowLeft'" @click="router.push('/flows')">返回</el-button>
        <h3>{{ flowName }}</h3>
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
        <el-button @click="save">保存</el-button>
        <el-button type="primary" :loading="running" :icon="'VideoPlay'" @click="run">运行整流</el-button>
      </div>
    </header>

    <div class="canvas">
      <VueFlow v-model="elements" :node-types="nodeTypes" fit-view-on-init :default-edge-options="{ animated: true }">
        <Background :gap="18" pattern-color="#2a2e3a" />
        <Controls />
        <MiniMap pannable zoomable />
      </VueFlow>
    </div>
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
.canvas {
  flex: 1;
  border: 1px solid var(--pf-border);
  border-radius: 12px;
  overflow: hidden;
}
</style>
