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

/**
 * 错误码 → 友好提示（对齐平台错误码号段：1xxxx 认证 / 4xxxx 请求 / 5xxxx 系统）。
 * 5xxxx 系统异常统一友好兜底（不暴露内部细节，安全规范）；其余按业务码原样提示。
 */
const ERROR_CODE_MESSAGES: Record<number, string> = {
  11801: '登录已失效，请重新登录',
  11802: '无操作权限（角色不足）',
  41801: '调用块不存在',
  41802: '流程不存在',
  41803: '版本未稳定或校验不一致',
  41804: '输入参数非法',
  41805: '流程存在环或拓扑非法',
  41806: '资源级权限不足（非属主/未授权）',
  41810: '接口不存在',
  41811: '接口已锁定，禁止修改',
  41812: '请求过于频繁，请稍后再试',
  41813: '接口路径已存在',
  51801: '执行超时，请稍后重试',
  51802: '沙箱执行失败',
  51803: 'K8s 部署失败',
  51804: '消息发布失败',
}

function friendlyMessage(data: any, fallback: string): string {
  const code: number | undefined = data?.code
  if (code && ERROR_CODE_MESSAGES[code]) {
    return ERROR_CODE_MESSAGES[code]
  }
  // 5xxxx 系统异常统一友好提示，不外泄内部 detail
  if (code && Math.floor(code / 10000) === 5) {
    return '系统繁忙，请稍后重试'
  }
  return data?.detail || data?.message || data?.msgKey || fallback
}

client.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const status = error.response?.status
    const data = error.response?.data
    const code: number | undefined = data?.code

    if (status === 401 || code === 11801) {
      // token 失效，跳转登录
      localStorage.removeItem('pyflow_token')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      ElMessage.error(ERROR_CODE_MESSAGES[11801])
      return Promise.reject(error)
    }

    ElMessage.error(friendlyMessage(data, error.message || '请求失败'))
    return Promise.reject(error)
  },
)

export default client
