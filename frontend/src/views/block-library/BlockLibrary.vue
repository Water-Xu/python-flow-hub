<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { blockApi, type Block } from '@/api'

const router = useRouter()
const blocks = ref<Block[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref({ name: '', description: '', type: 'script', execution_mode: 'sync_http' })

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
  form.value = { name: '', description: '', type: 'script', execution_mode: 'sync_http' }
  router.push(`/blocks/${block.id}`)
}

async function removeBlock(id: string) {
  await ElMessageBox.confirm('确认删除该调用块？', '提示', { type: 'warning' })
  await blockApi.remove(id)
  ElMessage.success('已删除')
  load()
}

const typeColor: Record<string, string> = {
  script: '#6366f1',
  notebook: '#06b6d4',
  gcp_bigquery: '#f59e0b',
  gcp_storage: '#10b981',
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

    <div v-loading="loading" class="grid">
      <transition-group name="list" tag="div" class="grid-inner">
        <div
          v-for="b in blocks"
          :key="b.id"
          class="pf-card block-card"
          @click="router.push(`/blocks/${b.id}`)"
        >
          <div class="card-top">
            <span class="type-dot" :style="{ background: typeColor[b.type] || '#888' }" />
            <span class="block-name">{{ b.name }}</span>
            <el-tag size="small" effect="dark">{{ b.execution_mode }}</el-tag>
          </div>
          <p class="block-desc">{{ b.description || '暂无描述' }}</p>
          <div class="card-foot">
            <span class="dim">{{ b.type }}</span>
            <el-button text type="danger" size="small" @click.stop="removeBlock(b.id)">删除</el-button>
          </div>
        </div>
      </transition-group>
      <el-empty v-if="!loading && blocks.length === 0" description="还没有调用块，点击右上角新建" />
    </div>

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
        <el-form-item label="执行模式">
          <el-select v-model="form.execution_mode" style="width: 100%">
            <el-option label="sync_http 同步" value="sync_http" />
            <el-option label="async_mq 异步" value="async_mq" />
            <el-option label="both 两者" value="both" />
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
  margin-bottom: 20px;
}
.page-head h2 {
  margin: 0;
}
.dim {
  color: var(--pf-text-dim);
  margin: 4px 0 0;
  font-size: 13px;
}
.grid-inner {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.block-card {
  padding: 18px;
  cursor: pointer;
}
.card-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.type-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.block-name {
  font-weight: 600;
  flex: 1;
}
.block-desc {
  color: var(--pf-text-dim);
  font-size: 13px;
  min-height: 38px;
  margin: 0 0 12px;
}
.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
</style>
