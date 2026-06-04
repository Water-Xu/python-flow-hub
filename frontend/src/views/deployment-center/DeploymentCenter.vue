<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { deploymentApi, flowApi } from '@/api'

const deployments = ref<any[]>([])
const flows = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref({ flow_id: '', name: '', environment: 'k8s' })

async function load() {
  loading.value = true
  try {
    deployments.value = await deploymentApi.list()
    flows.value = await flowApi.list()
  } finally {
    loading.value = false
  }
}

async function createDeployment() {
  if (!form.value.flow_id || !form.value.name) return ElMessage.warning('请选择流程并填写名称')
  await deploymentApi.create(form.value)
  dialogVisible.value = false
  ElMessage.success('部署记录已创建')
  load()
}

const statusType: Record<string, string> = {
  running: 'success',
  deploying: 'warning',
  building: 'warning',
  partially_degraded: 'warning',
  stopped: 'info',
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>部署中心</h2>
        <p class="dim">FlowDeployment 一键部署到 K8s（KEDA 扩缩 / GPU 节点池，Phase 4a 接入）</p>
      </div>
      <el-button type="primary" :icon="'Promotion'" @click="dialogVisible = true">新建部署</el-button>
    </header>

    <el-table v-loading="loading" :data="deployments" class="pf-table">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="resource_prefix" label="资源前缀" />
      <el-table-column prop="environment" label="环境" width="100" />
      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="statusType[row.status] || 'info'" effect="dark">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="flow_id" label="Flow ID" />
    </el-table>

    <el-dialog v-model="dialogVisible" title="新建部署" width="460px">
      <el-form label-width="80px">
        <el-form-item label="流程">
          <el-select v-model="form.flow_id" style="width: 100%">
            <el-option v-for="f in flows" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="prod-v1" /></el-form-item>
        <el-form-item label="环境">
          <el-radio-group v-model="form.environment">
            <el-radio-button label="local" />
            <el-radio-button label="k8s" />
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createDeployment">创建</el-button>
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
.pf-table {
  background: transparent;
  border-radius: 12px;
}
</style>
