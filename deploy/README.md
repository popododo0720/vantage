# Production container contract

Build from the repository root:

```sh
docker build -f deploy/Dockerfile -t vantage:local .
```

Production requires `VANTAGE_STORE_BACKEND=redis`, a reachable
`VANTAGE_REDIS_URL`, secure cookies, and the OpenStack adapter authentication
URL. Invalid combinations fail during startup; Vantage never falls back to
process memory in production. Put Redis credentials in the deployment secret
manager rather than the image or environment example.

Run more than one worker as separate containers/replicas. Size replicas and
`VANTAGE_OPENSTACK_SDK_THREAD_CAPACITY` together so aggregate concurrency does
not overload Keystone or service APIs. Route `/metrics` to the monitoring
network, use `/health/live` for liveness and `/health/ready` for readiness, and
allow the configured shutdown grace period before sending SIGKILL.

The image and configuration are independent of OpenStack deployment tooling,
storage backend, network backend, node count, and region topology.
