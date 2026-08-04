from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from vantage_bff.adapters.base import AdapterError
from vantage_bff.storage.models import QosSpec, StoragePool, StorageResourceKind, Volume
from vantage_bff.storage.openstack_sdk import OpenStackSdkStorageAdapter


class ImmediateRunner:
    async def run(self, function: Any, /, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)


class RecordingProxy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def volumes(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("volumes", (), kwargs))
        return [
            {
                "id": "volume-1",
                "name": "data",
                "status": "available",
                "size": 20,
                "volume_type": "fast",
                "availability_zone": "nova",
                "bootable": "true",
                "encrypted": False,
                "multiattach": False,
                "metadata": {"tier": "gold"},
                "attachments": [],
                "project_id": "project-alpha",
                "created_at": "2026-08-04T00:00:00Z",
            }
        ]

    def backend_pools(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("backend_pools", (), kwargs))
        return [
            {
                "name": "host@rbd#volumes",
                "capabilities": {
                    "volume_backend_name": "rbd",
                    "free_capacity_gb": 100,
                    "driver_version": "ceph",
                    "vendor_name": "Open Source",
                },
            }
        ]

    def create_transfer(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_transfer", (), kwargs))
        return {"id": "transfer-1", "auth_key": "one-time-key"}

    def create_qos_spec(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(("create_qos_spec", (), kwargs))
        return SimpleNamespace(id="qos-1", name=kwargs["name"])

    def associate_qos_spec(self, *args: Any) -> None:
        self.calls.append(("associate_qos_spec", args, {}))

    def qos_specs(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("qos_specs", (), kwargs))
        return [{"id": "qos-1", "name": "gold", "consumer": "both", "read_iops_sec": "500"}]


class RecordingCompute:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def create_volume_attachment(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_volume_attachment", args, kwargs))
        return {"id": "attachment-1"}


def adapter_for(proxy: Any, compute: Any | None = None) -> OpenStackSdkStorageAdapter:
    connection = SimpleNamespace(block_storage=proxy, compute=compute or RecordingCompute())
    return OpenStackSdkStorageAdapter(ImmediateRunner(), lambda *_args, **_kwargs: connection, 3)


@pytest.mark.asyncio
async def test_sdk_list_preserves_marker_filters_sort_request_id_and_normalizes_volume() -> None:
    proxy = RecordingProxy()
    adapter = adapter_for(proxy)
    result = await adapter.list_resources(
        {"scoped_token": "secret", "project_id": "project-alpha", "region": "RegionOne"},
        "project-alpha",
        "RegionOne",
        StorageResourceKind.VOLUME,
        limit=26,
        marker="volume-0",
        filters={"name": "data", "status": "available"},
        sort="created_at",
        direction="desc",
    )
    assert result.request_id and result.request_id.startswith("req-")
    assert result.has_next is False
    volume = result.items[0]
    assert isinstance(volume, Volume)
    assert volume.metadata == {"tier": "gold"}
    assert volume.bootable is True
    assert proxy.calls == [
        (
            "volumes",
            (),
            {
                "details": True,
                "name": "data",
                "status": "available",
                "marker": "volume-0",
                "limit": 26,
                "sort": "created_at:desc",
            },
        )
    ]


@pytest.mark.asyncio
async def test_sdk_backend_capabilities_remain_backend_neutral_and_ceph_visible() -> None:
    result = await adapter_for(RecordingProxy()).list_resources(
        {},
        "project-alpha",
        "RegionOne",
        StorageResourceKind.POOL,
        limit=25,
        marker=None,
        filters={},
        sort="name",
        direction="asc",
        all_projects=True,
    )
    pool = result.items[0]
    assert isinstance(pool, StoragePool)
    assert pool.backend == "rbd"
    assert pool.capabilities["driver_version"] == "ceph"


@pytest.mark.asyncio
async def test_sdk_attach_uses_nova_and_transfer_secret_is_only_immediate_body() -> None:
    proxy = RecordingProxy()
    compute = RecordingCompute()
    adapter = adapter_for(proxy, compute)
    auth = {"scoped_token": "secret", "project_id": "project-alpha", "region": "RegionOne"}
    attached = await adapter.mutate(
        auth,
        "project-alpha",
        "RegionOne",
        StorageResourceKind.VOLUME,
        "attach",
        "volume-1",
        {"server_id": "server-1", "device": "/dev/vdb"},
    )
    transfer = await adapter.mutate(
        auth,
        "project-alpha",
        "RegionOne",
        StorageResourceKind.VOLUME,
        "create_transfer",
        "volume-1",
        {},
    )
    assert attached.resource_id == "attachment-1"
    assert compute.calls[0][0] == "create_volume_attachment"
    assert transfer.body == {"id": "transfer-1", "auth_key": "one-time-key"}
    assert proxy.calls[-1] == ("create_transfer", (), {"volume_id": "volume-1", "name": None})


@pytest.mark.asyncio
async def test_sdk_qos_uses_current_openstacksdk_method_contract() -> None:
    proxy = RecordingProxy()
    adapter = adapter_for(proxy)
    auth = {"scoped_token": "secret", "project_id": "project-alpha", "region": "RegionOne"}
    result = await adapter.mutate(
        auth,
        "project-alpha",
        "RegionOne",
        StorageResourceKind.QOS_SPEC,
        "create",
        None,
        {
            "name": "gold",
            "consumer": "both",
            "specs": {"read_iops_sec": "500"},
            "associate_volume_type_ids": ["type-fast"],
        },
    )
    listed = await adapter.list_resources(
        auth,
        "project-alpha",
        "RegionOne",
        StorageResourceKind.QOS_SPEC,
        limit=25,
        marker=None,
        filters={},
        sort="name",
        direction="asc",
        all_projects=True,
    )
    assert result.resource_id == "qos-1"
    assert proxy.calls[1] == ("associate_qos_spec", ("qos-1", "type-fast"), {})
    assert isinstance(listed.items[0], QosSpec)
    assert listed.items[0].specs == {"read_iops_sec": "500"}


class ForbiddenProxy:
    def volumes(self, **_kwargs: Any) -> list[Any]:
        response = SimpleNamespace(
            status_code=403, headers={"x-openstack-request-id": "req-policy"}
        )
        failure = RuntimeError("forbidden")
        failure.response = response  # type: ignore[attr-defined]
        raise failure


@pytest.mark.asyncio
async def test_sdk_failure_preserves_policy_status_and_request_id() -> None:
    with pytest.raises(AdapterError) as captured:
        await adapter_for(ForbiddenProxy()).list_resources(
            {},
            "project-alpha",
            "RegionOne",
            StorageResourceKind.VOLUME,
            limit=25,
            marker=None,
            filters={},
            sort="created_at",
            direction="desc",
        )
    assert captured.value.status_code == 403
    assert captured.value.request_id == "req-policy"
