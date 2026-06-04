<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deploymentApi, flowApi } from '@/api'

const deployments = ref<any[]>([])
const flows = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref({ flow_id: '', name: '', environment: 'k8s' })
const acting = ref<Record<string, boolean>>({})

// 详情抽屉
const drawer = ref(false)
const detail = ref<any>(null)
const precheck = ref<any>(null)
const manifests = ref<any[]>([])
const detailTab = ref('status')

// 部署级环境变量编辑
const envRows = ref<{ key: string; value: string }[]>([])
const envSaving = ref(false)

let timer: number | undefined

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

async function doDeploy(row: any) {
  const pc = await deploymentApi.precheck(row.id)
  if (!pc.ok) {
    await ElMessageBox.confirm(
      `预检未通过：\n${(pc.issues || []).map((i: any) => `[${i.kind}] ${i.reason}`).join('\n')}`,
      '容量/配额预检',
      { type: 'warning', confirmButtonText: '仍尝试部署', distinguishCancelAndClose: true },
    ).catch(() => {
      throw new Error('cancelled')
    })
  }
  acting.value[row.id] = true
  try {
    const res = await deploymentApi.deploy(row.id)
    ElMessage.success(`部署完成：${res.status}`)
    const warnings: string[] = res.warnings || []
    if (warnings.length) {
      ElMessage({ type: 'warning', message: warnings.join('；'), duration: 8000, showClose: true })
    }
    await load()
  } catch (e: any) {
    if (e?.message !== 'cancelled') {
      const detail = e?.response?.data?.detail
      ElMessage.error(detail ? `部署失败：${detail}` : '部署失败，请查看详情')
    }
  } finally {
    acting.value[row.id] = false
  }
}

async function refreshStatus(row: any) {
  acting.value[row.id] = true
  try {
    const res = await deploymentApi.status(row.id)
    row.status = res.status
    row.block_statuses = res.block_statuses
  } finally {
    acting.value[row.id] = false
  }
}

async function doDestroy(row: any) {
  await ElMessageBox.confirm(`销毁部署 ${row.name}？将删除全部 K8s 资源（ADMIN）`, '确认销毁', {
    type: 'warning',
  })
  await deploymentApi.destroy(row.id)
  ElMessage.success('已销毁')
  load()
}

function loadEnvRows(dep: any) {
  const ev = dep?.env_vars || {}
  envRows.value = Object.keys(ev).map((k) => ({ key: k, value: String(ev[k]) }))
}

function addEnvRow() {
  envRows.value.push({ key: '', value: '' })
}

function removeEnvRow(i: number) {
  envRows.value.splice(i, 1)
}

async function saveEnv() {
  if (!detail.value) return
  const env_vars: Record<string, string> = {}
  for (const r of envRows.value) {
    if (r.key.trim()) env_vars[r.key.trim()] = r.value
  }
  envSaving.value = true
  try {
    await deploymentApi.updateEnv(detail.value.id, { env_vars })
    detail.value.env_vars = env_vars
    ElMessage.success('环境变量已保存（下次部署生效）')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    envSaving.value = false
  }
}

async function openDetail(row: any) {
  detail.value = row
  drawer.value = true
  detailTab.value = 'status'
  precheck.value = null
  manifests.value = []
  loadEnvRows(row)
  if (row.environment === 'k8s') {
    try {
      const res = await deploymentApi.status(row.id)
      detail.value = { ...row, ...res }
    } catch {
      /* ignore */
    }
  }
}

async function loadPrecheck() {
  if (!detail.value) return
  precheck.value = await deploymentApi.precheck(detail.value.id)
}

async function loadManifests() {
  if (!detail.value) return
  const res = await deploymentApi.manifests(detail.value.id)
  manifests.value = res.manifests || []
}

const statusType: Record<string, string> = {
  running: 'success',
  deploying: 'warning',
  building: 'warning',
  partially_degraded: 'danger',
  stopped: 'info',
}

onMounted(() => {
  load()
  timer = window.setInterval(load, 15000)
})
onBeforeUnmount(() => timer && clearInterval(timer))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>部署中心</h2>
        <p class="dim">FlowDeployment 一键部署到 K8s（容量预检 / KEDA 扩缩 / GPU 节点池 / NetworkPolicy）</p>
      </div>
      <el-button type="primary" :icon="'Promotion'" @click="dialogVisible = true">新建部署</el-button>
    </header>

    <el-table v-loading="loading" :data="deployments" class="pf-table" @row-click="openDetail">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="resource_prefix" label="资源前缀" show-overflow-tooltip />
      <el-table-column prop="environment" label="环境" width="90" />
      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="statusType[row.status] || 'info'" effect="dark" class="status-tag">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="副本" width="100">
        <template #default="{ row }">
          <span class="dim">{{ (row.block_statuses || []).length }} 块</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280">
        <template #default="{ row }">
          <el-button
            v-if="row.environment === 'k8s'"
            link
            type="primary"
            size="small"
            :loading="acting[row.id]"
            @click.stop="doDeploy(row)"
            >部署</el-button
          >
          <el-button link size="small" :loading="acting[row.id]" @click.stop="refreshStatus(row)">刷新状态</el-button>
          <el-button link type="danger" size="small" @click.stop="doDestroy(row)">销毁</el-button>
        </template>
      </el-table-column>
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

    <el-drawer v-model="drawer" :title="detail?.name" size="58%">
      <el-tabs v-model="detailTab">
        <el-tab-pane label="Block 状态" name="status">
          <el-table :data="detail?.block_statuses || []" size="small">
            <el-table-column prop="name" label="块" show-overflow-tooltip />
            <el-table-column prop="execution_mode" label="模式" width="110" />
            <el-table-column prop="replicas" label="副本" width="80" />
            <el-table-column prop="ready" label="Ready" width="80" />
            <el-table-column label="存在" width="80">
              <template #default="{ row }">
                <el-tag :type="row.exists ? 'success' : 'info'" size="small">{{ row.exists ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="容量预检" name="precheck">
          <el-button size="small" type="primary" @click="loadPrecheck">运行预检</el-button>
          <div v-if="precheck" class="precheck">
            <el-alert
              :title="precheck.ok ? '预检通过：容量/配额满足' : '预检未通过'"
              :type="precheck.ok ? 'success' : 'error'"
              :closable="false"
              show-icon
            />
            <ul v-if="!precheck.ok">
              <li v-for="(i, idx) in precheck.issues" :key="idx">[{{ i.kind }}] {{ i.reason }}</li>
            </ul>
            <pre class="cap">{{ JSON.stringify(precheck.capacity, null, 2) }}</pre>
          </div>
        </el-tab-pane>
        <el-tab-pane label="环境变量" name="env">
          <p class="dim env-tip">
            部署级环境变量注入该部署下全部块（优先级：全局 &lt; 部署 &lt; 块）。敏感凭据请用 Secret，勿在此明文存密码。
          </p>
          <div v-for="(r, i) in envRows" :key="i" class="env-row">
            <el-input v-model="r.key" placeholder="变量名" style="width: 38%" />
            <el-input v-model="r.value" placeholder="值" style="width: 50%" />
            <el-button link type="danger" @click="removeEnvRow(i)"><el-icon><Delete /></el-icon></el-button>
          </div>
          <div class="env-actions">
            <el-button size="small" @click="addEnvRow"><el-icon><Plus /></el-icon> 添加</el-button>
            <el-button size="small" type="primary" :loading="envSaving" @click="saveEnv">保存</el-button>
          </div>
        </el-tab-pane>
        <el-tab-pane label="Manifest 预览" name="manifests">
          <el-button size="small" type="primary" @click="loadManifests">渲染 manifest</el-button>
          <div v-for="(m, idx) in manifests" :key="idx" class="manifest">
            <el-tag size="small" effect="plain">{{ m.kind }} · {{ m.metadata?.name }}</el-tag>
            <pre>{{ JSON.stringify(m, null, 2) }}</pre>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>
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
  cursor: pointer;
}
.status-tag {
  transition: transform 0.2s ease;
}
.status-tag:hover {
  transform: scale(1.06);
}
.precheck,
.manifest {
  margin-top: 12px;
  animation: fade 0.25s ease;
}
.env-tip { margin: 0 0 12px; line-height: 1.6; }
.env-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.env-actions { display: flex; gap: 8px; margin-top: 6px; }
.cap,
.manifest pre {
  background: var(--pf-bg-soft, #f5f7fa);
  border-radius: 8px;
  padding: 10px;
  font-size: 12px;
  overflow: auto;
  max-height: 320px;
}
@keyframes fade {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
