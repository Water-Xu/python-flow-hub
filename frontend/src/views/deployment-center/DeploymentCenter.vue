<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deploymentApi, flowApi, type BlockResource } from '@/api'

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

// 部署级 Pod 资源配置编辑（按 block 覆盖 CPU/内存/GPU）
interface ResourceRow extends BlockResource {
  cpu_request: string
  memory_request: string
  cpu_limit: string
  memory_limit: string
  gpu_enabled: boolean
  gpu_count: number
  gpu_type: string
}
const resourceRows = ref<ResourceRow[]>([])
const resourceLoading = ref(false)
const resourceSaving = ref(false)
const gpuTypeOptions = ['nvidia-tesla-t4', 'nvidia-tesla-l4', 'nvidia-tesla-a100', 'nvidia-l4']

// 实时容量预检
const livePrecheck = ref<any>(null)
const livePrecheckLoading = ref(false)
let precheckTimer: number | undefined

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

async function loadResources() {
  if (!detail.value) return
  resourceLoading.value = true
  try {
    const rows = await deploymentApi.resources(detail.value.id)
    resourceRows.value = rows.map((r) => ({
      ...r,
      cpu_request: r.effective.cpu_request,
      memory_request: r.effective.memory_request,
      cpu_limit: r.effective.cpu_limit,
      memory_limit: r.effective.memory_limit,
      gpu_enabled: r.effective.gpu_enabled,
      gpu_count: r.effective.gpu_count,
      gpu_type: r.effective.gpu_type,
    }))
    runLivePrecheck()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载资源配置失败')
  } finally {
    resourceLoading.value = false
  }
}

function resetResourceRow(r: ResourceRow) {
  r.cpu_request = r.default.cpu_request
  r.memory_request = r.default.memory_request
  r.cpu_limit = r.default.cpu_limit
  r.memory_limit = r.default.memory_limit
  r.gpu_enabled = r.default.gpu_enabled
  r.gpu_count = r.default.gpu_count
  r.gpu_type = r.default.gpu_type
}

// CPU：100m / 0.5 / 2；内存：256Mi / 1Gi / 512M
const CPU_RE = /^\d+(\.\d+)?m?$/
const MEM_RE = /^\d+(\.\d+)?(Ki|Mi|Gi|Ti|Pi|K|M|G|T|P)?$/

/** 由当前编辑行构建 overrides 载荷；allValid 标记是否全部格式合法。 */
function buildOverridesPayload(): { overrides: Record<string, any>; allValid: boolean } {
  const overrides: Record<string, any> = {}
  let allValid = true
  for (const r of resourceRows.value) {
    const cpuOk = CPU_RE.test(String(r.cpu_request).trim()) && CPU_RE.test(String(r.cpu_limit).trim())
    const memOk = MEM_RE.test(String(r.memory_request).trim()) && MEM_RE.test(String(r.memory_limit).trim())
    if (!cpuOk || !memOk) {
      allValid = false
      continue
    }
    const o: Record<string, any> = {
      cpu_request: r.cpu_request.trim(),
      memory_request: r.memory_request.trim(),
      cpu_limit: r.cpu_limit.trim(),
      memory_limit: r.memory_limit.trim(),
      gpu_enabled: r.gpu_enabled,
    }
    if (r.gpu_enabled) {
      o.gpu_count = r.gpu_count
      o.gpu_type = r.gpu_type
    }
    overrides[r.block_id] = o
  }
  return { overrides, allValid }
}

async function runLivePrecheck() {
  if (!detail.value || resourceRows.value.length === 0) {
    livePrecheck.value = null
    return
  }
  const { overrides, allValid } = buildOverridesPayload()
  if (!allValid) {
    livePrecheck.value = { ok: false, format: true }
    return
  }
  livePrecheckLoading.value = true
  try {
    livePrecheck.value = await deploymentApi.precheckResources(detail.value.id, overrides)
  } catch {
    livePrecheck.value = null
  } finally {
    livePrecheckLoading.value = false
  }
}

// 编辑资源后防抖触发实时预检（600ms）
watch(
  resourceRows,
  () => {
    if (detailTab.value !== 'resources') return
    window.clearTimeout(precheckTimer)
    precheckTimer = window.setTimeout(runLivePrecheck, 600)
  },
  { deep: true },
)

function mib(v: number) {
  return v >= 1024 ? `${(v / 1024).toFixed(2)} Gi` : `${v} Mi`
}
function cores(m: number) {
  return `${(m / 1000).toFixed(2)} 核`
}

async function saveResources() {
  if (!detail.value) return
  const overrides: Record<string, any> = {}
  for (const r of resourceRows.value) {
    if (![r.cpu_request, r.cpu_limit].every((v) => CPU_RE.test(String(v).trim()))) {
      return ElMessage.error(`「${r.name}」CPU 格式非法（如 100m / 0.5 / 2）`)
    }
    if (![r.memory_request, r.memory_limit].every((v) => MEM_RE.test(String(v).trim()))) {
      return ElMessage.error(`「${r.name}」内存格式非法（如 256Mi / 1Gi）`)
    }
    const o: Record<string, any> = {
      cpu_request: r.cpu_request.trim(),
      memory_request: r.memory_request.trim(),
      cpu_limit: r.cpu_limit.trim(),
      memory_limit: r.memory_limit.trim(),
      gpu_enabled: r.gpu_enabled,
    }
    if (r.gpu_enabled) {
      o.gpu_count = r.gpu_count
      o.gpu_type = r.gpu_type
    }
    overrides[r.block_id] = o
  }
  resourceSaving.value = true
  try {
    const res = await deploymentApi.updateResources(detail.value.id, overrides)
    detail.value.resource_overrides = res.resource_overrides
    ElMessage.success('Pod 资源配置已保存（下次部署生效）')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    resourceSaving.value = false
  }
}

async function openDetail(row: any) {
  detail.value = row
  drawer.value = true
  detailTab.value = 'status'
  precheck.value = null
  manifests.value = []
  resourceRows.value = []
  livePrecheck.value = null
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
      <el-tabs v-model="detailTab" @tab-change="(n: any) => n === 'resources' && resourceRows.length === 0 && loadResources()">
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
        <el-tab-pane label="资源配置" name="resources">
          <div class="res-head">
            <p class="dim res-tip">
              按 Block（每个 Block 对应一个 Pod/Deployment）配置 CPU / 内存请求与上限，覆盖块默认值，仅作用于本部署，下次部署生效。
            </p>
            <el-button size="small" :loading="resourceLoading" @click="loadResources">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>

          <!-- 实时容量预检横幅 -->
          <transition name="banner-fade">
            <div v-if="livePrecheck" class="cap-banner" v-loading="livePrecheckLoading">
              <el-alert
                v-if="livePrecheck.format"
                title="资源格式不合法，请检查 CPU（如 100m / 0.5 / 2）与内存（如 256Mi / 1Gi）后再核算容量"
                type="warning"
                :closable="false"
                show-icon
              />
              <template v-else>
                <el-alert
                  :title="livePrecheck.ok ? '容量充足：常驻副本请求量未超出 pyflow-workers 节点池余量' : '容量不足：常驻副本请求量已超出节点池可分配容量'"
                  :type="livePrecheck.ok ? 'success' : 'error'"
                  :closable="false"
                  show-icon
                />
                <div v-if="livePrecheck.capacity" class="cap-bars">
                  <div class="cap-metric">
                    <div class="cap-metric-head">
                      <span>CPU 请求</span>
                      <span class="dim">{{ cores(livePrecheck.capacity.requested_cpu_m) }} / {{ cores(livePrecheck.capacity.pool_cpu_m) }}</span>
                    </div>
                    <el-progress
                      :percentage="Math.min(100, Math.round((livePrecheck.capacity.requested_cpu_m / livePrecheck.capacity.pool_cpu_m) * 100))"
                      :status="livePrecheck.capacity.requested_cpu_m > livePrecheck.capacity.pool_cpu_m ? 'exception' : 'success'"
                      :stroke-width="10"
                    />
                  </div>
                  <div class="cap-metric">
                    <div class="cap-metric-head">
                      <span>内存 请求</span>
                      <span class="dim">{{ mib(livePrecheck.capacity.requested_mem_mib) }} / {{ mib(livePrecheck.capacity.pool_mem_mib) }}</span>
                    </div>
                    <el-progress
                      :percentage="Math.min(100, Math.round((livePrecheck.capacity.requested_mem_mib / livePrecheck.capacity.pool_mem_mib) * 100))"
                      :status="livePrecheck.capacity.requested_mem_mib > livePrecheck.capacity.pool_mem_mib ? 'exception' : 'success'"
                      :stroke-width="10"
                    />
                  </div>
                </div>
                <ul v-if="!livePrecheck.ok && livePrecheck.issues?.length" class="cap-issues">
                  <li v-for="(i, idx) in livePrecheck.issues" :key="idx">[{{ i.kind }}] {{ i.reason }}</li>
                </ul>
              </template>
            </div>
          </transition>

          <transition-group name="res-list" tag="div" v-loading="resourceLoading">
            <div v-for="r in resourceRows" :key="r.block_id" class="res-card">
              <div class="res-card-head">
                <span class="res-name">{{ r.name }}</span>
                <el-tag size="small" effect="plain">{{ r.execution_mode }}</el-tag>
                <el-button class="res-reset" link size="small" @click="resetResourceRow(r)">
                  <el-icon><RefreshLeft /></el-icon> 恢复默认
                </el-button>
              </div>
              <div class="res-grid">
                <div class="res-field">
                  <label>CPU 请求</label>
                  <el-input v-model="r.cpu_request" size="small" placeholder="100m" />
                </div>
                <div class="res-field">
                  <label>CPU 上限</label>
                  <el-input v-model="r.cpu_limit" size="small" placeholder="1000m" />
                </div>
                <div class="res-field">
                  <label>内存 请求</label>
                  <el-input v-model="r.memory_request" size="small" placeholder="256Mi" />
                </div>
                <div class="res-field">
                  <label>内存 上限</label>
                  <el-input v-model="r.memory_limit" size="small" placeholder="1Gi" />
                </div>
              </div>
              <div class="res-gpu">
                <el-switch v-model="r.gpu_enabled" size="small" />
                <span class="res-gpu-label">GPU</span>
                <template v-if="r.gpu_enabled">
                  <el-input-number v-model="r.gpu_count" :min="1" :max="8" size="small" controls-position="right" style="width: 110px" />
                  <el-select v-model="r.gpu_type" size="small" style="width: 180px" placeholder="GPU 类型">
                    <el-option v-for="t in gpuTypeOptions" :key="t" :label="t" :value="t" />
                  </el-select>
                </template>
              </div>
            </div>
          </transition-group>
          <el-empty v-if="!resourceLoading && resourceRows.length === 0" description="该流程暂无可部署的 Block" :image-size="80" />
          <div v-if="resourceRows.length" class="res-actions">
            <el-button type="primary" :loading="resourceSaving" @click="saveResources">
              <el-icon style="margin-right:4px"><Check /></el-icon> 保存资源配置
            </el-button>
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

/* ── Pod 资源配置 ── */
.res-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.res-tip { margin: 0; line-height: 1.6; flex: 1; }
.res-card {
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: var(--pf-panel, #fff);
  transition: box-shadow 0.22s ease, border-color 0.22s ease, transform 0.22s ease;
}
.res-card:hover {
  border-color: var(--pf-accent, #409eff);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  transform: translateY(-2px);
}
.res-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.res-name { font-weight: 600; font-size: 14px; }
.res-reset { margin-left: auto; }
.res-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.res-field { display: flex; flex-direction: column; gap: 4px; }
.res-field label { font-size: 12px; color: var(--pf-text-dim, #909399); }
.res-gpu {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.res-gpu-label { font-size: 13px; color: var(--pf-text-dim, #909399); }
.res-actions { display: flex; justify-content: flex-end; margin-top: 8px; }
/* 实时容量预检横幅 */
.cap-banner { margin-bottom: 14px; }
.cap-bars {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 10px;
}
.cap-metric-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 4px;
}
.cap-issues {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--el-color-danger, #f56c6c);
}
.cap-issues li { margin: 2px 0; }
.banner-fade-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.banner-fade-enter-from { opacity: 0; transform: translateY(-8px); }
@media (max-width: 640px) {
  .cap-bars { grid-template-columns: 1fr; }
}
/* 资源卡片入场动画 */
.res-list-enter-active { transition: all 0.3s ease; }
.res-list-enter-from { opacity: 0; transform: translateY(10px); }
.res-list-move { transition: transform 0.3s ease; }
@media (max-width: 640px) {
  .res-grid { grid-template-columns: repeat(2, 1fr); }
}
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
