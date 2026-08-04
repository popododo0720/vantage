# ADR 0002: Idempotent Operation Boundary

Status: accepted for staged implementation

## Context

Vantage mutations span Nova, Neutron, Glance, Cinder, and Keystone. Many calls
return before a resource reaches its final state, and a browser can repeat a
submission after a timeout, reload, or network interruption. Retrying a raw
OpenStack create or relationship call can create duplicate resources or apply
the same action twice.

Mutation requests can also contain sensitive fields such as instance user data,
an administrator password, or generated key material. Operation tracking must
not turn those values into logs, caches, or history records.

## Decision

- Every state-changing resource request that can safely be represented as an
  asynchronous command requires an `Idempotency-Key` and returns a Vantage
  operation.
- The idempotency namespace is the signed-in user, active project, and region.
  Reusing a key in that namespace with the same operation kind and canonical
  request body returns the original operation. Reusing it with different input
  returns `409 Conflict` before another OpenStack call is made.
- Vantage stores a SHA-256 request fingerprint, never the request body. Secrets
  and tokens are therefore absent from operation state and idempotency records.
- Operation records contain the target identity, state, Vantage trace ID,
  upstream OpenStack request IDs, and a bounded problem response. They do not
  contain Keystone tokens, service endpoints, console URLs, user data, private
  keys, or raw upstream responses.
- Accepted work transitions through `accepted`, `running`, and one terminal
  state: `succeeded`, `failed`, or `cancelled`. Terminal records expire after a
  configured TTL. No unexpired record can be evicted merely to admit new work,
  because doing so would permit a duplicate mutation; new submissions are
  rejected when the bounded store is full.
- OpenStack policy is authoritative. A policy `403` becomes a failed operation
  with the upstream request ID; the UI never predicts success from navigation
  visibility or a cached capability descriptor.
- Public-key import is the OpenStack 2026.1 default and participates in normal
  operation replay. Explicit Nova 2.10 compatibility generation remains a
  synchronous one-time-secret response. Private material is never copied into
  the operation store, and a replay after successful delivery is rejected
  instead of generating a duplicate or pretending the secret can be recovered.

## Store Boundary

`OperationStore` is a server-side protocol. The in-memory implementation is for
the single-process development and reference path. A multi-worker or
high-availability deployment must use a shared implementation with atomic
key acquisition, state transitions, TTL, and the same no-secret data contract.
The browser only receives operation IDs and never chooses a backing worker.

## Consequences

- All mutation adapters can share one submission and polling contract.
- Browser retries do not duplicate resources, and conflicting reuse is visible.
- Operation history is safe to expose to the owning user in the active scope.
- Durable deployments need a shared operation store before enabling multiple
  BFF workers.
- Reconciliation after a BFF restart still requires querying the authoritative
  OpenStack resource; an in-memory operation record is not a transaction log.

## Upstream Baseline

Nova's [key-pair API](https://docs.openstack.org/api-ref/compute/#keypairs-keypairs)
requires `public_key` from microversion 2.92 onward and documents generated
private material only through 2.91. Vantage therefore keeps import as the
2026.1 default and labels lower-microversion generation as compatibility
behavior rather than an ordinary modern create path.
