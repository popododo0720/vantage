import { useEffect, useState } from 'react'
import { ApiError, api } from './api'
import { Pagination } from './Pagination'
import type { FlavorPage, InventoryQuery, Operation } from './types'

type Locale = 'en' | 'ko'

const copy = {
  en: { flavors: 'Flavors', create: 'Create', edit: 'Edit', remove: 'Delete', name: 'Name',
    id: 'ID', vcpus: 'vCPU', ram: 'RAM (MiB)', disk: 'Disk (GiB)', public: 'Public',
    description: 'Description', extra: 'Extra specs', access: 'Project access', apply: 'Apply',
    rows: 'Rows per page', page: 'Page', previousPage: 'Previous page', nextPage: 'Next page',
    loading: 'Loading Flavors...', empty: 'No Flavors are visible.', failed: 'Request failed',
    add: 'Add', unset: 'Unset', deactivate: 'Deactivate', reactivate: 'Reactivate',
    member: 'Image member project', properties: 'Properties (key=value)', tags: 'Tags', protected: 'Protected' },
  ko: { flavors: 'Flavor', create: '생성', edit: '편집', remove: '삭제', name: '이름',
    id: 'ID', vcpus: 'vCPU', ram: 'RAM (MiB)', disk: '디스크 (GiB)', public: '공개',
    description: '설명', extra: 'Extra specs', access: '프로젝트 접근', apply: '적용',
    rows: '페이지당 행', page: '페이지', previousPage: '이전 페이지', nextPage: '다음 페이지',
    loading: 'Flavor를 불러오는 중...', empty: '표시할 Flavor가 없습니다.', failed: '요청 실패',
    add: '추가', unset: '제거', deactivate: '비활성화', reactivate: '재활성화',
    member: '이미지 멤버 프로젝트', properties: '속성(key=value)', tags: '태그', protected: '보호' },
} as const

export function ImageAdminPanel({ locale }: { locale: Locale }) {
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [form, setForm] = useState({ id: '', name: '', disk: 'qcow2', visibility: 'private', uri: '',
    properties: '', tags: '', project: '', protected: false })
  const t = copy[locale]
  async function run(call: () => Promise<Operation>) {
    try { const result = await call(); setMessage(result.status) }
    catch (cause) { setMessage(cause instanceof ApiError ? cause.problem.detail : copy[locale].failed) }
  }
  return <section className="resource-admin-panel">
    <button type="button" onClick={() => setOpen(!open)}>{copy[locale].create} / CRUD</button>
    {open && <div className="resource-admin-form">
      <input aria-label="Image ID" placeholder="Image ID (edit/delete)" value={form.id}
        onChange={(event) => setForm({ ...form, id: event.target.value })} />
      <input aria-label="Image name" placeholder="Image name" value={form.name}
        onChange={(event) => setForm({ ...form, name: event.target.value })} />
      <input aria-label="Disk format" value={form.disk}
        onChange={(event) => setForm({ ...form, disk: event.target.value })} />
      <select aria-label="Visibility" value={form.visibility}
        onChange={(event) => setForm({ ...form, visibility: event.target.value })}>
        {['private', 'shared', 'community', 'public'].map((value) => <option key={value}>{value}</option>)}
      </select>
      <input aria-label="Import URL" placeholder="Optional web-download URL" value={form.uri}
        onChange={(event) => setForm({ ...form, uri: event.target.value })} />
      <input aria-label={t.properties} placeholder={t.properties} value={form.properties}
        onChange={(event) => setForm({ ...form, properties: event.target.value })} />
      <input aria-label={t.tags} placeholder={t.tags} value={form.tags}
        onChange={(event) => setForm({ ...form, tags: event.target.value })} />
      <label><input type="checkbox" checked={form.protected}
        onChange={(event) => setForm({ ...form, protected: event.target.checked })} />{t.protected}</label>
      <input aria-label={t.member} placeholder={t.member} value={form.project}
        onChange={(event) => setForm({ ...form, project: event.target.value })} />
      <button type="button" onClick={() => void run(() => api.imageMutation(undefined, 'POST', {
        name: form.name, disk_format: form.disk, container_format: 'bare', visibility: form.visibility,
        protected: form.protected, properties: onePair(form.properties), tags: csv(form.tags),
        ...(form.uri ? { import_uri: form.uri } : {}),
      }))}>{copy[locale].create}</button>
      <button type="button" className="secondary" disabled={!form.id} onClick={() => void run(() =>
        api.imageMutation(form.id, 'PATCH', { name: form.name, visibility: form.visibility,
          protected: form.protected, properties: onePair(form.properties), tags: csv(form.tags) }))}>
        {copy[locale].edit}</button>
      <button type="button" className="secondary" disabled={!form.id} onClick={() => void run(() =>
        api.imageMutation(form.id, 'POST', { action: 'deactivate' }, '/actions'))}>{t.deactivate}</button>
      <button type="button" className="secondary" disabled={!form.id} onClick={() => void run(() =>
        api.imageMutation(form.id, 'POST', { action: 'reactivate' }, '/actions'))}>{t.reactivate}</button>
      <button type="button" className="secondary" disabled={!form.id || !form.project} onClick={() => void run(() =>
        api.imageMutation(form.id, 'POST', { project_id: form.project }, '/members'))}>{t.add} {t.member}</button>
      <button type="button" className="secondary" disabled={!form.id || !form.project} onClick={() => void run(() =>
        api.imageMutation(form.id, 'DELETE', undefined, `/members/${encodeURIComponent(form.project)}`))}>{t.unset} {t.member}</button>
      <button type="button" className="danger" disabled={!form.id} onClick={() => {
        if (window.confirm(`${copy[locale].remove} ${form.id}?`)) void run(() => api.imageMutation(form.id, 'DELETE'))
      }}>{copy[locale].remove}</button>
    </div>}
    {message && <p role="status">{message}</p>}
  </section>
}

export function FlavorsPage({ scopeKey, locale, query, onQuery, onExpired }: {
  scopeKey: string; locale: Locale; query: InventoryQuery;
  onQuery: (query: InventoryQuery, mode: 'push' | 'replace') => void; onExpired: () => void
}) {
  const t = copy[locale]
  const [page, setPage] = useState<FlavorPage>()
  const [failure, setFailure] = useState('')
  const [form, setForm] = useState({ id: '', name: '', vcpus: '1', ram: '1024', disk: '10',
    description: '', specs: '', project: '', isPublic: true })
  useEffect(() => {
    const controller = new AbortController()
    void api.flavors(query, controller.signal).then(setPage).catch((cause: unknown) => {
      if (cause instanceof ApiError && cause.status === 401) onExpired()
      else setFailure(cause instanceof ApiError ? cause.problem.detail : t.failed)
    })
    return () => controller.abort()
  }, [locale, onExpired, query, scopeKey, t.failed])

  async function run(call: () => Promise<Operation>) {
    try { const result = await call(); setFailure(result.status === 'failed' ? result.problem?.detail ?? t.failed : result.status) }
    catch (cause) { setFailure(cause instanceof ApiError ? cause.problem.detail : t.failed) }
  }
  const change = (name: Exclude<keyof typeof form, 'isPublic'>, value: string) => setForm({ ...form, [name]: value })
  return <>
    <div className="page-heading"><div><p className="eyebrow compact">Compute</p><h1>{t.flavors}</h1></div></div>
    <section className="resource-admin-panel">
      <div className="resource-admin-form">
        {(['id', 'name', 'vcpus', 'ram', 'disk', 'description', 'specs', 'project'] as const).map((field) =>
          <input key={field} aria-label={field} placeholder={field} value={form[field]}
            onChange={(event) => change(field, event.target.value)} />)}
        <label><input type="checkbox" checked={form.isPublic}
          onChange={(event) => setForm({ ...form, isPublic: event.target.checked })} />{t.public}</label>
        <button type="button" onClick={() => void run(() => api.flavorMutation(undefined, 'POST', {
          name: form.name, ...(form.id ? { id: form.id } : {}), vcpus: Number(form.vcpus),
          ram_mib: Number(form.ram), disk_gib: Number(form.disk), is_public: form.isPublic,
          description: form.description || undefined,
        }))}>{t.create}</button>
        <button type="button" className="secondary" disabled={!form.id} onClick={() => void run(() =>
          api.flavorMutation(form.id, 'PATCH', { description: form.description }))}>{t.edit}</button>
        <button type="button" className="secondary" disabled={!form.id || !form.specs} onClick={() => void run(() =>
          api.flavorMutation(form.id, 'PUT', { specs: onePair(form.specs) }, '/extra-specs'))}>{t.apply} {t.extra}</button>
        <button type="button" className="secondary" disabled={!form.id || !form.specs} onClick={() => void run(() =>
          api.flavorMutation(form.id, 'DELETE', undefined,
            `/extra-specs/${encodeURIComponent(form.specs.split('=', 1)[0])}`))}>{t.unset} {t.extra}</button>
        <button type="button" className="secondary" disabled={!form.id || !form.project} onClick={() => void run(() =>
          api.flavorMutation(form.id, 'POST', { project_id: form.project }, '/access'))}>{t.add} {t.access}</button>
        <button type="button" className="secondary" disabled={!form.id || !form.project} onClick={() => void run(() =>
          api.flavorMutation(form.id, 'DELETE', undefined,
            `/access/${encodeURIComponent(form.project)}`))}>{t.unset} {t.access}</button>
        <button type="button" className="danger" disabled={!form.id} onClick={() => {
          if (window.confirm(`${t.remove} ${form.id}?`)) void run(() => api.flavorMutation(form.id, 'DELETE'))
        }}>{t.remove}</button>
      </div>
    </section>
    {failure && <p className="error" role="alert">{failure}</p>}
    {!page && !failure && <p>{t.loading}</p>}
    {page?.items.length === 0 && <p>{t.empty}</p>}
    {page && page.items.length > 0 && <div className="resource-table">
      {page.items.map((flavor) => <div className="resource-table-row" key={flavor.id}>
        <strong>{flavor.name ?? flavor.id}</strong><span>{flavor.vcpus} vCPU</span>
        <span>{flavor.ram_mib} MiB</span><span>{flavor.disk_gib} GiB</span>
        <small>{flavor.id}</small>
      </div>)}
    </div>}
    {page && <Pagination page={page.page} pageSize={query.limit} labels={t}
      onPage={(next) => onQuery({ ...query, page: next }, 'push')}
      onPageSize={(limit) => onQuery({ limit, page: 1 }, 'replace')} />}
  </>
}

function csv(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function onePair(value: string): Record<string, string> {
  const [key, content = ''] = value.split('=', 2).map((item) => item.trim())
  return key ? { [key]: content } : {}
}
