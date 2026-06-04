import axios from 'axios'
import { ElMessage } from 'element-plus'

const baseURL = import.meta.env.VITE_BASE_SERVER_URL || ''

const client = axios.create({
  baseURL,
  timeout: 30000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('pyflow_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const status = error.response?.status
    if (status === 401 || status === 11801) {
      // token 失效，跳转登录
      localStorage.removeItem('pyflow_token')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
    const data = error.response?.data
    const msg = data?.detail || data?.message || data?.msgKey || error.message
    ElMessage.error(`请求失败：${msg}`)
    return Promise.reject(error)
  },
)

export default client
