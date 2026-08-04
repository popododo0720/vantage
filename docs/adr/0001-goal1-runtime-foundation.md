# ADR 0001: Goal 1 runtime foundation

Status: accepted for Goal 1.1

## Context

The planning contract selects `openstacksdk` and a browser-facing BFF but does
not select an application framework. Goal 1.1 needs a small runnable vertical
slice without coupling the browser to OpenStack services or to the first home
lab deployment.

## Decision

- Use FastAPI and Pydantic for the Python BFF. This keeps the OpenAPI boundary
  explicit and places `openstacksdk` in its native Python runtime.
- Use React, TypeScript, and Vite for the browser application. The first slice
  contains only login, project selection, and the scoped shell.
- Keep authentication and project scoping behind `OpenStackAdapter`. Tests and
  local development use `FakeOpenStackAdapter`; deployments select
  `OpenStackSdkAdapter` explicitly.
- Keep sessions behind `SessionStore`. The in-memory implementation is for one
  process only and is intentionally replaceable by a shared production store.
- Deliver CSRF tokens in the `X-CSRF-Token` response header. The browser keeps
  the value in memory; it is never persisted. Project and preference changes
  rotate both the opaque session ID and CSRF token.

## Consequences

Keystone tokens, the service catalog, and scoped authorization context remain
server-side. A production deployment must provide a durable shared session
store and TLS, and must validate the SDK adapter against its service catalog,
regions, interface policy, and Keystone deployment before enabling users.
