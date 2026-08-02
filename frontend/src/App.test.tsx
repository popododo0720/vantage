import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { resetCsrfForTest } from './api'

const projects = [{ id: 'project-alpha', name: 'Alpha', enabled: true }]

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
})
