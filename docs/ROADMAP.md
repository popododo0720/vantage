# Incremental MVP Roadmap

## Delivery Rule

Each goal produces a reference-cloud-deployable result. The team observes real
usage, records latency and failure behavior, and only then implements the next
goal. Goal 1 is the initial usable MVP. Goals 2-4 expand the same console from
real use rather than hiding a large launch behind the word MVP.

## Goal 1: Initial Usable Project MVP

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
- Page sizes 10, 25, 50, and 100 with default 25
- Cursor/marker pagination
- List and detail
- OpenStack request ID propagation

Done when:

- The browser never downloads a complete collection to paginate locally.
- 1k and 10k synthetic-resource cases remain usable.

### Slice 1.5: Provisioning Inputs and Create

- Server-side image, Flavor, network, security-group, and keypair collections
- Images and keypairs inventory pages
- Three-step Create Instance flow
- Quota preflight without replacing OpenStack policy enforcement

Done when:

- A VM can be created without deployment-specific defaults.
- Public and project resources remain distinguishable.
- Private key material is shown only once when generated.

### Slice 1.6: Lifecycle and Recovery

- Edit display name
- Delete confirmation with explicit volume and Floating-IP outcomes
- Power, reboot, pause, suspend, resume, shelve, and unshelve actions
- Resize, `VERIFY_RESIZE`, confirm, and revert
- Operation tracking and request IDs

Done when:

- Duplicate destructive operations are idempotently rejected.
- Available actions follow capability, policy, and current server state.

### Slice 1.7: Connectivity, Storage, and Console

- Attach/detach supported NICs
- Edit supported Neutron port properties
- Allocate/associate/disassociate Floating IPs
- Attach/detach Cinder volumes
- Short-lived noVNC console

Done when:

- Multi-interface Floating IP targeting is explicit.
- The BFF remains Neutron/Cinder backend neutral.
- Console URLs and tokens never enter logs or persistent storage.

### Goal 1 Exit

- Functional, security, performance, and failure-injection checks pass.
- The MVP is used on the reference cloud for one review cycle.
- No application work for Goal 2 begins until the user confirms Goal 1.

## Goal 2: Full Project Networking

Detail after Goal 1 passes:

- Networks, subnets, ports, routers, Floating IPs
- Security groups and rules
- QoS and RBAC policies
- Capability-gated Octavia load balancers

## Goal 3: Project Storage Depth

Detail after Goal 2 passes:

- Volumes, snapshots, and backups
- Full attachment lifecycle
- Backend-neutral storage behavior

## Goal 4: Administrator and Identity

Detail after Goal 3 passes:

- Explicit system, domain, and project token scope
- Domains, projects, users, groups, and roles
- Role assignments and project quotas
- Cross-project instances, host aggregates, and Placement resource classes
- Multi-region and large-fleet operation
- Separate Nova flavor and Glance image navigation
- Neutron resource administration
- Cinder quota, volume type, backend, and QoS-spec administration
- Optional audit and observability integrations

## Goal 5+: Catalog Services

- Capability-gated Heat, Octavia, Swift, and other discovered services
- Explicit absent, unsupported, degraded, and policy-limited states
