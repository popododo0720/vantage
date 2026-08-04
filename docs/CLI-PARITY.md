# CLI and API Parity Contract

Baseline: OpenStack 2026.1 service APIs, `openstacksdk`, and
`python-openstackclient`.

Roadmap ownership:

| Goal | Resources reconciled before exit |
|---|---|
| Goal 1 | Instance, image inventory/allowed operations, Flavor inventory, key pair, Goal 1 port/Floating IP/volume relationships |
| Goal 2 | Network, subnet, port, router, Floating IP, security group/rule, QoS, Neutron RBAC, capability-gated Octavia |
| Goal 3 | Volume, snapshot, backup, and project-visible volume type behavior |
| Goal 4 | Identity, cross-project Compute, Flavor/image administration, quotas, Network administration, volume type/backend/QoS administration |

## Product Rule

Vantage is not a read-only dashboard or a reduced Horizon skin. If an operation
is supported by the deployed OpenStack API and the current policy allows it,
the web console must expose it. A CLI-supported option may be omitted only when
this ledger records an explicit reason.

Every resource surface follows the same contract:

1. List and server-side search/filter/sort.
2. Numbered UI pagination (`Rows 10/25/50/100`, range, `‹ 1 2 3 ... ›`)
   translated by the BFF to service cursor/marker pagination.
3. Detail view with exact IDs, request IDs, properties, and relationships.
4. Create, Edit settings, Set/Unset properties, Delete, and resource actions
   when the upstream API supports them.
5. `Basic` and `Advanced` editor sections. Advanced options are searchable and
   preserve exact OpenStack names where translation would be ambiguous.
6. English and Korean labels without translating resource names, IDs, status
   values, metadata keys, or extra-spec keys.

Options missing without a ledger reason are product defects.

## Support States

| State | UI behavior |
|---|---|
| Available | Enabled control with validation and API-derived defaults |
| Immutable | Read-only value plus `Clone as new` or recreate guidance |
| Capability-gated | Disabled with the missing service, extension, driver feature, or microversion |
| Policy-gated | Disabled with a permission explanation; the OpenStack API/403 remains authoritative |
| State-gated | Disabled with the blocking resource state or dependency |
| Upstream absent | No fake editor; show that the OpenStack API has no mutation |
| Deferred | Visible in the parity ledger with a target goal and tracked issue |

The UI must not infer authorization from role names. It can use capabilities to
avoid impossible requests, but the service policy result is final.

## Common Editor

- `Overview`: identity, status, ownership, project, timestamps, relationships.
- `Settings`: common mutable fields.
- `Advanced`: metadata/properties, tags, scheduler or provider options,
  microversion-gated fields, and service-specific flags.
- `Access`: visibility, sharing, RBAC, project access, or role assignments.
- `Actions`: lifecycle and one-shot commands.
- `Danger zone`: dependency-aware Delete when the API supports deletion.

Each field descriptor records its service, API field, SDK argument, CLI
equivalent, mutability, required extension/microversion, policy hint, default,
validation, and support state. Create and edit forms are generated from the
same descriptors so an option cannot silently exist in only one workflow.

## Delete Contract

- Every deletable resource has `Delete` in its row action menu and an explicit
  Delete command in the detail danger zone.
- A disabled Delete remains discoverable and states the blocking policy,
  resource state, or dependency.
- Confirmation identifies the exact resource and previews known dependencies:
  attached volumes, ports, Floating IPs, snapshots, router interfaces, project
  assignments, and delete-on-termination behavior as applicable.
- High-impact and admin deletes require typed confirmation by name or ID.
- Force delete is a separate capability-gated command and is never the default.
- Success removes or tombstones the row only after the upstream service accepts
  the operation. Errors retain the row and show the OpenStack request ID.
- Storage backends/pools are discovery data, not API-created resources. They do
  not receive a fake Delete command.

## Compute

| Resource | Create | Mutable settings and actions | Delete |
|---|---|---|---|
| Instance | Image/volume/snapshot source, Flavor, networks/ports/fixed IPs, security groups, key pair, AZ, metadata, tags, user data, config drive, server group, scheduler hints, block devices, min/max count, hostname, description | Name/description, metadata/tags, security groups, NICs, fixed IPs, Floating IPs, volume attachments, start/stop, soft/hard reboot, pause/unpause, suspend/resume, shelve/unshelve, lock/unlock, rescue/unrescue, rebuild, resize, confirm/revert resize, console | Yes; preview ports, Floating IPs, attached volumes, and boot-volume retention |
| Image | Upload/import and source URL where Glance supports it | Name, visibility, protected state, min disk/RAM, properties, tags, activate/deactivate, member access | Yes |
| Flavor (admin) | ID/name, vCPU, RAM, root/ephemeral disk, swap, RX/TX factor, visibility, description, extra specs, project access | Description, extra specs, and project access. Base sizing is immutable and uses `Clone as new` | Yes |
| Key pair | Import public key by default at Nova 2.92; explicit compatibility generation at 2.10 | No upstream rename/edit; fingerprint and public key are read-only | Yes |

### Flavor Rule

`vCPU`, RAM, disk, ephemeral disk, and swap cannot be presented as normal
editable fields because `flavor set` does not mutate base sizing. The Flavor
drawer provides:

- `Basic`: name/ID, sizing, visibility, description.
- `Extra specs`: key/value set and unset, including namespaced driver specs.
- `Access`: add/remove project access for private Flavors.
- `Clone as new`: prefill all values, change immutable sizing, create the new
  Flavor, optionally review migration candidates, then delete the old Flavor
  only through a separate confirmation.

## Network

| Resource | Required web coverage |
|---|---|
| Network | Create/edit name, description, admin state, shared/external/default flags, MTU, port security, DNS domain, QoS, provider type/segmentation/physical network, tags, extra properties; delete |
| Subnet | CIDR/IP version, gateway, DHCP, allocation pools, DNS, host routes, IPv6 modes, subnet pool/prefix, segment, service types, tags/properties; edit supported fields; delete |
| Port/NIC | Name/description, admin state, MAC, fixed IPs, device owner/ID, vNIC type, host, binding profile, NUMA policy, hints/trusted mode, DNS, QoS, security groups, port security, allowed address pairs, DHCP options, data-plane status, uplink propagation, tags/properties; attach/detach; delete |
| Router | Name/description/admin state, distributed/centralized, HA, routes, external gateway/fixed IPs, SNAT, NDP proxy, QoS, BFD, ECMP, tags; add/remove subnet or port; clear gateway; delete |
| Floating IP | Allocate, associate/disassociate by port and fixed IP, edit description/tags/QoS where supported, move association, release/delete |
| Security group | Name/description, stateful/stateless, tags/properties; create/edit/delete rules; delete group |
| QoS policy | Name/description/shared/default/project ownership, tags; create/edit/delete bandwidth, DSCP, minimum bandwidth/packet rate, and other advertised rule types; delete policy |
| Load balancer | Octavia-gated load balancer, listener, pool, member, health monitor, L7 policy/rule, VIP and failover operations with create/edit/delete coverage |
| Network RBAC | Create, inspect, edit supported target/action fields, and delete project/domain sharing policies |

OVN internals such as chassis and northbound/southbound databases are not
project-user resources and do not appear in the user navigation.

## Storage

| Resource | Required web coverage |
|---|---|
| Volume | Create from blank/image/snapshot/volume/backup, type, AZ, metadata, bootable/read-only flags and scheduler hints when allowed; edit name/description/metadata, extend, retype/migrate where supported, attach/detach, transfer, set bootable/read-only, snapshot/backup, delete/force-delete |
| Volume snapshot | Create, edit name/description/metadata, admin state only when policy allows, unset metadata, delete/force-delete |
| Volume backup | Create full/incremental or from snapshot, name/description/container/AZ/properties; edit supported fields/state, restore, export/import record, delete/force-delete |
| Volume type (admin) | Name/description, public/private access, project access, extra specs, multiattach/cacheable/replicated/AZ flags, encryption provider/cipher/key size/control location; set/unset; delete |
| QoS spec (admin) | Consumer and properties, associate/disassociate volume types, set/unset, delete/force-delete |
| Storage backend (admin) | Read capacity, state, capabilities, pools, host/cluster and driver data; policy-gated service enable/disable, freeze/thaw, and capability-gated replication failover. No backend create/edit/delete unless a deployed service API explicitly advertises it |

The design does not assume Ceph. Backend-specific fields are capability-gated
so a later Ceph deployment can be supported without changing the core model.

## Identity and Administration

| Resource | Required web coverage |
|---|---|
| Project | Create; edit name, description, enabled state, domain-compatible fields, tags/properties where supported; inspect members, role assignments, quotas and resources; delete with impact preview |
| User | Create; edit name, email/description, enabled state, default project/domain-compatible fields, password/application credentials where policy permits; group membership; delete |
| Group | Create/edit name and description, add/remove users, inspect assignments, delete |
| Role | Create/edit when supported, inspect implied roles and assignments, delete |
| Role assignment | Grant/revoke user or group roles at system, domain, project, or supported target scope; inherited assignment where supported |
| Project quota | Read effective/default/usage values; edit every field returned by Nova, Neutron, Cinder, and advertised quota providers independently; `Delete overrides` restores provider defaults without deleting the project; preserve provider default/unlimited semantics |
| All instances | Cross-project server-side filters and pagination, project/owner context, policy-gated lifecycle actions and delete |

Project-scoped users never see system-wide collections. Administration routes
use a distinct navigation model and can query all projects only through
policy-authorized server-side requests.

## Capability and Microversion Rules

- The BFF uses `openstacksdk` microversion negotiation whenever possible.
- Service catalog, extensions, API versions, driver capabilities, and policy
  responses determine field/action availability.
- Unsupported fields are not submitted with null or guessed values.
- A 403 never becomes a successful-looking UI state. The control returns to an
  actionable error state with the request ID.
- Any option that is available in CLI testing but absent from the web form must
  be added or assigned a non-Available ledger state before release.

## Goal 1 Reconciliation Ledger

This is the current design and browser-contract ledger. `Contracted` means the
field/action is represented in OpenAPI and interaction design; `Implemented`
means the runtime and automated tests exist but does not replace reference-cloud
validation. Goal 1 cannot be released until every row is implemented or has an
explicit non-Available state.

| Resource | Goal 1 operations | Current state | Evidence |
| --- | --- | --- | --- |
| Session and scope | Sign in/out, enumerate scopes, select project/region, expire session | Implemented | `POST/GET/DELETE /session`, `PUT /scope`; Login, Project Selection, Project Switcher |
| Project quotas | Read Nova, Neutron, and Cinder used/reserved/limit with independent failures | Implemented | `GET /overview`, `GET /quotas`; Project Overview, Quota Details |
| Instance | List/show/create, rename, lifecycle actions, resize/confirm/revert, delete preview/delete, noVNC | Contracted | `/instances*`, `/operations*`; Compute Goal 1 boards |
| Image | Server-filtered project-visible inventory for provisioning | Contracted | `GET /images`; Images board |
| Flavor | Server-filtered project-allowed inventory for provisioning | Contracted | `GET /flavors`; Create Instance descriptors |
| Key pair | List, default import, compatibility generation with one-time private key, delete | Contracted | `/keypairs*`, `/operations*`; Key Pairs board |
| Network/security group | Server-filtered inventories used by provisioning | Contracted | `GET /networks`, `GET /security-groups` |
| NIC and port | List, attach/detach, supported MAC/fixed-IP/security-group/QoS edits | Contracted | `/instances/{id}/interfaces*`, `PATCH /ports/{id}`; Instance Network and NIC Edit |
| Floating IP | List, allocate, associate/move/disassociate, release | Contracted | `/floating-ips*`; Instance Network |
| Volume relationship | List project volumes, list attachments, attach/detach | Contracted | `/volumes`, `/instances/{id}/volume-attachments*`; Instance Detail Storage |
| noVNC | Create short-lived console session, expire, reconnect | Contracted | `POST /instances/{id}/console`; noVNC board |

Full network CRUD, storage depth, and administrator CRUD remain design-ahead
Goals 2-4 and do not make Goal 1 implementation larger. Their rows above remain
in the broader parity tables so later goals cannot silently omit CLI/API
options.

## Release Gate

For each resource introduced by a roadmap goal:

1. Compare the relevant 2026.1 OpenStackClient object commands and SDK methods
   with the Vantage field/action ledger.
2. Exercise create, show, set, unset, action, and delete paths that exist.
3. Test immutable, capability-gated, policy-gated, dependency-blocked, 403, 409,
   and partial-failure states.
4. Verify both project and admin navigation.
5. Verify numbered pagination at 10, 25, 50, and 100 rows without downloading a
   complete collection.

## Primary References

- OpenStackClient 2026.1 command list:
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-list
- Flavor commands:
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/flavor.html
- Server commands:
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/server.html
- Network, port, router, and security group commands:
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/network.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/subnet.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/port.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/router.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/security-group.html
- Volume, snapshot, backup, type, and QoS commands:
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-snapshot.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-backup.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-type.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-qos.html
- Identity group and role-assignment commands:
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/group.html
  https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/role-assignment.html
