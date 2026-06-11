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

export interface Entrypoint {
  name: string
  description?: string
  params?: string[]
}

export interface Block {
  id: string
  name: string
  description: string
  type: string
  draft_code: string
  draft_requirements?: string
  requirements_hash?: string
  input_ports: any[]
  output_ports: any[]
  entrypoints: Entrypoint[]
  compute_config: Record<string, any>
  source_flow_id?: string | null
  source_flow_name?: string | null
}

export const blockApi = {
  list: () => client.get<any, Block[]>('/api/blocks').then(ensureArray<Block>),
  get: (id: string) => client.get<any, Block>(`/api/blocks/${id}`),
  create: (data: Partial<Block>) => client.post<any, Block>('/api/blocks', data),
  update: (id: string, data: Partial<Block>) => client.put<any, Block>(`/api/blocks/${id}`, data),
  remove: (id: string) => client.delete(`/api/blocks/${id}`),
  /** 静态扫描脚本暴露的入口函数清单（供节点选择调用哪个函数） */
  discoverEntrypoints: (id: string) =>
    client.post<any, { block_id: string; entrypoints: Entrypoint[] }>(
      `/api/blocks/${id}/discover-entrypoints`,
    ),
}

export const flowApi = {
  list: () => client.get<any, any[]>('/api/flows').then(ensureArray<any>),
  get: (id: string) => client.get<any, any>(`/api/flows/${id}`),
  create: (data: { name: string; description?: string }) => client.post('/api/flows', data),
  remove: (id: string) => client.delete(`/api/flows/${id}`),
  saveGraph: (id: string, nodes: any[], edges: any[], entry_node_id?: string | null) =>
    client.put(`/api/flows/${id}/graph`, { nodes, edges, entry_node_id: entry_node_id ?? null }),
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
  create: (data: { flow_id: string; name: string; environment: string; deployment_type?: string }) =>
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
  /** 列出该部署各 Block 的 Pod 资源（块默认值 / 部署级覆盖 / 生效值） */
  resources: (id: string) => client.get<any, BlockResource[]>(`/api/deployments/${id}/resources`).then(ensureArray<BlockResource>),
  /** 配置部署级 Pod 资源覆盖（按 block_id 覆盖 CPU/内存/GPU，下次部署生效，DEPLOYER） */
  updateResources: (id: string, resource_overrides: Record<string, BlockResourceSpec>) =>
    client.put<any, any>(`/api/deployments/${id}/resources`, { resource_overrides }),
  /** 对未保存的资源覆盖做实时容量/GPU 预检（编辑时即时反馈，不落库） */
  precheckResources: (id: string, resource_overrides: Record<string, BlockResourceSpec>) =>
    client.post<any, any>(`/api/deployments/${id}/resources/precheck`, { resource_overrides }),
  /** Flow 维度资源汇总（各块独立 Pod 请求/上限累加 + 节点池占用 + KEDA 峰值估算） */
  resourceSummary: (id: string) =>
    client.get<any, FlowResourceSummary>(`/api/deployments/${id}/resource-summary`),
}

export interface FlowResourceSummary {
  block_count: number
  is_flow_mode?: boolean
  pool: { name: string; cpu_m: number; mem_mib: number }
  resident: { cpu_m: number; mem_mib: number }
  limit: { cpu_m: number; mem_mib: number }
  keda_peak: { cpu_m: number; mem_mib: number }
  gpu: { total: number; block_count: number }
  usage: { cpu_pct: number; mem_pct: number }
  capacity_ok: boolean
  capacity_reason: string
  blocks: Array<{
    block_id: string
    name: string
    gpu_enabled: boolean
    request: { cpu_m: number; mem_mib: number }
    limit: { cpu_m: number; mem_mib: number }
    max_replica: number
  }>
}

export interface BlockResourceSpec {
  cpu_request?: string
  memory_request?: string
  cpu_limit?: string
  memory_limit?: string
  gpu_enabled?: boolean
  gpu_count?: number
  gpu_type?: string
}

export interface BlockResource {
  block_id: string
  name: string
  default: Required<BlockResourceSpec>
  override: BlockResourceSpec
  effective: Required<BlockResourceSpec>
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
  trigger_type: string
  mq_config: Record<string, any>
  entry_node_id: string | null
  entrypoint: string | null
  entrypoint_map: Record<string, string>
  is_locked: boolean
  lock_reason: string | null
  locked_by: string | null
  locked_at: string | null
  rate_limit_enabled: boolean
  rate_limit_per_minute: number
  load_balance_strategy: string
  degradation_enabled: boolean
  degradation_fallback: Record<string, any>
  encryption_enabled: boolean
  require_encrypted_request: boolean
  total_calls: number
  success_calls: number
  error_calls: number
  avg_latency_ms: number
  // 开发者文档字段
  remarks: string
  sample_request: string
  sample_response: string
  changelog: string
  created_at: string
  updated_at: string
}

export interface ApiEncryptionKey {
  api_id: string
  encryption_enabled: boolean
  require_encrypted_request: boolean
  /** 完整密钥（64 位 hex），仅新生成/轮转/主动查看时返回 */
  encryption_key: string | null
  /** 密钥指纹（前 8 位），用于核对而不暴露完整密钥 */
  key_hint: string | null
}

export interface FlowEntrypointsInfo {
  flow_id: string
  flow_name: string
  entry_node_id: string | null
  all_entrypoints: string[]
  has_multiple: boolean
  nodes: Array<{
    node_id: string
    block_id: string
    block_name: string
    is_entry: boolean
    configured_entrypoint: string
    available_entrypoints: Array<{ name: string; description: string }>
  }>
}

export const apiPortalApi = {
  list: () => client.get<any, PublishedApi[]>('/api/portal/apis').then(ensureArray<PublishedApi>),
  /** 浏览所有活跃接口（接口门户用，不限 owner） */
  browse: () => client.get<any, PublishedApi[]>('/api/portal/apis/browse').then(ensureArray<PublishedApi>),
  publish: (data: {
    name: string
    description?: string
    path: string
    tags?: string
    flow_id: string
    entry_node_id?: string | null
    entrypoint?: string | null
    entrypoint_map?: Record<string, string>
  }) => client.post<any, PublishedApi>('/api/portal/apis', data),
  /** 获取流程所有节点的可用入口函数（用于发布/MQ 配置时选择绑定函数） */
  getFlowEntrypoints: (flowId: string) =>
    client.get<any, FlowEntrypointsInfo>(`/api/portal/flows/${flowId}/entrypoints`),
  get: (id: string) => client.get<any, PublishedApi>(`/api/portal/apis/${id}`),
  unpublish: (id: string) => client.delete(`/api/portal/apis/${id}`),
  pause: (id: string) => client.post(`/api/portal/apis/${id}/pause`),
  activate: (id: string) => client.post(`/api/portal/apis/${id}/activate`),
  getDocs: (id: string) => client.get<any, any>(`/api/portal/apis/${id}/docs`),
  /** 配置接口触发方式（http/mq/both）+ MQ 触发参数（队列/条件/映射/回复/重试，决策 3.1 Flow 级） */
  updateMq: (id: string, data: { trigger_type: string; mq_config: Record<string, any> }) =>
    client.put<any, PublishedApi>(`/api/portal/apis/${id}/mq`, data),
  /** 开启/关闭接口加密保护（AES-256-GCM）；首次开启返回新生成的密钥 */
  updateEncryption: (
    id: string,
    data: { enabled: boolean; require_encrypted_request?: boolean },
  ) => client.put<any, ApiEncryptionKey>(`/api/portal/apis/${id}/encryption`, data),
  /** 轮转接口密钥（旧密钥立即失效），返回新密钥 */
  rotateEncryptionKey: (id: string) =>
    client.post<any, ApiEncryptionKey>(`/api/portal/apis/${id}/encryption/rotate`),
  /** 查看接口当前完整密钥（用于配置调用方） */
  getEncryptionKey: (id: string) =>
    client.get<any, ApiEncryptionKey>(`/api/portal/apis/${id}/encryption/key`),
  copyFlow: (flowId: string) => client.post<any, any>(`/api/flows/${flowId}/copy`),
  /** 更新接口开发者文档（备注、示例请求/响应、变更日志） */
  updateRemarks: (
    id: string,
    data: { remarks?: string; sample_request?: string; sample_response?: string; changelog?: string },
  ) => client.put<any, PublishedApi>(`/api/portal/apis/${id}/remarks`, data),
  /**
   * 在线测试：直接调用公开入口 POST /api/public/{path}，返回完整 AxiosResponse，
   * 供测试面板读取 HTTP 状态码与原始响应（不走全局错误拦截，错误由调用方捕获）。
   */
  invoke: (path: string, payload: any) =>
    rawClient.post(`/api/public/${path}`, payload, {
      headers: { 'Content-Type': 'application/json' },
      validateStatus: () => true,
    }),
  /**
   * 流式调用：POST /api/public/{path}/stream，SSE 逐 chunk 实时回调。
   * 用 fetch + ReadableStream 逐行解析（需 POST，不能用 EventSource）；返回 AbortController 供中止。
   * @param onChunk 每个 `event: data` 的 chunk 内容（用户代码 yield 的值）
   * @param onResult 终止 `event: result`（含 outputs / latency / degraded）
   * @param onError `event: error` 或网络异常
   * @param onDone 流结束（无论成功失败）
   */
  invokeStream: (
    path: string,
    payload: any,
    handlers: {
      onChunk?: (chunk: any) => void
      onResult?: (result: any) => void
      onError?: (err: string) => void
      onDone?: () => void
    },
  ): AbortController => {
    const ctrl = new AbortController()
    ;(async () => {
      try {
        const resp = await fetch(`${baseURL}/api/public/${path}/stream`, {
          method: 'POST',
          signal: ctrl.signal,
          headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
          body: JSON.stringify(payload),
        })
        if (!resp.ok || !resp.body) {
          let detail = `HTTP ${resp.status}`
          try {
            const j = await resp.json()
            detail = j?.detail || j?.msgKey || detail
          } catch {
            /* 非 JSON 错误体忽略 */
          }
          handlers.onError?.(detail)
          handlers.onDone?.()
          return
        }
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        // 逐块读取，按 SSE 帧（空行分隔）切分，解析 event/data
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let sep: number
          while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sep)
            buffer = buffer.slice(sep + 2)
            let event = 'message'
            const dataLines: string[] = []
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) event = line.slice(6).trim()
              else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
            }
            if (!dataLines.length) continue
            let data: any = {}
            try {
              data = JSON.parse(dataLines.join('\n'))
            } catch {
              data = { raw: dataLines.join('\n') }
            }
            if (event === 'data') handlers.onChunk?.(data.chunk)
            else if (event === 'result') handlers.onResult?.(data)
            else if (event === 'error') handlers.onError?.(data.error || '执行失败')
            else if (event === 'done') handlers.onDone?.()
          }
        }
        handlers.onDone?.()
      } catch (e: any) {
        if (e?.name !== 'AbortError') handlers.onError?.(e?.message || '网络错误')
        handlers.onDone?.()
      }
    })()
    return ctrl
  },
}

/** MQ 消费者管理（接口/Flow 级，决策 3.1 重写为 Flow 级模型 A，全部按 api_id 维度）。 */
export const mqApi = {
  getStatus: () => client.get<any, any>('/api/mq/status'),
  getApiStatus: (apiId: string) => client.get<any, any>(`/api/mq/apis/${apiId}/status`),
  getDepth: (apiId: string) => client.get<any, any>(`/api/mq/apis/${apiId}/depth`),
  start: (apiId: string) => client.post<any, any>(`/api/mq/apis/${apiId}/start`),
  stop: (apiId: string) => client.post<any, any>(`/api/mq/apis/${apiId}/stop`),
  restart: (apiId: string) => client.post<any, any>(`/api/mq/apis/${apiId}/restart`),
  /** 用 MQ payload 同步驱动整条 Flow（兼容 local/k8s，返回 outputs） */
  testRun: (apiId: string, data: { payload?: object; snowflake_id?: string }) =>
    client.post<any, any>(`/api/mq/apis/${apiId}/test-run`, data),
  /** 仅发布到接口队列 flow.{api_id}.queue（需要消费者正在运行） */
  publish: (apiId: string, data: { payload?: object; snowflake_id?: string }) =>
    client.post<any, any>(`/api/mq/apis/${apiId}/publish`, data),
  startAll: () => client.post<any, any>('/api/mq/start-all'),
  stopAll: () => client.post<any, any>('/api/mq/stop-all'),
  /** DLQ 运维：预览死信样本 */
  peekDlq: (apiId: string, limit = 10) =>
    client.get<any, any>(`/api/mq/apis/${apiId}/dlq`, { params: { limit } }),
  /** DLQ 运维：全部重投回主队列（重置 x-retry-count，DEPLOYER） */
  requeueDlq: (apiId: string) => client.post<any, any>(`/api/mq/apis/${apiId}/dlq/requeue`),
  /** DLQ 运维：清空死信（DEPLOYER） */
  purgeDlq: (apiId: string) => client.post<any, any>(`/api/mq/apis/${apiId}/dlq/purge`),
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
