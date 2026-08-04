# Vantage Application Architecture

Status: implemented runtime contract
Baseline: OpenStack 2026.1
Implementation: Goal 1 project foundation and Goal 2 network services

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
- Query state contains filters, page size, visible page number, selected row,
  and safe current-scope view data. Upstream cursors remain opaque BFF state.
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
  parameters. It never fetches a complete mutable service-resource collection
  merely to paginate. The Keystone user-project membership set is captured at
  authentication as bounded session authorization context because that endpoint
  has no portable cursor contract; only filtered, paginated slices reach the
  browser.
- Returns view-oriented bounded payloads while preserving OpenStack resource
  terminology and request IDs.
- Treats OpenStack policy and `403` as authoritative. It never retries with a
  shared administrator credential.

### Resource Contract Registry

- Stores one descriptor per create/edit field, relationship, action, and
  delete command.
- Each descriptor records service/API field, SDK argument, CLI equivalent,
  data type, validation, default, mutability, sensitivity, extension or
  microversion, policy/state hints, and support state.
- Produces the browser-facing resource-capability response used by forms,
  action menus, tooltips, and Korean/English labels.
- Keeps unsupported fields out of submitted payloads while preserving a
  visible reason for immutable, capability-gated, policy-gated, state-gated,
  upstream-absent, and deferred items.
- Is reconciled against the OpenStack 2026.1 command/API ledger for every
  resource before its roadmap goal exits.

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
- Run blocking SDK calls behind a configured capacity bound. Cancellation of
  the browser-facing request does not release capacity until the underlying
  SDK thread finishes, preventing stalled upstream calls from accumulating.
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
   filters, page size, and the resolved upstream cursor.
4. Return a fresh bounded value or start a bounded upstream request.
5. For overview only, fan out Nova, Neutron, and Cinder reads behind one BFF
   deadline and return successful widgets independently.
6. Return visible page number, page size, result range, navigable pages,
   optional reliable totals, stale timestamp, trace ID, and upstream request ID
   where applicable. Upstream cursors never leave the BFF.

For numbered browser pagination, the BFF keeps a short-lived cursor chain keyed
by session, scope, resource, filters, sort, and page size. It resolves visible
controls such as `‹ 1 2 3 ... ›` to upstream markers without exposing service
tokens or downloading a complete collection. Reliable totals are returned only
when the service can provide or safely cache them; otherwise the page window
contains reached and adjacent navigable pages. Any query-shape change discards
the chain and returns to page 1.

## Mutation Path

1. Validate session, CSRF token, scope, schema, capability, and idempotency key.
2. Perform safe client-side preconditions without treating them as
   authorization.
3. Submit through the signed-in user's scoped OpenStack connection.
4. Return an operation ID without waiting for the final resource state.
5. Observe final or recoverable intermediate state.
6. Invalidate only affected current-scope cache entries.
7. Surface OpenStack `403`, `404`, `409`, `429`, and `5xx` distinctly.

Delete uses the same path plus a bounded dependency preview. The preview is
informational and never substitutes for the service's final policy/state
decision. Force deletion is a distinct descriptor and idempotency scope, not a
flag silently added to an ordinary delete.

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

- Goal 1 targets the initial usable project MVP defined in the planned OpenAPI.
- Goal 1.1 implements the session and explicit-scope boundary; Goal 1.3 adds
  bounded Nova, Neutron, and Cinder quota aggregation with partial results.
- Goal 1.4 adds project-scoped Nova inventory and details. Its stable scope
  namespace survives locale-only session rotation, while project switch,
  logout, and upstream authentication failure invalidate cursor chains.
- Goal 2 expands full project networking.
- Goal 2's runtime exposes bounded, capability-driven Neutron and Octavia
  resources through `/api/v1/network`; Octavia resources disappear when the
  service is absent from the active catalog.
- Goal 3 expands project storage depth.
- Goal 4 enables administrator and Identity workflows.
- Goal 5+ adds catalog-discovered services.

A Penpot board or planned OpenAPI path remains a design artifact until its
runtime implementation, policy tests, performance tests, and reference-cloud
checks pass. The full staged package is approved; release evidence is still
required for every promoted operation.
