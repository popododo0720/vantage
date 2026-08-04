# Goal 2 Network Services Verification

Status: implemented; reference-cloud execution remains a release gate  
Baseline: OpenStack 2026.1

## Runtime coverage

`/api/v1/network` provides capability discovery and bounded list, detail,
create, update, dependency-preview, delete, action, and operation-status
contracts for:

- Neutron networks, subnets, ports, routers, floating IPs, security groups and
  rules, QoS policies and rules, and RBAC policies;
- Octavia load balancers, listeners, pools, members, health monitors, L7
  policies, and L7 rules when `load-balancer` is present in the catalog.

Port actions cover instance attach/detach and fixed-IP add/remove. Port edits
cover MAC address, fixed IPs, allowed-address pairs, security groups, QoS, and
port security. Router interface/gateway and floating-IP
associate/disassociate operations are explicit actions. Security-group rules
are intentionally immutable: Neutron supports create/delete rather than an
update operation. Dependency/state conflicts and policy denials remain
authoritative `409` and `403` results with the OpenStack request ID.

The Octavia table uses provisioning and operating status directly. It does not
invent a separate health semantic. Nested member, monitor, and L7 resources
require a parent identifier.

## Isolation and administration

The browser calls only the BFF. Keystone tokens and catalog endpoints remain
in the server session. All mutations require the secure session cookie, CSRF
token, and a scope-bound `Idempotency-Key`. Cursor state and operation lookup
are isolated by user, project, region, resource, filters, and page size.

Project routes reject administrator-only ownership, shared/external/default,
provider-network, device binding, and router deployment-mode fields. This is a
product-surface boundary, not an authorization substitute: Neutron and Octavia
policy are the final authority. Project responses also strip OVN and binding
internals. Administrator workflows remain in the separate administrator
workspace defined by Goal 4.

## Contract sources

- [OpenStack Networking API v2](https://docs.openstack.org/api-ref/network/v2/)
- [OpenStack Load Balancer API v2](https://docs.openstack.org/api-ref/load-balancer/v2/)
- [openstacksdk Network proxy](https://docs.openstack.org/openstacksdk/latest/user/proxies/network.html)
- [openstacksdk Load Balancer proxy](https://docs.openstack.org/openstacksdk/latest/user/proxies/load_balancer.html)

The SDK proxy is preferred for endpoint discovery, normalized resources, and
negotiated service behavior. No raw service URL or deployment topology is
encoded in the runtime.

## Automated gate

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

Tests exercise fake and openstacksdk adapters, filtering and bounded
pagination, nested resources, EN/KO presentation, CSRF and idempotency,
project/region isolation, immutable and administrator-only fields, upstream
`403`/`409` preservation, request IDs, destructive confirmation, and Octavia
status presentation.
