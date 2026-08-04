# Vantage

Vantage is a comprehensive, deployment-neutral OpenStack web console. It
serves project users and cloud administrators while keeping OpenStack's
services, resources, policies, and request identifiers visible.

The first delivery is one usable project-user MVP, followed by deliberately
smaller expansion goals. The complete project, network, storage, and
administrator console is approved; each slice still has to pass its automated
and reference-cloud gates before it is released. Penpot carries later surfaces
ahead of runtime delivery so information architecture can be reviewed without
a big-bang release.

## MVP

| Goal | Outcome | Scope |
| --- | --- | --- |
| 1 | Initial usable MVP | Secure entry, quota-first overview, instance lifecycle, provisioning inputs, NIC/Floating IP, volume attachment, noVNC |
| 2 | Full project networking | Networks, subnets, ports, routers, security groups, QoS, RBAC, capability-gated load balancing |
| 3 | Project storage depth | Volumes, snapshots, backups, attachment lifecycle, backend-neutral behavior |
| 4 | Administrator workspace | Identity/RBAC, cross-project compute, quotas, network and storage administration |
| 5+ | Catalog-driven expansion | Heat, Octavia, Swift, and other discovered services |

Goal 1 is the active release target. Later goals may be developed in isolated,
verifiable slices while the preceding release is exercised.

## Goal 1 development

The runnable application contains a FastAPI BFF and React/TypeScript browser
application for login, current session, logout, accessible projects,
project/region selection, a quota-first overview, and quota details. The
default adapter is a credential-free fake; use username `alice` (or `limited`)
and password `vantage` locally.

```bash
uv sync --extra dev
uv run uvicorn vantage_bff.app:app --app-dir backend --reload

cd frontend
npm ci
npm run dev
```

The Vite development server proxies `/api` to the BFF. Because production
cookies are secure by default, HTTP-only local development must start the BFF
with `VANTAGE_COOKIE_SECURE=false`. Production must leave the default enabled.

Validation commands:

```bash
uv run ruff check backend
uv run mypy backend/vantage_bff
uv run pytest

cd frontend
npm run lint
npm run typecheck
npm test
npm run build

cd ..
uv run openapi-spec-validator api/openapi.yaml
uv run openapi-spec-validator api/openapi.goal1-mvp.yaml
```

For a real cloud, install the SDK extra and select the adapter explicitly:

```bash
uv sync --extra dev --extra openstack
VANTAGE_ADAPTER=openstack \
VANTAGE_OS_AUTH_URL=https://keystone.example/v3 \
uv run uvicorn vantage_bff.app:app --app-dir backend
```

SDK requests use a 15-second default boundary. Set
`VANTAGE_OS_TIMEOUT_SECONDS` only when the reference cloud requires a different
measured value. Quota widgets have a shorter independent boundary controlled by
`VANTAGE_QUOTA_SOURCE_TIMEOUT_SECONDS`, defaulting to 3 seconds. Nova instance
list/detail calls use `VANTAGE_INSTANCE_SOURCE_TIMEOUT_SECONDS`; image, flavor,
key-pair, network, and security-group inventory calls use
`VANTAGE_PROVISIONING_SOURCE_TIMEOUT_SECONDS`. Both default to 3 seconds.
Blocking OpenStack SDK work is limited by
`VANTAGE_OPENSTACK_SDK_THREAD_CAPACITY` (default `8`); timed-out work retains
its slot until the underlying thread exits.

No credential, password, Keystone token, or service endpoint is committed.
See [ADR 0001](docs/adr/0001-goal1-runtime-foundation.md) for the runtime and
session-store boundaries and [ADR 0002](docs/adr/0002-idempotent-operation-boundary.md)
for the shared mutation and operation-tracking contract.

The public session response does not contain the complete accessible-project
set. Project selection uses the paginated `/api/v1/projects` route; only the
server session retains the Keystone membership snapshot used for scope checks.

## Product Scope

- Separate project and administrator workspaces
- Multi-project, multi-domain, and multi-region operation
- Keystone, Nova, Placement, Neutron, Glance, and Cinder as core services
- Capability-driven expansion to services such as Heat, Octavia, and Swift
- Service-catalog discovery instead of hard-coded endpoints or topology
- Deployment-tool, node-count, network-backend, and storage-backend neutrality

## Product Rules

- The browser never calls Nova, Neutron, Glance, or Cinder directly.
- Keystone tokens stay in the server-side session.
- The browser receives only an `HttpOnly; Secure; SameSite` session cookie.
- User actions are never proxied through a shared administrator account.
- Lists use server-side filtering and one numbered pagination pattern:
  `Rows 10/25/50/100`, a result range, and `‹ 1 2 3 … ›`. Text
  `Previous`/`Next` controls are not used.
- OpenStack policy enforcement and `403 Forbidden` are authoritative.
- `openstacksdk` handles microversion selection and normalized responses.
- Service endpoints come from the Keystone service catalog.
- Neutron is the user-facing network contract; OVN internals are not exposed.
- Network and storage backends do not become user-facing API contracts.
- Goal 1 supports English (`en`) and Korean (`ko`) product UI.
- Unsupported services and operations are hidden through catalog and capability
  discovery, not deployment-specific branches.
- Absent, unsupported, degraded, and policy-limited capabilities gate
  navigation and operations explicitly.
- OpenStack API/CLI-supported create, set, unset, action, and delete operations
  cannot be silently omitted. Immutable or unavailable options remain
  discoverable with an explicit reason.

## Documents

- [Product requirements](docs/PRD.md)
- [Incremental roadmap](docs/ROADMAP.md)
- [Security and API boundaries](docs/SECURITY.md)
- [Performance contract](docs/PERFORMANCE.md)
- [Application architecture](docs/ARCHITECTURE.md)
- [Design contract](docs/DESIGN.md)
- [Goal 1 screen and interaction specification](docs/GOAL1-FLOWS.md)
- [MVP mutation interaction specification](docs/MVP-INTERACTIONS.md)
- [Resource screen and interaction contract](docs/RESOURCE-INTERACTIONS.md)
- [CLI and API parity contract](docs/CLI-PARITY.md)
- [MVP planning and design readiness](docs/MVP-READINESS.md)
- [Penpot design completion audit](docs/DESIGN-QA.md)
- [Goal 1.3 quota overview verification](docs/GOAL1-3-VERIFICATION.md)
- [Implemented BFF OpenAPI](api/openapi.yaml)
- [Storage and Cinder verification](docs/STORAGE-VERIFICATION.md)
- [Planned Goal 1 MVP OpenAPI](api/openapi.goal1-mvp.yaml)

## Working Surfaces

- [Notion planning hub](https://app.notion.com/p/3ade0ff2ad2481358105ffc40c05a679)
- [Penpot design file](https://design.penpot.app/#/workspace?team-id=1c48efe5-2f9f-81cd-8007-beddeed3764c&file-id=8694f143-a620-8054-8008-675feb27ac54&page-id=8694f143-a620-8054-8008-675feb27ac55)

The Penpot file is organized by functional page. Auth and Dashboard remain
compact. Compute, Network, Storage, and Administration each have lightweight
review pages grouped by resource plus a canonical editable `X - ... Prototype`
page that retains the component layers and prototype transitions. The review
pages are mirrors and are not counted as additional product states. `Dashboard`
is the design-file grouping; the product navigation and browser route remain
`Overview` and `/overview`.

## Compatibility Baseline

- OpenStack 2026.1 is the first API baseline.
- `openstacksdk` and service capabilities extend support across releases.
- Converged and separated control/compute topologies are valid deployments.
- Single- and multi-region clouds are valid deployments.
- Neutron and Cinder implementation backends are abstracted from the UI/BFF
  contract.
- The current ML2/OVN, non-Ceph home lab is the first reference cloud, not a
  product constraint.
