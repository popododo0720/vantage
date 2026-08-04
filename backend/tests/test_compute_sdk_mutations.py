import base64
from types import SimpleNamespace
from typing import Any

import pytest
from vantage_bff.adapters.openstack_sdk import OpenStackSdkAdapter


def adapter_with(connection: Any, monkeypatch: pytest.MonkeyPatch) -> OpenStackSdkAdapter:
    adapter = OpenStackSdkAdapter("https://keystone.example/v3", "internal", "RegionOne", 15)
    monkeypatch.setattr(adapter, "_project_connection", lambda *_args: connection)
    monkeypatch.setattr(
        adapter,
        "_wait_for_server_state",
        lambda _compute, server, *_args, **_kwargs: server,
    )
    monkeypatch.setattr(adapter, "_wait_for_server_delete", lambda *_args: None)
    return adapter


def test_create_server_maps_volume_boot_network_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_calls: list[dict[str, Any]] = []
    port_calls: list[dict[str, Any]] = []
    compute = SimpleNamespace(
        create_server=lambda **attrs: (
            server_calls.append(attrs) or SimpleNamespace(id="server-1", name="vm")
        )
    )
    network = SimpleNamespace(
        create_port=lambda **attrs: port_calls.append(attrs) or SimpleNamespace(id="port-created")
    )
    adapter = adapter_with(SimpleNamespace(compute=compute, network=network), monkeypatch)

    result = adapter._create_instances(
        {"scoped_token": "token"},
        "project-1",
        "RegionOne",
        {
            "name": "vm",
            "count": 2,
            "flavor_id": "m1.small",
            "boot_source": {
                "type": "image",
                "image_id": "image-1",
                "create_boot_volume": True,
                "volume_size_gib": 20,
                "delete_on_termination": True,
            },
            "networks": [{"network_id": "network-1", "subnet_id": "subnet-1"}],
            "security_group_ids": ["sg-1"],
            "metadata": {"owner": "team"},
            "config_drive": True,
            "user_data": "#!/bin/sh\necho secret",
            "block_devices": [],
        },
    )

    assert result.resource_id == "server-1"
    assert port_calls == [
        {
            "network_id": "network-1",
            "fixed_ips": [{"subnet_id": "subnet-1"}],
            "security_group_ids": ["sg-1"],
        }
    ]
    assert server_calls[0]["networks"] == [{"port": "port-created"}]
    assert server_calls[0]["min_count"] == server_calls[0]["max_count"] == 2
    assert server_calls[0]["user_data"] == base64.b64encode(b"#!/bin/sh\necho secret").decode(
        "ascii"
    )
    assert server_calls[0]["block_device_mapping_v2"] == [
        {
            "source_type": "image",
            "uuid": "image-1",
            "destination_type": "volume",
            "boot_index": 0,
            "delete_on_termination": True,
            "volume_size": 20,
        }
    ]


@pytest.mark.parametrize(
    ("action", "method", "payload", "expected_args"),
    [
        ("start", "start_server", {}, ("server-1",)),
        ("stop", "stop_server", {}, ("server-1",)),
        ("pause", "pause_server", {}, ("server-1",)),
        ("unpause", "unpause_server", {}, ("server-1",)),
        ("suspend", "suspend_server", {}, ("server-1",)),
        ("resume", "resume_server", {}, ("server-1",)),
        ("shelve", "shelve_server", {}, ("server-1",)),
        ("unshelve", "unshelve_server", {}, ("server-1",)),
        ("unrescue", "unrescue_server", {}, ("server-1",)),
        ("unlock", "unlock_server", {}, ("server-1",)),
        ("resize_confirm", "confirm_server_resize", {}, ("server-1",)),
        ("resize_revert", "revert_server_resize", {}, ("server-1",)),
        ("soft_reboot", "reboot_server", {}, ("server-1", "SOFT")),
        ("hard_reboot", "reboot_server", {}, ("server-1", "HARD")),
        ("resize", "resize_server", {"flavor_id": "m1.large"}, ("server-1", "m1.large")),
    ],
)
def test_lifecycle_action_uses_sdk_proxy(
    action: str,
    method: str,
    payload: dict[str, Any],
    expected_args: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class Compute:
        def get_server(self, server: Any) -> Any:
            return server if not isinstance(server, str) else SimpleNamespace(id=server)

        def __getattr__(self, name: str) -> Any:
            return lambda *args, **kwargs: calls.append((name, args, kwargs))

    adapter = adapter_with(SimpleNamespace(compute=Compute()), monkeypatch)
    adapter._instance_action(
        {"scoped_token": "token"}, "project-1", "RegionOne", "server-1", action, payload
    )
    actual = calls[0]
    assert actual[0] == method
    assert tuple(getattr(value, "id", value) for value in actual[1]) == expected_args
    assert actual[2] == {}


def test_rebuild_encodes_user_data(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    server = SimpleNamespace(id="server-1")
    compute = SimpleNamespace(
        get_server=lambda _server: server,
        rebuild_server=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    adapter = adapter_with(SimpleNamespace(compute=compute), monkeypatch)

    adapter._instance_action(
        {"scoped_token": "token"},
        "project-1",
        "RegionOne",
        "server-1",
        "rebuild",
        {"image_id": "image-2", "user_data": "secret", "preserve_ephemeral": True},
    )

    assert calls == [
        (
            (server, "image-2"),
            {
                "user_data": base64.b64encode(b"secret").decode("ascii"),
                "preserve_ephemeral": True,
            },
        )
    ]


def test_image_property_removal_uses_escaped_json_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patches: list[tuple[Any, ...]] = []
    current = SimpleNamespace(
        patch=lambda *args, **kwargs: patches.append((args, kwargs)),
    )
    image = SimpleNamespace(
        update_image=lambda *_args, **_kwargs: SimpleNamespace(id="image-1"),
        get_image=lambda _image_id: current,
    )
    adapter = adapter_with(SimpleNamespace(image=image), monkeypatch)

    adapter._image_mutation(
        {"scoped_token": "token"},
        "project-1",
        "RegionOne",
        "update",
        "image-1",
        {"name": "renamed", "unset_properties": ["hw/foo~bar"]},
    )

    assert patches == [
        (
            (image, [{"op": "remove", "path": "/hw~1foo~0bar"}]),
            {
                "prepend_key": False,
            },
        )
    ]


def test_flavor_crud_specs_and_access_use_sdk_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class Compute:
        def create_flavor(self, **attrs: Any) -> Any:
            calls.append(("create_flavor", (), attrs))
            return SimpleNamespace(id="flavor-1")

        def __getattr__(self, name: str) -> Any:
            return lambda *args, **kwargs: calls.append((name, args, kwargs))

    adapter = adapter_with(SimpleNamespace(compute=Compute()), monkeypatch)
    adapter._flavor_mutation(
        {"scoped_token": "token"},
        "project-1",
        "RegionOne",
        "create",
        None,
        {
            "name": "m1.product",
            "vcpus": 2,
            "ram_mib": 4096,
            "disk_gib": 20,
            "is_public": False,
            "extra_specs": {"hw:cpu_policy": "dedicated"},
            "access_project_ids": ["tenant-1"],
        },
    )

    assert calls[0][0] == "create_flavor"
    assert calls[0][2]["ram"] == 4096
    assert calls[1:] == [
        ("create_flavor_extra_specs", ("flavor-1", {"hw:cpu_policy": "dedicated"}), {}),
        ("flavor_add_tenant_access", ("flavor-1", "tenant-1"), {}),
    ]


def test_operation_wait_observes_status_and_requested_resize_flavor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vantage_bff.adapters.openstack_sdk as sdk_module

    resources = iter(
        [
            SimpleNamespace(status="RESIZE", flavor={"id": "m1.small"}),
            SimpleNamespace(status="ACTIVE", flavor={"id": "m1.large"}),
        ]
    )
    compute = SimpleNamespace(get_server=lambda _server: next(resources))
    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3",
        "internal",
        "RegionOne",
        15,
        operation_timeout_seconds=10,
    )
    monkeypatch.setattr(sdk_module.time, "sleep", lambda _seconds: None)

    result = adapter._wait_for_server_state(
        compute,
        SimpleNamespace(id="server-1"),
        {"VERIFY_RESIZE", "ACTIVE"},
        flavor_id="m1.large",
    )

    assert result.status == "ACTIVE"
