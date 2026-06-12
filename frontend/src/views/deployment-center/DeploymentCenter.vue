<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, computed, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deploymentApi, flowApi, type BlockResource, type FlowResourceSummary, type DeploymentDependencies, type DepPackage } from '@/api'

const deployments = ref<any[]>([])
const flows = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref({ flow_id: '', name: '', environment: 'k8s', deployment_type: 'block_mode' })
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

// ── 节点日志 ──
const podList = ref<any[]>([])
const podListLoading = ref(false)
const selectedPod = ref<string>('')
const podLogs = ref<string>('')
const podLogsLoading = ref(false)
const showPrevLogs = ref(false)
const logTailLines = ref(300)
const logPanelRef = ref<HTMLElement | null>(null)
let logRefreshTimer: number | undefined

async function loadPodList() {
  if (!detail.value) return
  podListLoading.value = true
  try {
    podList.value = await deploymentApi.listPods(detail.value.id)
    if (podList.value.length && !selectedPod.value) {
      selectedPod.value = podList.value[0].name
    }
  } catch {
    podList.value = []
  } finally {
    podListLoading.value = false
  }
}

async function loadPodLogs() {
  if (!detail.value || !selectedPod.value) return
  podLogsLoading.value = true
  try {
    const res = await deploymentApi.podLogs(detail.value.id, selectedPod.value, {
      tail_lines: logTailLines.value,
      previous: showPrevLogs.value,
    })
    podLogs.value = res.logs || '（暂无日志）'
    await nextTick()
    if (logPanelRef.value) logPanelRef.value.scrollTop = logPanelRef.value.scrollHeight
  } catch (e: any) {
    podLogs.value = `[加载失败] ${e?.response?.data?.detail || e?.message || ''}`
  } finally {
    podLogsLoading.value = false
  }
}

function startLogRefresh() {
  stopLogRefresh()
  loadPodLogs()
  logRefreshTimer = window.setInterval(loadPodLogs, 5000)
}

function stopLogRefresh() {
  if (logRefreshTimer) { clearInterval(logRefreshTimer); logRefreshTimer = undefined }
}

watch(selectedPod, () => { if (selectedPod.value) loadPodLogs() })
watch(showPrevLogs, () => { if (selectedPod.value) loadPodLogs() })

// Flow 维度资源汇总（各块独立 Pod 累加 + 节点池占用 + KEDA 峰值）
const resSummary = ref<FlowResourceSummary | null>(null)
const resSummaryLoading = ref(false)

// ── 资源估算小工具：按工作画像 + 数据量推荐 CPU/内存（默认值偏大，按需瘦身）──
const estimatorOpen = ref(false)
type EstProfile = 'io' | 'standard' | 'compute' | 'memory'
const estProfile = ref<EstProfile>('io')
const estDataMb = ref(10)
const estProfiles: Record<EstProfile, { label: string; desc: string; cpuReq: number; cpuLim: number; memReq: number; memLim: number; memPerMb: number }> = {
  // cpu 单位 m；mem 单位 Mi；memPerMb：每 MB 输入数据额外预留内存倍数（作用于 limit）
  io:       { label: '轻量 IO', desc: '调用外部 API / 小数据转换，几乎不算', cpuReq: 50,  cpuLim: 250,  memReq: 64,  memLim: 192, memPerMb: 1.5 },
  standard: { label: '标准',    desc: 'pandas 小表 / 一般业务计算',          cpuReq: 100, cpuLim: 500,  memReq: 128, memLim: 384, memPerMb: 2.5 },
  compute:  { label: '计算密集', desc: '大量 CPU 运算 / 循环 / 编解码',       cpuReq: 250, cpuLim: 1000, memReq: 256, memLim: 512, memPerMb: 2.0 },
  memory:   { label: '内存密集', desc: '大数据集 / 向量 / 模型加载',          cpuReq: 150, cpuLim: 600,  memReq: 256, memLim: 768, memPerMb: 4.0 },
}

function roundMem(mib: number): number {
  // 向上取整到 32Mi 的倍数，避免奇怪的内存值
  return Math.max(64, Math.ceil(mib / 32) * 32)
}

const estResult = computed(() => {
  const p = estProfiles[estProfile.value]
  const data = Math.max(0, Number(estDataMb.value) || 0)
  const memLim = roundMem(p.memLim + data * p.memPerMb)
  const memReq = roundMem(Math.min(p.memReq + data * (p.memPerMb / 2), memLim))
  return {
    cpu_request: `${p.cpuReq}m`,
    cpu_limit: `${p.cpuLim}m`,
    memory_request: `${memReq}Mi`,
    memory_limit: `${memLim}Mi`,
  }
})

function applyEstimate(r: ResourceRow) {
  const e = estResult.value
  r.cpu_request = e.cpu_request
  r.cpu_limit = e.cpu_limit
  r.memory_request = e.memory_request
  r.memory_limit = e.memory_limit
}

function applyEstimateToAll() {
  for (const r of resourceRows.value) {
    if (r.gpu_enabled) continue
    applyEstimate(r)
  }
  estimatorOpen.value = false
  ElMessage.success(`已按「${estProfiles[estProfile.value].label}」画像应用到 ${resourceRows.value.filter((r) => !r.gpu_enabled).length} 个块`)
}

// 判断当前部署是否为整流单 Pod 模式
const isFlowMode = computed(() => detail.value?.deployment_type === 'flow_mode')

// 资源汇总摘要描述（按模式切换文案）
const resSummaryDesc = computed(() => {
  if (!resSummary.value) return ''
  if (resSummary.value.is_flow_mode) return `整流单 Pod · 所有块 in-process（${resSummary.value.pool.name} 节点池）`
  return `${resSummary.value.block_count} 个块 · 各自独立 Pod（${resSummary.value.pool.name} 节点池）`
})

const resSummaryTip = computed(() =>
  resSummary.value?.is_flow_mode
    ? 'FlowRunner 为整流单 Pod，所有块在同一进程内执行。常驻请求为容量闸门（min≥1 副本）；KEDA 对整个 Flow 级扩缩（0→N），峰值上界按 limit×maxReplica 估算，不计入常驻。'
    : '常驻请求为容量闸门（各块 min≥1 副本按 request 累加）；KEDA 仅作用于各 MQ 接口的 Flow-Consumer（0→N 按队列扩缩），峰值上界按各块 limit×maxReplica 估算，不计入常驻。'
)

// ── 依赖列表 ──
const depsData = ref<DeploymentDependencies | null>(null)
const depsLoading = ref(false)
const depsFilterText = ref('')
const installPkgInput = ref('')
const installLoading = ref(false)
const installDialogVisible = ref(false)
const selectedBlockIds = ref<string[]>([])

const filteredMerged = computed(() => {
  const q = depsFilterText.value.trim().toLowerCase()
  if (!q || !depsData.value) return depsData.value?.merged ?? []
  return depsData.value.merged.filter(
    (p) => p.name.toLowerCase().includes(q) || p.spec.toLowerCase().includes(q),
  )
})

async function loadDependencies() {
  if (!detail.value) return
  depsLoading.value = true
  try {
    depsData.value = await deploymentApi.listDependencies(detail.value.id)
    selectedBlockIds.value = depsData.value?.blocks.map((b) => b.block_id) ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载依赖失败')
  } finally {
    depsLoading.value = false
  }
}

async function doInstallDependency() {
  if (!detail.value || !installPkgInput.value.trim()) return
  installLoading.value = true
  try {
    const res = await deploymentApi.installDependency(detail.value.id, {
      package: installPkgInput.value.trim(),
      block_ids: selectedBlockIds.value.length < (depsData.value?.blocks.length ?? 0)
        ? selectedBlockIds.value
        : undefined,
    })
    ElMessage.success(res.message)
    installPkgInput.value = ''
    installDialogVisible.value = false
    await loadDependencies()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '安装失败')
  } finally {
    installLoading.value = false
  }
}

function pkgTypeTag(type: DepPackage['type']): string {
  const map: Record<string, string> = { pypi: 'success', wheel: 'warning', option: 'info', other: '' }
  return map[type] ?? ''
}

let _loadInFlight = false

async function load() {
  if (_loadInFlight) return
  _loadInFlight = true
  loading.value = true
  try {
    // 两个列表互不依赖，并行请求降低首屏/轮询延迟
    ;[deployments.value, flows.value] = await Promise.all([
      deploymentApi.list(),
      flowApi.list(),
    ])
  } finally {
    loading.value = false
    _loadInFlight = false
  }
}

async function createDeployment() {
  if (!form.value.flow_id || !form.value.name) return ElMessage.warning('请选择流程并填写名称')
  await deploymentApi.create(form.value)
  dialogVisible.value = false
  form.value = { flow_id: '', name: '', environment: 'k8s', deployment_type: 'block_mode' }
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
    loadResSummary()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载资源配置失败')
  } finally {
    resourceLoading.value = false
  }
}

async function loadResSummary() {
  if (!detail.value) return
  resSummaryLoading.value = true
  try {
    resSummary.value = await deploymentApi.resourceSummary(detail.value.id)
  } catch {
    resSummary.value = null
  } finally {
    resSummaryLoading.value = false
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
  resSummary.value = null
  podList.value = []
  selectedPod.value = ''
  podLogs.value = ''
  depsData.value = null
  depsFilterText.value = ''
  installPkgInput.value = ''
  stopLogRefresh()
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

let timer: ReturnType<typeof window.setInterval> | undefined

onMounted(() => {
  load()
  // 后台标签暂停轮询，省去不可见时的无谓请求
  timer = window.setInterval(() => {
    if (!document.hidden) load()
  }, 15000)
})
onBeforeUnmount(() => {
  timer && clearInterval(timer)
  stopLogRefresh()
})
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
          <span class="dim">
            <template v-if="row.deployment_type === 'flow_mode'">Flow Runner</template>
            <template v-else>{{ (row.block_statuses || []).length }} 块</template>
          </span>
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
      <el-form label-width="90px">
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
        <el-form-item v-if="form.environment === 'k8s'" label="部署模式">
          <el-radio-group v-model="form.deployment_type">
            <el-radio-button value="block_mode">块级独立 Pod</el-radio-button>
            <el-radio-button value="flow_mode">Flow 整流单 Pod</el-radio-button>
          </el-radio-group>
          <div style="margin-top:6px;font-size:12px;color:#888">
            <template v-if="form.deployment_type === 'block_mode'">
              每个调用块各自部署一个常驻 Pod（/invoke 服务），Flow 消费者按 DAG 编排调用。
            </template>
            <template v-else>
              整条 Flow 部署为单一 Pod，所有块 in-process 执行，KEDA 对 Flow 级扩缩。
              资源消耗更低，块间无 HTTP 调用开销。
            </template>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createDeployment">创建</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawer" :title="detail?.name" size="58%" @close="stopLogRefresh">
      <el-tabs
        v-model="detailTab"
        @tab-change="(n: any) => {
          if (n === 'resources' && resourceRows.length === 0) loadResources()
          if (n === 'logs') { loadPodList(); startLogRefresh() }
          if (n === 'deps' && !depsData) loadDependencies()
          if (n !== 'logs') stopLogRefresh()
        }"
      >
        <el-tab-pane label="Pod 状态" name="status">
          <el-table :data="detail?.block_statuses || []" size="small">
            <el-table-column prop="name" label="名称" show-overflow-tooltip />
            <el-table-column label="类型" width="140">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.kind === 'flow_consumer' ? 'warning' : row.kind === 'flow_runner' ? 'success' : 'info'"
                  effect="plain"
                >
                  {{ row.kind === 'flow_consumer' ? 'Flow 消费者' : row.kind === 'flow_runner' ? 'Flow Runner' : 'invoke 服务' }}
                </el-tag>
              </template>
            </el-table-column>
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
          <!-- Flow 维度资源汇总：各块独立 Pod 累加 + 节点池占用 + KEDA 峰值 -->
          <transition name="banner-fade">
            <div v-if="resSummary" class="flow-sum" v-loading="resSummaryLoading">
              <div class="flow-sum-head">
                <span class="flow-sum-title">⛁ Flow 资源汇总</span>
                <span class="dim">{{ resSummaryDesc }}</span>
                <el-tag
                  size="small"
                  :type="resSummary.capacity_ok ? 'success' : 'danger'"
                  effect="dark"
                >{{ resSummary.capacity_ok ? '容量充足' : '容量不足' }}</el-tag>
              </div>
              <div class="flow-sum-bars">
                <div class="cap-metric">
                  <div class="cap-metric-head">
                    <span>常驻 CPU 请求</span>
                    <span class="dim">{{ cores(resSummary.resident.cpu_m) }} / {{ cores(resSummary.pool.cpu_m) }}（{{ resSummary.usage.cpu_pct }}%）</span>
                  </div>
                  <el-progress
                    :percentage="Math.min(100, Math.round(resSummary.usage.cpu_pct))"
                    :status="resSummary.usage.cpu_pct > 100 ? 'exception' : 'success'"
                    :stroke-width="10"
                  />
                </div>
                <div class="cap-metric">
                  <div class="cap-metric-head">
                    <span>常驻内存 请求</span>
                    <span class="dim">{{ mib(resSummary.resident.mem_mib) }} / {{ mib(resSummary.pool.mem_mib) }}（{{ resSummary.usage.mem_pct }}%）</span>
                  </div>
                  <el-progress
                    :percentage="Math.min(100, Math.round(resSummary.usage.mem_pct))"
                    :status="resSummary.usage.mem_pct > 100 ? 'exception' : 'success'"
                    :stroke-width="10"
                  />
                </div>
              </div>
              <div class="flow-sum-stats">
                <span>上限合计：<b>{{ cores(resSummary.limit.cpu_m) }} / {{ mib(resSummary.limit.mem_mib) }}</b></span>
                <span>KEDA 峰值上界：<b>{{ cores(resSummary.keda_peak.cpu_m) }} / {{ mib(resSummary.keda_peak.mem_mib) }}</b></span>
                <span v-if="resSummary.gpu.block_count">GPU：<b>{{ resSummary.gpu.total }} 卡 / {{ resSummary.gpu.block_count }} 块</b></span>
              </div>
              <p class="dim flow-sum-tip">{{ resSummaryTip }}</p>
            </div>
          </transition>

          <div class="res-head">
            <p class="dim res-tip">
              <template v-if="isFlowMode">
                配置整流 Pod 的 CPU / 内存资源（整条 Flow 在单 Pod 内 in-process 执行），覆盖默认值，仅作用于本部署，下次部署生效。
              </template>
              <template v-else>
                按 Block（每个 Block 对应一个 Pod/Deployment）配置 CPU / 内存请求与上限，覆盖块默认值，仅作用于本部署，下次部署生效。
              </template>
            </p>
            <div class="res-head-actions">
              <el-popover v-model:visible="estimatorOpen" placement="bottom-end" :width="340" trigger="click">
                <template #reference>
                  <el-button size="small" type="primary" plain>
                    <el-icon style="margin-right:4px"><MagicStick /></el-icon> 资源估算器
                  </el-button>
                </template>
                <div class="est-pop">
                  <div class="est-title">按工作画像估算推荐资源</div>
                  <div class="est-field">
                    <label>工作画像</label>
                    <el-radio-group v-model="estProfile" size="small">
                      <el-radio-button v-for="(p, k) in estProfiles" :key="k" :value="k">{{ p.label }}</el-radio-button>
                    </el-radio-group>
                    <p class="est-desc">{{ estProfiles[estProfile].desc }}</p>
                  </div>
                  <div class="est-field">
                    <label>单次输入数据量：{{ estDataMb }} MB</label>
                    <el-slider v-model="estDataMb" :min="0" :max="500" :step="5" />
                  </div>
                  <div class="est-result">
                    <div class="est-cell"><span>CPU 请求</span><b>{{ estResult.cpu_request }}</b></div>
                    <div class="est-cell"><span>CPU 上限</span><b>{{ estResult.cpu_limit }}</b></div>
                    <div class="est-cell"><span>内存 请求</span><b>{{ estResult.memory_request }}</b></div>
                    <div class="est-cell"><span>内存 上限</span><b>{{ estResult.memory_limit }}</b></div>
                  </div>
                  <p class="est-hint">
                    <template v-if="isFlowMode">并发由 KEDA 横向扩 FlowRunner 副本承担，单 Pod 资源按「一次 Flow 完整调用」估算即可。</template>
                    <template v-else>并发由 KEDA 横向扩副本承担，单 Pod 资源按「一次调用」估算即可。GPU 块不受影响。</template>
                  </p>
                  <el-button type="primary" size="small" style="width:100%" @click="applyEstimateToAll">
                    {{ isFlowMode ? '应用到 Flow 整体 Pod' : '应用到全部块' }}
                  </el-button>
                </div>
              </el-popover>
              <el-button size="small" :loading="resourceLoading" @click="loadResources">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
            </div>
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
                <el-tag size="small" effect="plain" :type="r.block_id === '__flow__' ? 'success' : 'info'">
                  {{ r.block_id === '__flow__' ? 'flow_runner' : 'invoke' }}
                </el-tag>
                <el-button v-if="!r.gpu_enabled" class="res-reset" link size="small" @click="applyEstimate(r)">
                  <el-icon><MagicStick /></el-icon> 套用估算
                </el-button>
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

        <!-- ── 依赖列表 ── -->
        <el-tab-pane label="依赖列表" name="deps">
          <div class="deps-toolbar">
            <el-input
              v-model="depsFilterText"
              placeholder="搜索包名…"
              size="small"
              clearable
              style="width: 220px"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-button size="small" :loading="depsLoading" @click="loadDependencies">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
            <el-button size="small" type="primary" @click="installDialogVisible = true">
              <el-icon><Plus /></el-icon> 安装依赖
            </el-button>
            <el-tag v-if="depsData" size="small" effect="plain" style="margin-left:auto">
              共 {{ depsData.merged.length }} 个包 · {{ depsData.blocks.length }} 个块
            </el-tag>
          </div>

          <div v-loading="depsLoading">
            <!-- flow_mode：合并视图 -->
            <template v-if="depsData?.deployment_type === 'flow_mode'">
              <div class="deps-section-title">
                <el-tag type="success" size="small" effect="dark">flow_mode · 合并依赖</el-tag>
                <span class="dim">整流单 Pod，所有块依赖合并构建为同一镜像</span>
              </div>
              <transition-group name="dep-list" tag="div" class="deps-grid">
                <div
                  v-for="pkg in filteredMerged"
                  :key="pkg.spec"
                  class="dep-card"
                >
                  <div class="dep-card-head">
                    <span class="dep-name">{{ pkg.name }}</span>
                    <el-tag :type="pkgTypeTag(pkg.type)" size="small" effect="plain">{{ pkg.type }}</el-tag>
                  </div>
                  <div class="dep-spec">{{ pkg.version_spec || (pkg.type === 'wheel' ? 'wheel 包' : '任意版本') }}</div>
                  <div class="dep-raw dim">{{ pkg.spec }}</div>
                </div>
              </transition-group>
              <el-empty v-if="!depsLoading && filteredMerged.length === 0" description="暂无依赖声明" :image-size="64" />
            </template>

            <!-- block_mode：按块展开 -->
            <template v-else-if="depsData">
              <el-collapse v-if="depsData.blocks.length" accordion>
                <el-collapse-item
                  v-for="block in depsData.blocks"
                  :key="block.block_id"
                  :name="block.block_id"
                >
                  <template #title>
                    <div class="block-dep-title">
                      <span class="dep-name">{{ block.name }}</span>
                      <el-tag size="small" effect="plain" type="info">{{ block.packages.length }} 个包</el-tag>
                    </div>
                  </template>
                  <transition-group name="dep-list" tag="div" class="deps-grid">
                    <div
                      v-for="pkg in block.packages.filter(p => !depsFilterText || p.name.toLowerCase().includes(depsFilterText.toLowerCase()) || p.spec.toLowerCase().includes(depsFilterText.toLowerCase()))"
                      :key="pkg.spec"
                      class="dep-card"
                    >
                      <div class="dep-card-head">
                        <span class="dep-name">{{ pkg.name }}</span>
                        <el-tag :type="pkgTypeTag(pkg.type)" size="small" effect="plain">{{ pkg.type }}</el-tag>
                      </div>
                      <div class="dep-spec">{{ pkg.version_spec || (pkg.type === 'wheel' ? 'wheel 包' : '任意版本') }}</div>
                      <div class="dep-raw dim">{{ pkg.spec }}</div>
                    </div>
                  </transition-group>
                  <el-empty v-if="block.packages.length === 0" description="该块无依赖声明" :image-size="48" />
                </el-collapse-item>
              </el-collapse>
              <el-empty v-else description="该流程暂无可部署的块" :image-size="64" />
            </template>
            <el-empty v-else-if="!depsLoading" description="点击「刷新」加载依赖列表" :image-size="64" />
          </div>

          <!-- 安装新依赖对话框 -->
          <el-dialog v-model="installDialogVisible" title="安装新依赖" width="480px" append-to-body>
            <el-form label-width="90px">
              <el-form-item label="包规范">
                <el-input
                  v-model="installPkgInput"
                  placeholder="如: numpy>=1.24  或  torch==2.1.0  或  @gcs:path/pkg.whl"
                  clearable
                  @keyup.enter="doInstallDependency"
                />
                <div class="dim" style="margin-top:6px;font-size:12px;line-height:1.6">
                  支持 PyPI 包名（含版本约束）或 <code>@gcs:</code> / <code>@wheel:</code> 开头的私有 wheel 引用。<br>
                  添加后需重新 <b>部署</b> 使镜像更新生效。
                </div>
              </el-form-item>
              <el-form-item v-if="depsData?.deployment_type !== 'flow_mode'" label="目标块">
                <el-select
                  v-model="selectedBlockIds"
                  multiple
                  collapse-tags
                  style="width: 100%"
                  placeholder="默认添加到全部块"
                >
                  <el-option
                    v-for="b in depsData?.blocks"
                    :key="b.block_id"
                    :label="b.name"
                    :value="b.block_id"
                  />
                </el-select>
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="installDialogVisible = false">取消</el-button>
              <el-button type="primary" :loading="installLoading" :disabled="!installPkgInput.trim()" @click="doInstallDependency">
                添加到 requirements
              </el-button>
            </template>
          </el-dialog>
        </el-tab-pane>

        <!-- ── 节点日志 ── -->
        <el-tab-pane label="节点日志" name="logs">
          <div class="log-toolbar">
            <el-select
              v-model="selectedPod"
              placeholder="选择 Pod"
              size="small"
              style="width: 320px"
              v-loading="podListLoading"
              @change="loadPodLogs"
            >
              <el-option
                v-for="p in podList"
                :key="p.name"
                :label="p.name"
                :value="p.name"
              >
                <div class="pod-opt">
                  <span>{{ p.name }}</span>
                  <el-tag
                    size="small"
                    :type="p.state === 'running' ? 'success' : p.state?.startsWith('waiting') ? 'warning' : 'danger'"
                    effect="plain"
                  >{{ p.state }}</el-tag>
                  <span class="dim" style="font-size:11px">重启 {{ p.restarts }}</span>
                </div>
              </el-option>
            </el-select>
            <el-select v-model="logTailLines" size="small" style="width: 100px" @change="loadPodLogs">
              <el-option :value="100" label="后 100 行" />
              <el-option :value="300" label="后 300 行" />
              <el-option :value="500" label="后 500 行" />
              <el-option :value="2000" label="后 2000 行" />
            </el-select>
            <el-switch v-model="showPrevLogs" size="small" active-text="崩溃日志" inactive-text="当前" />
            <el-button size="small" :loading="podLogsLoading" @click="loadPodLogs">
              <el-icon><Refresh /></el-icon>
            </el-button>
            <el-button size="small" @click="loadPodList"><el-icon><RefreshLeft /></el-icon> 刷新 Pod</el-button>
            <el-tag size="small" type="info" effect="plain" style="margin-left:auto">每 5s 自动刷新</el-tag>
          </div>

          <div v-if="podList.length === 0 && !podListLoading" class="log-empty">
            <el-empty description="暂无运行中的 Pod，请先部署" :image-size="64" />
          </div>
          <div v-else-if="!selectedPod" class="log-empty">
            <el-empty description="请选择一个 Pod 查看日志" :image-size="64" />
          </div>
          <div v-else ref="logPanelRef" class="log-panel" v-loading="podLogsLoading && !podLogs">
            <pre class="log-content">{{ podLogs }}</pre>
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
.res-head-actions { display: flex; gap: 8px; flex-shrink: 0; }

/* ── 资源估算器 popover ── */
.est-pop { display: flex; flex-direction: column; gap: 12px; }
.est-title { font-weight: 600; font-size: 13px; }
.est-field { display: flex; flex-direction: column; gap: 6px; }
.est-field > label { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.est-desc { margin: 0; font-size: 11px; color: var(--el-text-color-secondary, #909399); line-height: 1.4; }
.est-result {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light, #f5f7fa);
}
.est-cell { display: flex; flex-direction: column; gap: 2px; }
.est-cell > span { font-size: 11px; color: var(--el-text-color-secondary, #909399); }
.est-cell > b { font-size: 14px; font-variant-numeric: tabular-nums; color: var(--el-color-primary, #409eff); }
.est-hint { margin: 0; font-size: 11px; line-height: 1.5; color: var(--el-text-color-secondary, #909399); }
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
/* Flow 资源汇总卡片 */
.flow-sum {
  margin-bottom: 16px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color, #e4e7ed);
  border-radius: 10px;
  background: var(--el-fill-color-light, #f5f7fa);
}
.flow-sum-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.flow-sum-title { font-weight: 700; font-size: 14px; }
.flow-sum-bars {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.flow-sum-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 12px;
  font-size: 12px;
}
.flow-sum-stats b { font-weight: 700; }
.flow-sum-tip { margin: 8px 0 0; font-size: 11px; line-height: 1.5; }
@media (max-width: 640px) {
  .flow-sum-bars { grid-template-columns: 1fr; }
}
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

/* ── 依赖列表 ── */
.deps-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light, #f5f7fa);
}
.deps-section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.deps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.dep-card {
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 10px;
  background: var(--pf-panel, #fff);
  transition: box-shadow 0.22s ease, border-color 0.22s ease, transform 0.22s ease;
  overflow: hidden;
}
.dep-card:hover {
  border-color: var(--pf-accent, #409eff);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  transform: translateY(-2px);
}
.dep-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 4px;
}
.dep-name {
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dep-spec {
  font-size: 12px;
  color: var(--el-color-primary, #409eff);
  margin-bottom: 2px;
  font-variant-numeric: tabular-nums;
}
.dep-raw {
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'JetBrains Mono', Consolas, monospace;
}
.block-dep-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dep-list-enter-active { transition: all 0.25s ease; }
.dep-list-enter-from { opacity: 0; transform: scale(0.95) translateY(6px); }
.dep-list-move { transition: transform 0.25s ease; }

/* ── 节点日志 ── */
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light, #f5f7fa);
}
.pod-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.log-empty { padding: 32px 0; }
.log-panel {
  height: calc(100vh - 340px);
  min-height: 300px;
  overflow-y: auto;
  background: #0d1117;
  border-radius: 10px;
  padding: 12px 14px;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  animation: fade 0.25s ease;
  scrollbar-width: thin;
  scrollbar-color: #30363d #0d1117;
}
.log-panel::-webkit-scrollbar { width: 6px; }
.log-panel::-webkit-scrollbar-track { background: #0d1117; }
.log-panel::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
.log-content {
  margin: 0;
  color: #c9d1d9;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
