# Storage and Cinder Verification

Status: implemented on `codex/storage-services`
Baseline: OpenStack 2026.1, Block Storage API v3, openstacksdk 4.x

## Runtime boundary

- All browser requests terminate at the FastAPI BFF. Keystone tokens and catalog endpoints remain
  in the server session.
- Every mutation requires both the session CSRF token and an `Idempotency-Key` and is recorded in
  the existing user/project/region-scoped operation store.
- Cinder policy remains authoritative. `401`, `403`, `404`, `409`, quota/capacity `413`, `429`,
  timeout, and upstream request IDs are preserved as problem responses.
- Lists use Cinder marker pagination through the bounded cursor store and expose only the common
  10/25/50/100 numbered-page contract.
- Pool/backend data is discovery-only. Vantage does not invent create, edit, or delete operations
  for storage backends.

## Parity reconciliation

| Resource | Implemented coverage |
| --- | --- |
| Volume | List/show; create from blank, image, snapshot, volume, or backup; name, description and metadata set/unset; attach/detach through Nova; extend; retype; migrate; transfer create/accept; upload to image; bootable/read-only; revert; manage/unmanage; delete/force-delete |
| Snapshot | List/show/create; name, description, metadata and policy-gated state; delete/force-delete; unmanage |
| Backup | List/show; full/incremental and snapshot-source create; name, description, metadata and policy-gated state; restore; export/import record; delete/force-delete |
| Volume type | List/show/create/update/delete; public/private access; project access; extra specs; encryption create/update/delete |
| QoS spec | List/show/create/update/delete/force-delete; property set/unset; volume-type associate/disassociate/all |
| Backend/pool | Capacity, host/backend identity, and driver-advertised capabilities; no fake mutations |
| Service | List and policy-gated enable, disable, freeze, thaw, and replication failover |

Admin routes intentionally do not infer authorization from role names. They call Cinder using the
active user's token and surface the policy result. Backend-specific capability maps are retained as
opaque data, so LVM, RBD/Ceph, and other drivers use the same browser/BFF contract.

## Risk controls

- Normal delete and force-delete are separate operations.
- Delete, force-delete, migrate, unmanage, revert, and service actions require the exact resource ID
  as typed confirmation.
- A normal delete of an attached or otherwise incompatible fake/reference resource returns `409`;
  the BFF does not hide Cinder dependency or in-use conflicts.
- Transfer auth keys and exported backup records are returned only in the first successful mutation
  response. They are not stored in the operation record.
- Attachment lifecycle uses Nova's public server volume-attachment contract rather than Cinder's
  service-to-service attachment API.

## Official contracts checked

- [Block Storage API v3](https://docs.openstack.org/api-ref/block-storage/v3/)
- [openstacksdk Block Storage v3 proxy](https://docs.openstack.org/openstacksdk/latest/user/proxies/block_storage_v3.html)
- [OpenStackClient volume commands](https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume.html)
- [OpenStackClient snapshot commands](https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-snapshot.html)
- [OpenStackClient backup commands](https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-backup.html)
- [OpenStackClient volume type commands](https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-type.html)
- [OpenStackClient QoS commands](https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/volume-qos.html)

## Automated gates

The storage test suite covers authentication and active-scope requirements, CSRF, idempotency
replay/conflict, user/project/region operation isolation, server filters, marker pagination, all four
page sizes, request IDs, exact confirmation, normal-delete conflict, force-delete, 403/409
preservation, source validation, and policy-driven admin collections. Frontend tests cover EN/KO,
project/admin navigation, action discoverability, stale-data behavior, numbered pagination, and
long identifiers in responsive card containers.
