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
    }

    function logout() {
      token.value = ''
      user.value = null
      localStorage.removeItem('pyflow_token')
    }

    // 恢复 localStorage 中的 token（页面刷新时）
    function restoreToken() {
      const saved = localStorage.getItem('pyflow_token')
      if (saved && !token.value) {
        token.value = saved
      }
    }

    return { token, user, loading, isLoggedIn, isAdmin, isEditor, setToken, setUser, logout, restoreToken }
  },
  {
    persist: {
      key: 'pyflow-auth',
      storage: localStorage,
      pick: ['token', 'user'],
    },
  },
)
