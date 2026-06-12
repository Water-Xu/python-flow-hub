<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isLoginPage = computed(() => route.path === '/login')

const menus = computed(() => {
  const base = [
    { path: '/dashboard', label: '链路看板', icon: 'Odometer' },
    { path: '/blocks', label: '调用块', icon: 'Grid' },
    { path: '/flows', label: '流程编排', icon: 'Share' },
    { path: '/mq-monitor', label: 'MQ 监控', icon: 'MessageBox' },
    { path: '/api-portal', label: '接口门户', icon: 'Connection' },
    { path: '/api-admin', label: '接口管理', icon: 'Management' },
    { path: '/deployments', label: '部署中心', icon: 'Promotion' },
    { path: '/executions', label: '执行历史', icon: 'Histogram' },
    { path: '/platform-settings', label: '平台设置', icon: 'Setting' },
  ]
  if (authStore.isAdmin) {
    base.push({ path: '/rbac-admin', label: '角色管理', icon: 'UserFilled' })
  }
  return base
})

const userInitial = computed(() => {
  const name = authStore.user?.username || authStore.user?.loginId || ''
  return name.slice(0, 1).toUpperCase() || '?'
})

const roleBadge = computed(() => {
  const role = authStore.user?.pyflowRole || ''
  const map: Record<string, string> = {
    admin: 'ADMIN', deployer: 'DEPLOYER', editor: 'EDITOR', viewer: 'VIEWER'
  }
  return map[role] || (role ? role.toUpperCase() : 'DEV')
})

const userTooltip = computed(() => {
  const name = authStore.user?.username || authStore.user?.loginId || 'dev'
  return `${name} · ${roleBadge.value}`
})

async function handleLogout() {
  await ElMessageBox.confirm('确认退出登录？', '退出', { type: 'warning' })
  authStore.logout()
  router.push('/login')
  ElMessage.success('已退出登录')
}

onMounted(async () => {
  if (authStore.isLoggedIn && !authStore.user) {
    try {
      const me = await authApi.me()
      authStore.setUser({
        loginId: me.login_id,
        username: me.username || me.login_id,
        pyflowRole: me.role || '',
      })
    } catch {}
  }
})
</script>

<template>
  <div v-if="isLoginPage" class="login-wrap">
    <router-view />
  </div>

  <div v-else class="layout">
    <aside class="sidebar">
      <el-tooltip content="PyFlowHub" placement="right" effect="light" :show-after="300">
        <div class="brand">
          <span class="logo">⚡</span>
        </div>
      </el-tooltip>

      <nav class="nav">
        <el-tooltip
          v-for="m in menus"
          :key="m.path"
          :content="m.label"
          placement="right"
          effect="light"
          :show-after="200"
        >
          <router-link
            :to="m.path"
            class="nav-item"
            :class="{ active: route.path.startsWith(m.path) }"
          >
            <el-icon :size="20"><component :is="m.icon" /></el-icon>
          </router-link>
        </el-tooltip>
      </nav>

      <div v-if="authStore.isLoggedIn" class="user-section">
        <el-tooltip :content="userTooltip" placement="right" effect="light" :show-after="200">
          <div class="user-avatar">{{ userInitial }}</div>
        </el-tooltip>
        <el-tooltip content="退出登录" placement="right" effect="light" :show-after="200">
          <button type="button" class="logout-btn" @click="handleLogout">
            <el-icon :size="18"><SwitchButton /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </aside>

    <main class="content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.login-wrap { height: 100vh; }

.layout {
  display: flex;
  height: 100%;
}

.sidebar {
  width: 64px;
  flex-shrink: 0;
  background: var(--pf-panel);
  border-right: 1px solid var(--pf-border);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 0 24px;
  gap: 8px;
}

.brand {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  cursor: default;
  transition: transform 0.25s ease, background 0.2s ease;
}
.brand:hover {
  background: var(--pf-panel-2);
  transform: scale(1.05);
}
.logo {
  font-size: 22px;
  line-height: 1;
}

.nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 12px 0;
  min-height: 0;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  color: var(--pf-text-dim);
  text-decoration: none;
  transition: background 0.22s ease, color 0.22s ease, transform 0.18s ease, box-shadow 0.22s ease;
}
.nav-item:hover {
  background: var(--pf-panel-2);
  color: var(--pf-text);
  transform: scale(1.06);
}
.nav-item.active {
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.15);
}

.user-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--pf-border);
  width: calc(100% - 16px);
  margin: 0 8px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: default;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.user-avatar:hover {
  transform: scale(1.06);
  box-shadow: 0 4px 12px rgba(124, 58, 237, 0.25);
}

.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--pf-text-dim);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, transform 0.18s ease;
}
.logout-btn:hover {
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
  transform: scale(1.06);
}

.content {
  flex: 1;
  overflow: auto;
  padding: 32px 40px;
  background: var(--pf-bg);
}
</style>
