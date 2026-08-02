import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, api } from './api'
import type { ProjectPage, Session } from './types'
import './styles.css'

type Locale = 'en' | 'ko'
type ErrorInfo = { message: string; references?: string[] }
type State =
  | { kind: 'loading' }
  | { kind: 'login'; error?: ErrorInfo }
  | { kind: 'reauth'; error: ErrorInfo; returnTo: string }
  | { kind: 'projects'; session: Session; error?: ErrorInfo }
  | { kind: 'overview'; session: Session; error?: ErrorInfo }
type HistoryMode = 'push' | 'replace' | 'none'

const labels = {
  en: {
    signIn: 'Sign in to your cloud',
    signingIn: 'Signing in...',
    domain: 'Domain',
    username: 'Username',
    password: 'Password',
    loginHelp: 'Use your Keystone credentials. Credentials are used only for authentication.',
    choose: 'Choose a project',
    chooseHelp: 'Select an explicit project and region.',
    search: 'Search projects',
    region: 'Region',
    switching: 'Switching...',
    continue: 'Continue to project',
    loadingProjects: 'Loading projects...',
    empty: 'No accessible projects found.',
    overview: 'Project overview',
    ready: 'Secure session and explicit project scope are active.',
    foundation: 'Foundation ready',
    expires: 'Session expires',
    switch: 'Switch project',
    logout: 'Sign out',
    signingOut: 'Signing out...',
    logoutFailed: 'Unable to sign out. Your session is still active.',
    reauthenticate: 'Session expired',
    reauthenticateHelp: 'Sign in again to continue to your previous page.',
    sessionExpired: 'Your session expired. Sign in again.',
    requestReference: 'Request reference',
    rows: 'Rows per page',
    page: 'Page',
    previousPage: 'Previous page',
    nextPage: 'Next page',
    language: 'Language',
    projects: 'Projects',
  },
  ko: {
    signIn: '클라우드 로그인',
    signingIn: '로그인 중...',
    domain: '도메인',
    username: '사용자 이름',
    password: '비밀번호',
    loginHelp: 'Keystone 계정을 사용합니다. 자격 증명은 인증에만 사용됩니다.',
    choose: '프로젝트 선택',
    chooseHelp: '사용할 프로젝트와 리전을 명시적으로 선택하세요.',
    search: '프로젝트 검색',
    region: '리전',
    switching: '전환 중...',
    continue: '프로젝트로 이동',
    loadingProjects: '프로젝트를 불러오는 중...',
    empty: '접근 가능한 프로젝트가 없습니다.',
    overview: '프로젝트 개요',
    ready: '보안 세션과 명시적 프로젝트 범위가 활성화되었습니다.',
    foundation: '기반 준비 완료',
    expires: '세션 만료',
    switch: '프로젝트 전환',
    logout: '로그아웃',
    signingOut: '로그아웃 중...',
    logoutFailed: '로그아웃할 수 없습니다. 현재 세션은 아직 활성 상태입니다.',
    reauthenticate: '세션 만료',
    reauthenticateHelp: '이전 페이지로 돌아가려면 다시 로그인하세요.',
    sessionExpired: '세션이 만료되었습니다. 다시 로그인하세요.',
    requestReference: '요청 참조',
    rows: '페이지당 행',
    page: '페이지',
    previousPage: '이전 페이지',
    nextPage: '다음 페이지',
    language: '언어',
    projects: '프로젝트',
  },
}
type Labels = typeof labels.en

function nextState(session: Session): State {
  return session.active_scope ? { kind: 'overview', session } : { kind: 'projects', session }
}

function pathForState(state: State): string {
  if (state.kind === 'login') return '/login'
  if (state.kind === 'reauth') return state.returnTo
  if (state.kind === 'projects') return '/projects/select'
  if (state.kind === 'overview') return '/overview'
  return window.location.pathname
}

function safeReturnUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length === 0) return undefined
  const url = new URL(value, window.location.origin)
  if (url.origin !== window.location.origin || url.pathname !== '/overview') return undefined
  return `${url.pathname}${url.search}${url.hash}`
}

function currentUrl(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

function sessionForState(state: State): Session | undefined {
  return state.kind === 'projects' || state.kind === 'overview' ? state.session : undefined
}

function errorInfo(cause: unknown, fallback: string): ErrorInfo {
  if (!(cause instanceof ApiError)) return { message: fallback }
  const references = [
    cause.problem.openstack_request_id && `OpenStack ${cause.problem.openstack_request_id}`,
    cause.problem.trace_id && `Vantage ${cause.problem.trace_id}`,
  ].filter((reference): reference is string => Boolean(reference))
  return {
    message: cause.problem.detail,
    references: references.length > 0 ? references : undefined,
  }
}

export function App() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const stateRef = useRef<State>(state)
  const pendingSafeRoute = useRef(
    safeReturnUrl(window.location.href) ?? safeReturnUrl(window.history.state?.returnTo),
  )
  const [locale, setLocale] = useState<Locale>('en')
  const localeRef = useRef<Locale>(locale)
  const t = labels[locale]

  useEffect(() => {
    localeRef.current = locale
  }, [locale])

  const transition = useCallback((next: State, mode: HistoryMode = 'push', route?: string) => {
    stateRef.current = next
    setState(next)
    if (mode === 'none') return
    const path = route ?? pathForState(next)
    const historyState = pendingSafeRoute.current
      ? { returnTo: pendingSafeRoute.current }
      : {}
    if (currentUrl() === path) {
      window.history.replaceState(historyState, '', path)
      return
    }
    window.history[mode === 'replace' ? 'replaceState' : 'pushState'](historyState, '', path)
  }, [])

  const enterSession = useCallback((session: Session, mode: HistoryMode = 'replace') => {
    const next = nextState(session)
    const returnTo = next.kind === 'overview' ? pendingSafeRoute.current : undefined
    if (returnTo) pendingSafeRoute.current = undefined
    transition(next, mode, returnTo)
  }, [transition])

  useEffect(() => {
    let active = true
    api.session()
      .then((session) => {
        if (!active) return
        setLocale(session.locale)
        enterSession(session)
      })
      .catch((cause) => {
        if (!active) return
        const error = cause instanceof ApiError && cause.status === 401
          ? undefined
          : errorInfo(cause, 'Unable to restore the session')
        transition({ kind: 'login', error }, 'replace')
      })
    return () => { active = false }
  }, [enterSession, transition])

  useEffect(() => {
    function handlePopState() {
      const current = stateRef.current
      if (current.kind === 'loading') return
      if (current.kind === 'reauth') {
        if (!window.history.state?.reauthGuard) window.history.forward()
        return
      }
      const session = sessionForState(current)
      let next: State | undefined
      if (window.location.pathname === '/login' && current.kind === 'login') {
        next = current
      } else if (window.location.pathname === '/projects/select' && session) {
        next = { kind: 'projects', session }
      } else if (window.location.pathname === '/overview' && session?.active_scope) {
        next = { kind: 'overview', session }
      }
      if (next) transition(next, 'none')
      else window.history.replaceState({}, '', pathForState(current))
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [transition])

  const expire = useCallback(() => {
    const returnTo = safeReturnUrl(window.location.href) ?? pendingSafeRoute.current ?? '/overview'
    pendingSafeRoute.current = returnTo
    transition({
      kind: 'reauth',
      error: { message: labels[localeRef.current].sessionExpired },
      returnTo,
    }, 'none')
    window.history.pushState({ reauthGuard: true, returnTo }, '', returnTo)
  }, [transition])

  async function changeLocale(next: Locale) {
    const previous = locale
    setLocale(next)
    if (state.kind !== 'projects' && state.kind !== 'overview') return
    try {
      const session = await api.locale(next)
      transition({ kind: state.kind, session }, 'replace')
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        expire()
        return
      }
      setLocale(previous)
      transition(
        { ...state, error: errorInfo(cause, 'Unable to update the language') },
        'replace',
      )
    }
  }

  const language = <Language locale={locale} label={t.language} onChange={changeLocale} />
  if (state.kind === 'loading') {
    return <main className="center"><p>Loading Vantage...</p></main>
  }
  if (state.kind === 'login') {
    return (
      <Login
        t={t}
        language={language}
        error={state.error}
        onSession={(session) => {
          setLocale(session.locale)
          enterSession(session)
        }}
      />
    )
  }
  if (state.kind === 'reauth') {
    return (
      <Login
        t={t}
        language={language}
        error={state.error}
        modal
        onSession={(session) => {
          setLocale(session.locale)
          enterSession(session)
        }}
      />
    )
  }
  if (state.kind === 'projects') {
    return (
      <ProjectSelection
        t={t}
        language={language}
        session={state.session}
        error={state.error}
        onSession={(session) => {
          const returnTo = pendingSafeRoute.current
          if (returnTo) pendingSafeRoute.current = undefined
          transition(nextState(session), 'push', returnTo)
        }}
        onExpired={expire}
      />
    )
  }
  return (
    <Overview
      t={t}
      language={language}
      session={state.session}
      error={state.error}
      onSwitch={() => {
        pendingSafeRoute.current = safeReturnUrl(window.location.href) ?? '/overview'
        transition({ kind: 'projects', session: state.session })
      }}
      onLogout={() => {
        pendingSafeRoute.current = undefined
        transition({ kind: 'login' }, 'replace')
      }}
    />
  )
}

function Language({
  locale,
  label,
  onChange,
}: {
  locale: Locale
  label: string
  onChange: (locale: Locale) => void
}) {
  return (
    <select
      className="locale"
      aria-label={label}
      value={locale}
      onChange={(event) => onChange(event.target.value as Locale)}
    >
      <option value="en">English</option>
      <option value="ko">한국어</option>
    </select>
  )
}

function ErrorNotice({ error, referenceLabel }: { error?: ErrorInfo; referenceLabel: string }) {
  if (!error) return null
  return (
    <div className="error" role="alert">
      <span>{error.message}</span>
      {error.references && (
        <small>{referenceLabel}: {error.references.join(' / ')}</small>
      )}
    </div>
  )
}

function Pagination({
  t,
  page,
  pageSize,
  onPage,
  onPageSize,
}: {
  t: Labels
  page?: ProjectPage['page']
  pageSize: number
  onPage: (page: number) => void
  onPageSize: (size: number) => void
}) {
  if (!page) return null
  return (
    <div className="pagination">
      <span className="page-range">
        {page.item_from}-{page.item_to} / {page.total_items ?? '?'}
      </span>
      <label className="page-size">
        <span>{t.rows}</span>
        <select
          value={pageSize}
          onChange={(event) => onPageSize(Number(event.target.value))}
        >
          {[10, 25, 50, 100].map((size) => <option key={size}>{size}</option>)}
        </select>
      </label>
      <nav aria-label={t.page}>
        <button
          type="button"
          className="page-button"
          aria-label={t.previousPage}
          disabled={!page.has_previous}
          onClick={() => onPage(page.number - 1)}
        >
          {'<'}
        </button>
        {page.navigable_pages.map((item, index, items) => (
          <Fragment key={item}>
            {index > 0 && item - items[index - 1] > 1 && <span className="page-gap">...</span>}
            <button
              type="button"
              className={item === page.number ? 'page-button current' : 'page-button'}
              aria-label={`${t.page} ${item}`}
              aria-current={item === page.number ? 'page' : undefined}
              onClick={() => onPage(item)}
            >
              {item}
            </button>
          </Fragment>
        ))}
        <button
          type="button"
          className="page-button"
          aria-label={t.nextPage}
          disabled={!page.has_next}
          onClick={() => onPage(page.number + 1)}
        >
          {'>'}
        </button>
      </nav>
    </div>
  )
}

function Login({
  t,
  language,
  error,
  modal = false,
  onSession,
}: {
  t: Labels
  language: ReactNode
  error?: ErrorInfo
  modal?: boolean
  onSession: (session: Session) => void
}) {
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState(error)
  const [invalidCredentials, setInvalidCredentials] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPending(true)
    setMessage(undefined)
    setInvalidCredentials(false)
    const form = event.currentTarget
    const data = new FormData(form)
    try {
      onSession(await api.login(
        String(data.get('username')),
        String(data.get('password')),
        String(data.get('domain')),
      ))
    } catch (cause) {
      setMessage(errorInfo(cause, 'Unable to sign in'))
      setInvalidCredentials(cause instanceof ApiError && cause.status === 401)
      const password = form.elements.namedItem('password')
      if (password instanceof HTMLInputElement) password.value = ''
    } finally {
      setPending(false)
    }
  }

  const title = modal ? t.reauthenticate : t.signIn
  const help = modal ? t.reauthenticateHelp : t.loginHelp

  return (
    <main className={modal ? 'auth-shell reauth-backdrop' : 'auth-shell'}>
      <section
        className="panel login-panel"
        role={modal ? 'dialog' : undefined}
        aria-modal={modal ? 'true' : undefined}
        aria-labelledby="login-title"
      >
        <div className="brand-row">
          <div className="brand"><span>V</span><strong>Vantage</strong></div>
          {language}
        </div>
        <p className="eyebrow">OPENSTACK CONSOLE</p>
        <h1 id="login-title">{title}</h1>
        <p className="muted">{help}</p>
        <ErrorNotice error={message} referenceLabel={t.requestReference} />
        <form onSubmit={submit}>
          <label>{t.domain}<input name="domain" defaultValue="default" required /></label>
          <label>
            {t.username}
            <input
              name="username"
              autoComplete="username"
              autoFocus={modal}
              aria-invalid={invalidCredentials}
              required
            />
          </label>
          <label>
            {t.password}
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={invalidCredentials}
              required
            />
          </label>
          <button type="submit" disabled={pending}>{pending ? t.signingIn : t.signIn}</button>
        </form>
      </section>
    </main>
  )
}

function ProjectSelection({
  t,
  language,
  session,
  error,
  onSession,
  onExpired,
}: {
  t: Labels
  language: ReactNode
  session: Session
  error?: ErrorInfo
  onSession: (session: Session) => void
  onExpired: () => void
}) {
  const [projects, setProjects] = useState<ProjectPage['items']>([])
  const [projectId, setProjectId] = useState(session.active_scope?.project.id ?? '')
  const [region, setRegion] = useState(session.active_scope?.region ?? session.regions[0] ?? '')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [pageInfo, setPageInfo] = useState<ProjectPage['page']>()
  const [projectsLoading, setProjectsLoading] = useState(true)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState(error)

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.projects(search.trim(), page, pageSize, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) return
          setMessage(undefined)
          setProjects(result.items)
          setPageInfo(result.page)
          setProjectId((current) => (
            result.items.some((project) => project.id === current)
              ? current
              : (result.items[0]?.id ?? '')
          ))
        })
        .catch((cause) => {
          if (cause instanceof DOMException && cause.name === 'AbortError') return
          if (cause instanceof ApiError && cause.status === 401) onExpired()
          else setMessage(errorInfo(cause, 'Unable to load projects'))
        })
        .finally(() => {
          if (!controller.signal.aborted) setProjectsLoading(false)
        })
    }, search.trim() ? 250 : 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [search, page, pageSize, onExpired])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setMessage(undefined)
    try {
      onSession(await api.scope(projectId, region))
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(errorInfo(cause, 'Unable to select the project'))
    } finally {
      setPending(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="panel project-panel">
        <div className="brand-row"><p className="eyebrow compact">SELECT SCOPE</p>{language}</div>
        <h1>{t.choose}</h1>
        <p className="muted">{session.user.name} / {t.chooseHelp}</p>
        <ErrorNotice error={message} referenceLabel={t.requestReference} />
        <label>
          {t.search}
          <input
            type="search"
            value={search}
            onChange={(event) => {
              setProjectsLoading(true)
              setSearch(event.target.value)
              setPage(1)
            }}
          />
        </label>
        <form onSubmit={submit}>
          <div className="project-list" role="radiogroup" aria-label={t.projects}>
            {projectsLoading && <p className="muted" aria-live="polite">{t.loadingProjects}</p>}
            {!projectsLoading && !message && projects.length === 0 && <p className="muted">{t.empty}</p>}
            {projects.map((project) => (
              <label className={projectId === project.id ? 'project active' : 'project'} key={project.id}>
                <input
                  type="radio"
                  name="project"
                  value={project.id}
                  checked={projectId === project.id}
                  onChange={() => setProjectId(project.id)}
                />
                <span>
                  <strong>{project.name}</strong>
                  <small>{project.domain_id ?? 'Unknown domain'} / {project.id}</small>
                </span>
              </label>
            ))}
          </div>
          <Pagination
            t={t}
            page={pageInfo}
            pageSize={pageSize}
            onPage={(nextPage) => {
              setProjectsLoading(true)
              setPage(nextPage)
            }}
            onPageSize={(size) => {
              setProjectsLoading(true)
              setPageSize(size)
              setPage(1)
            }}
          />
          <label>
            {t.region}
            <select value={region} onChange={(event) => setRegion(event.target.value)}>
              {session.regions.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <button type="submit" disabled={pending || !projectId || !region}>
            {pending ? t.switching : t.continue}
          </button>
        </form>
      </section>
    </main>
  )
}

function Overview({
  t,
  language,
  session,
  error,
  onSwitch,
  onLogout,
}: {
  t: Labels
  language: ReactNode
  session: Session
  error?: ErrorInfo
  onSwitch: () => void
  onLogout: () => void
}) {
  const scope = session.active_scope!
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState(error)

  async function logout() {
    setPending(true)
    setMessage(undefined)
    try {
      await api.logout()
      onLogout()
    } catch (cause) {
      setMessage(errorInfo(cause, t.logoutFailed))
      setPending(false)
    }
  }

  return (
    <div className="app-shell">
      <header>
        <div className="brand"><span>V</span><strong>Vantage</strong></div>
        <button type="button" className="scope secondary" onClick={onSwitch}>
          <strong>{scope.project.name}</strong><small>{scope.region}</small>
        </button>
        {language}
        <button type="button" className="secondary" onClick={logout} disabled={pending}>
          {pending ? t.signingOut : t.logout}
        </button>
      </header>
      <aside>
        <strong>Project</strong>
        <a href="/overview" className="selected" aria-current="page">{t.overview}</a>
      </aside>
      <main className="content">
        <p className="eyebrow compact">PROJECT OVERVIEW</p>
        <h1>{scope.project.name}</h1>
        <p className="muted">{t.ready}</p>
        <ErrorNotice error={message} referenceLabel={t.requestReference} />
        <section className="foundation">
          <h2>{t.foundation}</h2>
          <dl>
            <div><dt>{t.domain}</dt><dd>{scope.project.domain_id ?? 'Unknown'}</dd></div>
            <div><dt>{t.region}</dt><dd>{scope.region}</dd></div>
            <div><dt>{t.expires}</dt><dd>{new Date(session.expires_at).toLocaleString()}</dd></div>
          </dl>
          <button type="button" className="secondary switch" onClick={onSwitch}>{t.switch}</button>
        </section>
      </main>
    </div>
  )
}
