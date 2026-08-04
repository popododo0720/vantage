import { useState } from 'react'
import { ApiError, api } from './api'
import type { CreateInstancePayload, InstanceDetail, Operation } from './types'

type Locale = 'en' | 'ko'

const labels = {
  en: {
    create: 'Create instance', cancel: 'Cancel', back: 'Back', next: 'Next', launch: 'Launch',
    basics: 'Basics', access: 'Network & access', advanced: 'Advanced', review: 'Review',
    name: 'Name', description: 'Description', count: 'Count', boot: 'Boot source', image: 'Image',
    volume: 'Volume', sourceId: 'Source ID', bootVolume: 'Create boot volume', volumeSize: 'Volume size (GiB)',
    flavor: 'Flavor ID', networkMode: 'Network selection', network: 'Network ID', subnet: 'Subnet ID',
    port: 'Existing port ID', securityGroups: 'Security group IDs (comma separated)', keypair: 'Key pair',
    zone: 'Availability zone', metadata: 'Metadata (key=value, one per line)', configDrive: 'Config drive',
    userData: 'User data', submitting: 'Submitting...', accepted: 'Operation accepted', failed: 'Operation failed',
    edit: 'Edit', console: 'Console', snapshot: 'Snapshot', resize: 'Resize', rebuild: 'Rebuild',
    delete: 'Delete', networkActions: 'Attach NIC / Floating IP', networkBoundary: 'Provided by Network API',
    imageId: 'Image ID', confirmResize: 'Confirm resize', revertResize: 'Revert resize',
    deleteVolumes: 'Attached volumes retained',
    actions: { start: 'Start', stop: 'Stop', soft_reboot: 'Soft reboot', hard_reboot: 'Hard reboot',
      pause: 'Pause', unpause: 'Unpause', suspend: 'Suspend', resume: 'Resume', shelve: 'Shelve',
      unshelve: 'Unshelve', rescue: 'Rescue', unrescue: 'Unrescue', lock: 'Lock', unlock: 'Unlock' },
  },
  ko: {
    create: '인스턴스 생성', cancel: '취소', back: '이전', next: '다음', launch: '생성',
    basics: '기본 정보', access: '네트워크 및 접근', advanced: '고급 설정', review: '검토',
    name: '이름', description: '설명', count: '개수', boot: '부팅 소스', image: '이미지',
    volume: '볼륨', sourceId: '소스 ID', bootVolume: '부팅 볼륨 생성', volumeSize: '볼륨 크기(GiB)',
    flavor: 'Flavor ID', networkMode: '네트워크 선택', network: '네트워크 ID', subnet: '서브넷 ID',
    port: '기존 포트 ID', securityGroups: '보안 그룹 ID(쉼표 구분)', keypair: '키 페어',
    zone: '가용 영역', metadata: '메타데이터(한 줄에 key=value)', configDrive: 'Config drive',
    userData: '사용자 데이터', submitting: '요청 중...', accepted: '작업이 접수되었습니다', failed: '작업 실패',
    edit: '편집', console: '콘솔', snapshot: '스냅샷', resize: '크기 변경', rebuild: '재빌드',
    delete: '삭제', networkActions: 'NIC / Floating IP 연결', networkBoundary: 'Network API에서 제공',
    imageId: '이미지 ID', confirmResize: '크기 변경 확정', revertResize: '크기 변경 되돌리기',
    deleteVolumes: '연결된 볼륨은 유지됨',
    actions: { start: '시작', stop: '정지', soft_reboot: '소프트 재부팅', hard_reboot: '하드 재부팅',
      pause: '일시 정지', unpause: '일시 정지 해제', suspend: '중단', resume: '재개', shelve: 'Shelve',
      unshelve: 'Unshelve', rescue: '복구 모드', unrescue: '복구 모드 해제', lock: '잠금', unlock: '잠금 해제' },
  },
} as const

export function CreateInstanceButton({ locale }: { locale: Locale }) {
  const t = labels[locale]
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>{t.create}</button>
      {open && <CreateWizard locale={locale} onClose={() => setOpen(false)} />}
    </>
  )
}

function CreateWizard({ locale, onClose }: { locale: Locale; onClose: () => void }) {
  const t = labels[locale]
  const [step, setStep] = useState(0)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const [form, setForm] = useState({
    name: '', description: '', count: '1', bootType: 'image', sourceId: '', bootVolume: false,
    volumeSize: '', flavorId: '', networkMode: 'network', networkId: '', subnetId: '', portId: '',
    securityGroups: '', keypair: '', zone: '', metadata: '', configDrive: false, userData: '',
  })
  const steps = [t.basics, t.access, t.advanced, t.review]
  const set = (name: keyof typeof form, value: string | boolean) =>
    setForm((current) => ({ ...current, [name]: value }))

  async function launch() {
    setPending(true)
    setMessage('')
    try {
      const bootSource = form.bootType === 'image'
        ? {
            type: 'image' as const,
            image_id: form.sourceId,
            create_boot_volume: form.bootVolume,
            ...(form.volumeSize ? { volume_size_gib: Number(form.volumeSize) } : {}),
          }
        : { type: 'volume' as const, volume_id: form.sourceId, delete_on_termination: false }
      const network = form.networkMode === 'port'
        ? { port_id: form.portId }
        : {
            network_id: form.networkId,
            ...(form.subnetId ? { subnet_id: form.subnetId } : {}),
          }
      const payload: CreateInstancePayload = {
        name: form.name,
        ...(form.description ? { description: form.description } : {}),
        count: Number(form.count), flavor_id: form.flavorId, boot_source: bootSource,
        networks: [network],
        security_group_ids: csv(form.securityGroups),
        ...(form.keypair ? { keypair_name: form.keypair } : {}),
        ...(form.zone ? { availability_zone: form.zone } : {}),
        metadata: metadata(form.metadata), config_drive: form.configDrive,
        ...(form.userData ? { user_data: form.userData } : {}),
      }
      const operation = await api.createInstance(payload)
      setMessage(operation.status === 'failed' ? operation.problem?.detail ?? t.failed : t.accepted)
      if (operation.status !== 'failed') window.setTimeout(onClose, 600)
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.problem.detail : t.failed)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="instance-drawer-backdrop">
      <section className="instance-drawer create-wizard" role="dialog" aria-modal="true" aria-label={t.create}>
        <header className="instance-drawer-header"><h2>{t.create}</h2>
          <button type="button" className="secondary" onClick={onClose}>{t.cancel}</button>
        </header>
        <ol className="wizard-steps">{steps.map((label, index) =>
          <li className={index === step ? 'active' : ''} key={label}>{index + 1}. {label}</li>)}</ol>
        <div className="wizard-fields">
          {step === 0 && <>
            <Field label={t.name} value={form.name} onChange={(value) => set('name', value)} required />
            <Field label={t.description} value={form.description} onChange={(value) => set('description', value)} />
            <Field label={t.count} value={form.count} type="number" onChange={(value) => set('count', value)} required />
            <label>{t.boot}<select value={form.bootType} onChange={(event) => set('bootType', event.target.value)}>
              <option value="image">{t.image}</option><option value="volume">{t.volume}</option>
            </select></label>
            <Field label={t.sourceId} value={form.sourceId} onChange={(value) => set('sourceId', value)} required />
            {form.bootType === 'image' && <>
              <Check label={t.bootVolume} checked={form.bootVolume} onChange={(value) => set('bootVolume', value)} />
              {form.bootVolume && <Field label={t.volumeSize} value={form.volumeSize} type="number" onChange={(value) => set('volumeSize', value)} />}
            </>}
            <Field label={t.flavor} value={form.flavorId} onChange={(value) => set('flavorId', value)} required />
          </>}
          {step === 1 && <>
            <label>{t.networkMode}<select value={form.networkMode} onChange={(event) => set('networkMode', event.target.value)}>
              <option value="network">{t.network}</option><option value="port">{t.port}</option>
            </select></label>
            {form.networkMode === 'port'
              ? <Field label={t.port} value={form.portId} onChange={(value) => set('portId', value)} required />
              : <><Field label={t.network} value={form.networkId} onChange={(value) => set('networkId', value)} required />
                <Field label={t.subnet} value={form.subnetId} onChange={(value) => set('subnetId', value)} /></>}
            <Field label={t.securityGroups} value={form.securityGroups} onChange={(value) => set('securityGroups', value)} />
            <Field label={t.keypair} value={form.keypair} onChange={(value) => set('keypair', value)} />
          </>}
          {step === 2 && <>
            <Field label={t.zone} value={form.zone} onChange={(value) => set('zone', value)} />
            <label>{t.metadata}<textarea value={form.metadata} onChange={(event) => set('metadata', event.target.value)} /></label>
            <Check label={t.configDrive} checked={form.configDrive} onChange={(value) => set('configDrive', value)} />
            <label>{t.userData}<textarea value={form.userData} onChange={(event) => set('userData', event.target.value)} /></label>
          </>}
          {step === 3 && <pre className="wizard-review">{JSON.stringify({ ...form, userData: form.userData ? '••••••' : '' }, null, 2)}</pre>}
        </div>
        {message && <p role="status">{message}</p>}
        <footer className="wizard-actions">
          {step > 0 && <button type="button" className="secondary" onClick={() => setStep(step - 1)}>{t.back}</button>}
          {step < 3
            ? <button type="button" onClick={() => setStep(step + 1)}>{t.next}</button>
            : <button type="button" disabled={pending || !form.name || !form.sourceId || !form.flavorId}
                onClick={() => void launch()}>{pending ? t.submitting : t.launch}</button>}
        </footer>
      </section>
    </div>
  )
}

export function InstanceActions({ instance, locale, onChanged }: {
  instance: InstanceDetail; locale: Locale; onChanged: () => void
}) {
  const t = labels[locale]
  const [pending, setPending] = useState('')
  const [message, setMessage] = useState('')
  const actions = stateActions(instance.status)

  async function run(label: string, call: () => Promise<Operation>, destructive = false) {
    if (destructive && !window.confirm(`${label}: ${instance.name ?? instance.id}?`)) return
    setPending(label); setMessage('')
    try {
      const operation = await call()
      setMessage(operation.status === 'failed' ? operation.problem?.detail ?? t.failed : t.accepted)
      onChanged()
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.problem.detail : t.failed)
    } finally { setPending('') }
  }

  async function remove() {
    setPending(t.delete); setMessage('')
    try {
      const preview = await api.deletePreview(instance.id)
      const volumes = preview.attached_volume_ids.length
        ? `\n${t.deleteVolumes}: ${preview.attached_volume_ids.join(', ')}` : ''
      if (!window.confirm(`${t.delete}: ${instance.name ?? instance.id}?${volumes}`)) return
      const operation = await api.deleteInstance(instance.id)
      setMessage(operation.status === 'failed' ? operation.problem?.detail ?? t.failed : t.accepted)
      onChanged()
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.problem.detail : t.failed)
    } finally { setPending('') }
  }

  return (
    <section className="instance-actions" aria-label="Instance actions">
      <div className="instance-action-buttons">
        {actions.map((action) => <button type="button" className="secondary" key={action}
          disabled={Boolean(pending)} onClick={() => void run(action, () => api.instanceAction(instance.id, action), action === 'hard_reboot')}>
          {t.actions[action as keyof typeof t.actions]}</button>)}
        <button type="button" className="secondary" onClick={() => {
          const name = window.prompt(t.name, instance.name ?? '')
          if (name === null || !name) return
          const description = window.prompt(t.description, instance.description ?? '')
          if (description === null) return
          const before = instance.metadata ?? {}
          const rawMetadata = window.prompt(t.metadata,
            Object.entries(before).map(([key, value]) => `${key}=${value}`).join('\n'))
          if (rawMetadata === null) return
          const nextMetadata = metadata(rawMetadata)
          const unsetMetadata = Object.keys(before).filter((key) => !(key in nextMetadata))
          void run(t.edit, () => api.updateInstance(instance.id, {
            name, description, metadata: nextMetadata, unset_metadata: unsetMetadata,
          }))
        }}>{t.edit}</button>
        <button type="button" className="secondary" onClick={() => {
          const flavor = window.prompt(t.flavor)
          if (flavor) void run(t.resize, () => api.resizeInstance(instance.id, flavor))
        }}>{t.resize}</button>
        <button type="button" className="secondary" onClick={() => {
          const image = window.prompt(`${t.rebuild} ${t.imageId}`)
          if (image) void run(t.rebuild, () => api.rebuildInstance(instance.id, image), true)
        }}>{t.rebuild}</button>
        <button type="button" className="secondary" onClick={() => {
          const name = window.prompt(t.snapshot, `${instance.name ?? 'instance'}-snapshot`)
          if (name) void run(t.snapshot, () => api.snapshotInstance(instance.id, name))
        }}>{t.snapshot}</button>
        <button type="button" className="secondary" onClick={() => void api.console(instance.id).then((session) => {
          window.open(session.url, '_blank', 'noopener,noreferrer')
        }).catch((cause: unknown) => setMessage(cause instanceof ApiError ? cause.problem.detail : t.failed))}>{t.console}</button>
        {instance.status === 'VERIFY_RESIZE' && <>
          <button type="button" onClick={() => void run(t.confirmResize, () => api.resizeDecision(instance.id, 'confirm'))}>{t.confirmResize}</button>
          <button type="button" className="secondary" onClick={() => void run(t.revertResize, () => api.resizeDecision(instance.id, 'revert'))}>{t.revertResize}</button>
        </>}
        <button type="button" className="danger" disabled={Boolean(pending)} onClick={() => void remove()}>{t.delete}</button>
      </div>
      <button type="button" className="secondary" disabled title={t.networkBoundary}>{t.networkActions}</button>
      {message && <p role="status">{message}</p>}
    </section>
  )
}

function stateActions(status: string): string[] {
  const state = status.toUpperCase()
  if (state === 'SHUTOFF') return ['start', 'shelve', 'lock', 'rescue']
  if (state === 'PAUSED') return ['unpause', 'hard_reboot', 'lock']
  if (state === 'SUSPENDED') return ['resume', 'lock']
  if (state.startsWith('SHELVED')) return ['unshelve']
  if (state === 'RESCUE') return ['unrescue']
  return ['stop', 'soft_reboot', 'hard_reboot', 'pause', 'suspend', 'shelve', 'lock', 'unlock', 'rescue']
}

function csv(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function metadata(value: string): Record<string, string> {
  return Object.fromEntries(value.split('\n').map((line) => line.split('=', 2).map((part) => part.trim()))
    .filter((parts): parts is [string, string] => parts.length === 2 && Boolean(parts[0])))
}

function Field({ label, value, onChange, type = 'text', required = false }: {
  label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean
}) {
  return <label>{label}<input type={type} value={value} required={required}
    min={type === 'number' ? 1 : undefined} onChange={(event) => onChange(event.target.value)} /></label>
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="check-field"><input type="checkbox" checked={checked}
    onChange={(event) => onChange(event.target.checked)} />{label}</label>
}
