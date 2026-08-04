import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode, RefObject } from 'react'
import { ApiError, api } from './api'
import { Pagination } from './Pagination'
import type {
  Image,
  ImagePage,
  ImageQuery,
  ImageVisibility,
  InventoryQuery,
  KeyPair,
  KeyPairMode,
  KeyPairPage,
  KeyPairType,
  Operation,
  PageInfo,
} from './types'

type Locale = 'en' | 'ko'
type HistoryMode = 'push' | 'replace'
type Failure = { code?: string; references?: string[] }
type MutationFailure = Failure & { message: string }
type ActionNotice = { message: string; references?: string[] }
type Snapshot<T> = { value: T; receivedAt: string; stale: boolean }

const copy = {
  en: {
    compute: 'Compute', access: 'Access', images: 'Images', keypairs: 'Key pairs',
    name: 'Name', nameFilter: 'Filter by name', visibility: 'Visibility',
    allVisibilities: 'All visibilities', status: 'Status', format: 'Format', size: 'Size',
    minimums: 'Minimum requirements', created: 'Created', type: 'Type',
    fingerprint: 'Fingerprint', publicKey: 'Public key preview', lastUsed: 'Last used',
    filters: 'Filters',
    actions: 'Actions', manageKeypairs: 'Import or generate', createKeypair: 'Add a key pair',
    close: 'Close', cancel: 'Cancel', done: 'Done', generate: 'Generate', import: 'Import',
    creationMode: 'Key pair method', keyType: 'Key type', publicMaterial: 'Public key or certificate',
    sshPublicKey: 'SSH public key', x509Certificate: 'X.509 certificate',
    generateKeypair: 'Generate key pair', importKeypair: 'Import key pair',
    generating: 'Generating...', importing: 'Importing...', nameRequired: 'Enter a name.',
    publicMaterialRequired: 'Enter a public key or certificate.',
    privateKeyTitle: 'Save the private key now', privateKey: 'Private key',
    privateKeyOnce: 'This private key is shown once. Store it securely before closing.',
    copyPrivateKey: 'Copy private key', copied: 'Copied',
    copyFailed: 'Copy failed. Select the key and copy it manually.',
    keypairGenerated: 'Key pair generated.', keypairImportAccepted: 'Key pair import requested.',
    delete: 'Delete', deleteKeypair: 'Delete key pair',
    deleteWarning: 'This removes the key pair from the project. Existing instances are not changed.',
    confirmName: 'Type the key pair name to confirm', deleting: 'Deleting...',
    keypairDeleteAccepted: 'Key pair deletion requested.',
    createFailed: 'Unable to create the key pair.', deleteFailed: 'Unable to delete the key pair.',
    mutationForbidden: 'You do not have permission to manage key pairs in this project.',
    mutationNotFound: 'The requested key pair is no longer available.',
    mutationConflict: 'A key pair with this name already exists, or the request conflicts with its current state.',
    mutationRateLimited: 'Too many requests. Wait a moment and try again.',
    mutationUnavailable: 'The key pair service is temporarily unavailable. Try again shortly.',
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
    actions: '작업', manageKeypairs: '가져오기 또는 생성', createKeypair: '키 페어 추가',
    close: '닫기', cancel: '취소', done: '완료', generate: '생성', import: '가져오기',
    creationMode: '키 페어 방식', keyType: '키 유형', publicMaterial: '공개 키 또는 인증서',
    sshPublicKey: 'SSH 공개 키', x509Certificate: 'X.509 인증서',
    generateKeypair: '키 페어 생성', importKeypair: '키 페어 가져오기',
    generating: '생성 중...', importing: '가져오는 중...', nameRequired: '이름을 입력하세요.',
    publicMaterialRequired: '공개 키 또는 인증서를 입력하세요.',
    privateKeyTitle: '지금 개인 키를 저장하세요', privateKey: '개인 키',
    privateKeyOnce: '이 개인 키는 지금 한 번만 표시됩니다. 닫기 전에 안전한 곳에 저장하세요.',
    copyPrivateKey: '개인 키 복사', copied: '복사됨',
    copyFailed: '복사하지 못했습니다. 키를 선택하여 직접 복사하세요.',
    keypairGenerated: '키 페어를 생성했습니다.', keypairImportAccepted: '키 페어 가져오기를 요청했습니다.',
    delete: '삭제', deleteKeypair: '키 페어 삭제',
    deleteWarning: '프로젝트에서 키 페어를 삭제합니다. 기존 인스턴스는 변경되지 않습니다.',
    confirmName: '확인하려면 키 페어 이름을 입력하세요', deleting: '삭제 중...',
    keypairDeleteAccepted: '키 페어 삭제를 요청했습니다.',
    createFailed: '키 페어를 만들지 못했습니다.', deleteFailed: '키 페어를 삭제하지 못했습니다.',
    mutationForbidden: '이 프로젝트의 키 페어를 관리할 권한이 없습니다.',
    mutationNotFound: '요청한 키 페어를 더 이상 사용할 수 없습니다.',
    mutationConflict: '같은 이름의 키 페어가 이미 있거나 현재 상태와 요청이 충돌합니다.',
    mutationRateLimited: '요청이 너무 많습니다. 잠시 후 다시 시도하세요.',
    mutationUnavailable: '키 페어 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도하세요.',
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

function mutationFailure(cause: unknown, fallback: string, t: Copy): MutationFailure {
  const details = failureInfo(cause)
  if (!(cause instanceof ApiError)) return { ...details, message: fallback }
  const messages: Partial<Record<number, string>> = {
    403: t.mutationForbidden,
    404: t.mutationNotFound,
    409: t.mutationConflict,
    429: t.mutationRateLimited,
    503: t.mutationUnavailable,
  }
  return { ...details, message: messages[cause.status] ?? fallback }
}

function operationReferences(operation?: Operation): string[] | undefined {
  if (!operation) return undefined
  const references = [
    ...(operation.openstack_request_ids ?? []).map((id) => `OpenStack ${id}`),
    operation.trace_id && `Vantage ${operation.trace_id}`,
  ].filter((reference): reference is string => Boolean(reference))
  return references.length ? references : undefined
}

function useInventory<T>({
  queryKey, refreshKey = 0, loader, onCursorReset, onExpired,
}: {
  queryKey: string
  refreshKey?: number
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
  }, [queryKey, refreshKey])

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

function InventoryHeading({ eyebrow, title, command }: {
  eyebrow: string
  title: string
  command?: ReactNode
}) {
  return (
    <div className="page-heading inventory-heading">
      <div><p className="eyebrow compact">{eyebrow}</p><h1>{title}</h1></div>
      <div className={`inventory-command-area${command ? ' has-command' : ''}`}
        aria-hidden={command ? undefined : true}>{command}</div>
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
  const [refreshKey, setRefreshKey] = useState(0)
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KeyPair>()
  const [notice, setNotice] = useState<ActionNotice>()
  const returnFocus = useRef<HTMLElement | null>(null)
  const change = (patch: Partial<InventoryQuery>, mode: HistoryMode = 'replace') =>
    onQuery({ ...query, ...patch, page: patch.page ?? 1 }, mode)
  const key = `${scopeKey}:${query.limit}:${query.page}`
  const { data, loading, updating, failure } = useInventory<KeyPairPage>({
    queryKey: key, refreshKey, loader: (signal) => api.keypairs(query, signal),
    onCursorReset: () => change({ page: 1 }), onExpired,
  })

  function actionSucceeded(message: string, operation?: Operation) {
    setNotice({ message, references: operationReferences(operation) })
    setRefreshKey((value) => value + 1)
  }

  return <>
    <InventoryHeading eyebrow={t.access} title={t.keypairs} command={(
      <button type="button" className="keypair-create-button" onClick={(event) => {
        returnFocus.current = event.currentTarget
        setNotice(undefined)
        setCreateOpen(true)
      }}><span aria-hidden="true">+</span>{t.manageKeypairs}</button>
    )} />
    <InventoryShell page={data?.value.page} query={query} t={t}
      onPage={(page) => change({ page }, 'push')} onLimit={(limit) => change({ limit })}>
      {notice && <div className="success inventory-success" role="status">
        <span>{notice.message}</span>
        {notice.references && <small>{t.requestReference}: {notice.references.join(' / ')}</small>}
      </div>}
      <Status updating={updating} data={data} locale={locale} t={t} />
      <ErrorNotice failure={failure} fallback={t.keypairLoadFailed} t={t} />
      {loading && !data && <div className="loading-state" role="status">{t.loadingKeypairs}</div>}
      {data && (data.value.items.length ? <KeyPairTable items={data.value.items} locale={locale} t={t}
        onDelete={(item, trigger) => {
          returnFocus.current = trigger
          setNotice(undefined)
          setDeleteTarget(item)
        }} />
        : <p className="empty-state">{t.emptyKeypairs}</p>)}
    </InventoryShell>
    {createOpen && <CreateKeyPairModal t={t} returnFocus={returnFocus}
      onExpired={onExpired} onClose={() => setCreateOpen(false)} onSuccess={actionSucceeded} />}
    {deleteTarget && <DeleteKeyPairModal item={deleteTarget} t={t} returnFocus={returnFocus}
      onExpired={onExpired} onClose={() => setDeleteTarget(undefined)} onSuccess={actionSucceeded} />}
  </>
}

function KeyPairTable({ items, locale, t, onDelete }: {
  items: KeyPair[]
  locale: Locale
  t: Copy
  onDelete: (item: KeyPair, trigger: HTMLButtonElement) => void
}) {
  const columns = [t.name, t.type, t.fingerprint, t.publicKey, t.created, t.lastUsed, t.actions]
  return <div className="resource-table keypair-table" role="table" aria-label={t.keypairs}>
    <div className="resource-table-header" role="row">{columns.map((label) => <span role="columnheader" key={label}>{label}</span>)}</div>
    {items.map((item) => <div className="resource-table-row" role="row" key={item.name}>
      <span role="cell" data-label={t.name}><strong>{item.name}</strong></span>
      <span role="cell" data-label={t.type}>{item.type || t.notAvailable}</span>
      <span role="cell" data-label={t.fingerprint}><code>{item.fingerprint || t.notAvailable}</code></span>
      <span role="cell" data-label={t.publicKey}><code>{item.public_key_preview || t.notAvailable}</code></span>
      <span role="cell" data-label={t.created}>{optionalDate(item.created_at, locale, t)}</span>
      <span role="cell" data-label={t.lastUsed}>{optionalDate(item.last_used_at, locale, t)}</span>
      <span role="cell" data-label={t.actions} className="keypair-actions"><button type="button"
        className="danger-secondary" onClick={(event) => onDelete(item, event.currentTarget)}>{t.delete}</button></span>
    </div>)}
  </div>
}

function KeyPairModal({ title, t, locked, returnFocus, onClose, children }: {
  title: string
  t: Copy
  locked: boolean
  returnFocus: RefObject<HTMLElement | null>
  onClose: () => void
  children: ReactNode
}) {
  const dialog = useRef<HTMLElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const closeRef = useRef(onClose)
  const lockedRef = useRef(locked)

  useEffect(() => { closeRef.current = onClose }, [onClose])
  useEffect(() => { lockedRef.current = locked }, [locked])
  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    const focusTarget = returnFocus.current
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (lockedRef.current) return
        event.preventDefault()
        closeRef.current()
        return
      }
      if (event.key !== 'Tab' || !dialog.current) return
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.closest('[hidden]'))
      if (!focusable.length) return
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
      if (focusTarget?.isConnected) focusTarget.focus()
    }
  }, [returnFocus])

  return <div className="keypair-modal-backdrop" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !locked) onClose()
  }}>
    <section ref={dialog} className="keypair-modal" role="dialog" aria-modal="true"
      aria-label={title} aria-busy={locked}>
      <header className="keypair-modal-header"><h2>{title}</h2><button ref={closeButton} type="button"
        className="modal-close secondary" aria-label={t.close} title={t.close} disabled={locked}
        onClick={onClose}>&times;</button></header>
      <div className="keypair-modal-body">{children}</div>
    </section>
  </div>
}

function MutationErrorNotice({ failure, t }: { failure?: MutationFailure; t: Copy }) {
  if (!failure) return null
  return <div className="error modal-error" role="alert"><span>{failure.message}</span>
    {failure.references && <small>{t.requestReference}: {failure.references.join(' / ')}</small>}
  </div>
}

function CreateKeyPairModal({ t, returnFocus, onExpired, onClose, onSuccess }: {
  t: Copy
  returnFocus: RefObject<HTMLElement | null>
  onExpired: () => void
  onClose: () => void
  onSuccess: (message: string, operation?: Operation) => void
}) {
  const [mode, setMode] = useState<KeyPairMode>('generate')
  const [name, setName] = useState('')
  const [type, setType] = useState<KeyPairType>('ssh')
  const [publicMaterial, setPublicMaterial] = useState('')
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<MutationFailure>()
  const [validation, setValidation] = useState<{ name?: string; material?: string }>({})
  const [privateKeyVisible, setPrivateKeyVisible] = useState(false)
  const [copyStatus, setCopyStatus] = useState<'copied' | 'failed'>()
  const submitting = useRef(false)
  const privateKey = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (privateKeyVisible) privateKey.current?.focus()
  }, [privateKeyVisible])

  function dismiss() {
    if (privateKey.current) privateKey.current.value = ''
    onClose()
  }

  function selectMode(next: KeyPairMode) {
    if (pending) return
    setMode(next)
    setFailure(undefined)
    setValidation({})
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current) return
    const cleanName = name.trim()
    const cleanMaterial = publicMaterial.trim()
    const nextValidation = {
      name: cleanName ? undefined : t.nameRequired,
      material: mode === 'import' && !cleanMaterial ? t.publicMaterialRequired : undefined,
    }
    setValidation(nextValidation)
    if (nextValidation.name || nextValidation.material) return

    submitting.current = true
    setPending(true)
    setFailure(undefined)
    try {
      const result = await api.createKeyPair(mode === 'import'
        ? { name: cleanName, type, mode, public_key: cleanMaterial }
        : { name: cleanName, type, mode })
      if (mode === 'generate') {
        if (!('private_key' in result) || !result.private_key || !privateKey.current) {
          setFailure({ message: t.createFailed })
          return
        }
        // One-time private material lives only in this dialog DOM and is never placed in React state.
        privateKey.current.value = result.private_key
        setCopyStatus(undefined)
        setPrivateKeyVisible(true)
        onSuccess(t.keypairGenerated)
      } else {
        if (!('id' in result)) {
          setFailure({ message: t.createFailed })
          return
        }
        onSuccess(t.keypairImportAccepted, result)
        dismiss()
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setFailure(mutationFailure(cause, t.createFailed, t))
    } finally {
      submitting.current = false
      setPending(false)
    }
  }

  async function copyPrivateKey() {
    if (!privateKey.current?.value) return
    try {
      await navigator.clipboard.writeText(privateKey.current.value)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  const materialLabel = type === 'x509' ? t.x509Certificate : t.sshPublicKey
  return <KeyPairModal title={t.createKeypair} t={t} locked={pending} returnFocus={returnFocus}
    onClose={dismiss}>
    <form className="keypair-form" onSubmit={submit} noValidate hidden={privateKeyVisible}>
      <div className="segmented keypair-mode" aria-label={t.creationMode}>
        {(['generate', 'import'] as const).map((value) => <button type="button" key={value}
          className={mode === value ? 'active' : undefined} aria-pressed={mode === value}
          disabled={pending} onClick={() => selectMode(value)}>{t[value]}</button>)}
      </div>
      <label>{t.name}<input value={name} maxLength={255} autoComplete="off" disabled={pending}
        aria-invalid={Boolean(validation.name)} onChange={(event) => {
          setName(event.target.value)
          if (validation.name) setValidation((value) => ({ ...value, name: undefined }))
        }} />{validation.name && <small className="field-error">{validation.name}</small>}</label>
      <label>{t.keyType}<select value={type} disabled={pending}
        onChange={(event) => setType(event.target.value as KeyPairType)}>
        <option value="ssh">SSH</option><option value="x509">X.509</option>
      </select></label>
      {mode === 'import' && <label>{materialLabel}<textarea value={publicMaterial} rows={8}
        maxLength={16_384} spellCheck="false" wrap="off" disabled={pending}
        aria-invalid={Boolean(validation.material)}
        onChange={(event) => {
          setPublicMaterial(event.target.value)
          if (validation.material) setValidation((value) => ({ ...value, material: undefined }))
        }} />{validation.material && <small className="field-error">{validation.material}</small>}</label>}
      <MutationErrorNotice failure={failure} t={t} />
      <div className="modal-actions"><button type="button" className="secondary" disabled={pending}
        onClick={dismiss}>{t.cancel}</button><button type="submit" disabled={pending}>
        {pending ? (mode === 'generate' ? t.generating : t.importing)
          : (mode === 'generate' ? t.generateKeypair : t.importKeypair)}</button></div>
    </form>
    <section className="private-key-result" hidden={!privateKeyVisible}>
      <h3>{t.privateKeyTitle}</h3><p>{t.privateKeyOnce}</p>
      <label>{t.privateKey}<textarea ref={privateKey} readOnly rows={12} spellCheck="false" wrap="off" /></label>
      {copyStatus === 'failed' && <p className="field-error" role="alert">{t.copyFailed}</p>}
      <div className="modal-actions"><button type="button" className="secondary"
        onClick={() => void copyPrivateKey()}>{copyStatus === 'copied' ? t.copied : t.copyPrivateKey}</button>
      <button type="button" onClick={dismiss}>{t.done}</button></div>
    </section>
  </KeyPairModal>
}

function DeleteKeyPairModal({ item, t, returnFocus, onExpired, onClose, onSuccess }: {
  item: KeyPair
  t: Copy
  returnFocus: RefObject<HTMLElement | null>
  onExpired: () => void
  onClose: () => void
  onSuccess: (message: string, operation?: Operation) => void
}) {
  const [confirmation, setConfirmation] = useState('')
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<MutationFailure>()
  const submitting = useRef(false)
  const confirmed = confirmation === item.name

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!confirmed || submitting.current) return
    submitting.current = true
    setPending(true)
    setFailure(undefined)
    try {
      const operation = await api.deleteKeyPair(item.name)
      onSuccess(t.keypairDeleteAccepted, operation)
      onClose()
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setFailure(mutationFailure(cause, t.deleteFailed, t))
    } finally {
      submitting.current = false
      setPending(false)
    }
  }

  return <KeyPairModal title={t.deleteKeypair} t={t} locked={pending} returnFocus={returnFocus}
    onClose={onClose}>
    <form className="keypair-form" onSubmit={submit}>
      <p className="delete-warning">{t.deleteWarning}</p>
      <code className="confirmation-name">{item.name}</code>
      <label>{t.confirmName}<input value={confirmation} autoComplete="off" disabled={pending}
        onChange={(event) => setConfirmation(event.target.value)} /></label>
      <MutationErrorNotice failure={failure} t={t} />
      <div className="modal-actions"><button type="button" className="secondary" disabled={pending}
        onClick={onClose}>{t.cancel}</button><button type="submit" className="danger-action"
        disabled={!confirmed || pending}>{pending ? t.deleting : t.delete}</button></div>
    </form>
  </KeyPairModal>
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
