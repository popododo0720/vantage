# Performance Contract

Replacing Horizon is successful only if Vantage is materially faster in daily
use. Visual improvement without measurable latency improvement is not enough.

## MVP SLOs

| Signal | Target | Measurement |
| --- | ---: | --- |
| First useful project view | p75 <= 1.5 s | Browser RUM, reference-cloud matrix |
| Cached route transition | p95 <= 300 ms | Browser RUM |
| Project overview BFF | p95 <= 800 ms | BFF metrics |
| Normal list BFF | p95 <= 600 ms | BFF metrics |
| Mutation acknowledgement | <= 300 ms | Browser and BFF |
| Partial service failure | 0 full-page blocks | Fault injection |

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

## Observability

Track:

- TTFB, FCP/LCP, and interaction latency by route
- service latency, timeout, and error rate
- cache hit and stale-served rate
- project-switch latency
- `403`, `409`, `429`, and `5xx` rates
- Vantage trace ID to OpenStack request ID correlation
- operation acknowledgement to final-resource-state duration

## Release Gate

- Measure cold and warm cache separately.
- Test normal, Nova-slow, Neutron-error, and Keystone-expired scenarios.
- Exercise 1k and 10k synthetic collection sizes.
- Exercise single- and multi-region latency profiles.
- Do not release the next goal while the current release exceeds its SLO;
  isolated implementation and testing may continue.
