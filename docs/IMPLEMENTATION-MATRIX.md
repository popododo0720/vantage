# OpenStack 2026.1 Implementation and CLI Parity Matrix

Audit baseline: `origin/codex/vantage-mvp-planning` at
`f813873730b62a46988833a6cec2eab70a6530e0` (2026-08-04).

This is an implementation audit, not a roadmap. A requirement, Penpot audit,
or path in the planned Goal 1 OpenAPI is not implementation evidence. Statuses
are assigned only from files present at the audit baseline:

- **Implemented**: browser/BFF/adapter behavior required by the row exists and
  has automated evidence; local runtime or browser evidence is recorded where
  applicable.
- **Partial**: at least one implementation layer exists, but the row is not an
  end-to-end completed slice.
- **Missing**: no product runtime implementation exists; prose or planned
  OpenAPI may exist.
- **Unverified**: implementation or a measurable contract exists, but the
  required deployment, real-cloud, browser, or performance evidence is absent.

## Evidence key

Every matrix cell states the evidence needed and the evidence actually present.
`—` means the required evidence is absent.

| Key | Repository evidence |
| --- | --- |
| UI-A | [`frontend/src/App.tsx`](../frontend/src/App.tsx), [`frontend/src/App.test.tsx`](../frontend/src/App.test.tsx) |
| UI-I | [`frontend/src/InstancesPage.tsx`](../frontend/src/InstancesPage.tsx), [`frontend/src/instance-route.ts`](../frontend/src/instance-route.ts) |
| UI-P | [`frontend/src/ProvisioningPages.tsx`](../frontend/src/ProvisioningPages.tsx), [`frontend/src/inventory-route.ts`](../frontend/src/inventory-route.ts) |
| UI-G | [`frontend/src/Pagination.tsx`](../frontend/src/Pagination.tsx), [`frontend/src/styles.css`](../frontend/src/styles.css) |
| API-R | Published runtime contract: [`api/openapi.yaml`](../api/openapi.yaml) |
| API-P | Planned-only Goal 1 contract: [`api/openapi.goal1-mvp.yaml`](../api/openapi.goal1-mvp.yaml) |
| BFF | [`backend/vantage_bff/app.py`](../backend/vantage_bff/app.py), [`backend/vantage_bff/models.py`](../backend/vantage_bff/models.py) |
| SEC | [`backend/vantage_bff/sessions.py`](../backend/vantage_bff/sessions.py), [`backend/vantage_bff/rate_limit.py`](../backend/vantage_bff/rate_limit.py) |
| CUR | [`backend/vantage_bff/cursors.py`](../backend/vantage_bff/cursors.py) |
| OPS | [`backend/vantage_bff/operations.py`](../backend/vantage_bff/operations.py) |
| SDK | [`backend/vantage_bff/adapters/openstack_sdk.py`](../backend/vantage_bff/adapters/openstack_sdk.py) |
| FAKE | [`backend/vantage_bff/adapters/fake.py`](../backend/vantage_bff/adapters/fake.py) |
| T-S | [`backend/tests/test_session_scope.py`](../backend/tests/test_session_scope.py) |
| T-Q | [`backend/tests/test_quota_overview.py`](../backend/tests/test_quota_overview.py) |
| T-I | [`backend/tests/test_instance_inventory.py`](../backend/tests/test_instance_inventory.py) |
| T-P | [`backend/tests/test_provisioning_inputs.py`](../backend/tests/test_provisioning_inputs.py) |
| T-O | [`backend/tests/test_operations.py`](../backend/tests/test_operations.py) |
| T-A | [`backend/tests/test_openstack_adapter.py`](../backend/tests/test_openstack_adapter.py) |
| T-C | [`backend/tests/test_openapi_contract.py`](../backend/tests/test_openapi_contract.py) |
| V-1 | Local evidence: [`GOAL1-1-VERIFICATION.md`](GOAL1-1-VERIFICATION.md) |
| V-Q | Local evidence: [`GOAL1-3-VERIFICATION.md`](GOAL1-3-VERIFICATION.md) |
| V-I | Local evidence: [`GOAL1-4-VERIFICATION.md`](GOAL1-4-VERIFICATION.md) |

## 1. Entry, scope, overview, and shared interaction

| ID | Requirement | Owner | Scope | UI evidence needed → current | BFF/API evidence needed → current | Adapter/upstream evidence needed → current | Automated test evidence needed → current | Runtime/manual evidence needed → current | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-001 | Keystone login and non-enumerating failure/rate-limit states | Identity | Project | Login, pending, 401, 429 → UI-A | Cookie session endpoint and normalized problems → API-R, BFF, SEC | User-auth exchange/request ID → SDK, FAKE | credential secrecy, rate limit, errors → T-S, T-A | local fake desktop/mobile → V-1; real Keystone → — | Implemented |
| IM-002 | Server-side session, expiry, logout, re-authentication | Platform | Both | expiry block and logout → UI-A | GET/PATCH/DELETE session, rotation/expiry → API-R, BFF, SEC | scoped token lifecycle → SDK | expiry, rotation, invalidation, CSRF → T-S | local fake → V-1; durable multi-worker/TLS → — | Implemented |
| IM-003 | Accessible project selection and bounded search | Identity | Project | search/select/loading/empty/error → UI-A, UI-G | `/projects`, 10/25/50/100 page response → API-R, BFF | Keystone membership boundary → SDK, FAKE | bounded pagination/isolation → T-S | local fake → V-1; large live membership → — | Implemented |
| IM-004 | Explicit project switch with prior-scope invalidation | Platform | Project | switcher/skeleton/no old rows → UI-A | atomic scope/session rotation → API-R, BFF, SEC, CUR | project-scoped connection → SDK | project/user isolation and cursor invalidation → T-S, T-I | local fake → V-1; live multi-project → — | Implemented |
| IM-005 | Region selection/switch and catalog-selected interface | Platform | Both | exact active region → UI-A | region in server scope/cache key → API-R, BFF, SEC | catalog/interface/region connection arguments → SDK | argument and isolation tests → T-S, T-A | local fake → V-1; multi-region cloud → — | Implemented |
| IM-006 | English/Korean language selection and persistence | UX | Both | locale control and translated implemented routes → UI-A, UI-I, UI-P | session preference rotation → API-R, BFF, SEC | no service translation required → n/a | UI-A tests, T-S | implemented surfaces desktop/mobile → V-1, V-Q, V-I; complete product → — | Partial |
| IM-007 | Quota-first project overview: Nova/Neutron/Cinder | Quota | Project | independent quota cards → UI-A | concurrent `/overview` aggregation → API-R, BFF | detailed per-service quota calls → SDK, FAKE | normalization and partial failures → T-Q | local fake → V-Q; live service variants → — | Implemented |
| IM-008 | Project quota detail: used/reserved/limit/unlimited | Quota | Project | service filter and bounded table → UI-A | `/quotas` and service filtering → API-R, BFF | missing fields omitted, negative limit unlimited → SDK | reserved/negative/absent tests → T-Q | local fake → V-Q; per-type live quotas → — | Implemented |
| IM-009 | Administrator quota dashboard and cross-project perspectives | Quota/Admin | Admin | admin overview/project context → — | admin quota/list endpoints and explicit system/domain/project scope → — | policy-authorized cross-project quota calls → — | admin isolation/partial-apply tests → — | real admin cloud → — | Missing |
| IM-010 | Project quota edit, provider-specific apply, `Delete overrides` | Quota/Admin | Admin | schema-driven edit/review/partial result → — | independent Nova/Neutron/Cinder mutation schemas → — | quota update/reset APIs → — | 403/409/partial apply/default semantics → — | real admin cloud → — | Missing |
| IM-011 | Shared list sizes 10/25/50/100, default 25, range and `< 1 2 >` | UX/Platform | Both | shared numbered footer → UI-G on project, instances, images, keypairs | page metadata and cursor maps → API-R, BFF, CUR | one bounded upstream page → SDK | T-S, T-I, T-P and UI-A | implemented lists → V-1, V-I; all project/admin lists → — | Partial |
| IM-012 | Shared server-side search/filter/sort and query reset | Platform | Both | URL/query controls and reset → UI-A, UI-I, UI-P | bounded validated query → API-R, BFF, CUR | translated upstream filters/sorts → SDK | T-S, T-I, T-P | implemented lists only → V-I | Partial |
| IM-013 | Shared CRUD row menu, detail sections, and danger-zone confirmation | UX | Both | common view/edit/relations/delete pattern → — | shared descriptors/delete preview/mutations → API-P only | upstream CRUD/action adapters → — | state/policy/dependency tests → — | browser workflows → — | Missing |
| IM-014 | Loading, empty, error, 403, 409, stale and partial states | UX/Platform | Both | distinct states without false empty → UI-A, UI-I, UI-P for implemented reads | normalized problems/request IDs → API-R, BFF | upstream exception mapping → SDK | T-S, T-Q, T-I, T-P | implemented read surfaces → V-Q, V-I; all mutations/resources → — | Partial |
| IM-015 | Responsive/mobile behavior and accessible keyboard/focus | UX | Both | desktop/tablet/mobile, focus restoration, no overflow → UI-A, UI-I, UI-G for implemented views | no special API evidence → n/a | n/a | React tests cover implemented navigation → UI-A | local 1280/1024/390 evidence → V-1, V-Q, V-I; complete scope → — | Partial |

## 2. Compute, image, flavor, and key-pair parity

| ID | Requirement | Owner | Scope | UI evidence needed → current | BFF/API evidence needed → current | Adapter/upstream evidence needed → current | Automated test evidence needed → current | Runtime/manual evidence needed → current | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-016 | Instance list with project filters, image/status/sort and bounded pagination | Compute | Project | table/filter/numbered pages → UI-I, UI-G | `/instances` query/page schema → API-R, BFF, CUR | one Nova `/servers/detail`, `limit+1`, marker → SDK | 1k/10k, clamp, isolation, errors → T-I | local fake desktop/mobile → V-I; live Nova → — | Implemented |
| IM-017 | Instance detail with exact ID/status/image/flavor/addresses/volumes/request ID | Compute | Project | routed drawer, independent tabs → UI-I | `/instances/{id}` nullable-safe schema → API-R, BFF | Nova detail normalization → SDK | partial/down-cell, 403/404/request ID → T-I | local fake → V-I; live Nova → — | Implemented |
| IM-018 | Instance create: sources/count/flavor/AZ/network/port/SG/key/user-data/metadata/tags/config-drive/hints | Compute | Project | four-step wizard/review/preflight → — | create schema/idempotent operation → API-P only, OPS not wired | Nova create + capability/microversion arguments → — | payload, quota, 403/409/replay tests → — | real create → — | Missing |
| IM-019 | Instance edit name/description/hostname/metadata/tags set/unset | Compute | Project | settings/advanced diff and recovery → — | PATCH/descriptors → API-P only | Nova update/metadata/tag calls → — | field/microversion/policy tests → — | real edit → — | Missing |
| IM-020 | Start/stop and soft/hard reboot | Compute | Project | state-gated actions/pending/error → — | tracked action endpoint → API-P only, OPS not wired | Nova server actions → — | state/403/409/idempotency tests → — | real lifecycle → — | Missing |
| IM-021 | Pause/unpause and suspend/resume | Compute | Project | state-gated actions → — | tracked action endpoint → API-P only | Nova actions → — | state/policy/replay tests → — | real lifecycle → — | Missing |
| IM-022 | Shelve/unshelve including advertised AZ/host options | Compute | Project/Admin | capability/state-gated forms → — | tracked action descriptors → API-P only | Nova microversion-negotiated actions → — | 403/409/microversion tests → — | real lifecycle → — | Missing |
| IM-023 | Lock/unlock, rescue/unrescue, rebuild and other supported Nova actions | Compute | Both | discoverable parity controls/gating → — | action descriptors/schemas → — | Nova actions and microversions → — | policy/state/capability tests → — | real cloud → — | Missing |
| IM-024 | Resize and explicit `VERIFY_RESIZE` confirm/revert | Compute | Project | flavor comparison and recovery state → — | resize/confirm/revert operations → API-P only, OPS not wired | Nova resize actions → — | state/409/replay/auto-confirm tests → — | real resize → — | Missing |
| IM-025 | Instance console: short-lived noVNC, expiry/reconnect/fullscreen/keyboard | Compute | Project | noVNC surface and expiry → — | console issuance with no-store/no persistence → API-P only | Nova remote-console call → — | token/log/expiry/policy tests → — | real browser console → — | Missing |
| IM-026 | Instance delete preview, exact-name confirmation, retention outcomes, normal/force delete | Compute | Both | row/danger zone and dependency outcomes → — | preview + separate idempotent delete/force-delete → API-P only for normal delete | Nova delete and policy/state handling → — | dependency/403/409/replay tests → — | real delete → — | Missing |
| IM-027 | Image inventory with visibility/minimums/filter/pagination | Image | Project | list/filter/visibility → UI-P, UI-G | `/images` schema → API-R, BFF, CUR | Glance bounded list → SDK, FAKE | filters/page/request IDs/errors → T-P | frontend automated evidence; recorded browser walkthrough → — | Implemented |
| IM-028 | Image upload/import/URL, edit/properties/tags/protection/visibility/members/actions/delete | Image | Both | CRUD/settings/access/actions → — | Glance mutation contracts → — | Glance import/member/action APIs → — | capability/policy/async tests → — | real Glance → — | Missing |
| IM-029 | Flavor allowed inventory for provisioning | Compute | Project | selectable/list inventory → no routed Flavor surface | `/flavors` read schema → API-R, BFF, CUR | project-allowed bounded Nova list → SDK, FAKE | bounded/filter/error tests → T-P | direct API local only → — | Partial |
| IM-030 | Flavor admin CRUD, immutable sizing clone, extra specs and private project access | Compute/Admin | Admin | create/clone/settings/extra-spec/access/delete → — | admin flavor contracts → — | Nova Flavor APIs → — | immutable/policy/access tests → — | real admin Nova → — | Missing |
| IM-031 | Key-pair inventory with exact name/type/fingerprint/public key | Compute | Project | list/filter/page → UI-P, UI-G | `/keypairs` read schema → API-R, BFF, CUR | bounded Nova list → SDK, FAKE | bounded/filter/request ID tests → T-P | frontend automated evidence; real Nova → — | Implemented |
| IM-032 | Key-pair generate/import, one-time private-key presentation/download, delete | Compute | Project | generate/import modal, one-time copy/download, exact-name delete → — | synchronous secret response and delete contract → API-P only | Nova key-pair create/delete and microversions → — | non-retention/replay/policy tests → OPS unit only, not key-pair route | real key-pair lifecycle → — | Missing |
| IM-033 | Cross-project instances, owner/project context, admin lifecycle/migrate/evacuate/force delete | Compute/Admin | Admin | separate admin fleet surface → — | all-projects bounded endpoints and explicit scope → — | Nova admin APIs → — | cross-project leakage/policy/large-fleet tests → — | real admin Nova → — | Missing |
| IM-034 | Hypervisors, host aggregates, Placement classes/traits/inventory | Compute/Admin | Admin | dedicated admin routes → — | admin compute/Placement contracts → — | Nova/Placement adapters → — | catalog/policy/pagination tests → — | real admin cloud → — | Missing |

## 3. Networking, NIC/IP/MAC, QoS/RBAC, and Octavia

| ID | Requirement | Owner | Scope | UI evidence needed → current | BFF/API evidence needed → current | Adapter/upstream evidence needed → current | Automated test evidence needed → current | Runtime/manual evidence needed → current | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-035 | Network inventory for provisioning | Network | Project | network selector/list → — | `/networks` bounded read → API-R, BFF, CUR | Neutron bounded list → SDK, FAKE | bounded/filter/policy tests → T-P | direct API local only → — | Partial |
| IM-036 | Network CRUD: shared/external/provider/MTU/DNS/QoS/port-security/tags | Network | Both | list/detail/create/settings/delete → — | network CRUD schemas → — | Neutron networks/extensions → — | capability/revision/policy tests → — | real Neutron → — | Missing |
| IM-037 | Subnet CRUD: pools/DNS/routes/IP modes/subnet pools/segments/service types | Network | Both | list/detail/row editors/delete → — | subnet CRUD schemas → — | Neutron subnets/extensions → — | validation/revision/dependency tests → — | real Neutron → — | Missing |
| IM-038 | Port CRUD and NIC attach/detach | Network/Compute | Both | port list/detail and attach/detach confirmation → — | port and interface mutation routes → API-P only | Neutron port/Nova interface calls → — | 403/409/idempotency/state tests → — | real Nova/Neutron → — | Missing |
| IM-039 | Port fixed-IP, MAC, SG, allowed-address-pair, DNS, QoS, binding/vNIC/host edits | Network | Both | capability-aware row editors → — | PATCH descriptors and revision guard → API-P only | Neutron extension-aware update → — | MAC/IP/revision/policy tests → — | real extension matrix → — | Missing |
| IM-040 | Router CRUD, interfaces, routes, gateway/SNAT, HA/distributed/NDP/QoS/BFD/ECMP | Network | Both | list/detail/settings/relationship/delete → — | router contracts → — | Neutron L3/extensions → — | dependency/revision/policy tests → — | real Neutron → — | Missing |
| IM-041 | Floating IP list/allocate/associate/move/disassociate/release with explicit port/fixed IP | Network | Project | inventory and distinct confirmations → — | FIP routes → API-P only | Neutron Floating IP API → — | ambiguity/409/replay/release tests → — | real Neutron → — | Missing |
| IM-042 | Security-group inventory for provisioning | Network | Project | selector/list → — | `/security-groups` bounded read → API-R, BFF, CUR | Neutron bounded list → SDK, FAKE | bounded/filter/policy tests → T-P | direct API local only → — | Partial |
| IM-043 | Security-group/rule CRUD incl. stateful, remote group/CIDR/address group | Network | Both | group/rule editors and dependencies → — | SG/rule contracts → — | Neutron security-group extensions → — | validation/revision/policy tests → — | real Neutron → — | Missing |
| IM-044 | QoS policy CRUD and all advertised rule types/relationships | Network | Both | policy/rule editors and dependency delete → — | QoS schemas/capabilities → — | Neutron QoS extensions → — | advertised-rule/revision/policy tests → — | real Neutron → — | Missing |
| IM-045 | Neutron RBAC policy list/create/edit-or-replace/delete and target isolation | Network/Admin | Both | access/admin list and confirmations → — | RBAC contracts and explicit owner/target → — | Neutron RBAC API → — | cross-project leak/extension/policy tests → — | real Neutron → — | Missing |
| IM-046 | Octavia LB/listener/pool/member/health-monitor/L7 CRUD and failover states | Load Balancing | Both | catalog-gated service and async states → — | Octavia resource contracts → — | Octavia v2 adapter/capabilities → — | absence/async/403/409 tests → — | cloud with/without Octavia → — | Missing |

## 4. Storage and Cinder administration

| ID | Requirement | Owner | Scope | UI evidence needed → current | BFF/API evidence needed → current | Adapter/upstream evidence needed → current | Automated test evidence needed → current | Runtime/manual evidence needed → current | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-047 | Volume inventory and eligible attachment list | Storage | Project | volume list/filter/page → — | `/volumes` exists only in API-P | Cinder bounded list → — | pagination/policy/state tests → — | real Cinder → — | Missing |
| IM-048 | Volume create from blank/image/snapshot/volume/backup with type/AZ/metadata/hints | Storage | Project | source-specific create/review → — | create schema/idempotent operation → — | Cinder v3 create/capabilities → — | source/quota/403/409 tests → — | non-Ceph and RBD clouds → — | Missing |
| IM-049 | Volume edit/set/unset, bootable/read-only, extend, retype/migrate, transfer | Storage | Both | settings/advanced/actions → — | mutation/action contracts → — | Cinder v3 actions/microversions → — | capability/state/policy tests → — | real backends → — | Missing |
| IM-050 | Volume attach/detach incl. device/tag/delete-on-termination and conflict recovery | Storage/Compute | Project | instance storage relationship → — | attachment routes → API-P only | Nova/Cinder attachment calls → — | intermediate/409/replay tests → — | real attach/detach → — | Missing |
| IM-051 | Volume delete/force-delete with attachment/snapshot/backup dependency preview | Storage | Both | distinct normal/force confirmations → — | preview and separate mutations → — | Cinder delete/actions → — | state/dependency/policy tests → — | real Cinder → — | Missing |
| IM-052 | Snapshot list/create/edit/metadata/unset/delete/force-delete | Storage | Both | list/detail/settings/actions → — | snapshot contracts → — | Cinder snapshot APIs → — | dependency/state/policy tests → — | real Cinder → — | Missing |
| IM-053 | Backup list/full/incremental/from-snapshot/edit/restore/export/import/delete/force | Storage | Both | list/detail/create/actions → — | backup contracts → — | Cinder backup APIs → — | capability/intermediate/failure tests → — | cloud with backup service → — | Missing |
| IM-054 | Project-visible volume types and capability/default presentation | Storage | Project | type selector/details → — | project type/default endpoints → — | Cinder type/default APIs → — | visibility/default tests → — | real multi-backend Cinder → — | Missing |
| IM-055 | Admin volume types: visibility/access/extra specs/encryption/flags/delete | Storage/Admin | Admin | settings/extra-spec/access/encryption → — | admin type contracts → — | Cinder type/access/encryption APIs → — | in-use/default/policy tests → — | real admin Cinder → — | Missing |
| IM-056 | Admin QoS specs: properties, consumer, type association, normal/force delete | Storage/Admin | Admin | QoS spec CRUD/relationships → — | admin QoS contracts → — | Cinder QoS APIs → — | association/policy/conflict tests → — | real admin Cinder → — | Missing |
| IM-057 | Backend/service/pool discovery and gated enable/disable/freeze/thaw/failover; no fake CRUD | Storage/Admin | Admin | read-only backend and service actions → — | admin backend/service contracts → — | Cinder scheduler/service capabilities → — | no-fake-CRUD/capability/policy tests → — | LVM and RBD matrices → — | Missing |

## 5. Keystone identity, authorization, and administration

| ID | Requirement | Owner | Scope | UI evidence needed → current | BFF/API evidence needed → current | Adapter/upstream evidence needed → current | Automated test evidence needed → current | Runtime/manual evidence needed → current | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-058 | Explicit SYSTEM/DOMAIN/PROJECT administrator scope and separate navigation | Identity/Admin | Admin | scope badge/workspace separation → — | admin session/scope contracts → — | Keystone scoped tokens → — | role-name bypass/scope leak tests → — | real admin Keystone → — | Missing |
| IM-059 | Domain list/detail/create/edit/delete where supported | Identity/Admin | Admin | dedicated domain surfaces → — | domain contracts → — | Keystone v3 domains → — | policy/dependency tests → — | real Keystone → — | Missing |
| IM-060 | Project list/detail/create/edit/enable-disable/delete with domain/hierarchy | Identity/Admin | Admin | dedicated project workflows → — | admin project contracts → — | Keystone v3 projects/extensions → — | 403/409/hierarchy/dependency tests → — | real Keystone → — | Missing |
| IM-061 | Users CRUD, enable/default project, password and application-credential boundaries | Identity/Admin | Admin | settings/access/sensitive flows → — | user/credential contracts → — | Keystone v3 users/application credentials → — | secret/non-disclosure/policy tests → — | real Keystone → — | Missing |
| IM-062 | Groups CRUD and add/remove user membership | Identity/Admin | Admin | group/member relationships → — | group/membership contracts → — | Keystone v3 groups → — | membership conflict/policy tests → — | real Keystone → — | Missing |
| IM-063 | Roles CRUD, implied roles, assignment inspection and protected delete | Identity/Admin | Admin | role/settings/relationships → — | role contracts → — | Keystone v3 roles/implied roles → — | dependency/policy tests → — | real Keystone → — | Missing |
| IM-064 | Role assignments grant/revoke for user/group at system/domain/project, inherited scope | Identity/Admin | Admin | assignment editor and high-impact revoke → — | assignment contracts/filters → — | Keystone role-assignment and OS-INHERIT APIs → — | effective/inherited/policy tests → — | real Keystone → — | Missing |
| IM-065 | Project memberships keep identity deletion distinct from revoke/remove | Identity/Admin | Admin | relationship-specific confirmations → — | membership relationship endpoints → — | Keystone grant/revoke APIs → — | identity-retention tests → — | real Keystone → — | Missing |
| IM-066 | Policy/RBAC capability registry and resource field/action descriptors | Platform/AuthZ | Both | visible immutable/capability/policy/state reasons → — | `/resource-contracts` is API-P only | discovery/microversion/extension policy hints → — | descriptor reconciliation tests → — | real policy matrices → — | Missing |
| IM-067 | No shared administrator impersonation or privilege retry | Security | Both | no client role escalation → implemented project UI only | all project routes derive server scope → BFF, SEC; no admin routes | SDK uses session auth context → SDK | isolation/403 tests → T-S, T-Q, T-I, T-P | local fake only → V-1, V-Q, V-I; admin workspace → — | Partial |

## 6. BFF, security, operation, and compatibility boundaries

| ID | Requirement | Owner | Scope | UI evidence needed → current | BFF/API evidence needed → current | Adapter/upstream evidence needed → current | Automated test evidence needed → current | Runtime/manual evidence needed → current | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-068 | Browser calls only same-origin FastAPI BFF; no OpenStack endpoints/tokens in browser | Security | Both | API client only uses `/api/v1` → UI-A | same-origin routes/no-store/token-shaped response exclusions → API-R, BFF, SEC | credentials/tokens stay in adapter/session → SDK | token/cookie/static-origin tests → T-S | local fake → V-1; production ingress → — | Implemented |
| IM-069 | `HttpOnly; Secure; SameSite=Lax` opaque cookie and memory-only CSRF | Security | Both | CSRF kept by API client memory → UI-A | cookie flags and CSRF dependency on mutations → API-R, BFF, SEC | no upstream concern → n/a | cookie and missing/invalid CSRF tests → T-S | local test client → V-1; TLS browser → — | Implemented |
| IM-070 | Idempotency: scope-bound key, exact replay, payload conflict, in-progress/failed replay | Platform | Both | stable key and duplicate-disabled mutations → — | store/fingerprint/state machine exists but no runtime mutation route → OPS; API-P headers only | no mutation adapter integration → — | store concurrency/replay/conflict/secret tests → T-O | no end-to-end runtime evidence → — | Partial |
| IM-071 | Operation retrieval isolated by user+project+region; accepted/running/terminal/request IDs | Platform | Both | operation polling/history → — | store isolation exists; `/operations/{id}` only API-P, not runtime → OPS | no upstream mutation wiring → — | store visibility/transitions/request IDs → T-O | no endpoint/manual flow → — | Partial |
| IM-072 | Preserve upstream OpenStack request IDs and distinct 401/403/404/409/429/5xx | Platform | Both | reference shown on implemented error surfaces → UI-A, UI-I, UI-P | normalized problem/trace schemas → API-R, BFF | header/exception extraction → SDK | T-S, T-Q, T-I, T-P, T-A | local fake/exception paths → V-1, V-I; full mutation scope → — | Partial |
| IM-073 | Catalog endpoint discovery, region/interface selection, no hard-coded topology | Platform | Both | capability-driven navigation → implemented shell only | catalog retained server-side → SEC | SDK connection uses catalog/region/interface → SDK | connection-boundary tests → T-A | live catalog/interface/multi-region → — | Unverified |
| IM-074 | `openstacksdk` normalization and call-level microversion/capability negotiation | Platform | Both | capability-gated fields/actions → — | no runtime resource registry → — | SDK read adapters exist; mutation negotiation absent → SDK | read normalization/connection tests → T-A, T-Q, T-I, T-P | live 2026.1 capability matrix → — | Partial |
| IM-075 | Server-side filtering/pagination; upstream markers/cursors never reach browser | Platform | Both | page numbers only → UI-A, UI-I, UI-P, UI-G | scope/query-bound cursor chain → BFF, CUR | bounded SDK reads for implemented lists → SDK | 1k/10k and marker tests → T-I, T-P | implemented lists → V-I; all resources/admin → — | Partial |
| IM-076 | Sensitive data exclusion: credentials/tokens/private keys/user-data/noVNC URLs/logs/errors/cache | Security | Both | no sensitive browser persistence for implemented auth → UI-A | session/operation no-secret structures → SEC, OPS | auth adapter boundary → SDK | login and operation-secret tests → T-S, T-O | private-key/user-data/noVNC flows absent → — | Partial |
| IM-077 | Durable shared session/cursor/operation/rate-limit stores for multi-worker deployment | Platform | Both | transparent to UI → n/a | protocols exist; memory implementations only → SEC, CUR, OPS | n/a | atomic in-memory tests → T-S, T-I, T-O | multi-worker/HA deployment → — | Unverified |
| IM-078 | Policy `403` authoritative; no cached/role-name authorization or admin retry | Security | Both | distinct permission state on implemented reads → UI-A, UI-I, UI-P | normalized 403 and active scope → BFF | upstream policy result preserved → SDK | T-S, T-Q, T-I, T-P | local injected failures → V-Q, V-I; real policies → — | Partial |
| IM-079 | Catalog and API capability administration/diagnostics | Platform/Admin | Admin | service/version/extension/capability inventory → — | catalog/capability admin endpoints → — | service catalog and discovery adapters → SDK retains catalog but has no diagnostics API | catalog variation/policy tests → — | real multi-service catalog → — | Partial |
| IM-080 | Project API access and settings without exposing server-held tokens | Platform | Project | endpoint/capability-safe access guidance and project preferences → — | safe metadata/preferences/download contracts → — | catalog-derived public metadata only → — | token non-disclosure/download tests → — | real cloud/browser → — | Missing |
| IM-081 | Default quota administration distinct from project overrides | Quota/Admin | Admin | provider default/effective/override views → — | default-quota read/update contracts → — | Nova/Neutron/Cinder default quota APIs → — | default/unlimited/policy tests → — | real admin cloud → — | Missing |
| IM-082 | Heat orchestration when catalog/capability discovered | Orchestration | Both | stack/template/resource/event workflows → — | Heat contracts → — | Orchestration adapter → — | absence/policy/async/failure tests → — | cloud with/without Heat → — | Missing |
| IM-083 | Swift object storage when catalog/capability discovered | Object Storage | Both | container/object lifecycle and metadata → — | Swift contracts → — | Object Store adapter → — | absence/policy/pagination/large-object tests → — | cloud with/without Swift → — | Missing |
| IM-084 | Optional audit and observability integrations | Operations/Admin | Admin | opt-in event/audit surfaces → — | integration contracts and scope controls → — | discovered/configured integration adapters → — | redaction/failure/isolation tests → — | deployed integrations → — | Missing |

## 7. Performance, deployment, and release verification

| ID | Requirement | Owner | Scope | UI evidence needed → current | BFF/API evidence needed → current | Adapter/upstream evidence needed → current | Automated test evidence needed → current | Runtime/manual evidence needed → current | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IM-085 | First useful project view p75 ≤1.5 s and cached route p95 ≤300 ms | Performance | Both | RUM instrumentation/results → — | trace correlation → partial BFF trace only | measured upstream timing → — | performance gate → — | 30 cold/100 warm per profile → — | Unverified |
| IM-086 | Overview p95 ≤800 ms, list p95 ≤600 ms, mutation ack ≤300 ms | Performance | Both | browser timing → — | BFF latency metrics → — | upstream timing/capacity → SDK capacity bound exists | load/perf suite → — | reference-cloud measurements → — | Unverified |
| IM-087 | Partial dependency failure causes zero full-page blocks | Performance | Both | widget/list scoped failures → UI-A on quota, UI-I/UI-P read errors | concurrent quota deadlines → BFF | source-specific timeouts → SDK | timeout/failure tests → T-Q, T-I, T-P | local quota evidence → V-Q; full service matrix → — | Partial |
| IM-088 | Lab-small, project-1k, fleet-10k and multi-region workload matrix | Performance | Both | usable interaction at scale → partial synthetic UI only | bounded request behavior → BFF, CUR | one-page reads → SDK | 1k/10k bounded instance tests → T-I | full concurrency/network profiles → — | Unverified |
| IM-089 | Real OpenStack 2026.1 verification across Keystone/Nova/Glance/Neutron/Cinder | Release | Both | browser walkthrough → — | deployed BFF contract → — | live service calls/catalog/microversions → — | smoke/contract suite against cloud → — | explicitly not claimed by V-1, V-Q, V-I | Unverified |
| IM-090 | Deployment neutrality: converged/separated, non-Ceph and RBD, single/multi-region | Release | Both | same UX without backend branches → incomplete product | backend-neutral read models partly exist → BFF | topology/backend variants → — | deployment matrix → — | lab + representative variants → — | Unverified |
| IM-091 | Browser verification: Chromium/Firefox/WebKit, desktop/tablet/mobile, EN/KO, keyboard/a11y | UX/QA | Both | all routes/states across browsers → partial implemented-route evidence | n/a | n/a | one React test environment → UI-A | Chromium-like local viewports only → V-1, V-Q, V-I | Unverified |
| IM-092 | Failure injection: slow/error/expired/403/409/429/5xx and recovery without leakage | Release | Both | recovery states → partial implemented reads | normalized failures → BFF | injected upstream behavior → FAKE, SDK errors | unit/API coverage for implemented reads → T-S, T-Q, T-I, T-P | reference-cloud fault injection → — | Unverified |
| IM-093 | Runtime OpenAPI parity, schema/reference validity and internal Markdown links | Release | Both | client types/routes align → UI-A, UI-I, UI-P | runtime routes exactly match API-R; API-P remains non-runtime | adapter signatures align with implemented reads → SDK | contract validator/parity test → T-C | local validation required for this commit | Implemented |

## Official OpenStack 2026.1 anchors

Repository wording was checked against primary OpenStack documentation where
operation breadth or semantics were ambiguous:

- [OpenStackClient 2026.1 server commands](https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/server.html)
  confirms the broader create/set/unset/action surface, interface and volume
  relationship commands, and explicit resize confirm/revert.
- [OpenStackClient 2026.1 Flavor commands](https://docs.openstack.org/python-openstackclient/2026.1/cli/command-objects/flavor.html)
  is the command baseline for immutable sizing, extra specs, and project
  access.
- [Compute API reference](https://docs.openstack.org/api-ref/compute/)
  is the authoritative Nova server, action, key-pair, Flavor, attachment, and
  remote-console API reference.
- [Networking API v2](https://docs.openstack.org/api-ref/network/v2/index.html)
  covers networks, subnets, ports, routers, Floating IPs, security groups,
  QoS, RBAC, revision conflicts, tags, and extension-gated attributes.
- [Octavia API v2](https://docs.openstack.org/api-ref/load-balancer/v2/)
  confirms the load balancer/listener/pool/member model and asynchronous
  `provisioning_status` behavior.
- [Block Storage API v3](https://docs.openstack.org/api-ref/block-storage/v3/)
  covers volumes, snapshots, backups, types, QoS, services, scheduler pools,
  action states, and microversion-dependent behavior.
- [Identity API v3](https://docs.openstack.org/api-ref/identity/v3/)
  covers projects, users, groups, roles, system/domain/project assignments,
  effective assignment filters, and inherited-role relationships.
- [openstacksdk microversion guidance](https://docs.openstack.org/openstacksdk/latest/user/microversions)
  defines SDK call-level negotiation behavior.
- [Keystone service catalog administration](https://docs.openstack.org/keystone/latest/admin/manage-services.html)
  is the endpoint discovery baseline.

## Audit summary

The baseline implements a secure project-user foundation plus quota reads,
Nova instance inventory/detail, Glance image inventory, and key-pair inventory.
Flavor, network, and security-group read APIs exist without complete routed UI.
The operation/idempotency store is unit-tested but not exposed by a runtime
operation endpoint and is not connected to mutations. Goals 2–4 remain
documentation/design scope with no product runtime routes.

Status counts are generated from the rows above during validation; the checked
commit must report the same values as the final audit output.
