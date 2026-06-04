import client from './client'

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
  list: () => client.get<any, Block[]>('/api/blocks'),
  get: (id: string) => client.get<any, Block>(`/api/blocks/${id}`),
  create: (data: Partial<Block>) => client.post<any, Block>('/api/blocks', data),
  update: (id: string, data: Partial<Block>) => client.put<any, Block>(`/api/blocks/${id}`, data),
  remove: (id: string) => client.delete(`/api/blocks/${id}`),
  run: (id: string, inputs: Record<string, any>) =>
    client.post(`/api/blocks/${id}/run`, { inputs }),
}

export const flowApi = {
  list: () => client.get<any, any[]>('/api/flows'),
  get: (id: string) => client.get<any, any>(`/api/flows/${id}`),
  create: (data: { name: string; description?: string }) => client.post('/api/flows', data),
  saveGraph: (id: string, nodes: any[], edges: any[]) =>
    client.put(`/api/flows/${id}/graph`, { nodes, edges }),
  run: (id: string, inputs: Record<string, any>) => client.post(`/api/flows/${id}/run`, { inputs }),
}

export const execApi = {
  records: (blockId?: string) =>
    client.get<any, any[]>('/api/exec/records', { params: { block_id: blockId } }),
  record: (id: string) => client.get(`/api/exec/records/${id}`),
  flowRuns: (flowId?: string) =>
    client.get<any, any[]>('/api/exec/flow-runs', { params: { flow_id: flowId } }),
}

export const deploymentApi = {
  list: () => client.get<any, any[]>('/api/deployments'),
  create: (data: { flow_id: string; name: string; environment: string }) =>
    client.post('/api/deployments', data),
}
