import axios from 'axios'
import client from './client'

const baseURL = import.meta.env.VITE_BASE_SERVER_URL || ''

// 不走封装 client（避免 401 循环重定向），用于登录接口
const rawClient = axios.create({ baseURL, timeout: 15000 })

export const authApi = {
  /**
   * 调用现有 Sa-Token admin 登录接口（clientId=admin-app）。
   * 直连：开发态前端直接访问 gateway/admin，因 Vite proxy 会转发到 backend；
   * prod 走 gateway 前缀 /lhy-styon-admin。
   */
  login: (username: string, password: string): Promise<any> => {
    const params = new URLSearchParams({ clientId: 'admin-app', username, password })
    return rawClient
      .post('/auth/login', params, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
      .then((r) => r.data)
      .catch(() => {
        // auth_enabled=false 时后端 dev-bypass：直接获取 dev token
        return client.post('/api/auth/dev-login', { username }).then((r: any) => r)
      })
  },
  /** 获取当前用户在 PyFlowHub 中的信息和角色 */
  me: (): Promise<any> => client.get('/api/auth/me'),
}

export const rbacApi = {
  listUsers: () => client.get<any, any[]>('/api/rbac/users'),
  listRoles: (loginId: string) => client.get<any, any[]>(`/api/rbac/roles/${loginId}`),
  grant: (loginId: string, role: string) => client.post('/api/rbac/grant', { login_id: loginId, role }),
  revoke: (loginId: string, role: string) => client.post('/api/rbac/revoke', { login_id: loginId, role }),
  listResourceGrants: (resourceType: string, resourceId: string) =>
    client.get<any, any[]>(`/api/rbac/resource/${resourceType}/${resourceId}/grants`),
  grantResource: (data: object) => client.post('/api/rbac/resource/grant', data),
  revokeResource: (data: object) => client.post('/api/rbac/resource/revoke', data),
}

/** 防御：列表接口必须返回数组；任何异常响应（如 SPA 回退的 HTML 字符串）都归一化为空数组。 */
function ensureArray<T>(value: any): T[] {
  return Array.isArray(value) ? value : []
}

export interface Block {
  id: string
  name: string
  description: string
  type: string
  draft_code: string
  execution_mode: string
  input_ports: any[]
  output_ports: any[]
  compute_config: Record<string, any>
  mq_config: Record<string, any>
}

export const blockApi = {
  list: () => client.get<any, Block[]>('/api/blocks').then(ensureArray<Block>),
  get: (id: string) => client.get<any, Block>(`/api/blocks/${id}`),
  create: (data: Partial<Block>) => client.post<any, Block>('/api/blocks', data),
  update: (id: string, data: Partial<Block>) => client.put<any, Block>(`/api/blocks/${id}`, data),
  remove: (id: string) => client.delete(`/api/blocks/${id}`),
  run: (id: string, inputs: Record<string, any>) =>
    client.post(`/api/blocks/${id}/run`, { inputs }),
}

export const flowApi = {
  list: () => client.get<any, any[]>('/api/flows').then(ensureArray<any>),
  get: (id: string) => client.get<any, any>(`/api/flows/${id}`),
  create: (data: { name: string; description?: string }) => client.post('/api/flows', data),
  saveGraph: (id: string, nodes: any[], edges: any[]) =>
    client.put(`/api/flows/${id}/graph`, { nodes, edges }),
  run: (id: string, inputs: Record<string, any>) => client.post(`/api/flows/${id}/run`, { inputs }),
  importZip: (file: File, name?: string) => {
    const data = new FormData()
    data.append('file', file)
    if (name) data.append('name', name)
    return client.post<any, any>('/api/flows/import-zip', data, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}

export const execApi = {
  records: (blockId?: string) =>
    client
      .get<any, any[]>('/api/exec/records', { params: { block_id: blockId } })
      .then(ensureArray<any>),
  record: (id: string) => client.get(`/api/exec/records/${id}`),
  flowRuns: (flowId?: string) =>
    client
      .get<any, any[]>('/api/exec/flow-runs', { params: { flow_id: flowId } })
      .then(ensureArray<any>),
}

export const deploymentApi = {
  list: () => client.get<any, any[]>('/api/deployments').then(ensureArray<any>),
  get: (id: string) => client.get<any, any>(`/api/deployments/${id}`),
  create: (data: { flow_id: string; name: string; environment: string }) =>
    client.post('/api/deployments', data),
  /** 一键部署到 K8s（构建镜像 + apply Deployment/Service/KEDA/NetworkPolicy，DEPLOYER） */
  deploy: (id: string) => client.post<any, any>(`/api/deployments/${id}/deploy`),
  /** 销毁部署（删除全部 K8s 资源，ADMIN） */
  destroy: (id: string) => client.delete<any, any>(`/api/deployments/${id}`),
  /** 实时 K8s 状态（Pod 副本 / Ready） */
  status: (id: string) => client.get<any, any>(`/api/deployments/${id}/status`),
  /** 容量预检（部署前评估节点池余量） */
  precheck: (id: string) => client.get<any, any>(`/api/deployments/${id}/precheck`),
  /** 渲染 K8s manifest 预览（不 apply） */
  manifests: (id: string) => client.get<any, any>(`/api/deployments/${id}/manifests`),
  /** 配置部署级环境变量（注入该部署全部块，下次部署生效，DEPLOYER） */
  updateEnv: (id: string, data: { env_vars: Record<string, string>; secret_refs?: Record<string, string> }) =>
    client.put<any, any>(`/api/deployments/${id}/env`, data),
}

/** 平台级全局环境变量 + 中间件接入信息 */
export const platformApi = {
  listEnv: () => client.get<any, any[]>('/api/platform/env').then(ensureArray<any>),
  upsertEnv: (data: { env_key: string; env_value: string; description?: string }) =>
    client.post<any, any>('/api/platform/env', data),
  deleteEnv: (id: string) => client.delete(`/api/platform/env/${id}`),
  middleware: () => client.get<any, any>('/api/platform/middleware'),
}

/** 链路监控看板 */
export const dashboardApi = {
  overview: () => client.get<any, any>('/api/dashboard/overview'),
  flowRunTrace: (runId: string) => client.get<any, any>(`/api/dashboard/flow-runs/${runId}/trace`),
}

export const versionApi = {
  listBlockVersions: (blockId: string) =>
    client.get<any, any[]>(`/api/versions/blocks/${blockId}`).then(ensureArray<any>),
  createBlockVersion: (
    blockId: string,
    data: { version_tag: string; commit_message?: string; requirements_text?: string; set_stable?: boolean },
  ) => client.post<any, any>(`/api/versions/blocks/${blockId}`, data),
  getBlockVersion: (versionId: string) =>
    client.get<any, any>(`/api/versions/block-versions/${versionId}`),
  setBlockStable: (versionId: string) =>
    client.post<any, any>(`/api/versions/block-versions/${versionId}/stable`),
  diffBlock: (blockId: string, fromVersion: string, toVersion: string) =>
    client.get<any, any>(`/api/versions/blocks/${blockId}/diff`, {
      params: { from_version: fromVersion, to_version: toVersion },
    }),
  listFlowVersions: (flowId: string) =>
    client.get<any, any[]>(`/api/versions/flows/${flowId}`).then(ensureArray<any>),
  createFlowVersion: (
    flowId: string,
    data: { version_tag: string; commit_message?: string; set_stable?: boolean },
  ) => client.post<any, any>(`/api/versions/flows/${flowId}`, data),
}

export const jupyterApi = {
  start: (blockId: string) => client.post<any, any>(`/api/jupyter/${blockId}/start`),
  execute: (blockId: string, code: string) =>
    client.post<any, any>(`/api/jupyter/${blockId}/execute`, { code }),
  interrupt: (blockId: string) => client.post<any, any>(`/api/jupyter/${blockId}/interrupt`),
  shutdown: (blockId: string) => client.post<any, any>(`/api/jupyter/${blockId}/shutdown`),
  status: (blockId: string) => client.get<any, any>(`/api/jupyter/${blockId}/status`),
}

export interface PublishedApi {
  id: string
  name: string
  description: string
  path: string
  invoke_path: string
  tags: string
  flow_id: string
  active_flow_id: string | null
  owner_login_id: string
  status: string
  is_locked: boolean
  lock_reason: string | null
  locked_by: string | null
  locked_at: string | null
  rate_limit_enabled: boolean
  rate_limit_per_minute: number
  load_balance_strategy: string
  degradation_enabled: boolean
  degradation_fallback: Record<string, any>
  total_calls: number
  success_calls: number
  error_calls: number
  avg_latency_ms: number
  created_at: string
  updated_at: string
}

export const apiPortalApi = {
  list: () => client.get<any, PublishedApi[]>('/api/portal/apis').then(ensureArray<PublishedApi>),
  publish: (data: {
    name: string
    description?: string
    path: string
    tags?: string
    flow_id: string
  }) => client.post<any, PublishedApi>('/api/portal/apis', data),
  get: (id: string) => client.get<any, PublishedApi>(`/api/portal/apis/${id}`),
  unpublish: (id: string) => client.delete(`/api/portal/apis/${id}`),
  pause: (id: string) => client.post(`/api/portal/apis/${id}/pause`),
  activate: (id: string) => client.post(`/api/portal/apis/${id}/activate`),
  getDocs: (id: string) => client.get<any, any>(`/api/portal/apis/${id}/docs`),
  copyFlow: (flowId: string) => client.post<any, any>(`/api/flows/${flowId}/copy`),
}

export const mqApi = {
  getStatus: () => client.get<any, any>('/api/mq/status'),
  getBlockStatus: (blockId: string) => client.get<any, any>(`/api/mq/blocks/${blockId}/status`),
  getDepth: (blockId: string) => client.get<any, any>(`/api/mq/blocks/${blockId}/depth`),
  start: (blockId: string) => client.post<any, any>(`/api/mq/blocks/${blockId}/start`),
  stop: (blockId: string) => client.post<any, any>(`/api/mq/blocks/${blockId}/stop`),
  restart: (blockId: string) => client.post<any, any>(`/api/mq/blocks/${blockId}/restart`),
  /** 同步执行（兼容 local/k8s，记录执行历史，返回结果） */
  testRun: (blockId: string, data: { payload?: object; snowflake_id?: string }) =>
    client.post<any, any>(`/api/mq/blocks/${blockId}/test-run`, data),
  /** 仅发布到队列（需要消费者正在运行） */
  publish: (blockId: string, data: { payload?: object; snowflake_id?: string }) =>
    client.post<any, any>(`/api/mq/blocks/${blockId}/publish`, data),
  startAll: () => client.post<any, any>('/api/mq/start-all'),
  stopAll: () => client.post<any, any>('/api/mq/stop-all'),
  /** DLQ 运维：预览死信样本 */
  peekDlq: (blockId: string, limit = 10) =>
    client.get<any, any>(`/api/mq/blocks/${blockId}/dlq`, { params: { limit } }),
  /** DLQ 运维：全部重投回主队列（重置 x-retry-count，DEPLOYER） */
  requeueDlq: (blockId: string) => client.post<any, any>(`/api/mq/blocks/${blockId}/dlq/requeue`),
  /** DLQ 运维：清空死信（DEPLOYER） */
  purgeDlq: (blockId: string) => client.post<any, any>(`/api/mq/blocks/${blockId}/dlq/purge`),
}

export const healthApi = {
  deps: () => client.get<any, Record<string, string>>('/health/deps'),
}

export const apiAdminApi = {
  listAll: () => client.get<any, PublishedApi[]>('/api/admin/apis').then(ensureArray<PublishedApi>),
  get: (id: string) => client.get<any, PublishedApi>(`/api/admin/apis/${id}`),
  getDocs: (id: string) => client.get<any, any>(`/api/admin/apis/${id}/docs`),
  getInstances: (id: string) => client.get<any, any>(`/api/admin/apis/${id}/instances`),
  getOverview: () => client.get<any, any>('/api/admin/stats/overview'),
  updatePolicy: (
    id: string,
    data: {
      rate_limit_enabled?: boolean
      rate_limit_per_minute?: number
      load_balance_strategy?: string
      degradation_enabled?: boolean
      degradation_fallback?: object
    },
  ) => client.put<any, PublishedApi>(`/api/admin/apis/${id}/policy`, data),
  lock: (id: string, lock_reason?: string) =>
    client.post<any, PublishedApi>(`/api/admin/apis/${id}/lock`, { lock_reason }),
  unlock: (id: string) => client.post<any, PublishedApi>(`/api/admin/apis/${id}/unlock`),
  switchVersion: (id: string, new_flow_id: string) =>
    client.post<any, PublishedApi>(`/api/admin/apis/${id}/switch-version`, { new_flow_id }),
}
