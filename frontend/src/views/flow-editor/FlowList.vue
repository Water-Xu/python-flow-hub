<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { flowApi } from '@/api'

const router = useRouter()
const flows = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref({ name: '', description: '' })

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

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>流程编排</h2>
        <p class="dim">VueFlow 可视化画布，串联多个调用块与条件分支</p>
      </div>
      <el-button type="primary" :icon="'Plus'" @click="dialogVisible = true">新建流程</el-button>
    </header>

    <div v-loading="loading">
      <transition-group name="list" tag="div" class="grid-inner">
        <div v-for="f in flows" :key="f.id" class="pf-card flow-card" @click="router.push(`/flows/${f.id}`)">
          <div class="flow-icon">🔗</div>
          <div class="flow-name">{{ f.name }}</div>
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
}
.flow-icon {
  font-size: 28px;
}
.flow-name {
  font-weight: 600;
  margin: 10px 0 6px;
}
</style>
