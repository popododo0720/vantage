# Incremental MVP Roadmap

## Delivery Rule

Each goal produces a reference-cloud-deployable result. The team observes real
usage, records latency and failure behavior, and only then details the next
goal. Goals 1-4 are the first delivery of a comprehensive OpenStack console,
not the final product boundary.

## Goal 1: Secure Project Entry

### Slice 1.1: Session Boundary

- Keystone login
- Server-side token/session storage
- Secure session cookie
- Logout and token-expiry handling

Done when:

- The browser never receives an OpenStack token.
- Session cookies are `HttpOnly`, `Secure`, and `SameSite`.
- Logout invalidates the server session and project caches.

### Slice 1.2: Explicit Scope

- List accessible projects
- Choose active project
- Display project, domain, and region
- Rotate scoped token/session context on switch

Done when:

- Previous-project data cannot remain after a switch.
- Endpoint selection comes from the service catalog.

### Slice 1.3: Quota-First Overview

- Aggregate compute, network, and storage quota
- Show used/limit and pressure
- Isolate partial service failures
- Background revalidation

Done when:

- Useful content is visible within the Goal 1 SLO.
- A failed quota source affects only its widget.

### Slice 1.4: Instance Inventory

- Server-side filters
- Cursor/marker pagination
- List and detail
- OpenStack request ID propagation

Done when:

- The browser never downloads a complete collection to paginate locally.
- 1k and 10k synthetic-resource cases remain usable.

## Goal 2: Provision and Operate Compute

Detail after Goal 1 passes:

- Select image, flavor, network, security group, and keypair from server-side
  lists
- VM create/delete
- Power actions
- Task status and request tracing
- noVNC

## Goal 3: Manage Provisioning Resources

Detail after Goal 2 passes:

- Browse project/public images and allowed flavors
- Create and manage project networks and security groups
- Create and manage keypairs

## Goal 4: Connectivity and Storage

Detail after Goal 3 passes:

- Floating IP lifecycle
- Cinder volume attach/detach
- Backend-neutral behavior

## MVP Exit

The first project MVP exits only after Goals 1-4 pass functional, security,
performance, and failure-injection checks across supported reference clouds.

## Product Continuation

The next goals expand the same product rather than start a separate console:

### Stage 5: Administrator and Identity

- Explicit system, domain, and project token scope
- Domains, projects, users, groups, and roles
- Cross-project instances, host aggregates, and Placement resource classes
- Multi-region and large-fleet operation

### Stage 6: Image, Network, Quota, and Storage Administration

- Separate Nova flavor and Glance image navigation
- Neutron resource administration
- Cinder quota, volume type, and backend administration
- Optional audit and observability integrations

### Stage 7: Catalog Services

- Capability-gated Heat, Octavia, Swift, and other discovered services
- Explicit absent, unsupported, degraded, and policy-limited states
