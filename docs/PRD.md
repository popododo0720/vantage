# Vantage MVP Product Requirements

Status: Goal 1 active  
Target: OpenStack 2026.1  
Environment: three-node converged lab

## Why Vantage

The current console is replaced for two equally important reasons:

1. Daily OpenStack work is difficult to scan and navigate.
2. Page transitions and resource views are too slow for repeated operations.

Vantage is not a visual skin over Horizon. It establishes a new browser-to-BFF
boundary, a project-first information model, and measurable performance gates.

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
- Building the administrator workspace before the project MVP is proven.
- Depending on Ceph or naming an API after a storage backend.
- Recreating every Horizon feature before users can try Vantage.

## MVP Definition

The MVP is complete only when Goals 1 through 4 pass their lab gates.

### Goal 1: Secure Project Entry

User outcome:

> Sign in, select a project, understand quota pressure, and inspect instances
> without a full page reload or a manual refresh.

Included:

- Keystone sign-in and sign-out
- Accessible project list and explicit project switch
- Current project, domain, and region context
- Used/limit quota for vCPU, RAM, instances, volumes, and floating IPs
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
- First useful view is at most 1.5 seconds at p75 on the lab LAN.
- Project overview BFF latency is at most 800 ms at p95 under normal lab load.
- Nova or Neutron failure does not blank the entire page.

### Goal 2: Compute Lifecycle

Included:

- Create and delete a VM
- Start, stop, and reboot
- Asynchronous task feedback
- noVNC session creation and expiration

Entry condition:

- Goal 1 is used in the lab for at least one review cycle.
- Goal 1 security and performance gates remain green.

Release gate:

- Every operation uses the signed-in user's project-scoped authorization.
- `403 Forbidden` is returned as permission denied and is never retried with a
  shared administrator credential.
- Duplicate clicks or retries cannot create duplicate destructive operations.
- noVNC URLs and tokens are short-lived and excluded from logs.

### Goal 3: Provisioning Inputs

Included:

- Images
- Flavors
- Networks
- Security groups
- Keypairs

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

Administrator scope begins after the project MVP:

- All projects
- Users, groups, and roles
- Cross-project instances
- Hypervisors and capacity
- Neutron resources
- Volume types and storage backends
- Service state, default quotas, and audit log

Administrator actions still use the administrator's own scoped token. They are
not a shared proxy for project users.

## Source Baseline

- [openstacksdk microversions](https://docs.openstack.org/openstacksdk/latest/user/microversions)
- [Compute microversions](https://docs.openstack.org/api-guide/compute/microversions.html)
- [Kolla-Ansible 2026.1](https://docs.openstack.org/releasenotes/kolla-ansible/2026.1.html)
- [Neutron ML2/OVN](https://docs.openstack.org/neutron/latest/install/ovn/manual_install.html)

