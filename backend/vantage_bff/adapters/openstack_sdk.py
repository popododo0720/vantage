from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, ParamSpec, TypeVar, cast
from uuid import UUID, uuid4

from vantage_bff.adapters.base import (
    AdapterError,
    AdapterTimeoutError,
    AuthenticationError,
    AuthResult,
    InstanceListResult,
    ProvisioningListResult,
    ScopeError,
    ScopeResult,
    normalized_quota,
)
from vantage_bff.compute_models import MutationResult, RemoteConsoleResult
from vantage_bff.models import (
    Flavor,
    Image,
    ImageVisibility,
    Instance,
    InstanceDetail,
    InstanceSort,
    InstanceVolume,
    KeyPair,
    KeyPairType,
    Network,
    Project,
    Quota,
    QuotaService,
    QuotaUnit,
    SecurityGroup,
    SortDirection,
    User,
)

_QUOTA_SPECS: dict[QuotaService, tuple[tuple[str, tuple[str, ...], QuotaUnit], ...]] = {
    QuotaService.COMPUTE: (
        ("instances", ("instances",), QuotaUnit.COUNT),
        ("cores", ("cores",), QuotaUnit.COUNT),
        ("ram_mib", ("ram", "ram_mib"), QuotaUnit.MIB),
    ),
    QuotaService.NETWORK: (("floating_ips", ("floating_ips", "floatingip"), QuotaUnit.COUNT),),
    QuotaService.STORAGE: (
        ("volumes", ("volumes",), QuotaUnit.COUNT),
        ("gigabytes", ("gigabytes",), QuotaUnit.GIB),
        ("snapshots", ("snapshots",), QuotaUnit.COUNT),
        ("backups", ("backups",), QuotaUnit.COUNT),
        ("backup_gigabytes", ("backup_gigabytes",), QuotaUnit.GIB),
    ),
}

_APP_VERSION = "0.3.0"
_P = ParamSpec("_P")
_T = TypeVar("_T")


class _BoundedToThreadRunner:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("SDK thread capacity must be positive")
        self._capacity = asyncio.Semaphore(capacity)
        self._running: set[asyncio.Task[Any]] = set()

    async def run(
        self,
        function: Callable[_P, _T],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T:
        await self._capacity.acquire()
        try:
            task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        except BaseException:
            self._capacity.release()
            raise
        self._running.add(task)
        task.add_done_callback(self._completed)
        # Once admitted, the worker task owns capacity until to_thread returns.
        return await asyncio.shield(task)

    def _completed(self, task: asyncio.Task[Any]) -> None:
        self._running.discard(task)
        self._capacity.release()
        if not task.cancelled():
            task.exception()


class OpenStackSdkAdapter:
    """OpenStack boundary; endpoint discovery and token scoping stay in openstacksdk."""

    def __init__(
        self,
        auth_url: str,
        interface: str,
        default_region: str,
        request_timeout_seconds: int,
        quota_timeout_seconds: float | None = None,
        instance_timeout_seconds: float | None = None,
        provisioning_timeout_seconds: float | None = None,
        operation_timeout_seconds: int = 600,
        thread_capacity: int = 8,
    ) -> None:
        self.auth_url = auth_url
        self.interface = interface
        self.default_region = default_region
        self.request_timeout_seconds = request_timeout_seconds
        self.quota_timeout_seconds = quota_timeout_seconds or float(request_timeout_seconds)
        self.instance_timeout_seconds = instance_timeout_seconds or float(request_timeout_seconds)
        self.provisioning_timeout_seconds = provisioning_timeout_seconds or float(
            request_timeout_seconds
        )
        self.operation_timeout_seconds = operation_timeout_seconds
        self._sdk_threads = _BoundedToThreadRunner(thread_capacity)

    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        return await self._sdk_threads.run(self._authenticate, username, password, domain)

    def _authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        try:
            from openstack.connection import Connection

            connection = Connection(
                auth_url=self.auth_url,
                username=username,
                password=password,
                user_domain_name=domain,
                interface=self.interface,
                api_timeout=self.request_timeout_seconds,
                app_name="vantage",
                app_version=_APP_VERSION,
            )
            token = connection.authorize()
            user_id = connection.current_user_id
            if not user_id:
                raise AuthenticationError
            identity = cast(Any, connection.identity)
            projects = tuple(
                Project(
                    id=project.id,
                    name=project.name,
                    domain_id=getattr(project, "domain_id", None),
                    enabled=getattr(project, "is_enabled", None),
                )
                for project in identity.user_projects(user_id)
            )
            auth_plugin = connection.session.auth
            if auth_plugin is None:
                raise AuthenticationError
            access = cast(Any, auth_plugin).get_access(connection.session)
            catalog = access.service_catalog.catalog
            regions = sorted(
                {
                    endpoint.get("region_id") or endpoint.get("region")
                    for service in catalog
                    for endpoint in service.get("endpoints", [])
                    if endpoint.get("region_id") or endpoint.get("region")
                }
            ) or [self.default_region]
            return AuthResult(
                user=User(id=user_id, name=username, domain_id=access.user_domain_id),
                projects=projects,
                regions=tuple(regions),
                auth_context={"unscoped_token": token},
                expires_at=access.expires,
            )
        except Exception as exc:
            raise _authentication_failure(exc) from exc

    async def scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult:
        return await self._sdk_threads.run(self._scope, auth_context, project_id, region)

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        return await self._sdk_threads.run(self._quotas, auth_context, project_id, region, service)

    async def list_instances(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
        image_id: str | None,
        sort: InstanceSort,
        direction: SortDirection,
    ) -> InstanceListResult:
        return await self._sdk_threads.run(
            self._list_instances,
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
            name=name,
            status=status,
            image_id=image_id,
            sort=sort,
            direction=direction,
        )

    async def get_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
    ) -> InstanceDetail:
        return await self._sdk_threads.run(
            self._get_instance,
            auth_context,
            project_id,
            region,
            instance_id,
        )

    async def list_images(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        visibility: ImageVisibility | None,
    ) -> ProvisioningListResult:
        return await self._sdk_threads.run(
            self._list_images,
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
            name=name,
            visibility=visibility,
        )

    async def list_flavors(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult:
        return await self._sdk_threads.run(
            self._list_flavors,
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
        )

    async def list_keypairs(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult:
        return await self._sdk_threads.run(
            self._list_keypairs,
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
        )

    async def list_networks(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
    ) -> ProvisioningListResult:
        return await self._sdk_threads.run(
            self._list_networks,
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
            name=name,
            status=status,
        )

    async def list_security_groups(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
    ) -> ProvisioningListResult:
        return await self._sdk_threads.run(
            self._list_security_groups,
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
            name=name,
        )

    async def create_instances(
        self, auth_context: dict[str, Any], project_id: str, region: str, payload: dict[str, Any]
    ) -> MutationResult:
        return await self._sdk_threads.run(
            self._create_instances, auth_context, project_id, region, payload
        )

    async def update_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
        payload: dict[str, Any],
    ) -> MutationResult:
        return await self._sdk_threads.run(
            self._update_instance, auth_context, project_id, region, instance_id, payload
        )

    async def delete_instance(
        self, auth_context: dict[str, Any], project_id: str, region: str, instance_id: str
    ) -> MutationResult:
        return await self._sdk_threads.run(
            self._delete_instance, auth_context, project_id, region, instance_id
        )

    async def instance_action(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> MutationResult:
        return await self._sdk_threads.run(
            self._instance_action,
            auth_context,
            project_id,
            region,
            instance_id,
            action,
            payload,
        )

    async def create_console(
        self, auth_context: dict[str, Any], project_id: str, region: str, instance_id: str
    ) -> RemoteConsoleResult:
        return await self._sdk_threads.run(
            self._create_console, auth_context, project_id, region, instance_id
        )

    async def image_mutation(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        action: str,
        image_id: str | None,
        payload: dict[str, Any],
    ) -> MutationResult:
        return await self._sdk_threads.run(
            self._image_mutation, auth_context, project_id, region, action, image_id, payload
        )

    async def flavor_mutation(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        action: str,
        flavor_id: str | None,
        payload: dict[str, Any],
    ) -> MutationResult:
        return await self._sdk_threads.run(
            self._flavor_mutation, auth_context, project_id, region, action, flavor_id, payload
        )

    def _create_instances(
        self, auth_context: dict[str, Any], project_id: str, region: str, payload: dict[str, Any]
    ) -> MutationResult:
        correlation_id = _global_request_id()
        created_ports: list[str] = []
        try:
            connection = self._project_connection(auth_context, project_id, region, correlation_id)
            networks: list[dict[str, Any]] = []
            security_groups = [str(value) for value in payload.get("security_group_ids", [])]
            for attachment in payload["networks"]:
                if attachment.get("port_id"):
                    networks.append({"port": str(attachment["port_id"])})
                    continue
                if attachment.get("subnet_id") or security_groups:
                    fixed_ips: list[dict[str, str]] = []
                    if attachment.get("subnet_id"):
                        fixed_ip = {"subnet_id": str(attachment["subnet_id"])}
                        if attachment.get("fixed_ip"):
                            fixed_ip["ip_address"] = str(attachment["fixed_ip"])
                        fixed_ips.append(fixed_ip)
                    port = cast(Any, connection.network).create_port(
                        network_id=str(attachment["network_id"]),
                        **({"fixed_ips": fixed_ips} if fixed_ips else {}),
                        security_group_ids=security_groups,
                    )
                    created_ports.append(str(port.id))
                    networks.append({"port": str(port.id), **_optional_tag(attachment)})
                    continue
                network = {"uuid": str(attachment["network_id"]), **_optional_tag(attachment)}
                if attachment.get("fixed_ip"):
                    network["fixed_ip"] = attachment["fixed_ip"]
                networks.append(network)

            attrs: dict[str, Any] = {
                "name": payload["name"],
                "flavor_id": payload["flavor_id"],
                "networks": networks,
                "min_count": payload.get("count", 1),
                "max_count": payload.get("count", 1),
                "metadata": payload.get("metadata", {}),
                "config_drive": payload.get("config_drive", False),
            }
            if security_groups and not any("port" in network for network in networks):
                attrs["security_groups"] = [{"name": value} for value in security_groups]
            for source, target in (
                ("description", "description"),
                ("hostname", "hostname"),
                ("availability_zone", "availability_zone"),
                ("keypair_name", "key_name"),
            ):
                if payload.get(source) is not None:
                    attrs[target] = payload[source]
            if payload.get("user_data"):
                attrs["user_data"] = base64.b64encode(
                    str(payload["user_data"]).encode("utf-8")
                ).decode("ascii")
            attrs.update(
                _boot_source_attrs(payload["boot_source"], payload.get("block_devices", []))
            )
            compute = cast(Any, connection.compute)
            server = compute.create_server(**attrs)
            server = self._wait_for_server_state(compute, server, {"ACTIVE"})
            return MutationResult(
                resource_id=str(server.id),
                resource_name=getattr(server, "name", payload["name"]),
                openstack_request_id=_resource_request_id(server) or correlation_id,
            )
        except Exception as exc:
            if created_ports:
                try:
                    connection = self._project_connection(
                        auth_context, project_id, region, correlation_id
                    )
                    for port_id in created_ports:
                        cast(Any, connection.network).delete_port(port_id, ignore_missing=True)
                except Exception:
                    pass
            raise _instance_failure(exc) from exc

    def _update_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
        payload: dict[str, Any],
    ) -> MutationResult:
        correlation_id = _global_request_id()
        try:
            connection = self._project_connection(auth_context, project_id, region, correlation_id)
            compute = cast(Any, connection.compute)
            attrs = {
                key: payload[key] for key in ("name", "description") if payload.get(key) is not None
            }
            resource = compute.update_server(instance_id, **attrs) if attrs else None
            if payload.get("metadata"):
                compute.set_server_metadata(instance_id, **payload["metadata"])
            if payload.get("unset_metadata"):
                compute.delete_server_metadata(instance_id, payload["unset_metadata"])
            return MutationResult(
                resource_id=instance_id,
                resource_name=payload.get("name"),
                openstack_request_id=_resource_request_id(resource) or correlation_id,
            )
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _delete_instance(
        self, auth_context: dict[str, Any], project_id: str, region: str, instance_id: str
    ) -> MutationResult:
        correlation_id = _global_request_id()
        try:
            connection = self._project_connection(auth_context, project_id, region, correlation_id)
            compute = cast(Any, connection.compute)
            server = compute.get_server(instance_id)
            compute.delete_server(server, ignore_missing=False)
            self._wait_for_server_delete(compute, server)
            return MutationResult(resource_id=instance_id, openstack_request_id=correlation_id)
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _instance_action(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> MutationResult:
        correlation_id = _global_request_id()
        try:
            connection = self._project_connection(auth_context, project_id, region, correlation_id)
            compute = cast(Any, connection.compute)
            server = compute.get_server(instance_id)
            simple = {
                "start": "start_server",
                "stop": "stop_server",
                "pause": "pause_server",
                "unpause": "unpause_server",
                "suspend": "suspend_server",
                "resume": "resume_server",
                "shelve": "shelve_server",
                "unshelve": "unshelve_server",
                "unrescue": "unrescue_server",
                "unlock": "unlock_server",
                "resize_confirm": "confirm_server_resize",
                "resize_revert": "revert_server_resize",
            }
            if action in simple:
                getattr(compute, simple[action])(server)
            elif action in {"soft_reboot", "hard_reboot"}:
                compute.reboot_server(server, action.removesuffix("_reboot").upper())
            elif action == "lock":
                compute.lock_server(server, locked_reason=payload.get("locked_reason"))
            elif action == "rescue":
                compute.rescue_server(server, image_ref=payload.get("image_id"))
            elif action == "resize":
                compute.resize_server(server, payload["flavor_id"])
            elif action == "rebuild":
                attrs = {
                    key: value
                    for key, value in payload.items()
                    if key in {"name", "metadata", "preserve_ephemeral"} and value is not None
                }
                if payload.get("user_data") is not None:
                    attrs["user_data"] = base64.b64encode(
                        str(payload["user_data"]).encode("utf-8")
                    ).decode("ascii")
                compute.rebuild_server(server, payload["image_id"], **attrs)
            elif action == "snapshot":
                image = compute.create_server_image(
                    server,
                    payload["name"],
                    metadata=payload.get("metadata"),
                    wait=True,
                    timeout=self.operation_timeout_seconds,
                )
                return MutationResult(
                    resource_id=str(getattr(image, "id", "")) or None,
                    resource_name=payload["name"],
                    openstack_request_id=_resource_request_id(image) or correlation_id,
                )
            else:
                raise ValueError(f"Unsupported instance action: {action}")
            target_states = {
                "start": {"ACTIVE"},
                "stop": {"SHUTOFF"},
                "soft_reboot": {"ACTIVE"},
                "hard_reboot": {"ACTIVE"},
                "pause": {"PAUSED"},
                "unpause": {"ACTIVE"},
                "suspend": {"SUSPENDED"},
                "resume": {"ACTIVE"},
                "shelve": {"SHELVED", "SHELVED_OFFLOADED"},
                "unshelve": {"ACTIVE"},
                "rescue": {"RESCUE"},
                "unrescue": {"ACTIVE"},
                "resize": {"VERIFY_RESIZE", "ACTIVE", "SHUTOFF"},
                "resize_confirm": {"ACTIVE", "SHUTOFF"},
                "resize_revert": {"ACTIVE", "SHUTOFF"},
                "rebuild": {"ACTIVE"},
            }.get(action)
            if target_states is not None:
                self._wait_for_server_state(
                    compute,
                    server,
                    target_states,
                    flavor_id=str(payload["flavor_id"]) if action == "resize" else None,
                    require_update=action in {"soft_reboot", "hard_reboot", "rebuild"},
                )
            return MutationResult(resource_id=instance_id, openstack_request_id=correlation_id)
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _create_console(
        self, auth_context: dict[str, Any], project_id: str, region: str, instance_id: str
    ) -> RemoteConsoleResult:
        correlation_id = _global_request_id()
        try:
            connection = self._project_connection(auth_context, project_id, region, correlation_id)
            console = cast(Any, connection.compute).create_console(
                instance_id, "novnc", console_protocol="vnc"
            )
            values = _as_mapping(console)
            url = values.get("url")
            if not isinstance(url, str) or not url:
                raise ValueError("Nova did not return a noVNC URL")
            return RemoteConsoleResult(url=url, openstack_request_id=correlation_id)
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _image_mutation(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        action: str,
        image_id: str | None,
        payload: dict[str, Any],
    ) -> MutationResult:
        correlation_id = _global_request_id()
        try:
            connection = self._project_connection(auth_context, project_id, region, correlation_id)
            image = cast(Any, connection.image)
            resource: Any = None
            if action == "create":
                attrs = _image_attrs(payload)
                resource = image.create_image(**attrs)
                image_id = str(resource.id)
                if payload.get("import_uri"):
                    image.import_image(image_id, method="web-download", uri=payload["import_uri"])
            elif action == "update":
                resource = image.update_image(image_id, **_image_attrs(payload))
                unset = payload.get("unset_properties", [])
                if unset:
                    current = image.get_image(image_id)
                    current.patch(
                        image,
                        [
                            {"op": "remove", "path": f"/{_json_pointer_segment(prop)}"}
                            for prop in unset
                        ],
                        prepend_key=False,
                    )
            elif action == "delete":
                image.delete_image(image_id, ignore_missing=False)
            elif action == "deactivate":
                image.deactivate_image(image_id)
            elif action == "reactivate":
                image.reactivate_image(image_id)
            elif action == "member_add":
                resource = image.add_member(image_id, member_id=payload["project_id"])
            elif action == "member_remove":
                image.remove_member(payload["project_id"], image=image_id, ignore_missing=False)
            else:
                raise ValueError(f"Unsupported image action: {action}")
            return MutationResult(
                resource_id=image_id,
                resource_name=payload.get("name"),
                openstack_request_id=_resource_request_id(resource) or correlation_id,
            )
        except Exception as exc:
            raise _provisioning_failure(exc) from exc

    def _flavor_mutation(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        action: str,
        flavor_id: str | None,
        payload: dict[str, Any],
    ) -> MutationResult:
        correlation_id = _global_request_id()
        try:
            connection = self._project_connection(auth_context, project_id, region, correlation_id)
            compute = cast(Any, connection.compute)
            resource: Any = None
            if action == "create":
                attrs = {
                    "name": payload["name"],
                    "vcpus": payload["vcpus"],
                    "ram": payload["ram_mib"],
                    "disk": payload.get("disk_gib", 0),
                    "ephemeral": payload.get("ephemeral_gib", 0),
                    "swap": payload.get("swap_mib", 0),
                    "rxtx_factor": payload.get("rxtx_factor", 1.0),
                    "is_public": payload.get("is_public", True),
                }
                if payload.get("id"):
                    attrs["id"] = payload["id"]
                if payload.get("description") is not None:
                    attrs["description"] = payload["description"]
                resource = compute.create_flavor(**attrs)
                flavor_id = str(resource.id)
                if payload.get("extra_specs"):
                    compute.create_flavor_extra_specs(flavor_id, payload["extra_specs"])
                for tenant in payload.get("access_project_ids", []):
                    compute.flavor_add_tenant_access(flavor_id, tenant)
            elif action == "update":
                resource = compute.update_flavor(flavor_id, description=payload.get("description"))
            elif action == "delete":
                compute.delete_flavor(flavor_id, ignore_missing=False)
            elif action == "extra_specs_set":
                resource = compute.create_flavor_extra_specs(flavor_id, payload["specs"])
            elif action == "extra_spec_unset":
                compute.delete_flavor_extra_specs_property(flavor_id, payload["key"])
            elif action == "access_add":
                resource = compute.flavor_add_tenant_access(flavor_id, payload["project_id"])
            elif action == "access_remove":
                resource = compute.flavor_remove_tenant_access(flavor_id, payload["project_id"])
            else:
                raise ValueError(f"Unsupported flavor action: {action}")
            return MutationResult(
                resource_id=flavor_id,
                resource_name=payload.get("name"),
                openstack_request_id=_resource_request_id(resource) or correlation_id,
            )
        except Exception as exc:
            raise _provisioning_failure(exc) from exc

    def _wait_for_server_state(
        self,
        compute: Any,
        server: Any,
        target_states: set[str],
        *,
        flavor_id: str | None = None,
        require_update: bool = False,
    ) -> Any:
        """Observe Nova until a safe terminal or recovery state is visible."""

        deadline = time.monotonic() + self.operation_timeout_seconds
        current = server
        initial_updated = _optional_text(server, "updated", "updated_at")
        while True:
            current = compute.get_server(current)
            status = str(getattr(current, "status", "")).upper()
            if status == "ERROR":
                raise RuntimeError("Nova server entered ERROR")
            flavor_matches = flavor_id is None or _reference(current, "flavor") == flavor_id
            updated = _optional_text(current, "updated", "updated_at")
            update_observed = not require_update or updated != initial_updated
            if status in target_states and flavor_matches and update_observed:
                return current
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Nova server did not reach {sorted(target_states)}")
            time.sleep(2)

    def _wait_for_server_delete(self, compute: Any, server: Any) -> None:
        compute.wait_for_delete(server, interval=2, wait=self.operation_timeout_seconds)

    def _scope(self, auth_context: dict[str, Any], project_id: str, region: str) -> ScopeResult:
        try:
            from openstack.connection import Connection

            connection = Connection(
                auth_url=self.auth_url,
                auth_type="v3token",
                token=auth_context["unscoped_token"],
                project_id=project_id,
                region_name=region,
                interface=self.interface,
                api_timeout=self.request_timeout_seconds,
                app_name="vantage",
                app_version=_APP_VERSION,
            )
            scoped_token = connection.authorize()
            auth_plugin = connection.session.auth
            if auth_plugin is None:
                raise ScopeError
            access = cast(Any, auth_plugin).get_access(connection.session)
            identity = cast(Any, connection.identity)
            project_resource = identity.get_project(project_id)
            project = Project(
                id=project_resource.id,
                name=project_resource.name,
                domain_id=getattr(project_resource, "domain_id", None),
                enabled=getattr(project_resource, "is_enabled", None),
            )
            return ScopeResult(
                project=project,
                region=region,
                auth_context={
                    **auth_context,
                    "scoped_token": scoped_token,
                    "catalog": access.service_catalog.catalog,
                    "project_id": project_id,
                    "region": region,
                },
                expires_at=access.expires,
            )
        except Exception as exc:
            raise _scope_failure(exc) from exc

    def _quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        try:
            from openstack.connection import Connection

            token = auth_context.get("scoped_token")
            if not isinstance(token, str) or not token:
                raise AdapterError(status_code=401)
            connection = Connection(
                auth_url=self.auth_url,
                auth_type="v3token",
                token=token,
                project_id=project_id,
                region_name=region,
                interface=self.interface,
                api_timeout=self.quota_timeout_seconds,
                app_name="vantage",
                app_version=_APP_VERSION,
            )
            if service is QuotaService.COMPUTE:
                resource = cast(Any, connection.compute).get_quota_set(project_id, usage=True)
            elif service is QuotaService.NETWORK:
                resource = cast(Any, connection.network).get_quota(project_id, details=True)
            else:
                resource = cast(Any, connection.block_storage).get_quota_set(project_id, usage=True)
            return _normalize_quota_resource(service, resource)
        except Exception as exc:
            raise _quota_failure(exc) from exc

    def _list_instances(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
        image_id: str | None,
        sort: InstanceSort,
        direction: SortDirection,
    ) -> InstanceListResult:
        correlation_id = _global_request_id()
        try:
            from openstack import exceptions
            from openstack.compute.v2.server import Server

            connection = self._project_connection(
                auth_context,
                project_id,
                region,
                correlation_id,
            )
            query: dict[str, Any] = {
                "limit": limit,
                "sort_key": {
                    InstanceSort.CREATED_AT: "created_at",
                    InstanceSort.NAME: "display_name",
                    InstanceSort.STATUS: "vm_state",
                }[sort],
                "sort_dir": direction.value,
            }
            if marker is not None:
                query["marker"] = marker
            if name is not None:
                query["name"] = name
            if status is not None:
                query["status"] = status
            if image_id is not None:
                query["image"] = image_id
            session = cast(Any, connection.compute)
            base_path = "/servers/detail"
            microversion = Server._get_microversion(session)
            api_filters = Server._query_mapping._validate(
                query,
                base_path=base_path,
                allow_unknown_params=True,
            )
            query_params = Server._query_mapping._transpose(api_filters, Server)
            response = session.get(
                base_path,
                headers={"Accept": "application/json"},
                params=query_params,
                microversion=microversion,
            )
            exceptions.raise_from_response(response)
            data = response.json()
            if not isinstance(data, Mapping):
                raise ValueError("Nova server list response must be an object")
            resources = data.get("servers")
            if not isinstance(resources, list):
                raise ValueError("Nova server list response must contain servers")
            return InstanceListResult(
                items=tuple(_normalize_instance(resource) for resource in resources),
                has_next=_has_next_server_link(response, data),
                openstack_request_id=correlation_id,
            )
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _get_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
    ) -> InstanceDetail:
        correlation_id = _global_request_id()
        try:
            from openstack.compute.v2.server import Server

            connection = self._project_connection(
                auth_context,
                project_id,
                region,
                correlation_id,
            )
            resource = Server.existing(id=instance_id).fetch(cast(Any, connection.compute))
            return _normalize_instance_detail(resource, correlation_id)
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _list_images(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        visibility: ImageVisibility | None,
    ) -> ProvisioningListResult:
        from openstack.image.v2.image import Image as SdkImage

        query = _list_query(limit, marker, name)
        if visibility is not None:
            query["visibility"] = visibility.value
        return self._list_provisioning_resource(
            auth_context,
            project_id,
            region,
            service="image",
            resource_class=SdkImage,
            base_path="/images",
            collection_key="images",
            query=query,
            normalizer=_normalize_image,
        )

    def _list_flavors(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult:
        from openstack.compute.v2.flavor import Flavor as SdkFlavor

        return self._list_provisioning_resource(
            auth_context,
            project_id,
            region,
            service="compute",
            resource_class=SdkFlavor,
            base_path="/flavors/detail",
            collection_key="flavors",
            query=_list_query(limit, marker, None),
            normalizer=_normalize_flavor,
        )

    def _list_keypairs(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult:
        from openstack.compute.v2.keypair import Keypair as SdkKeyPair

        return self._list_provisioning_resource(
            auth_context,
            project_id,
            region,
            service="compute",
            resource_class=SdkKeyPair,
            base_path="/os-keypairs",
            collection_key="keypairs",
            query=_list_query(limit, marker, None),
            normalizer=_normalize_keypair,
            required_microversion="2.35",
        )

    def _list_networks(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
    ) -> ProvisioningListResult:
        from openstack.network.v2.network import Network as SdkNetwork

        query = _list_query(limit, marker, name)
        if status is not None:
            query["status"] = status
        return self._list_provisioning_resource(
            auth_context,
            project_id,
            region,
            service="network",
            resource_class=SdkNetwork,
            base_path="/networks",
            collection_key="networks",
            query=query,
            normalizer=_normalize_network,
        )

    def _list_security_groups(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
    ) -> ProvisioningListResult:
        from openstack.network.v2.security_group import SecurityGroup as SdkSecurityGroup

        return self._list_provisioning_resource(
            auth_context,
            project_id,
            region,
            service="network",
            resource_class=SdkSecurityGroup,
            base_path="/security-groups",
            collection_key="security_groups",
            query=_list_query(limit, marker, name),
            normalizer=_normalize_security_group,
        )

    def _list_provisioning_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        service: str,
        resource_class: Any,
        base_path: str,
        collection_key: str,
        query: dict[str, Any],
        normalizer: Callable[[Any], Image | Flavor | KeyPair | Network | SecurityGroup],
        required_microversion: str | None = None,
    ) -> ProvisioningListResult:
        correlation_id = _global_request_id()
        try:
            from openstack import exceptions

            connection = self._project_connection(
                auth_context,
                project_id,
                region,
                correlation_id,
                request_timeout_seconds=self.provisioning_timeout_seconds,
            )
            session = cast(Any, getattr(connection, service))
            if required_microversion is not None:
                from openstack import utils

                microversion = utils.pick_microversion(session, required_microversion)
            else:
                microversion = resource_class._get_microversion(session)
            api_filters = resource_class._query_mapping._validate(
                query, base_path=base_path, allow_unknown_params=True
            )
            query_params = resource_class._query_mapping._transpose(api_filters, resource_class)
            # Preserve explicitly supported filters missing from an SDK mapping.
            for name, value in query.items():
                query_params.setdefault(name, value)
            response = session.get(
                base_path,
                headers={"Accept": "application/json"},
                params=query_params,
                microversion=microversion,
            )
            exceptions.raise_from_response(response)
            data = response.json()
            if not isinstance(data, Mapping):
                raise ValueError(f"{collection_key} list response must be an object")
            resources = data.get(collection_key)
            if not isinstance(resources, list):
                raise ValueError(f"{collection_key} list response must contain a list")
            return ProvisioningListResult(
                items=tuple(normalizer(resource) for resource in resources),
                has_next=_has_next_collection_link(response, data, collection_key),
                openstack_request_id=_response_request_id(response) or correlation_id,
            )
        except Exception as exc:
            raise _provisioning_failure(exc) from exc

    def _project_connection(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        correlation_id: str,
        *,
        request_timeout_seconds: float | None = None,
    ) -> Any:
        from openstack.connection import Connection

        token = auth_context.get("scoped_token")
        if (
            not isinstance(token, str)
            or not token
            or auth_context.get("project_id") != project_id
            or auth_context.get("region") != region
        ):
            raise AdapterError(status_code=401)
        return Connection(
            auth_url=self.auth_url,
            auth_type="v3token",
            token=token,
            project_id=project_id,
            region_name=region,
            interface=self.interface,
            api_timeout=request_timeout_seconds or self.instance_timeout_seconds,
            app_name="vantage",
            app_version=_APP_VERSION,
            global_request_id=correlation_id,
        )


def _has_next_server_link(response: Any, data: Mapping[str, Any]) -> bool:
    body_links = data.get("servers_links")
    if isinstance(body_links, list):
        for link in body_links:
            if (
                isinstance(link, Mapping)
                and link.get("rel") == "next"
                and isinstance(link.get("href"), str)
                and link["href"]
            ):
                return True

    response_links = getattr(response, "links", None)
    if not isinstance(response_links, Mapping):
        return False
    next_link = response_links.get("next")
    if isinstance(next_link, str):
        return bool(next_link)
    if not isinstance(next_link, Mapping):
        return False
    return any(
        isinstance(next_link.get(key), str) and bool(next_link[key])
        for key in ("url", "uri", "href")
    )


def _list_query(limit: int, marker: str | None, name: str | None) -> dict[str, Any]:
    query: dict[str, Any] = {"limit": limit}
    if marker is not None:
        query["marker"] = marker
    if name is not None:
        query["name"] = name
    return query


def _has_next_collection_link(response: Any, data: Mapping[str, Any], collection_key: str) -> bool:
    for key in ("next", f"{collection_key}_links", "links"):
        links = data.get(key)
        if isinstance(links, str) and links:
            return True
        if isinstance(links, Mapping):
            candidate = links.get("next")
            if isinstance(candidate, str) and candidate:
                return True
        if isinstance(links, list):
            for link in links:
                if (
                    isinstance(link, Mapping)
                    and link.get("rel") == "next"
                    and isinstance(link.get("href"), str)
                    and link["href"]
                ):
                    return True
    return _has_next_server_link(response, {})


def _response_request_id(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name in ("x-openstack-request-id", "X-OpenStack-Request-ID"):
        value = headers.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _resource_request_id(resource: Any) -> str | None:
    if resource is None:
        return None
    for name in ("request_id", "x_openstack_request_id"):
        value = getattr(resource, name, None)
        if isinstance(value, str) and value:
            return value
    return None


def _optional_tag(attachment: Mapping[str, Any]) -> dict[str, str]:
    tag = attachment.get("tag")
    return {"tag": tag} if isinstance(tag, str) and tag else {}


def _boot_source_attrs(
    boot_source: Mapping[str, Any], block_devices: list[dict[str, Any]]
) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    source_type = str(boot_source["type"])
    if source_type == "image" and not boot_source.get("create_boot_volume"):
        attrs: dict[str, Any] = {"image_id": str(boot_source["image_id"])}
    else:
        source_id_name = {
            "image": "image_id",
            "volume": "volume_id",
            "volume_snapshot": "snapshot_id",
        }[source_type]
        mappings.append(
            {
                "source_type": "snapshot" if source_type == "volume_snapshot" else source_type,
                "uuid": str(boot_source[source_id_name]),
                "destination_type": "volume",
                "boot_index": 0,
                "delete_on_termination": boot_source.get("delete_on_termination", False),
                **(
                    {"volume_size": boot_source["volume_size_gib"]}
                    if boot_source.get("volume_size_gib") is not None
                    else {}
                ),
                **(
                    {"volume_type": boot_source["volume_type"]}
                    if boot_source.get("volume_type") is not None
                    else {}
                ),
            }
        )
        attrs = {}
    for device in block_devices:
        mapping = {
            "source_type": device["source_type"],
            "destination_type": device["destination_type"],
            "boot_index": device["boot_index"],
            "delete_on_termination": device.get("delete_on_termination", False),
        }
        aliases = {
            "source_id": "uuid",
            "device_name": "device_name",
            "volume_size_gib": "volume_size",
            "volume_type": "volume_type",
            "tag": "tag",
        }
        for source, target in aliases.items():
            if device.get(source) is not None:
                mapping[target] = str(device[source])
        mappings.append(mapping)
    if mappings:
        attrs["block_device_mapping_v2"] = mappings
    return attrs


def _image_attrs(payload: Mapping[str, Any]) -> dict[str, Any]:
    aliases = {
        "name": "name",
        "disk_format": "disk_format",
        "container_format": "container_format",
        "visibility": "visibility",
        "min_disk_gib": "min_disk",
        "min_ram_mib": "min_ram",
        "protected": "is_protected",
        "tags": "tags",
    }
    attrs = {
        target: payload[source]
        for source, target in aliases.items()
        if source in payload and payload[source] is not None
    }
    properties = payload.get("properties")
    if isinstance(properties, Mapping):
        attrs.update(properties)
    return attrs


def _json_pointer_segment(value: str) -> str:
    """Escape an arbitrary Glance property name for an RFC 6901 pointer."""

    return value.replace("~", "~0").replace("/", "~1")


def _global_request_id() -> str:
    return f"req-{uuid4()}"


def _source_mapping(value: Any) -> Mapping[str, Any]:
    body = getattr(value, "_body", None)
    attributes = getattr(body, "attributes", None)
    if isinstance(attributes, Mapping):
        return attributes
    if isinstance(value, Mapping):
        return value
    attributes = getattr(value, "__dict__", None)
    return attributes if isinstance(attributes, Mapping) else {}


def _source_value(value: Any, *names: str) -> tuple[bool, Any]:
    source = _source_mapping(value)
    for name in names:
        if name in source:
            return True, source[name]
    return False, None


def _required_text(value: Any, *names: str) -> str:
    present, raw = _source_value(value, *names)
    if not present or not isinstance(raw, str) or not raw:
        raise ValueError(f"Missing required instance field: {names[0]}")
    return raw


def _optional_text(value: Any, *names: str) -> str | None:
    present, raw = _source_value(value, *names)
    return raw if present and isinstance(raw, str) else None


def _reference(value: Any, *names: str) -> str | None:
    present, raw = _source_value(value, *names)
    if not present or raw is None:
        return None
    if isinstance(raw, str):
        return raw or None
    values = _source_mapping(raw)
    for key in ("original_name", "name", "id"):
        candidate = values.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _created_at(value: Any) -> datetime | None:
    present, raw = _source_value(value, "created", "created_at")
    if not present or raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _addresses(value: Any) -> list[str] | None:
    present, raw = _source_value(value, "addresses")
    if not present or raw is None:
        return None
    if not isinstance(raw, Mapping):
        return None
    addresses: list[str] = []
    for network, network_addresses in raw.items():
        if not isinstance(network, str) or not isinstance(network_addresses, list):
            continue
        for address in network_addresses:
            values = _source_mapping(address)
            ip_address = values.get("addr")
            if isinstance(ip_address, str) and ip_address:
                addresses.append(f"{network}: {ip_address}")
    return addresses


def _volumes(value: Any) -> list[InstanceVolume] | None:
    present, raw = _source_value(
        value,
        "os-extended-volumes:volumes_attached",
        "attached_volumes",
        "volumes",
    )
    if not present or raw is None:
        return None
    if not isinstance(raw, list):
        return None
    volumes: list[InstanceVolume] = []
    for attachment in raw:
        values = _source_mapping(attachment)
        volume_id = values.get("id", values.get("volume_id"))
        if not isinstance(volume_id, str) or not volume_id:
            continue
        device = values.get("device")
        volumes.append(
            InstanceVolume(
                id=volume_id,
                device=device if isinstance(device, str) else None,
            )
        )
    return volumes


def _normalize_instance(resource: Any) -> Instance:
    return Instance(
        id=UUID(_required_text(resource, "id")),
        status=_required_text(resource, "status"),
        name=_optional_text(resource, "name"),
        created_at=_created_at(resource),
        flavor=_reference(resource, "flavor", "flavor_id", "flavorRef"),
        image=_reference(resource, "image", "image_id", "imageRef"),
        addresses=_addresses(resource),
    )


def _normalize_instance_detail(resource: Any, request_id: str) -> InstanceDetail:
    instance = _normalize_instance(resource)
    return InstanceDetail(
        **instance.model_dump(),
        volumes=_volumes(resource),
        description=_optional_text(resource, "description"),
        metadata=_optional_string_mapping(resource, "metadata"),
        availability_zone=_optional_text(
            resource, "OS-EXT-AZ:availability_zone", "availability_zone"
        ),
        locked=_optional_bool(resource, "locked", "is_locked"),
        openstack_request_id=request_id,
    )


def _optional_int(value: Any, *names: str) -> int | None:
    present, raw = _source_value(value, *names)
    if not present or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _optional_bool(value: Any, *names: str) -> bool | None:
    present, raw = _source_value(value, *names)
    return raw if present and isinstance(raw, bool) else None


def _optional_string_mapping(value: Any, *names: str) -> dict[str, str] | None:
    present, raw = _source_value(value, *names)
    if not present or not isinstance(raw, Mapping):
        return None
    return {
        str(key): str(item)
        for key, item in raw.items()
        if isinstance(key, str) and isinstance(item, (str, int, float, bool))
    }


def _optional_string_list(value: Any, *names: str) -> list[str] | None:
    present, raw = _source_value(value, *names)
    if not present or not isinstance(raw, list):
        return None
    return [item for item in raw if isinstance(item, str)]


def _normalize_image(resource: Any) -> Image:
    visibility_value = _optional_text(resource, "visibility")
    try:
        visibility = ImageVisibility(visibility_value) if visibility_value else None
    except ValueError:
        visibility = None
    return Image(
        id=UUID(_required_text(resource, "id")),
        name=_optional_text(resource, "name"),
        status=_optional_text(resource, "status"),
        visibility=visibility,
        disk_format=_optional_text(resource, "disk_format"),
        container_format=_optional_text(resource, "container_format"),
        size_bytes=_optional_int(resource, "size", "size_bytes"),
        min_disk_gib=_optional_int(resource, "min_disk", "min_disk_gib"),
        min_ram_mib=_optional_int(resource, "min_ram", "min_ram_mib"),
        created_at=_created_at(resource),
        protected=_optional_bool(resource, "protected", "is_protected"),
        properties=_optional_string_mapping(resource, "properties"),
        tags=_optional_string_list(resource, "tags"),
    )


def _normalize_flavor(resource: Any) -> Flavor:
    return Flavor(
        id=_required_text(resource, "id"),
        name=_optional_text(resource, "name"),
        vcpus=_optional_int(resource, "vcpus"),
        ram_mib=_optional_int(resource, "ram", "ram_mib"),
        disk_gib=_optional_int(resource, "disk", "disk_gib"),
        ephemeral_gib=_optional_int(resource, "OS-FLV-EXT-DATA:ephemeral", "ephemeral"),
        is_public=_optional_bool(resource, "os-flavor-access:is_public", "is_public"),
        description=_optional_text(resource, "description"),
        extra_specs=_optional_string_mapping(resource, "extra_specs"),
    )


def _normalize_keypair(resource: Any) -> KeyPair:
    values = _source_mapping(resource)
    wrapped = values.get("keypair")
    if wrapped is not None:
        resource = wrapped
    type_value = _optional_text(resource, "type")
    try:
        key_type = KeyPairType(type_value) if type_value else None
    except ValueError:
        key_type = None
    public_key = _optional_text(resource, "public_key")
    return KeyPair(
        name=_required_text(resource, "name"),
        type=key_type,
        fingerprint=_optional_text(resource, "fingerprint"),
        public_key_preview=(
            f"{public_key[:61]}..."
            if public_key is not None and len(public_key) > 64
            else public_key
        ),
        created_at=_created_at(resource),
        last_used_at=_optional_datetime(resource, "last_used_at"),
    )


def _optional_datetime(value: Any, *names: str) -> datetime | None:
    present, raw = _source_value(value, *names)
    if not present or raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _normalize_network(resource: Any) -> Network:
    present, subnets = _source_value(resource, "subnets")
    subnet_count = len(subnets) if present and isinstance(subnets, list) else None
    return Network(
        id=UUID(_required_text(resource, "id")),
        name=_optional_text(resource, "name"),
        status=_optional_text(resource, "status"),
        shared=_optional_bool(resource, "shared", "is_shared"),
        external=_optional_bool(resource, "router:external", "is_router_external", "external"),
        mtu=_optional_int(resource, "mtu"),
        subnet_count=subnet_count,
    )


def _normalize_security_group(resource: Any) -> SecurityGroup:
    present, rules = _source_value(resource, "security_group_rules", "rules")
    rule_count = len(rules) if present and isinstance(rules, list) else None
    return SecurityGroup(
        id=UUID(_required_text(resource, "id")),
        name=_optional_text(resource, "name"),
        description=_optional_text(resource, "description"),
        rule_count=rule_count,
        revision_number=_optional_int(resource, "revision_number"),
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, Mapping):
            return result
    attributes = getattr(value, "__dict__", None)
    return attributes if isinstance(attributes, Mapping) else {}


def _resource_value(resource: Any, aliases: tuple[str, ...]) -> Any:
    values = _as_mapping(resource)
    for alias in aliases:
        if alias in values:
            return values[alias]
        value = getattr(resource, alias, None)
        if value is not None:
            return value
    return None


def _number(value: Any, names: tuple[str, ...]) -> int | float | None:
    values = _as_mapping(value)
    for name in names:
        candidate = values.get(name, getattr(value, name, None))
        if isinstance(candidate, bool) or candidate is None:
            continue
        if isinstance(candidate, (int, float)):
            return candidate
        if isinstance(candidate, str):
            try:
                return float(candidate) if "." in candidate else int(candidate)
            except ValueError:
                continue
    return None


def _normalize_quota_resource(service: QuotaService, resource: Any) -> tuple[Quota, ...]:
    quotas: list[Quota] = []
    for name, aliases, unit in _QUOTA_SPECS[service]:
        raw = _resource_value(resource, aliases)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            limit: int | float | None = raw
            used: int | float | None = 0
            reserved: int | float | None = 0
        else:
            limit = _number(raw, ("limit",))
            used = _number(raw, ("in_use", "used"))
            reserved = _number(raw, ("reserved",))
        quotas.append(
            normalized_quota(
                service=service,
                resource=name,
                used=used,
                reserved=reserved,
                limit=limit,
                unit=unit,
            )
        )
    return tuple(quotas)


def _status_code(exc: Exception) -> int | None:
    for attribute in ("status_code", "http_status"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and value > 0:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) and value > 0 else None


def _request_id(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get("x-openstack-request-id")
        if isinstance(value, str) and value:
            return value
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return None


def _authentication_failure(exc: Exception) -> AdapterError:
    status = _status_code(exc)
    request_id = _request_id(exc)
    if status == 401 or isinstance(exc, AuthenticationError):
        return AuthenticationError(request_id=request_id)
    if status in {403, 429}:
        return AdapterError(status_code=status, request_id=request_id)
    return AdapterError(status_code=503, request_id=request_id)


def _scope_failure(exc: Exception) -> ScopeError:
    status = _status_code(exc)
    request_id = _request_id(exc)
    if isinstance(exc, ScopeError):
        return ScopeError(status_code=exc.status_code, request_id=exc.request_id)
    if status not in {401, 403, 404, 409, 429}:
        status = 503
    return ScopeError(status_code=status, request_id=request_id)


def _quota_failure(exc: Exception) -> AdapterError:
    if isinstance(exc, AdapterError):
        return AdapterError(status_code=exc.status_code, request_id=exc.request_id)
    status = _status_code(exc)
    if status not in {401, 403, 404, 429}:
        status = 503
    return AdapterError(status_code=status, request_id=_request_id(exc))


def _instance_failure(exc: Exception) -> AdapterError:
    if isinstance(exc, AdapterTimeoutError):
        return AdapterTimeoutError(request_id=exc.request_id)
    if isinstance(exc, AdapterError):
        if exc.status_code == 504:
            return AdapterTimeoutError(request_id=exc.request_id)
        return AdapterError(status_code=exc.status_code, request_id=exc.request_id)
    request_id = _request_id(exc)
    timeout_names = {"ConnectTimeout", "ReadTimeout", "RequestTimeout", "Timeout"}
    if isinstance(exc, TimeoutError) or exc.__class__.__name__ in timeout_names:
        return AdapterTimeoutError(request_id=request_id)
    status = _status_code(exc)
    if status == 504:
        return AdapterTimeoutError(request_id=request_id)
    if status not in {400, 401, 403, 404, 409, 429}:
        status = 503
    return AdapterError(status_code=status, request_id=request_id)


def _provisioning_failure(exc: Exception) -> AdapterError:
    if isinstance(exc, AdapterTimeoutError):
        return AdapterTimeoutError(request_id=exc.request_id)
    if isinstance(exc, AdapterError):
        if exc.status_code == 504:
            return AdapterTimeoutError(request_id=exc.request_id)
        return AdapterError(status_code=exc.status_code, request_id=exc.request_id)
    request_id = _request_id(exc)
    timeout_names = {"ConnectTimeout", "ReadTimeout", "RequestTimeout", "Timeout"}
    if isinstance(exc, TimeoutError) or exc.__class__.__name__ in timeout_names:
        return AdapterTimeoutError(request_id=request_id)
    status = _status_code(exc)
    if status == 504:
        return AdapterTimeoutError(request_id=request_id)
    if status not in {400, 401, 403, 404, 409, 429}:
        status = 503
    return AdapterError(status_code=status, request_id=request_id)
