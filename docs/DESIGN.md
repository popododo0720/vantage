# Design Contract

## Product Character

Vantage should combine:

- AWS-like service and resource hierarchy
- Proxmox-like density and capacity visibility
- OpenStack's existing project and service vocabulary

It is an operational console, not a marketing dashboard.

## Information Principles

- Make the current project, domain, and region unambiguous.
- Lead with quota used/limit and pressure, not decorative resource counts.
- Keep project and administrator navigation separate.
- Prefer tables, filters, comparison, and clear operation feedback.
- Preserve context through list, detail, and mutation flows.
- Use OpenStack resource names; do not expose OVN implementation internals.
- Derive service navigation from the Keystone catalog and API capabilities.
- Keep node count, deployment topology, and backend names out of the product IA.
- Do not create default project navigation for network-backend internals.

## Project MVP Navigation

- Overview
- Instances
- Images
- Flavors
- Keypairs
- Networks
- Security groups
- Floating IPs
- Volumes
- API access
- Project settings

## Administrator Navigation

- Token scope: System, Domain, or Project
- Domains and projects
- Users, groups, and roles
- Cross-project instances
- Hypervisors, aggregates, and Placement resource classes
- Flavors under Compute
- Images under a separate Image service section
- Neutron resources
- Volumes, volume types, and storage backends
- Catalog and API capabilities
- Default quotas
- Optional integrations

The project and administrator workspaces share design tokens and interaction
patterns, but never share an implicit scope. Service-specific navigation appears
only when the catalog and capability checks support it. Absent, unsupported,
degraded, and policy-limited states are explicit and gate affected navigation
or operations.

## Required States

Every primary view accounts for:

- loading
- empty
- permission denied
- partial service failure
- expired session
- stale cached data with timestamp
- asynchronous action in progress
- action failure with an OpenStack request ID

## Visual Rules

- Dense but legible layout for repeated operations.
- Stable dimensions for tables, quota bars, status cells, and toolbars.
- Restrained OpenStack red accent with semantic blue, green, amber, and red.
- Cards only for individual summaries or repeated resources.
- No cards nested inside cards.
- No manual refresh control; show background-update state only when useful.
- Icons for familiar actions, with tooltips for unfamiliar controls.
- Text and actions must fit at desktop and mobile breakpoints without overlap.

## Penpot Boards

- `Vantage - Incremental MVP 2026.1`
- `Vantage - Project Overview`
- `Vantage - Admin Overview`
- `Vantage Console - Components`
- `Console Identity Directions`

Design file:
[Vantage Console in Penpot](https://design.penpot.app/#/workspace?team-id=1c48efe5-2f9f-81cd-8007-beddeed3764c&file-id=8694f143-a620-8054-8008-675feb27ac54&page-id=8694f143-a620-8054-8008-675feb27ac55)
