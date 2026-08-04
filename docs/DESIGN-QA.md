# Penpot Design Completion Audit

Status: the pre-development design review is complete. Development remains
blocked until the user approves the resulting design.

This audit distinguishes a written interaction contract from inspectable design
evidence. A resource is not design-complete merely because its list page or
requirements exist.

## Evidence Levels

- `Verified`: the dedicated state and prototype transition were inspected.
- `Manifest`: the dedicated board is present in the current Penpot inventory,
  but the final visual and transition audit must be rerun after the last edit.
- `Pending`: the current board manifest does not prove the required states;
  inspect the existing board and add dedicated states when absent.
- `Contract only`: behavior is specified in Markdown but is not yet represented
  by adequate Penpot evidence.

## Goal 1

| Surface | Required states | Evidence |
| --- | --- | --- |
| Authentication | simple login, invalid credentials, project selection, session expiry | Verified |
| Overview | quota-first project overview, project switcher, quota detail, partial-service states | Verified |
| Instances | list, page size, detail drawer, four-step create, lifecycle menu, rename, resize verify, delete confirm, noVNC | Verified |
| Instance networking | NIC inspect/edit/attach/detach, fixed IP and MAC fields, security groups, Floating IP associate/disassociate/release | Verified |
| Instance storage | volume attach/detach and attachment-conflict recovery | Verified |
| Images and Flavors | server-filtered provisioning inventories | Verified |
| Key pairs | default import, explicit compatibility generation with one-time private key, delete confirm | Verified |
| Localization | English/Korean controls and action terminology | Verified |

## Goal 2 Network Design

The interaction contract is complete in `RESOURCE-INTERACTIONS.md` and
`CLI-PARITY.md`. The canonical Network prototype now contains 66 dedicated
states. Four lightweight preview pages mirror those states for page-level
review without duplicating the editable source.

| Resource | Required Penpot evidence | Current evidence |
| --- | --- | --- |
| Networks | list, create, detail, settings, row actions, delete dependency confirm | Verified |
| Subnets | list, create, settings, allocation/DNS/route row editing, delete dependency confirm | Verified |
| Ports | list, create, settings, fixed-IP/security-group/address-pair row editing, detach versus delete, delete confirm | Verified |
| Routers | list, create, settings, interface add/remove, gateway clear, delete dependency confirm | Verified |
| Floating IPs | list, allocate, settings, associate/move/disassociate, forwarding rules, release confirm | Verified |
| Security groups | list, create, settings, rule create/edit/delete, attached-resource delete confirm | Verified |
| QoS policies | list, create, settings, advertised-rule editor, attached-resource delete confirm | Verified |
| Load balancing | capability-gated load balancer, listener, pool, member, health monitor and L7 create/edit/delete plus asynchronous states | Verified |
| Network RBAC | admin list, create/replacement, settings, row actions, delete confirm | Verified |

The Network audit covers 66 canonical boards, 12,839 shapes, and 1,888 click
transitions. No canonical board lacks an interaction, no destination is
unresolved, and the Penpot file validator reports zero errors. The preview
pages contain exactly 13, 15, 22, and 16 boards in stable three-column grids.

## Goal 3 Storage Design

| Resource | Required Penpot evidence | Current evidence |
| --- | --- | --- |
| Volumes | list, create sources, detail, settings, row actions, attach/detach, extend/retype/transfer, delete and force-delete | Verified |
| Snapshots | list, create, settings, row actions, dependent-volume delete and force-delete | Verified |
| Backups | list, create, settings, restore, import/export, row actions, delete and force-delete | Verified |
| Common storage lists | server-side filters, `10/25/50/100`, range, numbered pagination, preserved list state | Verified |

The Storage audit covers 25 canonical boards, 4,744 shapes, and 307 click
transitions. No canonical board lacks an interaction, no same-file destination
is unresolved, no text layer is invisible, and no shape lies outside its owning
board. `05A - Volumes & Attachments` contains 9 review boards and `05B -
Snapshots & Backups` contains 16; both use the standard three-column grid.

## Goal 4 Administration Design

| Resource | Required Penpot evidence | Current evidence |
| --- | --- | --- |
| Projects | list, create, settings/review, membership/roles, row actions, delete confirm | Verified |
| Project quotas | usage/default/effective values, service-specific edit, review/apply, row actions, `Delete overrides` confirm | Verified |
| Users | list, create, settings, row actions, credential boundary, delete confirm | Verified |
| Groups | list, create, settings, member relationships, row actions, remove-members and delete confirms | Verified |
| Roles and assignments | create/settings, implied roles, grant/replace, revoke, row actions, protected delete | Verified |
| Flavors | list, create/clone, settings, extra specs, project access, row actions, delete confirm | Verified |
| Cross-project instances | list, project context, lifecycle operations, row actions, force-delete confirm | Verified |
| Network RBAC | list, create/replacement, settings, row actions, delete confirm | Verified |
| Volume Types and QoS Specs | create/settings, relationships, row actions, normal/force delete confirms | Verified |
| Storage backends/services | read-only backend discovery and capability-gated service operations; no fake backend CRUD | Verified |

`Create project` belongs only to the dedicated Projects section. It covers
domain selection, optional hierarchy capability, name, description, enabled
state, metadata/properties, `403` and `409` recovery with request ID, cancel,
success return, and no shortcut on Administration Overview.

The six Administration review pages contain exactly 13, 11, 13, 9, 13, and 5
boards for Projects/Quotas, Users/Groups, Roles/Membership, Compute, Storage,
and Network administration. The 64 editable states and all 1,222 prototype
transitions remain canonical in `06X - Administration Prototype`.

## Shared Final Gate

- Every list uses server-side filtering and page-size values
  `10`, `25`, `50`, and `100`.
- Pagination uses a range and numbered form such as `< 1 2 3 ... >`.
- A detail drawer never exposes a list-level row-count selector.
- Settings, relationship actions, lifecycle actions, and Delete use consistent
  placement and labels.
- Delete and detach, disassociate, revoke, reset, or `Delete overrides` remain
  distinct operations.
- All destructive actions identify project, resource, dependency impact, and
  retained resources before confirmation.
- `403`, `404`, `409`, timeout, partial failure, unsupported capability, and
  asynchronous operation failure preserve context and expose the OpenStack
  request ID.
- English and Korean labels fit without clipping or overlap.
- Every clickable prototype destination resolves inside the file.
- No text or control extends outside its owning board.

## Completed Penpot Gate

1. Compute, Network, Storage, and Administration are split into lightweight
   resource review pages with canonical editable prototypes preserved.
2. Page order, expected counts, duplicate names, preview dimensions, board
   ownership, and preview child structure pass the global audit.
3. Desktop screenshots cover the split Storage and Administration grids,
   destructive confirmations, settings surfaces, row-action menus, and common
   pagination.
4. The Penpot file validator reports zero errors after the final split.

The remaining work is synchronization of this measured inventory to Notion and
the GitHub draft PR, followed by explicit user approval before development.
