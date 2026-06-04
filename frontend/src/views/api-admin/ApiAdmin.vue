<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiAdminApi, flowApi, type PublishedApi } from '@/api'
import MqMockTestDialog from '@/components/MqMockTestDialog.vue'

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

// ── MQ Mock 测试 ──────────────────────────────────────────────────────────
const mqTestVisible = ref(false)
const mqTestBlock = ref<{ id: string; name: string; preset: Record<string, any> | null }>({
  id: '',
  name: '',
  preset: null,
})

function openMqTest(block: any) {
  mqTestBlock.value = {
    id: block.mq_invocation?.block_id || block.block_id,
    name: block.block_name,
    preset: block.mq_invocation?.message_example || null,
  }
  mqTestVisible.value = true
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

const lbLabels: Record<string, string> = {
  round_robin: '轮询',
  least_conn: '最少连接',
  ip_hash: 'IP哈希',
}

const successRate = (api: PublishedApi) =>
  api.total_calls > 0 ? ((api.success_calls / api.total_calls) * 100).toFixed(1) + '%' : '—'

const errorRate = (api: PublishedApi) =>
  api.total_calls > 0 ? ((api.error_calls / api.total_calls) * 100).toFixed(1) + '%' : '—'

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>接口管理中心</h2>
        <p class="dim">管理员视图 — 查看所有已发布接口、流量统计、实例负载，配置策略并锁定接口</p>
      </div>
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
          <el-tag :type="statusType[row.status] || 'info'" size="small" effect="light">
            {{ row.status }}
          </el-tag>
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
          <div class="policy-tags">
            <el-tag v-if="row.rate_limit_enabled" size="small" type="warning" effect="plain">
              限流 {{ row.rate_limit_per_minute }}/min
            </el-tag>
            <el-tag size="small" type="info" effect="plain">
              {{ lbLabels[row.load_balance_strategy] || row.load_balance_strategy }}
            </el-tag>
            <el-tag v-if="row.degradation_enabled" size="small" type="danger" effect="plain">
              降级开
            </el-tag>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="320" fixed="right">
        <template #default="{ row }">
          <div class="action-btns">
            <el-tooltip content="接口文档">
              <el-button size="small" circle @click="openDocs(row)">
                <el-icon><Document /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="实例负载">
              <el-button size="small" circle @click="openInstances(row)">
                <el-icon><Monitor /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="策略配置">
              <el-button size="small" circle type="primary" @click="openPolicy(row)">
                <el-icon><Setting /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="版本切换">
              <el-button size="small" circle type="info" @click="openVersionSwitch(row)">
                <el-icon><Switch /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip :content="row.is_locked ? '解锁接口' : '锁定接口'">
              <el-button
                size="small"
                circle
                :type="row.is_locked ? 'danger' : 'warning'"
                @click="row.is_locked ? unlockApi(row) : openLock(row)"
              >
                <el-icon><component :is="row.is_locked ? 'Unlock' : 'Lock'" /></el-icon>
              </el-button>
            </el-tooltip>
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
            <el-descriptions-item label="MQ 调用">
              <el-tag v-if="docsData.mq_supported" type="primary" size="small">
                {{ docsData.mq_block_count }} 个块支持
              </el-tag>
              <span v-else class="dim">不支持</span>
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

          <el-divider>调用块详情</el-divider>

          <el-collapse accordion v-if="docsData.blocks?.length">
            <el-collapse-item
              v-for="block in docsData.blocks"
              :key="block.node_id || block.block_id"
              :title="block.block_name"
            >
              <template #title>
                <span>{{ block.block_name }}</span>
                <el-tag
                  v-if="block.mq_invocation"
                  size="small"
                  type="primary"
                  effect="plain"
                  style="margin-left:8px"
                >
                  <el-icon style="margin-right:3px"><MessageBox /></el-icon>支持 MQ 调用
                </el-tag>
              </template>
              <p class="dim">{{ block.description || '暂无描述' }}</p>
              <p><strong>执行模式：</strong>{{ block.execution_mode }}</p>
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

              <!-- 通过 MQ 调用 -->
              <transition name="mq-section">
                <div v-if="block.mq_invocation" class="mq-invoke">
                  <div class="mq-invoke-head">
                    <el-icon><MessageBox /></el-icon>
                    <span>通过 MQ 调用</span>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      class="mq-test-btn"
                      @click="openMqTest(block)"
                    >
                      <el-icon style="margin-right:4px"><VideoPlay /></el-icon>Mock 测试
                    </el-button>
                  </div>
                  <div class="mq-kv-grid">
                    <div class="mq-kv"><span class="mq-k">主队列</span><code>{{ block.mq_invocation.queue }}</code></div>
                    <div class="mq-kv"><span class="mq-k">交换机</span><code>{{ block.mq_invocation.exchange }}</code></div>
                    <div class="mq-kv"><span class="mq-k">路由键</span><code>{{ block.mq_invocation.routing_key }}</code></div>
                    <div class="mq-kv"><span class="mq-k">死信队列</span><code>{{ block.mq_invocation.dlq_queue }}</code></div>
                    <div class="mq-kv">
                      <span class="mq-k">重试</span>
                      <span>{{ block.mq_invocation.max_retry }} 次 / {{ block.mq_invocation.retry_delay_ms }}ms</span>
                    </div>
                    <div class="mq-kv">
                      <span class="mq-k">回复</span>
                      <el-tag size="small" :type="block.mq_invocation.reply_enabled ? 'success' : 'info'" effect="plain">
                        {{ block.mq_invocation.reply_enabled ? '开启' : '关闭' }}
                      </el-tag>
                    </div>
                  </div>
                  <div v-if="block.mq_invocation.condition_expression" class="mq-line">
                    <span class="mq-k">条件订阅</span>
                    <code>{{ block.mq_invocation.condition_language }}: {{ block.mq_invocation.condition_expression }}</code>
                  </div>
                  <div v-if="Object.keys(block.mq_invocation.input_mapping || {}).length" class="mq-line">
                    <span class="mq-k">字段映射（输入字段 ← 消息路径）</span>
                    <ul class="port-list">
                      <li v-for="(src, target) in block.mq_invocation.input_mapping" :key="target">
                        <code>{{ target }}</code><span class="dim">←</span><code>{{ src }}</code>
                      </li>
                    </ul>
                  </div>
                  <div class="mq-line">
                    <span class="mq-k">示例消息体</span>
                    <pre class="mq-code">{{ JSON.stringify(block.mq_invocation.message_example, null, 2) }}</pre>
                  </div>
                </div>
              </transition>
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
            <span>实例数量：<strong>{{ instanceData.instance_count }}</strong></span>
          </div>

          <transition-group name="list" tag="div">
            <div
              v-for="inst in instanceData.instances"
              :key="inst.pod_name"
              class="instance-card pf-card"
            >
              <div class="inst-row">
                <el-icon :color="inst.ready ? '#22c55e' : '#ef4444'">
                  <component :is="inst.ready ? 'CircleCheck' : 'CircleClose'" />
                </el-icon>
                <span class="inst-name">{{ inst.pod_name }}</span>
                <el-tag :type="inst.status === 'running' ? 'success' : 'danger'" size="small">
                  {{ inst.status }}
                </el-tag>
              </div>
              <div class="inst-detail" v-if="inst.cpu_usage !== '—'">
                <span>CPU: {{ inst.cpu_usage }}</span>
                <span>Mem: {{ inst.memory_usage }}</span>
                <span>重启: {{ inst.restart_count }}</span>
              </div>
              <div class="inst-detail dim" v-else>
                Dev 本地模式 — 无 Pod 指标
              </div>
            </div>
          </transition-group>
        </template>
      </div>
    </el-drawer>

    <!-- MQ Mock 测试 Dialog（复用组件） -->
    <MqMockTestDialog
      v-model="mqTestVisible"
      :block-id="mqTestBlock.id"
      :block-name="mqTestBlock.name"
      :preset-payload="mqTestBlock.preset"
    />
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
</style>
