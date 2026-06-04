<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'

const router = useRouter()
const authStore = useAuthStore()

const form = ref({ username: '', password: '' })
const loading = ref(false)
const mounted = ref(false)

onMounted(() => {
  setTimeout(() => (mounted.value = true), 50)
  if (authStore.isLoggedIn) {
    router.replace('/')
  }
})

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    return ElMessage.warning('请输入账号和密码')
  }
  loading.value = true
  try {
    const res = await authApi.login(form.value.username, form.value.password)
    if (res.code !== 200) {
      return ElMessage.error(res.message || '登录失败')
    }
    const tokenStr: string = (res.data?.tokenHead || '') + (res.data?.tokenValue || res.data?.token || '')
    if (!tokenStr) {
      return ElMessage.error('未获取到 Token，请检查账号密码')
    }
    authStore.setToken(tokenStr)

    // 获取 PyFlowHub 中的用户角色
    try {
      const me = await authApi.me()
      authStore.setUser({
        loginId: me.login_id,
        username: me.username || form.value.username,
        pyflowRole: me.role || '',
      })
    } catch {
      authStore.setUser({
        loginId: form.value.username,
        username: form.value.username,
        pyflowRole: '',
      })
    }

    ElMessage.success('登录成功')
    router.replace('/')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '登录失败')
  } finally {
    loading.value = false
  }
}

function handleEnter(e: KeyboardEvent) {
  if (e.key === 'Enter') handleLogin()
}
</script>

<template>
  <div class="login-bg">
    <!-- 背景动态粒子 -->
    <div class="bg-orb orb-1" />
    <div class="bg-orb orb-2" />
    <div class="bg-orb orb-3" />

    <transition name="card-appear">
      <div v-if="mounted" class="login-card">
        <!-- Logo / 标题 -->
        <div class="login-logo">
          <div class="logo-icon">
            <el-icon size="32" color="#fff"><Connection /></el-icon>
          </div>
          <h1 class="logo-title">PyFlowHub</h1>
          <p class="logo-sub">Python 可视化调用中台</p>
        </div>

        <!-- 表单 -->
        <div class="login-form" @keydown="handleEnter">
          <div class="field-wrap">
            <label>账号</label>
            <el-input
              v-model="form.username"
              placeholder="请输入用户名"
              prefix-icon="User"
              size="large"
              autocomplete="username"
              class="pf-input"
            />
          </div>
          <div class="field-wrap">
            <label>密码</label>
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              prefix-icon="Lock"
              size="large"
              show-password
              autocomplete="current-password"
              class="pf-input"
            />
          </div>

          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            {{ loading ? '登录中...' : '登 录' }}
          </el-button>
        </div>

        <!-- 提示 -->
        <p class="dev-hint" v-if="!loading">
          <el-icon><InfoFilled /></el-icon>
          dev 模式可在后端设置 <code>PYFLOW_AUTH_ENABLED=false</code> 跳过登录
        </p>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.login-bg {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
  position: relative;
  overflow: hidden;
}

/* 背景动态光晕 */
.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.35;
  animation: orb-float 8s ease-in-out infinite alternate;
}
.orb-1 {
  width: 400px; height: 400px;
  background: radial-gradient(circle, #7c3aed, transparent);
  top: -100px; left: -100px;
  animation-delay: 0s;
}
.orb-2 {
  width: 350px; height: 350px;
  background: radial-gradient(circle, #0891b2, transparent);
  bottom: -80px; right: -80px;
  animation-delay: 3s;
}
.orb-3 {
  width: 250px; height: 250px;
  background: radial-gradient(circle, #4f46e5, transparent);
  top: 50%; left: 60%;
  animation-delay: 5s;
}
@keyframes orb-float {
  from { transform: translate(0, 0) scale(1); }
  to   { transform: translate(20px, 30px) scale(1.08); }
}

/* 卡片 */
.login-card {
  width: 420px;
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 24px;
  padding: 44px 40px 36px;
  box-shadow: 0 32px 80px rgba(0,0,0,0.4);
  z-index: 10;
}

/* 卡片进入动画 */
.card-appear-enter-active {
  transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.card-appear-enter-from {
  opacity: 0;
  transform: translateY(40px) scale(0.95);
}

/* Logo */
.login-logo {
  text-align: center;
  margin-bottom: 36px;
}
.logo-icon {
  width: 60px; height: 60px;
  border-radius: 16px;
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 14px;
  box-shadow: 0 8px 24px rgba(124,58,237,0.4);
  animation: logo-pulse 3s ease-in-out infinite;
}
@keyframes logo-pulse {
  0%, 100% { box-shadow: 0 8px 24px rgba(124,58,237,0.4); }
  50%       { box-shadow: 0 8px 40px rgba(124,58,237,0.7); }
}
.logo-title {
  font-size: 26px;
  font-weight: 700;
  color: #fff;
  margin: 0 0 4px;
  letter-spacing: 1px;
}
.logo-sub {
  font-size: 13px;
  color: rgba(255,255,255,0.5);
  margin: 0;
}

/* 表单 */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field-wrap label {
  display: block;
  font-size: 13px;
  color: rgba(255,255,255,0.6);
  margin-bottom: 6px;
}
.pf-input :deep(.el-input__wrapper) {
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 10px;
  box-shadow: none;
}
.pf-input :deep(.el-input__wrapper:hover),
.pf-input :deep(.el-input__wrapper.is-focus) {
  border-color: rgba(124,58,237,0.7);
  background: rgba(255,255,255,0.12);
}
.pf-input :deep(.el-input__inner) {
  color: #fff;
  font-size: 14px;
}
.pf-input :deep(.el-input__prefix-inner .el-icon) {
  color: rgba(255,255,255,0.4);
}

.login-btn {
  width: 100%;
  height: 46px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 2px;
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  border: none;
  margin-top: 8px;
  transition: all 0.25s;
}
.login-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(124,58,237,0.5);
}

.dev-hint {
  margin: 20px 0 0;
  font-size: 12px;
  color: rgba(255,255,255,0.35);
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: center;
  flex-wrap: wrap;
}
.dev-hint code {
  color: rgba(124,240,154,0.7);
  background: rgba(255,255,255,0.06);
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
