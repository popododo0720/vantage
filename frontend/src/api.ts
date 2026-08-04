import type {
  InstanceDetail,
  InstancePage,
  InstanceQuery,
  ImagePage,
  ImageQuery,
  InventoryQuery,
  KeyPairPage,
  Problem,
  ProjectOverview,
  ProjectPage,
  QuotaPayload,
  QuotaService,
  Session,
  Operation,
  StoragePage,
  StorageQuery,
} from './types'

let csrfToken = ''
const REQUEST_TIMEOUT_MS = 20_000

export class ApiError extends Error {
  constructor(public readonly problem: Problem, public readonly status: number) {
    super(problem.detail)
  }
}

async function readProblem(response: Response): Promise<Problem> {
  const traceId = response.headers.get('X-Trace-ID') ?? 'unavailable'
  try {
    const value = (await response.json()) as Partial<Problem>
    return {
      detail: value.detail ?? `Request failed with status ${response.status}`,
      code: value.code ?? 'request_failed',
      trace_id: value.trace_id ?? traceId,
      openstack_request_id: value.openstack_request_id,
    }
  } catch {
    return {
      detail: `Request failed with status ${response.status}`,
      code: 'request_failed',
      trace_id: traceId,
    }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const abortFromCaller = () => controller.abort(init?.signal?.reason)
  if (init?.signal?.aborted) abortFromCaller()
  else init?.signal?.addEventListener('abort', abortFromCaller, { once: true })
  const timeout = window.setTimeout(() => {
    controller.abort(new DOMException('Request timed out', 'TimeoutError'))
  }, REQUEST_TIMEOUT_MS)
  const headers = new Headers(init?.headers)
  headers.set('Accept', 'application/json')
  if (init?.body) headers.set('Content-Type', 'application/json')
  if (init?.method && init.method !== 'GET' && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...init,
      headers,
      signal: controller.signal,
      credentials: 'same-origin',
    })
    const nextCsrf = response.headers.get('X-CSRF-Token')
    if (nextCsrf) csrfToken = nextCsrf
    if (response.status === 401) csrfToken = ''
    if (!response.ok) throw new ApiError(await readProblem(response), response.status)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } finally {
    window.clearTimeout(timeout)
    init?.signal?.removeEventListener('abort', abortFromCaller)
  }
}

export const api = {
  session: () => request<Session>('/session'),
  login: (username: string, password: string, domain: string) => {
    csrfToken = ''
    return request<Session>('/session/login', {
      method: 'POST',
      body: JSON.stringify({ username, password, domain }),
    })
  },
  projects: (name = '', page = 1, limit = 25, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: String(limit), page: String(page) })
    if (name) query.set('name', name)
    return request<ProjectPage>(`/projects?${query}`, { signal })
  },
  scope: (projectId: string, region: string) =>
    request<Session>('/scope', {
      method: 'PUT',
      body: JSON.stringify({ project_id: projectId, region }),
    }),
  locale: (locale: 'en' | 'ko') =>
    request<Session>('/session', {
      method: 'PATCH',
      body: JSON.stringify({ locale }),
    }),
  overview: (signal?: AbortSignal) =>
    request<ProjectOverview>('/overview', { signal }),
  quotas: (service?: QuotaService, signal?: AbortSignal) => {
    const query = service ? `?${new URLSearchParams({ service })}` : ''
    return request<QuotaPayload>(`/quotas${query}`, { signal })
  },
  instances: (filters: InstanceQuery, signal?: AbortSignal) => {
    const query = new URLSearchParams({
      limit: String(filters.limit),
      page: String(filters.page),
      name: filters.name,
      status: filters.status,
      image_id: filters.imageId,
      sort: filters.sort,
      direction: filters.direction,
    })
    return request<InstancePage>(`/instances?${query}`, { signal })
  },
  images: (filters: ImageQuery, signal?: AbortSignal) => {
    const query = new URLSearchParams({
      limit: String(filters.limit),
      page: String(filters.page),
    })
    if (filters.name) query.set('name', filters.name)
    if (filters.visibility) query.set('visibility', filters.visibility)
    return request<ImagePage>(`/images?${query}`, { signal })
  },
  keypairs: (filters: InventoryQuery, signal?: AbortSignal) => {
    const query = new URLSearchParams({
      limit: String(filters.limit),
      page: String(filters.page),
    })
    return request<KeyPairPage>(`/keypairs?${query}`, { signal })
  },
  storage: (filters: StorageQuery, signal?: AbortSignal) => {
    const paths = {
      volumes: '/volumes', snapshots: '/volume-snapshots', backups: '/volume-backups',
      types: '/admin/storage/volume-types', qos: '/admin/storage/qos-specs',
      pools: '/admin/storage/pools', services: '/admin/storage/services',
    } as const
    const query = new URLSearchParams({
      limit: String(filters.limit), page: String(filters.page),
      sort: filters.sort, direction: filters.direction,
    })
    if (filters.name) query.set('name', filters.name)
    if (filters.status) query.set('status', filters.status)
    return request<StoragePage>(`${paths[filters.resource]}?${query}`, { signal })
  },
  storageCreate: (resource: 'volumes' | 'snapshots' | 'backups' | 'types' | 'qos', payload: unknown) => {
    const paths = {
      volumes: '/volumes', snapshots: '/volume-snapshots', backups: '/volume-backups',
      types: '/admin/storage/volume-types', qos: '/admin/storage/qos-specs',
    } as const
    return request<Operation>(paths[resource], {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    })
  },
  storageUpdate: (resource: 'volumes' | 'snapshots' | 'backups' | 'types' | 'qos', id: string, payload: unknown) => {
    const paths = {
      volumes: '/volumes', snapshots: '/volume-snapshots', backups: '/volume-backups',
      types: '/admin/storage/volume-types', qos: '/admin/storage/qos-specs',
    } as const
    return request<Operation>(`${paths[resource]}/${encodeURIComponent(id)}`, {
      method: resource === 'types' || resource === 'qos' ? 'PUT' : 'PATCH',
      headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify(payload),
    })
  },
  storageDelete: (resource: 'volumes' | 'snapshots' | 'backups' | 'types' | 'qos', id: string, force = false) => {
    const paths = {
      volumes: '/volumes', snapshots: '/volume-snapshots', backups: '/volume-backups',
      types: '/admin/storage/volume-types', qos: '/admin/storage/qos-specs',
    } as const
    const query = new URLSearchParams({ confirmation: id })
    if (resource === 'qos' && force) query.set('force', 'true')
    if (force && resource !== 'qos') {
      return request<Operation>(`${paths[resource]}/${encodeURIComponent(id)}/actions`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ action: 'force_delete', confirmation: id, force: true }),
      })
    }
    return request<Operation>(`${paths[resource]}/${encodeURIComponent(id)}?${query}`, {
      method: 'DELETE', headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },
  volumeAction: (id: string, payload: Record<string, unknown>) =>
    request<Operation>(`/volumes/${encodeURIComponent(id)}/actions`, {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  snapshotAction: (id: string, payload: Record<string, unknown>) =>
    request<Operation>(`/volume-snapshots/${encodeURIComponent(id)}/actions`, {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  backupAction: (id: string, payload: Record<string, unknown>) =>
    request<Operation>(`/volume-backups/${encodeURIComponent(id)}/actions`, {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  serviceAction: (id: string, payload: Record<string, unknown>) =>
    request<Operation>(`/admin/storage/services/${encodeURIComponent(id)}/actions`, {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  instance: (instanceId: string, signal?: AbortSignal) =>
    request<InstanceDetail>(`/instances/${encodeURIComponent(instanceId)}`, { signal }),
  logout: async () => {
    await request<void>('/session', { method: 'DELETE' })
    csrfToken = ''
  },
}

export function resetCsrfForTest(): void {
  csrfToken = ''
}
