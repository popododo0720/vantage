# MVP Planning and Design Readiness

Status: planning and Penpot design passed review. User approval was received,
and the Goal 1.1 session plus explicit-scope foundation is now implemented for
local verification. Later Goal 1 slices remain contract-only.

This checklist separates design-contract evidence from checks that can only
pass after an implementation exists. A Penpot board or OpenAPI operation is
evidence of an agreed contract, not evidence that the deployed behavior works.

## Goal 1 Contract Gate

| Capability | Planning evidence | Design evidence | Delivery status |
| --- | --- | --- | --- |
| Login, logout, session expiry | `GOAL1-FLOWS.md`, `SECURITY.md`, runtime OpenAPI | Login, Login Error, Project Selection | Implemented locally; reference-cloud validation pending |
| Project and region scope switch | `ARCHITECTURE.md`, `GOAL1-FLOWS.md`, runtime OpenAPI | Project Selection, Project Switcher | Implemented locally; reference-cloud validation pending |
| Quota-first overview | `PRD.md`, `GOAL1-FLOWS.md`, planned Goal 1 OpenAPI | Project Overview, Quota Details, Dashboard States | Contracted |
| Instance list and detail | `MVP-INTERACTIONS.md`, planned Goal 1 OpenAPI | Instances, page-size state, detail drawer | Contracted |
| Four-step instance create | `GOAL1-FLOWS.md`, planned Goal 1 OpenAPI | Create Instance steps 1-4 | Contracted |
| Instance edit, delete, lifecycle | `RESOURCE-INTERACTIONS.md`, planned Goal 1 OpenAPI | Edit Name, Row Actions, Delete Confirm, Actions EN/KO | Contracted |
| Resize confirm or revert | `MVP-INTERACTIONS.md`, planned Goal 1 OpenAPI | Resize, Resize Verify | Contracted |
| NIC and allowed port edits | `RESOURCE-INTERACTIONS.md`, planned Goal 1 OpenAPI | Instance Network, NIC Edit, NIC Attach, NIC Detach Confirm | Contracted |
| Floating IP lifecycle | `RESOURCE-INTERACTIONS.md`, planned Goal 1 OpenAPI | Instance Floating IP, Disassociate Confirm, Release Confirm | Contracted |
| Volume attach or detach | `RESOURCE-INTERACTIONS.md`, planned Goal 1 OpenAPI | Volume Attach, Detach Confirm, Attachment Conflict | Contracted |
| Key-pair lifecycle | `RESOURCE-INTERACTIONS.md`, planned Goal 1 OpenAPI | Key Pairs, Create, Private Key, Delete Confirm | Contracted |
| noVNC session | `SECURITY.md`, planned Goal 1 OpenAPI | noVNC | Contracted |
| English and Korean | `GOAL1-FLOWS.md`, `DESIGN.md` | locale controls and Actions EN/KO | Contracted |

`Implemented locally` means the fake-adapter vertical slice and automated local
checks pass. It does not claim TLS ingress, shared sessions, or a real Keystone
deployment. `Contracted` means the expected behavior is specified but the slice
has not been implemented.

## Shared Interaction Gate

- Lists use server-side filtering, sorting, and pagination.
- Visible page sizes are exactly `10`, `25`, `50`, and `100`; default is `25`.
- Visible pagination uses a range plus `< 1 2 3 ... >`; it never shows text
  `Previous`, `Prev`, or `Next` buttons.
- Opening a row preserves list filters, page, page size, and scroll position.
- Detail surfaces never contain a list-level page-size selector.
- Applicable resources expose View, Settings, Advanced, Access or relationship
  actions, lifecycle actions, and Delete in a consistent order.
- Delete remains in both the row menu and the detail danger zone.
- Destructive actions identify the resource and project, show dependencies and
  retain/detach/release consequences, and preserve context on failure.
- Unsupported actions remain visible with an exact immutable, capability,
  policy, state, upstream, or deferred reason.

## Administrator Quota and Project Gate

Project Quotas are not read-only:

1. `Project Quotas -> Edit quotas`
2. `Project Quota Settings -> Review changes`
3. `Quota Review Changes -> Apply changes`
4. `Project Quota Settings -> Delete overrides -> Delete Quota Overrides Confirm`
5. `Quota row menu -> View quota usage`, `Edit quotas`, or `Delete overrides`

Nova, Neutron, and Cinder changes are submitted independently. Successful
service updates remain applied when another service fails, and the failed
service keeps its proposed values and request ID for recovery.

The settings surface is schema-driven rather than limited to the fields shown in
one static mockup. It includes current Nova limits such as instances, cores,
RAM, server groups and members, key pairs, and metadata items; Neutron limits
such as networks, subnets, subnet pools, ports, routers, Floating IPs, security
groups/rules, and RBAC policies; and Cinder base plus advertised per-volume-type
limits. Capability-discovered service quota groups, including Octavia when
available, appear as separate service sections.

A quota is not an independently deletable resource. Where an upstream service
uses `DELETE`, Vantage labels the operation `Delete overrides`: it deletes or
unsets only the explicit service override and restores the current service
default. It never deletes the project or any project resource.

The dedicated Projects section exposes Create project. Existing projects expose
View details, Edit project, Manage members, Edit quotas, Enable or Disable, and
Delete project. Create validates domain and hierarchy capabilities and keeps a
409 conflict or upstream 403 actionable with the OpenStack request ID. Project
delete uses a dependency preflight and typed confirmation; Vantage never
pretends to cascade-delete OpenStack service resources.

## Administrator Resource Design Gate

These are design and behavior contracts for the policy-gated Administration
workspace. They do not imply that Goal 4 BFF routes are implemented.

| Resource | Inspectable Penpot states | Mutation boundary |
| --- | --- | --- |
| Projects | list, dedicated create, settings, review changes, membership/roles, row actions, delete confirm | domain/hierarchy capability checks, property and lifecycle edit, quota and membership relationships, dependency-preflight delete |
| Users | list, create, settings, row actions, delete confirm | identity edit, credential reset, group/role access, disable, delete |
| Groups | list, create, settings, row actions, remove-members confirm, delete confirm | property edit, member add/remove, role grant/revoke, delete |
| Roles | list, create, settings, row actions, delete confirm | role edit, implied-role relationships, assignment inspection, protected delete |
| Role assignments | list, grant/replace editor, row actions, revoke confirm | no in-place assignment object update; replace is revoke plus grant |
| Flavors | list, create/clone, settings, row actions, delete confirm | capacity is create-only; extra specs and private project access remain editable |
| Cross-project instances | list, operations, row actions, force-delete confirm | state- and policy-gated power, migrate, evacuate, rescue, rebuild, force delete |
| Network RBAC | list, create/replacement, settings, row actions, delete confirm | target/action edit where supported; owner/object identity remains immutable |
| Volume Types | list, create, settings, row actions, delete confirm | visibility, access, extra specs, encryption, QoS association, default/in-use preflight |
| QoS Specs | list, create, settings, row actions, force-delete confirm | key set/unset, type association, normal delete versus force delete |
| Storage backends | list, row actions, service operations | no backend CRUD; inspect pools/capabilities and gate enable/disable, freeze/thaw, failover |
| Project membership | list, relationship editor, row actions, revoke confirm | removing membership or revoking a role never deletes an identity resource |

Every administrator mutation preserves the active scope, filters, page, and
unsaved values when the upstream service rejects the operation. A `403`, `404`,
`409`, timeout, partial failure, or unsupported capability remains visible with
the service name and OpenStack request ID. The resource-specific review and
recovery contract is:

| Resource | Review or confirmation | Required gate and recovery |
| --- | --- | --- |
| Projects | review property/lifecycle diff; dependency preview and typed delete | domain/hierarchy capability, duplicate conflict, policy denial, and service-resource dependency block |
| Project quotas | per-service Nova/Neutron/Cinder diff; explicit `Delete overrides` confirmation | validate against current usage; preserve successful service updates and retry only failed service groups |
| Users | separate credential action; disable and delete confirmation with memberships/assignments | duplicate identity, protected/default-project dependency, policy denial, and stale membership conflict |
| Groups | member-removal review and group delete dependency preview | assignment/membership conflict, protected group, policy denial, and concurrent membership change |
| Roles | edit/implied-role review and protected delete confirmation | assigned or implied-role dependency, immutable/protected role, policy denial |
| Role assignments | grant summary; revoke confirmation, typed for high-impact system/domain scope | duplicate/missing assignment conflict, inherited-assignment capability, and policy denial |
| Flavors | create/clone review; delete impact confirmation | immutable capacity fields require clone; extra-spec/access conflict, in-use visibility, and policy denial remain explicit |
| Cross-project instances | lifecycle review; typed force-delete confirmation | state conflict, locked/server-task conflict, policy denial, asynchronous operation polling and recoverable failure |
| Network RBAC | create or replacement review; delete confirmation | immutable owner/object identity, duplicate target/action conflict, extension capability, and policy denial |
| Volume Types | settings diff; in-use/default delete confirmation | project-access, encryption/QoS association, default/in-use dependency, backend capability, and policy denial |
| QoS Specs | key/type-association diff; separate normal and force-delete confirmation | associated-type dependency, unsupported consumer/key, concurrent update, and policy denial |
| Storage backends | service-operation review; failover/freeze confirmation when advertised | no synthetic backend CRUD; exact capability/state conflict, policy denial, asynchronous result and request ID |
| Project membership | grant/replace summary and revoke confirmation | identity remains intact; duplicate/missing assignment, inherited-role capability, and policy denial |

Administration collection routes and schemas remain a Goal 4 API-contract task.
Before implementation, each row above must gain explicit server-side filters,
page metadata, mutation schemas, and documented `403`/`404`/`409` outcomes in
a Goal 4 OpenAPI contract. Neither the runtime nor planned Goal 1 contract
claims these administrator routes.

## Penpot Inventory

The current production-target Penpot planning inventory contains 193 unique
screen states:

| Page | Boards |
| --- | ---: |
| Auth | 3 |
| Dashboard | 4 |
| Compute | 31 |
| Network | 66 |
| Storage | 25 |
| Administration | 64 |

For faster review, the larger domains are mirrored as lightweight preview
boards:

| Domain | Review pages | Canonical editable page |
| --- | --- | --- |
| Compute | `03A` (12), `03B` (9), `03C` (10) | `03X - Compute Prototype` (31) |
| Network | `04A` (13), `04B` (15), `04C` (22), `04D` (16) | `04X - Network Prototype` (66) |
| Storage | `05A` (9), `05B` (16) | `05X - Storage Prototype` (25) |
| Administration | `06A` (13), `06B` (11), `06C` (13), `06D` (9), `06E` (13), `06F` (5) | `06X - Administration Prototype` (64) |

The review pages are not counted again. Editable layers and all prototype
transitions remain in the canonical `X` pages.

The Administration page contains the Project and quota workflows plus explicit
create, edit, relationship, lifecycle, row-action, and destructive-confirmation
states for Identity, cross-project Compute, Network RBAC, Volume Types, QoS
Specs, and storage backend operations. The primary commands and row actions are
connected as prototype transitions rather than existing only as static labels.
Project creation is represented by a dedicated board reachable only from the
Projects list.
Its current automated audit covers 64 boards and 1,222 click transitions, with
zero boards lacking an interaction, zero unresolved same-file destinations,
zero severe text-overflow findings, and zero shapes outside their owning board.
Every administrator list opens the common server-side pagination state with
`10`, `25`, `50`, and `100` rows and numbered navigation.
The six Administration review pages contain no missing, duplicate, unexpected,
mis-sized, or incorrectly nested boards.

The canonical Network audit covers 66 boards, 12,839 shapes, and 1,888 click
transitions, with zero boards lacking an interaction and zero unresolved
same-page destinations. The split preview pages contain no missing, duplicate,
unexpected, or mis-sized boards, and the Penpot file validator reports zero
errors.

The Compute page includes dedicated create, edit, destructive-confirmation, and
conflict states for key pairs, NICs, Floating IPs, and volume attachments. Its
current automated audit covers 31 production boards, 6,761 shapes, and 429
click transitions, with zero unresolved same-file destinations, zero invisible
text layers, and zero shapes outside their owning board. Its three review pages
contain exactly 12, 9, and 10 boards.

The canonical Storage audit covers 25 boards, 4,744 shapes, and 307 click
transitions, with zero boards lacking an interaction, zero unresolved same-file
destinations, zero invisible text layers, and zero shapes outside their owning
board. Its two review pages contain exactly 9 and 16 boards.

Across all split domains, page order, board counts, board dimensions, preview
structure, duplicate names, and canonical-source isolation pass. The Penpot
file validator reports zero errors.

## Security and Performance Gate

- The browser never calls Nova, Neutron, Glance, or Cinder directly.
- Keystone tokens remain in the Vantage server session.
- The browser receives only an opaque `HttpOnly + Secure + SameSite` cookie.
- User operations are never retried with a shared administrator credential.
- OpenStack policy and the upstream `403` response are authoritative.
- openstacksdk performs supported microversion negotiation and normalization.
- CSRF protection applies to mutations; idempotency and operation IDs protect
  creates and destructive retries.
- Dashboard service requests fan out independently and preserve successful
  widgets during partial failure.
- Performance must be measured against the workload matrix in
  `PERFORMANCE.md`, not against an empty demonstration project.

## Current OpenAPI Checks

The implemented runtime contract reports:

- 6 operations with exact path and method parity against the FastAPI runtime;
- only the session, login, project-list, and explicit-scope routes delivered by
  Goal 1.1.

The separate planned Goal 1 contract reports:

- 40 operations and 40 unique operation IDs;
- no missing internal component references;
- no authenticated operation missing the documented `401` response, with
  idempotent logout handled as the explicit exception;
- no authenticated mutation missing the CSRF parameter;
- page sizes exactly `10`, `25`, `50`, and `100`, default `25`;
- idempotency keys on resource creates and destructive or retry-sensitive
  mutations. Session preference, logout, scope selection, and short-lived
  console URL issuance are the documented non-resource exceptions.

Goal 1.1 adds `openapi-spec-validator` to the development dependencies. Both
`api/openapi.yaml` and `api/openapi.goal1-mvp.yaml` are parsed and
reference-validated locally. The test suite additionally compares every
published runtime path and method with FastAPI, and CI repeats both checks.

## Incremental Development Gate

User approval started incremental Goal 1 development. Goal 1.1 and the explicit
scope foundation are the only implemented runtime boundary in this branch.
Each later slice must still pass:

- current OpenAPI parser and reference validation;
- authentication and cross-project isolation tests;
- page-size, numbered pagination, and large-list tests;
- lifecycle, resize, NIC, Floating IP, volume, and noVNC scenarios;
- partial failure, stale data, 401, 403, 404, and 409 recovery;
- English and Korean accessibility and overflow checks;
- the performance workload matrix and release SLOs.
