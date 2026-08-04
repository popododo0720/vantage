# Performance Contract

Replacing Horizon is successful only if Vantage is materially faster in daily
use. Visual improvement without measurable latency improvement is not enough.

## MVP SLOs

The targets below are release gates, not averages. Browser timings include the
network profile in the reference matrix; BFF timings are measured at the HTTP
boundary and exclude browser rendering.

| Signal | Target | BFF/upstream budget | Measurement |
| --- | ---: | --- | --- |
| Login | p95 <= 2.5 s | Keystone 2.0 s, BFF 100 ms | Browser RUM and BFF metrics |
| Project/region scope switch | p95 <= 1.2 s | Keystone 1.0 s, BFF 100 ms | Browser RUM and BFF metrics |
| First useful project view | p75 <= 1.5 s | shell independent; overview p95 <= 800 ms | Browser RUM, reference-cloud matrix |
| Project overview/dashboard BFF | p95 <= 800 ms | widgets 3.0 s independently, whole response 4.0 s | BFF and upstream metrics |
| First filtered list page | p95 <= 600 ms | service 3.0 s, exactly one bounded request | BFF and upstream metrics |
| Subsequent cursor page | p95 <= 450 ms | cursor lookup 25 ms, service 3.0 s | BFF and upstream metrics |
| Cached route/reference transition | p95 <= 300 ms | cache lookup 25 ms | Browser RUM |
| Mutation acknowledgement | p95 <= 300 ms | durable operation/idempotency write 100 ms | Browser and BFF |
| noVNC bootstrap | p95 <= 2.0 s | Nova console request 1.5 s, BFF 100 ms | Browser and BFF; URL never cached |
| Partial service failure | 0 full-page blocks | independent timeout/error result | Fault injection |

Login, scope switch, mutation acknowledgement, and noVNC are forward-looking
budgets until their complete runtime slices exist. A route is not declared
compliant merely because the common platform can measure it.

## Request Strategy

- Render the application shell independently from OpenStack API calls.
- Fan out overview calls in parallel behind one BFF deadline.
- Give every widget an independent timeout and error state.
- Use stale-while-revalidate only for bounded, project-scoped read data.
- Invalidate relevant cache entries on project switch, logout, and mutation.
- Revalidate on route entry, focus, and task completion.
- Do not add a manual refresh button.

### Instance inventory invariant

- Each Nova list request sends the selected `limit` plus one look-ahead item;
  the BFF returns only the selected page size.
- The adapter issues one Nova `/servers/detail` request and never lets an SDK
  generator follow pagination links for a browser list request. When an
  operator-defined Nova `max_limit` clamps the look-ahead request, Vantage
  honors the response's `servers_links` `rel=next` signal instead of treating
  the short page as the end of the collection.
- The last returned server ID becomes the marker for the next visible page.
  Markers stay in a short-lived scope- and query-bound server map and never
  enter the browser URL or response body.
- Nova does not provide a portable total for this list. Vantage does not run a
  second full-list or count request to manufacture one; numbered controls grow
  progressively as cursor pages are reached.
- Blocking SDK calls share a bounded execution capacity. A timed-out or
  cancelled request keeps its slot until the underlying SDK thread exits, so
  repeated upstream stalls cannot create an unbounded executor queue.

## Initial Timeout Budget

| Dependency | Timeout |
| --- | ---: |
| Session/Keystone | 2 s |
| Nova list/detail | 3 s |
| Neutron list | 3 s |
| Glance/Cinder list | 3 s |
| Entire overview deadline | 4 s |

The values are starting budgets. Goal 1 reference-deployment traces determine
final settings. Results are separated by region distance, cloud scale, and
deployment topology so the first home lab does not define the product envelope.

## Reference Workload Matrix

Each release candidate runs the same matrix. Results are reported separately;
one fast home-lab result cannot hide a slow large-cloud result.

| Profile | Collection shape | Concurrency | Network profile | Required scenarios |
| --- | --- | ---: | --- | --- |
| Lab-small | 100 instances, 100 ports, 100 volumes | 5 active sessions | LAN, <= 2 ms RTT | Cold/warm entry, project switch, normal mutations |
| Project-1k | 1k instances, 2k ports, 1k volumes | 20 active sessions | 20 ms RTT | Filter, sort, page 1/middle/last, task polling |
| Fleet-10k | 10k instances, 20k ports, 10k volumes | 50 active sessions | 50 ms RTT | Bounded pagination, cache isolation, admin list fan-out |
| Multi-region | Project-1k in two regions | 20 active sessions | 20/100 ms RTT | Region switch, independent cache keys, partial region failure |

For every profile:

1. Run at least 30 cold-cache and 100 warm-cache samples per measured route.
2. Record browser TTFB, FCP/LCP, interaction latency, BFF duration, upstream
   service duration, cache state, region, project, page size, and request ID.
3. Run normal, Nova-slow, Neutron-error, Cinder-timeout, Keystone-expired,
   policy-403, and rate-limited scenarios.
4. Verify that list requests never download a complete collection and that
   project/region switches never reuse another scope's rows.
   For Nova inventory, assert one upstream request and at most `limit + 1`
   decoded resources for every browser page.
5. Fail the gate when a profile exceeds an SLO; averages across profiles do not
   convert a failing profile into a pass.

## Cache Rules

Cache keys include:

- user
- project
- region
- service
- negotiated API behavior
- filter and cursor

Never cache:

- passwords or credentials
- Keystone tokens in a browser-accessible cache
- noVNC URLs or tokens
- private keys
- mutation responses as reusable state

The implemented quota-widget cache defaults to 10 seconds and coalesces
identical misses in each BFF worker. Redis shares the successful bounded value
between workers. Keys hash, but logically include, user, project, region,
policy-scope namespace, service, resource, and query behavior. Errors and
timeouts are not cached. Scope switch, logout, and terminal authentication
failure invalidate the old policy-scope index.

Catalog and immutable/reference caches must use the same key builder and an
explicit resource-specific TTL when those adapters are introduced. A cache may
store only shaped JSON, never an SDK object, token-bearing connection, response
header collection, credential, console URL, or private key.

## Observability

Track:

- TTFB, FCP/LCP, and interaction latency by route
- service latency, timeout, and error rate
- cache hit and stale-served rate
- project-switch latency
- `403`, `409`, `429`, and `5xx` rates
- Vantage trace ID to OpenStack request ID correlation
- operation acknowledgement to final-resource-state duration

The BFF exports Prometheus text at `/metrics` using OpenTelemetry-compatible
metric names and bounded labels. `/health/live` proves that the process event
loop is serving; `/health/ready` checks the configured shared platform store.
Readiness does not issue synthetic OpenStack API calls or make a transient
Nova/Neutron failure restart every BFF worker. JSON request logs contain route,
status, latency, Vantage trace ID, and response request ID, but exclude payloads,
cookies, authorization, CSRF values, passwords, tokens, console URLs, and
private keys.

## CI Performance Regression Workload

`backend/tests/test_performance_platform.py` runs without OpenStack and gates:

- parallel overview fan-out (the three quota adapters must be admitted together);
- 20 concurrent cold overview requests coalescing to one call per service;
- cache isolation and invalidation by policy-scope namespace;
- liveness, readiness, Prometheus exposition, and log redaction;
- production configuration rejecting process-local stores.

The instance/provisioning regression suites additionally assert one upstream
request per browser page, `limit + 1` look-ahead, progressive cursor behavior,
and no manufactured total/full collection fetch. CI timings prove algorithmic
behavior, not reference-cloud SLO compliance.

## OpenStack 2026.1 Validation Procedure

1. Deploy at least two BFF workers with Redis and the OpenStack adapter. Confirm
   one session survives requests distributed across both workers and that
   logout/scope switch invalidates both workers' old cursor/cache state.
2. Seed or select each reference-matrix collection shape. Run 30 cold and 100
   warm samples per route with fixed RTT shaping; record p50/p75/p95/p99 rather
   than an aggregate average.
3. Capture `vantage_http_request_duration_seconds`,
   `vantage_upstream_request_duration_seconds`, cache result counters, in-flight
   saturation, browser Web Vitals, Vantage trace IDs, and OpenStack request IDs.
4. Inject Nova slow/error, Neutron 403/429, Cinder timeout, Keystone expiry, and
   Redis loss. Widget failures must remain partial; Redis loss must make
   readiness fail and must not silently fall back to per-process production
   state.
5. Inspect Nova/Neutron/Glance/Cinder access logs for every list sample. Each
   page must send only its supported server-side filters and bounded look-ahead;
   no hidden count or full-list request is allowed.
6. Exercise login, scope switch, mutation acknowledgement, and noVNC only when
   their runtime slices are present. Verify console URLs and tokens are absent
   from Redis, logs, spans, metrics, and error reports.

## Release Gate

- Measure cold and warm cache separately.
- Test normal, Nova-slow, Neutron-error, and Keystone-expired scenarios.
- Exercise 1k and 10k synthetic collection sizes.
- Exercise single- and multi-region latency profiles.
- Do not release the next goal while the current release exceeds its SLO;
  isolated implementation and testing may continue.
