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
- Numbered UI pagination (`‹ 1 2 3 ... ›`) backed by service cursor/marker
  pagination; text `Previous`/`Next` controls are not used
- List and detail
- OpenStack request ID propagation

Done when:

- The browser never downloads a complete collection to paginate locally.
- 1k and 10k synthetic-resource cases remain usable.

### Slice 1.5: Provisioning Inputs and Create

- Server-side image, Flavor, network, security-group, and keypair collections
- Images and keypairs inventory pages
- Four-step Create Instance flow: Basics, Network & access, Advanced, Review
- Capability-gated boot source, metadata, tags, user data, config drive, server
  group/scheduler hints, and microversion-specific fields
- Quota preflight without replacing OpenStack policy enforcement

Done when:

- A VM can be created without deployment-specific defaults.
- Public and project resources remain distinguishable.
- Private key material is shown only once when generated.

### Slice 1.6: Lifecycle and Recovery

- Edit display name
- Shared row action and detail danger-zone patterns
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
- Goal 1 resources pass the 2026.1 create/show/set/unset/action/delete parity
  ledger with no unexplained omissions.
- The MVP is used on the reference cloud for one review cycle.
- No application work for Goal 2 begins until the user confirms Goal 1.

## Goal 2: Full Project Networking

### Slice 2.1: Network Inventory

- Networks, subnets, ports, routers, and Floating IP lists and details
- Shared server-side filters and numbered pagination
- Project ownership, status, relationships, request IDs, and partial errors

Done when:

- A user can inspect the complete Neutron topology using Neutron resources
  without seeing OVN chassis or database internals.
- Every collection remains bounded at 10/25/50/100 rows.

### Slice 2.2: Core Network Lifecycle

- Network and subnet create/edit/delete
- Port create/edit/delete and attach/detach
- Router create/edit/delete, gateway, route, and interface lifecycle
- Floating IP allocate/edit/associate/disassociate/release

Done when:

- Dependency-aware deletion prevents accidental router-interface, port, and
  Floating-IP loss.
- MAC, fixed IP, allowed-address-pair, DNS, QoS, security-group, and other
  supported port options have explicit parity states.

### Slice 2.3: Security and Sharing

- Security groups and rule lifecycle
- QoS policies and advertised rule types
- Project-visible Neutron RBAC policies

Done when:

- Set/unset, rule ordering, project sharing, revision conflicts, and policy
  failures are represented without silent fallback to CLI.

### Slice 2.4: Optional Load Balancing

- Octavia-gated load balancers, listeners, pools, members, health monitors,
  and L7 policies/rules
- Intermediate provisioning and failover states

Done when:

- Octavia absence removes the service navigation without affecting Neutron.
- Present Octavia resources pass their own create/edit/action/delete ledger.

### Goal 2 Exit

- Full project Neutron coverage passes reference-cloud policy, conflict,
  performance, and parity checks.
- Goal 2 is used for one review cycle before Goal 3 starts.

## Goal 3: Project Storage Depth

### Slice 3.1: Volume Lifecycle

- Volume create from supported sources, edit, extend, retype/migrate when
  allowed, attach/detach, transfer, and delete/force-delete
- Bootable, read-only, metadata, type, AZ, and capability-gated options

### Slice 3.2: Snapshot and Backup Lifecycle

- Snapshot create/edit/delete/force-delete
- Full and incremental backup, restore, export/import record, and delete
- Separate capacity/count quota presentation

### Goal 3 Exit

- Cinder resources pass create/show/set/unset/action/delete parity.
- The same UI contract works on the initial non-Ceph backend and remains
  compatible with a later Ceph/RBD backend.
- Goal 3 is used for one review cycle before Goal 4 starts.

## Goal 4: Administrator and Identity

### Slice 4.1: Identity and Scope

- Explicit system, domain, and project token scope
- Domains, projects, users, groups, and roles
- Role assignments and project quotas

### Slice 4.2: Compute Administration

- Cross-project instances, host aggregates, and Placement resource classes
- Multi-region and large-fleet operation
- Separate Nova flavor and Glance image navigation

### Slice 4.3: Network and Storage Administration

- Neutron resource administration
- Cinder quota, volume type, backend, and QoS-spec administration

Storage backends remain read-only unless an actual deployed service API
advertises a mutation. Flavor sizing uses `Clone as new`; extra specs and
project access remain directly editable.

### Slice 4.4: Operational Integrations

- Optional audit and observability integrations

### Goal 4 Exit

- Every administrator operation uses the signed-in administrator's explicit
  scope and passes policy, large-fleet pagination, and parity checks.
- Project users cannot discover system-wide resources through navigation,
  counts, errors, or cached data.

## Goal 5+: Catalog Services

- Capability-gated Heat, Octavia, Swift, and other discovered services
- Explicit absent, unsupported, degraded, and policy-limited states
