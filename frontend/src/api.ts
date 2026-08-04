import type {
  AdminOperation,
  AdminQuotaCollection,
  AdminScopeType,
  AdminSession,
  IdentityKind,
  IdentityPage,
  IdentityResource,
  InstanceDetail,
  InstancePage,
  InstanceQuery,
  ImagePage,
  ImageQuery,
  InventoryQuery,
  KeyPairPage,
  OperationAck,
  Problem,
  ProjectOverview,
  ProjectPage,
  QuotaPayload,
  QuotaService,
  RoleAssignmentPage,
  Session,
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
  instance: (instanceId: string, signal?: AbortSignal) =>
    request<InstanceDetail>(`/instances/${encodeURIComponent(instanceId)}`, { signal }),
  adminSession: (signal?: AbortSignal) => request<AdminSession>('/admin/session', { signal }),
  adminScope: (type: AdminScopeType, id: string) => request<AdminSession>('/admin/scope', {
    method: 'PUT',
    body: JSON.stringify({ type, id }),
  }),
  adminIdentity: (
    kind: IdentityKind,
    name: string,
    page: number,
    limit: number,
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams({ page: String(page), limit: String(limit) })
    if (name) query.set('name', name)
    return request<IdentityPage>(`/admin/identity/${kind}?${query}`, { signal })
  },
  adminIdentityDetail: (kind: IdentityKind, id: string) =>
    request<IdentityResource>(`/admin/identity/${kind}/${encodeURIComponent(id)}`),
  createAdminIdentity: (kind: IdentityKind, payload: Record<string, unknown>, confirm: string) =>
    request<OperationAck>(`/admin/identity/${kind}`, {
      method: 'POST',
      headers: {
        'Idempotency-Key': crypto.randomUUID(),
        'X-Confirm-Target': confirm,
      },
      body: JSON.stringify(payload),
    }),
  updateAdminIdentity: (
    kind: IdentityKind,
    id: string,
    payload: Record<string, unknown>,
  ) => request<OperationAck>(`/admin/identity/${kind}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Idempotency-Key': crypto.randomUUID(), 'X-Confirm-Target': id },
    body: JSON.stringify(payload),
  }),
  deleteAdminIdentity: (kind: IdentityKind, id: string, confirm: string) =>
    request<OperationAck>(`/admin/identity/${kind}/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ confirm }),
    }),
  adminAssignments: (page: number, limit: number, signal?: AbortSignal) => {
    const query = new URLSearchParams({ page: String(page), limit: String(limit) })
    return request<RoleAssignmentPage>(`/admin/role-assignments?${query}`, { signal })
  },
  grantAdminRole: (payload: Record<string, unknown>, actorId: string) =>
    request<OperationAck>('/admin/role-assignments', {
      method: 'POST',
      headers: {
        'Idempotency-Key': crypto.randomUUID(),
        'X-Confirm-Target': actorId,
      },
      body: JSON.stringify(payload),
    }),
  revokeAdminRole: (id: string) => request<OperationAck>(
    `/admin/role-assignments/${encodeURIComponent(id)}`,
    {
      method: 'DELETE',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ confirm: id }),
    },
  ),
  adminQuotas: (projectId: string, userId = '', signal?: AbortSignal) => {
    const query = new URLSearchParams()
    if (userId) query.set('user_id', userId)
    const suffix = query.size ? `?${query}` : ''
    return request<AdminQuotaCollection>(
      `/admin/projects/${encodeURIComponent(projectId)}/quotas${suffix}`,
      { signal },
    )
  },
  updateAdminQuotas: (
    projectId: string,
    service: QuotaService,
    values: Record<string, number>,
    userId = '',
  ) => request<OperationAck>(
    `/admin/projects/${encodeURIComponent(projectId)}/quotas/${service}`,
    {
      method: 'PUT',
      headers: {
        'Idempotency-Key': crypto.randomUUID(),
        'X-Confirm-Target': projectId,
      },
      body: JSON.stringify({ values, user_id: userId || null }),
    },
  ),
  resetAdminQuotas: (projectId: string, service: QuotaService, userId = '') => {
    const query = userId ? `?${new URLSearchParams({ user_id: userId })}` : ''
    return request<OperationAck>(
      `/admin/projects/${encodeURIComponent(projectId)}/quotas/${service}${query}`,
      {
        method: 'DELETE',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ confirm: projectId }),
      },
    )
  },
  adminOperation: (id: string, signal?: AbortSignal) =>
    request<AdminOperation>(`/admin/operations/${encodeURIComponent(id)}`, { signal }),
  logout: async () => {
    await request<void>('/session', { method: 'DELETE' })
    csrfToken = ''
  },
}

export function resetCsrfForTest(): void {
  csrfToken = ''
}
