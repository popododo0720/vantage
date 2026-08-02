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

function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init })
}

describe('session and scope flow', () => {
  beforeEach(() => {
    resetCsrfForTest()
    window.history.replaceState({}, '', '/')
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.unstubAllGlobals()
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
      .mockResolvedValueOnce(json(projectPage))
      .mockResolvedValueOnce(json({ ...scopedSession, locale: 'ko' }, {
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'rotated-csrf' },
      }))
      .mockResolvedValue(json(projectPage))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('heading', { name: 'Alpha' })
    fireEvent.click(screen.getByRole('button', { name: /Alpha\s*RegionOne/ }))
    await screen.findByRole('heading', { name: 'Choose a project' })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'ko' } })

    expect(await screen.findByRole('heading', { name: '프로젝트 선택' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/projects/select')
  })
})
