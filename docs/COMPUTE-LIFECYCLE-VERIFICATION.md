# Compute Lifecycle Implementation and Verification

Status: implemented
Baseline: OpenStack 2026.1

## Delivered Boundary

- The browser calls only the FastAPI BFF. Every compute, image, and flavor
  mutation requires the active server-side session, CSRF proof, active project
  and region, and a scope-bound `Idempotency-Key`.
- Instance creation covers image and volume boot, optional boot-from-volume,
  flavor, network/subnet or existing port, security groups, existing key pair,
  availability zone, metadata, config drive, user data, block devices, and
  count. Selecting a subnet or explicit security groups creates a Neutron port
  so those attributes have one authoritative owner; a failed Nova create
  cleans up only ports created for that request. Existing-port security groups
  remain a Network-slice mutation.
- Lifecycle covers create, update, delete, start/stop, soft/hard reboot,
  pause/unpause, suspend/resume, shelve/unshelve, rescue/unrescue, lock/unlock,
  rebuild, resize, confirm/revert resize, and snapshot.
- Nova state-changing operations remain `running` until the SDK observer sees
  the requested final or recovery state (including `VERIFY_RESIZE`) within
  `VANTAGE_OPERATION_TIMEOUT_SECONDS`, which defaults to 600 seconds.
- Image mutations cover create/import, edit, delete, protect/visibility and
  custom properties, deactivate/reactivate, and member access. Flavor
  mutations cover create, description update, delete, extra specs, and project
  access. Key-pair mutation is intentionally outside this slice; its existing
  paginated list contract is unchanged.
- noVNC URLs are returned directly from a dedicated response with a two-minute
  client validity hint. They are not placed in the operation store, cache, or
  logs. The browser opens the URL with `noopener,noreferrer`.
- VM NIC and Floating IP actions remain owned by the Network slice. The compute
  UI exposes a disabled boundary and delete preview returns the intended API
  contract paths without implementing duplicate network mutations.

## SDK and API Contract

The adapter uses the project-scoped `openstacksdk` connection so service
catalog discovery and microversion negotiation remain inside the SDK. Nova
server, remote-console, flavor, extra-spec, and flavor-access operations use
the Compute proxy. Glance image, import, lifecycle, and member operations use
the Image v2 proxy. Custom image-property removal uses the SDK resource's JSON
Patch support with escaped RFC 6901 paths; this is the only place where remove
semantics differ from an ordinary SDK attribute update.

Primary references:

- [Nova Compute API](https://docs.openstack.org/api-ref/compute/)
- [openstacksdk 2026.1 Compute proxy](https://docs.openstack.org/openstacksdk/2026.1/user/proxies/compute.html)
- [Glance Image API v2](https://docs.openstack.org/api-ref/image/v2/)
- [openstacksdk 2026.1 Image v2 proxy](https://docs.openstack.org/openstacksdk/2026.1/user/proxies/image_v2.html)

## Verification Gates

Run from the repository root:

```bash
uv run ruff check backend
uv run mypy backend/vantage_bff
uv run pytest
uv run openapi-spec-validator api/openapi.yaml
uv run openapi-spec-validator api/openapi.goal1-mvp.yaml

cd frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build

cd ..
git diff --check
```

Tests cover fake and SDK adapters, validation, CSRF and idempotency, operation
scope isolation, upstream request IDs, policy/error propagation, pagination,
secret redaction, one-time console handling, lifecycle actions, image JSON
Patch removal, and flavor extra-spec/access calls.
