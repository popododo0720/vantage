# Resource Screen and Interaction Contract

Status: design-ahead contract; implementation follows the roadmap goals
Baseline: OpenStack 2026.1

This document defines what happens after a user selects a resource, opens an
action menu, edits settings, changes relationships, or deletes it. It prevents
the product from stopping at overview and list mockups.

## Shared Page Pattern

Every project and administrator collection uses the same structure:

1. Route header with exact scope, region, service, and primary create command.
2. Server-side search, supported filters/sort, and `Rows 10/25/50/100`.
3. Stable table rows and `range + ‹ 1 2 3 … ›` pagination.
4. Row selection opens a detail drawer while preserving list state.
5. The final row cell is an icon action menu:
   `View details`, `Edit settings`, relationships/lifecycle, `Delete`.
6. Detail sections appear only when meaningful:
   `Overview`, `Settings`, `Advanced`, `Access`, relationships, `Events`.
7. The detail danger zone contains Delete when the upstream API supports it.

Text `Previous`, `Prev`, and `Next` controls are prohibited. A detail drawer
never repeats the list's `Rows`, range, or page controls.

## Shared Editor Pattern

- `Settings` contains common mutable values and uses translated labels.
- `Advanced` is searchable and preserves exact API, metadata, tag, property,
  extra-spec, and scheduler-hint keys.
- `Access` owns visibility, project sharing, RBAC, membership, and role
  assignment.
- Set and unset are both explicit. Clearing a value never submits a guessed
  null when the service expects an unset operation.
- Immutable values remain visible and explain the required clone/recreate
  operation.
- Capability-, microversion-, policy-, and state-gated controls remain
  discoverable with the blocking reason.
- Save shows a field-level diff and submits one idempotent mutation.
- A `403`, `409`, partial failure, or request timeout preserves the user's
  values and displays the OpenStack request ID.

## Shared Delete Pattern

The row menu and danger zone open the same dependency-aware confirmation:

1. Show type, name, ID, project, current state, and owning service.
2. Preview bounded known dependencies and default outcomes.
3. Separate retain, detach, disassociate, release, delete, and force-delete
   choices.
4. Require typed name or ID for resources with dependencies and for
   administrator-scoped deletes.
5. Keep the row until the service accepts the operation.
6. Preserve the row and current filters on failure.

Storage backends and pools are discovery data and have no fake Delete action.

## Compute

### Instances - Goal 1

List row menu:

- View details
- Edit settings
- Console
- Start or Stop
- Soft reboot or Hard reboot
- Pause/Unpause, Suspend/Resume, Shelve/Unshelve
- Resize
- Delete

Detail:

- `Overview`: UUID, project, status/task state, image/source, Flavor, AZ,
  timestamps, request IDs
- `Settings`: display name and supported description/hostname
- `Advanced`: metadata set/unset and tags
- `Network`: ports/NICs, MAC/fixed IP, security groups, Floating IP
- `Storage`: boot and attached volumes, device, delete-on-termination
- `Events`: Vantage operation and OpenStack request history

Create uses `Basics`, `Network & access`, `Advanced`, and `Review`. Resize must
reach `VERIFY_RESIZE` before Confirm/Revert unless the cloud auto-confirms.
Delete previews ports, Floating IP allocation/association, boot-volume
behavior, and other attached volumes.

### Images - Goal 1 Inventory, Extended Lifecycle by Capability

- Create/upload/import and project-owned image delete appear only when the
  active Glance API and policy allow them.
- Settings: name, visibility, protected state, minimum disk/RAM.
- Advanced: properties, tags, import method, activate/deactivate.
- Access: image members and accept/reject status.
- Delete is unavailable for non-owned or protected images with an exact reason.

### Key Pairs - Goal 1

- Create offers Generate or Import public key.
- Generated private key is displayed/downloaded once and never persisted.
- Detail is read-only because upstream rename/edit is absent.
- Delete appears in the row menu and detail danger zone.

### Flavors - Goal 4 Administration

- Create: ID/name, vCPU, RAM, root/ephemeral disk, swap, RX/TX factor,
  visibility, description, extra specs, and project access.
- `Settings`: name/ID and sizing are shown, but base sizing is immutable.
- `Extra specs`: arbitrary namespaced key/value set and unset.
- `Access`: add/remove project access for private Flavors.
- `Clone as new`: prefill the Flavor, allow new sizing, and create a distinct
  Flavor. It never silently deletes the old Flavor.
- Delete is separate, typed, and previews project access and known instance
  usage.

## Network - Goal 2

### Networks

- Create/Edit: name, description, admin state, shared/external/default flags,
  MTU, port security, DNS domain, QoS, provider values, tags/properties.
- Detail: subnets, ports, routers, RBAC, utilization when available.
- Delete previews subnets, ports, router interfaces, and Floating IP impact.

### Subnets

- Create/Edit: CIDR/IP version, gateway, DHCP, allocation pools, DNS, host
  routes, IPv6 modes, subnet pool/prefix, segment, service types, tags.
- Allocation pools, DNS servers, and host routes have add/remove row controls.
- Delete previews ports and router interfaces.

### Ports and Instance NICs

- Create/Edit: name/description, admin state, MAC, fixed IPs, device owner/ID,
  vNIC type, binding host/profile, NUMA policy, hints/trusted mode, DNS, QoS,
  security groups, port security, allowed address pairs, DHCP options, tags.
- Fixed IP, security-group, and allowed-address-pair rows support add/remove.
- Attach/detach is explicit; delete is separate from detach.
- Binding/admin fields are policy/capability gated rather than hidden.

### Routers

- Create/Edit: name/description/admin state, distributed/centralized, HA,
  routes, external gateway/fixed IPs, SNAT, NDP proxy, QoS, BFD, ECMP, tags.
- Interfaces support Add subnet/port and Remove interface.
- Clear gateway is distinct from Delete router.
- Delete previews interfaces, routes, and gateway dependencies.

### Floating IPs

- Allocate, associate, change association, disassociate, and release are
  distinct commands.
- Association requires port and fixed IP when ambiguous.
- Settings expose description, tags, and QoS where supported.
- Delete means release allocation and requires confirmation.

### Security Groups and Rules

- Group Settings: name, description, stateful/stateless, tags/properties.
- Rules have create/edit/delete with direction, EtherType, protocol, ports,
  remote CIDR/group/address group, description, and capability-gated fields.
- Delete group previews attached ports and instances.

### QoS Policies

- Settings: name, description, shared/default, ownership, tags.
- Rules are nested editable rows for every rule type advertised by Neutron.
- Delete previews attached networks, ports, Floating IPs, and gateways.

### Network RBAC

- Create, inspect, set supported target/action values, and delete.
- Project/domain target scope is explicit.
- Policy denial never leaks a cross-project target.

### Load Balancing

When Octavia is present, separate tabs cover load balancers, listeners, pools,
members, health monitors, and L7 policies/rules. Every child supports its own
create/edit/delete contract and asynchronous provisioning state. Octavia
absence removes only this navigation group.

## Storage - Goal 3

### Volumes

- Create from blank, image, snapshot, volume, or backup.
- Settings: name, description, metadata, bootable/read-only flags.
- Advanced: type, AZ, scheduler hints, extend, retype/migrate, transfer.
- Relationships: attach/detach, snapshot, backup.
- Delete/force-delete previews attachments, snapshots, backups, transfers, and
  current state. Detach never implies Delete.

### Volume Snapshots

- Create, edit name/description/metadata, unset metadata, and delete.
- Admin state and force-delete are separately policy gated.
- Delete previews dependent volumes.

### Volume Backups

- Create full/incremental or from snapshot.
- Settings: name, description, container, AZ, properties.
- Actions: restore, export/import record, reset state where policy permits.
- Delete and force-delete are separate.

### Volume Types - Goal 4 Administration

- Settings: name, description, public/private visibility.
- Extra specs: set/unset arbitrary driver keys.
- Access: add/remove project access.
- Encryption: provider, cipher, key size, control location.
- Capability flags include multiattach, cacheable, replicated, and AZ behavior.
- Delete previews volumes using the type.

### QoS Specs - Goal 4 Administration

- Create/Edit consumer and key/value specs.
- Associate/disassociate Volume Types.
- Set/unset, delete, and force-delete are distinct.

### Storage Backends - Goal 4 Administration

- Read-only capacity, state, capabilities, pools, host/cluster, and driver data.
- No create/edit/delete unless a deployed service API explicitly advertises
  one. The UI remains backend-neutral and does not assume Ceph.

## Identity and Administration - Goal 4

### Projects

- Create and Edit live in the dedicated Projects section, never on the admin
  overview.
- Settings: name, description, enabled state, domain-compatible fields,
  tags/properties.
- Tabs: members/role assignments, quotas, and discovered resources.
- Delete uses a typed impact preview across Identity and service resources.

### Users

- Settings: name, email/description, enabled state, default project and
  domain-compatible values.
- Access: group membership, role assignments, application credentials where
  policy allows.
- Password reset/change is a dedicated sensitive flow.
- Delete previews memberships, assignments, and owned credentials.

### Groups and Roles

- Groups support create/edit, add/remove users, assignment inspection, delete.
- Roles support create/edit where upstream allows it, implied-role inspection,
  assignment inspection, and delete.
- Membership and assignment removal are not represented as resource deletion.

### Role Assignments

- Grant/Revoke supports user or group principals and system, domain, project,
  or advertised target scope.
- Inherited assignment is capability gated.
- List filters and pagination are server side; revoke uses typed review for
  high-impact system/domain scope.

### Project Quotas

- Show used, reserved, effective/default, and limit separately.
- Edit/reset Nova, Neutron, Cinder, and discovered service quotas independently.
- Unlimited values use the exact service representation and are never guessed.

### Cross-Project Compute and Infrastructure

- All Instances adds project/owner context and policy-gated actions.
- Hypervisors, aggregates, Placement inventories, resource classes, and traits
  use dedicated admin routes.
- Large-fleet lists use the same numbered UI pagination without downloading
  complete collections.

## Localization and Authorization

- Goal 1 labels support English and Korean.
- OpenStack names, IDs, status values, metadata/property/extra-spec keys, and
  request IDs remain exact.
- Navigation and control state may guide the user, but the active OpenStack
  service policy and `403` are the final authorization decision.
- Administrator routes require explicit SYSTEM, DOMAIN, or PROJECT scope and
  the signed-in administrator's own token.

## Design and Release Gate

For every resource introduced by a goal:

1. Penpot contains list, detail, edit/advanced/access, action, delete, and
   required error/intermediate states.
2. The OpenAPI exposes only the routes implemented by that goal.
3. The parity ledger records every 2026.1 create/show/set/unset/action/delete
   option.
4. Missing options have an explicit immutable, gated, upstream-absent, or
   deferred state.
5. Project and administrator policy tests pass before the goal exits.
