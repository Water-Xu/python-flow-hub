<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiAdminApi, apiPortalApi, flowApi, type PublishedApi, type FlowEntrypointsInfo, type ApiEncryptionKey } from '@/api'
import MqMockTestDialog from '@/components/MqMockTestDialog.vue'
import MqTriggerForm from '@/components/MqTriggerForm.vue'

const apis = ref<PublishedApi[]>([])
const flows = ref<any[]>([])
const overview = ref<any>(null)
const loading = ref(false)
const activeApi = ref<PublishedApi | null>(null)

// 面板控制
const policyDialogVisible = ref(false)
const lockDialogVisible = ref(false)
const versionDialogVisible = ref(false)
const docsDrawerVisible = ref(false)
const instanceDrawerVisible = ref(false)

const policyForm = ref({
  rate_limit_enabled: false,
  rate_limit_per_minute: 60,
  load_balance_strategy: 'round_robin',
  degradation_enabled: false,
  degradation_fallback: '{}',
})
const lockForm = ref({ lock_reason: '' })
const versionForm = ref({ new_flow_id: '' })
const docsData = ref<any>(null)
const instanceData = ref<any>(null)
const detailLoading = ref(false)

// ── MQ Mock 测试（接口/Flow 级）────────────────────────────────────────────
const mqTestVisible = ref(false)
const mqTestApi = ref<{ id: string; name: string; preset: Record<string, any> | null }>({
  id: '',
  name: '',
  preset: null,
})

function openMqTest(api: { id: string; name: string }, preset?: Record<string, any> | null) {
  mqTestApi.value = { id: api.id, name: api.name, preset: preset || null }
  mqTestVisible.value = true
}

// ── 触发配置（http/mq/both，Flow 级，决策 3.1）──────────────────────────────
const triggerDialogVisible = ref(false)
const triggerApi = ref<PublishedApi | null>(null)
const triggerFormRef = ref<InstanceType<typeof MqTriggerForm> | null>(null)
const triggerSaving = ref(false)

function openTriggerConfig(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已锁定，无法修改触发配置')
  triggerApi.value = api
  triggerDialogVisible.value = true
}

async function saveTrigger() {
  if (!triggerApi.value || !triggerFormRef.value) return
  if (triggerFormRef.value.errors.length) {
    return ElMessage.error(triggerFormRef.value.errors[0])
  }
  triggerSaving.value = true
  try {
    await apiPortalApi.updateMq(triggerApi.value.id, triggerFormRef.value.collect())
    ElMessage.success('触发配置已保存')
    triggerDialogVisible.value = false
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    triggerSaving.value = false
  }
}

async function load() {
  loading.value = true
  try {
    ;[apis.value, flows.value, overview.value] = await Promise.all([
      apiAdminApi.listAll(),
      flowApi.list(),
      apiAdminApi.getOverview(),
    ])
  } finally {
    loading.value = false
  }
}

function openPolicy(api: PublishedApi) {
  activeApi.value = api
  policyForm.value = {
    rate_limit_enabled: api.rate_limit_enabled,
    rate_limit_per_minute: api.rate_limit_per_minute,
    load_balance_strategy: api.load_balance_strategy,
    degradation_enabled: api.degradation_enabled,
    degradation_fallback: JSON.stringify(api.degradation_fallback || {}, null, 2),
  }
  policyDialogVisible.value = true
}

async function savePolicy() {
  if (!activeApi.value) return
  let fallback: object = {}
  try {
    fallback = JSON.parse(policyForm.value.degradation_fallback || '{}')
  } catch {
    return ElMessage.error('降级 fallback 必须是合法 JSON')
  }
  try {
    await apiAdminApi.updatePolicy(activeApi.value.id, {
      ...policyForm.value,
      degradation_fallback: fallback,
    })
    ElMessage.success('策略已更新')
    policyDialogVisible.value = false
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  }
}

function openLock(api: PublishedApi) {
  activeApi.value = api
  lockForm.value = { lock_reason: '' }
  lockDialogVisible.value = true
}

async function lockApi() {
  if (!activeApi.value) return
  try {
    await apiAdminApi.lock(activeApi.value.id, lockForm.value.lock_reason)
    ElMessage.success('接口已锁定，关联的块和流程现在只读')
    lockDialogVisible.value = false
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '锁定失败')
  }
}

async function unlockApi(api: PublishedApi) {
  await ElMessageBox.confirm(`确认解锁接口「${api.name}」？解锁后关联块/流程可再次编辑。`, '解锁确认', {
    type: 'warning',
  })
  try {
    await apiAdminApi.unlock(api.id)
    ElMessage.success('已解锁')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '解锁失败')
  }
}

function openVersionSwitch(api: PublishedApi) {
  activeApi.value = api
  versionForm.value = { new_flow_id: api.active_flow_id || api.flow_id }
  versionDialogVisible.value = true
}

async function switchVersion() {
  if (!activeApi.value) return
  try {
    await apiAdminApi.switchVersion(activeApi.value.id, versionForm.value.new_flow_id)
    ElMessage.success('版本切换成功，接口已平滑过渡到新版本流程')
    versionDialogVisible.value = false
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '切换失败')
  }
}

async function openDocs(api: PublishedApi) {
  activeApi.value = api
  docsDrawerVisible.value = true
  detailLoading.value = true
  try {
    docsData.value = await apiAdminApi.getDocs(api.id)
  } finally {
    detailLoading.value = false
  }
}

async function openInstances(api: PublishedApi) {
  activeApi.value = api
  instanceDrawerVisible.value = true
  detailLoading.value = true
  try {
    instanceData.value = await apiAdminApi.getInstances(api.id)
  } finally {
    detailLoading.value = false
  }
}

const statusType: Record<string, string> = {
  active: 'success',
  paused: 'warning',
  deprecated: 'danger',
}

const triggerTypeLabel: Record<string, string> = {
  http: 'HTTP', mq: 'MQ', both: 'HTTP+MQ',
}

const lbLabels: Record<string, string> = {
  round_robin: '轮询',
  least_conn: '最少连接',
  ip_hash: 'IP哈希',
}

const successRate = (api: PublishedApi) =>
  api.total_calls > 0 ? ((api.success_calls / api.total_calls) * 100).toFixed(1) + '%' : '—'

const errorRate = (api: PublishedApi) =>
  api.total_calls > 0 ? ((api.error_calls / api.total_calls) * 100).toFixed(1) + '%' : '—'

// ── 发布接口（从接口门户迁移来）──────────────────────────────────────────────
const publishDialogVisible = ref(false)
const publishForm = ref({
  name: '', description: '', path: '', tags: '',
  flow_id: '', entry_node_id: null as string | null, entrypoint_map: {} as Record<string, string>,
})
const flowEntrypointsInfo = ref<FlowEntrypointsInfo | null>(null)
const entrypointsLoading = ref(false)
watch(
  () => publishForm.value.flow_id,
  async (flowId) => {
    if (!flowId) { flowEntrypointsInfo.value = null; return }
    entrypointsLoading.value = true
    try {
      flowEntrypointsInfo.value = await apiPortalApi.getFlowEntrypoints(flowId)
    } catch { /* ignore */ } finally {
      entrypointsLoading.value = false
    }
  },
)
async function publish() {
  if (!publishForm.value.name || !publishForm.value.path || !publishForm.value.flow_id)
    return ElMessage.warning('请填写接口名称、路径和关联流程')
  try {
    await apiPortalApi.publish({
      name: publishForm.value.name, description: publishForm.value.description,
      path: publishForm.value.path, tags: publishForm.value.tags,
      flow_id: publishForm.value.flow_id, entry_node_id: publishForm.value.entry_node_id || null,
      entrypoint: null, entrypoint_map: { ...publishForm.value.entrypoint_map },
    })
    publishDialogVisible.value = false
    ElMessage.success('接口发布成功')
    publishForm.value = { name: '', description: '', path: '', tags: '', flow_id: '', entry_node_id: null, entrypoint_map: {} }
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '发布失败') }
}

// ── 加密（从接口门户迁移来）──────────────────────────────────────────────────
const encryptionDialogVisible = ref(false)
const encryptionApi = ref<PublishedApi | null>(null)
const encryptionInfo = ref<ApiEncryptionKey | null>(null)
const encryptionLoading = ref(false)
const encryptionSaving = ref(false)
const encEnabled = ref(false)
const encRequire = ref(false)
async function openEncryption(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已锁定，无法修改加密配置')
  encryptionApi.value = api
  encryptionInfo.value = null
  encEnabled.value = api.encryption_enabled
  encRequire.value = api.require_encrypted_request
  encryptionDialogVisible.value = true
  encryptionLoading.value = true
  try {
    encryptionInfo.value = await apiPortalApi.getEncryptionKey(api.id)
    encEnabled.value = encryptionInfo.value.encryption_enabled
    encRequire.value = encryptionInfo.value.require_encrypted_request
  } catch { /* 读取失败不阻断 */ } finally {
    encryptionLoading.value = false
  }
}
async function saveEncryption() {
  if (!encryptionApi.value) return
  encryptionSaving.value = true
  try {
    const res = await apiPortalApi.updateEncryption(encryptionApi.value.id, {
      enabled: encEnabled.value, require_encrypted_request: encRequire.value,
    })
    encryptionInfo.value = { ...res, encryption_key: res.encryption_key ?? encryptionInfo.value?.encryption_key ?? null }
    ElMessage.success(encEnabled.value ? '加密保护已开启' : '加密保护已关闭')
    encryptionDialogVisible.value = false
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { encryptionSaving.value = false }
}
async function rotateKey() {
  if (!encryptionApi.value) return
  await ElMessageBox.confirm('轮转后旧密钥立即失效，调用方需同步更新为新密钥。确认轮转？', '轮转密钥', { type: 'warning' })
  encryptionSaving.value = true
  try {
    encryptionInfo.value = await apiPortalApi.rotateEncryptionKey(encryptionApi.value.id)
    ElMessage.success('密钥已轮转，请复制并更新到调用方')
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '轮转失败') }
  finally { encryptionSaving.value = false }
}
async function copyKey() {
  const key = encryptionInfo.value?.encryption_key
  if (!key) return ElMessage.warning('当前无可复制的完整密钥，请轮转或重新开启以获取')
  try { await navigator.clipboard.writeText(key); ElMessage.success('密钥已复制') }
  catch { ElMessage.warning('复制失败，请手动选择复制') }
}
const javaConfigSnippet = computed(() => {
  const path = encryptionApi.value?.path || 'your-api-path'
  const key = encryptionInfo.value?.encryption_key || '（在此填入上方完整密钥）'
  return `flowhub:\n  encryption:\n    enabled: true\n    path-keys:\n      ${path}: "${key}"`
})

// ── 暂停 / 激活 ───────────────────────────────────────────────────────────────
async function toggleStatus(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已锁定，无法操作')
  try {
    if (api.status === 'active') { await apiPortalApi.pause(api.id); ElMessage.success('已暂停') }
    else { await apiPortalApi.activate(api.id); ElMessage.success('已激活') }
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '操作失败') }
}

// ── 复制流程 ──────────────────────────────────────────────────────────────────
async function copyFlow(api: PublishedApi) {
  try {
    const res = await apiPortalApi.copyFlow(api.flow_id)
    ElMessage.success(`已创建流程副本：${res.name}`)
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '复制失败') }
}

// ── 下线（从接口门户迁移来）──────────────────────────────────────────────────
async function unpublish(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已被管理员锁定，无法下线')
  await ElMessageBox.confirm(`确认下线接口「${api.name}」？`, '下线确认', { type: 'warning' })
  try {
    await apiPortalApi.unpublish(api.id); ElMessage.success('已下线'); load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '操作失败') }
}

/** 更多操作下拉统一路由 */
function handleMoreCmd(cmd: string, row: PublishedApi) {
  switch (cmd) {
    case 'docs':       openDocs(row); break
    case 'instances':  openInstances(row); break
    case 'version':    openVersionSwitch(row); break
    case 'encryption': openEncryption(row); break
    case 'lock':       row.is_locked ? unlockApi(row) : openLock(row); break
    case 'remarks':    openRemarksEdit(row); break
    case 'copy':       copyFlow(row); break
    case 'unpublish':  unpublish(row); break
  }
}


// ── 文档编辑（备注/示例/变更日志）───────────────────────────────────────────
const remarksDrawerVisible = ref(false)
const remarksApi = ref<PublishedApi | null>(null)
const remarksForm = ref({ remarks: '', sample_request: '', sample_response: '', changelog: '' })
const remarksSaving = ref(false)
function openRemarksEdit(api: PublishedApi) {
  remarksApi.value = api
  remarksForm.value = {
    remarks: api.remarks || '',
    sample_request: api.sample_request || '',
    sample_response: api.sample_response || '',
    changelog: api.changelog || '',
  }
  remarksDrawerVisible.value = true
}
async function saveRemarks() {
  if (!remarksApi.value) return
  remarksSaving.value = true
  try {
    await apiPortalApi.updateRemarks(remarksApi.value.id, remarksForm.value)
    ElMessage.success('文档已保存')
    remarksDrawerVisible.value = false
    load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { remarksSaving.value = false }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>接口管理中心</h2>
        <p class="dim">管理员视图 — 查看所有已发布接口、流量统计、实例负载，配置策略并锁定接口</p>
      </div>
      <el-button type="primary" @click="publishDialogVisible = true">
        <el-icon style="margin-right:6px"><Plus /></el-icon>发布接口
      </el-button>
    </header>

    <!-- 概览卡片 -->
    <div class="overview-grid" v-if="overview">
      <div class="pf-card overview-card" style="animation-delay:0ms">
        <div class="ov-icon"><el-icon size="24"><Connection /></el-icon></div>
        <div class="ov-info">
          <span class="ov-val">{{ overview.total_apis }}</span>
          <span class="ov-label">总接口数</span>
        </div>
      </div>
      <div class="pf-card overview-card" style="animation-delay:60ms">
        <div class="ov-icon green"><el-icon size="24"><CircleCheck /></el-icon></div>
        <div class="ov-info">
          <span class="ov-val">{{ overview.active_apis }}</span>
          <span class="ov-label">运行中</span>
        </div>
      </div>
      <div class="pf-card overview-card" style="animation-delay:120ms">
        <div class="ov-icon yellow"><el-icon size="24"><Lock /></el-icon></div>
        <div class="ov-info">
          <span class="ov-val">{{ overview.locked_apis }}</span>
          <span class="ov-label">已锁定</span>
        </div>
      </div>
      <div class="pf-card overview-card" style="animation-delay:180ms">
        <div class="ov-icon blue"><el-icon size="24"><Histogram /></el-icon></div>
        <div class="ov-info">
          <span class="ov-val">{{ overview.total_calls?.toLocaleString() }}</span>
          <span class="ov-label">总调用次数</span>
        </div>
      </div>
      <div class="pf-card overview-card" style="animation-delay:240ms">
        <div class="ov-icon" :class="overview.success_rate >= 99 ? 'green' : 'red'">
          <el-icon size="24"><TrendCharts /></el-icon>
        </div>
        <div class="ov-info">
          <span class="ov-val">{{ overview.success_rate }}%</span>
          <span class="ov-label">全局成功率</span>
        </div>
      </div>
    </div>

    <!-- 接口列表 -->
    <el-table v-loading="loading" :data="apis" class="api-table" row-class-name="api-row">
      <el-table-column label="接口名称 / 路径" min-width="200">
        <template #default="{ row }">
          <div class="cell-name">
            <el-icon v-if="row.is_locked" color="#f59e0b" style="flex-shrink:0"><Lock /></el-icon>
            <span class="name-text">{{ row.name }}</span>
          </div>
          <div class="cell-path">
            <code>POST /api/public/{{ row.path }}</code>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <!-- <el-tag :type="statusType[row.status] || 'info'" size="small" effect="light">
            {{ row.status }}
          </el-tag> -->
              <!-- 状态快切：运行中 / 已暂停 -->
              <el-tooltip :content="row.status === 'active' ? '点击暂停' : '点击激活'">
              <span
                class="status-toggle"
                :class="row.status === 'active' ? 'st-active' : 'st-paused'"
                :style="row.is_locked ? 'opacity:.45;cursor:not-allowed' : ''"
                @click="!row.is_locked && toggleStatus(row)"
              >
                <span class="st-dot" />
                {{ row.status === 'active' ? '运行中' : '已暂停' }}
              </span>
            </el-tooltip>
        </template>
      </el-table-column>

      <el-table-column label="负责人" prop="owner_login_id" width="120" />

      <el-table-column label="流量" width="180">
        <template #default="{ row }">
          <div class="traffic-cell">
            <span class="tc-total">{{ row.total_calls.toLocaleString() }} 次</span>
            <span class="tc-rate" :class="{ 'tc-ok': row.total_calls > 0 && row.error_calls / row.total_calls < 0.01 }">
              成功 {{ successRate(row) }}
            </span>
            <span class="tc-err">{{ row.avg_latency_ms.toFixed(0) }}ms 均延迟</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="策略" width="160">
        <template #default="{ row }">
          <div class="policy-tags"  >
            <el-tag v-if="row.rate_limit_enabled" size="small" type="warning" effect="plain" @click="openPolicy(row)">
              限流 {{ row.rate_limit_per_minute }}/min
            </el-tag>
            <el-tag size="small" type="info" effect="plain" @click="openPolicy(row)">
              {{ lbLabels[row.load_balance_strategy] || row.load_balance_strategy }}
            </el-tag>
            <el-tag v-if="row.degradation_enabled" size="small" type="danger" effect="plain" @click="openPolicy(row)">
              降级开
            </el-tag>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <div class="act-bar">
            <!-- 主操作：文档 + 策略 + 触发 -->
            <!-- <el-button size="small" class="act-btn" @click="openDocs(row)">
              <el-icon><Document /></el-icon>文档
            </el-button> -->
            <!-- <el-button size="small" class="act-btn act-btn-primary" @click="openPolicy(row)">
              <el-icon><Setting /></el-icon>限流
            </el-button> -->
            <el-button size="small" class="act-btn act-btn-primary" :disabled="row.is_locked" @click="openTriggerConfig(row)">
              <el-icon><MessageBox /></el-icon>触发
            </el-button>



            <!-- 更多操作下拉 -->
            <el-dropdown trigger="click" @command="(cmd) => handleMoreCmd(cmd, row)">
              <el-button size="small" class="act-btn act-more">
                更多<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu class="more-menu">
                  <!-- <el-dropdown-item command="docs" icon="Document">查看文档</el-dropdown-item> -->
                  <el-dropdown-item command="instances" icon="Monitor">实例负载</el-dropdown-item>
                  <el-dropdown-item command="version" icon="Switch">版本切换</el-dropdown-item>
                  <el-dropdown-item divided command="encryption" icon="Lock">
                    <span>加密保护</span>
                    <el-tag v-if="row.encryption_enabled" size="small" type="success" effect="plain" style="margin-left:6px">已开启</el-tag>
                  </el-dropdown-item>
                  <el-dropdown-item command="lock" icon="Lock">
                    <span>{{ row.is_locked ? '解锁接口' : '锁定接口' }}</span>
                    <el-tag v-if="row.is_locked" size="small" type="danger" effect="plain" style="margin-left:6px">已锁定</el-tag>
                  </el-dropdown-item>
                  <el-dropdown-item divided command="remarks" icon="EditPen">编辑文档</el-dropdown-item>
                  <el-dropdown-item command="copy" icon="CopyDocument">复制流程</el-dropdown-item>
                  <el-dropdown-item divided command="unpublish" icon="Delete" :disabled="row.is_locked">
                    <span style="color:#ef4444">下线接口</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 策略配置 Dialog -->
    <el-dialog v-model="policyDialogVisible" title="接口策略配置" width="520px">
      <el-form label-width="100px" v-if="activeApi">
        <el-divider content-position="left">限流</el-divider>
        <el-form-item label="启用限流">
          <el-switch v-model="policyForm.rate_limit_enabled" />
        </el-form-item>
        <el-form-item label="每分钟上限" v-if="policyForm.rate_limit_enabled">
          <el-input-number v-model="policyForm.rate_limit_per_minute" :min="1" :max="100000" />
          <span class="dim" style="margin-left:8px">次/分钟</span>
        </el-form-item>

        <el-divider content-position="left">负载均衡</el-divider>
        <el-form-item label="均衡策略">
          <el-radio-group v-model="policyForm.load_balance_strategy">
            <el-radio-button value="round_robin">轮询</el-radio-button>
            <el-radio-button value="least_conn">最少连接</el-radio-button>
            <el-radio-button value="ip_hash">IP哈希</el-radio-button>
          </el-radio-group>
          <p class="dim" style="margin:4px 0 0">Phase 4+ K8s 模式下生效</p>
        </el-form-item>

        <el-divider content-position="left">降级</el-divider>
        <el-form-item label="启用降级">
          <el-switch v-model="policyForm.degradation_enabled" />
          <span class="dim" style="margin-left:8px">开启后直接返回 fallback，不执行流程</span>
        </el-form-item>
        <el-form-item label="Fallback JSON" v-if="policyForm.degradation_enabled">
          <el-input
            v-model="policyForm.degradation_fallback"
            type="textarea"
            :rows="4"
            placeholder='{"status": "degraded", "message": "服务暂时不可用"}'
            style="font-family: monospace; font-size: 12px"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="policyDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="savePolicy">保存策略</el-button>
      </template>
    </el-dialog>

    <!-- 锁定 Dialog -->
    <el-dialog v-model="lockDialogVisible" title="锁定接口" width="440px">
      <div class="lock-warning">
        <el-icon size="32" color="#f59e0b"><Warning /></el-icon>
        <div>
          <p><strong>锁定「{{ activeApi?.name }}」后：</strong></p>
          <ul>
            <li>关联的块和流程禁止任何人修改</li>
            <li>只允许为关联资源创建副本 / 新版本</li>
            <li>接口本身仍正常运行</li>
          </ul>
        </div>
      </div>
      <el-form label-width="70px" style="margin-top:16px">
        <el-form-item label="锁定原因">
          <el-input v-model="lockForm.lock_reason" placeholder="说明锁定原因（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="lockDialogVisible = false">取消</el-button>
        <el-button type="warning" @click="lockApi">确认锁定</el-button>
      </template>
    </el-dialog>

    <!-- 版本切换 Dialog -->
    <el-dialog v-model="versionDialogVisible" title="平滑切换版本" width="500px">
      <div class="version-info" v-if="activeApi">
        <div class="version-row">
          <span class="vr-label">当前版本流程：</span>
          <el-tag type="info">{{ activeApi.active_flow_id || activeApi.flow_id }}</el-tag>
        </div>
        <el-icon size="20" style="margin: 6px 0; color: var(--pf-accent)"><ArrowDown /></el-icon>
        <div class="version-row">
          <span class="vr-label">切换到新版本：</span>
          <el-select v-model="versionForm.new_flow_id" style="flex:1" placeholder="选择新版本流程">
            <el-option
              v-for="f in flows"
              :key="f.id"
              :label="`${f.name}（${f.id.slice(0, 8)}）`"
              :value="f.id"
            />
          </el-select>
        </div>
        <el-alert
          type="success"
          :closable="false"
          show-icon
          style="margin-top:14px"
          title="平滑过渡说明"
          description="切换后接口立即调用新版本流程，原版本流程（若已锁定）保持只读。可随时再次切换回旧版本。"
        />
      </div>
      <template #footer>
        <el-button @click="versionDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="switchVersion">确认切换</el-button>
      </template>
    </el-dialog>

    <!-- 接口文档 Drawer -->
    <el-drawer v-model="docsDrawerVisible" title="接口文档" size="520px" direction="rtl">
      <div v-loading="detailLoading">
        <template v-if="docsData">
          <el-descriptions :column="1" border size="small" style="margin-bottom:16px">
            <el-descriptions-item label="接口名称">{{ docsData.name }}</el-descriptions-item>
            <el-descriptions-item label="调用路径">
              <code>{{ docsData.method }} {{ docsData.path }}</code>
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="statusType[docsData.status] || 'info'">{{ docsData.status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="锁定">
              <el-tag :type="docsData.is_locked ? 'warning' : 'success'">
                {{ docsData.is_locked ? '已锁定' : '未锁定' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="负责人">{{ docsData.owner_login_id }}</el-descriptions-item>
            <el-descriptions-item label="关联流程">{{ docsData.flow_name }}</el-descriptions-item>
            <el-descriptions-item label="触发方式">
              <el-tag :type="docsData.trigger_type === 'http' ? 'info' : 'primary'" size="small">
                {{ triggerTypeLabel[docsData.trigger_type] || 'HTTP' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <div class="stats-box">
            <div class="sb-item">
              <span class="sb-val">{{ docsData.stats?.total_calls?.toLocaleString() }}</span>
              <span class="sb-label">总调用</span>
            </div>
            <div class="sb-item">
              <span class="sb-val text-success">{{ docsData.stats?.success_rate }}%</span>
              <span class="sb-label">成功率</span>
            </div>
            <div class="sb-item">
              <span class="sb-val">{{ docsData.stats?.avg_latency_ms }}ms</span>
              <span class="sb-label">均延迟</span>
            </div>
          </div>

          <!-- 通过 MQ 触发（接口/Flow 级，决策 3.1 Flow 级模型 A）-->
          <transition name="mq-section">
            <div v-if="docsData.mq_invocation" class="mq-invoke" style="margin-top:16px">
              <div class="mq-invoke-head">
                <el-icon><MessageBox /></el-icon>
                <span>通过 MQ 触发（异步驱动整条流程）</span>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  class="mq-test-btn"
                  v-if="activeApi"
                  @click="openMqTest(activeApi, docsData.mq_invocation.message_example)"
                >
                  <el-icon style="margin-right:4px"><VideoPlay /></el-icon>Mock 测试
                </el-button>
              </div>
              <div class="mq-kv-grid">
                <div class="mq-kv"><span class="mq-k">主队列</span><code>{{ docsData.mq_invocation.queue }}</code></div>
                <div class="mq-kv"><span class="mq-k">交换机</span><code>{{ docsData.mq_invocation.exchange }}</code></div>
                <div class="mq-kv"><span class="mq-k">路由键</span><code>{{ docsData.mq_invocation.routing_key }}</code></div>
                <div class="mq-kv"><span class="mq-k">死信队列</span><code>{{ docsData.mq_invocation.dlq_queue }}</code></div>
                <div class="mq-kv">
                  <span class="mq-k">重试</span>
                  <span>{{ docsData.mq_invocation.max_retry }} 次 / {{ docsData.mq_invocation.retry_delay_ms }}ms</span>
                </div>
                <div class="mq-kv">
                  <span class="mq-k">回复</span>
                  <el-tag size="small" :type="docsData.mq_invocation.reply_enabled ? 'success' : 'info'" effect="plain">
                    {{ docsData.mq_invocation.reply_enabled ? '开启' : '关闭' }}
                  </el-tag>
                </div>
              </div>
              <div v-if="docsData.mq_invocation.condition_expression" class="mq-line">
                <span class="mq-k">条件订阅</span>
                <code>{{ docsData.mq_invocation.condition_language }}: {{ docsData.mq_invocation.condition_expression }}</code>
              </div>
              <div v-if="Object.keys(docsData.mq_invocation.input_mapping || {}).length" class="mq-line">
                <span class="mq-k">字段映射（流程输入 ← 消息路径）</span>
                <ul class="port-list">
                  <li v-for="(src, target) in docsData.mq_invocation.input_mapping" :key="target">
                    <code>{{ target }}</code><span class="dim">←</span><code>{{ src }}</code>
                  </li>
                </ul>
              </div>
              <div class="mq-line">
                <span class="mq-k">示例消息体</span>
                <pre class="mq-code">{{ JSON.stringify(docsData.mq_invocation.message_example, null, 2) }}</pre>
              </div>
            </div>
          </transition>

          <el-divider>调用块详情</el-divider>

          <el-collapse accordion v-if="docsData.blocks?.length">
            <el-collapse-item
              v-for="block in docsData.blocks"
              :key="block.node_id || block.block_id"
              :title="block.block_name"
            >
              <template #title>
                <span>{{ block.block_name }}</span>
              </template>
              <p class="dim">{{ block.description || '暂无描述' }}</p>
              <p><strong>入口函数：</strong><code>{{ block.entrypoint || 'run' }}</code></p>
              <div class="port-grid">
                <div>
                  <strong>输入端口</strong>
                  <ul class="port-list">
                    <li v-for="p in block.input_ports" :key="p.name">
                      <code>{{ p.name }}</code>
                      <span class="dim">{{ p.type }}</span>
                    </li>
                    <li v-if="!block.input_ports?.length" class="dim">无</li>
                  </ul>
                </div>
                <div>
                  <strong>输出端口</strong>
                  <ul class="port-list">
                    <li v-for="p in block.output_ports" :key="p.name">
                      <code>{{ p.name }}</code>
                      <span class="dim">{{ p.type }}</span>
                    </li>
                    <li v-if="!block.output_ports?.length" class="dim">无</li>
                  </ul>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </template>
      </div>
    </el-drawer>

    <!-- 实例负载 Drawer -->
    <el-drawer v-model="instanceDrawerVisible" title="实例负载" size="440px" direction="rtl">
      <div v-loading="detailLoading">
        <template v-if="instanceData">
          <el-alert
            :type="instanceData.deployment_mode === 'local' ? 'info' : 'success'"
            :title="`部署模式：${instanceData.deployment_mode}`"
            :description="instanceData.deployment_mode === 'local' ? 'Dev 本地模式，1 个进程内实例；K8s 模式下显示真实 Pod 列表（Phase 4+）' : ''"
            :closable="false"
            show-icon
            style="margin-bottom:16px"
          />

          <div class="instance-header">
            <span>实例数量（Ready）：<strong>{{ instanceData.instance_count }}</strong></span>
            <span class="dim" style="font-size:12px;margin-left:8px">共 {{ instanceData.instances.length }} 个 Deployment</span>
          </div>

          <transition-group name="list" tag="div">
            <div
              v-for="inst in instanceData.instances"
              :key="inst.pod_name"
              class="instance-card pf-card"
              :class="`inst-kind-${inst.kind || 'block'}`"
            >
              <div class="inst-row">
                <el-icon :color="inst.ready ? '#22c55e' : (inst.status === 'degraded' ? '#e6a23c' : '#909399')">
                  <CircleCheck v-if="inst.ready" />
                  <Warning v-else-if="inst.status === 'degraded'" />
                  <Remove v-else />
                </el-icon>
                <span class="inst-name">{{ inst.pod_name }}</span>
                <el-tag
                  :type="inst.status === 'running' ? 'success' : inst.status === 'degraded' ? 'warning' : inst.status === 'stopped' ? 'danger' : 'info'"
                  size="small"
                >
                  {{ inst.status === 'scaled_down' ? '已缩零' : inst.status === 'degraded' ? '降级' : inst.status === 'stopped' ? '已停止' : inst.status }}
                </el-tag>
                <el-tag v-if="inst.kind === 'flow_consumer'" size="small" type="primary" effect="plain" style="margin-left:2px">
                  MQ消费者
                </el-tag>
              </div>
              <div class="inst-detail">
                <span class="dim">{{ inst.label || inst.block_name || '—' }}</span>
                <span>副本: {{ inst.replicas }}</span>
                <span v-if="inst.kind !== 'flow_consumer' && inst.cpu_usage !== '—'">CPU: {{ inst.cpu_usage }}</span>
              </div>
            </div>
          </transition-group>
        </template>
      </div>
    </el-drawer>

    <!-- ─── 发布接口 Dialog ─────────────────────────────────────────────────── -->
    <el-dialog v-model="publishDialogVisible" title="发布接口" width="600px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="接口名称" required>
          <el-input v-model="publishForm.name" placeholder="例如 向量检索接口" />
        </el-form-item>
        <el-form-item label="URL 路径" required>
          <el-input v-model="publishForm.path" placeholder="例如 vector-search（仅字母/数字/下划线/短横线）">
            <template #prepend>/api/public/</template>
          </el-input>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="publishForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="publishForm.tags" placeholder="逗号分隔，如 search,ai,vector" />
        </el-form-item>
        <el-form-item label="关联流程" required>
          <el-select v-model="publishForm.flow_id" style="width:100%" placeholder="选择要发布的流程" filterable>
            <el-option v-for="f in flows" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="flowEntrypointsInfo?.entry_node_id" label="入口节点">
          <el-tag type="success">已由流程配置（{{ flowEntrypointsInfo?.nodes.find(n => n.node_id === flowEntrypointsInfo?.entry_node_id)?.block_name || publishForm.entry_node_id }}）</el-tag>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="publishDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="publish">发布</el-button>
      </template>
    </el-dialog>

    <!-- ─── 加密保护 Dialog ─────────────────────────────────────────────────── -->
    <el-dialog v-model="encryptionDialogVisible" :title="`加密保护 - ${encryptionApi?.name || ''}`" width="540px" destroy-on-close>
      <div v-loading="encryptionLoading">
        <div class="enc-status-row">
          <div class="enc-status-label">AES-256-GCM 加密</div>
          <el-switch v-model="encEnabled" active-text="开启" inactive-text="关闭" />
        </div>
        <el-form-item v-if="encEnabled" label="强制加密" style="margin-top:12px">
          <el-switch v-model="encRequire" />
          <span class="dim" style="margin-left:8px">开启后拒绝明文请求</span>
        </el-form-item>
        <template v-if="encryptionInfo?.key_hint">
          <el-divider />
          <div class="key-section">
            <div class="key-hint-row">
              <span class="dim">密钥指纹：</span>
              <code>{{ encryptionInfo.key_hint }}...</code>
              <el-button text size="small" @click="rotateKey" :loading="encryptionSaving">轮转密钥</el-button>
            </div>
            <template v-if="encryptionInfo.encryption_key">
              <el-input :value="encryptionInfo.encryption_key" readonly class="key-input" size="small">
                <template #append>
                  <el-button @click="copyKey">复制</el-button>
                </template>
              </el-input>
            </template>
            <el-divider content-position="left"><span class="dim" style="font-size:12px">Java 调用方配置示例</span></el-divider>
            <pre class="code-block">{{ javaConfigSnippet }}</pre>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="encryptionDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="encryptionSaving" @click="saveEncryption">保存</el-button>
      </template>
    </el-dialog>

    <!-- ─── 编辑文档 Drawer ─────────────────────────────────────────────────── -->
    <el-drawer
      v-model="remarksDrawerVisible"
      :title="`编辑文档 — ${remarksApi?.name || ''}`"
      size="600px"
      direction="rtl"
    >
      <div class="remarks-edit">
        <el-form label-position="top">
          <el-form-item label="开发者备注（将展示在接口门户文档中）">
            <el-input
              v-model="remarksForm.remarks"
              type="textarea"
              :rows="4"
              placeholder="描述接口用途、调用限制、注意事项等..."
            />
          </el-form-item>
          <el-form-item label="示例请求体（JSON 格式，留空则自动生成）">
            <el-input
              v-model="remarksForm.sample_request"
              type="textarea"
              :rows="6"
              placeholder='{"inputs": {"text": "Spring Cloud 微服务架构"}}'
              style="font-family: monospace; font-size: 12px"
            />
          </el-form-item>
          <el-form-item label="示例响应体（JSON 格式，留空则自动生成）">
            <el-input
              v-model="remarksForm.sample_response"
              type="textarea"
              :rows="6"
              placeholder='{"outputs": {"results": []}, "status": "succeeded"}'
              style="font-family: monospace; font-size: 12px"
            />
          </el-form-item>
          <el-form-item label="变更日志（Markdown，记录版本历史）">
            <el-input
              v-model="remarksForm.changelog"
              type="textarea"
              :rows="5"
              placeholder="## v1.1.0 (2026-06-11)&#10;- 新增批量向量化支持&#10;- 优化延迟性能"
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="remarksDrawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="remarksSaving" @click="saveRemarks">保存文档</el-button>
      </template>
    </el-drawer>

    <!-- MQ Mock 测试 Dialog（复用组件） -->
    <MqMockTestDialog
      v-model="mqTestVisible"
      :api-id="mqTestApi.id"
      :api-name="mqTestApi.name"
      :preset-payload="mqTestApi.preset"
    />

    <!-- 触发配置 Dialog（http/mq/both，Flow 级） -->
    <el-dialog
      v-model="triggerDialogVisible"
      :title="`触发配置 - ${triggerApi?.name || ''}`"
      width="640px"
      destroy-on-close
    >
      <MqTriggerForm
        v-if="triggerApi"
        ref="triggerFormRef"
        :api-id="triggerApi.id"
        :trigger-type="triggerApi.trigger_type"
        :mq-config="triggerApi.mq_config"
      />
      <template #footer>
        <el-button @click="triggerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="triggerSaving" @click="saveTrigger">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 24px;
}
.page-head h2 {
  margin: 0;
  font-size: 22px;
}
.dim {
  color: var(--pf-text-dim);
  font-size: 13px;
  margin: 4px 0 0;
}

/* 概览卡片 */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}
.overview-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
  animation: slide-up 0.4s ease both;
}
@keyframes slide-up {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.ov-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ov-icon.green { background: rgba(34,197,94,0.12); color: #22c55e; }
.ov-icon.yellow { background: rgba(245,158,11,0.12); color: #f59e0b; }
.ov-icon.blue { background: rgba(8,145,178,0.12); color: #0891b2; }
.ov-icon.red { background: rgba(239,68,68,0.12); color: #ef4444; }
.ov-info {
  display: flex;
  flex-direction: column;
}
.ov-val {
  font-size: 22px;
  font-weight: 700;
  line-height: 1;
}
.ov-label {
  font-size: 12px;
  color: var(--pf-text-dim);
  margin-top: 4px;
}

/* 接口表格 */
.api-table {
  border-radius: 12px;
  overflow: hidden;
}
.cell-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.name-text {
  font-size: 14px;
}
.cell-path code {
  font-size: 12px;
  color: var(--pf-accent);
  background: var(--pf-accent-soft);
  padding: 1px 5px;
  border-radius: 3px;
}
.traffic-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tc-total { font-size: 14px; font-weight: 600; }
.tc-rate { font-size: 12px; color: var(--pf-text-dim); }
.tc-rate.tc-ok { color: #22c55e; }
.tc-err { font-size: 12px; color: var(--pf-text-dim); }
.policy-tags {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.action-btns {
  display: flex;
  gap: 6px;
}

/* ── 新版操作栏 ──────────────────────────────────── */
.act-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
}
.act-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0 9px;
  height: 26px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid var(--pf-border-strong, #d8dce3);
  background: var(--pf-panel, #fff);
  color: var(--pf-text, #1f2329);
  cursor: pointer;
  transition: all .15s ease;
  white-space: nowrap;
  flex-shrink: 0;
}
.act-btn:hover {
  border-color: var(--pf-accent, #2563eb);
  color: var(--pf-accent, #2563eb);
  background: rgba(37,99,235,.05);
}
.act-btn.act-btn-primary {
  background: rgba(37,99,235,.06);
  border-color: rgba(37,99,235,.3);
  color: var(--pf-accent, #2563eb);
}
.act-btn.act-btn-primary:hover {
  background: rgba(37,99,235,.14);
  border-color: var(--pf-accent, #2563eb);
}
.act-btn.act-more {
  background: var(--pf-panel-2, #f0f2f5);
  border-color: var(--pf-border, #e5e7eb);
  color: var(--pf-text-dim, #6b7280);
}
.act-btn.act-more:hover {
  background: var(--pf-border, #e5e7eb);
  color: var(--pf-text, #1f2329);
  border-color: var(--pf-border-strong, #d8dce3);
}
.act-btn:disabled { opacity: .45; cursor: not-allowed; pointer-events: none; }

/* 状态快切徽章 */
.status-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s;
  border: 1px solid;
  flex-shrink: 0;
  user-select: none;
}
.status-toggle.st-active {
  background: #dcfce7;
  color: #15803d;
  border-color: #bbf7d0;
}
.status-toggle.st-active:hover { background: #bbf7d0; }
.status-toggle.st-paused {
  background: #fef3c7;
  color: #b45309;
  border-color: #fde68a;
}
.status-toggle.st-paused:hover { background: #fde68a; }
.st-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: blink 1.5s ease-in-out infinite;
}
.st-paused .st-dot { animation: none; opacity: .6; }
@keyframes blink {
  0%,100% { opacity: 1; }
  50% { opacity: .3; }
}

/* 下拉菜单微调 */
.more-menu :deep(.el-dropdown-menu__item) {
  font-size: 13px;
  padding: 7px 16px;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 锁定警告 */
.lock-warning {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 14px;
  background: rgba(245,158,11,0.08);
  border-radius: 8px;
  border: 1px solid rgba(245,158,11,0.3);
}
.lock-warning p { margin: 0 0 4px; }
.lock-warning ul {
  margin: 6px 0 0;
  padding-left: 16px;
  font-size: 13px;
  color: var(--pf-text-dim);
}

/* 版本切换 */
.version-info {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.version-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.vr-label {
  font-size: 13px;
  color: var(--pf-text-dim);
  flex-shrink: 0;
}

/* 统计盒子（抽屉内） */
.stats-box {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  background: var(--pf-panel-2);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}
.sb-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.sb-val { font-size: 18px; font-weight: 700; }
.sb-label { font-size: 12px; color: var(--pf-text-dim); }
.text-success { color: #22c55e; }

/* 实例卡片 */
.instance-header {
  font-size: 14px;
  margin-bottom: 12px;
}
.instance-card {
  padding: 12px 14px;
  margin-bottom: 10px;
}
.inst-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.inst-name {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  font-family: monospace;
}
.inst-detail {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--pf-text-dim);
}
.inst-kind-flow_consumer {
  border-left: 3px solid var(--pf-accent);
  opacity: 0.85;
}

/* 端口列表 */
.port-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 8px;
}
.port-list {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.port-list li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

/* ── MQ 调用方式区 ── */
.mq-invoke {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--pf-accent-soft);
  border-radius: 8px;
  background: var(--pf-accent-soft);
}
.mq-invoke-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13px;
  color: var(--pf-accent);
  margin-bottom: 10px;
}
.mq-test-btn { margin-left: auto; }
.mq-kv-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
}
.mq-kv {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.mq-k {
  color: var(--pf-text-dim);
  font-size: 11px;
  min-width: 60px;
  flex-shrink: 0;
}
.mq-kv code {
  background: var(--pf-panel);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  word-break: break-all;
}
.mq-line { margin-top: 10px; font-size: 12px; }
.mq-line code {
  background: var(--pf-panel);
  padding: 1px 6px;
  border-radius: 4px;
}
.mq-code {
  background: var(--pf-code-bg);
  color: var(--pf-code-text);
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  overflow-x: auto;
  margin: 6px 0 0;
}
.mq-section-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.mq-section-enter-from { opacity: 0; transform: translateY(8px); }

/* 加密 Dialog */
.enc-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: rgba(0,0,0,.12);
  border-radius: 8px;
  margin-bottom: 8px;
}
.enc-status-label { font-weight: 600; font-size: 14px; }
.key-section { display: flex; flex-direction: column; gap: 8px; }
.key-hint-row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.key-input :deep(.el-input__inner) { font-family: monospace; font-size: 11px; }
.code-block {
  background: rgba(0,0,0,.25);
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 12px;
  font-family: monospace;
  color: #a5d6ff;
  overflow-x: auto;
  margin: 0;
}

/* 文档编辑 */
.remarks-edit { padding: 0 4px; }
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
