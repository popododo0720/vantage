# Administrator identity, RBAC, and quotas

This slice implements the Goal 4 administrator workspace without changing the
project-user overview. The browser receives only a server-authorized
`admin_available` capability and calls the BFF for every administrator action;
it never receives or stores a Keystone token.

## Authorization and scope

At authentication time the OpenStack adapter attempts real system and domain
scope token issuance. Only scopes accepted by Keystone are retained in the
server session. Entering the administrator workspace then requires an explicit
system, domain, or project administrator scope. A role name in the browser is
never treated as authorization, and an upstream `403` remains the final policy
decision.

Changing administrator scope rotates the CSRF token and the operation
namespace. Lists, cursors, operations, and idempotency records cannot be reused
across user, administrator-scope, project, or region boundaries.

## Identity and role assignments

Projects, users, groups, and roles support bounded list/search, detail, create,
update, disable where Keystone exposes `enabled`, and delete. Role grants and
revocations support user or group actors and system, domain, or project scope;
inherited grants are accepted only for domain and project scope.

The identity list adapter uses Keystone's bounded REST collection response so
the upstream `links.next` marker remains opaque and server-side. Mutations use
openstacksdk proxy methods. The contract is based on the
[Keystone Identity API](https://docs.openstack.org/api-ref/identity/v3/) and
[openstacksdk Identity v3 proxy](https://docs.openstack.org/openstacksdk/2026.1/user/proxies/identity_v3.html).

## Quotas

The workspace reads, updates, and deletes project quota overrides for Nova,
Neutron, and Cinder. “Reset” means deleting/reverting the service quota
override; it never deletes a project. Nova user-specific quota operations are
kept separate and send `user_id`/`user` only to Compute. Neutron and Cinder
reject user-specific quota input rather than silently changing project quota.

The service boundaries follow the
[Nova quota-set API](https://docs.openstack.org/api-ref/compute/#quota-sets-os-quota-sets),
[Neutron quota API](https://docs.openstack.org/api-ref/network/v2/#quotas), and
[Cinder quota-set API](https://docs.openstack.org/api-ref/block-storage/v3/#quota-sets-extension-os-quota-sets).
If one service fails, the read response retains successful services and returns
a typed partial error for the failed service.

## Mutation safety and auditability

Every administrator mutation requires CSRF, `Idempotency-Key`, and an exact
typed confirmation target. The BFF records an operation ID, Vantage trace ID,
and all returned OpenStack request IDs. `403`, `409`, and partial failures remain
distinct outcomes. Passwords and tokens are not included in operation records;
password input contributes only to the one-way idempotency fingerprint.

Lists accept page sizes `10`, `25`, `50`, or `100` and expose the shared
`< 1 2 >` pagination model. Search and role-assignment filters are sent to
Keystone, while opaque upstream cursors stay in the BFF cursor store.
