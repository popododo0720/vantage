# Vantage Product Requirements

Status: Goal 1 active  
Target: OpenStack 2026.1  
Product scope: comprehensive, deployment-neutral OpenStack web console

## Why Vantage

The current console is replaced for two equally important reasons:

1. Daily OpenStack work is difficult to scan and navigate.
2. Page transitions and resource views are too slow for repeated operations.

Vantage is not a visual skin over Horizon. It establishes a new browser-to-BFF
boundary, a project-first information model, and measurable performance gates.

## Product Scope

Vantage is intended to cover the daily OpenStack workflows served by a
Skyline- or Horizon-class console without inheriting their information
architecture or performance constraints.

- Project and administrator workspaces are first-class product surfaces.
- Domain, region, project, and system scope remain explicit.
- Keystone, Nova, Placement, Neutron, Glance, and Cinder are core services.
- Heat, Octavia, Swift, and other services can appear when discovered through
  the service catalog and supported capabilities.
- Navigation and behavior cannot depend on a deployment tool, node count,
  converged topology, network backend, or storage backend.
- The current home lab is an initial reference cloud, not the product model.

## Product Outcomes

- A user can enter a project and understand quota pressure immediately.
- Common compute tasks require fewer page transitions and retain context.
- Project and administrator workspaces have separate navigation and scope.
- One slow OpenStack service cannot block an otherwise useful page.
- OpenStack terminology, resources, policies, and request IDs remain visible.
- The implementation stays compatible with cloud upgrades through service
  catalog discovery and `openstacksdk` normalization.

## Non-Goals

- Exposing OVN NB/SB databases, chassis, or metadata implementation details.
- Showing a DHCP agent surface in an OVN-native deployment.
- Treating the first project MVP as the final product boundary.
- Depending on Ceph or naming an API after a storage backend.
- Recreating every Horizon feature before users can try Vantage.

## MVP Definition

The first project MVP is complete only when Goals 1 through 4 pass on supported
reference clouds.

### Goal 1: Secure Project Entry

User outcome:

> Sign in, select a project, understand quota pressure, and inspect instances
> without a full page reload or a manual refresh.

Included:

- Keystone sign-in and sign-out
- Accessible project list and explicit project switch
- Current project, domain, and region context
- Used/limit quota for vCPU, RAM, instances, and floating IPs
- Cinder `gigabytes` in-use plus reserved usage, volume and snapshot counts,
  and separate backup count/capacity quotas
- Server-filtered, paginated instance list
- Instance detail with status, image, flavor, addresses, and volume summary
- Background revalidation and widget-level partial failure

Excluded:

- Mutating instance actions
- Resource creation
- Administrator-wide views
- Ceph-specific capacity

Release gate:

- No Keystone token is observable in browser storage, payloads, or JavaScript.
- Switching projects cannot leak data from the previous project.
- First useful view is at most 1.5 seconds at p75 on the reference-cloud matrix.
- Project overview BFF latency is at most 800 ms at p95 under the defined
  reference workload.
- Nova or Neutron failure does not blank the entire page.

### Goal 2: Provision and Operate Compute

Included:

- Select image, flavor, network, security group, and keypair from server-side
  lists
- Create and delete a VM
- Start, stop, and reboot
- Asynchronous task feedback
- noVNC session creation and expiration

Entry condition:

- Goal 1 is used on a reference deployment for at least one review cycle.
- Goal 1 security and performance gates remain green.

Release gate:

- Every operation uses the signed-in user's project-scoped authorization.
- `403 Forbidden` is returned as permission denied and is never retried with a
  shared administrator credential.
- Duplicate clicks or retries cannot create duplicate destructive operations.
- noVNC URLs and tokens are short-lived and excluded from logs.
- Required inputs are explicit and do not depend on deployment-specific
  defaults.
- Input collections use server-side filtering and pagination.

### Goal 3: Manage Provisioning Resources

Included:

- Browse project and public images
- Browse allowed flavors
- Create and manage project networks and security groups
- Create and manage keypairs

Release gate:

- Every collection is server-filtered and paginated.
- Public and project-owned resources are clearly distinguished.
- Private key material is never displayed again after creation.
- The UI exposes Neutron resources, not OVN implementation objects.

### Goal 4: Connectivity and Storage

Included:

- Allocate, associate, disassociate, and release floating IPs
- Attach and detach Cinder volumes
- Display intermediate and failed attachment state

Release gate:

- The BFF API is backend-neutral.
- The initial Cinder backend works without Ceph.
- Adding an RBD backend later does not require a user-flow or endpoint change.

## Administrator Workspace

The administrator workspace is part of the product scope and begins as staged
deliveries after the first project MVP. The active system, domain, or project
token scope is always explicit:

- Domains and projects
- Users, groups, and roles
- Cross-project instances
- Hypervisors, host aggregates, and Placement resource classes
- Flavors under Compute
- Images under a separate Image service section
- Neutron resources
- Volume types and storage backends
- Catalog and API capabilities
- Default quotas
- Optional audit and observability integrations

Administrator actions still use the administrator's own scoped token. They are
not a shared proxy for project users.

## Capability-Driven Expansion

- Feature availability is derived from the Keystone service catalog and API
  capabilities.
- Absent, unsupported, degraded, and policy-limited capabilities gate
  navigation and operations explicitly.
- Heat, Octavia, Swift, and additional services are delivered as independent
  product goals after the core project and administrator workflows.
- Multi-region and large-fleet behavior is validated independently from the
  first home-lab reference environment.

## Source Baseline

- [openstacksdk microversions](https://docs.openstack.org/openstacksdk/latest/user/microversions)
- [Compute microversions](https://docs.openstack.org/api-guide/compute/microversions.html)
- [Keystone service catalog](https://docs.openstack.org/keystone/latest/admin/manage-services.html)
- [Neutron ML2/OVN](https://docs.openstack.org/neutron/latest/install/ovn/manual_install.html)
