<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// ── 彩蛋：连点 5 次 ⚡ ────────────────────────────────────────────────────────
const eggVisible = ref(false)
const eggClickCount = ref(0)
const logoShake = ref(false)
let eggResetTimer: ReturnType<typeof setTimeout> | undefined

function handleLogoClick() {
  eggClickCount.value++
  // 每次点击抖动一下
  logoShake.value = false
  requestAnimationFrame(() => { logoShake.value = true })
  setTimeout(() => { logoShake.value = false }, 500)

  if (eggClickCount.value >= 5) {
    eggVisible.value = true
    eggClickCount.value = 0
    clearTimeout(eggResetTimer)
    return
  }
  // 2s 内没继续点则重置计数
  clearTimeout(eggResetTimer)
  eggResetTimer = setTimeout(() => { eggClickCount.value = 0 }, 2000)
}

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
        <div class="brand" @click="handleLogoClick">
          <span class="logo" :class="{ 'logo-shake': logoShake }">⚡</span>
          <!-- 点击进度气泡 -->
          <transition name="bubble">
            <span v-if="eggClickCount > 0" class="click-bubble">{{ eggClickCount }}</span>
          </transition>
        </div>
      </el-tooltip>

      <!-- 彩蛋弹窗 -->
      <Teleport to="body">
        <Transition name="egg-modal">
          <div v-if="eggVisible" class="egg-overlay" @click.self="eggVisible = false">
            <div class="egg-box">
              <button class="egg-close" @click="eggVisible = false">✕</button>
              <div class="egg-sparkles">
                <span v-for="i in 8" :key="i" class="sparkle" :style="{ '--i': i }" />
              </div>
              <img src="/easter-egg.png" class="egg-img" alt="彩蛋" />
              <div class="egg-sig">
                <span class="sig-label">Crafted with ❤️ by</span>
                <span class="sig-name">Water_Xu</span>
              </div>
              <div class="egg-tip">你发现了隐藏彩蛋 🎉</div>
            </div>
          </div>
        </Transition>
      </Teleport>

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
  cursor: pointer;
  position: relative;
  transition: transform 0.25s ease, background 0.2s ease;
  user-select: none;
}
.brand:hover {
  background: var(--pf-panel-2);
  transform: scale(1.05);
}
.logo {
  font-size: 22px;
  line-height: 1;
  display: inline-block;
}

/* 点击抖动 */
@keyframes logo-shake {
  0%   { transform: rotate(0deg) scale(1.1); }
  20%  { transform: rotate(-12deg) scale(1.2); }
  40%  { transform: rotate(12deg) scale(1.2); }
  60%  { transform: rotate(-8deg) scale(1.15); }
  80%  { transform: rotate(6deg) scale(1.1); }
  100% { transform: rotate(0deg) scale(1); }
}
.logo-shake { animation: logo-shake 0.45s cubic-bezier(0.36,0.07,0.19,0.97) both; }

/* 点击计数气泡 */
.click-bubble {
  position: absolute;
  top: -6px; right: -6px;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: #ef4444;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  line-height: 1;
  pointer-events: none;
}
.bubble-enter-active { animation: bubble-pop 0.25s cubic-bezier(0.34,1.56,0.64,1) both; }
.bubble-leave-active { animation: bubble-pop 0.15s ease reverse both; }
@keyframes bubble-pop {
  from { transform: scale(0); opacity: 0; }
  to   { transform: scale(1); opacity: 1; }
}

/* ── 彩蛋弹窗 ── */
.egg-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.65);
  backdrop-filter: blur(6px);
  display: flex; align-items: center; justify-content: center;
}
.egg-box {
  position: relative;
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%);
  border: 1px solid rgba(167,139,250,0.35);
  border-radius: 24px;
  padding: 40px 48px 32px;
  display: flex; flex-direction: column; align-items: center; gap: 18px;
  box-shadow: 0 0 60px rgba(124,58,237,0.4), 0 0 120px rgba(79,70,229,0.2);
  min-width: 320px;
  animation: egg-appear 0.6s cubic-bezier(0.34,1.56,0.64,1) both;
}
@keyframes egg-appear {
  from { transform: scale(0.4) rotate(-8deg); opacity: 0; }
  to   { transform: scale(1) rotate(0deg); opacity: 1; }
}

/* 关闭按钮 */
.egg-close {
  position: absolute; top: 14px; right: 16px;
  background: rgba(255,255,255,0.08); border: none; border-radius: 8px;
  color: rgba(255,255,255,0.5); font-size: 14px;
  width: 28px; height: 28px; cursor: pointer;
  transition: background 0.2s, color 0.2s, transform 0.15s;
  display: flex; align-items: center; justify-content: center;
}
.egg-close:hover { background: rgba(239,68,68,0.2); color: #f87171; transform: scale(1.1); }

/* 星光粒子 */
.egg-sparkles { position: absolute; inset: 0; pointer-events: none; overflow: hidden; border-radius: 24px; }
.sparkle {
  position: absolute;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: radial-gradient(circle, #fff 0%, #a78bfa 60%, transparent 100%);
  animation: sparkle-float calc(2s + var(--i) * 0.3s) ease-in-out infinite alternate;
  top: calc(10% + var(--i) * 11%);
  left: calc(5% + var(--i) * 12%);
  opacity: 0.7;
}
@keyframes sparkle-float {
  from { transform: translateY(0) scale(1); opacity: 0.4; }
  to   { transform: translateY(-12px) scale(1.4); opacity: 1; }
}

/* 图片 */
.egg-img {
  width: 180px; height: 180px;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid rgba(167,139,250,0.5);
  box-shadow: 0 0 0 6px rgba(124,58,237,0.15), 0 8px 32px rgba(0,0,0,0.4);
  animation: img-bounce 3s ease-in-out infinite;
}
@keyframes img-bounce {
  0%, 100% { transform: translateY(0); }
  50%       { transform: translateY(-8px); }
}

/* 签名 */
.egg-sig {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.sig-label { font-size: 12px; color: rgba(196,181,253,0.7); letter-spacing: 0.5px; }
.sig-name {
  font-size: 22px; font-weight: 800;
  background: linear-gradient(90deg, #a78bfa, #60a5fa, #f472b6, #a78bfa);
  background-size: 300% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: name-shimmer 3s linear infinite;
  letter-spacing: 1px;
}
@keyframes name-shimmer {
  0%   { background-position: 0% 50%; }
  100% { background-position: 300% 50%; }
}

/* 底部提示 */
.egg-tip {
  font-size: 12px; color: rgba(196,181,253,0.5);
  letter-spacing: 0.5px;
  animation: tip-pulse 2s ease-in-out infinite;
}
@keyframes tip-pulse {
  0%, 100% { opacity: 0.5; }
  50%       { opacity: 1; }
}

/* 弹窗过渡 */
.egg-modal-enter-active { animation: egg-overlay-in 0.3s ease both; }
.egg-modal-leave-active { animation: egg-overlay-in 0.2s ease reverse both; }
@keyframes egg-overlay-in {
  from { opacity: 0; }
  to   { opacity: 1; }
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
