import type { StorageQuery, StorageResource } from './types'

const PAGE_SIZES = new Set([10, 25, 50, 100])
const RESOURCES = new Set<StorageResource>([
  'volumes', 'snapshots', 'backups', 'types', 'qos', 'pools', 'services',
])

export const DEFAULT_STORAGE_QUERY: StorageQuery = {
  resource: 'volumes', page: 1, limit: 25, name: '', status: '',
  sort: 'created_at', direction: 'desc',
}

export function parseStorageRoute(value: string): StorageQuery | undefined {
  const url = new URL(value, window.location.origin)
  if (url.pathname !== '/storage') return undefined
  const resource = url.searchParams.get('resource') as StorageResource | null
  const limit = Number(url.searchParams.get('limit') ?? 25)
  const page = Number(url.searchParams.get('page') ?? 1)
  const sort = url.searchParams.get('sort')
  const direction = url.searchParams.get('direction')
  return {
    resource: resource && RESOURCES.has(resource) ? resource : 'volumes',
    limit: (PAGE_SIZES.has(limit) ? limit : 25) as StorageQuery['limit'],
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    name: url.searchParams.get('name') ?? '',
    status: url.searchParams.get('status') ?? '',
    sort: sort === 'name' || sort === 'status' ? sort : 'created_at',
    direction: direction === 'asc' ? 'asc' : 'desc',
  }
}

export function storagePath(query: StorageQuery): string {
  const params = new URLSearchParams()
  if (query.resource !== 'volumes') params.set('resource', query.resource)
  if (query.page !== 1) params.set('page', String(query.page))
  if (query.limit !== 25) params.set('limit', String(query.limit))
  if (query.name) params.set('name', query.name)
  if (query.status) params.set('status', query.status)
  if (query.sort !== 'created_at') params.set('sort', query.sort)
  if (query.direction !== 'desc') params.set('direction', query.direction)
  const queryString = params.toString()
  return `/storage${queryString ? `?${queryString}` : ''}`
}
