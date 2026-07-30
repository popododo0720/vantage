# Vantage

Vantage is a comprehensive, deployment-neutral OpenStack web console. It
serves project users and cloud administrators while keeping OpenStack's
services, resources, policies, and request identifiers visible.

The first delivery is one usable project-user MVP, followed by deliberately
smaller expansion goals. Each goal must pass on supported reference clouds
before the next goal is implemented. Penpot carries the later project and
administrator surfaces now so information architecture can be reviewed without
committing to a big-bang implementation.

## MVP

| Goal | Outcome | Scope |
| --- | --- | --- |
| 1 | Initial usable MVP | Secure entry, quota-first overview, instance lifecycle, provisioning inputs, NIC/Floating IP, volume attachment, noVNC |
| 2 | Full project networking | Networks, subnets, ports, routers, security groups, QoS, RBAC, capability-gated load balancing |
| 3 | Project storage depth | Volumes, snapshots, backups, attachment lifecycle, backend-neutral behavior |
| 4 | Administrator workspace | Identity/RBAC, cross-project compute, quotas, network and storage administration |
| 5+ | Catalog-driven expansion | Heat, Octavia, Swift, and other discovered services |

Goal 1 is the active delivery target.

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
- Lists use server-side filtering and pagination.
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

## Documents

- [Product requirements](docs/PRD.md)
- [Incremental roadmap](docs/ROADMAP.md)
- [Security and API boundaries](docs/SECURITY.md)
- [Performance contract](docs/PERFORMANCE.md)
- [Application architecture](docs/ARCHITECTURE.md)
- [Design contract](docs/DESIGN.md)
- [Goal 1 screen and interaction specification](docs/GOAL1-FLOWS.md)
- [MVP mutation interaction specification](docs/MVP-INTERACTIONS.md)
- [Goal 1 BFF OpenAPI](api/openapi.yaml)

## Working Surfaces

- [Notion planning hub](https://app.notion.com/p/3ade0ff2ad2481358105ffc40c05a679)
- [Penpot design file](https://design.penpot.app/#/workspace?team-id=1c48efe5-2f9f-81cd-8007-beddeed3764c&file-id=8694f143-a620-8054-8008-675feb27ac54&page-id=8694f143-a620-8054-8008-675feb27ac55)

The Penpot file is organized by functional page: Auth, Dashboard, Compute,
Network, Storage, and Administration. `Dashboard` is the design-file grouping;
the product navigation and browser route remain `Overview` and `/overview`.

## Compatibility Baseline

- OpenStack 2026.1 is the first API baseline.
- `openstacksdk` and service capabilities extend support across releases.
- Converged and separated control/compute topologies are valid deployments.
- Single- and multi-region clouds are valid deployments.
- Neutron and Cinder implementation backends are abstracted from the UI/BFF
  contract.
- The current ML2/OVN, non-Ceph home lab is the first reference cloud, not a
  product constraint.
