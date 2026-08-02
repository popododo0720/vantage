import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, api } from './api'
import { Pagination } from './Pagination'
import type {
  Image,
  ImagePage,
  ImageQuery,
  ImageVisibility,
  InventoryQuery,
  KeyPair,
  KeyPairPage,
  PageInfo,
} from './types'

type Locale = 'en' | 'ko'
type HistoryMode = 'push' | 'replace'
type Failure = { code?: string; references?: string[] }
type Snapshot<T> = { value: T; receivedAt: string; stale: boolean }

const copy = {
  en: {
    compute: 'Compute', access: 'Access', images: 'Images', keypairs: 'Key pairs',
    name: 'Name', nameFilter: 'Filter by name', visibility: 'Visibility',
    allVisibilities: 'All visibilities', status: 'Status', format: 'Format', size: 'Size',
    minimums: 'Minimum requirements', created: 'Created', type: 'Type',
    fingerprint: 'Fingerprint', publicKey: 'Public key preview', lastUsed: 'Last used',
    filters: 'Filters',
    clearFilters: 'Clear filters', rows: 'Rows per page', page: 'Page',
    previousPage: 'Previous page', nextPage: 'Next page',
    loadingImages: 'Loading images...', loadingKeypairs: 'Loading key pairs...',
    imageLoadFailed: 'Unable to load images', keypairLoadFailed: 'Unable to load key pairs',
    emptyImages: 'No images match the current filters.',
    emptyKeypairs: 'No key pairs match the current filters.',
    updating: 'Updating in the background...', updated: 'Updated',
    stale: 'Showing the last available data', requestReference: 'Request reference',
    notAvailable: 'Not available', disk: 'disk', ram: 'RAM',
    problems: {
      page_cursor_unavailable: 'This page is no longer available. Returning to page 1.',
      page_cursor_changed: 'The pages changed. Returning to page 1.',
      images_forbidden: 'You do not have permission to view images in this project.',
      images_not_found: 'The image list is unavailable for this project.',
      keypairs_forbidden: 'You do not have permission to view key pairs in this project.',
      keypairs_not_found: 'The key pair list is unavailable for this project.',
    },
  },
  ko: {
    compute: '컴퓨트', access: '접근', images: '이미지', keypairs: '키 페어',
    name: '이름', nameFilter: '이름으로 필터', visibility: '공개 범위',
    allVisibilities: '모든 공개 범위', status: '상태', format: '형식', size: '크기',
    minimums: '최소 요구 사항', created: '생성 시각', type: '유형',
    fingerprint: '지문', publicKey: '공개 키 미리보기', lastUsed: '마지막 사용',
    filters: '필터',
    clearFilters: '필터 초기화', rows: '페이지당 행', page: '페이지',
    previousPage: '이전 페이지', nextPage: '다음 페이지',
    loadingImages: '이미지를 불러오는 중...', loadingKeypairs: '키 페어를 불러오는 중...',
    imageLoadFailed: '이미지를 불러올 수 없습니다', keypairLoadFailed: '키 페어를 불러올 수 없습니다',
    emptyImages: '현재 필터와 일치하는 이미지가 없습니다.',
    emptyKeypairs: '현재 필터와 일치하는 키 페어가 없습니다.',
    updating: '백그라운드에서 업데이트 중...', updated: '업데이트됨',
    stale: '마지막으로 확인된 데이터 표시 중', requestReference: '요청 참조',
    notAvailable: '사용할 수 없음', disk: '디스크', ram: 'RAM',
    problems: {
      page_cursor_unavailable: '이 페이지를 더 이상 사용할 수 없습니다. 1페이지로 돌아갑니다.',
      page_cursor_changed: '페이지가 변경되었습니다. 1페이지로 돌아갑니다.',
      images_forbidden: '이 프로젝트의 이미지를 볼 권한이 없습니다.',
      images_not_found: '이 프로젝트의 이미지 목록을 사용할 수 없습니다.',
      keypairs_forbidden: '이 프로젝트의 키 페어를 볼 권한이 없습니다.',
      keypairs_not_found: '이 프로젝트의 키 페어 목록을 사용할 수 없습니다.',
    },
  },
}
type Copy = typeof copy.en

function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError'
}

function isCursorFailure(cause: unknown): cause is ApiError {
  return cause instanceof ApiError && cause.status === 409
    && (cause.problem.code === 'page_cursor_unavailable' || cause.problem.code === 'page_cursor_changed')
}

function failureInfo(cause: unknown): Failure {
  if (!(cause instanceof ApiError)) return {}
  const references = [
    cause.problem.openstack_request_id && `OpenStack ${cause.problem.openstack_request_id}`,
    cause.problem.trace_id && `Vantage ${cause.problem.trace_id}`,
  ].filter((reference): reference is string => Boolean(reference))
  return { code: cause.problem.code, references: references.length ? references : undefined }
}

function useInventory<T>({
  queryKey, loader, onCursorReset, onExpired,
}: {
  queryKey: string
  loader: (signal: AbortSignal) => Promise<T>
  onCursorReset: () => void
  onExpired: () => void
}) {
  const loaderRef = useRef(loader)
  const cursorResetRef = useRef(onCursorReset)
  const expiredRef = useRef(onExpired)
  const keyRef = useRef(queryKey)
  const dataRef = useRef<Snapshot<T> | undefined>(undefined)
  const [data, setData] = useState<Snapshot<T>>()
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [failure, setFailure] = useState<Failure>()

  useEffect(() => {
    loaderRef.current = loader
    cursorResetRef.current = onCursorReset
    expiredRef.current = onExpired
  }, [loader, onCursorReset, onExpired])
  useEffect(() => {
    let disposed = false
    let current: AbortController | undefined
    if (keyRef.current !== queryKey) {
      keyRef.current = queryKey
      dataRef.current = undefined
      setData(undefined)
    }
    async function refresh() {
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
          expiredRef.current()
        } else if (isCursorFailure(cause)) {
          cursorResetRef.current()
        } else {
          if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
            dataRef.current = undefined
            setData(undefined)
          } else if (dataRef.current) {
            const stale = { ...dataRef.current, stale: true }
            dataRef.current = stale
            setData(stale)
          }
          setFailure(failureInfo(cause))
        }
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
  }, [queryKey])

  return { data, loading, updating, failure }
}

function ErrorNotice({ failure, fallback, t }: { failure?: Failure; fallback: string; t: Copy }) {
  if (!failure) return null
  const message = failure.code
    ? t.problems[failure.code as keyof Copy['problems']]
    : undefined
  return (
    <div className="error inventory-error" role="alert">
      <span>{message ?? fallback}</span>
      {failure.references && <small>{t.requestReference}: {failure.references.join(' / ')}</small>}
    </div>
  )
}

function InventoryHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="page-heading inventory-heading">
      <div><p className="eyebrow compact">{eyebrow}</p><h1>{title}</h1></div>
      <div className="inventory-command-area" aria-hidden="true" />
    </div>
  )
}

function Filters({
  name, visibility, t, onChange,
}: {
  name: string
  visibility?: ImageVisibility
  t: Copy
  onChange: (name: string, visibility?: ImageVisibility) => void
}) {
  const [pendingName, setPendingName] = useState(name)
  useEffect(() => {
    if (pendingName === name) return
    const timer = window.setTimeout(() => onChange(pendingName, visibility), 300)
    return () => window.clearTimeout(timer)
  }, [name, onChange, pendingName, visibility])
  const active = Boolean(pendingName || visibility)
  return (
    <section className="inventory-filters" aria-label={t.filters}>
      <label>{t.name}<input type="search" aria-label={t.nameFilter} value={pendingName}
        onChange={(event) => setPendingName(event.target.value)} /></label>
      {visibility !== undefined && (
        <label>{t.visibility}<select value={visibility}
          onChange={(event) => onChange(pendingName, event.target.value as ImageVisibility)}>
          <option value="">{t.allVisibilities}</option>
          {['public', 'private', 'shared', 'community'].map((value) => <option key={value}>{value}</option>)}
        </select></label>
      )}
      {active && <button type="button" className="secondary" onClick={() => {
        setPendingName('')
        onChange('', visibility === undefined ? undefined : '')
      }}>{t.clearFilters}</button>}
    </section>
  )
}

function Status({ updating, data, locale, t }: {
  updating: boolean
  data?: Snapshot<unknown>
  locale: Locale
  t: Copy
}) {
  return <p className={`sync-status${data?.stale ? ' stale' : ''}`} aria-live="polite">
    {updating ? t.updating : data ? <>{data.stale ? t.stale : t.updated} <time dateTime={data.receivedAt}>{formatDate(data.receivedAt, locale)}</time></> : null}
  </p>
}

function InventoryShell({ children, page, query, t, onPage, onLimit }: {
  children: ReactNode
  page?: PageInfo
  query: InventoryQuery
  t: Copy
  onPage: (page: number) => void
  onLimit: (limit: InventoryQuery['limit']) => void
}) {
  return <section className="resource-inventory">
    {children}
    {page && <Pagination page={page} pageSize={query.limit} labels={t}
      onPage={onPage} onPageSize={onLimit} />}
  </section>
}

export function ImagesPage({ scopeKey, locale, query, onQuery, onExpired }: {
  scopeKey: string
  locale: Locale
  query: ImageQuery
  onQuery: (query: ImageQuery, mode: HistoryMode) => void
  onExpired: () => void
}) {
  const t = copy[locale]
  const change = (patch: Partial<ImageQuery>, mode: HistoryMode = 'replace') =>
    onQuery({ ...query, ...patch, page: patch.page ?? 1 }, mode)
  const key = `${scopeKey}:${query.limit}:${query.page}:${query.name}:${query.visibility}`
  const { data, loading, updating, failure } = useInventory<ImagePage>({
    queryKey: key, loader: (signal) => api.images(query, signal),
    onCursorReset: () => change({ page: 1 }), onExpired,
  })
  return <>
    <InventoryHeading eyebrow={t.compute} title={t.images} />
    <Filters key={`${query.name}:${query.visibility}`} name={query.name} visibility={query.visibility} t={t}
      onChange={(name, visibility = '') => change({ name, visibility })} />
    <InventoryShell page={data?.value.page} query={query} t={t}
      onPage={(page) => change({ page }, 'push')} onLimit={(limit) => change({ limit })}>
      <Status updating={updating} data={data} locale={locale} t={t} />
      <ErrorNotice failure={failure} fallback={t.imageLoadFailed} t={t} />
      {loading && !data && <div className="loading-state" role="status">{t.loadingImages}</div>}
      {data && (data.value.items.length ? <ImageTable items={data.value.items} locale={locale} t={t} />
        : <p className="empty-state">{t.emptyImages}</p>)}
    </InventoryShell>
  </>
}

function ImageTable({ items, locale, t }: { items: Image[]; locale: Locale; t: Copy }) {
  const columns = [t.name, t.status, t.visibility, t.format, t.size, t.minimums, t.created]
  return <div className="resource-table image-table" role="table" aria-label={t.images}>
    <div className="resource-table-header" role="row">{columns.map((label) => <span role="columnheader" key={label}>{label}</span>)}</div>
    {items.map((item) => <div className="resource-table-row" role="row" key={item.id}>
      <span role="cell" data-label={t.name}><strong>{item.name || t.notAvailable}</strong><small>{item.id}</small></span>
      <span role="cell" data-label={t.status}><span className="instance-status">{item.status || t.notAvailable}</span></span>
      <span role="cell" data-label={t.visibility}>{item.visibility || t.notAvailable}</span>
      <span role="cell" data-label={t.format}>{formatImage(item, t)}</span>
      <span role="cell" data-label={t.size}>{formatBytes(item.size_bytes, locale, t)}</span>
      <span role="cell" data-label={t.minimums}>{formatMinimums(item, locale, t)}</span>
      <span role="cell" data-label={t.created}>{optionalDate(item.created_at, locale, t)}</span>
    </div>)}
  </div>
}

export function KeyPairsPage({ scopeKey, locale, query, onQuery, onExpired }: {
  scopeKey: string
  locale: Locale
  query: InventoryQuery
  onQuery: (query: InventoryQuery, mode: HistoryMode) => void
  onExpired: () => void
}) {
  const t = copy[locale]
  const change = (patch: Partial<InventoryQuery>, mode: HistoryMode = 'replace') =>
    onQuery({ ...query, ...patch, page: patch.page ?? 1 }, mode)
  const key = `${scopeKey}:${query.limit}:${query.page}`
  const { data, loading, updating, failure } = useInventory<KeyPairPage>({
    queryKey: key, loader: (signal) => api.keypairs(query, signal),
    onCursorReset: () => change({ page: 1 }), onExpired,
  })
  return <>
    <InventoryHeading eyebrow={t.access} title={t.keypairs} />
    <InventoryShell page={data?.value.page} query={query} t={t}
      onPage={(page) => change({ page }, 'push')} onLimit={(limit) => change({ limit })}>
      <Status updating={updating} data={data} locale={locale} t={t} />
      <ErrorNotice failure={failure} fallback={t.keypairLoadFailed} t={t} />
      {loading && !data && <div className="loading-state" role="status">{t.loadingKeypairs}</div>}
      {data && (data.value.items.length ? <KeyPairTable items={data.value.items} locale={locale} t={t} />
        : <p className="empty-state">{t.emptyKeypairs}</p>)}
    </InventoryShell>
  </>
}

function KeyPairTable({ items, locale, t }: { items: KeyPair[]; locale: Locale; t: Copy }) {
  const columns = [t.name, t.type, t.fingerprint, t.publicKey, t.created, t.lastUsed]
  return <div className="resource-table keypair-table" role="table" aria-label={t.keypairs}>
    <div className="resource-table-header" role="row">{columns.map((label) => <span role="columnheader" key={label}>{label}</span>)}</div>
    {items.map((item) => <div className="resource-table-row" role="row" key={item.name}>
      <span role="cell" data-label={t.name}><strong>{item.name}</strong></span>
      <span role="cell" data-label={t.type}>{item.type || t.notAvailable}</span>
      <span role="cell" data-label={t.fingerprint}><code>{item.fingerprint || t.notAvailable}</code></span>
      <span role="cell" data-label={t.publicKey}><code>{item.public_key_preview || t.notAvailable}</code></span>
      <span role="cell" data-label={t.created}>{optionalDate(item.created_at, locale, t)}</span>
      <span role="cell" data-label={t.lastUsed}>{optionalDate(item.last_used_at, locale, t)}</span>
    </div>)}
  </div>
}

function formatImage(item: Image, t: Copy): string {
  return [item.disk_format, item.container_format].filter(Boolean).join(' / ') || t.notAvailable
}

function formatBytes(value: number | null | undefined, locale: Locale, t: Copy): string {
  if (value === null || value === undefined) return t.notAvailable
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let amount = value
  let unit = 0
  while (Math.abs(amount) >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  return `${new Intl.NumberFormat(locale === 'ko' ? 'ko-KR' : 'en-US', { maximumFractionDigits: 1 }).format(amount)} ${units[unit]}`
}

function formatMinimums(item: Image, locale: Locale, t: Copy): string {
  const number = new Intl.NumberFormat(locale === 'ko' ? 'ko-KR' : 'en-US')
  const values = [
    item.min_disk_gib != null && `${number.format(item.min_disk_gib)} GiB ${t.disk}`,
    item.min_ram_mib != null && `${number.format(item.min_ram_mib)} MiB ${t.ram}`,
  ].filter((value): value is string => Boolean(value))
  return values.join(' / ') || t.notAvailable
}

function optionalDate(value: string | null | undefined, locale: Locale, t: Copy): string {
  return value ? formatDate(value, locale) : t.notAvailable
}

function formatDate(value: string, locale: Locale): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale === 'ko' ? 'ko-KR' : 'en-US')
}
