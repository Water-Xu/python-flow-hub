<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { flowApi } from '@/api'

const router = useRouter()
const flows = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const importing = ref(false)
const deletingId = ref('')
const form = ref({ name: '', description: '' })
const fileInput = ref<HTMLInputElement>()

async function load() {
  loading.value = true
  try {
    flows.value = await flowApi.list()
  } finally {
    loading.value = false
  }
}

async function createFlow() {
  if (!form.value.name) return ElMessage.warning('请输入流程名称')
  const flow: any = await flowApi.create(form.value)
  dialogVisible.value = false
  router.push(`/flows/${flow.id}`)
}

async function removeFlow(flow: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除流程「${flow.name}」吗？此操作将一并清理其节点、边与版本记录，不可恢复。`,
      '删除流程',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  deletingId.value = flow.id
  try {
    await flowApi.remove(flow.id)
    ElMessage.success('流程已删除')
    flows.value = flows.value.filter((f) => f.id !== flow.id)
  } finally {
    deletingId.value = ''
  }
}

function pickZip() {
  fileInput.value?.click()
}

async function onZipPicked(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  importing.value = true
  try {
    const res: any = await flowApi.importZip(file)
    ElMessage.success(`已导入 ${res.block_count} 个调用块、${res.resource_count} 个资源`)
    router.push(`/flows/${res.flow_id}`)
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>流程编排</h2>
        <p class="dim">VueFlow 可视化画布，串联多个调用块与条件分支</p>
      </div>
      <div class="head-actions">
        <input
          ref="fileInput"
          type="file"
          accept=".zip"
          style="display: none"
          @change="onZipPicked"
        />
        <el-button :icon="'Upload'" :loading="importing" @click="pickZip">导入压缩包</el-button>
        <el-button type="primary" :icon="'Plus'" @click="dialogVisible = true">新建流程</el-button>
      </div>
    </header>

    <div v-loading="loading">
      <transition-group name="list" tag="div" class="grid-inner">
        <div v-for="f in flows" :key="f.id" class="pf-card flow-card" @click="router.push(`/flows/${f.id}`)">
          <el-button
            class="flow-delete"
            type="danger"
            :icon="'Delete'"
            circle
            size="small"
            :loading="deletingId === f.id"
            title="删除流程"
            @click.stop="removeFlow(f)"
          />
          <div class="flow-icon">{{ f.source === 'zip_import' ? '📁' : '🔗' }}</div>
          <div class="flow-name">
            {{ f.name }}
            <el-tag v-if="f.source === 'zip_import'" size="small" effect="dark" type="success">导入</el-tag>
          </div>
          <p class="dim">{{ f.description || '暂无描述' }}</p>
        </div>
      </transition-group>
      <el-empty v-if="!loading && flows.length === 0" description="还没有流程" />
    </div>

    <el-dialog v-model="dialogVisible" title="新建流程" width="440px">
      <el-form label-width="70px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createFlow">创建</el-button>
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
.head-actions {
  display: flex;
  gap: 8px;
}
.dim {
  color: var(--pf-text-dim);
  font-size: 13px;
  margin: 4px 0 0;
}
.grid-inner {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}
.flow-card {
  padding: 20px;
  cursor: pointer;
  position: relative;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.flow-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
}
.flow-delete {
  position: absolute;
  top: 12px;
  right: 12px;
  opacity: 0;
  transform: scale(0.8);
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.flow-card:hover .flow-delete {
  opacity: 1;
  transform: scale(1);
}
.flow-icon {
  font-size: 28px;
}
.flow-name {
  font-weight: 600;
  margin: 10px 0 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
