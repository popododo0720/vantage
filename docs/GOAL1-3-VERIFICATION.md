# Goal 1.3 Quota Overview Verification

Baseline: OpenStack 2026.1

## Implemented

- `GET /api/v1/overview` and `GET /api/v1/quotas`
- Concurrent Nova, Neutron, and Cinder quota reads with independent 3-second
  request boundaries
- Partial results for timeout, policy denial, rate limiting, and service
  failure; upstream `401` invalidates the server session
- Negative OpenStack limits normalized as unlimited, while fields absent from
  an SDK response are omitted rather than reported as unlimited
- Instance total derived from Nova quota usage without enumerating servers
- Quota-first project overview and service-filtered quota table in English and
  Korean
- Scope-keyed background revalidation every 30 seconds and on focus, preserving
  only failed services as stale
- Route scroll reset, responsive table layout, and stable quota progress bars

## Automated Evidence

- Backend: Ruff passed, strict mypy passed, `74 passed`
- Frontend: ESLint passed, TypeScript passed, `13 passed`, production build
  passed
- Runtime and planned OpenAPI documents parsed and reference-validated
- Runtime path and method parity is included in the backend suite

## Browser Evidence

- Local fake-adapter login, project selection, overview, and service-filtered
  quota requests completed successfully
- Desktop viewport `1280 x 720`: nine quota cards, no horizontal overflow
- Mobile viewport `390 x 844`: responsive navigation and table rows, no
  horizontal overflow
- English/Korean switching preserved the selected service filter and active
  session
- Browser console contained no warning or error entries during the verified
  flow

## Not Yet Claimed

- No request has been made against the home-lab Keystone, Nova, Neutron, or
  Cinder endpoints.
- The latency SLOs still require reference-cloud cold/warm measurements and
  service fault injection.
- Multi-process durable sessions, distributed caching, TLS ingress, and
  production secret handling remain deployment work.
- Live-cloud variation in quota extensions and per-volume-type quotas remains
  part of the reference-cloud compatibility gate.
