import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { resetCsrfForTest } from './api'
import type { ImagePage, InstanceDetail, InstancePage, KeyPairPage, Operation } from './types'

const projects = [{ id: 'project-alpha', name: 'Alpha', enabled: true }]
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

const session = {
  user: { id: 'user-alice', name: 'alice', domain_id: 'default' },
  active_scope: null,
  expires_at: '2026-08-02T00:00:00Z',
  regions: ['RegionOne'],
  locale: 'en',
}

const projectPage = {
  items: projects,
  page: {
    number: 1,
    size: 25,
    item_from: 1,
    item_to: 1,
    total_items: 1,
    total_pages: 1,
    has_previous: false,
    has_next: false,
    navigable_pages: [1],
  },
}

const scopedSession = {
  ...session,
  active_scope: { project: projects[0], region: 'RegionOne' },
}

const quotas = [
  { service: 'compute', resource: 'instances', used: 2, reserved: 1, limit: 10, unit: 'count', state: 'normal' },
  { service: 'compute', resource: 'cores', used: 8, reserved: 2, limit: 20, unit: 'count', state: 'normal' },
  { service: 'compute', resource: 'ram_mib', used: 10240, reserved: 0, limit: null, unit: 'MiB', state: 'unknown' },
  { service: 'network', resource: 'floating_ips', used: 5, reserved: 1, limit: 10, unit: 'count', state: 'watch' },
  { service: 'storage', resource: 'volumes', used: 12, reserved: 0, limit: 20, unit: 'count', state: 'watch' },
]

const overviewPayload = {
  scope: scopedSession.active_scope,
  generated_at: '2026-08-02T01:02:03Z',
  stale: false,
  quotas,
  instance_summary: { total: 2, active: 1, stopped: 1, error: 0 },
  partial_errors: [],
}

const quotaPayload = {
  scope: scopedSession.active_scope,
  generated_at: '2026-08-02T01:02:03Z',
  stale: false,
  quotas,
  partial_errors: [],
}

const server = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'web-01',
  status: 'ACTIVE',
  created_at: '2026-08-01T12:00:00Z',
  flavor: 'm1.small',
  image: 'ubuntu-24.04',
  addresses: ['private=10.0.0.10', 'public=203.0.113.10'],
}

const unknownServer = {
  id: '22222222-2222-4222-8222-222222222222',
  name: null,
  status: 'UNKNOWN',
  created_at: null,
  flavor: null,
  image: null,
  addresses: null,
}

const instancePage: InstancePage = {
  items: [server, unknownServer],
  page: {
    number: 1,
    size: 25,
    item_from: 1,
    item_to: 2,
    total_items: null,
    total_pages: null,
    has_previous: false,
    has_next: true,
    navigable_pages: [1, 2],
    openstack_request_id: 'req-list-1',
  },
}

const serverDetail: InstanceDetail = {
  ...server,
  volumes: [{ id: 'volume-01', device: '/dev/vdb' }, { id: 'volume-02', device: null }],
  openstack_request_id: 'req-detail-1',
}

const imagePage: ImagePage = {
  items: [{
    id: 'image-ubuntu', name: 'Ubuntu 24.04', status: 'active', visibility: 'public',
    disk_format: 'qcow2', container_format: 'bare', size_bytes: 2_147_483_648,
    min_disk_gib: 20, min_ram_mib: 2048, created_at: '2026-07-01T09:00:00Z',
  }],
  page: {
    number: 1, size: 25, item_from: 1, item_to: 1, total_items: 26, total_pages: 2,
    has_previous: false, has_next: true, navigable_pages: [1, 2],
  },
}

const keyPairPage: KeyPairPage = {
  items: [{
    name: 'ops-key', type: 'ssh', fingerprint: 'SHA256:abc123',
    public_key_preview: 'ssh-ed25519 AAAAC3...', created_at: '2026-06-01T09:00:00Z',
    last_used_at: '2026-07-31T11:00:00Z',
  }],
  page: {
    number: 1, size: 25, item_from: 1, item_to: 1, total_items: 1, total_pages: 1,
    has_previous: false, has_next: false, navigable_pages: [1],
  },
}

const acceptedOperation: Operation = {
  id: '33333333-3333-4333-8333-333333333333',
  kind: 'keypair.import',
  status: 'accepted',
  submitted_at: '2026-08-02T10:00:00Z',
  updated_at: '2026-08-02T10:00:00Z',
  target: { resource_type: 'keypair', resource_id: null, resource_name: 'ops-key' },
  trace_id: 'trace-keypair',
  openstack_request_ids: ['req-keypair'],
  problem: null,
}

function scopedFetch({
  list = instancePage,
  detail = serverDetail,
}: {
  list?: InstancePage
  detail?: InstanceDetail
} = {}) {
  return vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/session' && method === 'GET') return Promise.resolve(json(scopedSession))
    if (url === '/api/v1/session' && method === 'PATCH') {
      return Promise.resolve(json({ ...scopedSession, locale: 'ko' }))
    }
    if (url.startsWith('/api/v1/instances?')) {
      const parameters = new URL(url, 'http://local').searchParams
      const page = Number(parameters.get('page'))
      const size = Number(parameters.get('limit'))
      return Promise.resolve(json({
        ...list,
        page: {
          ...list.page,
          number: page,
          size,
          item_from: (page - 1) * size + 1,
          item_to: (page - 1) * size + list.items.length,
          has_previous: page > 1,
          has_next: list.page.total_pages === null ? page < 2 : page < list.page.total_pages,
        },
      }))
    }
    if (url.startsWith('/api/v1/instances/')) return Promise.resolve(json(detail))
    throw new Error(`Unexpected request: ${method} ${url}`)
  })
}

function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init })
}

describe('session and scope flow', () => {
  beforeEach(() => {
    resetCsrfForTest()
    vi.stubGlobal('scrollTo', vi.fn())
    window.history.replaceState({}, '', '/')
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows login when no session exists', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'expired' }, { status: 401 })))
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Sign in to your cloud' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
  })

  it('recovers from an initial request timeout', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal
        signal?.addEventListener('abort', () => reject(signal.reason), { once: true })
      })
    )))

    render(<App />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })

    expect(screen.getByRole('heading', { name: 'Sign in to your cloud' })).toBeInTheDocument()
    expect(screen.getByText('Unable to restore the session')).toBeInTheDocument()
  })

  it('shows project loading separately from a confirmed empty result', async () => {
    let resolveProjects: (response: Response) => void = () => undefined
    const pendingProjects = new Promise<Response>((resolve) => {
      resolveProjects = resolve
    })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(session))
      .mockReturnValueOnce(pendingProjects)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    expect(await screen.findByText('Loading projects...')).toBeInTheDocument()
    expect(screen.queryByText('No accessible projects found.')).not.toBeInTheDocument()

    resolveProjects(json({
      items: [],
      page: { ...projectPage.page, item_from: 0, item_to: 0, total_items: 0, total_pages: 0, navigable_pages: [] },
    }))
    expect(await screen.findByText('No accessible projects found.')).toBeInTheDocument()
  })

  it('returns to the original safe URL after login and scope selection', async () => {
    window.history.replaceState({}, '', '/overview?panel=quota#usage')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ detail: 'expired' }, { status: 401 }))
      .mockResolvedValueOnce(json(session, {
        status: 201,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-login' },
      }))
      .mockResolvedValueOnce(json(projectPage))
      .mockResolvedValueOnce(json(scopedSession))
      .mockResolvedValueOnce(json(overviewPayload))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('heading', { name: 'Sign in to your cloud' })
    expect(window.history.state).toEqual({ returnTo: '/overview?panel=quota#usage' })
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'vantage' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in to your cloud' }))

    await screen.findByRole('button', { name: 'Continue to project' })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    fireEvent.click(screen.getByRole('button', { name: 'Continue to project' }))

    await screen.findByRole('heading', { name: 'Alpha' })
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`)
      .toBe('/overview?panel=quota#usage')
  })

  it('marks credentials invalid and clears the password after a 401', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ detail: 'expired' }, { status: 401 }))
      .mockResolvedValueOnce(json({
        detail: 'The supplied credentials are invalid',
        code: 'invalid_credentials',
        trace_id: 'trace-login',
      }, { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    const username = await screen.findByLabelText('Username')
    const password = screen.getByLabelText('Password')
    fireEvent.change(username, { target: { value: 'alice' } })
    fireEvent.change(password, { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in to your cloud' }))

    expect(await screen.findByText('The supplied credentials are invalid')).toBeInTheDocument()
    expect(username).toHaveAttribute('aria-invalid', 'true')
    expect(password).toHaveAttribute('aria-invalid', 'true')
    expect(password).toHaveValue('')
  })

  it('selects a project using the CSRF response header', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(session, { headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-value' } }))
      .mockResolvedValueOnce(json(projectPage))
      .mockResolvedValueOnce(json({ ...session, active_scope: { project: projects[0], region: 'RegionOne' } }))
      .mockResolvedValueOnce(json(overviewPayload))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await screen.findByRole('button', { name: 'Continue to project' })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByRole('button', { name: 'Continue to project' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Alpha' })).toBeInTheDocument())
    expect(window.location.pathname).toBe('/overview')
    const options = fetchMock.mock.calls[2][1] as RequestInit
    expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('csrf-value')
  })

  it('uses numbered server pages and resets page one when the page size changes', async () => {
    const firstPage = {
      ...projectPage,
      page: {
        ...projectPage.page,
        total_items: 26,
        total_pages: 2,
        has_next: true,
        navigable_pages: [1, 2],
      },
    }
    const secondPage = {
      ...projectPage,
      page: {
        ...firstPage.page,
        number: 2,
        item_from: 26,
        item_to: 26,
        has_previous: true,
        has_next: false,
      },
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(json(firstPage))
      .mockResolvedValueOnce(json(secondPage))
      .mockResolvedValueOnce(json({ ...projectPage, page: { ...projectPage.page, size: 50 } }))
      .mockResolvedValue(json(projectPage))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('button', { name: 'Page 2' })
    const pageSize = screen.getByLabelText('Rows per page')
    expect(within(pageSize).getAllByRole('option').map((option) => option.textContent))
      .toEqual(['10', '25', '50', '100'])
    fireEvent.click(screen.getByRole('button', { name: 'Page 2' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/projects?limit=25&page=2')

    fireEvent.change(pageSize, { target: { value: '50' } })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
    expect(fetchMock.mock.calls[3][0]).toBe('/api/v1/projects?limit=50&page=1')

    fireEvent.change(pageSize, { target: { value: '10' } })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5))
    expect(fetchMock.mock.calls[4][0]).toBe('/api/v1/projects?limit=10&page=1')

    fireEvent.change(pageSize, { target: { value: '100' } })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6))
    expect(fetchMock.mock.calls[5][0]).toBe('/api/v1/projects?limit=100&page=1')
  })

  it('clears the CSRF token and explains an expired scoped session', async () => {
    const expired = {
      detail: 'Session missing or expired',
      code: 'unauthenticated',
      trace_id: 'trace-expired',
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(session, {
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'stale-csrf' },
      }))
      .mockResolvedValueOnce(json(projectPage))
      .mockResolvedValueOnce(json(expired, { status: 401 }))
      .mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(json(projectPage))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('button', { name: 'Continue to project' })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByRole('button', { name: 'Continue to project' }))

    expect(await screen.findByRole('dialog', { name: 'Session expired' })).toBeInTheDocument()
    expect(screen.getByText('Your session expired. Sign in again.')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/overview')
    expect(window.history.state).toEqual({ reauthGuard: true, returnTo: '/overview' })
    expect(screen.getByLabelText('Username')).toHaveFocus()
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'vantage' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in to your cloud' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5))
    const loginOptions = fetchMock.mock.calls[3][1] as RequestInit
    expect(new Headers(loginOptions.headers).get('X-CSRF-Token')).toBeNull()
  })

  it('keeps the active screen visible when sign-out fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(scopedSession))
      .mockResolvedValueOnce(json(overviewPayload))
      .mockRejectedValueOnce(new TypeError('offline'))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('heading', { name: 'Alpha' })
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await screen.findByText('Unable to sign out. Your session is still active.')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/overview')
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled()
  })

  it('keeps the project selector open while changing language', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(scopedSession, {
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-value' },
      }))
      .mockResolvedValueOnce(json(overviewPayload))
      .mockResolvedValueOnce(json(projectPage))
      .mockResolvedValueOnce(json({ ...scopedSession, locale: 'ko' }, {
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'rotated-csrf' },
      }))
      .mockResolvedValue(json(projectPage))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('heading', { name: 'Alpha' })
    fireEvent.click(screen.getByRole('button', { name: 'Switch project: Alpha, RegionOne' }))
    await screen.findByRole('heading', { name: 'Choose a project' })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'ko' } })

    expect(await screen.findByRole('heading', { name: '프로젝트 선택' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/projects/select')
  })

  it('renders grouped quotas, unlimited capacity, and localized partial failures', async () => {
    const overQuota = quotas.map((quota) => (
      quota.resource === 'cores'
        ? { ...quota, used: 22, reserved: 3, limit: 20, state: 'high' }
        : quota
    ))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(scopedSession))
      .mockResolvedValueOnce(json({
        ...overviewPayload,
        quotas: overQuota,
        partial_errors: [{
          code: 'network_quota_timeout',
          message: 'Raw backend English must not be primary copy',
          openstack_request_id: 'req-network-1',
        }],
      }))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Quota usage' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Compute' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Network' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Storage' })).toBeInTheDocument()
    expect(screen.getByText(/Unlimited/)).toBeInTheDocument()
    expect(screen.getAllByText('10,240 MiB')).toHaveLength(2)
    expect(screen.getByText('Network quota request timed out.')).toBeInTheDocument()
    expect(screen.queryByText('Raw backend English must not be primary copy')).not.toBeInTheDocument()
    expect(screen.getByText(/req-network-1/)).toBeInTheDocument()

    const progress = screen.getByRole('progressbar', { name: /vCPUs/ })
    expect(progress).toHaveAttribute('aria-valuemax', '20')
    expect(progress).toHaveAttribute('aria-valuenow', '20')
    expect(progress.parentElement).toHaveTextContent(/22.*3.*20/)
  })

  it('navigates and filters quota details without losing the filter on language change', async () => {
    const computePayload = {
      ...quotaPayload,
      quotas: quotas.filter((quota) => quota.service === 'compute'),
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(scopedSession))
      .mockResolvedValueOnce(json(overviewPayload))
      .mockResolvedValueOnce(json(quotaPayload))
      .mockResolvedValueOnce(json(computePayload))
      .mockResolvedValueOnce(json({ ...scopedSession, locale: 'ko' }))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('heading', { name: 'Quota usage' })
    const scrollToMock = vi.mocked(window.scrollTo)
    scrollToMock.mockClear()
    fireEvent.click(screen.getByRole('link', { name: 'Quotas' }))

    const table = await screen.findByRole('table', { name: 'Quotas' })
    expect(window.location.pathname).toBe('/quotas')
    expect(scrollToMock).toHaveBeenCalledWith({ top: 0, left: 0 })
    const dataRows = within(table).getAllByRole('row').slice(1)
    expect(dataRows[0].querySelectorAll('[data-label]')).toHaveLength(6)

    fireEvent.click(screen.getByRole('tab', { name: 'Compute' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/quotas?service=compute',
      expect.any(Object),
    ))
    await waitFor(() => expect(screen.queryByText('Floating IPs')).not.toBeInTheDocument())
    expect(window.location.href).toContain('/quotas?service=compute')

    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'ko' } })
    expect(await screen.findByRole('tab', { name: '컴퓨트' })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByRole('table', { name: '쿼터' })).toHaveTextContent('인스턴스')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5))
    expect(screen.queryByText('컴퓨트 쿼터 요청이 일시적으로 제한되었습니다.')).not.toBeInTheDocument()
    expect(`${window.location.pathname}${window.location.search}`).toBe('/quotas?service=compute')
  })

  it('merges partial refreshes, marks rejected refreshes stale, and cleans up polling', async () => {
    let intervalHandler: (() => void) | undefined
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockImplementation((handler, timeout) => {
      if (timeout === 30_000 && typeof handler === 'function') intervalHandler = handler as () => void
      return 41
    })
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')
    const partialRefresh = {
      ...overviewPayload,
      generated_at: '2026-08-02T01:03:03Z',
      quotas: [
        { ...quotas[3], used: 7, reserved: 0 },
        { ...quotas[4], used: 13 },
      ],
      instance_summary: null,
      partial_errors: [{ code: 'compute_quota_timeout', message: 'compute failed' }],
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(scopedSession))
      .mockResolvedValueOnce(json(overviewPayload))
      .mockResolvedValueOnce(json(partialRefresh))
      .mockRejectedValueOnce(new TypeError('offline'))
    vi.stubGlobal('fetch', fetchMock)

    const { unmount } = render(<App />)
    await screen.findByRole('heading', { name: 'Quota usage' })
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 30_000)
    expect(intervalHandler).toBeTypeOf('function')

    act(() => intervalHandler?.())
    expect(await screen.findByText('Compute quota request timed out.')).toBeInTheDocument()
    expect(screen.getByText('Showing the last available data')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Instances' }).closest('article')).toHaveTextContent(/2.*1.*10/)
    expect(screen.getByRole('heading', { name: 'Floating IPs' }).closest('article')).toHaveTextContent(/7.*10/)
    expect(screen.getByText('Total instances').nextElementSibling).toHaveTextContent('2')

    act(() => intervalHandler?.())
    expect(await screen.findByText('Unable to load the project overview')).toBeInTheDocument()
    expect(screen.getByText('Showing the last available data')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Floating IPs' }).closest('article')).toHaveTextContent(/7.*10/)

    const callsBeforeUnmount = fetchMock.mock.calls.length
    unmount()
    expect(clearIntervalSpy).toHaveBeenCalledWith(41)
    act(() => intervalHandler?.())
    window.dispatchEvent(new Event('focus'))
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforeUnmount)
  })

  it('debounces instance text filters and uses bounded server-side pages', async () => {
    window.history.replaceState({}, '', '/instances?page=10')
    const list = {
      ...instancePage,
      page: { ...instancePage.page, navigable_pages: Array.from({ length: 20 }, (_, index) => index + 1) },
    }
    const fetchMock = scopedFetch({ list })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('table', { name: 'Instances' })

    const instanceRequests = () => fetchMock.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.startsWith('/api/v1/instances?'))
    expect(instanceRequests()).toEqual([
      '/api/v1/instances?limit=25&page=10&name=&status=&image_id=&sort=created_at&direction=desc',
    ])
    expect(screen.getByRole('button', { name: 'Page 10' })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('button', { name: 'Page 5' })).not.toBeInTheDocument()
    expect(screen.getAllByText('...')).toHaveLength(2)
    expect(document.querySelector('.page-range')).toHaveTextContent('226-227')
    expect(document.querySelector('.page-range')).not.toHaveTextContent('?')

    const name = screen.getByLabelText('Filter by name')
    const image = screen.getByLabelText('Filter by image ID')
    fireEvent.change(name, { target: { value: 'w' } })
    fireEvent.change(name, { target: { value: 'web' } })
    fireEvent.change(image, { target: { value: 'image-1' } })
    expect(instanceRequests()).toHaveLength(1)

    await waitFor(() => expect(instanceRequests()).toHaveLength(2), { timeout: 1_500 })
    expect(instanceRequests().at(-1)).toBe(
      '/api/v1/instances?limit=25&page=1&name=web&status=&image_id=image-1&sort=created_at&direction=desc',
    )
    expect(`${window.location.pathname}${window.location.search}`).toBe('/instances?name=web&image_id=image-1')

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'ACTIVE' } })
    await waitFor(() => expect(instanceRequests()).toHaveLength(3))
    expect(instanceRequests().at(-1)).toContain('page=1&name=web&status=ACTIVE&image_id=image-1')

    fireEvent.click(await screen.findByRole('button', { name: 'Page 2' }))
    await waitFor(() => expect(instanceRequests()).toHaveLength(4))
    expect(instanceRequests().at(-1)).toContain('limit=25&page=2&name=web&status=ACTIVE')

    const rows = screen.getByLabelText('Rows per page')
    expect(within(rows).getAllByRole('option').map((option) => option.textContent))
      .toEqual(['10', '25', '50', '100'])
    fireEvent.change(rows, { target: { value: '100' } })
    await waitFor(() => expect(instanceRequests()).toHaveLength(5))
    expect(instanceRequests().at(-1)).toContain('limit=100&page=1&name=web&status=ACTIVE')
    expect(screen.queryByText('Prev')).not.toBeInTheDocument()
    expect(screen.queryByText('Next')).not.toBeInTheDocument()
  })

  it.each(['page_cursor_unavailable', 'page_cursor_changed'] as const)(
    'recovers a direct page route from %s without losing its query',
    async (code) => {
      const route = '/instances?limit=50&page=3&name=web&status=ACTIVE&image_id=image-1&sort=name&direction=asc'
      window.history.replaceState({}, '', route)
      const requests: string[] = []
      const fetchMock = vi.fn((input: string | URL | Request) => {
        const url = String(input)
        if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
        if (url.startsWith('/api/v1/instances?')) {
          requests.push(url)
          if (requests.length === 1) {
            return Promise.resolve(json({
              detail: 'Raw cursor detail must not be shown',
              code,
              trace_id: `trace-${code}`,
            }, { status: 409 }))
          }
          return Promise.resolve(json({
            ...instancePage,
            page: { ...instancePage.page, size: 50, has_next: false, navigable_pages: [1] },
          }))
        }
        throw new Error(`Unexpected request: ${url}`)
      })
      vi.stubGlobal('fetch', fetchMock)

      render(<App />)

      expect(await screen.findByRole('table', { name: 'Instances' })).toBeInTheDocument()
      expect(requests).toEqual([
        '/api/v1/instances?limit=50&page=3&name=web&status=ACTIVE&image_id=image-1&sort=name&direction=asc',
        '/api/v1/instances?limit=50&page=1&name=web&status=ACTIVE&image_id=image-1&sort=name&direction=asc',
      ])
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        '/instances?limit=50&name=web&status=ACTIVE&image_id=image-1&sort=name&direction=asc',
      )
      expect(screen.queryByText('Raw cursor detail must not be shown')).not.toBeInTheDocument()
    },
  )

  it.each([
    [403, 'instances_forbidden', 'You do not have permission to view instances in this project.'],
    [404, 'instances_not_found', 'The instance list is unavailable for this project.'],
  ] as const)(
    'clears a previously loaded instance list after a %s response',
    async (status, code, expectedMessage) => {
      window.history.replaceState({}, '', '/instances')
      let listCalls = 0
      const fetchMock = vi.fn((input: string | URL | Request) => {
        const url = String(input)
        if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
        if (url.startsWith('/api/v1/instances?')) {
          listCalls += 1
          if (listCalls === 1) return Promise.resolve(json(instancePage))
          return Promise.resolve(json({
            detail: 'Raw backend list detail must not be shown',
            code,
            trace_id: `trace-list-${status}`,
            openstack_request_id: `req-list-${status}`,
          }, { status }))
        }
        throw new Error(`Unexpected request: ${url}`)
      })
      vi.stubGlobal('fetch', fetchMock)

      render(<App />)
      expect(await screen.findByText('web-01')).toBeInTheDocument()

      act(() => window.dispatchEvent(new Event('focus')))

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(expectedMessage)
      expect(alert).toHaveTextContent(`OpenStack req-list-${status}`)
      expect(alert).toHaveTextContent(`Vantage trace-list-${status}`)
      expect(screen.queryByText('Raw backend list detail must not be shown')).not.toBeInTheDocument()
      expect(screen.queryByRole('table', { name: 'Instances' })).not.toBeInTheDocument()
      expect(screen.queryByText('web-01')).not.toBeInTheDocument()
      expect(screen.queryByText('req-list-1')).not.toBeInTheDocument()
    },
  )

  it.each([
    ['active_scope_required', 409, 'Select a project and region before viewing instances.'],
    ['invalid_request', 422, 'The instance request is invalid.'],
    ['invalid_page_size', 422, 'The selected page size is not supported.'],
    ['invalid_instance_filter', 422, 'One or more instance filters are invalid.'],
    ['instance_rate_limited', 429, 'Instance data is temporarily rate limited. Try again shortly.'],
    ['instance_unavailable', 503, 'The compute service is temporarily unavailable.'],
    ['instance_timeout', 504, 'The compute service did not respond in time.'],
  ] as const)(
    'maps the expected %s problem to localized copy and preserves references',
    async (code, status, expectedMessage) => {
      window.history.replaceState({}, '', '/instances')
      vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
        const url = String(input)
        if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
        if (url.startsWith('/api/v1/instances?')) {
          return Promise.resolve(json({
            detail: 'Raw backend problem detail must not be shown',
            code,
            trace_id: `trace-${code}`,
            openstack_request_id: `req-${code}`,
          }, { status }))
        }
        throw new Error(`Unexpected request: ${url}`)
      }))

      render(<App />)

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(expectedMessage)
      expect(alert).toHaveTextContent(`OpenStack req-${code}`)
      expect(alert).toHaveTextContent(`Vantage trace-${code}`)
      expect(screen.queryByText('Raw backend problem detail must not be shown')).not.toBeInTheDocument()
    },
  )

  it('opens a routed instance drawer with live network and storage data', async () => {
    window.history.replaceState({}, '', '/instances?page=2&status=ACTIVE')
    const fetchMock = scopedFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    const opener = await screen.findByRole('button', { name: 'Open instance details: web-01' })
    vi.spyOn(window, 'scrollX', 'get').mockReturnValue(23)
    vi.spyOn(window, 'scrollY', 'get').mockReturnValue(517)
    const scrollToMock = vi.mocked(window.scrollTo)
    scrollToMock.mockClear()
    fireEvent.click(opener)

    let dialog = await screen.findByRole('dialog', { name: 'web-01' })
    expect(scrollToMock).not.toHaveBeenCalled()
    expect(document.body.style.overflow).toBe('hidden')
    expect(`${window.location.pathname}${window.location.search}`).toBe(
      `/instances/${server.id}?page=2&status=ACTIVE`,
    )
    const tabs = within(dialog).getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent))
      .toEqual(['Overview', 'Network', 'Storage'])
    expect(within(dialog).getAllByRole('tabpanel', { hidden: true })).toHaveLength(3)
    for (const tab of tabs) {
      expect(document.getElementById(tab.getAttribute('aria-controls')!)).toBeInTheDocument()
    }
    const [overviewTab, networkTab, storageTab] = tabs
    expect(overviewTab).toHaveAttribute('tabindex', '0')
    expect(networkTab).toHaveAttribute('tabindex', '-1')
    expect(storageTab).toHaveAttribute('tabindex', '-1')

    overviewTab.focus()
    fireEvent.keyDown(overviewTab, { key: 'ArrowLeft' })
    expect(storageTab).toHaveFocus()
    expect(storageTab).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(storageTab, { key: 'Home' })
    expect(overviewTab).toHaveFocus()
    fireEvent.keyDown(overviewTab, { key: 'End' })
    expect(storageTab).toHaveFocus()
    fireEvent.keyDown(storageTab, { key: 'ArrowRight' })
    expect(overviewTab).toHaveFocus()
    fireEvent.keyDown(overviewTab, { key: 'ArrowRight' })
    expect(networkTab).toHaveFocus()
    fireEvent.keyDown(networkTab, { key: 'ArrowLeft' })
    expect(overviewTab).toHaveFocus()
    expect(within(dialog).queryByText('Events')).not.toBeInTheDocument()
    expect(within(dialog).queryByLabelText('Rows per page')).not.toBeInTheDocument()

    fireEvent.click(networkTab)
    expect(within(dialog).getByRole('tabpanel')).toHaveTextContent('private=10.0.0.10')
    fireEvent.click(storageTab)
    expect(within(dialog).getByRole('tabpanel')).toHaveTextContent('volume-01')
    expect(within(dialog).getByRole('tabpanel')).toHaveTextContent('/dev/vdb')
    expect(within(dialog).getByRole('tabpanel')).toHaveTextContent('volume-02')
    expect(within(dialog).getByRole('tabpanel')).toHaveTextContent('Not available')

    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(`${window.location.pathname}${window.location.search}`).toBe('/instances?page=2&status=ACTIVE')
    await waitFor(() => expect(opener).toHaveFocus())
    expect(scrollToMock).toHaveBeenLastCalledWith({ left: 23, top: 517 })
    expect(document.body.style.overflow).toBe('')

    fireEvent.click(opener)
    await screen.findByRole('dialog', { name: 'web-01' })
    act(() => window.history.back())
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    fireEvent.click(opener)
    dialog = await screen.findByRole('dialog', { name: 'web-01' })
    fireEvent.mouseDown(dialog.parentElement!)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it.each([
    [403, 'instance_forbidden', '이 인스턴스를 볼 권한이 없습니다.'],
    [404, 'instance_not_found', '활성 프로젝트에 이 인스턴스가 더 이상 존재하지 않습니다.'],
  ] as const)(
    'clears previously loaded instance details after a %s response',
    async (status, code, expectedMessage) => {
      window.history.replaceState({}, '', '/instances')
      let detailCalls = 0
      const fetchMock = vi.fn((input: string | URL | Request) => {
        const url = String(input)
        if (url === '/api/v1/session') {
          return Promise.resolve(json({ ...scopedSession, locale: 'ko' }))
        }
        if (url.startsWith('/api/v1/instances?')) return Promise.resolve(json(instancePage))
        if (url.startsWith('/api/v1/instances/')) {
          detailCalls += 1
          if (detailCalls === 1) return Promise.resolve(json(serverDetail))
          return Promise.resolve(json({
            detail: 'Raw backend detail must not be shown',
            code,
            trace_id: `trace-detail-${status}`,
            openstack_request_id: `req-detail-${status}`,
          }, { status }))
        }
        throw new Error(`Unexpected request: ${url}`)
      })
      vi.stubGlobal('fetch', fetchMock)

      render(<App />)
      const opener = await screen.findByRole('button', { name: '인스턴스 상세 열기: web-01' })
      fireEvent.click(opener)
      const dialog = await screen.findByRole('dialog', { name: 'web-01' })
      expect(within(dialog).getByText('m1.small')).toBeInTheDocument()

      act(() => window.dispatchEvent(new Event('focus')))

      const alert = await within(dialog).findByRole('alert')
      expect(alert).toHaveTextContent(expectedMessage)
      expect(alert).toHaveTextContent(`OpenStack req-detail-${status}`)
      expect(alert).toHaveTextContent(`Vantage trace-detail-${status}`)
      expect(within(dialog).queryByText('Raw backend detail must not be shown')).not.toBeInTheDocument()
      expect(within(dialog).queryByText('web-01')).not.toBeInTheDocument()
      expect(within(dialog).queryByText('m1.small')).not.toBeInTheDocument()
      expect(within(dialog).queryByRole('tab')).not.toBeInTheDocument()
      expect(dialog).toHaveAccessibleName('인스턴스 상세')
    },
  )

  it('handles direct detail URLs and distinguishes unavailable from empty values', async () => {
    const unknownDetail: InstanceDetail = { ...unknownServer, volumes: null }
    const emptyAddressServer = {
      ...server,
      id: '33333333-3333-4333-8333-333333333333',
      name: 'empty-addresses',
      addresses: [],
    }
    const list: InstancePage = {
      items: [unknownServer, emptyAddressServer],
      page: { ...instancePage.page, has_next: false, navigable_pages: [1] },
    }
    window.history.replaceState({}, '', `/instances/${unknownServer.id}?name=unknown`)
    vi.stubGlobal('fetch', scopedFetch({ list, detail: unknownDetail }))

    render(<App />)
    const dialog = await screen.findByRole('dialog', { name: unknownServer.id })
    expect(await screen.findByRole('button', {
      name: `Open instance details: ${unknownServer.id}`,
    })).toBeInTheDocument()
    expect(screen.getByText('No addresses')).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole('tab', { name: 'Network' }))
    let panel = within(dialog).getByRole('tabpanel')
    expect(panel).toHaveTextContent('Not available')
    expect(panel).not.toHaveTextContent('No addresses')
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Storage' }))
    panel = within(dialog).getByRole('tabpanel')
    expect(panel).toHaveTextContent('Not available')
    expect(panel).not.toHaveTextContent('No attached volumes')

    fireEvent.click(within(dialog).getByRole('button', { name: 'Close instance details' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(`${window.location.pathname}${window.location.search}`).toBe('/instances?name=unknown')
  })

  it('localizes the instance route without losing filters or refetching the list', async () => {
    const route = '/instances?limit=50&page=2&status=ACTIVE&sort=name&direction=asc'
    window.history.replaceState({}, '', route)
    const fetchMock = scopedFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('heading', { name: 'Instances', level: 1 })
    const requestsBefore = fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/v1/instances?')).length
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'ko' } })

    expect(await screen.findByRole('heading', { name: '인스턴스', level: 1 })).toBeInTheDocument()
    expect(screen.getByLabelText('이름으로 필터')).toBeInTheDocument()
    expect(screen.getByLabelText('페이지당 행')).toHaveValue('50')
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/session', expect.objectContaining({ method: 'PATCH' })))
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/v1/instances?'))).toHaveLength(requestsBefore)
  })

  it('aborts a superseded Nova list request after the debounced query changes', async () => {
    window.history.replaceState({}, '', '/instances')
    let firstSignal: AbortSignal | undefined
    let listCalls = 0
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
      if (url.startsWith('/api/v1/instances?')) {
        listCalls += 1
        if (listCalls === 1) {
          firstSignal = init?.signal ?? undefined
          return new Promise<Response>((_resolve, reject) => {
            firstSignal?.addEventListener('abort', () => {
              reject(new DOMException('Aborted', 'AbortError'))
            }, { once: true })
          })
        }
        return Promise.resolve(json(instancePage))
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    const name = await screen.findByLabelText('Filter by name')
    fireEvent.change(name, { target: { value: 'a' } })
    fireEvent.change(name, { target: { value: 'api' } })

    await waitFor(() => expect(listCalls).toBe(2), { timeout: 1_500 })
    expect(firstSignal?.aborted).toBe(true)
    expect(await screen.findByRole('table', { name: 'Instances' })).toBeInTheDocument()
    const lastUrl = String(fetchMock.mock.calls.at(-1)?.[0])
    expect(lastUrl).toContain('page=1&name=api&status=&image_id=')
  })

  it('reauthenticates on an instance-list 401 while preserving the route', async () => {
    const route = '/instances?status=ACTIVE'
    window.history.replaceState({}, '', route)
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
      if (url.startsWith('/api/v1/instances?')) {
        return Promise.resolve(json({
          detail: 'Session missing or expired',
          code: 'unauthenticated',
          trace_id: 'trace-instances-expired',
        }, { status: 401 }))
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    expect(await screen.findByRole('dialog', { name: 'Session expired' })).toBeInTheDocument()
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)
    expect(screen.queryByRole('table', { name: 'Instances' })).not.toBeInTheDocument()
  })

  it('drops prior-project rows and recovers a missing cursor after a project switch', async () => {
    window.history.replaceState({}, '', '/instances?limit=50&page=2&status=ACTIVE&sort=name&direction=asc')
    const betaProject = { id: 'project-beta', name: 'Beta', enabled: true }
    const betaSession = {
      ...scopedSession,
      active_scope: { project: betaProject, region: 'RegionOne' },
    }
    const betaServer = {
      ...server,
      id: '44444444-4444-4444-8444-444444444444',
      name: 'db-beta',
    }
    const betaPage: InstancePage = {
      items: [betaServer],
      page: { ...instancePage.page, size: 50, item_to: 1, has_next: false, navigable_pages: [1] },
    }
    const projectsWithBeta = {
      items: [projects[0], betaProject],
      page: { ...projectPage.page, item_to: 2, total_items: 2 },
    }
    let currentProject = 'project-alpha'
    const betaRequests: string[] = []
    let resolveBeta: (response: Response) => void = () => undefined
    const pendingBeta = new Promise<Response>((resolve) => { resolveBeta = resolve })
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
      if (url.startsWith('/api/v1/instances?')) {
        if (currentProject === 'project-alpha') {
          return Promise.resolve(json({
            ...instancePage,
            page: {
              ...instancePage.page,
              number: 2,
              size: 50,
              item_from: 51,
              item_to: 52,
              has_previous: true,
            },
          }))
        }
        betaRequests.push(url)
        if (betaRequests.length === 1) {
          return Promise.resolve(json({
            detail: 'Open page 1 first',
            code: 'page_cursor_unavailable',
            trace_id: 'trace-beta-cursor',
          }, { status: 409 }))
        }
        return pendingBeta
      }
      if (url.startsWith('/api/v1/instances/')) return Promise.resolve(json(serverDetail))
      if (url.startsWith('/api/v1/projects?')) return Promise.resolve(json(projectsWithBeta))
      if (url === '/api/v1/scope' && init?.method === 'PUT') {
        currentProject = 'project-beta'
        return Promise.resolve(json(betaSession))
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    const opener = await screen.findByRole('button', { name: 'Open instance details: web-01' })
    fireEvent.click(opener)
    await screen.findByRole('dialog', { name: 'web-01' })
    expect(window.location.pathname).toBe(`/instances/${server.id}`)
    fireEvent.click(screen.getByRole('button', { name: 'Switch project: Alpha, RegionOne' }))
    const beta = await screen.findByRole('radio', { name: /Beta/ })
    fireEvent.click(beta)
    fireEvent.click(screen.getByRole('button', { name: 'Continue to project' }))

    await waitFor(() => expect(betaRequests).toHaveLength(2))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('web-01')).not.toBeInTheDocument()
    resolveBeta(json(betaPage))
    expect(await screen.findByText('db-beta')).toBeInTheDocument()
    expect(screen.queryByText('web-01')).not.toBeInTheDocument()
    expect(betaRequests).toEqual([
      '/api/v1/instances?limit=50&page=2&name=&status=ACTIVE&image_id=&sort=name&direction=asc',
      '/api/v1/instances?limit=50&page=1&name=&status=ACTIVE&image_id=&sort=name&direction=asc',
    ])
    expect(`${window.location.pathname}${window.location.search}`).toBe(
      '/instances?limit=50&status=ACTIVE&sort=name&direction=asc',
    )
  })

  it('renders the separate image route, filters it, and uses shared numbered pagination', async () => {
    window.history.replaceState({}, '', '/images?limit=50&page=2&name=ubuntu&visibility=public')
    const requests: string[] = []
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
      if (url.startsWith('/api/v1/images?')) {
        requests.push(url)
        const parameters = new URL(url, 'http://local').searchParams
        const page = Number(parameters.get('page'))
        return Promise.resolve(json({
          ...imagePage,
          page: { ...imagePage.page, number: page, size: Number(parameters.get('limit')),
            has_previous: page > 1, has_next: page < 2 },
        }))
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    expect(await screen.findByRole('table', { name: 'Images' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Images' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Key pairs' })).toHaveAttribute('href', '/keypairs')
    expect(screen.getByText('qcow2 / bare')).toBeInTheDocument()
    expect(screen.getByText('2 GiB')).toBeInTheDocument()
    expect(screen.getByText('20 GiB disk / 2,048 MiB RAM')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Visibility'), { target: { value: 'private' } })
    await waitFor(() => expect(requests.at(-1)).toBe(
      '/api/v1/images?limit=50&page=1&name=ubuntu&visibility=private',
    ))
    fireEvent.change(screen.getByLabelText('Filter by name'), { target: { value: 'debian' } })
    await waitFor(() => expect(requests.at(-1)).toBe(
      '/api/v1/images?limit=50&page=1&name=debian&visibility=private',
    ), { timeout: 1_500 })
    expect(`${window.location.pathname}${window.location.search}`).toBe(
      '/images?limit=50&name=debian&visibility=private',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Page 2' }))
    await waitFor(() => expect(requests.at(-1)).toContain('page=2&name=debian&visibility=private'))
    expect(window.location.search).toContain('page=2')
  })

  it('renders key pairs on their own route and localizes without losing query state', async () => {
    const route = '/keypairs?limit=10'
    window.history.replaceState({}, '', route)
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/v1/session' && !init?.method) return Promise.resolve(json(scopedSession))
      if (url === '/api/v1/session' && init?.method === 'PATCH') {
        return Promise.resolve(json({ ...scopedSession, locale: 'ko' }))
      }
      if (url.startsWith('/api/v1/keypairs?')) return Promise.resolve(json(keyPairPage))
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    expect(await screen.findByRole('table', { name: 'Key pairs' })).toBeInTheDocument()
    expect(screen.getByText('SHA256:abc123')).toBeInTheDocument()
    expect(screen.getByText('ssh-ed25519 AAAAC3...')).toBeInTheDocument()
    const callsBefore = fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/v1/keypairs?')).length
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'ko' } })
    expect(await screen.findByRole('heading', { name: '키 페어' })).toBeInTheDocument()
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/v1/keypairs?'))).toHaveLength(callsBefore)
    fireEvent.click(screen.getByRole('button', { name: '가져오기 또는 생성' }))
    const dialog = await screen.findByRole('dialog', { name: '키 페어 추가' })
    expect(within(dialog).getByRole('button', { name: '생성' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '가져오기' })).toBeInTheDocument()
    expect(within(dialog).getByLabelText('키 유형')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '닫기' }))
  })

  it('generates a key pair once, blocks duplicate submission, copies the private key, and refreshes in place', async () => {
    const route = '/keypairs?limit=10&page=2'
    const privateMaterial = '-----BEGIN PRIVATE KEY-----\none-time-secret\n-----END PRIVATE KEY-----'
    const writeText = vi.fn().mockResolvedValue(undefined)
    let listCalls = 0
    let resolveCreate: ((response: Response) => void) | undefined
    window.history.replaceState({}, '', route)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/session' && method === 'GET') {
        return Promise.resolve(json(scopedSession, {
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-keypairs' },
        }))
      }
      if (url.startsWith('/api/v1/keypairs?') && method === 'GET') {
        listCalls += 1
        return Promise.resolve(json(keyPairPage))
      }
      if (url === '/api/v1/keypairs' && method === 'POST') {
        return new Promise<Response>((resolve) => { resolveCreate = resolve })
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('table', { name: 'Key pairs' })
    fireEvent.click(screen.getByRole('button', { name: 'Import or generate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a key pair' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'generated-key' } })
    const submit = within(dialog).getByRole('button', { name: 'Generate key pair' })
    fireEvent.click(submit)
    fireEvent.click(submit)

    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
    expect(within(dialog).getByRole('button', { name: 'Generating...' })).toBeDisabled()
    const createCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    const createOptions = createCall?.[1] as RequestInit
    const createHeaders = new Headers(createOptions.headers)
    expect(createHeaders.get('X-CSRF-Token')).toBe('csrf-keypairs')
    expect(createHeaders.get('Idempotency-Key')).toMatch(UUID_V4)
    expect(JSON.parse(String(createOptions.body))).toEqual({
      name: 'generated-key', type: 'ssh', mode: 'generate',
    })

    await act(async () => {
      resolveCreate?.(json({ keypair: keyPairPage.items[0], private_key: privateMaterial }, { status: 201 }))
    })
    const privateKey = await screen.findByRole('textbox', { name: 'Private key' })
    expect(privateKey).toHaveValue(privateMaterial)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Copy private key' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(privateMaterial))
    expect(within(dialog).getByRole('button', { name: 'Copied' })).toBeInTheDocument()
    await waitFor(() => expect(listCalls).toBe(2))
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)

    fireEvent.click(within(dialog).getByRole('button', { name: 'Done' }))
    expect(screen.queryByRole('dialog', { name: 'Add a key pair' })).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue(privateMaterial)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Import or generate' }))
    const reopened = await screen.findByRole('dialog', { name: 'Add a key pair' })
    expect(within(reopened).queryByRole('textbox', { name: 'Private key' })).not.toBeInTheDocument()
  })

  it('imports an X.509 key pair with request references and refreshes the same query', async () => {
    const route = '/keypairs?limit=50&page=3'
    let listCalls = 0
    window.history.replaceState({}, '', route)
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/session' && method === 'GET') {
        return Promise.resolve(json(scopedSession, {
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-import' },
        }))
      }
      if (url.startsWith('/api/v1/keypairs?') && method === 'GET') {
        listCalls += 1
        return Promise.resolve(json(keyPairPage))
      }
      if (url === '/api/v1/keypairs' && method === 'POST') {
        return Promise.resolve(json({
          ...acceptedOperation,
          trace_id: 'trace-import',
          openstack_request_ids: ['req-import'],
        }, { status: 202 }))
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('table', { name: 'Key pairs' })
    fireEvent.click(screen.getByRole('button', { name: 'Import or generate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a key pair' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Import' }))
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'client-cert' } })
    fireEvent.change(within(dialog).getByLabelText('Key type'), { target: { value: 'x509' } })
    fireEvent.change(within(dialog).getByLabelText('X.509 certificate'), {
      target: { value: '  -----BEGIN CERTIFICATE-----\ncertificate\n-----END CERTIFICATE-----  ' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Import key pair' }))

    expect(await screen.findByText('Key pair import requested.')).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Add a key pair' })).not.toBeInTheDocument()
    const createCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    const createOptions = createCall?.[1] as RequestInit
    const createHeaders = new Headers(createOptions.headers)
    expect(createHeaders.get('X-CSRF-Token')).toBe('csrf-import')
    expect(createHeaders.get('Idempotency-Key')).toMatch(UUID_V4)
    expect(JSON.parse(String(createOptions.body))).toEqual({
      name: 'client-cert',
      type: 'x509',
      mode: 'import',
      public_key: '-----BEGIN CERTIFICATE-----\ncertificate\n-----END CERTIFICATE-----',
    })
    expect(screen.getByText(/OpenStack req-import/)).toHaveTextContent('Vantage trace-import')
    await waitFor(() => expect(listCalls).toBe(2))
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)
  })

  it('requires the exact name, encodes deletion paths, blocks duplicates, and refreshes in place', async () => {
    const route = '/keypairs?limit=100&page=2'
    const keypairName = 'ops/key + cert'
    const page = { ...keyPairPage, items: [{ ...keyPairPage.items[0], name: keypairName }] }
    let listCalls = 0
    let resolveDelete: ((response: Response) => void) | undefined
    window.history.replaceState({}, '', route)
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/session' && method === 'GET') {
        return Promise.resolve(json(scopedSession, {
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-delete' },
        }))
      }
      if (url.startsWith('/api/v1/keypairs?') && method === 'GET') {
        listCalls += 1
        return Promise.resolve(json(page))
      }
      if (method === 'DELETE') return new Promise<Response>((resolve) => { resolveDelete = resolve })
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByText(keypairName)
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete key pair' })
    const deleteButton = within(dialog).getByRole('button', { name: 'Delete' })
    expect(deleteButton).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Type the key pair name to confirm'), {
      target: { value: 'ops/key' },
    })
    expect(deleteButton).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Type the key pair name to confirm'), {
      target: { value: keypairName },
    })
    expect(deleteButton).toBeEnabled()
    fireEvent.click(deleteButton)
    fireEvent.click(deleteButton)

    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(1))
    const deleteCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(String(deleteCall?.[0])).toBe(`/api/v1/keypairs/${encodeURIComponent(keypairName)}`)
    const deleteHeaders = new Headers((deleteCall?.[1] as RequestInit).headers)
    expect(deleteHeaders.get('X-CSRF-Token')).toBe('csrf-delete')
    expect(deleteHeaders.get('Idempotency-Key')).toMatch(UUID_V4)

    await act(async () => {
      resolveDelete?.(json({
        ...acceptedOperation,
        kind: 'keypair.delete',
        trace_id: 'trace-delete',
        openstack_request_ids: ['req-delete'],
      }, { status: 202 }))
    })
    expect(await screen.findByText('Key pair deletion requested.')).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Delete key pair' })).not.toBeInTheDocument()
    expect(screen.getByText(/OpenStack req-delete/)).toHaveTextContent('Vantage trace-delete')
    await waitFor(() => expect(listCalls).toBe(2))
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)
  })

  it.each([
    [403, 'You do not have permission to manage key pairs in this project.'],
    [404, 'The requested key pair is no longer available.'],
    [409, 'A key pair with this name already exists, or the request conflicts with its current state.'],
    [429, 'Too many requests. Wait a moment and try again.'],
    [503, 'The key pair service is temporarily unavailable. Try again shortly.'],
  ] as const)('handles a key-pair mutation %s with safe copy and request references', async (status, message) => {
    let listCalls = 0
    window.history.replaceState({}, '', '/keypairs')
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/session' && method === 'GET') return Promise.resolve(json(scopedSession))
      if (url.startsWith('/api/v1/keypairs?') && method === 'GET') {
        listCalls += 1
        return Promise.resolve(json(keyPairPage))
      }
      if (url === '/api/v1/keypairs' && method === 'POST') return Promise.resolve(json({
        detail: 'raw upstream detail',
        code: `mutation_${status}`,
        trace_id: `trace-${status}`,
        openstack_request_id: `req-${status}`,
      }, { status }))
      throw new Error(`Unexpected request: ${method} ${url}`)
    }))

    render(<App />)
    await screen.findByRole('table', { name: 'Key pairs' })
    fireEvent.click(screen.getByRole('button', { name: 'Import or generate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a key pair' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'conflicting-key' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate key pair' }))

    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent(message)
    expect(alert).toHaveTextContent(`OpenStack req-${status}`)
    expect(alert).toHaveTextContent(`Vantage trace-${status}`)
    expect(alert).not.toHaveTextContent('raw upstream detail')
    expect(within(dialog).getByRole('button', { name: 'Generate key pair' })).toBeEnabled()
    expect(listCalls).toBe(1)
  })

  it('recovers login after a key-pair mutation 401 without changing the route', async () => {
    const route = '/keypairs?limit=50&page=2'
    window.history.replaceState({}, '', route)
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/session' && method === 'GET') {
        return Promise.resolve(json(scopedSession, {
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-expiring' },
        }))
      }
      if (url.startsWith('/api/v1/keypairs?') && method === 'GET') return Promise.resolve(json(keyPairPage))
      if (url === '/api/v1/keypairs' && method === 'POST') return Promise.resolve(json({
        detail: 'expired', code: 'unauthenticated', trace_id: 'trace-mutation-auth',
      }, { status: 401 }))
      throw new Error(`Unexpected request: ${method} ${url}`)
    }))

    render(<App />)
    await screen.findByRole('table', { name: 'Key pairs' })
    fireEvent.click(screen.getByRole('button', { name: 'Import or generate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a key pair' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'expired-key' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate key pair' }))

    expect(await screen.findByRole('dialog', { name: 'Session expired' })).toBeInTheDocument()
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)
  })

  it.each(['page_cursor_unavailable', 'page_cursor_changed'])(
    'recovers image %s conflicts at page one while retaining filters',
    async (code) => {
      window.history.replaceState({}, '', '/images?limit=100&page=3&name=base&visibility=shared')
      const requests: string[] = []
      vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
        const url = String(input)
        if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
        if (url.startsWith('/api/v1/images?')) {
          requests.push(url)
          if (requests.length === 1) return Promise.resolve(json({
            detail: 'raw cursor detail', code, trace_id: 'trace-cursor',
          }, { status: 409 }))
          return Promise.resolve(json(imagePage))
        }
        throw new Error(`Unexpected request: ${url}`)
      }))

      render(<App />)
      expect(await screen.findByRole('table', { name: 'Images' })).toBeInTheDocument()
      expect(requests).toEqual([
        '/api/v1/images?limit=100&page=3&name=base&visibility=shared',
        '/api/v1/images?limit=100&page=1&name=base&visibility=shared',
      ])
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        '/images?limit=100&name=base&visibility=shared',
      )
    },
  )

  it('reauthenticates on a key-pair 401 while preserving its route', async () => {
    const route = '/keypairs?limit=50&page=2'
    window.history.replaceState({}, '', route)
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
      if (url.startsWith('/api/v1/keypairs?')) return Promise.resolve(json({
        detail: 'expired', code: 'unauthenticated', trace_id: 'trace-auth',
      }, { status: 401 }))
      throw new Error(`Unexpected request: ${url}`)
    }))

    render(<App />)
    expect(await screen.findByRole('dialog', { name: 'Session expired' })).toBeInTheDocument()
    expect(`${window.location.pathname}${window.location.search}`).toBe(route)
    expect(screen.queryByRole('table', { name: 'Key pairs' })).not.toBeInTheDocument()
  })

  it.each([403, 404])('clears stale key-pair rows after a %s refresh', async (status) => {
    window.history.replaceState({}, '', '/keypairs')
    let calls = 0
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url === '/api/v1/session') return Promise.resolve(json(scopedSession))
      if (url.startsWith('/api/v1/keypairs?')) {
        calls += 1
        if (calls === 1) return Promise.resolve(json(keyPairPage))
        return Promise.resolve(json({
          detail: 'raw forbidden detail',
          code: status === 403 ? 'keypairs_forbidden' : 'keypairs_not_found',
          trace_id: `trace-${status}`,
        }, { status }))
      }
      throw new Error(`Unexpected request: ${url}`)
    }))

    render(<App />)
    expect(await screen.findByText('ops-key')).toBeInTheDocument()
    act(() => window.dispatchEvent(new Event('focus')))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      status === 403 ? 'You do not have permission to view key pairs' : 'The key pair list is unavailable',
    )
    expect(screen.queryByText('ops-key')).not.toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Key pairs' })).not.toBeInTheDocument()
  })
})
