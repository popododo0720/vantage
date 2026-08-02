import type { ImageQuery, InventoryQuery } from './types'

const PAGE_SIZES = [10, 25, 50, 100] as const

export const DEFAULT_IMAGE_QUERY: ImageQuery = {
  limit: 25,
  page: 1,
  name: '',
  visibility: '',
}

export const DEFAULT_KEYPAIR_QUERY: InventoryQuery = {
  limit: 25,
  page: 1,
}

function limit(value: string | null): InventoryQuery['limit'] {
  const parsed = Number(value)
  return PAGE_SIZES.includes(parsed as InventoryQuery['limit'])
    ? parsed as InventoryQuery['limit']
    : 25
}

function page(value: string | null): number {
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1
}

function visibility(value: string | null): ImageQuery['visibility'] {
  return value === 'private'
    || value === 'shared'
    || value === 'community'
    || value === 'public'
    ? value
    : ''
}

export function parseImageRoute(value: string): ImageQuery | undefined {
  const url = new URL(value, window.location.origin)
  if (url.pathname !== '/images') return undefined
  return {
    limit: limit(url.searchParams.get('limit')),
    page: page(url.searchParams.get('page')),
    name: url.searchParams.get('name') ?? '',
    visibility: visibility(url.searchParams.get('visibility')),
  }
}

export function parseKeyPairRoute(value: string): InventoryQuery | undefined {
  const url = new URL(value, window.location.origin)
  if (url.pathname !== '/keypairs') return undefined
  return {
    limit: limit(url.searchParams.get('limit')),
    page: page(url.searchParams.get('page')),
  }
}

function basePath(query: InventoryQuery): URLSearchParams {
  const search = new URLSearchParams()
  if (query.limit !== 25) search.set('limit', String(query.limit))
  if (query.page !== 1) search.set('page', String(query.page))
  return search
}

export function imagePath(query: ImageQuery): string {
  const search = basePath(query)
  if (query.name) search.set('name', query.name)
  if (query.visibility) search.set('visibility', query.visibility)
  return `/images${search.size ? `?${search}` : ''}`
}

export function keyPairPath(query: InventoryQuery): string {
  const search = basePath(query)
  return `/keypairs${search.size ? `?${search}` : ''}`
}
