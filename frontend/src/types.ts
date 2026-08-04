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

export interface Flavor {
  id: string
  name: string | null
  vcpus: number | null
  ram_mib: number | null
  disk_gib: number | null
  ephemeral_gib?: number | null
  is_public?: boolean | null
  description?: string | null
  extra_specs?: Record<string, string> | null
}

export interface FlavorPage {
  items: Flavor[]
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
  description?: string | null
  metadata?: Record<string, string> | null
  availability_zone?: string | null
  locked?: boolean | null
  openstack_request_id?: string | null
}

export interface Operation {
  id: string
  kind: string
  status: 'accepted' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  target: { resource_type: string; resource_id?: string | null; resource_name?: string | null }
  openstack_request_ids: string[]
  problem?: { detail: string; openstack_request_id?: string | null } | null
}

export interface CreateInstancePayload {
  name: string
  description?: string
  count: number
  flavor_id: string
  boot_source:
    | { type: 'image'; image_id: string; create_boot_volume: boolean; volume_size_gib?: number }
    | { type: 'volume'; volume_id: string; delete_on_termination: boolean }
  networks: Array<{ network_id?: string; subnet_id?: string; port_id?: string }>
  security_group_ids: string[]
  keypair_name?: string
  availability_zone?: string
  metadata: Record<string, string>
  config_drive: boolean
  user_data?: string
}

export interface ConsoleSession {
  instance_id: string
  type: 'novnc'
  url: string
  expires_at: string
  openstack_request_id?: string | null
}

export interface DeletePreview {
  instance_id: string
  attached_volume_ids: string[]
  network_contract: string
  floating_ip_contract: string
  warning: string
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
