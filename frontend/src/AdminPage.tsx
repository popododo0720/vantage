import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, api } from './api'
import { Pagination } from './Pagination'
import type {
  AdminOperation,
  AdminQuotaCollection,
  AdminSession,
  IdentityKind,
  IdentityPage,
  IdentityResource,
  OperationAck,
  QuotaService,
  RoleAssignmentPage,
  Session,
} from './types'

export type AdminSection = IdentityKind | 'assignments' | 'quotas'

const copy = {
  en: {
    administration: 'Administration', scope: 'Administrator scope', back: 'Project workspace',
    projects: 'Projects', users: 'Users', groups: 'Groups', roles: 'Roles',
    assignments: 'Role assignments', quotas: 'Project quotas', search: 'Search',
    create: 'Create', edit: 'Edit', disable: 'Disable', delete: 'Delete', details: 'Details',
    name: 'Name', id: 'ID', domain: 'Domain', enabled: 'Enabled', actions: 'Actions',
    loading: 'Loading administrator data...', empty: 'No resources found.',
    denied: 'This session has no policy-authorized administrator workspace.',
    failed: 'Administrator request failed', rows: 'Rows per page', page: 'Page',
    previousPage: 'Previous page', nextPage: 'Next page', confirm: 'Type the exact name or ID',
    operation: 'Operation', requestIds: 'OpenStack request IDs', projectId: 'Project ID',
    userId: 'User ID (Compute quota only)', load: 'Load quotas', service: 'Service',
    resource: 'Resource', used: 'Used', reserved: 'Reserved', limit: 'Limit',
    default: 'Default', apply: 'Apply changes', reset: 'Delete overrides', actor: 'Actor ID',
    actorType: 'Actor type', roleId: 'Role ID', scopeType: 'Assignment scope', scopeId: 'Scope ID',
    grant: 'Grant role', inherited: 'Inherited to projects', signOut: 'Sign out',
    useProjectScope: 'Use project scope', close: 'Close',
  },
  ko: {
    administration: '관리자', scope: '관리자 범위', back: '프로젝트 작업공간',
    projects: '프로젝트', users: '사용자', groups: '그룹', roles: '역할',
    assignments: '역할 할당', quotas: '프로젝트 쿼터', search: '검색',
    create: '생성', edit: '편집', disable: '비활성화', delete: '삭제', details: '상세',
    name: '이름', id: 'ID', domain: '도메인', enabled: '활성', actions: '작업',
    loading: '관리자 데이터를 불러오는 중...', empty: '리소스가 없습니다.',
    denied: '이 세션에서 정책으로 허용된 관리자 작업공간이 없습니다.',
    failed: '관리자 요청에 실패했습니다.', rows: '페이지당 행', page: '페이지',
    previousPage: '이전 페이지', nextPage: '다음 페이지', confirm: '정확한 이름 또는 ID를 입력하세요',
    operation: '작업', requestIds: 'OpenStack 요청 ID', projectId: '프로젝트 ID',
    userId: '사용자 ID(Compute 사용자 쿼터 전용)', load: '쿼터 조회', service: '서비스',
    resource: '리소스', used: '사용', reserved: '예약', limit: '한도',
    default: '기본값', apply: '변경 적용', reset: '오버라이드 삭제', actor: '대상 ID',
    actorType: '대상 유형', roleId: '역할 ID', scopeType: '할당 범위', scopeId: '범위 ID',
    grant: '역할 부여', inherited: '하위 프로젝트 상속', signOut: '로그아웃',
    useProjectScope: '프로젝트 범위로 전환', close: '닫기',
  },
}

type Locale = keyof typeof copy

function problem(cause: unknown, fallback: string): string {
  return cause instanceof ApiError
    ? `${cause.problem.detail} (${cause.problem.openstack_request_id ?? cause.problem.trace_id})`
    : fallback
}

export function AdminWorkspace({
  session,
  locale,
  language,
  section,
  onSection,
  onBack,
  onExpired,
  onLogout,
}: {
  session: Session
  locale: Locale
  language: ReactNode
  section: AdminSection
  onSection: (section: AdminSection) => void
  onBack: () => void
  onExpired: () => void
  onLogout: () => void
}) {
  const t = copy[locale]
  const [admin, setAdmin] = useState<AdminSession>()
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let active = true
    api.adminSession()
      .then(async (value) => {
        if (value.active_scope || !value.available_scopes[0]) return value
        const first = value.available_scopes[0]
        return api.adminScope(first.type, first.id)
      })
      .then((value) => { if (active) setAdmin(value) })
      .catch((cause: unknown) => {
        if (!active) return
        if (cause instanceof ApiError && cause.status === 401) onExpired()
        else setMessage(cause instanceof ApiError && cause.status === 403 ? t.denied : problem(cause, t.failed))
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [onExpired, t.denied, t.failed])

  async function changeScope(value: string) {
    const selected = admin?.available_scopes.find((item) => `${item.type}:${item.id}` === value)
    if (!selected) return
    setLoading(true)
    try {
      setAdmin(await api.adminScope(selected.type, selected.id))
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(problem(cause, t.failed))
    } finally {
      setLoading(false)
    }
  }

  async function logout() {
    try {
      await api.logout()
      onLogout()
    } catch (cause) {
      setMessage(problem(cause, t.failed))
    }
  }

  return (
    <div className="app-shell admin-shell" aria-label={`${t.administration}: ${session.user.name}`}>
      <header>
        <div className="brand"><span>V</span><strong>Vantage</strong></div>
        {admin?.active_scope && (
          <label className="admin-scope-select">
            <span>{t.scope}</span>
            <select
              value={`${admin.active_scope.type}:${admin.active_scope.id}`}
              onChange={(event) => void changeScope(event.target.value)}
            >
              {admin.available_scopes.map((item) => (
                <option key={`${item.type}:${item.id}`} value={`${item.type}:${item.id}`}>
                  {item.type.toUpperCase()} / {item.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {language}
        <button type="button" className="secondary" onClick={() => void logout()}>{t.signOut}</button>
      </header>
      <aside aria-label={t.administration}>
        <strong>{t.administration}</strong>
        {(['projects', 'users', 'groups', 'roles', 'assignments', 'quotas'] as AdminSection[]).map((item) => (
          <a
            href={`/admin/${item}`}
            key={item}
            className={section === item ? 'selected' : undefined}
            aria-current={section === item ? 'page' : undefined}
            onClick={(event) => { event.preventDefault(); onSection(item) }}
          >
            {t[item]}
          </a>
        ))}
        <button type="button" className="admin-back" onClick={onBack}>{t.back}</button>
      </aside>
      <main className="content">
        {message && <div className="error" role="alert">{message}</div>}
        {loading || !admin?.active_scope ? (
          !message && <p className="loading-state">{t.loading}</p>
        ) : section === 'assignments' ? (
          <Assignments locale={locale} onExpired={onExpired} />
        ) : section === 'quotas' ? (
          <AdminQuotas locale={locale} onExpired={onExpired} />
        ) : (
          <IdentityList
            key={`${admin.active_scope.type}:${admin.active_scope.id}:${section}`}
            kind={section}
            locale={locale}
            onExpired={onExpired}
            onScopeChange={setAdmin}
          />
        )}
      </main>
    </div>
  )
}

async function completedOperation(ack: OperationAck): Promise<AdminOperation> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const operation = await api.adminOperation(ack.operation_id)
    if (['succeeded', 'failed', 'cancelled'].includes(operation.status)) return operation
    await new Promise((resolve) => window.setTimeout(resolve, 250))
  }
  throw new Error('Operation timed out')
}

function IdentityList({
  kind,
  locale,
  onExpired,
  onScopeChange,
}: {
  kind: IdentityKind
  locale: Locale
  onExpired: () => void
  onScopeChange: (session: AdminSession) => void
}) {
  const t = copy[locale]
  const [data, setData] = useState<IdentityPage>()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<10 | 25 | 50 | 100>(25)
  const [reload, setReload] = useState(0)
  const [message, setMessage] = useState('')
  const [creating, setCreating] = useState(false)
  const [detail, setDetail] = useState<IdentityResource>()

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.adminIdentity(kind, search.trim(), page, pageSize, controller.signal)
        .then(setData)
        .catch((cause) => {
          if (cause instanceof DOMException && cause.name === 'AbortError') return
          if (cause instanceof ApiError && cause.status === 401) onExpired()
          else setMessage(problem(cause, t.failed))
        })
    }, search ? 250 : 0)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [kind, onExpired, page, pageSize, reload, search, t.failed])

  async function run(command: () => Promise<OperationAck>) {
    setMessage('')
    try {
      const operation = await completedOperation(await command())
      if (operation.status === 'failed') {
        setMessage(`${operation.problem?.detail ?? t.failed} (${operation.openstack_request_ids.join(', ')})`)
      } else {
        setMessage(`${t.operation}: ${operation.status}. ${t.requestIds}: ${operation.openstack_request_ids.join(', ')}`)
        setReload((value) => value + 1)
      }
    } catch (cause) {
      setMessage(problem(cause, t.failed))
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    const name = String(values.get('name') ?? '')
    const confirm = window.prompt(`${t.confirm}: ${name}`)
    if (confirm !== name) return
    const payload: Record<string, unknown> = {
      name,
      description: String(values.get('description') ?? '') || null,
      ...(kind !== 'roles' ? { domain_id: String(values.get('domain_id') ?? '') || null } : {}),
      ...(kind === 'users' ? {
        email: String(values.get('email') ?? '') || null,
        password: String(values.get('password') ?? '') || null,
        enabled: true,
      } : {}),
      ...(kind === 'projects' ? { enabled: true } : {}),
    }
    await run(() => api.createAdminIdentity(kind, payload, confirm))
    form.reset()
    setCreating(false)
  }

  async function showDetail(item: IdentityResource) {
    setMessage('')
    try { setDetail(await api.adminIdentityDetail(kind, item.id)) }
    catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(problem(cause, t.failed))
    }
  }

  async function switchProjectScope(project: IdentityResource) {
    setMessage('')
    try { onScopeChange(await api.adminScope('project', project.id)) }
    catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(problem(cause, t.failed))
    }
  }

  return (
    <section className="admin-resource-page">
      <div className="page-heading admin-heading">
        <div><p className="eyebrow">{t.administration}</p><h1>{t[kind]}</h1></div>
        <button type="button" onClick={() => setCreating((value) => !value)}>{t.create}</button>
      </div>
      {message && <div className="error" role="status">{message}</div>}
      {detail && (
        <section className="admin-detail" aria-label={`${t.details}: ${detail.name}`}>
          <div className="section-heading"><h2>{detail.name}</h2><button type="button" className="secondary" onClick={() => setDetail(undefined)}>{t.close}</button></div>
          <dl><div><dt>{t.id}</dt><dd><code>{detail.id}</code></dd></div><div><dt>{t.domain}</dt><dd>{detail.domain_id ?? '—'}</dd></div><div><dt>{t.enabled}</dt><dd>{detail.enabled === null ? '—' : String(detail.enabled)}</dd></div></dl>
        </section>
      )}
      {creating && (
        <form className="admin-create-form" onSubmit={(event) => void create(event)}>
          <label>{t.name}<input name="name" required /></label>
          {kind !== 'roles' && <label>{t.domain}<input name="domain_id" defaultValue="default" /></label>}
          <label>Description<input name="description" /></label>
          {kind === 'users' && <label>Email<input name="email" type="email" /></label>}
          {kind === 'users' && <label>Password<input name="password" type="password" required /></label>}
          <button type="submit">{t.create}</button>
        </form>
      )}
      <div className="admin-toolbar">
        <label>{t.search}<input type="search" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} /></label>
      </div>
      <div className="admin-table">
        <div className="admin-table-row admin-table-header">
          <span>{t.name}</span><span>{t.id}</span><span>{t.domain}</span><span>{t.enabled}</span><span>{t.actions}</span>
        </div>
        {data?.items.map((item) => (
          <div className="admin-table-row" key={item.id}>
            <span><strong>{item.name}</strong><small>{item.description ?? item.email ?? ''}</small></span>
            <code>{item.id}</code><span>{item.domain_id ?? '—'}</span><span>{item.enabled === null ? '—' : String(item.enabled)}</span>
            <span className="admin-row-actions">
              <button type="button" className="secondary" onClick={() => void showDetail(item)}>{t.details}</button>
              {kind === 'projects' && <button type="button" className="secondary" onClick={() => void switchProjectScope(item)}>{t.useProjectScope}</button>}
              <button type="button" className="secondary" onClick={() => {
                const name = window.prompt(t.name, item.name)
                if (name && name !== item.name) void run(() => api.updateAdminIdentity(kind, item.id, { name }))
              }}>{t.edit}</button>
              {item.enabled === true && <button type="button" className="secondary" onClick={() => void run(() => api.updateAdminIdentity(kind, item.id, { enabled: false }))}>{t.disable}</button>}
              <button type="button" className="danger-secondary" onClick={() => {
                const confirm = window.prompt(`${t.confirm}: ${item.name}`)
                if (confirm === item.name || confirm === item.id) void run(() => api.deleteAdminIdentity(kind, item.id, confirm))
              }}>{t.delete}</button>
            </span>
          </div>
        ))}
        {data?.items.length === 0 && <p className="empty-state">{t.empty}</p>}
      </div>
      <Pagination page={data?.page} pageSize={pageSize} labels={t} onPage={setPage} onPageSize={(size) => { setPageSize(size); setPage(1) }} />
    </section>
  )
}

function Assignments({ locale, onExpired }: { locale: Locale; onExpired: () => void }) {
  const t = copy[locale]
  const [data, setData] = useState<RoleAssignmentPage>()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<10 | 25 | 50 | 100>(25)
  const [reload, setReload] = useState(0)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    api.adminAssignments(page, pageSize, controller.signal).then(setData).catch((cause) => {
      if (cause instanceof DOMException && cause.name === 'AbortError') return
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(problem(cause, t.failed))
    })
    return () => controller.abort()
  }, [onExpired, page, pageSize, reload, t.failed])

  async function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    const actorId = String(values.get('actor_id'))
    const confirm = window.prompt(`${t.confirm}: ${actorId}`)
    if (confirm !== actorId) return
    try {
      const operation = await completedOperation(await api.grantAdminRole({
        role_id: String(values.get('role_id')),
        actor_type: String(values.get('actor_type')),
        actor_id: actorId,
        scope_type: String(values.get('scope_type')),
        scope_id: String(values.get('scope_id')),
        inherited: values.get('inherited') === 'on',
      }, actorId))
      setMessage(`${t.operation}: ${operation.status}`)
      setReload((value) => value + 1)
    } catch (cause) { setMessage(problem(cause, t.failed)) }
  }

  return (
    <section className="admin-resource-page">
      <div className="page-heading"><div><p className="eyebrow">{t.administration}</p><h1>{t.assignments}</h1></div></div>
      {message && <div className="error" role="status">{message}</div>}
      <form className="assignment-form" onSubmit={(event) => void grant(event)}>
        <label>{t.roleId}<input name="role_id" required /></label>
        <label>{t.actorType}<select name="actor_type"><option value="user">user</option><option value="group">group</option></select></label>
        <label>{t.actor}<input name="actor_id" required /></label>
        <label>{t.scopeType}<select name="scope_type"><option value="project">project</option><option value="domain">domain</option><option value="system">system</option></select></label>
        <label>{t.scopeId}<input name="scope_id" defaultValue="all" required /></label>
        <label className="checkbox-label"><input name="inherited" type="checkbox" />{t.inherited}</label>
        <button type="submit">{t.grant}</button>
      </form>
      <div className="admin-table assignment-table">
        <div className="admin-table-row admin-table-header"><span>{t.roleId}</span><span>{t.actor}</span><span>{t.scope}</span><span>{t.actions}</span></div>
        {data?.items.map((item) => (
          <div className="admin-table-row" key={item.id}>
            <code>{item.role_id}</code><span>{item.actor_type}: {item.actor_id}</span><span>{item.scope_type}: {item.scope_id}</span>
            <span><button type="button" className="danger-secondary" onClick={() => {
              if (window.prompt(`${t.confirm}: ${item.id}`) === item.id) {
                void api.revokeAdminRole(item.id).then(completedOperation).then(() => setReload((value) => value + 1)).catch((cause) => setMessage(problem(cause, t.failed)))
              }
            }}>{t.delete}</button></span>
          </div>
        ))}
      </div>
      <Pagination page={data?.page} pageSize={pageSize} labels={t} onPage={setPage} onPageSize={(size) => { setPageSize(size); setPage(1) }} />
    </section>
  )
}

function AdminQuotas({ locale, onExpired }: { locale: Locale; onExpired: () => void }) {
  const t = copy[locale]
  const [projectId, setProjectId] = useState('')
  const [userId, setUserId] = useState('')
  const [data, setData] = useState<AdminQuotaCollection>()
  const [values, setValues] = useState<Record<string, number>>({})
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    if (!projectId) return
    try {
      const result = await api.adminQuotas(projectId, userId)
      setData(result)
      setValues(Object.fromEntries(result.quotas.map((item) => [`${item.service}:${item.resource}`, item.limit ?? -1])))
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setMessage(problem(cause, t.failed))
    }
  }, [onExpired, projectId, t.failed, userId])

  async function mutate(service: QuotaService, reset: boolean) {
    const confirm = window.prompt(`${t.confirm}: ${projectId}`)
    if (confirm !== projectId) return
    try {
      const serviceValues = Object.fromEntries(
        Object.entries(values).filter(([key]) => key.startsWith(`${service}:`)).map(([key, value]) => [key.split(':')[1], value]),
      )
      const ack = reset
        ? await api.resetAdminQuotas(projectId, service, service === 'compute' ? userId : '')
        : await api.updateAdminQuotas(projectId, service, serviceValues, service === 'compute' ? userId : '')
      const operation = await completedOperation(ack)
      setMessage(`${t.operation}: ${operation.status}. ${t.requestIds}: ${operation.openstack_request_ids.join(', ')}`)
      await load()
    } catch (cause) { setMessage(problem(cause, t.failed)) }
  }

  return (
    <section className="admin-resource-page">
      <div className="page-heading"><div><p className="eyebrow">{t.administration}</p><h1>{t.quotas}</h1></div></div>
      {message && <div className="error" role="status">{message}</div>}
      <form className="quota-project-form" onSubmit={(event) => { event.preventDefault(); void load() }}>
        <label>{t.projectId}<input value={projectId} onChange={(event) => setProjectId(event.target.value)} required /></label>
        <label>{t.userId}<input value={userId} onChange={(event) => setUserId(event.target.value)} /></label>
        <button type="submit">{t.load}</button>
      </form>
      {data?.partial_errors.map((item) => <div className="error" key={item.code}>{item.message} {item.openstack_request_id}</div>)}
      {(['compute', 'network', 'storage'] as QuotaService[]).map((service) => {
        const items = data?.quotas.filter((item) => item.service === service) ?? []
        if (!data || items.length === 0) return null
        return (
          <section className="admin-quota-service" key={service}>
            <div className="section-heading"><h2>{service}</h2><span className="admin-row-actions"><button type="button" onClick={() => void mutate(service, false)}>{t.apply}</button><button type="button" className="danger-secondary" onClick={() => void mutate(service, true)}>{t.reset}</button></span></div>
            <div className="admin-table quota-admin-table">
              <div className="admin-table-row admin-table-header"><span>{t.resource}</span><span>{t.used}</span><span>{t.reserved}</span><span>{t.default}</span><span>{t.limit}</span></div>
              {items.map((item) => (
                <div className="admin-table-row" key={`${service}:${item.resource}`}>
                  <strong>{item.resource}</strong><span>{item.used ?? '—'}</span><span>{item.reserved ?? '—'}</span><span>{item.default ?? 'Unlimited'}</span>
                  <input type="number" value={values[`${service}:${item.resource}`] ?? -1} onChange={(event) => setValues((current) => ({ ...current, [`${service}:${item.resource}`]: Number(event.target.value) }))} />
                </div>
              ))}
            </div>
          </section>
        )
      })}
    </section>
  )
}
