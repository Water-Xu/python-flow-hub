<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { platformApi } from '@/api'

const envList = ref<any[]>([])
const middleware = ref<any>(null)
const loading = ref(false)

const dialogVisible = ref(false)
const form = ref({ env_key: '', env_value: '', description: '' })
const saving = ref(false)

async function load() {
  loading.value = true
  try {
    const [envs, mw] = await Promise.all([platformApi.listEnv(), platformApi.middleware()])
    envList.value = envs
    middleware.value = mw
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { env_key: '', env_value: '', description: '' }
  dialogVisible.value = true
}

function openEdit(row: any) {
  form.value = { env_key: row.env_key, env_value: row.env_value, description: row.description }
  dialogVisible.value = true
}

async function save() {
  if (!form.value.env_key.trim()) return ElMessage.warning('请填写变量名')
  saving.value = true
  try {
    await platformApi.upsertEnv(form.value)
    ElMessage.success('已保存（下次部署生效）')
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`删除全局变量 ${row.env_key}？`, '确认', { type: 'warning' })
  await platformApi.deleteEnv(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>平台设置</h2>
        <p class="dim">全局环境变量（注入所有 K8s 部署的调用块） · 中间件接入（块连接 redis/mq/db/minio）</p>
      </div>
      <el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </header>

    <!-- 中间件接入 -->
    <div class="pf-card mw-card" v-if="middleware">
      <div class="card-title">
        <el-icon><Link /></el-icon> 中间件接入
        <el-tag :type="middleware.inject_enabled ? 'success' : 'info'" size="small" effect="dark" style="margin-left:8px">
          {{ middleware.inject_enabled ? '已启用注入' : '未启用' }}
        </el-tag>
      </div>
      <p class="dim mw-tip">
        部署时自动渲染共享 Secret <code>{{ middleware.secret_name }}</code> 注入每个块（envFrom），
        并按白名单放行 NetworkPolicy egress。块内 Python 代码按约定环境变量读取连接（如
        <code>os.environ["DATABASE_URL"]</code>）。
      </p>

      <div class="mw-grid">
        <div class="mw-section">
          <div class="mw-sub">连接环境变量（脱敏）</div>
          <div v-for="c in middleware.connections" :key="c.env" class="mw-row">
            <code class="mw-env">{{ c.env }}</code>
            <span class="mw-val">{{ c.value }}</span>
          </div>
        </div>
        <div class="mw-section">
          <div class="mw-sub">egress 白名单</div>
          <div class="mw-tags">
            <el-tag size="small" effect="plain" type="success">
              ns: {{ middleware.middleware_namespace }} · {{ (middleware.ns_ports || []).join('/') }}
            </el-tag>
            <el-tag v-for="c in middleware.egress_cidrs" :key="c" size="small" effect="plain">{{ c }}</el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 全局环境变量 -->
    <div class="pf-card env-card">
      <div class="card-title">
        <el-icon><Setting /></el-icon> 全局环境变量
        <span class="dim title-sub">优先级：全局 &lt; 部署 &lt; 块（更具体者覆盖）· 仅存非敏感配置，密码走 Secret</span>
        <el-button type="primary" size="small" style="margin-left:auto" @click="openCreate">
          <el-icon><Plus /></el-icon> 新增
        </el-button>
      </div>
      <el-table v-loading="loading" :data="envList" size="small" class="pf-table">
        <el-table-column prop="env_key" label="变量名" min-width="160">
          <template #default="{ row }"><code class="mw-env">{{ row.env_key }}</code></template>
        </el-table-column>
        <el-table-column prop="env_value" label="值" min-width="200" show-overflow-tooltip />
        <el-table-column prop="description" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !envList.length" description="暂无全局环境变量" :image-size="60" />
    </div>

    <el-dialog v-model="dialogVisible" title="全局环境变量" width="460px">
      <el-form label-width="80px">
        <el-form-item label="变量名">
          <el-input v-model="form.env_key" placeholder="BUSINESS_API_BASE" />
        </el-form-item>
        <el-form-item label="值">
          <el-input v-model="form.env_value" type="textarea" :rows="2" placeholder="http://lhy-styon-gateway.lhy-styon.svc.cluster.local:8201" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-head h2 { margin: 0; font-size: 22px; }
.dim { color: var(--pf-text-dim); font-size: 13px; margin: 4px 0 0; }
.card-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; margin-bottom: 14px; }
.title-sub { font-weight: 400; font-size: 12px; }
.mw-card { padding: 18px 22px; margin-bottom: 16px; animation: slide-up 0.35s ease both; }
.mw-tip { margin: 0 0 14px; line-height: 1.7; }
.mw-tip code { color: var(--pf-accent); background: var(--pf-accent-soft); padding: 1px 5px; border-radius: 3px; }
.mw-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 22px; }
@media (max-width: 900px) { .mw-grid { grid-template-columns: 1fr; } }
.mw-sub { font-size: 12px; font-weight: 600; color: var(--pf-text-dim); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.04em; }
.mw-row { display: flex; align-items: center; gap: 10px; padding: 5px 0; border-bottom: 1px dashed var(--pf-border); }
.mw-env { color: var(--pf-accent); font-size: 12px; min-width: 130px; }
.mw-val { font-family: monospace; font-size: 12px; color: var(--pf-text); word-break: break-all; }
.mw-tags { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.env-card { padding: 18px 22px; animation: slide-up 0.45s ease both; }
.pf-table { background: transparent; }
@keyframes slide-up { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
</style>
