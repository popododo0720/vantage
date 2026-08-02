import type { InstanceQuery, InstanceSort, SortDirection } from './types'

const PAGE_SIZES = [10, 25, 50, 100] as const
const SORTS: InstanceSort[] = ['created_at', 'name', 'status']
const DIRECTIONS: SortDirection[] = ['asc', 'desc']

export const DEFAULT_INSTANCE_QUERY: InstanceQuery = {
  limit: 25,
  page: 1,
  name: '',
  status: '',
  imageId: '',
  sort: 'created_at',
  direction: 'desc',
}

function pageSize(value: string | null): InstanceQuery['limit'] {
  const parsed = Number(value)
  return PAGE_SIZES.includes(parsed as InstanceQuery['limit'])
    ? parsed as InstanceQuery['limit']
    : DEFAULT_INSTANCE_QUERY.limit
}

function pageNumber(value: string | null): number {
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1
}

function instanceSort(value: string | null): InstanceSort {
  return SORTS.includes(value as InstanceSort) ? value as InstanceSort : DEFAULT_INSTANCE_QUERY.sort
}

function sortDirection(value: string | null): SortDirection {
  return DIRECTIONS.includes(value as SortDirection)
    ? value as SortDirection
    : DEFAULT_INSTANCE_QUERY.direction
}

export function parseInstanceRoute(value: string): {
  query: InstanceQuery
  instanceId?: string
} | undefined {
  const url = new URL(value, window.location.origin)
  let instanceId: string | undefined
  if (url.pathname !== '/instances') {
    const match = url.pathname.match(/^\/instances\/([^/]+)$/)
    if (!match) return undefined
    try {
      instanceId = decodeURIComponent(match[1])
    } catch {
      return undefined
    }
    if (!instanceId) return undefined
  }
  return {
    query: {
      limit: pageSize(url.searchParams.get('limit')),
      page: pageNumber(url.searchParams.get('page')),
      name: url.searchParams.get('name') ?? '',
      status: url.searchParams.get('status') ?? '',
      imageId: url.searchParams.get('image_id') ?? '',
      sort: instanceSort(url.searchParams.get('sort')),
      direction: sortDirection(url.searchParams.get('direction')),
    },
    instanceId,
  }
}

export function instancePath(query: InstanceQuery, instanceId?: string): string {
  const search = new URLSearchParams()
  if (query.limit !== DEFAULT_INSTANCE_QUERY.limit) search.set('limit', String(query.limit))
  if (query.page !== 1) search.set('page', String(query.page))
  if (query.name) search.set('name', query.name)
  if (query.status) search.set('status', query.status)
  if (query.imageId) search.set('image_id', query.imageId)
  if (query.sort !== DEFAULT_INSTANCE_QUERY.sort) search.set('sort', query.sort)
  if (query.direction !== DEFAULT_INSTANCE_QUERY.direction) search.set('direction', query.direction)
  const suffix = search.size > 0 ? `?${search}` : ''
  return `${instanceId ? `/instances/${encodeURIComponent(instanceId)}` : '/instances'}${suffix}`
}
