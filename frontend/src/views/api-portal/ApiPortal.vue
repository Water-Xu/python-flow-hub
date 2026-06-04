<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiPortalApi, flowApi, type PublishedApi } from '@/api'

const apis = ref<PublishedApi[]>([])
const flows = ref<any[]>([])
const loading = ref(false)
const publishDialogVisible = ref(false)
const docsDialogVisible = ref(false)
const selectedApi = ref<PublishedApi | null>(null)
const docsData = ref<any>(null)
const docsLoading = ref(false)

const form = ref({
  name: '',
  description: '',
  path: '',
  tags: '',
  flow_id: '',
})

async function load() {
  loading.value = true
  try {
    ;[apis.value, flows.value] = await Promise.all([apiPortalApi.list(), flowApi.list()])
  } finally {
    loading.value = false
  }
}

async function publish() {
  if (!form.value.name || !form.value.path || !form.value.flow_id) {
    return ElMessage.warning('请填写接口名称、路径和关联流程')
  }
  try {
    await apiPortalApi.publish(form.value)
    publishDialogVisible.value = false
    ElMessage.success('接口发布成功')
    resetForm()
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '发布失败')
  }
}

async function toggleStatus(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已锁定，无法操作')
  try {
    if (api.status === 'active') {
      await apiPortalApi.pause(api.id)
      ElMessage.success('已暂停')
    } else {
      await apiPortalApi.activate(api.id)
      ElMessage.success('已激活')
    }
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function unpublish(api: PublishedApi) {
  if (api.is_locked) return ElMessage.warning('接口已被管理员锁定，无法下线')
  await ElMessageBox.confirm(`确认下线接口「${api.name}」？`, '下线确认', { type: 'warning' })
  try {
    await apiPortalApi.unpublish(api.id)
    ElMessage.success('已下线')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function copyFlow(api: PublishedApi) {
  try {
    const res = await apiPortalApi.copyFlow(api.flow_id)
    ElMessage.success(`已创建流程副本：${res.name}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '复制失败')
  }
}

async function viewDocs(api: PublishedApi) {
  selectedApi.value = api
  docsDialogVisible.value = true
  docsLoading.value = true
  try {
    docsData.value = await apiPortalApi.getDocs(api.id)
  } finally {
    docsLoading.value = false
  }
}

function resetForm() {
  form.value = { name: '', description: '', path: '', tags: '', flow_id: '' }
}

const statusType: Record<string, string> = {
  active: 'success',
  paused: 'warning',
  deprecated: 'danger',
}

const successRate = (api: PublishedApi) =>
  api.total_calls > 0 ? ((api.success_calls / api.total_calls) * 100).toFixed(1) : '—'

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>接口门户</h2>
        <p class="dim">将流程发布为可调用的 HTTP 接口，支持限流 / 降级 / 版本平滑切换</p>
      </div>
      <el-button type="primary" @click="publishDialogVisible = true">
        <el-icon style="margin-right:6px"><Plus /></el-icon>发布接口
      </el-button>
    </header>

    <transition-group name="list" tag="div" class="api-grid">
      <div v-for="api in apis" :key="api.id" class="pf-card api-card">
        <!-- 锁定角标 -->
        <div v-if="api.is_locked" class="lock-badge">
          <el-icon><Lock /></el-icon> 已锁定
        </div>

        <div class="api-card-header">
          <div>
            <span class="api-name">{{ api.name }}</span>
            <el-tag
              :type="statusType[api.status] || 'info'"
              size="small"
              effect="plain"
              style="margin-left:8px"
            >{{ api.status }}</el-tag>
          </div>
          <el-tag v-if="api.rate_limit_enabled" size="small" type="warning" effect="plain">
            限流 {{ api.rate_limit_per_minute }}/min
          </el-tag>
        </div>

        <p class="api-path">
          <el-icon><Link /></el-icon>
          <code>POST /api/public/{{ api.path }}</code>
        </p>
        <p class="api-desc">{{ api.description || '—' }}</p>

        <!-- 流量统计 -->
        <div class="stats-row">
          <div class="stat-item">
            <span class="stat-label">总调用</span>
            <span class="stat-val">{{ api.total_calls.toLocaleString() }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">成功率</span>
            <span class="stat-val" :class="{ 'text-success': Number(successRate(api)) >= 99 }">
              {{ successRate(api) }}{{ api.total_calls > 0 ? '%' : '' }}
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-label">均延迟</span>
            <span class="stat-val">{{ api.avg_latency_ms.toFixed(0) }}ms</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">降级</span>
            <span class="stat-val">{{ api.degradation_enabled ? '开' : '关' }}</span>
          </div>
        </div>

        <div class="api-actions">
          <el-button size="small" @click="viewDocs(api)">
            <el-icon><Document /></el-icon> 文档
          </el-button>
          <el-button
            size="small"
            :type="api.status === 'active' ? 'warning' : 'success'"
            :disabled="api.is_locked"
            @click="toggleStatus(api)"
          >
            {{ api.status === 'active' ? '暂停' : '激活' }}
          </el-button>
          <el-button size="small" type="info" @click="copyFlow(api)">
            <el-icon><CopyDocument /></el-icon> 复制流程
          </el-button>
          <el-button
            size="small"
            type="danger"
            :disabled="api.is_locked"
            @click="unpublish(api)"
          >
            下线
          </el-button>
        </div>
      </div>
    </transition-group>

    <el-empty v-if="!loading && apis.length === 0" description="暂无已发布接口，点击「发布接口」开始" />

    <!-- 发布接口 Dialog -->
    <el-dialog v-model="publishDialogVisible" title="发布流程为接口" width="520px" :close-on-click-modal="false">
      <el-form label-width="90px" class="publish-form">
        <el-form-item label="接口名称" required>
          <el-input v-model="form.name" placeholder="如：图像识别服务" />
        </el-form-item>
        <el-form-item label="接口路径" required>
          <el-input v-model="form.path" placeholder="如：image-classify（仅字母数字_-）">
            <template #prepend>/api/public/</template>
          </el-input>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tags" placeholder="如：AI,图像（逗号分隔）" />
        </el-form-item>
        <el-form-item label="关联流程" required>
          <el-select v-model="form.flow_id" style="width:100%" placeholder="选择要发布的流程">
            <el-option v-for="f in flows" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="publishDialogVisible = false; resetForm()">取消</el-button>
        <el-button type="primary" @click="publish">发布</el-button>
      </template>
    </el-dialog>

    <!-- 接口文档 Dialog -->
    <el-dialog v-model="docsDialogVisible" title="接口文档" width="680px" top="5vh">
      <div v-loading="docsLoading">
        <template v-if="docsData">
          <div class="docs-section">
            <h3 class="docs-title">{{ docsData.name }}</h3>
            <p class="docs-desc">{{ docsData.description || '暂无描述' }}</p>
            <div class="docs-meta-row">
              <el-tag type="success">{{ docsData.method }}</el-tag>
              <code class="docs-path">{{ docsData.path }}</code>
              <el-tag :type="statusType[docsData.status] || 'info'">{{ docsData.status }}</el-tag>
            </div>
          </div>

          <el-divider />

          <div class="docs-section">
            <h4>流程信息</h4>
            <p>流程名称：<strong>{{ docsData.flow_name }}</strong>（{{ docsData.node_count }} 块 / {{ docsData.edge_count }} 条边）</p>
          </div>

          <div class="docs-section" v-if="docsData.blocks?.length">
            <h4>调用块列表</h4>
            <el-collapse accordion>
              <el-collapse-item
                v-for="block in docsData.blocks"
                :key="block.block_id"
                :title="block.block_name"
              >
                <p class="dim" style="margin:0 0 8px">{{ block.description || '暂无描述' }}</p>
                <div class="port-grid">
                  <div>
                    <strong>输入端口</strong>
                    <ul class="port-list">
                      <li v-for="p in block.input_ports" :key="p.name">
                        <code>{{ p.name }}</code>
                        <span class="dim">{{ p.type }}</span>
                        <el-tag v-if="p.required" size="small" type="danger">必填</el-tag>
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
          </div>

          <el-divider />

          <div class="docs-section">
            <h4>示例请求</h4>
            <pre class="code-block">{{ JSON.stringify(docsData.request_example, null, 2) }}</pre>
            <h4>示例响应</h4>
            <pre class="code-block">{{ JSON.stringify(docsData.response_example, null, 2) }}</pre>
          </div>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
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
.api-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
.api-card {
  padding: 20px;
  position: relative;
  overflow: hidden;
  cursor: default;
  transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
}
.api-card:hover {
  transform: translateY(-3px);
  border-color: var(--pf-accent);
  box-shadow: var(--pf-shadow-md);
}
.lock-badge {
  position: absolute;
  top: 0;
  right: 0;
  background: #facc15;
  color: #78350f;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 0 12px 0 10px;
  display: flex;
  align-items: center;
  gap: 4px;
  animation: badge-in 0.3s ease;
}
@keyframes badge-in {
  from { opacity: 0; transform: translateX(20px); }
  to   { opacity: 1; transform: translateX(0); }
}
.api-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.api-name {
  font-size: 15px;
  font-weight: 600;
}
.api-path {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--pf-accent);
  margin: 0 0 6px;
}
.api-path code {
  background: var(--pf-accent-soft);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.api-desc {
  font-size: 13px;
  color: var(--pf-text-dim);
  margin: 0 0 14px;
  min-height: 18px;
}
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  background: var(--pf-panel-2);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 14px;
}
.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.stat-label {
  font-size: 11px;
  color: var(--pf-text-dim);
}
.stat-val {
  font-size: 15px;
  font-weight: 600;
  color: var(--pf-text);
}
.text-success {
  color: #22c55e;
}
.api-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.publish-form .el-form-item {
  margin-bottom: 18px;
}
.docs-section {
  margin-bottom: 16px;
}
.docs-title {
  margin: 0 0 4px;
  font-size: 17px;
}
.docs-desc {
  color: var(--pf-text-dim);
  margin: 0 0 10px;
}
.docs-meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.docs-path {
  background: var(--pf-panel-2);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 13px;
}
.port-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
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
  font-size: 13px;
}
.code-block {
  background: var(--pf-code-bg);
  color: var(--pf-code-text);
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 12px;
  overflow-x: auto;
  margin: 8px 0 16px;
}
</style>
