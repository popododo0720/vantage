export interface Project {
  id: string
  name: string
  domain_id?: string
  enabled?: boolean
}

export interface Scope {
  project: Project
  region: string
}

export interface Session {
  user: { id: string; name: string; domain_id?: string }
  active_scope?: Scope | null
  expires_at: string
  regions: string[]
  locale: 'en' | 'ko'
}

export interface Problem {
  detail: string
  code: string
  trace_id: string
  openstack_request_id?: string
}

export interface PageInfo {
  number: number
  size: number
  item_from: number
  item_to: number
  total_items: number | null
  total_pages: number | null
  has_previous: boolean
  has_next: boolean
  navigable_pages: number[]
  openstack_request_id?: string | null
}

export interface ProjectPage {
  items: Project[]
  page: PageInfo
}

export type InstanceSort = 'created_at' | 'name' | 'status'
export type SortDirection = 'asc' | 'desc'

export interface InstanceQuery {
  limit: 10 | 25 | 50 | 100
  page: number
  name: string
  status: string
  imageId: string
  sort: InstanceSort
  direction: SortDirection
}

export interface Instance {
  id: string
  name: string | null
  status: string
  created_at: string | null
  flavor?: string | null
  image?: string | null
  addresses: string[] | null
}

export interface InstancePage {
  items: Instance[]
  page: PageInfo
}

export interface InstanceVolume {
  id: string
  device?: string | null
}

export interface InstanceDetail extends Instance {
  volumes: InstanceVolume[] | null
  openstack_request_id?: string | null
}

export type QuotaService = 'compute' | 'network' | 'storage'
export type QuotaUnit = 'count' | 'MiB' | 'GiB'
export type QuotaState = 'normal' | 'watch' | 'high' | 'unknown'

export interface Quota {
  service: QuotaService
  resource: string
  used: number
  reserved: number
  limit: number | null
  unit: QuotaUnit
  state: QuotaState
}

export interface WidgetError {
  code: string
  message: string
  openstack_request_id?: string
}

export interface QuotaPayload {
  scope: Scope
  generated_at: string
  stale: boolean
  quotas: Quota[]
  partial_errors: WidgetError[]
}

export interface InstanceSummary {
  total: number
  active: number | null
  stopped: number | null
  error: number | null
}

export interface ProjectOverview extends QuotaPayload {
  instance_summary: InstanceSummary | null
}
