import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, api } from './api'
import { Pagination } from './Pagination'
import type {
  AdminStorageItem,
  Operation,
  StorageItem,
  StoragePage as StoragePagePayload,
  StorageQuery,
  StorageResource,
  Volume,
  VolumeBackup,
  VolumeSnapshot,
} from './types'

type Locale = 'en' | 'ko'
type HistoryMode = 'push' | 'replace'
type Dialog =
  | { kind: 'create' }
  | { kind: 'edit'; item: StorageItem }
  | { kind: 'action'; item: StorageItem }
  | { kind: 'delete'; item: StorageItem }

const projectResources: StorageResource[] = ['volumes', 'snapshots', 'backups']
const adminResources: StorageResource[] = ['types', 'qos', 'pools', 'services']

const copy = {
  en: {
    storage: 'Storage', projectStorage: 'Project storage', administration: 'Administration',
    volumes: 'Volumes', snapshots: 'Snapshots', backups: 'Backups', types: 'Volume types',
    qos: 'QoS specs', pools: 'Pools & capabilities', services: 'Services',
    create: 'Create', edit: 'Settings', actions: 'Actions', delete: 'Delete', forceDelete: 'Force delete',
    filters: 'Filters', name: 'Name', status: 'Status', clear: 'Clear filters',
    loading: 'Loading storage resources...', empty: 'No storage resources match these filters.',
    failed: 'Unable to load storage resources.', partial: 'Some storage data is unavailable.',
    rows: 'Rows per page', page: 'Page', previousPage: 'Previous page', nextPage: 'Next page',
    size: 'Size', type: 'Type', source: 'Source', created: 'Created', attached: 'Attached',
    more: 'More', description: 'Description', metadata: 'Metadata / specs (JSON)',
    primary: 'Source volume/snapshot or size', operation: 'Operation', target: 'Target / value',
    secondary: 'Secondary value', force: 'Force', save: 'Submit', cancel: 'Cancel', pending: 'Submitting...',
    confirmation: 'Type the exact resource ID', dangerHelp: 'Cinder may reject this operation when the resource is in use or has dependencies.',
    requestReference: 'Request reference', succeeded: 'Operation accepted', oneTime: 'One-time result',
    invalidJson: 'Metadata/specs must be a JSON object.',
  },
  ko: {
    storage: '스토리지', projectStorage: '프로젝트 스토리지', administration: '관리자 기능',
    volumes: '볼륨', snapshots: '스냅샷', backups: '백업', types: '볼륨 타입',
    qos: 'QoS 스펙', pools: '풀 및 기능', services: '서비스',
    create: '생성', edit: '설정', actions: '작업', delete: '삭제', forceDelete: '강제 삭제',
    filters: '필터', name: '이름', status: '상태', clear: '필터 초기화',
    loading: '스토리지 리소스를 불러오는 중...', empty: '필터와 일치하는 스토리지 리소스가 없습니다.',
    failed: '스토리지 리소스를 불러올 수 없습니다.', partial: '일부 스토리지 데이터를 사용할 수 없습니다.',
    rows: '페이지당 행', page: '페이지', previousPage: '이전 페이지', nextPage: '다음 페이지',
    size: '크기', type: '타입', source: '원본', created: '생성 시각', attached: '연결',
    more: '더보기', description: '설명', metadata: '메타데이터 / 스펙 (JSON)',
    primary: '원본 볼륨/스냅샷 또는 크기', operation: '작업', target: '대상 / 값',
    secondary: '보조 값', force: '강제 실행', save: '실행', cancel: '취소', pending: '요청 중...',
    confirmation: '정확한 리소스 ID 입력', dangerHelp: '사용 중이거나 의존 리소스가 있으면 Cinder가 이 작업을 거부할 수 있습니다.',
    requestReference: '요청 참조', succeeded: '작업이 접수되었습니다.', oneTime: '최초 1회 결과',
    invalidJson: '메타데이터/스펙은 JSON 객체여야 합니다.',
  },
}
type Copy = typeof copy.en

const actions: Record<StorageResource, string[]> = {
  volumes: [
    'attach', 'detach', 'extend', 'retype', 'migrate', 'create_transfer',
    'accept_transfer', 'upload_to_image', 'set_bootable', 'set_read_only',
    'revert_to_snapshot', 'unmanage', 'force_delete',
  ],
  snapshots: ['unmanage', 'force_delete'],
  backups: ['restore', 'export_record', 'force_delete'],
  services: ['enable', 'disable', 'freeze', 'thaw', 'failover'],
  types: [], qos: [], pools: [],
}

function resourceId(item: StorageItem): string {
  if ('id' in item && item.id) return String(item.id)
  if ('name' in item && item.name) return String(item.name)
  if ('host' in item && item.host) return String(item.host)
  return ''
}

function itemName(item: StorageItem, fallback: string): string {
  return ('name' in item && item.name) || ('host' in item && item.host) || fallback
}

function parseObject(value: FormDataEntryValue | null): Record<string, unknown> {
  const text = String(value ?? '').trim()
  if (!text) return {}
  const parsed: unknown = JSON.parse(text)
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('object')
  return parsed as Record<string, unknown>
}

function reference(error: ApiError): string {
  return [
    error.problem.openstack_request_id && `OpenStack ${error.problem.openstack_request_id}`,
    error.problem.trace_id && `Vantage ${error.problem.trace_id}`,
  ].filter(Boolean).join(' / ')
}

export function StoragePage({
  scopeKey, locale, query, onQuery, onExpired,
}: {
  scopeKey: string
  locale: Locale
  query: StorageQuery
  onQuery: (query: StorageQuery, mode: HistoryMode) => void
  onExpired: () => void
}) {
  const t = copy[locale]
  const [data, setData] = useState<StoragePagePayload>()
  const [loading, setLoading] = useState(true)
  const [failure, setFailure] = useState<{ message: string; reference?: string }>()
  const [dialog, setDialog] = useState<Dialog>()
  const [operation, setOperation] = useState<Operation>()
  const [refresh, setRefresh] = useState(0)
  const [pendingName, setPendingName] = useState(query.name)
  const key = `${scopeKey}:${query.resource}:${query.limit}:${query.page}:${query.name}:${query.status}:${query.sort}:${query.direction}:${refresh}`
  const previous = useRef<StoragePagePayload | undefined>(undefined)

  const change = useCallback((patch: Partial<StorageQuery>, mode: HistoryMode = 'replace') =>
    onQuery({ ...query, ...patch, page: patch.page ?? 1 }, mode), [onQuery, query])

  useEffect(() => {
    if (pendingName === query.name) return
    const timer = window.setTimeout(() => change({ name: pendingName }), 300)
    return () => window.clearTimeout(timer)
  }, [change, pendingName, query.name])

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      setLoading(true)
      setFailure(undefined)
      try {
        const result = await api.storage(query, controller.signal)
        previous.current = result
        setData(result)
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === 'AbortError') return
        if (cause instanceof ApiError && cause.status === 401) return onExpired()
        if (cause instanceof ApiError && cause.status === 409 && cause.problem.code.includes('cursor')) {
          change({ page: 1 })
          return
        }
        if (previous.current && !(cause instanceof ApiError && [403, 404].includes(cause.status))) {
          setData(previous.current)
        } else setData(undefined)
        setFailure({
          message: cause instanceof ApiError ? cause.problem.detail : t.failed,
          reference: cause instanceof ApiError ? reference(cause) : undefined,
        })
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [change, key, onExpired, query, t.failed])

  const isAdmin = adminResources.includes(query.resource)
  const creatable = !['pools', 'services'].includes(query.resource)

  return <>
    <div className="page-heading storage-heading">
      <div><p className="eyebrow compact">{t.storage}</p><h1>{t[query.resource]}</h1></div>
      {creatable && <button type="button" onClick={() => setDialog({ kind: 'create' })}>{t.create}</button>}
    </div>
    <nav className="storage-workspaces" aria-label={t.storage}>
      <div><strong>{t.projectStorage}</strong>{projectResources.map((resource) =>
        <button key={resource} className={!isAdmin && query.resource === resource ? 'selected' : ''}
          onClick={() => change({ resource, name: '', status: '', sort: 'created_at', direction: 'desc' }, 'push')}>
          {t[resource]}
        </button>)}</div>
      <div><strong>{t.administration}</strong>{adminResources.map((resource) =>
        <button key={resource} className={isAdmin && query.resource === resource ? 'selected' : ''}
          onClick={() => change({ resource, name: '', status: '', sort: 'name', direction: 'asc' }, 'push')}>
          {t[resource]}
        </button>)}</div>
    </nav>
    <section className="inventory-filters" aria-label={t.filters}>
      <label>{t.name}<input type="search" value={pendingName}
        onChange={(event) => setPendingName(event.target.value)} /></label>
      {!['types', 'qos', 'pools'].includes(query.resource) && <label>{t.status}<input
        value={query.status} onChange={(event) => change({ status: event.target.value })} /></label>}
      {(query.name || query.status) && <button type="button" className="secondary"
        onClick={() => { setPendingName(''); change({ name: '', status: '' }) }}>{t.clear}</button>}
    </section>
    {failure && <div className="error" role="alert"><span>{failure.message}</span>
      {failure.reference && <small>{t.requestReference}: {failure.reference}</small>}</div>}
    {data?.partial_errors.length ? <div className="partial-errors" role="status">{t.partial}</div> : null}
    {operation && <OperationNotice operation={operation} t={t} />}
    {loading && !data && <div className="loading-state" role="status">{t.loading}</div>}
    {data && (data.items.length ? <StorageTable items={data.items} resource={query.resource}
      locale={locale} t={t} onDialog={setDialog} /> : <p className="empty-state">{t.empty}</p>)}
    {data && <Pagination page={data.page} pageSize={query.limit} labels={t}
      onPage={(page) => change({ page }, 'push')} onPageSize={(limit) => change({ limit })} />}
    {dialog && <StorageDialog dialog={dialog} resource={query.resource} t={t}
      onClose={() => setDialog(undefined)} onComplete={(next) => {
        setDialog(undefined); setOperation(next); setRefresh((value) => value + 1)
      }} onExpired={onExpired} />}
  </>
}

function StorageTable({ items, resource, locale, t, onDialog }: {
  items: StorageItem[]; resource: StorageResource; locale: Locale; t: Copy
  onDialog: (dialog: Dialog) => void
}) {
  return <div className="storage-grid" role="list" aria-label={t[resource]}>
    {items.map((item) => {
      const id = resourceId(item)
      const status = 'status' in item ? item.status : ('state' in item ? item.state : undefined)
      return <article className="storage-card" role="listitem" key={id}>
        <div className="storage-card-title"><div><strong>{itemName(item, id)}</strong>
          <code>{id}</code></div>{status && <span className="instance-status">{status}</span>}</div>
        <dl><StorageFacts item={item} locale={locale} t={t} /></dl>
        <div className="storage-card-actions">
          {!['pools', 'services'].includes(resource) && <button type="button" className="secondary"
            onClick={() => onDialog({ kind: 'edit', item })}>{t.edit}</button>}
          {actions[resource].length > 0 && <button type="button" className="secondary"
            onClick={() => onDialog({ kind: 'action', item })}>{t.actions}</button>}
          {!['pools', 'services'].includes(resource) && <button type="button" className="danger"
            onClick={() => onDialog({ kind: 'delete', item })}>{t.delete}</button>}
        </div>
      </article>
    })}
  </div>
}

function StorageFacts({ item, locale, t }: { item: StorageItem; locale: Locale; t: Copy }) {
  if ('size_gib' in item) return <>
    <div><dt>{t.size}</dt><dd>{item.size_gib ?? '—'} GiB</dd></div>
    {'volume_type' in item && <div><dt>{t.type}</dt><dd>{item.volume_type || '—'}</dd></div>}
    {'volume_id' in item && <div><dt>{t.source}</dt><dd><code>
      {item.volume_id || ('snapshot_id' in item ? item.snapshot_id : undefined) || '—'}
    </code></dd></div>}
    {'attachments' in item && <div><dt>{t.attached}</dt><dd>{item.attachments.length}</dd></div>}
    <div><dt>{t.created}</dt><dd>{formatDate(item.created_at, locale)}</dd></div>
  </>
  const admin = item as AdminStorageItem
  return <>
    {admin.description && <div><dt>{t.description}</dt><dd>{admin.description}</dd></div>}
    {admin.binary && <div><dt>{t.type}</dt><dd>{admin.binary}</dd></div>}
    {(admin.extra_specs || admin.specs) && <div><dt>{t.metadata}</dt>
      <dd><code>{JSON.stringify(admin.extra_specs ?? admin.specs)}</code></dd></div>}
    {admin.capabilities && <div><dt>{t.more}</dt><dd><code>{JSON.stringify(admin.capabilities)}</code></dd></div>}
  </>
}

function StorageDialog({ dialog, resource, t, onClose, onComplete, onExpired }: {
  dialog: Dialog; resource: StorageResource; t: Copy; onClose: () => void
  onComplete: (operation: Operation) => void; onExpired: () => void
}) {
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<string>()
  const item = dialog.kind === 'create' ? undefined : dialog.item
  const id = item ? resourceId(item) : ''
  const availableActions = actions[resource]
  const defaultAction = availableActions[0] ?? ''

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPending(true); setFailure(undefined)
    const data = new FormData(event.currentTarget)
    try {
      let result: Operation
      if (dialog.kind === 'delete') {
        if (String(data.get('confirmation')) !== id) throw new Error('confirmation')
        result = await api.storageDelete(resource as 'volumes', id, data.get('force') === 'on')
      } else if (dialog.kind === 'action') {
        const action = String(data.get('action'))
        const payload = actionPayload(action, id, data)
        if (resource === 'volumes') result = await api.volumeAction(id, payload)
        else if (resource === 'snapshots') result = await api.snapshotAction(id, payload)
        else if (resource === 'backups') result = await api.backupAction(id, payload)
        else if (resource === 'services') result = await api.serviceAction(id, payload)
        else throw new Error('unsupported-action')
      } else {
        const payload = editorPayload(resource, data, dialog.kind === 'create')
        result = dialog.kind === 'create'
          ? await api.storageCreate(resource as 'volumes', payload)
          : await api.storageUpdate(resource as 'volumes', id, payload)
      }
      onComplete(result)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else if (cause instanceof SyntaxError) setFailure(t.invalidJson)
      else if (cause instanceof Error && cause.message === 'confirmation') setFailure(t.confirmation)
      else setFailure(cause instanceof ApiError ? cause.problem.detail : t.failed)
    } finally { setPending(false) }
  }

  const title = dialog.kind === 'create' ? t.create : dialog.kind === 'edit'
    ? t.edit : dialog.kind === 'action' ? t.actions : t.delete
  return <div className="dialog-backdrop"><section className="storage-dialog" role="dialog" aria-modal="true">
    <div className="dialog-heading"><h2>{title}: {itemName(item ?? {}, resource)}</h2>
      <button type="button" className="secondary" onClick={onClose}>×</button></div>
    {failure && <div className="error" role="alert">{failure}</div>}
    <form onSubmit={submit}>
      {(dialog.kind === 'create' || dialog.kind === 'edit') && <EditorFields
        resource={resource} item={item} t={t} />}
      {dialog.kind === 'action' && <>
        <label>{t.operation}<select name="action" defaultValue={defaultAction}>
          {availableActions.map((action) => <option key={action}>{action}</option>)}</select></label>
        <label>{t.target}<input name="target" /></label>
        <label>{t.secondary}<input name="secondary" /></label>
        <label className="inline-check"><input type="checkbox" name="force" />{t.force}</label>
        {availableActions.some((action) => ['migrate', 'unmanage', 'force_delete', 'failover'].includes(action))
          && <label>{t.confirmation}<input name="confirmation" placeholder={id} /></label>}
      </>}
      {dialog.kind === 'delete' && <><p className="danger-copy">{t.dangerHelp}</p>
        <label>{t.confirmation}<input name="confirmation" autoComplete="off" placeholder={id} /></label>
        <label className="inline-check"><input type="checkbox" name="force" />{t.forceDelete}</label></>}
      <div className="dialog-actions"><button type="button" className="secondary" onClick={onClose}>{t.cancel}</button>
        <button type="submit" className={dialog.kind === 'delete' ? 'danger' : ''} disabled={pending}>
          {pending ? t.pending : t.save}</button></div>
    </form>
  </section></div>
}

function EditorFields({ resource, item, t }: { resource: StorageResource; item?: StorageItem; t: Copy }) {
  const current = item as (Volume | VolumeSnapshot | VolumeBackup | AdminStorageItem | undefined)
  return <>
    <label>{t.name}<input name="name" defaultValue={current?.name ?? ''} required={resource === 'types' || resource === 'qos'} /></label>
    {!['qos'].includes(resource) && <label>{t.description}<textarea name="description"
      defaultValue={'description' in (current ?? {}) ? String(current?.description ?? '') : ''} /></label>}
    {resource === 'volumes' && !item && <label>{t.size}<input name="primary" type="number" min="1" required /></label>}
    {resource === 'snapshots' && !item && <label>{t.primary}<input name="primary" required /></label>}
    {resource === 'backups' && !item && <label>{t.primary}<input name="primary" required /></label>}
    <label>{t.metadata}<textarea name="metadata"
      defaultValue={JSON.stringify(itemProperties(current), null, 2)} /></label>
  </>
}

function itemProperties(item: StorageItem | undefined): Record<string, unknown> {
  if (!item) return {}
  if ('metadata' in item) return item.metadata
  if ('extra_specs' in item && item.extra_specs) return item.extra_specs
  if ('specs' in item && item.specs) return item.specs
  return {}
}

function editorPayload(resource: StorageResource, data: FormData, creating: boolean): Record<string, unknown> {
  const common = { name: String(data.get('name') || ''), description: String(data.get('description') || '') }
  const values = parseObject(data.get('metadata'))
  if (resource === 'volumes') return { ...common, size_gib: creating ? Number(data.get('primary')) : undefined, metadata: values }
  if (resource === 'snapshots') return { ...common, volume_id: creating ? String(data.get('primary')) : undefined, metadata: values }
  if (resource === 'backups') return { ...common, volume_id: creating ? String(data.get('primary')) : undefined, metadata: values }
  if (resource === 'types') return { ...common, is_public: true, extra_specs: values }
  return { name: common.name, consumer: 'both', specs: values }
}

function actionPayload(action: string, id: string, data: FormData): Record<string, unknown> {
  const target = String(data.get('target') || '')
  const secondary = String(data.get('secondary') || '')
  const force = data.get('force') === 'on'
  const confirmation = String(data.get('confirmation') || '')
  const payload: Record<string, unknown> = { action, force }
  if (['migrate', 'unmanage', 'force_delete', 'revert_to_snapshot', 'failover'].includes(action)) payload.confirmation = confirmation
  if (action === 'attach') payload.server_id = target
  if (action === 'detach') { payload.server_id = target; payload.attachment_id = secondary }
  if (action === 'extend') payload.size_gib = Number(target)
  if (action === 'retype') { payload.volume_type = target; payload.migration_policy = secondary || 'never' }
  if (action === 'migrate') payload.host = target
  if (action === 'accept_transfer') { payload.transfer_id = target; payload.auth_key = secondary }
  if (action === 'upload_to_image') payload.image_name = target
  if (action === 'set_bootable') payload.bootable = target !== 'false'
  if (action === 'set_read_only') payload.read_only = target !== 'false'
  if (action === 'revert_to_snapshot') payload.snapshot_id = target
  if (action === 'restore') payload.volume_id = target || undefined
  if (action === 'disable') payload.disabled_reason = target
  if (action === 'failover') payload.backend_id = target
  if (action === 'force_delete') payload.confirmation = confirmation || id
  return payload
}

function OperationNotice({ operation, t }: { operation: Operation; t: Copy }) {
  return <div className="operation-notice" role="status"><strong>{t.succeeded}</strong>
    <span>{operation.kind} / {operation.status}</span>
    {operation.openstack_request_ids.length > 0 && <small>{t.requestReference}: OpenStack {operation.openstack_request_ids.join(', ')}</small>}
    {operation.result && <details><summary>{t.oneTime}</summary><code>{JSON.stringify(operation.result)}</code></details>}
  </div>
}

function formatDate(value: string | null | undefined, locale: Locale): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale === 'ko' ? 'ko-KR' : 'en-US')
}
