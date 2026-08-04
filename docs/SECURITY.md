# Security and OpenStack API Boundaries

## Trust Boundary

```text
Browser
  -> Vantage BFF
      -> openstacksdk
          -> Keystone service catalog
              -> Nova / Neutron / Glance / Cinder
```

The browser talks only to Vantage. It never calls an OpenStack service endpoint.

## Authentication and Session

- Credentials are used only for the Keystone authentication exchange.
- Keystone tokens and the service catalog are stored in a server-side session.
- The browser receives an opaque session ID in an
  `HttpOnly; Secure; SameSite=Lax` cookie.
- State-changing requests use CSRF protection.
- Project switching creates a new project-scoped context and invalidates the
  previous project's cached data.
- Logout removes the server session and related cache entries.
- Tokens, passwords, noVNC URLs, and private keys are excluded from logs and
  telemetry.

## No Shared Administrator Proxy

Vantage does not retry a user's failed action with a shared administrator or
service account. User actions retain the user's identity, scope, and audit
trail. Administrator actions use the signed-in administrator's own scoped
token.

## Authorization

- UI visibility is a convenience, not the security boundary.
- OpenStack service policy enforcement is authoritative.
- `403 Forbidden` is normalized as permission denied without privilege retry.
- `404` and `403` are not rewritten in a way that leaks cross-project resource
  existence.
- Vantage records the upstream request ID for authorized troubleshooting.

## Endpoint Discovery and Microversions

- Endpoints are selected from the Keystone service catalog for the active
  region and configured interface.
- Service URLs, ports, and project paths are not hard-coded.
- `openstacksdk` cloud/proxy APIs select supported microversions call by call.
- The UI does not expose microversion selection.
- A microversion-only feature returns an explicit unsupported-feature error
  when the cloud cannot provide it.

Reference:
[openstacksdk microversion guidance](https://docs.openstack.org/openstacksdk/latest/user/microversions)

## Collection Contract

- Every list accepts a bounded `limit`.
- Cursor or marker pagination is used where the upstream service supports it.
- Filters are translated to upstream server-side filters where the service
  supports them. Keystone user-project selection is filtered and paginated in
  the BFF from the server-session membership snapshot; the browser never
  receives the complete membership set.
- Vantage never fetches a complete collection only to slice it in the browser.
- The browser uses a visible page number and never receives an upstream marker
  or cursor. The BFF keeps a scope- and query-bound short-lived cursor chain.
- Responses include the page size, result range, navigable page numbers,
  previous/next availability, optional reliable totals, and an upstream
  request ID when available.
- Previous/next availability is response metadata used to enable the two
  icon-only edge chevrons. It never introduces visible `Previous`, `Prev`, or
  `Next` text buttons.

## Mutation Contract

- Mutations run under the active user's current scope.
- Duplicate execution is prevented for create/delete/attach operations.
- Long-running work returns a task ID instead of holding the browser request
  open.
- Tasks retain the Vantage trace ID and OpenStack request ID.
- Edit payloads contain only fields advertised by the active resource contract;
  unsupported or hidden fields are never submitted as guessed null values.
- Delete confirmation previews bounded dependencies but does not weaken or
  replace the upstream policy/state decision.
- Force delete is a separate policy- and capability-gated command with its own
  confirmation and idempotency key.

## noVNC

- Vantage requests a remote console from Nova only after access validation.
- Console URLs and tokens have a short lifetime and are never persisted.
- Console secrets do not enter application logs, analytics, or error reports.
