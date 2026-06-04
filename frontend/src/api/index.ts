import client from './client'

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
  create: (data: { flow_id: string; name: string; environment: string }) =>
    client.post('/api/deployments', data),
}

export interface PublishedApi {
  id: string
  name: string
  description: string
  path: string
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
  publish: (blockId: string, data: { payload?: object; snowflake_id?: string }) =>
    client.post<any, any>(`/api/mq/blocks/${blockId}/publish`, data),
  startAll: () => client.post<any, any>('/api/mq/start-all'),
  stopAll: () => client.post<any, any>('/api/mq/stop-all'),
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
