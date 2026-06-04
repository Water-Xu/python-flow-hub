<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { rbacApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const users = ref<any[]>([])
const loading = ref(false)

// 授权新用户
const grantDialogVisible = ref(false)
const grantForm = ref({ login_id: '', role: 'viewer' })
const granting = ref(false)

const roles = ['viewer', 'editor', 'deployer', 'admin']
const roleLabels: Record<string, string> = {
  viewer: '观察者', editor: '编辑者', deployer: '部署者', admin: '管理员',
}
const roleTagTypes: Record<string, string> = {
  viewer: 'info', editor: 'primary', deployer: 'warning', admin: 'danger',
}

async function load() {
  loading.value = true
  try {
    users.value = await rbacApi.listUsers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function grantRole() {
  if (!grantForm.value.login_id.trim()) return ElMessage.warning('请输入用户 ID')
  granting.value = true
  try {
    await rbacApi.grant(grantForm.value.login_id.trim(), grantForm.value.role)
    ElMessage.success(`已授予 ${grantForm.value.login_id} [${roleLabels[grantForm.value.role]}] 角色`)
    grantDialogVisible.value = false
    grantForm.value = { login_id: '', role: 'viewer' }
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '授权失败')
  } finally {
    granting.value = false
  }
}

async function revokeRole(loginId: string, role: string) {
  await ElMessageBox.confirm(`确认撤销 ${loginId} 的 [${roleLabels[role]}] 角色？`, '撤销确认', { type: 'warning' })
  try {
    await rbacApi.revoke(loginId, role)
    ElMessage.success('已撤销')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '撤销失败')
  }
}

const myLoginId = computed(() => authStore.user?.loginId || '')

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2>角色权限管理</h2>
        <p class="dim">仅 ADMIN 可操作 · 基于 PyFlowHub 平台级 RBAC（决策 2）</p>
      </div>
      <div class="head-actions">
        <el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
        <el-button type="primary" @click="grantDialogVisible = true">
          <el-icon><Plus /></el-icon> 授予角色
        </el-button>
      </div>
    </header>

    <!-- 角色说明 -->
    <div class="role-legend pf-card">
      <span class="legend-title">角色权限速查：</span>
      <span v-for="r in roles" :key="r" class="legend-item">
        <el-tag :type="roleTagTypes[r]" size="small">{{ r }}</el-tag>
        <span class="dim">{{ { viewer: '查看', editor: '编辑/运行', deployer: '部署', admin: '全权限+授权' }[r] }}</span>
      </span>
    </div>

    <!-- 用户角色列表 -->
    <el-table :data="users" v-loading="loading" class="pf-card" style="margin-top:16px">
      <el-table-column label="用户 ID" prop="login_id" min-width="160" />
      <el-table-column label="角色" min-width="120">
        <template #default="{ row }">
          <el-tag :type="roleTagTypes[row.role]" effect="dark">
            {{ roleLabels[row.role] || row.role }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="授权人" prop="granted_by" min-width="140" />
      <el-table-column label="授权时间" prop="granted_at" min-width="160">
        <template #default="{ row }">
          {{ row.granted_at ? new Date(row.granted_at).toLocaleString('zh-CN') : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button
            type="danger"
            size="small"
            text
            :disabled="row.login_id === myLoginId && row.role === 'admin'"
            @click="revokeRole(row.login_id, row.role)"
          >
            撤销
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && users.length === 0" description="暂无用户角色记录，点击「授予角色」为首个用户分配权限" />

    <!-- 授权 Dialog -->
    <el-dialog v-model="grantDialogVisible" title="授予角色" width="440px">
      <el-form :model="grantForm" label-width="90px">
        <el-form-item label="用户 ID">
          <el-input v-model="grantForm.login_id" placeholder="平台统一用户 ID（Sa-Token loginId）" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="grantForm.role" style="width:100%">
            <el-option v-for="r in roles" :key="r" :label="`${r} — ${roleLabels[r]}`" :value="r" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="grantDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="granting" @click="grantRole">确认授予</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px;
}
.page-head h2 { margin: 0; font-size: 22px; }
.dim { color: var(--pf-text-dim); font-size: 13px; margin: 4px 0 0; }
.head-actions { display: flex; gap: 8px; }
.role-legend {
  display: flex; align-items: center; gap: 16px; padding: 12px 18px; flex-wrap: wrap;
}
.legend-title { font-size: 13px; color: var(--pf-text-dim); }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.pf-card { border-radius: 12px; }
</style>
