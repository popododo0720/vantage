# Goal 1.4 Instance Inventory Verification

Baseline: OpenStack 2026.1

## Implemented

- `GET /api/v1/instances` with project-scoped Nova filters, sorting, and page
  sizes 10, 25, 50, and 100
- `GET /api/v1/instances/{instance_id}` with nullable down-cell fields,
  addresses, attached-volume summaries, and request correlation
- Progressive numbered pagination backed by a short-lived, session- and
  query-bound Nova marker chain; upstream markers never enter browser state
- One Nova request per browser page, `limit + 1` look-ahead, and authoritative
  `servers_links rel=next` handling when Nova clamps the requested limit
- Scope switch, logout, and upstream authentication invalidation of cursor
  chains; stale or missing chains recover to page 1 without losing filters
- Bounded SDK thread capacity that remains occupied until timed-out blocking
  calls actually finish
- Responsive instance inventory and routed detail drawer in English and
  Korean, including Network and Storage tabs
- Policy-safe stale handling: `403` and `404` remove previously visible list or
  detail data rather than retaining it

## Automated Evidence

- Backend: Ruff passed, strict mypy passed, `117 passed`
- Frontend: ESLint passed, TypeScript passed, `33 passed`, production build
  passed
- Runtime and planned OpenAPI documents parsed and reference-validated
- Both instance list and detail contracts include normalized `401`, `403`,
  `404`, `409`, `429`, `503`, `504`, and `422` responses
- Synthetic inventory tests cover 1k/10k bounded access, concurrent cursor
  refresh, cursor expiry, and Nova operator `max_limit` clamping

## Runtime Evidence

- Local fake-adapter login, explicit project selection, page 1/page 2 reads,
  and instance detail completed successfully
- `limit=10` returned 10 resources per page without a total/count request
- Detail responses carried the instance status, attachments, and request
  correlation identifier

## Browser Evidence

- Desktop `1280 x 720`: six-column table and filters, 25 rows, numbered
  pagination, no horizontal overflow
- Intermediate `1200 x 800` and tablet `1024 x 768`: compact two-column rows,
  no clipped fields or horizontal overflow
- Mobile `390 x 844`: single-column rows and full-width detail drawer, no
  horizontal overflow
- Drawer contained Overview, Network, and Storage only; no list-level rows
  selector appeared inside it
- Arrow-key tab navigation moved selection and focus together; drawer open and
  close preserve the list route, scroll position, and opener focus
- Browser console contained no warnings or errors during the verified flow

## Not Yet Claimed

- No request has been made against the home-lab Keystone or Nova endpoints.
- Reference-cloud p75/p95 latency measurements and Nova fault injection remain
  required before Goal 1 exits.
- Multi-process durable sessions and cursor storage remain deployment work.
- Create, lifecycle, NIC, Floating IP, volume attachment, and noVNC operations
  continue in Goal 1.5 through Goal 1.7.
