import type { NetworkQuery, ResourceKind } from './types'

export const RESOURCE_KINDS: ResourceKind[] = [
  'network',
  'subnet',
  'port',
  'router',
  'floating_ip',
  'security_group',
  'security_group_rule',
  'qos_policy',
  'qos_rule',
  'rbac_policy',
  'load_balancer',
  'listener',
  'pool',
  'member',
  'health_monitor',
  'l7_policy',
  'l7_rule',
]

export const DEFAULT_NETWORK_QUERY: NetworkQuery = {
  kind: 'network',
  limit: 25,
  page: 1,
  name: '',
  status: '',
  parentId: '',
  ruleType: '',
}

function pageSize(value: string | null): NetworkQuery['limit'] {
  const parsed = Number(value)
  return parsed === 10 || parsed === 50 || parsed === 100 ? parsed : 25
}

export function parseNetworkRoute(value: string): NetworkQuery | undefined {
  const url = new URL(value, window.location.origin)
  const match = /^\/network\/([^/]+)$/.exec(url.pathname)
  if (!match || !RESOURCE_KINDS.includes(match[1] as ResourceKind)) return undefined
  return {
    kind: match[1] as ResourceKind,
    limit: pageSize(url.searchParams.get('limit')),
    page: Math.max(1, Number(url.searchParams.get('page')) || 1),
    name: url.searchParams.get('name') ?? '',
    status: url.searchParams.get('status') ?? '',
    parentId: url.searchParams.get('parent_id') ?? '',
    ruleType: url.searchParams.get('rule_type') ?? '',
  }
}

export function networkPath(query: NetworkQuery): string {
  const params = new URLSearchParams()
  if (query.limit !== 25) params.set('limit', String(query.limit))
  if (query.page !== 1) params.set('page', String(query.page))
  if (query.name) params.set('name', query.name)
  if (query.status) params.set('status', query.status)
  if (query.parentId) params.set('parent_id', query.parentId)
  if (query.ruleType) params.set('rule_type', query.ruleType)
  const suffix = params.size ? `?${params}` : ''
  return `/network/${query.kind}${suffix}`
}
