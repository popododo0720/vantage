# Vantage

Vantage is a fast, project-first OpenStack console for the 2026.1 lab.

The project replaces Horizon incrementally. The MVP is split into four usable
goals, and each goal must pass in the lab before the next goal is detailed.

## MVP

| Goal | Outcome | Scope |
| --- | --- | --- |
| 1 | Secure project entry | Login, project switch, quota, instance list/detail |
| 2 | Compute lifecycle | Create, delete, power actions, noVNC |
| 3 | Provisioning inputs | Images, flavors, networks, security groups, keypairs |
| 4 | Connectivity and storage | Floating IPs, volume attach/detach |

Goal 1 is the active delivery target.

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
- The MVP does not depend on Ceph, but the Cinder contract remains RBD-ready.

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

## Lab Baseline

- OpenStack 2026.1
- Kolla-Ansible 22.x
- Three converged nodes: `stack1`, `stack2`, `stack3`
- Neutron ML2/OVN
- No Ceph dependency in the MVP

