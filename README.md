# Vantage

Vantage is a comprehensive, deployment-neutral OpenStack web console. It
serves project users and cloud administrators while keeping OpenStack's
services, resources, policies, and request identifiers visible.

The first delivery is a project-user MVP split into four usable goals. Each
goal must pass on supported reference clouds before the next goal is detailed.
Administrator, identity, image, network, quota, storage, and optional service
management continue as staged product goals after that first delivery.

## MVP

| Goal | Outcome | Scope |
| --- | --- | --- |
| 1 | Secure project entry | Login, project switch, quota, instance list/detail |
| 2 | Provision and operate compute | Select required inputs, create/delete, power actions, noVNC |
| 3 | Manage provisioning resources | Images, flavors, networks, security groups, keypairs |
| 4 | Connectivity and storage | Floating IPs, volume attach/detach |

Goal 1 is the active delivery target.

## Product Scope

- Separate project and administrator workspaces
- Multi-project, multi-domain, and multi-region operation
- Keystone, Nova, Neutron, Glance, and Cinder as core services
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
- Unsupported services and operations are hidden through catalog and capability
  discovery, not deployment-specific branches.

## Documents

- [Product requirements](docs/PRD.md)
- [Incremental roadmap](docs/ROADMAP.md)
- [Security and API boundaries](docs/SECURITY.md)
- [Performance contract](docs/PERFORMANCE.md)
- [Design contract](docs/DESIGN.md)
- [Goal 1 BFF OpenAPI](api/openapi.yaml)

## Working Surfaces

- [Notion planning hub](https://app.notion.com/p/3ade0ff2ad2481358105ffc40c05a679)
- [Penpot design file](https://design.penpot.app/#/workspace?team-id=1c48efe5-2f9f-81cd-8007-beddeed3764c&file-id=8694f143-a620-8054-8008-675feb27ac54&page-id=8694f143-a620-8054-8008-675feb27ac55)

## Compatibility Baseline

- OpenStack 2026.1 is the first API baseline.
- `openstacksdk` and service capabilities extend support across releases.
- Converged and separated control/compute topologies are valid deployments.
- Single- and multi-region clouds are valid deployments.
- Neutron and Cinder implementation backends are abstracted from the UI/BFF
  contract.
- The current ML2/OVN, non-Ceph home lab is the first reference cloud, not a
  product constraint.
