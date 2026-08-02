import type { Problem, ProjectPage, Session } from './types'

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
  logout: async () => {
    await request<void>('/session', { method: 'DELETE' })
    csrfToken = ''
  },
}

export function resetCsrfForTest(): void {
  csrfToken = ''
}
