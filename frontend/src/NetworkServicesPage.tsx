import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, api } from './api'
import { networkPath, RESOURCE_KINDS } from './network-route'
import { Pagination } from './Pagination'
import type {
  NetworkCapabilities,
  NetworkField,
  NetworkQuery,
  NetworkResource,
  NetworkResourcePage,
  Operation,
  ResourceKind,
} from './types'

const NESTED = new Set<ResourceKind>(['qos_rule', 'member', 'l7_rule'])
const QOS_RULE_TYPES = [
  'bandwidth_limit',
  'dscp_marking',
  'minimum_bandwidth',
  'minimum_packet_rate',
  'packet_rate_limit',
]

const ACTION_FIELDS: Record<string, string[]> = {
  attach_instance: ['server_id'],
  detach_instance: ['server_id'],
  add_fixed_ip: ['fixed_ip'],
  remove_fixed_ip: ['fixed_ip'],
  add_interface: ['subnet_id', 'port_id'],
  remove_interface: ['subnet_id', 'port_id'],
  set_gateway: ['external_gateway_info'],
  clear_gateway: [],
  associate: ['port_id', 'fixed_ip_address'],
  disassociate: [],
  failover: [],
}

const copy = {
  en: {
    title: 'Network services',
    help: 'Manage project Neutron resources and catalog-discovered Octavia resources.',
    resource: 'Resource',
    name: 'Name',
    status: 'Status',
    provisioning: 'Provisioning',
    operating: 'Operating',
    revision: 'Revision',
    actions: 'Actions',
    search: 'Search by name',
    statusFilter: 'Filter by status',
    parent: 'Parent ID',
    qosRuleType: 'QoS rule type',
    create: 'Create',
    details: 'Details',
    edit: 'Edit settings',
    delete: 'Delete',
    save: 'Save',
    cancel: 'Cancel',
    loading: 'Loading network resources...',
    empty: 'No resources match this project and filter.',
    unavailable: 'This service is not present in the active region.',
    failed: 'Unable to load network resources.',
    adminOnly: 'Administrator-only fields',
    adminHelp: 'These fields are available only in the separate administrator workspace.',
    immutable: 'Immutable after creation',
    confirmation: 'Type the exact resource name or ID to confirm.',
    dependency: 'OpenStack may reject deletion while dependent resources remain.',
    operation: 'Operation',
    request: 'OpenStack request',
    fieldHelp: 'Objects and arrays accept JSON. Empty optional fields are omitted.',
    invalidValue: 'One or more values are not valid JSON or scalar values.',
    close: 'Close',
  },
  ko: {
    title: '네트워크 서비스',
    help: '프로젝트 Neutron 리소스와 카탈로그에서 확인된 Octavia 리소스를 관리합니다.',
    resource: '리소스',
    name: '이름',
    status: '상태',
    provisioning: '프로비저닝',
    operating: '운영 상태',
    revision: '리비전',
    actions: '작업',
    search: '이름 검색',
    statusFilter: '상태 필터',
    parent: '상위 리소스 ID',
    qosRuleType: 'QoS 규칙 유형',
    create: '생성',
    details: '상세',
    edit: '설정 편집',
    delete: '삭제',
    save: '저장',
    cancel: '취소',
    loading: '네트워크 리소스를 불러오는 중...',
    empty: '현재 프로젝트와 필터에 맞는 리소스가 없습니다.',
    unavailable: '활성 리전에 이 서비스가 없습니다.',
    failed: '네트워크 리소스를 불러올 수 없습니다.',
    adminOnly: '관리자 전용 필드',
    adminHelp: '이 필드는 분리된 관리자 워크스페이스에서만 사용할 수 있습니다.',
    immutable: '생성 후 변경 불가',
    confirmation: '정확한 리소스 이름 또는 ID를 입력해 확인하세요.',
    dependency: '종속 리소스가 남아 있으면 OpenStack이 삭제를 거부할 수 있습니다.',
    operation: '작업',
    request: 'OpenStack 요청',
    fieldHelp: '객체와 배열은 JSON으로 입력합니다. 비어 있는 선택 필드는 전송하지 않습니다.',
    invalidValue: '일부 값이 올바른 JSON 또는 스칼라 값이 아닙니다.',
    close: '닫기',
  },
}

type Dialog =
  | { kind: 'create' }
  | { kind: 'detail'; resource: NetworkResource }
  | { kind: 'edit'; resource: NetworkResource }
  | { kind: 'delete'; resource: NetworkResource }
  | { kind: 'action'; resource: NetworkResource; action: string }

function problem(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.problem.detail : fallback
}

function parseValue(value: string): unknown {
  const trimmed = value.trim()
  if (!trimmed) return undefined
  if (['true', 'false', 'null'].includes(trimmed) || /^[{["\d-]/.test(trimmed)) {
    try {
      return JSON.parse(trimmed)
    } catch {
      if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed)
      if (trimmed.startsWith('{') || trimmed.startsWith('[')) throw new Error('invalid JSON')
    }
  }
  return trimmed
}

function displayValue(value: unknown): string {
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

async function waitForOperation(operation: Operation): Promise<Operation> {
  let current = operation
  for (let count = 0; count < 40 && ['accepted', 'running'].includes(current.status); count += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 250))
    current = await api.networkOperation(operation.id)
  }
  return current
}

export function NetworkServicesPage({
  scopeKey,
  locale,
  query,
  onQuery,
  onExpired,
}: {
  scopeKey: string
  locale: 'en' | 'ko'
  query: NetworkQuery
  onQuery: (query: NetworkQuery, mode: 'push' | 'replace') => void
  onExpired: () => void
}) {
  const t = copy[locale]
  const [capabilities, setCapabilities] = useState<NetworkCapabilities>()
  const [page, setPage] = useState<NetworkResourcePage>()
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string>()
  const [dialog, setDialog] = useState<Dialog>()
  const [operation, setOperation] = useState<Operation>()
  const [version, setVersion] = useState(0)
  const contract = capabilities?.resources.find((item) => item.resource_type === query.kind)

  useEffect(() => {
    const controller = new AbortController()
    api.networkCapabilities(controller.signal)
      .then(setCapabilities)
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 401) onExpired()
        else setMessage(problem(cause, t.failed))
      })
    return () => controller.abort()
  }, [scopeKey, onExpired, t.failed])

  useEffect(() => {
    const controller = new AbortController()
    api.networkResources(query, controller.signal)
      .then(setPage)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return
        if (cause instanceof ApiError && cause.status === 401) onExpired()
        else setMessage(problem(cause, t.failed))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [query, scopeKey, version, onExpired, t.failed])

  const labels = useMemo(() => ({
    rows: locale === 'ko' ? '페이지당 행' : 'Rows per page',
    page: locale === 'ko' ? '페이지' : 'Page',
    previousPage: locale === 'ko' ? '이전 페이지' : 'Previous page',
    nextPage: locale === 'ko' ? '다음 페이지' : 'Next page',
  }), [locale])

  function change(patch: Partial<NetworkQuery>, mode: 'push' | 'replace' = 'push') {
    const next = { ...query, ...patch }
    setLoading(true)
    setPage(undefined)
    setMessage(undefined)
    onQuery(next, mode)
  }

  async function runMutation(start: () => Promise<Operation>) {
    setMessage(undefined)
    try {
      const result = await waitForOperation(await start())
      setOperation(result)
      if (result.status === 'failed') setMessage(result.problem?.detail ?? t.failed)
      else {
        setDialog(undefined)
        setVersion((current) => current + 1)
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(problem(cause, t.failed))
    }
  }

  async function openDetail(resource: NetworkResource) {
    setMessage(undefined)
    try {
      const detail = await api.networkResource(
        resource.resource_type,
        resource.id,
        query.parentId,
        query.ruleType,
      )
      setDialog({ kind: 'detail', resource: detail })
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(problem(cause, t.failed))
    }
  }

  return (
    <section className="resource-page network-page">
      <div className="resource-heading">
        <div><p className="eyebrow">NEUTRON / OCTAVIA</p><h1>{t.title}</h1><p>{t.help}</p></div>
        <button type="button" disabled={!contract?.available} onClick={() => setDialog({ kind: 'create' })}>
          {t.create}
        </button>
      </div>
      <div className="network-toolbar">
        <label>{t.resource}
          <select
            value={query.kind}
            onChange={(event) => change({
              kind: event.target.value as ResourceKind,
              page: 1,
              parentId: '',
              ruleType: '',
            })}
          >
            {RESOURCE_KINDS.map((kind) => <option key={kind} value={kind}>{kind.replaceAll('_', ' ')}</option>)}
          </select>
        </label>
        <label>{t.search}
          <input value={query.name} onChange={(event) => change({ name: event.target.value, page: 1 }, 'replace')} />
        </label>
        <label>{t.statusFilter}
          <input value={query.status} onChange={(event) => change({ status: event.target.value, page: 1 }, 'replace')} />
        </label>
        {NESTED.has(query.kind) && <label>{t.parent}
          <input required value={query.parentId} onChange={(event) => change({ parentId: event.target.value, page: 1 }, 'replace')} />
        </label>}
        {query.kind === 'qos_rule' && <label>{t.qosRuleType}
          <select value={query.ruleType} onChange={(event) => change({ ruleType: event.target.value, page: 1 })}>
            <option value="">-</option>
            {QOS_RULE_TYPES.map((kind) => <option key={kind}>{kind}</option>)}
          </select>
        </label>}
      </div>
      {message && <div className="error" role="alert">{message}</div>}
      {operation && <div className={`operation ${operation.status}`} aria-live="polite">
        <strong>{t.operation}: {operation.status}</strong>
        {operation.openstack_request_ids.length > 0 && <small>{t.request}: {operation.openstack_request_ids.join(', ')}</small>}
      </div>}
      {contract && !contract.available ? <p className="empty-state">{t.unavailable}</p> : loading ? (
        <p className="muted">{t.loading}</p>
      ) : page?.items.length === 0 ? <p className="empty-state">{t.empty}</p> : (
        <div className="table-wrap"><table>
          <thead><tr><th>{t.name}</th><th>ID</th><th>{t.status}</th><th>{t.provisioning}</th><th>{t.operating}</th><th>{t.revision}</th><th>{t.actions}</th></tr></thead>
          <tbody>{page?.items.map((item) => <tr key={item.id}>
            <td><strong>{item.name ?? '—'}</strong></td><td><code>{item.id}</code></td>
            <td>{item.status ?? '—'}</td><td>{item.provisioning_status ?? '—'}</td><td>{item.operating_status ?? '—'}</td>
            <td>{item.revision_number ?? '—'}</td>
            <td className="row-actions">
              <button className="secondary" type="button" onClick={() => void openDetail(item)}>{t.details}</button>
              <button className="secondary" type="button" onClick={() => setDialog({ kind: 'edit', resource: item })}>{t.edit}</button>
              {contract?.actions.map((action) => <button className="secondary" type="button" key={action} onClick={() => setDialog({ kind: 'action', resource: item, action })}>{action.replaceAll('_', ' ')}</button>)}
              <button className="danger" type="button" onClick={() => setDialog({ kind: 'delete', resource: item })}>{t.delete}</button>
            </td>
          </tr>)}</tbody>
        </table></div>
      )}
      <Pagination
        labels={labels}
        page={page?.page}
        pageSize={query.limit}
        onPage={(next) => change({ page: next })}
        onPageSize={(limit) => change({ limit, page: 1 })}
      />
      {dialog && contract && <ResourceDialog
        dialog={dialog}
        contractFields={contract.fields}
        parentId={query.parentId}
        labels={t}
        onCancel={() => setDialog(undefined)}
        onSubmit={(attributes) => {
          if (dialog.kind === 'create') {
            void runMutation(() => api.createNetworkResource(query.kind, attributes, query.parentId))
          } else if (dialog.kind === 'edit') {
            void runMutation(() => api.updateNetworkResource(dialog.resource, attributes, query.parentId, query.ruleType))
          } else if (dialog.kind === 'delete') {
            void runMutation(() => api.deleteNetworkResource(dialog.resource, query.parentId, query.ruleType))
          } else if (dialog.kind === 'action') {
            void runMutation(() => api.runNetworkAction(dialog.resource, dialog.action, attributes))
          }
        }}
      />}
      <a className="sr-only" href={networkPath(query)}>Current network route</a>
    </section>
  )
}

function ResourceDialog({
  dialog,
  contractFields,
  labels,
  onCancel,
  onSubmit,
}: {
  dialog: Dialog
  contractFields: NetworkField[]
  parentId: string
  labels: typeof copy.en
  onCancel: () => void
  onSubmit: (values: Record<string, unknown>) => void
}) {
  const [confirmation, setConfirmation] = useState('')
  const [invalid, setInvalid] = useState(false)
  const editResource = dialog.kind === 'edit' ? dialog.resource : undefined
  const fields = dialog.kind === 'action'
    ? (ACTION_FIELDS[dialog.action] ?? []).map((name) => ({ name, required: true }))
    : contractFields
      .filter((field) => !field.admin_only && (dialog.kind === 'create' ? field.create : field.update))
  const adminFields = contractFields.filter((field) => field.admin_only)
  const immutable = contractFields.filter((field) => field.create && !field.update)
  const expected = dialog.kind === 'delete' ? dialog.resource.name || dialog.resource.id : ''

  if (dialog.kind === 'detail') {
    const values = {
      id: dialog.resource.id,
      name: dialog.resource.name,
      status: dialog.resource.status,
      provisioning_status: dialog.resource.provisioning_status,
      operating_status: dialog.resource.operating_status,
      revision_number: dialog.resource.revision_number,
      ...dialog.resource.attributes,
    }
    return (
      <div className="dialog-backdrop" role="presentation">
        <section className="panel resource-dialog" role="dialog" aria-modal="true" aria-labelledby="resource-dialog-title">
          <h2 id="resource-dialog-title">{labels.details}</h2>
          <dl className="network-detail-list">
            {Object.entries(values).map(([name, value]) => value === undefined || value === null ? null : (
              <div key={name}><dt>{name}</dt><dd><code>{displayValue(value)}</code></dd></div>
            ))}
          </dl>
          <div className="dialog-actions"><button type="button" className="secondary" onClick={onCancel}>{labels.close}</button></div>
        </section>
      </div>
    )
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (dialog.kind === 'delete') {
      if (confirmation === expected) onSubmit({})
      return
    }
    const data = new FormData(event.currentTarget)
    try {
      const values = Object.fromEntries(
        fields
          .map((field) => [field.name, parseValue(String(data.get(field.name) ?? ''))] as const)
          .filter((entry) => entry[1] !== undefined),
      )
      setInvalid(false)
      onSubmit(values)
    } catch {
      setInvalid(true)
    }
  }

  const title = dialog.kind === 'create'
    ? labels.create
    : dialog.kind === 'edit'
      ? labels.edit
      : dialog.kind === 'delete'
        ? labels.delete
        : dialog.action.replaceAll('_', ' ')
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="panel resource-dialog" role="dialog" aria-modal="true" aria-labelledby="resource-dialog-title">
        <h2 id="resource-dialog-title">{title}</h2>
        <form onSubmit={submit}>
          {dialog.kind === 'delete' ? (
            <><p>{labels.dependency}</p><p>{labels.confirmation}</p><code>{expected}</code>
              <input autoFocus value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></>
          ) : <><p className="muted">{labels.fieldHelp}</p>
            {fields.map((field) => <label key={field.name}>{field.name}
              <input
                name={field.name}
                required={field.required}
                defaultValue={displayValue(editResource?.attributes[field.name])}
              />
            </label>)}
            {invalid && <div className="error" role="alert">{labels.invalidValue}</div>}
            {adminFields.length > 0 && <details><summary>{labels.adminOnly}</summary><p>{labels.adminHelp}</p><code>{adminFields.map((field) => field.name).join(', ')}</code></details>}
            {dialog.kind === 'edit' && immutable.length > 0 && <details><summary>{labels.immutable}</summary><code>{immutable.map((field) => field.name).join(', ')}</code></details>}
          </>}
          <div className="dialog-actions">
            <button type="button" className="secondary" onClick={onCancel}>{labels.cancel}</button>
            <button type="submit" className={dialog.kind === 'delete' ? 'danger' : undefined} disabled={dialog.kind === 'delete' && confirmation !== expected}>
              {dialog.kind === 'delete' ? labels.delete : labels.save}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
