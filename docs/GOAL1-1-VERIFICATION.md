# Goal 1.1 Foundation Verification

Date: 2026-08-02
Baseline: `codex/vantage-mvp-planning` at
`9b682d49d79eb44ec5de39cc62057281bf2cad3a`

## Implemented Boundary

- React/TypeScript routes for login, project search and selection, region
  selection, locale, scoped overview shell, project switching, session expiry,
  browser history, and logout.
- FastAPI `/api/v1/session`, `/api/v1/session/login`, `/api/v1/projects`, and
  `/api/v1/scope` runtime matching `api/openapi.yaml`.
- The published runtime contract contains only implemented routes. The later
  Goal 1 design contract remains in `api/openapi.goal1-mvp.yaml`.
- Exact project-list page sizes `10`, `25`, `50`, and `100`, bounded navigable
  page numbers, debounced and cancellable server requests, and no complete
  project-membership array in the browser session response.
- Opaque secure cookie, memory-only CSRF value, atomic session rotation,
  upstream-token-bounded expiry, atomic failed-login reservations, no-store and
  browser security headers, a 15-second SDK request boundary, and normalized
  upstream request IDs.
- `OpenStackAdapter` boundary with deterministic fake and optional
  `openstacksdk` adapters. Keystone tokens and scoped service catalogs remain in
  server session records.

## Local Verification

The Python environment and npm dependency/cache directories were placed on
`D:`. Checks were run sequentially to avoid sustained local disk load.

```text
ruff check backend
All checks passed

mypy backend/vantage_bff
Success: no issues found in 9 source files

pytest -q, after the production frontend build
53 passed

frontend npm run lint
passed

frontend npm run typecheck
passed

frontend npm test
1 file passed, 10 tests passed

frontend npm run build
passed; 205.71 kB JavaScript and 4.69 kB CSS before gzip

frontend npm audit --omit=dev
0 vulnerabilities

openapi-spec-validator api/openapi.yaml
OK; 6 implemented operations and exact FastAPI route parity

openapi-spec-validator api/openapi.goal1-mvp.yaml
OK; 40 planned operations and 40 unique operation IDs
```

The test suite covers cookie hardening, credential and token non-disclosure,
CSRF on every implemented mutation, logout failure and expiry re-authentication,
safe-route restoration, user/project isolation, scope and locale rotation,
project loading versus empty states, numbered server pagination, page-size
reset, bounded page navigation, rate-limiting concurrency, atomic session
rotation, distinct upstream `401/403/404/409/429/5xx` handling, OpenStack
request IDs, SDK timeout/interface/region/scope arguments, OpenAPI parsing and
runtime route parity, and same-origin production frontend serving.

The fake-adapter UI was exercised at `1280x720` and `390x844`: login, project
selection, numbered pagination controls, region scope, Korean locale, project
switch, browser back, session route changes, and logout all completed. The
mobile checks found no horizontal document or element overflow.

`.github/workflows/goal1-foundation.yml` repeats frontend build and checks before
the backend suite so the same-origin static test cannot be skipped in CI.

## Not Yet Claimed

- No request has been made against the home-lab Keystone or another real
  OpenStack 2026.1 cloud.
- TLS ingress, a durable shared multi-process session store and rate limiter,
  service-catalog and multi-region variations, Keystone user-project membership
  scale, and production secret handling still require deployment validation.
- The `openstacksdk` adapter's exception translation has pure tests, but its live
  authentication, project membership, and scoped catalog behavior remain
  unverified.
- Goal 1.3 quota aggregation and every resource operation from Goal 1.4 onward
  remain later slices; the current overview is only a scoped runtime shell.
- The Starlette test client emits upstream cookie and httpx deprecation
  warnings. They do not change current results but should be removed during the
  dependency-maintenance slice.
