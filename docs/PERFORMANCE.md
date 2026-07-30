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
- Do not start the next goal while the current goal exceeds its SLO.
