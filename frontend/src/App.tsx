import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, api } from './api'
import { DEFAULT_INSTANCE_QUERY, instancePath, parseInstanceRoute } from './instance-route'
import { InstancesPage } from './InstancesPage'
import {
  DEFAULT_IMAGE_QUERY,
  DEFAULT_KEYPAIR_QUERY,
  imagePath,
  keyPairPath,
  parseImageRoute,
  parseKeyPairRoute,
} from './inventory-route'
import { Pagination } from './Pagination'
import { ImagesPage, KeyPairsPage } from './ProvisioningPages'
import type {
  ImageQuery,
  InstanceQuery,
  InventoryQuery,
  ProjectOverview,
  ProjectPage,
  Quota,
  QuotaPayload,
  QuotaService,
  Session,
  WidgetError,
} from './types'
import './styles.css'

type Locale = 'en' | 'ko'
type QuotaFilter = 'all' | QuotaService
type ErrorInfo = { message: string; references?: string[] }
type State =
  | { kind: 'loading' }
  | { kind: 'login'; error?: ErrorInfo }
  | { kind: 'reauth'; error: ErrorInfo; returnTo: string }
  | { kind: 'projects'; session: Session; error?: ErrorInfo }
  | { kind: 'overview'; session: Session; error?: ErrorInfo }
  | { kind: 'quotas'; session: Session; filter: QuotaFilter; error?: ErrorInfo }
  | {
    kind: 'instances'
    session: Session
    query: InstanceQuery
    selectedId?: string
    drawerFromList: boolean
    error?: ErrorInfo
  }
  | { kind: 'images'; session: Session; query: ImageQuery; error?: ErrorInfo }
  | { kind: 'keypairs'; session: Session; query: InventoryQuery; error?: ErrorInfo }
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
    projectNavigation: 'Project navigation',
    quotas: 'Quotas',
    overviewDescription: 'Current capacity and workload for this project.',
    quotasDescription: 'Review service limits and current consumption.',
    instanceSummary: 'Instance summary',
    totalInstances: 'Total instances',
    activeInstances: 'Active',
    stoppedInstances: 'Stopped',
    errorInstances: 'Error',
    statusUnavailable: 'Status breakdown unavailable',
    quotaUsage: 'Quota usage',
    compute: 'Compute',
    network: 'Network',
    storage: 'Storage',
    all: 'All',
    quotaFilters: 'Quota service filters',
    loadingOverview: 'Loading project capacity...',
    loadingQuotas: 'Loading quotas...',
    overviewFailed: 'Unable to load the project overview',
    quotasFailed: 'Unable to load quotas',
    noQuotas: 'No quota data is available for this service.',
    partialData: 'Some service data is unavailable.',
    quotaTimedOut: 'quota request timed out.',
    quotaUnavailable: 'quota data is unavailable.',
    quotaForbidden: 'quota data is not permitted for this project.',
    quotaRateLimited: 'quota data is temporarily rate limited.',
    serviceDataUnavailable: 'Service data is currently unavailable.',
    errorCode: 'Error code',
    updated: 'Updated',
    updating: 'Updating in the background...',
    stale: 'Showing the last available data',
    unlimited: 'Unlimited',
    used: 'Used',
    reserved: 'Reserved',
    limit: 'Limit',
    resource: 'Resource',
    service: 'Service',
    state: 'State',
    normal: 'Normal',
    watch: 'Watch',
    high: 'High',
    unknown: 'Unknown',
    instances: 'Instances',
    images: 'Images',
    access: 'Access',
    keypairs: 'Key pairs',
    cores: 'vCPUs',
    ram_mib: 'Memory',
    volumes: 'Volumes',
    gigabytes: 'Volume capacity',
    snapshots: 'Snapshots',
    backups: 'Backups',
    backup_gigabytes: 'Backup capacity',
    floating_ips: 'Floating IPs',
    networks: 'Networks',
    ports: 'Ports',
    routers: 'Routers',
    security_groups: 'Security groups',
    security_group_rules: 'Security group rules',
    load_balancers: 'Load balancers',
    projectContext: 'Project context',
    notAvailable: 'Not available',
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
    projectNavigation: '프로젝트 탐색',
    quotas: '쿼터',
    overviewDescription: '이 프로젝트의 현재 용량과 워크로드를 확인합니다.',
    quotasDescription: '서비스별 제한과 현재 사용량을 확인합니다.',
    instanceSummary: '인스턴스 요약',
    totalInstances: '전체 인스턴스',
    activeInstances: '실행 중',
    stoppedInstances: '정지',
    errorInstances: '오류',
    statusUnavailable: '상태별 집계를 사용할 수 없음',
    quotaUsage: '쿼터 사용량',
    compute: '컴퓨트',
    network: '네트워크',
    storage: '스토리지',
    all: '전체',
    quotaFilters: '쿼터 서비스 필터',
    loadingOverview: '프로젝트 용량을 불러오는 중...',
    loadingQuotas: '쿼터를 불러오는 중...',
    overviewFailed: '프로젝트 개요를 불러올 수 없습니다.',
    quotasFailed: '쿼터를 불러올 수 없습니다.',
    noQuotas: '이 서비스에서 사용할 수 있는 쿼터 데이터가 없습니다.',
    partialData: '일부 서비스 데이터를 사용할 수 없습니다.',
    quotaTimedOut: '쿼터 요청 시간이 초과되었습니다.',
    quotaUnavailable: '쿼터 데이터를 사용할 수 없습니다.',
    quotaForbidden: '이 프로젝트에서 쿼터 데이터를 조회할 권한이 없습니다.',
    quotaRateLimited: '쿼터 요청이 일시적으로 제한되었습니다.',
    serviceDataUnavailable: '서비스 데이터를 현재 사용할 수 없습니다.',
    errorCode: '오류 코드',
    updated: '업데이트',
    updating: '백그라운드에서 업데이트 중...',
    stale: '마지막으로 확인된 데이터를 표시 중',
    unlimited: '무제한',
    used: '사용',
    reserved: '예약',
    limit: '한도',
    resource: '리소스',
    service: '서비스',
    state: '상태',
    normal: '정상',
    watch: '주의',
    high: '높음',
    unknown: '알 수 없음',
    instances: '인스턴스',
    images: '이미지',
    access: '접근',
    keypairs: '키 페어',
    cores: 'vCPU',
    ram_mib: '메모리',
    volumes: '볼륨',
    gigabytes: '볼륨 용량',
    snapshots: '스냅샷',
    backups: '백업',
    backup_gigabytes: '백업 용량',
    floating_ips: '플로팅 IP',
    networks: '네트워크',
    ports: '포트',
    routers: '라우터',
    security_groups: '보안 그룹',
    security_group_rules: '보안 그룹 규칙',
    load_balancers: '로드 밸런서',
    projectContext: '프로젝트 범위',
    notAvailable: '사용할 수 없음',
  },
}
type Labels = typeof labels.en

function quotaFilter(value: string | null): QuotaFilter {
  return value === 'compute' || value === 'network' || value === 'storage' ? value : 'all'
}

function scopedState(session: Session, route = '/overview', drawerFromList = false): State {
  if (!session.active_scope) return { kind: 'projects', session }
  const url = new URL(route, window.location.origin)
  if (url.pathname === '/quotas') {
    return { kind: 'quotas', session, filter: quotaFilter(url.searchParams.get('service')) }
  }
  const imageQuery = parseImageRoute(url.href)
  if (imageQuery) return { kind: 'images', session, query: imageQuery }
  const keypairQuery = parseKeyPairRoute(url.href)
  if (keypairQuery) return { kind: 'keypairs', session, query: keypairQuery }
  const instanceRoute = parseInstanceRoute(url.href)
  if (instanceRoute) {
    return {
      kind: 'instances',
      session,
      query: instanceRoute.query,
      selectedId: instanceRoute.instanceId,
      drawerFromList: Boolean(instanceRoute.instanceId && drawerFromList),
    }
  }
  return { kind: 'overview', session }
}

function pathForState(state: State): string {
  if (state.kind === 'login') return '/login'
  if (state.kind === 'reauth') return state.returnTo
  if (state.kind === 'projects') return '/projects/select'
  if (state.kind === 'overview') return '/overview'
  if (state.kind === 'quotas') {
    return state.filter === 'all' ? '/quotas' : `/quotas?service=${state.filter}`
  }
  if (state.kind === 'instances') return instancePath(state.query, state.selectedId)
  if (state.kind === 'images') return imagePath(state.query)
  if (state.kind === 'keypairs') return keyPairPath(state.query)
  return window.location.pathname
}

function safeReturnUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length === 0) return undefined
  const url = new URL(value, window.location.origin)
  if (url.origin !== window.location.origin) return undefined
  const instanceRoute = parseInstanceRoute(url.href)
  if (instanceRoute) return instancePath(instanceRoute.query, instanceRoute.instanceId)
  const imageQuery = parseImageRoute(url.href)
  if (imageQuery) return imagePath(imageQuery)
  const keypairQuery = parseKeyPairRoute(url.href)
  if (keypairQuery) return keyPairPath(keypairQuery)
  if (url.pathname !== '/overview' && url.pathname !== '/quotas') return undefined
  if (url.pathname === '/quotas' && url.searchParams.has('service')) {
    const service = url.searchParams.get('service')
    if (service !== 'compute' && service !== 'network' && service !== 'storage') return undefined
  }
  return `${url.pathname}${url.search}${url.hash}`
}

function currentUrl(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

function preservesInstanceBackground(current: State, next: State): boolean {
  return current.kind === 'instances'
    && next.kind === 'instances'
    && Boolean(current.selectedId || next.selectedId)
    && instancePath(current.query) === instancePath(next.query)
}

function sessionForState(state: State): Session | undefined {
  return state.kind === 'projects'
    || state.kind === 'overview'
    || state.kind === 'quotas'
    || state.kind === 'instances'
    || state.kind === 'images'
    || state.kind === 'keypairs'
    ? state.session
    : undefined
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
    const preserveScroll = preservesInstanceBackground(stateRef.current, next)
    stateRef.current = next
    setState(next)
    if (mode === 'none') return
    const path = route ?? pathForState(next)
    const historyState = {
      ...(pendingSafeRoute.current ? { returnTo: pendingSafeRoute.current } : {}),
      ...(next.kind === 'instances' && next.selectedId && next.drawerFromList
        ? { instanceDrawer: true }
        : {}),
    }
    if (currentUrl() === path) {
      window.history.replaceState(historyState, '', path)
      return
    }
    window.history[mode === 'replace' ? 'replaceState' : 'pushState'](historyState, '', path)
    if (!preserveScroll) window.scrollTo({ top: 0, left: 0 })
  }, [])

  const enterSession = useCallback((session: Session, mode: HistoryMode = 'replace') => {
    const returnTo = session.active_scope ? pendingSafeRoute.current : undefined
    const next = scopedState(session, returnTo ?? '/overview')
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
      } else if (window.location.pathname === '/quotas' && session?.active_scope) {
        next = scopedState(session, currentUrl())
      } else if (parseInstanceRoute(window.location.href) && session?.active_scope) {
        next = scopedState(session, currentUrl(), Boolean(window.history.state?.instanceDrawer))
      } else if ((parseImageRoute(window.location.href) || parseKeyPairRoute(window.location.href)) && session?.active_scope) {
        next = scopedState(session, currentUrl())
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
    if (
      state.kind !== 'projects'
      && state.kind !== 'overview'
      && state.kind !== 'quotas'
      && state.kind !== 'instances'
      && state.kind !== 'images'
      && state.kind !== 'keypairs'
    ) return
    try {
      const session = await api.locale(next)
      transition({ ...state, session }, 'replace')
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
          transition(scopedState(session, returnTo ?? '/overview'), 'push', returnTo)
        }}
        onExpired={expire}
      />
    )
  }
  return (
    <ProjectWorkspace
      t={t}
      locale={locale}
      language={language}
      session={state.session}
      error={state.error}
      view={state.kind}
      filter={state.kind === 'quotas' ? state.filter : 'all'}
      instanceQuery={state.kind === 'instances' ? state.query : DEFAULT_INSTANCE_QUERY}
      selectedInstanceId={state.kind === 'instances' ? state.selectedId : undefined}
      imageQuery={state.kind === 'images' ? state.query : DEFAULT_IMAGE_QUERY}
      keypairQuery={state.kind === 'keypairs' ? state.query : DEFAULT_KEYPAIR_QUERY}
      onNavigate={(view, filter = 'all') => {
        if (view === 'quotas') transition({ kind: 'quotas', session: state.session, filter })
        else if (view === 'instances') {
          transition({
            kind: 'instances',
            session: state.session,
            query: DEFAULT_INSTANCE_QUERY,
            drawerFromList: false,
          })
        } else if (view === 'images') {
          transition({ kind: 'images', session: state.session, query: DEFAULT_IMAGE_QUERY })
        } else if (view === 'keypairs') {
          transition({ kind: 'keypairs', session: state.session, query: DEFAULT_KEYPAIR_QUERY })
        } else transition({ kind: 'overview', session: state.session })
      }}
      onInstanceQuery={(query, mode) => {
        if (state.kind !== 'instances') return
        transition({ ...state, query }, mode)
      }}
      onInstanceOpen={(instanceId) => {
        if (state.kind !== 'instances') return
        transition({
          ...state,
          selectedId: instanceId,
          drawerFromList: true,
        }, 'push')
      }}
      onInstanceClose={() => {
        if (state.kind !== 'instances') return
        if (state.drawerFromList) {
          window.history.back()
          return
        }
        transition({ ...state, selectedId: undefined, drawerFromList: false }, 'replace')
      }}
      onImageQuery={(query, mode) => {
        if (state.kind === 'images') transition({ ...state, query }, mode)
      }}
      onKeyPairQuery={(query, mode) => {
        if (state.kind === 'keypairs') transition({ ...state, query }, mode)
      }}
      onSwitch={() => {
        pendingSafeRoute.current = state.kind === 'instances'
          ? instancePath(state.query)
          : safeReturnUrl(window.location.href) ?? '/overview'
        transition({ kind: 'projects', session: state.session })
      }}
      onExpired={expire}
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
            labels={t}
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

const REVALIDATE_INTERVAL_MS = 30_000
const SERVICES: QuotaService[] = ['compute', 'network', 'storage']
const RESOURCE_LABELS: Record<string, keyof Labels> = {
  instances: 'instances',
  cores: 'cores',
  ram_mib: 'ram_mib',
  volumes: 'volumes',
  gigabytes: 'gigabytes',
  snapshots: 'snapshots',
  backups: 'backups',
  backup_gigabytes: 'backup_gigabytes',
  floating_ips: 'floating_ips',
  networks: 'networks',
  ports: 'ports',
  routers: 'routers',
  security_groups: 'security_groups',
  security_group_rules: 'security_group_rules',
  load_balancers: 'load_balancers',
}

function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError'
}

function serviceFromErrorCode(code: string): QuotaService | undefined {
  return SERVICES.find((service) => code === service || code.startsWith(`${service}_`))
}

function reconcileQuotaPayload<T extends QuotaPayload>(previous: T | undefined, next: T): T {
  if (!previous || next.partial_errors.length === 0) return next
  const failedServices = new Set(
    next.partial_errors
      .map((error) => serviceFromErrorCode(error.code))
      .filter((service): service is QuotaService => Boolean(service)),
  )
  if (failedServices.size === 0) return next
  const quotas = [
    ...next.quotas.filter((quota) => !failedServices.has(quota.service)),
    ...previous.quotas.filter((quota) => failedServices.has(quota.service)),
  ]
  const merged = { ...next, quotas, stale: true } as T
  if (
    failedServices.has('compute')
    && 'instance_summary' in previous
    && 'instance_summary' in next
  ) {
    return { ...merged, instance_summary: previous.instance_summary } as T
  }
  return merged
}

function markQuotaPayloadStale<T extends QuotaPayload>(previous: T): T {
  return previous.stale ? previous : { ...previous, stale: true }
}

function useBackgroundResource<T>({
  key,
  loader,
  reconcile,
  staleOnError,
  fallback,
  onExpired,
}: {
  key: string
  loader: (signal: AbortSignal) => Promise<T>
  reconcile?: (previous: T | undefined, next: T) => T
  staleOnError?: (previous: T) => T
  fallback: string
  onExpired: () => void
}) {
  const loaderRef = useRef(loader)
  const reconcileRef = useRef(reconcile)
  const staleOnErrorRef = useRef(staleOnError)
  const fallbackRef = useRef(fallback)
  const dataRef = useRef<T | undefined>(undefined)
  const [data, setData] = useState<T>()
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [failure, setFailure] = useState<ErrorInfo>()

  useEffect(() => {
    loaderRef.current = loader
    reconcileRef.current = reconcile
    staleOnErrorRef.current = staleOnError
    fallbackRef.current = fallback
  }, [fallback, loader, reconcile, staleOnError])

  useEffect(() => {
    let disposed = false
    let current: AbortController | undefined

    async function refresh() {
      if (disposed) return
      current?.abort()
      const controller = new AbortController()
      current = controller
      if (dataRef.current) setUpdating(true)
      else setLoading(true)
      setFailure(undefined)
      try {
        const next = await loaderRef.current(controller.signal)
        if (disposed || current !== controller) return
        const result = reconcileRef.current?.(dataRef.current, next) ?? next
        dataRef.current = result
        setData(result)
      } catch (cause) {
        if (disposed || current !== controller || isAbort(cause)) return
        if (cause instanceof ApiError && cause.status === 401) {
          onExpired()
          return
        }
        if (dataRef.current && staleOnErrorRef.current) {
          const stale = staleOnErrorRef.current(dataRef.current)
          dataRef.current = stale
          setData(stale)
        }
        setFailure(errorInfo(cause, fallbackRef.current))
      } finally {
        if (!disposed && current === controller) {
          setLoading(false)
          setUpdating(false)
        }
      }
    }

    void refresh()
    const interval = window.setInterval(() => void refresh(), REVALIDATE_INTERVAL_MS)
    const handleFocus = () => void refresh()
    window.addEventListener('focus', handleFocus)
    return () => {
      disposed = true
      current?.abort()
      window.clearInterval(interval)
      window.removeEventListener('focus', handleFocus)
    }
  }, [key, onExpired])

  return { data, failure, loading, updating }
}

function ProjectWorkspace({
  t,
  locale,
  language,
  session,
  error,
  view,
  filter,
  instanceQuery,
  selectedInstanceId,
  imageQuery,
  keypairQuery,
  onNavigate,
  onInstanceQuery,
  onInstanceOpen,
  onInstanceClose,
  onImageQuery,
  onKeyPairQuery,
  onSwitch,
  onExpired,
  onLogout,
}: {
  t: Labels
  locale: Locale
  language: ReactNode
  session: Session
  error?: ErrorInfo
  view: 'overview' | 'quotas' | 'instances' | 'images' | 'keypairs'
  filter: QuotaFilter
  instanceQuery: InstanceQuery
  selectedInstanceId?: string
  imageQuery: ImageQuery
  keypairQuery: InventoryQuery
  onNavigate: (view: 'overview' | 'quotas' | 'instances' | 'images' | 'keypairs', filter?: QuotaFilter) => void
  onInstanceQuery: (query: InstanceQuery, mode: 'push' | 'replace') => void
  onInstanceOpen: (instanceId: string) => void
  onInstanceClose: () => void
  onImageQuery: (query: ImageQuery, mode: 'push' | 'replace') => void
  onKeyPairQuery: (query: InventoryQuery, mode: 'push' | 'replace') => void
  onSwitch: () => void
  onExpired: () => void
  onLogout: () => void
}) {
  const scope = session.active_scope!
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<ErrorInfo>()

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
        <button
          type="button"
          className="scope secondary"
          aria-label={`${t.switch}: ${scope.project.name}, ${scope.region}`}
          onClick={onSwitch}
        >
          <strong>{scope.project.name}</strong><small>{scope.region}</small>
        </button>
        {language}
        <button type="button" className="secondary" onClick={logout} disabled={pending}>
          {pending ? t.signingOut : t.logout}
        </button>
      </header>
      <aside aria-label={t.projectNavigation}>
        <strong>{t.projectContext}</strong>
        <a
          href="/overview"
          className={view === 'overview' ? 'selected' : undefined}
          aria-current={view === 'overview' ? 'page' : undefined}
          onClick={(event) => {
            event.preventDefault()
            onNavigate('overview')
          }}
        >
          {t.overview}
        </a>
        <a
          href="/quotas"
          className={view === 'quotas' ? 'selected' : undefined}
          aria-current={view === 'quotas' ? 'page' : undefined}
          onClick={(event) => {
            event.preventDefault()
            onNavigate('quotas')
          }}
        >
          {t.quotas}
        </a>
        <strong>{t.compute}</strong>
        <a
          href="/instances"
          className={view === 'instances' ? 'selected' : undefined}
          aria-current={view === 'instances' ? 'page' : undefined}
          onClick={(event) => {
            event.preventDefault()
            onNavigate('instances')
          }}
        >
          {t.instances}
        </a>
        <a
          href="/images"
          className={view === 'images' ? 'selected' : undefined}
          aria-current={view === 'images' ? 'page' : undefined}
          onClick={(event) => {
            event.preventDefault()
            onNavigate('images')
          }}
        >
          {t.images}
        </a>
        <strong>{t.access}</strong>
        <a
          href="/keypairs"
          className={view === 'keypairs' ? 'selected' : undefined}
          aria-current={view === 'keypairs' ? 'page' : undefined}
          onClick={(event) => {
            event.preventDefault()
            onNavigate('keypairs')
          }}
        >
          {t.keypairs}
        </a>
      </aside>
      <main className="content">
        <ErrorNotice error={message ?? error} referenceLabel={t.requestReference} />
        {view === 'overview' ? (
          <OverviewPage
            key={`${scope.project.id}:${scope.region}:overview`}
            t={t}
            locale={locale}
            session={session}
            onExpired={onExpired}
          />
        ) : view === 'quotas' ? (
          <QuotaDetailsPage
            key={`${scope.project.id}:${scope.region}:quotas:${filter}`}
            t={t}
            locale={locale}
            session={session}
            filter={filter}
            onFilter={(next) => onNavigate('quotas', next)}
            onExpired={onExpired}
          />
        ) : view === 'instances' ? (
          <InstancesPage
            key={`${scope.project.id}:${scope.region}:instances`}
            scopeKey={`${scope.project.id}:${scope.region}`}
            locale={locale}
            query={instanceQuery}
            selectedId={selectedInstanceId}
            onQuery={onInstanceQuery}
            onOpen={onInstanceOpen}
            onClose={onInstanceClose}
            onExpired={onExpired}
          />
        ) : view === 'images' ? (
          <ImagesPage
            scopeKey={`${scope.project.id}:${scope.region}`}
            locale={locale}
            query={imageQuery}
            onQuery={onImageQuery}
            onExpired={onExpired}
          />
        ) : (
          <KeyPairsPage
            scopeKey={`${scope.project.id}:${scope.region}`}
            locale={locale}
            query={keypairQuery}
            onQuery={onKeyPairQuery}
            onExpired={onExpired}
          />
        )}
      </main>
    </div>
  )
}

function OverviewPage({
  t,
  locale,
  session,
  onExpired,
}: {
  t: Labels
  locale: Locale
  session: Session
  onExpired: () => void
}) {
  const scope = session.active_scope!
  const { data, failure, loading, updating } = useBackgroundResource<ProjectOverview>({
    key: `${scope.project.id}:${scope.region}:overview`,
    loader: (signal) => api.overview(signal),
    reconcile: reconcileQuotaPayload,
    staleOnError: markQuotaPayloadStale,
    fallback: t.overviewFailed,
    onExpired,
  })

  return (
    <>
      <PageHeading
        eyebrow={t.overview}
        title={scope.project.name}
        description={t.overviewDescription}
        data={data}
        updating={updating}
        locale={locale}
        t={t}
      />
      <ErrorNotice error={failure} referenceLabel={t.requestReference} />
      {loading && !data && <LoadingState label={t.loadingOverview} />}
      {data && (
        <>
          <PartialErrors errors={data.partial_errors} t={t} />
          <InstanceSummaryView summary={data.instance_summary} t={t} locale={locale} />
          <section className="quota-overview" aria-labelledby="quota-usage-heading">
            <div className="section-heading">
              <h2 id="quota-usage-heading">{t.quotaUsage}</h2>
            </div>
            {SERVICES.map((service) => (
              <QuotaGroup
                key={service}
                service={service}
                quotas={data.quotas.filter((quota) => quota.service === service)}
                t={t}
                locale={locale}
              />
            ))}
          </section>
        </>
      )}
    </>
  )
}

function QuotaDetailsPage({
  t,
  locale,
  session,
  filter,
  onFilter,
  onExpired,
}: {
  t: Labels
  locale: Locale
  session: Session
  filter: QuotaFilter
  onFilter: (filter: QuotaFilter) => void
  onExpired: () => void
}) {
  const scope = session.active_scope!
  const service = filter === 'all' ? undefined : filter
  const { data, failure, loading, updating } = useBackgroundResource<QuotaPayload>({
    key: `${scope.project.id}:${scope.region}:quotas:${filter}`,
    loader: (signal) => api.quotas(service, signal),
    reconcile: reconcileQuotaPayload,
    staleOnError: markQuotaPayloadStale,
    fallback: t.quotasFailed,
    onExpired,
  })

  return (
    <>
      <PageHeading
        eyebrow={t.projectContext}
        title={t.quotas}
        description={t.quotasDescription}
        data={data}
        updating={updating}
        locale={locale}
        t={t}
      />
      <div className="segmented" role="tablist" aria-label={t.quotaFilters}>
        {(['all', ...SERVICES] as QuotaFilter[]).map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={filter === item}
            className={filter === item ? 'active' : undefined}
            onClick={() => onFilter(item)}
          >
            {filterLabel(item, t)}
          </button>
        ))}
      </div>
      <ErrorNotice error={failure} referenceLabel={t.requestReference} />
      {loading && !data && <LoadingState label={t.loadingQuotas} />}
      {data && (
        <>
          <PartialErrors errors={data.partial_errors} t={t} />
          {data.quotas.length > 0
            ? <QuotaTable quotas={data.quotas} t={t} locale={locale} />
            : <p className="empty-state">{t.noQuotas}</p>}
        </>
      )}
    </>
  )
}

function PageHeading({
  eyebrow,
  title,
  description,
  data,
  updating,
  locale,
  t,
}: {
  eyebrow: string
  title: string
  description: string
  data?: { generated_at: string; stale: boolean }
  updating: boolean
  locale: Locale
  t: Labels
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow compact">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="muted">{description}</p>
      </div>
      <p className={`sync-status${data?.stale ? ' stale' : ''}`} aria-live="polite">
        {updating
          ? t.updating
          : data
            ? <>{data.stale ? t.stale : t.updated} <time dateTime={data.generated_at}>{formatDate(data.generated_at, locale)}</time></>
            : null}
      </p>
    </div>
  )
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="loading-state" role="status">
      <span className="loading-line" />
      <span>{label}</span>
    </div>
  )
}

function PartialErrors({ errors, t }: { errors: WidgetError[]; t: Labels }) {
  if (errors.length === 0) return null
  return (
    <section className="partial-errors" aria-labelledby="partial-errors-heading">
      <h2 id="partial-errors-heading">{t.partialData}</h2>
      {errors.map((error, index) => (
        <div className="partial-error" key={`${error.code}:${error.openstack_request_id ?? index}`}>
          <span>{localizedPartialError(error, t)}</span>
          <small>
            {t.errorCode}: {error.code}
            {error.openstack_request_id && <> / {t.requestReference}: OpenStack {error.openstack_request_id}</>}
          </small>
        </div>
      ))}
    </section>
  )
}

function InstanceSummaryView({
  summary,
  t,
  locale,
}: {
  summary: ProjectOverview['instance_summary']
  t: Labels
  locale: Locale
}) {
  const metrics = [
    [t.totalInstances, summary?.total],
    [t.activeInstances, summary?.active],
    [t.stoppedInstances, summary?.stopped],
    [t.errorInstances, summary?.error],
  ] as const
  return (
    <section className="instance-summary" aria-labelledby="instance-summary-heading">
      <div className="section-heading">
        <h2 id="instance-summary-heading">{t.instanceSummary}</h2>
        {summary && metrics.slice(1).every(([, value]) => value === null) && (
          <span>{t.statusUnavailable}</span>
        )}
      </div>
      <dl>
        {metrics.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value === null || value === undefined ? '—' : formatNumber(value, locale)}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function QuotaGroup({
  service,
  quotas,
  t,
  locale,
}: {
  service: QuotaService
  quotas: Quota[]
  t: Labels
  locale: Locale
}) {
  return (
    <section className="quota-group" aria-labelledby={`quota-group-${service}`}>
      <div className="quota-group-heading">
        <h3 id={`quota-group-${service}`}>{serviceLabel(service, t)}</h3>
        <span>{quotas.length}</span>
      </div>
      {quotas.length > 0 ? (
        <div className="quota-grid">
          {quotas.map((quota) => <QuotaCard key={quota.resource} quota={quota} t={t} locale={locale} />)}
        </div>
      ) : (
        <p className="empty-service">{t.noQuotas}</p>
      )}
    </section>
  )
}

function QuotaCard({ quota, t, locale }: { quota: Quota; t: Labels; locale: Locale }) {
  const consumed = quota.used + quota.reserved
  const ariaLimit = quota.limit === null ? undefined : Math.max(0, quota.limit)
  const ariaValue = ariaLimit === undefined
    ? undefined
    : Math.min(ariaLimit, Math.max(0, consumed))
  const percent = quota.limit === null || quota.limit <= 0
    ? 0
    : Math.min(100, Math.max(0, (consumed / quota.limit) * 100))
  const label = resourceLabel(quota.resource, t)
  return (
    <article className={`quota-card state-${quota.state}`}>
      <div className="quota-title-row">
        <h4>{label}</h4>
        <span className="state-label">{stateLabel(quota.state, t)}</span>
      </div>
      <p className="quota-total">
        <strong>{formatQuotaValue(quota.used, quota.unit, locale)}</strong>
        {quota.reserved > 0 && <span> + {formatQuotaValue(quota.reserved, quota.unit, locale)} {t.reserved.toLowerCase()}</span>}
        <span> / {quota.limit === null ? t.unlimited : formatQuotaValue(quota.limit, quota.unit, locale)}</span>
      </p>
      <div
        className={`quota-progress state-${quota.state}`}
        role="progressbar"
        aria-label={`${label}: ${t.used} ${quota.used}, ${t.reserved} ${quota.reserved}, ${t.limit} ${quota.limit ?? t.unlimited}`}
        aria-valuemin={ariaLimit === undefined ? undefined : 0}
        aria-valuemax={ariaLimit}
        aria-valuenow={ariaValue}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="quota-breakdown">
        <span>{t.used} <strong>{formatQuotaValue(quota.used, quota.unit, locale)}</strong></span>
        <span>{t.reserved} <strong>{formatQuotaValue(quota.reserved, quota.unit, locale)}</strong></span>
      </div>
    </article>
  )
}

function QuotaTable({ quotas, t, locale }: { quotas: Quota[]; t: Labels; locale: Locale }) {
  return (
    <div className="quota-table" role="table" aria-label={t.quotas}>
      <div className="quota-table-header" role="row">
        {[t.resource, t.service, t.used, t.reserved, t.limit, t.state].map((label) => (
          <span role="columnheader" key={label}>{label}</span>
        ))}
      </div>
      {quotas.map((quota) => (
        <div className="quota-table-row" role="row" key={`${quota.service}:${quota.resource}`}>
          <span role="cell" data-label={t.resource}><strong>{resourceLabel(quota.resource, t)}</strong></span>
          <span role="cell" data-label={t.service}>{serviceLabel(quota.service, t)}</span>
          <span role="cell" data-label={t.used}>{formatQuotaValue(quota.used, quota.unit, locale)}</span>
          <span role="cell" data-label={t.reserved}>{formatQuotaValue(quota.reserved, quota.unit, locale)}</span>
          <span role="cell" data-label={t.limit}>{quota.limit === null ? t.unlimited : formatQuotaValue(quota.limit, quota.unit, locale)}</span>
          <span role="cell" data-label={t.state} className={`table-state state-${quota.state}`}>
            {stateLabel(quota.state, t)}
          </span>
        </div>
      ))}
    </div>
  )
}

function filterLabel(filter: QuotaFilter, t: Labels): string {
  return filter === 'all' ? t.all : serviceLabel(filter, t)
}

function localizedPartialError(error: WidgetError, t: Labels): string {
  const service = serviceFromErrorCode(error.code)
  const prefix = service ? `${serviceLabel(service, t)} ` : ''
  if (error.code.includes('timeout')) return `${prefix}${t.quotaTimedOut}`
  if (
    error.code.includes('forbidden')
    || error.code.includes('denied')
    || error.code.includes('policy')
  ) {
    return `${prefix}${t.quotaForbidden}`
  }
  if (error.code.includes('rate_limited')) return `${prefix}${t.quotaRateLimited}`
  if (
    error.code.includes('unavailable')
    || error.code.includes('failed')
    || error.code.includes('error')
  ) {
    return `${prefix}${t.quotaUnavailable}`
  }
  return service ? `${prefix}${t.quotaUnavailable}` : t.serviceDataUnavailable
}

function serviceLabel(service: QuotaService, t: Labels): string {
  return t[service]
}

function stateLabel(state: Quota['state'], t: Labels): string {
  return t[state]
}

function resourceLabel(resource: string, t: Labels): string {
  const key = RESOURCE_LABELS[resource]
  if (key) return t[key]
  return resource.replaceAll('_', ' ').replace(/\b\w/g, (value) => value.toUpperCase())
}

function formatNumber(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === 'ko' ? 'ko-KR' : 'en-US').format(value)
}

function formatQuotaValue(value: number, unit: Quota['unit'], locale: Locale): string {
  const formatted = formatNumber(value, locale)
  return unit === 'count' ? formatted : `${formatted} ${unit}`
}

function formatDate(value: string, locale: Locale): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(locale === 'ko' ? 'ko-KR' : 'en-US')
}
