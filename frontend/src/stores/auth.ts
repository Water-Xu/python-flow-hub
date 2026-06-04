import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface UserInfo {
  loginId: string
  username: string
  pyflowRole: string          // viewer | editor | deployer | admin | ''
  avatar?: string
}

export const useAuthStore = defineStore(
  'pyflow-auth',
  () => {
    const token = ref<string>('')
    const user = ref<UserInfo | null>(null)
    const loading = ref(false)

    const isLoggedIn = computed(() => !!token.value)
    const isAdmin = computed(() => user.value?.pyflowRole === 'admin')
    const isEditor = computed(() =>
      ['editor', 'deployer', 'admin'].includes(user.value?.pyflowRole || '')
    )

    function setToken(t: string) {
      token.value = t
      localStorage.setItem('pyflow_token', t)
    }

    function setUser(u: UserInfo) {
      user.value = u
      localStorage.setItem('pyflow_user', JSON.stringify(u))
    }

    function logout() {
      token.value = ''
      user.value = null
      localStorage.removeItem('pyflow_token')
      localStorage.removeItem('pyflow_user')
    }

    // Store 初始化时从 localStorage 恢复（替代 pinia-persist）
    const savedToken = localStorage.getItem('pyflow_token')
    if (savedToken) token.value = savedToken
    try {
      const savedUser = localStorage.getItem('pyflow_user')
      if (savedUser) user.value = JSON.parse(savedUser)
    } catch {}

    return { token, user, loading, isLoggedIn, isAdmin, isEditor, setToken, setUser, logout }
  },
)
