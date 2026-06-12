<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpened, Folder, Document } from '@element-plus/icons-vue'
import { blockApi, type Block } from '@/api'

const router = useRouter()
const blocks = ref<Block[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref({ name: '', description: '', type: 'script' })

// 文件夹折叠状态：key=source_flow_id（null 表示"独立调用块"组）
const collapsed = reactive<Record<string, boolean>>({})

async function load() {
  loading.value = true
  try {
    blocks.value = await blockApi.list()
  } finally {
    loading.value = false
  }
}

async function createBlock() {
  if (!form.value.name) return ElMessage.warning('请输入块名称')
  const block = await blockApi.create({
    ...form.value,
    draft_code: 'def run(inputs):\n    return {"echo": inputs}\n',
  })
  dialogVisible.value = false
  form.value = { name: '', description: '', type: 'script' }
  router.push(`/blocks/${block.id}`)
}

async function removeBlock(id: string, e: Event) {
  e.stopPropagation()
  await ElMessageBox.confirm('确认删除该调用块？删除后不可恢复。', '提示', { type: 'warning' })
  await blockApi.remove(id)
  ElMessage.success('已删除')
  load()
}

/** 分组：独立块放到 null 组，zip 导入块按 source_flow_id 分组 */
const groups = computed(() => {
  const map = new Map<string | null, { flowId: string | null; flowName: string; blocks: Block[] }>()
  for (const b of blocks.value) {
    const key = b.source_flow_id ?? null
    if (!map.has(key)) {
      map.set(key, {
        flowId: key,
        flowName: b.source_flow_name ?? (key ? `流程 ${key.slice(0, 8)}` : '独立调用块'),
        blocks: [],
      })
    }
    map.get(key)!.blocks.push(b)
  }
  // 独立块在最前，zip 来源组按 flowName 排序
  const independents = map.get(null)
  const zipGroups = [...map.entries()]
    .filter(([k]) => k !== null)
    .map(([, v]) => v)
    .sort((a, b) => a.flowName.localeCompare(b.flowName))
  return [
    ...(independents ? [independents] : []),
    ...zipGroups,
  ]
})

function toggleGroup(key: string | null) {
  const k = key ?? '__null__'
  collapsed[k] = !collapsed[k]
}

function isCollapsed(key: string | null) {
  return !!collapsed[key ?? '__null__']
}

const typeColor: Record<string, string> = {
  script: '#2563eb',
  notebook: '#0891b2',
  gcp_bigquery: '#d97706',
  gcp_storage: '#059669',
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>调用块库</h2>
        <p class="dim">以 Block 为最小执行单元，Docker 沙箱隔离执行</p>
      </div>
      <el-button type="primary" :icon="'Plus'" @click="dialogVisible = true">新建调用块</el-button>
    </header>

    <div v-loading="loading" class="groups">
      <el-empty v-if="!loading && blocks.length === 0" description="还没有调用块，点击右上角新建" />

      <div
        v-for="group in groups"
        :key="group.flowId ?? '__null__'"
        class="group-section"
      >
        <!-- 文件夹标题行 -->
        <div
          class="folder-header"
          :class="{ 'is-zip': group.flowId !== null }"
          @click="toggleGroup(group.flowId)"
        >
          <el-icon class="folder-icon" :class="{ collapsed: isCollapsed(group.flowId) }">
            <FolderOpened v-if="!isCollapsed(group.flowId)" />
            <Folder v-else />
          </el-icon>
          <span class="folder-name">{{ group.flowName }}</span>
          <el-tag
            v-if="group.flowId !== null"
            size="small"
            type="info"
            effect="plain"
            class="zip-tag"
          >ZIP 导入</el-tag>
          <span class="folder-count">{{ group.blocks.length }} 个块</span>
          <el-icon class="chevron" :class="{ 'is-down': !isCollapsed(group.flowId) }">
            <el-icon-arrow-right />
          </el-icon>
        </div>

        <!-- 块卡片网格（折叠动画） -->
        <transition name="folder-collapse">
          <div v-show="!isCollapsed(group.flowId)" class="grid-inner">
            <transition-group name="list" tag="div" class="grid-inner-wrap">
              <div
                v-for="b in group.blocks"
                :key="b.id"
                class="pf-card block-card"
                @click="router.push(`/blocks/${b.id}`)"
              >
                <div class="card-top">
                  <span class="type-dot" :style="{ background: typeColor[b.type] || '#888' }" />
                  <span class="block-name">{{ b.name }}</span>
                  <el-tag size="small" effect="dark">{{ b.type }}</el-tag>
                </div>
                <p class="block-desc">{{ b.description || '暂无描述' }}</p>
                <div class="card-foot">
                  <div class="card-foot-left">
                    <el-icon style="margin-right:4px"><Document /></el-icon>
                    <span class="dim">{{ b.entrypoints?.length ?? 0 }} 个入口</span>
                  </div>
                  <el-button text type="danger" size="small" @click="removeBlock(b.id, $event)">删除</el-button>
                </div>
              </div>
            </transition-group>
          </div>
        </transition>
      </div>
    </div>

    <!-- 新建对话框 -->
    <el-dialog v-model="dialogVisible" title="新建调用块" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如 数据清洗" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="script 脚本" value="script" />
            <el-option label="notebook" value="notebook" />
            <el-option label="gcp_bigquery" value="gcp_bigquery" />
            <el-option label="gcp_storage" value="gcp_storage" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createBlock">创建并编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}
.page-head h2 {
  margin: 0;
}
.dim {
  color: var(--pf-text-dim);
  margin: 4px 0 0;
  font-size: 13px;
}

/* 分组 */
.groups {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.group-section {
  border-radius: 10px;
  overflow: hidden;
  background: var(--pf-card-bg, #e9effd);
  border: 1px solid var(--pf-border, rgba(255,255,255,.07));
  transition: box-shadow .2s;
}
.group-section:hover {
  box-shadow: 0 4px 24px rgba(0,0,0,.18);
}

.folder-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px;
  cursor: pointer;
  user-select: none;
  background: rgba(255,255,255,.02);
  border-bottom: 1px solid var(--pf-border, rgba(255,255,255,.06));
  transition: background .18s;
}
.folder-header:hover {
  background: rgba(255,255,255,.05);
}
.folder-header.is-zip .folder-name {
  color: var(--el-color-primary);
}
.folder-icon {
  font-size: 18px;
  color: var(--el-color-warning);
  transition: transform .22s;
}
.folder-icon.collapsed {
  transform: scale(.9);
}
.folder-name {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
}
.zip-tag {
  margin-left: 4px;
}
.folder-count {
  font-size: 12px;
  color: var(--pf-text-dim);
  margin-right: 4px;
}
.chevron {
  font-size: 14px;
  color: var(--pf-text-dim);
  transition: transform .22s;
}
.chevron.is-down {
  transform: rotate(90deg);
}

/* 卡片网格 */
.grid-inner {
  padding: 16px;
  overflow: hidden;
}
.grid-inner-wrap {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 14px;
}
.block-card {
  padding: 16px;
  cursor: pointer;
  transition: transform .18s, box-shadow .18s;
}
.block-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,.22);
}
.card-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.type-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}
.block-name {
  font-weight: 600;
  font-size: 13px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.block-desc {
  color: var(--pf-text-dim);
  font-size: 12px;
  min-height: 36px;
  margin: 0 0 10px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.card-foot-left {
  display: flex;
  align-items: center;
  color: var(--pf-text-dim);
  font-size: 12px;
}

/* 折叠动画 */
.folder-collapse-enter-active,
.folder-collapse-leave-active {
  transition: max-height .28s cubic-bezier(.4, 0, .2, 1), opacity .2s;
  max-height: 2000px;
  overflow: hidden;
}
.folder-collapse-enter-from,
.folder-collapse-leave-to {
  max-height: 0;
  opacity: 0;
}

/* 卡片列表动画 */
.list-enter-active,
.list-leave-active {
  transition: all .22s ease;
}
.list-enter-from,
.list-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
