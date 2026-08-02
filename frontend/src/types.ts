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

export interface ProjectPage {
  items: Project[]
  page: {
    number: number
    size: number
    item_from: number
    item_to: number
    total_items: number | null
    total_pages: number | null
    has_previous: boolean
    has_next: boolean
    navigable_pages: number[]
  }
}
