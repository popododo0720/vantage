# Design Contract

## Product Character

Vantage should combine:

- AWS-like service and resource hierarchy
- Proxmox-like density and capacity visibility
- OpenStack's existing project and service vocabulary

It is an operational console, not a marketing dashboard.

## Information Principles

- Make the current project, domain, and region unambiguous.
- Lead with quota used/limit and pressure, not decorative resource counts.
- Keep project and administrator navigation separate.
- Prefer tables, filters, comparison, and clear operation feedback.
- Preserve context through list, detail, and mutation flows.
- Use OpenStack resource names; do not expose OVN implementation internals.
- Derive service navigation from the Keystone catalog and API capabilities.
- Keep node count, deployment topology, and backend names out of the product IA.
- Do not create default project navigation for network-backend internals.

## Project MVP Navigation

- Overview
- Instances
- Images
- Flavors
- Keypairs
- Networks
- Security groups
- Floating IPs
- Volumes
- API access
- Project settings

## Goal 1 Screen Inventory

Goal 1 is not complete with an overview alone. The following screens and
overlay states form one usable operating path:

| Surface | Entry | Result |
| --- | --- | --- |
| Login | Direct URL or expired session | Authenticate with Keystone and create a server session |
| Login error | Invalid credentials or authentication rate limit | Keep the form, clear the password, and show a non-enumerating inline error |
| Project selection | Login with multiple accessible projects | Search and select an explicit project scope |
| Project switcher | Project name in the global header | Attached popover; selecting a project clears old scope and shows a switching state |
| Project overview | Successful project entry | Quota pressure, workload summary, network summary, and partial failures |
| Quota details | `View all quotas` or `View quota details` | Compute, network, and storage quota rows with used, reserved, and limit values |
| Instance list | `Instances`, `View all`, or workload count | Server-filtered search, status filter, sort, 10/25/50/100 page sizing, numbered pagination backed by BFF cursor mapping, and row selection |
| Instance detail | Instance row or name | Right-side drawer with overview, addresses, image/flavor, volumes, and request IDs |
| Images and Key Pairs | Compute navigation or create flow | Paginated Glance inventory and project keypair inventory with one-time private-key handling |
| Create Instance | `Create instance` | Basics, Network & access, Advanced, and Review steps with quota preflight and asynchronous launch |
| Instance commands | `Edit name` or `Actions` | Name edit, state-aware lifecycle actions, resize/confirm/revert, and destructive delete confirmation |
| Instance network | Network tab in detail | NIC attachment, supported port editing, security groups, and Floating IP association |
| Volume attachment | Storage tab in detail | Attach/detach a project volume with intermediate and failed states |
| noVNC | `Console` | Short-lived remote console with reconnect, fullscreen, keyboard capture, and explicit expiry |
| Session expired | Any authenticated route | Blocking re-authentication dialog without exposing or retaining a token |

Goal 1 commands remain hidden when the matching service, extension,
microversion, policy, resource state, or server capability is unavailable. A
disabled control with no useful result is not shown.

## Goal 1 Interaction Contract

- **Project selection:** use an attached select/popover. It closes on selection,
  outside click, or `Escape`, supports keyboard navigation, and marks the active
  project. Selecting a project immediately disables repeat input, clears the
  previous project cache, and replaces project data with a switching skeleton.
  The list never fans out quota calls across every accessible project; it uses
  project metadata and locally stored last-opened time.
- **Collection pagination:** every project and admin resource list uses one
  footer pattern: a `Rows` selector with exactly 10, 25, 50, and 100 (25 by
  default), a result range such as `1-25 of 248`, and numbered controls such as
  `‹ 1 2 3 ... ›`. The active page has a distinct selected state and the edge
  chevron is disabled when no page exists in that direction. Text buttons named
  `Previous`, `Prev`, or `Next` are not permitted. Filter, sort, project, or page
  size changes return to page 1.
- **Instance inventory:** rows have a stable 48 px interaction target. Search,
  status, and sort are server-side. The BFF translates the visible page number
  to the upstream service marker/cursor and retains the token chain for the
  active query. The browser never downloads a complete collection to calculate
  page numbers. Large collections may virtualize visible rows without changing
  the API contract.
- **Collection row actions:** every resource row ends with the same icon menu.
  It contains `View details`, `Edit settings`, relationship or lifecycle
  commands, and `Delete` when the upstream API supports them. A gated command
  remains discoverable with its policy, capability, dependency, or state
  reason. Storage backends are read-only discovery data and do not receive a
  fake Delete command.
- **Resource detail:** use `Overview`, `Settings`, `Advanced`, `Access`,
  resource-specific relationships, and `Events` only where each section is
  meaningful. Create and edit reuse the same field descriptors. Mutable values
  support set/unset; immutable values remain read-only and offer clone/recreate
  when applicable.
- **Danger zone:** every deletable detail view ends with an explicit Delete
  command. Confirmation names the resource, previews known dependants and
  retention outcomes, and requires typed name/ID confirmation for high-impact
  or administrator resources. Force delete is separate and capability gated.
- **Instance detail:** open a right drawer that preserves list filters and scroll
  position. The drawer closes via its close icon, backdrop, or `Escape`; focus
  returns to the originating row. List-only controls such as `Rows 25` never
  render inside or above the drawer content.
- **Async buttons:** use `idle -> loading -> success|error` states. Loading
  disables duplicate submission while keeping the label width stable.
- **Partial failure:** keep successful widgets and rows visible. Failed widgets
  show the service name, retry-by-background status, and OpenStack request ID
  when available.
- **Session expiry:** block mutation and sensitive reads, discard project
  context, and offer a single `Sign in again` command.

Interaction mechanisms are based on beui.dev `select`, `drawer`, `table`, and
stateful `button` patterns. Spatial movement uses interruptible springs; opacity
and color use short easing. Reduced-motion mode removes translation and keeps
only immediate or short opacity changes.

## Staged Interaction Designs

Penpot includes the active Goal 1 screens plus design-ahead project and
administrator surfaces:

- **Edit instance name (Goal 1):** edit the Nova display name without implying
  that the server UUID or guest hostname changes.
- **Resize instance (Goal 1):** compare the current and requested Flavor, start
  the asynchronous Nova resize, then expose `Confirm resize` and
  `Revert resize` while the server is in `VERIFY_RESIZE`.
- **Instance network (Goal 1):** manage Nova interface attachments,
  Neutron-backed fixed IPs and security groups, and Floating IP association
  without exposing OVN implementation objects.
- **Advanced instance create (Goal 1):** keep common provisioning concise while
  exposing capability-gated boot source, metadata, tags, user data, config
  drive, server group/scheduler hints, and microversion-specific fields in a
  searchable Advanced step.
- **Network and storage areas (Goals 2-3):** keep Neutron and Cinder resources
  as separate product pages. Goal 1 exposes only the subset needed for daily VM
  connectivity and attachment.
- **Administration (Goal 4):** use a separate policy- and scope-aware workspace
  for Identity, cross-project Compute, Network RBAC, quotas, volume types,
  storage backends, and QoS specs.

The detailed pending, success, conflict, policy, and rollback behavior is in
[MVP mutation interaction specification](MVP-INTERACTIONS.md).
The per-resource list, detail, Settings, Advanced, Access, relationship, and
Delete behavior is in
[Resource screen and interaction contract](RESOURCE-INTERACTIONS.md).

## Administrator Navigation

- Token scope: System, Domain, or Project
- Domains and projects
- Users, groups, and roles
- Cross-project instances
- Hypervisors, aggregates, and Placement resource classes
- Flavors under Compute
- Images under a separate Image service section
- Neutron resources
- Volumes, volume types, and storage backends
- Catalog and API capabilities
- Default quotas
- Optional integrations

The project and administrator workspaces share design tokens and interaction
patterns, but never share an implicit scope. Service-specific navigation appears
only when the catalog and capability checks support it. Absent, unsupported,
degraded, and policy-limited states are explicit and gate affected navigation
or operations.

The administrator overview always declares SYSTEM, DOMAIN, or PROJECT scope and
can aggregate all projects. It has no global `Create project` shortcut; project,
user, group, and role changes begin in their dedicated Identity sections. It
also has no manual refresh control.

## Required States

Every primary view accounts for:

- loading
- empty
- permission denied
- partial service failure
- expired session
- stale cached data with timestamp
- asynchronous action in progress
- action failure with an OpenStack request ID
- immutable, capability-gated, policy-gated, state-gated, and
  dependency-blocked controls with a visible reason

## Visual Rules

- Dense but legible layout for repeated operations.
- Stable dimensions for tables, quota bars, status cells, and toolbars.
- Restrained OpenStack red accent with semantic blue, green, amber, and red.
- Cards only for individual summaries or repeated resources.
- No cards nested inside cards.
- No manual refresh control; show background-update state only when useful.
- Icons for familiar actions, with tooltips for unfamiliar controls.
- Row menus and detail actions use the same labels and ordering across Compute,
  Network, Storage, and Administration. Delete is never hidden in an unrelated
  settings form.
- Text and actions must fit at desktop and mobile breakpoints without overlap.
- English and Korean are the Goal 1 locales. Localized labels may wrap, but
  resource names, IDs, API statuses, and request IDs remain exact.
- Login exposes an `English / 한국어` selector. Authenticated project and
  Administration shells expose the same locale control in the global account
  area, and the selected locale persists in the server session across scopes.

## Penpot File Organization

`00 - Product & Foundations` contains the product direction, components, and
historical exploration. Production screen boards are organized as follows:

| Page | Boards |
| --- | --- |
| `01 - Auth` | 3: Login, Login Error, Project Selection |
| `02 - Dashboard` | 4: Project Overview, Project Switcher, Quota Details, Dashboard States |
| `03 - Compute` | 20: Instances, Instance Row Actions, noVNC, Create Instance steps 1-4, Images, Key Pairs, Instances Page Size, Instance Detail, Instance Delete Confirm, Resource Delete Pattern, Actions EN/KO, Resize Verify, Resize, Edit Name, Instance Network, NIC Edit |
| `04 - Network` | 14: Networks, Network Detail, Network Row Actions, Network Settings, Network Delete Confirm, Port Settings, RBAC Policies, Load Balancers, QoS Policies, Security Groups, Routers, Ports, Subnets, Floating IPs |
| `05 - Storage` | 9: Volumes, Volume Detail, Volume Row Actions, Volume Settings, Volume Delete Confirm, Volume Snapshots, Snapshot Row Actions, Volume Backups, Backup Row Actions |
| `06 - Administration` | 11: Admin Overview, QoS Specs, Storage Backends, Volume Types, Projects, Users, Groups, Role Assignments, Project Quotas, Network RBAC, All Instances |

`Dashboard` is only the Penpot page grouping. The product label and route remain
`Overview` and `/overview`. Project screens use Neutron and Cinder vocabulary;
they never expose OVN chassis/databases or a Ceph/RBD backend.

Design file:
[Vantage in Penpot](https://design.penpot.app/#/workspace?team-id=1c48efe5-2f9f-81cd-8007-beddeed3764c&file-id=8694f143-a620-8054-8008-675feb27ac54&page-id=8694f143-a620-8054-8008-675feb27ac55)

Detailed transitions and command outcomes:
[Goal 1 screen and interaction specification](GOAL1-FLOWS.md)
