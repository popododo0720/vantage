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
  admin_available?: boolean
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

export interface InventoryQuery {
  limit: 10 | 25 | 50 | 100
  page: number
}

export type ImageVisibility = '' | 'private' | 'shared' | 'community' | 'public'

export interface ImageQuery extends InventoryQuery {
  name: string
  visibility: ImageVisibility
}

export interface Image {
  id: string
  name: string | null
  status: string
  visibility: string
  disk_format?: string | null
  container_format?: string | null
  size_bytes?: number | null
  min_disk_gib?: number | null
  min_ram_mib?: number | null
  created_at?: string | null
}

export interface ImagePage {
  items: Image[]
  page: PageInfo
}

export interface KeyPair {
  name: string
  type: 'ssh' | 'x509' | null
  fingerprint: string | null
  public_key_preview?: string | null
  created_at?: string | null
  last_used_at?: string | null
}

export interface KeyPairPage {
  items: KeyPair[]
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

export type AdminScopeType = 'system' | 'domain' | 'project'

export interface AdminScope {
  type: AdminScopeType
  id: string
  name: string
}

export interface AdminSession {
  available_scopes: AdminScope[]
  active_scope: AdminScope | null
}

export type IdentityKind = 'projects' | 'users' | 'groups' | 'roles'

export interface IdentityResource {
  id: string
  name: string
  description: string | null
  domain_id: string | null
  enabled: boolean | null
  default_project_id: string | null
  email: string | null
  parent_id: string | null
  extra: Record<string, unknown>
}

export interface IdentityPage {
  items: IdentityResource[]
  page: PageInfo
}

export interface RoleAssignment {
  id: string
  role_id: string
  actor_type: 'user' | 'group'
  actor_id: string
  scope_type: AdminScopeType
  scope_id: string
  inherited: boolean
}

export interface RoleAssignmentPage {
  items: RoleAssignment[]
  page: PageInfo
}

export interface AdminQuota {
  service: QuotaService
  resource: string
  limit: number | null
  used: number | null
  reserved: number | null
  default: number | null
  user_id: string | null
}

export interface AdminQuotaCollection {
  project_id: string
  generated_at: string
  quotas: AdminQuota[]
  partial_errors: WidgetError[]
}

export interface OperationAck {
  operation_id: string
  status: string
  trace_id: string
  replayed: boolean
}

export interface AdminOperation {
  id: string
  kind: string
  status: 'accepted' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  submitted_at: string
  updated_at: string
  target_type: string
  target_id: string | null
  target_name: string | null
  trace_id: string
  openstack_request_ids: string[]
  problem: { status: number; code: string; detail: string; openstack_request_id?: string } | null
}
