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
