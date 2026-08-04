import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent } from 'react'
import { ApiError, api } from './api'
import { DEFAULT_INSTANCE_QUERY } from './instance-route'
import { Pagination } from './Pagination'
import type {
  Instance,
  InstanceDetail,
  InstancePage,
  InstanceQuery,
  InstanceSort,
  SortDirection,
} from './types'

type Locale = 'en' | 'ko'
type HistoryMode = 'push' | 'replace'
type DetailTab = 'overview' | 'network' | 'storage'
type ErrorResolution = 'handled' | 'retry' | undefined

const DETAIL_TABS: DetailTab[] = ['overview', 'network', 'storage']

const STATUSES = [
  'ACTIVE',
  'BUILD',
  'ERROR',
  'PAUSED',
  'REBOOT',
  'RESCUE',
  'RESIZE',
  'REVERT_RESIZE',
  'SHELVED',
  'SHELVED_OFFLOADED',
  'SHUTOFF',
  'SOFT_DELETED',
  'SUSPENDED',
  'UNKNOWN',
  'VERIFY_RESIZE',
] as const

const copy = {
  en: {
    compute: 'Compute',
    instances: 'Instances',
    description: 'Virtual machines and their current state in this project.',
    name: 'Name',
    nameFilter: 'Filter by name',
    status: 'Status',
    allStatuses: 'All statuses',
    image: 'Image',
    imageId: 'Image ID',
    imageFilter: 'Filter by image ID',
    flavor: 'Flavor',
    addresses: 'Addresses',
    created: 'Created',
    sortBy: 'Sort by',
    direction: 'Direction',
    createdSort: 'Created',
    nameSort: 'Name',
    statusSort: 'Status',
    ascending: 'Ascending',
    descending: 'Descending',
    clearFilters: 'Clear filters',
    rows: 'Rows per page',
    page: 'Page',
    previousPage: 'Previous page',
    nextPage: 'Next page',
    loading: 'Loading instances...',
    loadFailed: 'Unable to load instances',
    empty: 'No instances match the current filters.',
    updating: 'Updating in the background...',
    updated: 'Updated',
    stale: 'Showing the last available data',
    requestReference: 'Request reference',
    openInstance: 'Open instance details',
    details: 'Instance details',
    close: 'Close instance details',
    overview: 'Overview',
    network: 'Network',
    storage: 'Storage',
    id: 'ID',
    attachedVolumes: 'Attached volumes',
    device: 'Device',
    noAddresses: 'No addresses',
    noVolumes: 'No attached volumes',
    notAvailable: 'Not available',
    detailLoading: 'Loading instance details...',
    detailFailed: 'Unable to load instance details',
    problems: {
      active_scope_required: 'Select a project and region before viewing instances.',
      invalid_request: 'The instance request is invalid.',
      invalid_page_size: 'The selected page size is not supported.',
      invalid_instance_filter: 'One or more instance filters are invalid.',
      page_cursor_unavailable: 'This instance page is no longer available. Returning to page 1.',
      page_cursor_changed: 'The instance pages changed. Returning to page 1.',
      instances_forbidden: 'You do not have permission to view instances in this project.',
      instances_not_found: 'The instance list is unavailable for this project.',
      instance_forbidden: 'You do not have permission to view this instance.',
      instance_not_found: 'This instance no longer exists in the active project.',
      instance_conflict: 'The instance changed while its details were loading. Try again.',
      instance_rate_limited: 'Instance data is temporarily rate limited. Try again shortly.',
      instance_unavailable: 'The compute service is temporarily unavailable.',
      instance_timeout: 'The compute service did not respond in time.',
    },
  },
  ko: {
    compute: '컴퓨트',
    instances: '인스턴스',
    description: '이 프로젝트의 가상 머신과 현재 상태를 확인합니다.',
    name: '이름',
    nameFilter: '이름으로 필터',
    status: '상태',
    allStatuses: '모든 상태',
    image: '이미지',
    imageId: '이미지 ID',
    imageFilter: '이미지 ID로 필터',
    flavor: 'Flavor',
    addresses: '주소',
    created: '생성 시각',
    sortBy: '정렬 기준',
    direction: '정렬 방향',
    createdSort: '생성 시각',
    nameSort: '이름',
    statusSort: '상태',
    ascending: '오름차순',
    descending: '내림차순',
    clearFilters: '필터 초기화',
    rows: '페이지당 행',
    page: '페이지',
    previousPage: '이전 페이지',
    nextPage: '다음 페이지',
    loading: '인스턴스를 불러오는 중...',
    loadFailed: '인스턴스를 불러올 수 없습니다',
    empty: '현재 필터에 맞는 인스턴스가 없습니다.',
    updating: '백그라운드에서 업데이트 중...',
    updated: '업데이트',
    stale: '마지막으로 확인한 데이터를 표시 중',
    requestReference: '요청 참조',
    openInstance: '인스턴스 상세 열기',
    details: '인스턴스 상세',
    close: '인스턴스 상세 닫기',
    overview: '개요',
    network: '네트워크',
    storage: '스토리지',
    id: 'ID',
    attachedVolumes: '연결된 볼륨',
    device: '장치',
    noAddresses: '연결된 주소 없음',
    noVolumes: '연결된 볼륨 없음',
    notAvailable: '사용할 수 없음',
    detailLoading: '인스턴스 상세를 불러오는 중...',
    detailFailed: '인스턴스 상세를 불러올 수 없습니다',
    problems: {
      active_scope_required: '인스턴스를 보려면 프로젝트와 리전을 선택하세요.',
      invalid_request: '인스턴스 요청 형식이 올바르지 않습니다.',
      invalid_page_size: '지원되지 않는 페이지 크기입니다.',
      invalid_instance_filter: '하나 이상의 인스턴스 필터가 올바르지 않습니다.',
      page_cursor_unavailable: '이 인스턴스 페이지를 더 이상 사용할 수 없습니다. 1페이지로 돌아갑니다.',
      page_cursor_changed: '인스턴스 페이지가 변경되었습니다. 1페이지로 돌아갑니다.',
      instances_forbidden: '이 프로젝트의 인스턴스를 볼 권한이 없습니다.',
      instances_not_found: '이 프로젝트의 인스턴스 목록을 사용할 수 없습니다.',
      instance_forbidden: '이 인스턴스를 볼 권한이 없습니다.',
      instance_not_found: '활성 프로젝트에 이 인스턴스가 더 이상 존재하지 않습니다.',
      instance_conflict: '상세 정보를 불러오는 동안 인스턴스가 변경되었습니다. 다시 시도하세요.',
      instance_rate_limited: '인스턴스 데이터 요청이 일시적으로 제한되었습니다. 잠시 후 다시 시도하세요.',
      instance_unavailable: '컴퓨트 서비스를 일시적으로 사용할 수 없습니다.',
      instance_timeout: '컴퓨트 서비스가 제시간에 응답하지 않았습니다.',
    },
  },
}

type Copy = typeof copy.en

function queryKey(query: InstanceQuery): string {
  return [
    query.limit,
    query.page,
    query.name,
    query.status,
    query.imageId,
    query.sort,
    query.direction,
  ].join(':')
}

function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError'
}

type Failure = { code?: string; references?: string[] }
type Snapshot<T> = { value: T; receivedAt: string; stale: boolean }

function failureInfo(cause: unknown): Failure {
  if (!(cause instanceof ApiError)) return {}
  const references = [
    cause.problem.openstack_request_id && `OpenStack ${cause.problem.openstack_request_id}`,
    cause.problem.trace_id && `Vantage ${cause.problem.trace_id}`,
  ].filter((reference): reference is string => Boolean(reference))
  return {
    code: cause.problem.code,
    references: references.length > 0 ? references : undefined,
  }
}

function isCursorFailure(cause: unknown): cause is ApiError {
  return cause instanceof ApiError
    && cause.status === 409
    && (cause.problem.code === 'page_cursor_unavailable' || cause.problem.code === 'page_cursor_changed')
}

function clearsSnapshot(cause: unknown): boolean {
  return cause instanceof ApiError && (cause.status === 403 || cause.status === 404)
}

function useRevalidatedResource<T>({
  key,
  loader,
  onError,
  onExpired,
}: {
  key: string
  loader: (signal: AbortSignal) => Promise<T>
  onError?: (cause: unknown) => ErrorResolution
  onExpired: () => void
}) {
  const loaderRef = useRef(loader)
  const onErrorRef = useRef(onError)
  const dataRef = useRef<Snapshot<T> | undefined>(undefined)
  const [data, setData] = useState<Snapshot<T>>()
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [failure, setFailure] = useState<Failure>()

  useEffect(() => {
    loaderRef.current = loader
    onErrorRef.current = onError
  }, [loader, onError])

  useEffect(() => {
    let disposed = false
    let current: AbortController | undefined

    async function refresh(allowRecovery = true) {
      if (disposed) return
      current?.abort()
      const controller = new AbortController()
      current = controller
      if (dataRef.current) setUpdating(true)
      else setLoading(true)
      setFailure(undefined)
      try {
        const value = await loaderRef.current(controller.signal)
        if (disposed || current !== controller) return
        const next = { value, receivedAt: new Date().toISOString(), stale: false }
        dataRef.current = next
        setData(next)
      } catch (cause) {
        if (disposed || current !== controller || isAbort(cause)) return
        if (cause instanceof ApiError && cause.status === 401) {
          onExpired()
          return
        }
        const resolution = allowRecovery ? onErrorRef.current?.(cause) : undefined
        if (resolution === 'handled') return
        if (resolution === 'retry') {
          void refresh(false)
          return
        }
        if (clearsSnapshot(cause)) {
          dataRef.current = undefined
          setData(undefined)
        } else if (dataRef.current) {
          const stale = { ...dataRef.current, stale: true }
          dataRef.current = stale
          setData(stale)
        }
        setFailure(failureInfo(cause))
      } finally {
        if (!disposed && current === controller) {
          setLoading(false)
          setUpdating(false)
        }
      }
    }

    void refresh()
    const interval = window.setInterval(() => void refresh(), 30_000)
    const handleFocus = () => void refresh()
    window.addEventListener('focus', handleFocus)
    return () => {
      disposed = true
      current?.abort()
      window.clearInterval(interval)
      window.removeEventListener('focus', handleFocus)
    }
  }, [key, onExpired])

  return { data, loading, updating, failure }
}

function ErrorNotice({ failure, fallback, t }: { failure?: Failure; fallback: string; t: Copy }) {
  if (!failure) return null
  const localized = failure.code
    ? t.problems[failure.code as keyof Copy['problems']]
    : undefined
  return (
    <div className="error instance-error" role="alert">
      <span>{localized ?? fallback}</span>
      {failure.references && <small>{t.requestReference}: {failure.references.join(' / ')}</small>}
    </div>
  )
}

export function InstancesPage({
  scopeKey,
  locale,
  query,
  selectedId,
  onQuery,
  onOpen,
  onClose,
  onExpired,
}: {
  scopeKey: string
  locale: Locale
  query: InstanceQuery
  selectedId?: string
  onQuery: (query: InstanceQuery, mode: HistoryMode) => void
  onOpen: (instanceId: string) => void
  onClose: () => void
  onExpired: () => void
}) {
  const t = copy[locale]
  const opener = useRef<HTMLElement | null>(null)
  const wasOpen = useRef(false)
  const backgroundScroll = useRef({ left: window.scrollX, top: window.scrollY })

  useEffect(() => {
    if (!wasOpen.current && selectedId) {
      backgroundScroll.current = { left: window.scrollX, top: window.scrollY }
    } else if (wasOpen.current && !selectedId) {
      const position = backgroundScroll.current
      const target = opener.current
      const restoreBackground = () => {
        window.scrollTo(position)
        if (target?.isConnected) target.focus()
      }
      if (typeof window.requestAnimationFrame === 'function') {
        const frame = window.requestAnimationFrame(restoreBackground)
        wasOpen.current = false
        return () => window.cancelAnimationFrame(frame)
      }
      const timer = window.setTimeout(restoreBackground, 0)
      wasOpen.current = false
      return () => window.clearTimeout(timer)
    }
    wasOpen.current = Boolean(selectedId)
  }, [selectedId])

  function change(patch: Partial<InstanceQuery>, mode: HistoryMode = 'replace') {
    onQuery({ ...query, ...patch, page: patch.page ?? 1 }, mode)
  }

  function open(instanceId: string, element: HTMLElement) {
    opener.current = element
    backgroundScroll.current = { left: window.scrollX, top: window.scrollY }
    onOpen(instanceId)
  }

  return (
    <>
      <div className="page-heading instance-heading">
        <div>
          <p className="eyebrow compact">{t.compute}</p>
          <h1>{t.instances}</h1>
          <p className="muted">{t.description}</p>
        </div>
      </div>
      <InstanceFilters
        key={`${query.name}\u0000${query.imageId}`}
        query={query}
        t={t}
        onQuery={onQuery}
      />
      <InstanceInventory
        key={`${scopeKey}:${queryKey(query)}`}
        scopeKey={scopeKey}
        locale={locale}
        query={query}
        t={t}
        onPage={(page) => change({ page }, 'push')}
        onPageSize={(limit) => change({ limit })}
        onCursorReset={() => change({ page: 1 }, 'replace')}
        onOpen={open}
        onExpired={onExpired}
      />
      {selectedId && (
        <InstanceDrawer
          key={`${scopeKey}:${selectedId}`}
          scopeKey={scopeKey}
          instanceId={selectedId}
          locale={locale}
          t={t}
          onClose={onClose}
          onExpired={onExpired}
        />
      )}
    </>
  )
}

function InstanceFilters({
  query,
  t,
  onQuery,
}: {
  query: InstanceQuery
  t: Copy
  onQuery: (query: InstanceQuery, mode: HistoryMode) => void
}) {
  const [pendingName, setPendingName] = useState(query.name)
  const [pendingImageId, setPendingImageId] = useState(query.imageId)

  useEffect(() => {
    if (pendingName === query.name && pendingImageId === query.imageId) return
    const timer = window.setTimeout(() => {
      onQuery({
        ...query,
        page: 1,
        name: pendingName,
        imageId: pendingImageId,
      }, 'replace')
    }, 300)
    return () => window.clearTimeout(timer)
  }, [onQuery, pendingImageId, pendingName, query])

  function immediate(patch: Partial<InstanceQuery>) {
    onQuery({ ...query, ...patch, page: 1 }, 'replace')
  }

  const hasFilters = Boolean(
    pendingName
    || query.status
    || pendingImageId
    || query.sort !== DEFAULT_INSTANCE_QUERY.sort
    || query.direction !== DEFAULT_INSTANCE_QUERY.direction,
  )

  return (
    <section className="instance-filters" aria-label={t.instances}>
      <label>
        {t.name}
        <input
          type="search"
          aria-label={t.nameFilter}
          value={pendingName}
          onChange={(event) => setPendingName(event.target.value)}
        />
      </label>
      <label>
        {t.status}
        <select value={query.status} onChange={(event) => immediate({ status: event.target.value })}>
          <option value="">{t.allStatuses}</option>
          {STATUSES.map((status) => <option key={status}>{status}</option>)}
        </select>
      </label>
      <label>
        {t.imageId}
        <input
          type="search"
          aria-label={t.imageFilter}
          value={pendingImageId}
          onChange={(event) => setPendingImageId(event.target.value)}
        />
      </label>
      <label>
        {t.sortBy}
        <select
          value={query.sort}
          onChange={(event) => immediate({ sort: event.target.value as InstanceSort })}
        >
          <option value="created_at">{t.createdSort}</option>
          <option value="name">{t.nameSort}</option>
          <option value="status">{t.statusSort}</option>
        </select>
      </label>
      <label>
        {t.direction}
        <select
          value={query.direction}
          onChange={(event) => immediate({ direction: event.target.value as SortDirection })}
        >
          <option value="desc">{t.descending}</option>
          <option value="asc">{t.ascending}</option>
        </select>
      </label>
      {hasFilters && (
        <button
          type="button"
          className="secondary clear-instance-filters"
          onClick={() => {
            setPendingName('')
            setPendingImageId('')
            onQuery({ ...DEFAULT_INSTANCE_QUERY, limit: query.limit }, 'replace')
          }}
        >
          {t.clearFilters}
        </button>
      )}
    </section>
  )
}

function InstanceInventory({
  scopeKey,
  locale,
  query,
  t,
  onPage,
  onPageSize,
  onCursorReset,
  onOpen,
  onExpired,
}: {
  scopeKey: string
  locale: Locale
  query: InstanceQuery
  t: Copy
  onPage: (page: number) => void
  onPageSize: (limit: InstanceQuery['limit']) => void
  onCursorReset: () => void
  onOpen: (instanceId: string, element: HTMLElement) => void
  onExpired: () => void
}) {
  const { data, loading, updating, failure } = useRevalidatedResource<InstancePage>({
    key: `${scopeKey}:${queryKey(query)}`,
    loader: (signal) => api.instances(query, signal),
    onError: (cause) => {
      if (!isCursorFailure(cause)) return undefined
      if (query.page === 1) return 'retry'
      onCursorReset()
      return 'handled'
    },
    onExpired,
  })
  const page = data?.value

  return (
    <section className="instance-inventory" aria-labelledby="instance-inventory-heading">
      <div className="instance-inventory-status">
        <h2 id="instance-inventory-heading" className="visually-hidden">{t.instances}</h2>
        <p className={`sync-status${data?.stale ? ' stale' : ''}`} aria-live="polite">
          {updating
            ? t.updating
            : data
              ? <>{data.stale ? t.stale : t.updated} <time dateTime={data.receivedAt}>{formatDate(data.receivedAt, locale)}</time></>
              : null}
        </p>
      </div>
      <ErrorNotice failure={failure} fallback={t.loadFailed} t={t} />
      {loading && !page && <LoadingState label={t.loading} />}
      {page && page.items.length === 0 && <p className="empty-state instance-empty">{t.empty}</p>}
      {page && page.items.length > 0 && (
        <InstanceTable items={page.items} locale={locale} t={t} onOpen={onOpen} />
      )}
      {page && (
        <>
          <Pagination
            page={page.page}
            pageSize={query.limit}
            labels={t}
            onPage={onPage}
            onPageSize={onPageSize}
          />
          {page.page.openstack_request_id && (
            <p className="request-reference">
              {t.requestReference}: OpenStack {page.page.openstack_request_id}
            </p>
          )}
        </>
      )}
    </section>
  )
}

function InstanceTable({
  items,
  locale,
  t,
  onOpen,
}: {
  items: Instance[]
  locale: Locale
  t: Copy
  onOpen: (instanceId: string, element: HTMLElement) => void
}) {
  function openFromRow(instanceId: string, event: ReactMouseEvent<HTMLElement>) {
    onOpen(instanceId, event.currentTarget)
  }

  function openFromKeyboard(instanceId: string, event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    onOpen(instanceId, event.currentTarget)
  }

  return (
    <div className="instance-table" role="table" aria-label={t.instances}>
      <div className="instance-table-header" role="row">
        {[t.name, t.status, t.flavor, t.image, t.addresses, t.created].map((label) => (
          <span role="columnheader" key={label}>{label}</span>
        ))}
      </div>
      {items.map((instance) => {
        const accessibleName = instance.name?.trim() || instance.id
        return (
          <div
            className="instance-table-row"
            role="row"
            tabIndex={0}
            aria-label={`${t.openInstance}: ${accessibleName}`}
            key={instance.id}
            onClick={(event) => openFromRow(instance.id, event)}
            onKeyDown={(event) => openFromKeyboard(instance.id, event)}
          >
            <span role="cell" data-label={t.name} className="instance-name-cell">
              <button
                type="button"
                className="instance-name-button"
                aria-label={`${t.openInstance}: ${accessibleName}`}
                onClick={(event) => {
                  event.stopPropagation()
                  onOpen(instance.id, event.currentTarget)
                }}
              >
                {instance.name?.trim() || t.notAvailable}
              </button>
              <small>{instance.id}</small>
            </span>
            <span role="cell" data-label={t.status}>
              <Status value={instance.status} t={t} />
            </span>
            <span role="cell" data-label={t.flavor}>{textOrFallback(instance.flavor, t)}</span>
            <span role="cell" data-label={t.image}>{textOrFallback(instance.image, t)}</span>
            <span role="cell" data-label={t.addresses}>
              <AddressSummary addresses={instance.addresses} t={t} />
            </span>
            <span role="cell" data-label={t.created}>
              {instance.created_at ? formatDate(instance.created_at, locale) : t.notAvailable}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function InstanceDrawer({
  scopeKey,
  instanceId,
  locale,
  t,
  onClose,
  onExpired,
}: {
  scopeKey: string
  instanceId: string
  locale: Locale
  t: Copy
  onClose: () => void
  onExpired: () => void
}) {
  const [tab, setTab] = useState<DetailTab>('overview')
  const closeButton = useRef<HTMLButtonElement>(null)
  const drawer = useRef<HTMLElement>(null)
  const tabButtons = useRef<Partial<Record<DetailTab, HTMLButtonElement | null>>>({})
  const { data, loading, updating, failure } = useRevalidatedResource<InstanceDetail>({
    key: `${scopeKey}:${instanceId}`,
    loader: (signal) => api.instance(instanceId, signal),
    onExpired,
  })
  const instance = data?.value
  const title = instance?.name?.trim() || instance?.id || t.details

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !drawer.current) return
      const focusable = Array.from(drawer.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  function handleTabKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>, current: DetailTab) {
    const currentIndex = DETAIL_TABS.indexOf(current)
    let next: DetailTab | undefined
    if (event.key === 'ArrowRight') next = DETAIL_TABS[(currentIndex + 1) % DETAIL_TABS.length]
    else if (event.key === 'ArrowLeft') {
      next = DETAIL_TABS[(currentIndex - 1 + DETAIL_TABS.length) % DETAIL_TABS.length]
    } else if (event.key === 'Home') next = DETAIL_TABS[0]
    else if (event.key === 'End') next = DETAIL_TABS[DETAIL_TABS.length - 1]
    if (!next) return
    event.preventDefault()
    setTab(next)
    tabButtons.current[next]?.focus()
  }

  return (
    <div
      className="instance-drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        ref={drawer}
        className="instance-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="instance-drawer-title"
      >
        <header className="instance-drawer-header">
          <div>
            <p className="eyebrow compact">{t.details}</p>
            <h2 id="instance-drawer-title">{title}</h2>
            {instance && <Status value={instance.status} t={t} />}
          </div>
          <button
            ref={closeButton}
            type="button"
            className="drawer-close secondary"
            aria-label={t.close}
            title={t.close}
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="drawer-sync" aria-live="polite">
          {updating && <span>{t.updating}</span>}
          {!updating && data?.stale && <span className="stale">{t.stale}</span>}
        </div>
        <ErrorNotice failure={failure} fallback={t.detailFailed} t={t} />
        {loading && !instance && <LoadingState label={t.detailLoading} />}
        {instance && (
          <>
            <div className="drawer-tabs" role="tablist" aria-label={t.details}>
              {DETAIL_TABS.map((item) => (
                <button
                  ref={(element) => { tabButtons.current[item] = element }}
                  type="button"
                  role="tab"
                  id={`instance-tab-${item}`}
                  aria-controls={`instance-panel-${item}`}
                  aria-selected={tab === item}
                  tabIndex={tab === item ? 0 : -1}
                  className={tab === item ? 'active' : undefined}
                  key={item}
                  onClick={() => setTab(item)}
                  onKeyDown={(event) => handleTabKeyDown(event, item)}
                >
                  {t[item]}
                </button>
              ))}
            </div>
            {DETAIL_TABS.map((item) => (
              <div
                className="drawer-tab-panel"
                role="tabpanel"
                id={`instance-panel-${item}`}
                aria-labelledby={`instance-tab-${item}`}
                hidden={tab !== item}
                key={item}
              >
                {tab === item && item === 'overview' && (
                  <InstanceOverview instance={instance} locale={locale} t={t} />
                )}
                {tab === item && item === 'network' && <InstanceNetwork instance={instance} t={t} />}
                {tab === item && item === 'storage' && <InstanceStorage instance={instance} t={t} />}
              </div>
            ))}
            {instance.openstack_request_id && (
              <p className="request-reference drawer-request-reference">
                {t.requestReference}: OpenStack {instance.openstack_request_id}
              </p>
            )}
          </>
        )}
      </section>
    </div>
  )
}

function InstanceOverview({ instance, locale, t }: { instance: InstanceDetail; locale: Locale; t: Copy }) {
  return (
    <dl className="instance-details-list">
      <div><dt>{t.name}</dt><dd>{textOrFallback(instance.name, t)}</dd></div>
      <div><dt>{t.id}</dt><dd className="monospace">{instance.id}</dd></div>
      <div><dt>{t.status}</dt><dd><Status value={instance.status} t={t} /></dd></div>
      <div><dt>{t.created}</dt><dd>{instance.created_at ? formatDate(instance.created_at, locale) : t.notAvailable}</dd></div>
      <div><dt>{t.flavor}</dt><dd>{textOrFallback(instance.flavor, t)}</dd></div>
      <div><dt>{t.image}</dt><dd>{textOrFallback(instance.image, t)}</dd></div>
    </dl>
  )
}

function InstanceNetwork({ instance, t }: { instance: InstanceDetail; t: Copy }) {
  return (
    <section className="drawer-data-section drawer-data-section-first" aria-labelledby="instance-addresses-heading">
      <h3 id="instance-addresses-heading">{t.addresses}</h3>
      {instance.addresses === null
        ? <p>{t.notAvailable}</p>
        : instance.addresses.length === 0
          ? <p>{t.noAddresses}</p>
          : <ul>{instance.addresses.map((address, index) => <li key={`${address}:${index}`}>{address || t.notAvailable}</li>)}</ul>}
    </section>
  )
}

function InstanceStorage({ instance, t }: { instance: InstanceDetail; t: Copy }) {
  return (
    <section className="drawer-data-section drawer-data-section-first" aria-labelledby="instance-volumes-heading">
      <h3 id="instance-volumes-heading">{t.attachedVolumes}</h3>
      {instance.volumes === null
        ? <p>{t.notAvailable}</p>
        : instance.volumes.length === 0
          ? <p>{t.noVolumes}</p>
          : (
            <ul className="volume-list">
              {instance.volumes.map((volume) => (
                <li key={volume.id}>
                  <span className="monospace">{volume.id}</span>
                  <small>{t.device}: {textOrFallback(volume.device, t)}</small>
                </li>
              ))}
            </ul>
          )}
    </section>
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

function Status({ value, t }: { value: string; t: Copy }) {
  const label = value?.trim() || t.notAvailable
  const token = label.toLowerCase().replace(/[^a-z0-9]+/g, '-')
  return <span className={`instance-status status-${token}`}>{label}</span>
}

function AddressSummary({ addresses, t }: { addresses: string[] | null; t: Copy }) {
  if (addresses === null) return t.notAvailable
  if (addresses.length === 0) return t.noAddresses
  return (
    <span className="address-summary">
      {addresses.map((address, index) => <span key={`${address}:${index}`}>{address || t.notAvailable}</span>)}
    </span>
  )
}

function textOrFallback(value: string | null | undefined, t: Copy): string {
  return value?.trim() || t.notAvailable
}

function formatDate(value: string, locale: Locale): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(locale === 'ko' ? 'ko-KR' : 'en-US')
}
