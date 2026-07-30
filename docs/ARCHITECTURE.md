# Vantage Application Architecture

Status: planning contract
Baseline: OpenStack 2026.1
Implementation: not started

## Objectives

Vantage replaces Horizon for two reasons that must be solved together:

- operational information must be easier to scan and act on;
- daily routes must be materially faster and remain useful when one OpenStack
  service is slow or unavailable.

The current ML2/OVN, non-Ceph lab is the first reference cloud. Node count,
deployment tooling, Neutron backend, and Cinder backend are not product
contracts.

## Runtime Boundary

```text
Browser
  -> Vantage BFF
      -> server-side session and scoped cache
      -> operation coordinator
      -> openstacksdk service adapters
          -> Keystone service catalog
              -> Keystone / Nova / Placement / Glance / Neutron / Cinder
```

The browser never calls an OpenStack service endpoint. It receives an opaque
`HttpOnly; Secure; SameSite` session cookie and a CSRF token, not a Keystone
token. Credentials exist only for the Keystone authentication exchange.

## Logical Components

### Browser Application

- Route shell for Auth, Overview, Compute, Network, Storage, and
  Administration.
- Query state contains filters, page size, cursor, selected row, and safe
  current-scope view data.
- Mutations receive an operation ID and observe operation state rather than
  holding a browser request open.
- English and Korean are Goal 1 locales. Resource names, IDs, status values,
  and request IDs remain exact.
- No manual refresh button. Route entry, focus, project switch, mutation
  completion, and bounded background revalidation trigger reads.

### Browser-Facing BFF

- Owns `/api/v1`, request validation, CSRF, idempotency, error normalization,
  and response shaping.
- Derives user, project, region, catalog, and capability context from the
  server session.
- Translates list filters and cursors to service-supported server-side
  parameters. It never fetches a complete collection merely to paginate.
- Returns view-oriented bounded payloads while preserving OpenStack resource
  terminology and request IDs.
- Treats OpenStack policy and `403` as authoritative. It never retries with a
  shared administrator credential.

### Session and Scope Store

- Stores the Keystone token, service catalog, active scope, region,
  negotiated-capability summary, expiry, and locale server side.
- Rotates or rebuilds project-scoped context on project switch.
- Invalidates all previous-project cache keys before new-scope content becomes
  visible.
- Removes the session and related caches on logout or terminal expiry.
- Never persists passwords, generated private keys, or noVNC URLs.

### OpenStack Adapters

- Use `openstacksdk` cloud/proxy APIs for normalized resources and call-level
  microversion negotiation.
- Select endpoints from the active Keystone service catalog.
- Expose capabilities such as remote console, port editing, Neutron
  extensions, Cinder backup support, and Octavia presence without
  deployment-specific UI branches.
- Preserve upstream request IDs and normalize service-specific errors into the
  BFF problem contract.
- Keep Neutron and Cinder backend details out of browser-facing schemas.

### Operation Coordinator

- Accepts create, delete, action, resize, attach, detach, associate, and
  disassociate commands with a scope-bound idempotency key.
- Returns a stable operation ID within the mutation acknowledgement SLO.
- Tracks `accepted`, `running`, `succeeded`, `failed`, and `cancelled` states.
- Correlates the Vantage trace ID with every OpenStack request ID.
- Revalidates affected resources and cache keys after final state.
- Does not invent a completed state when an OpenStack resource remains in an
  intermediate state such as `BUILD`, `VERIFY_RESIZE`, `attaching`, or
  `detaching`.

## Read Path

1. Resolve the opaque Vantage session.
2. Validate active project, region, and route capability.
3. Build a cache key from user, project, region, service, capability behavior,
   filters, page size, and cursor.
4. Return a fresh bounded value or start a bounded upstream request.
5. For overview only, fan out Nova, Neutron, and Cinder reads behind one BFF
   deadline and return successful widgets independently.
6. Preserve `next_cursor`, `has_more`, stale timestamp, trace ID, and upstream
   request ID where applicable.

## Mutation Path

1. Validate session, CSRF token, scope, schema, capability, and idempotency key.
2. Perform safe client-side preconditions without treating them as
   authorization.
3. Submit through the signed-in user's scoped OpenStack connection.
4. Return an operation ID without waiting for the final resource state.
5. Observe final or recoverable intermediate state.
6. Invalidate only affected current-scope cache entries.
7. Surface OpenStack `403`, `404`, `409`, `429`, and `5xx` distinctly.

## Caching and Performance

- Application shell assets are independent from OpenStack response latency.
- Project overview widgets have independent deadlines and errors.
- Stale-while-revalidate is limited to safe, project-scoped read data.
- Mutation results, passwords, tokens, private keys, and noVNC URLs are never
  reusable cache values.
- Cold and warm route measurements are separated.
- The release targets and fault-injection matrix are defined in
  [Performance contract](PERFORMANCE.md).

## Project and Administrator Separation

Project routes operate only in the active project scope. Administrator routes
require an explicit SYSTEM, DOMAIN, or PROJECT scope and use the signed-in
administrator's own token. Administrator navigation and aggregate queries are
separate from project navigation and are not enabled by a client-side role
check alone.

## Rollout Boundaries

- Goal 1 implements the initial usable project MVP defined in the OpenAPI.
- Goal 2 expands full project networking.
- Goal 3 expands project storage depth.
- Goal 4 enables administrator and Identity workflows.
- Goal 5+ adds catalog-discovered services.

A Penpot board or OpenAPI path is a design and contract artifact until its
implementation, policy tests, performance tests, and reference-cloud checks
pass. No application implementation begins before this planning package is
approved.
