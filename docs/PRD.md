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

## Delivery Model

Goal 1 is the initial usable MVP. Goals 2-4 are incremental product expansion,
not prerequisites hidden inside one large launch. Each goal is implemented,
used on a reference cloud, and re-validated for security and performance before
the next goal starts. Penpot includes all four goals now so product structure,
policy boundaries, and administrator separation can be reviewed before code.

### Goal 1: Initial Usable Project MVP

User outcome:

> Sign in, select a project, understand quota pressure, provision and operate a
> VM, connect it to the network and storage, and open a console without a full
> page reload or a manual refresh.

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
- Browse project/public images, allowed Flavors, networks, security groups, and
  keypairs through server-side collections
- Three-step instance creation: Basics, Network & access, Review
- Edit the Nova display name
- Create and delete a VM
- Start, stop, soft reboot, hard reboot, pause, unpause, suspend, resume,
  shelve, and unshelve when capability, policy, and server state allow
- Resize to an allowed Flavor and explicitly confirm or revert
  `VERIFY_RESIZE`
- Attach/detach a supported network interface and edit permitted Neutron port
  attributes
- Allocate/associate/disassociate a Floating IP, including explicit port and
  fixed-IP selection for multi-interface instances
- Attach/detach a Cinder volume
- Short-lived noVNC console session
- English and Korean UI with stable OpenStack resource names, IDs, status
  values, and request IDs
- Asynchronous operation tracking and OpenStack request IDs

Excluded from Goal 1 implementation:

- Full project network CRUD beyond resources required for everyday VM
  connectivity
- Snapshot/backup management and storage administration
- Administrator-wide views
- Ceph-specific capacity

Release gate:

- No Keystone token is observable in browser storage, payloads, or JavaScript.
- Switching projects cannot leak data from the previous project.
- First useful view is at most 1.5 seconds at p75 on the reference-cloud matrix.
- Project overview BFF latency is at most 800 ms at p95 under the defined
  reference workload.
- Nova or Neutron failure does not blank the entire page.
- Every operation uses the signed-in user's project-scoped authorization.
- `403 Forbidden` is returned as permission denied and is never retried with a
  shared administrator credential.
- Duplicate clicks or retries cannot create duplicate destructive operations.
- noVNC URLs and tokens are short-lived and excluded from logs.
- Required inputs are explicit and do not depend on deployment-specific
  defaults.
- Input collections use server-side filtering and pagination.

### Goal 2: Full Project Networking

Included:

- Networks, subnets, ports, routers, and Floating IP lifecycle
- Security groups and rules
- QoS policies
- Project-visible Neutron RBAC policies
- Capability-gated load balancers when Octavia is present
- Safe editing of supported fixed IP, MAC address, allowed-address-pair, QoS,
  and security-group attributes

Release gate:

- Every collection is server-filtered and paginated.
- The UI exposes Neutron resources, not OVN implementation objects.
- Extension-dependent fields and commands are capability gated.
- Policy `403`, revision conflicts, and asynchronous provisioning states are
  distinct from empty or unsupported states.

### Goal 3: Project Storage Depth

Included:

- Volume create/delete and attachment lifecycle
- Volume snapshots and backups
- Incremental-backup capability handling
- Intermediate and failed storage operations
- Volume types visible to the project when policy permits

Release gate:

- The BFF API is backend-neutral.
- The initial Cinder backend works without Ceph.
- Adding an RBD backend later does not require a user-flow or endpoint change.

### Goal 4: Administrator Workspace

The administrator workspace is a separate staged goal. The active system,
domain, or project token scope is always explicit:

- Domains and projects
- Users, groups, and roles
- Role assignments and project quotas
- Cross-project instances
- Hypervisors, host aggregates, and Placement resource classes
- Flavors under Compute
- Images under a separate Image service section
- Neutron resources and RBAC policies
- Volume types, storage backends, and QoS specs
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
