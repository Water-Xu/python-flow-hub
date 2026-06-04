<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const collapsed = ref(false)

const isLoginPage = computed(() => route.path === '/login')

const menus = computed(() => {
  const base = [
    { path: '/blocks', label: '调用块', icon: 'Grid' },
    { path: '/flows', label: '流程编排', icon: 'Share' },
    { path: '/mq-monitor', label: 'MQ 监控', icon: 'MessageBox' },
    { path: '/api-portal', label: '接口门户', icon: 'Connection' },
    { path: '/api-admin', label: '接口管理', icon: 'Management' },
    { path: '/deployments', label: '部署中心', icon: 'Promotion' },
    { path: '/executions', label: '执行历史', icon: 'Histogram' },
  ]
  // ADMIN 才显示角色管理
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

const roleBadgeType = computed(() => {
  const role = authStore.user?.pyflowRole || ''
  if (role === 'admin') return 'danger'
  if (role === 'deployer') return 'warning'
  if (role === 'editor') return 'primary'
  return 'info'
})

async function handleLogout() {
  await ElMessageBox.confirm('确认退出登录？', '退出', { type: 'warning' })
  authStore.logout()
  router.push('/login')
  ElMessage.success('已退出登录')
}

// 应用启动时拉取当前用户信息
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
  <!-- 登录页不显示侧边栏 -->
  <div v-if="isLoginPage" class="login-wrap">
    <router-view />
  </div>

  <!-- 主布局 -->
  <div v-else class="layout">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand">
        <span class="logo">⚡</span>
        <transition name="fade">
          <span v-if="!collapsed" class="brand-name">PyFlowHub</span>
        </transition>
      </div>

      <nav class="nav">
        <router-link
          v-for="m in menus"
          :key="m.path"
          :to="m.path"
          class="nav-item"
          :class="{ active: route.path.startsWith(m.path) }"
        >
          <el-icon><component :is="m.icon" /></el-icon>
          <transition name="fade">
            <span v-if="!collapsed" class="nav-label">{{ m.label }}</span>
          </transition>
        </router-link>
      </nav>

      <!-- 用户信息 + 登出 -->
      <div class="user-section" v-if="authStore.isLoggedIn">
        <transition name="fade">
          <div v-if="!collapsed" class="user-info">
            <div class="user-avatar">{{ userInitial }}</div>
            <div class="user-detail">
              <span class="user-name">{{ authStore.user?.username || authStore.user?.loginId || 'dev' }}</span>
              <el-tag :type="roleBadgeType" size="small" effect="dark">{{ roleBadge }}</el-tag>
            </div>
          </div>
        </transition>
        <div class="user-avatar-mini" v-if="collapsed" :title="authStore.user?.username">
          {{ userInitial }}
        </div>
        <div class="logout-btn" @click="handleLogout" title="退出登录">
          <el-icon><SwitchButton /></el-icon>
          <transition name="fade">
            <span v-if="!collapsed">退出</span>
          </transition>
        </div>
      </div>

      <div class="collapse-btn" @click="collapsed = !collapsed">
        <el-icon><component :is="collapsed ? 'Expand' : 'Fold'" /></el-icon>
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
  width: 220px;
  background: var(--pf-panel);
  border-right: 1px solid var(--pf-border);
  box-shadow: var(--pf-shadow-sm);
  display: flex;
  flex-direction: column;
  transition: width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}
.sidebar.collapsed { width: 68px; }
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px;
  font-size: 20px;
  font-weight: 700;
}
.logo { font-size: 24px; }
.brand-name { color: var(--pf-text); letter-spacing: 0.2px; }
.nav {
  flex: 1;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  color: var(--pf-text-dim);
  text-decoration: none;
  transition: background 0.2s ease, color 0.2s ease, transform 0.15s ease;
}
.nav-item:hover {
  background: var(--pf-panel-2);
  color: var(--pf-text);
  transform: translateX(3px);
}
.nav-item.active {
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  box-shadow: inset 3px 0 0 var(--pf-accent);
}

/* 用户区 */
.user-section {
  border-top: 1px solid var(--pf-border);
  padding: 10px 10px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 6px;
  border-radius: 10px;
  background: var(--pf-panel-2);
}
.user-avatar {
  width: 34px; height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.user-avatar-mini {
  width: 34px; height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto;
  cursor: default;
}
.user-detail {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--pf-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.logout-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--pf-text-dim);
  cursor: pointer;
  transition: all 0.2s;
}
.logout-btn:hover {
  background: rgba(239,68,68,0.08);
  color: #ef4444;
}

.collapse-btn {
  padding: 14px;
  cursor: pointer;
  color: var(--pf-text-dim);
  border-top: 1px solid var(--pf-border);
  transition: color 0.2s ease;
}
.collapse-btn:hover { color: var(--pf-accent); }
.content {
  flex: 1;
  overflow: auto;
  padding: 24px;
}
</style>
