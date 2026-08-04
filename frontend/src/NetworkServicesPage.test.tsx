import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { NetworkServicesPage } from './NetworkServicesPage'
import type {
  NetworkCapabilities,
  NetworkQuery,
  NetworkResource,
  NetworkResourcePage,
} from './types'

const query: NetworkQuery = {
  kind: 'load_balancer',
  limit: 25,
  page: 1,
  name: '',
  status: '',
  parentId: '',
  ruleType: '',
}

const resource: NetworkResource = {
  id: '11111111-1111-1111-1111-111111111111',
  resource_type: 'load_balancer',
  name: 'public-lb',
  project_id: 'project-alpha',
  status: 'ACTIVE',
  provisioning_status: 'ACTIVE',
  operating_status: 'ONLINE',
  revision_number: 4,
  created_at: '2026-08-04T00:00:00Z',
  updated_at: '2026-08-04T00:00:00Z',
  attributes: { vip_subnet_id: 'subnet-1' },
}

const capabilities: NetworkCapabilities = {
  neutron: true,
  octavia: true,
  resources: [
    {
      resource_type: 'load_balancer',
      service: 'load-balancer',
      available: true,
      parent_required: false,
      fields: [
        {
          name: 'name',
          create: true,
          update: true,
          required: false,
          admin_only: false,
          extension: null,
          immutable_reason_en: null,
          immutable_reason_ko: null,
        },
        {
          name: 'vip_subnet_id',
          create: true,
          update: false,
          required: false,
          admin_only: false,
          extension: null,
          immutable_reason_en: 'OpenStack does not allow this field to be edited.',
          immutable_reason_ko: 'OpenStack에서 이 필드의 편집을 허용하지 않습니다.',
        },
      ],
      actions: ['failover'],
    },
  ],
}

const page: NetworkResourcePage = {
  items: [resource],
  page: {
    number: 1,
    size: 25,
    item_from: 1,
    item_to: 1,
    total_items: null,
    total_pages: null,
    has_previous: false,
    has_next: false,
    navigable_pages: [1],
  },
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function setup(locale: 'en' | 'ko' = 'en') {
  vi.spyOn(api, 'networkCapabilities').mockResolvedValue(capabilities)
  vi.spyOn(api, 'networkResources').mockResolvedValue(page)
  return render(
    <NetworkServicesPage
      scopeKey="project-alpha:RegionOne"
      locale={locale}
      query={query}
      onQuery={vi.fn()}
      onExpired={vi.fn()}
    />,
  )
}

describe('NetworkServicesPage', () => {
  it('shows Octavia provisioning and operating status without a health tile', async () => {
    setup()

    expect(await screen.findByText('public-lb')).toBeInTheDocument()
    expect(screen.getAllByText('ACTIVE')).toHaveLength(2)
    expect(screen.getByText('ONLINE')).toBeInTheDocument()
    expect(screen.queryByText(/health semantic/i)).not.toBeInTheDocument()
  })

  it('uses Korean product strings while preserving OpenStack status values', async () => {
    setup('ko')

    expect(await screen.findByRole('heading', { name: '네트워크 서비스' })).toBeInTheDocument()
    expect(screen.getByText('운영 상태')).toBeInTheDocument()
    expect(screen.getByText('ONLINE')).toBeInTheDocument()
  })

  it('loads a project-scoped detail before opening the detail dialog', async () => {
    setup()
    const detail = vi.spyOn(api, 'networkResource').mockResolvedValue(resource)
    await screen.findByText('public-lb')
    fireEvent.click(screen.getByRole('button', { name: 'Details' }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(detail).toHaveBeenCalledWith('load_balancer', resource.id, '', '')
    expect(screen.getByText('vip_subnet_id')).toBeInTheDocument()
  })

  it('requires exact destructive confirmation before enabling Delete', async () => {
    setup()
    await screen.findByText('public-lb')
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    const dialog = screen.getByRole('dialog')
    const deleteButton = screen.getAllByRole('button', { name: 'Delete' }).at(-1)
    expect(deleteButton).toBeDisabled()
    fireEvent.change(dialog.querySelector('input')!, { target: { value: 'public-lb' } })
    await waitFor(() => expect(deleteButton).toBeEnabled())
  })
})
