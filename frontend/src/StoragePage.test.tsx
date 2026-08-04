import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { StoragePage } from './StoragePage'
import { DEFAULT_STORAGE_QUERY } from './storage-route'
import type { StoragePage as StoragePayload, StorageQuery } from './types'

const payload: StoragePayload = {
  items: [{
    id: 'volume-with-a-very-long-resource-identifier-that-must-wrap-on-mobile',
    name: 'database-volume-with-a-long-display-name', description: 'Data', status: 'available',
    size_gib: 100, volume_type: 'fast', availability_zone: 'nova', bootable: false,
    encrypted: false, multiattach: false, read_only: false,
    metadata: { environment: 'production' }, attachments: [],
    created_at: '2026-08-04T00:00:00Z',
  }],
  page: {
    number: 1, size: 25, item_from: 1, item_to: 1, total_items: null, total_pages: null,
    has_previous: false, has_next: true, navigable_pages: [1, 2],
    openstack_request_id: 'req-storage-list',
  },
  partial_errors: [],
}

describe('StoragePage', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('shows project and admin resources with numbered pagination', async () => {
    vi.spyOn(api, 'storage').mockResolvedValue(payload)
    const onQuery = vi.fn()
    render(<StoragePage scopeKey="project-alpha:RegionOne" locale="en"
      query={DEFAULT_STORAGE_QUERY} onQuery={onQuery} onExpired={vi.fn()} />)

    expect(await screen.findByText('database-volume-with-a-long-display-name')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Volume types' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next page' })).toBeInTheDocument()
    expect(document.querySelector('.storage-grid')).toBeInTheDocument()
    expect(document.querySelector('.storage-card')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Volume types' }))
    expect(onQuery).toHaveBeenCalledWith(expect.objectContaining({
      resource: 'types', page: 1, sort: 'name', direction: 'asc',
    }), 'push')
  })

  it('uses Korean strings and exposes all volume action names', async () => {
    vi.spyOn(api, 'storage').mockResolvedValue(payload)
    render(<StoragePage scopeKey="project-alpha:RegionOne" locale="ko"
      query={DEFAULT_STORAGE_QUERY} onQuery={vi.fn()} onExpired={vi.fn()} />)
    await screen.findByText('database-volume-with-a-long-display-name')
    fireEvent.click(screen.getByRole('button', { name: '작업' }))
    const options = Array.from(screen.getByLabelText('작업').querySelectorAll('option'))
      .map((option) => option.textContent)
    expect(options).toEqual(expect.arrayContaining([
      'attach', 'detach', 'extend', 'retype', 'migrate', 'create_transfer',
      'accept_transfer', 'upload_to_image', 'set_bootable', 'set_read_only',
      'revert_to_snapshot', 'unmanage', 'force_delete',
    ]))
  })

  it('keeps stale data on a temporary partial failure', async () => {
    const storage = vi.spyOn(api, 'storage')
      .mockResolvedValueOnce(payload)
      .mockRejectedValueOnce(new Error('temporary'))
    const { rerender } = render(<StoragePage scopeKey="project-alpha:RegionOne" locale="en"
      query={DEFAULT_STORAGE_QUERY} onQuery={vi.fn()} onExpired={vi.fn()} />)
    await screen.findByText('database-volume-with-a-long-display-name')
    const changed: StorageQuery = { ...DEFAULT_STORAGE_QUERY, status: 'available' }
    rerender(<StoragePage scopeKey="project-alpha:RegionOne" locale="en"
      query={changed} onQuery={vi.fn()} onExpired={vi.fn()} />)
    await waitFor(() => expect(storage).toHaveBeenCalledTimes(2))
    expect(screen.getByText('database-volume-with-a-long-display-name')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load storage resources.')
  })
})
