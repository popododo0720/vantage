from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from vantage_bff.adapters.base import AdapterError, AdapterTimeoutError
from vantage_bff.storage.base import StorageListResult, StorageMutationResult
from vantage_bff.storage.models import (
    Attachment,
    QosSpec,
    StorageItem,
    StoragePool,
    StorageResourceKind,
    StorageService,
    Volume,
    VolumeBackup,
    VolumeSnapshot,
    VolumeType,
    VolumeTypeEncryption,
)


class ThreadRunner(Protocol):
    async def run(self, function: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any: ...


class OpenStackSdkStorageAdapter:
    """Cinder v3 adapter using the active user-scoped openstacksdk connection."""

    def __init__(
        self,
        runner: ThreadRunner,
        connection_factory: Callable[..., Any],
        timeout_seconds: float,
    ) -> None:
        self._runner = runner
        self._connection_factory = connection_factory
        self._timeout_seconds = timeout_seconds

    async def list_resources(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        *,
        limit: int,
        marker: str | None,
        filters: dict[str, str],
        sort: str,
        direction: str,
        all_projects: bool = False,
    ) -> StorageListResult:
        return cast(
            StorageListResult,
            await self._runner.run(
                self._list_resources,
                auth_context,
                project_id,
                region,
                kind,
                limit=limit,
                marker=marker,
                filters=filters,
                sort=sort,
                direction=direction,
                all_projects=all_projects,
            ),
        )

    async def get_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        resource_id: str,
    ) -> StorageItem:
        return cast(
            StorageItem,
            await self._runner.run(
                self._get_resource, auth_context, project_id, region, kind, resource_id
            ),
        )

    async def mutate(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> StorageMutationResult:
        return cast(
            StorageMutationResult,
            await self._runner.run(
                self._mutate,
                auth_context,
                project_id,
                region,
                kind,
                operation,
                resource_id,
                payload,
            ),
        )

    def _connection(
        self, auth: dict[str, Any], project_id: str, region: str, correlation_id: str
    ) -> Any:
        return self._connection_factory(
            auth,
            project_id,
            region,
            correlation_id,
            request_timeout_seconds=self._timeout_seconds,
        )

    def _list_resources(
        self,
        auth: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        *,
        limit: int,
        marker: str | None,
        filters: dict[str, str],
        sort: str,
        direction: str,
        all_projects: bool,
    ) -> StorageListResult:
        correlation_id = self._correlation_id()
        try:
            proxy = self._connection(auth, project_id, region, correlation_id).block_storage
            query: dict[str, Any] = {**filters}
            if marker:
                query["marker"] = marker
            query["limit"] = limit
            query["sort"] = f"{self._api_sort(sort)}:{direction}"
            if all_projects:
                query["all_projects"] = True
            if kind is StorageResourceKind.VOLUME:
                resources = proxy.volumes(details=True, **query)
            elif kind is StorageResourceKind.SNAPSHOT:
                resources = proxy.snapshots(details=True, **query)
            elif kind is StorageResourceKind.BACKUP:
                resources = proxy.backups(details=True, **query)
            elif kind is StorageResourceKind.VOLUME_TYPE:
                query.pop("sort", None)
                resources = proxy.types(**query)
            elif kind is StorageResourceKind.QOS_SPEC:
                query.pop("sort", None)
                resources = proxy.qos_specs(**query)
            elif kind is StorageResourceKind.POOL:
                resources = proxy.backend_pools(detail=True)
            else:
                resources = proxy.services(**{k: v for k, v in filters.items() if v})
            items = tuple(self._normalize(kind, item) for item in resources)
            return StorageListResult(
                items=items,
                has_next=len(items) >= limit
                and kind not in {StorageResourceKind.POOL, StorageResourceKind.SERVICE},
                request_id=correlation_id,
            )
        except Exception as exc:
            raise self._failure(exc) from exc

    def _get_resource(
        self,
        auth: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        resource_id: str,
    ) -> StorageItem:
        correlation_id = self._correlation_id()
        try:
            proxy = self._connection(auth, project_id, region, correlation_id).block_storage
            getter = {
                StorageResourceKind.VOLUME: proxy.get_volume,
                StorageResourceKind.SNAPSHOT: proxy.get_snapshot,
                StorageResourceKind.BACKUP: proxy.get_backup,
                StorageResourceKind.VOLUME_TYPE: proxy.get_type,
                StorageResourceKind.QOS_SPEC: proxy.get_qos_spec,
            }.get(kind)
            if getter is None:
                raise AdapterError(status_code=405, request_id=correlation_id)
            return self._normalize(kind, getter(resource_id))
        except Exception as exc:
            raise self._failure(exc) from exc

    def _mutate(
        self,
        auth: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> StorageMutationResult:
        correlation_id = self._correlation_id()
        try:
            connection = self._connection(auth, project_id, region, correlation_id)
            proxy = connection.block_storage
            clean = {k: v for k, v in payload.items() if v is not None and v != []}
            result: Any = None
            if operation == "create":
                result = self._create(proxy, kind, clean)
            elif operation == "manage" and kind is StorageResourceKind.VOLUME:
                result = proxy.manage_volume(**self._volume_attrs(clean))
            elif operation == "import_record" and kind is StorageResourceKind.BACKUP:
                result = proxy.import_backup(clean["backup_service"], clean["backup_metadata"])
            elif operation == "update":
                result = self._update(proxy, kind, self._required_id(resource_id), clean)
            elif operation in {"delete", "force_delete", "unmanage"}:
                self._delete(proxy, kind, operation, self._required_id(resource_id), clean)
            else:
                result = self._action(
                    connection, proxy, kind, operation, self._required_id(resource_id), clean
                )
            identifier = self._text(result, "id") or resource_id
            name = self._text(result, "name")
            body = self._result_body(operation, result)
            return StorageMutationResult(
                resource_id=identifier,
                resource_name=name,
                request_id=correlation_id,
                body=body,
            )
        except Exception as exc:
            raise self._failure(exc) from exc

    def _create(self, proxy: Any, kind: StorageResourceKind, attrs: dict[str, Any]) -> Any:
        if kind is StorageResourceKind.VOLUME:
            return proxy.create_volume(**self._volume_attrs(attrs))
        if kind is StorageResourceKind.SNAPSHOT:
            return proxy.create_snapshot(**self._snapshot_attrs(attrs))
        if kind is StorageResourceKind.BACKUP:
            return proxy.create_backup(**self._backup_attrs(attrs))
        if kind is StorageResourceKind.VOLUME_TYPE:
            resource = proxy.create_type(
                name=attrs["name"],
                description=attrs.get("description"),
                is_public=attrs.get("is_public", True),
            )
            self._apply_type_relationships(proxy, resource.id, attrs)
            return resource
        if kind is StorageResourceKind.QOS_SPEC:
            resource = proxy.create_qos_spec(
                name=attrs["name"],
                consumer=attrs.get("consumer", "both"),
                specs=attrs.get("specs", {}),
            )
            self._apply_qos_relationships(proxy, resource.id, attrs)
            return resource
        raise AdapterError(status_code=405)

    def _update(
        self, proxy: Any, kind: StorageResourceKind, resource_id: str, attrs: dict[str, Any]
    ) -> Any:
        if kind is StorageResourceKind.VOLUME:
            resource = proxy.update_volume(resource_id, **self._only(attrs, "name", "description"))
            self._apply_metadata(proxy, "volume", resource_id, attrs)
            return resource
        if kind is StorageResourceKind.SNAPSHOT:
            resource = proxy.update_snapshot(
                resource_id, **self._only(attrs, "name", "description")
            )
            self._apply_metadata(proxy, "snapshot", resource_id, attrs)
            if attrs.get("state"):
                proxy.reset_snapshot_status(resource_id, attrs["state"])
            return resource
        if kind is StorageResourceKind.BACKUP:
            resource = proxy.update_backup(resource_id, **self._only(attrs, "name", "description"))
            if attrs.get("metadata") is not None:
                proxy.update_backup(resource_id, metadata=attrs["metadata"])
            if attrs.get("unset_metadata"):
                proxy.delete_backup_metadata(resource_id, attrs["unset_metadata"])
            if attrs.get("state"):
                proxy.reset_backup_status(resource_id, attrs["state"])
            return resource
        if kind is StorageResourceKind.VOLUME_TYPE:
            resource = proxy.update_type(
                resource_id, **self._only(attrs, "name", "description", "is_public")
            )
            self._apply_type_relationships(proxy, resource_id, attrs)
            return resource
        if kind is StorageResourceKind.QOS_SPEC:
            if attrs.get("specs"):
                proxy.update_qos_spec(resource_id, **attrs["specs"])
            if attrs.get("unset_specs"):
                proxy.delete_qos_spec_metadata(resource_id, attrs["unset_specs"])
            self._apply_qos_relationships(proxy, resource_id, attrs)
            return proxy.get_qos_spec(resource_id)
        raise AdapterError(status_code=405)

    def _delete(
        self,
        proxy: Any,
        kind: StorageResourceKind,
        operation: str,
        resource_id: str,
        attrs: dict[str, Any],
    ) -> None:
        force = operation == "force_delete" or bool(attrs.get("force"))
        if operation == "unmanage":
            if kind is StorageResourceKind.VOLUME:
                proxy.unmanage_volume(resource_id)
            elif kind is StorageResourceKind.SNAPSHOT:
                proxy.unmanage_snapshot(resource_id)
            else:
                raise AdapterError(status_code=405)
        elif kind is StorageResourceKind.VOLUME:
            proxy.delete_volume(resource_id, ignore_missing=False, force=force)
        elif kind is StorageResourceKind.SNAPSHOT:
            proxy.delete_snapshot(resource_id, ignore_missing=False, force=force)
        elif kind is StorageResourceKind.BACKUP:
            proxy.delete_backup(resource_id, ignore_missing=False, force=force)
        elif kind is StorageResourceKind.VOLUME_TYPE:
            proxy.delete_type(resource_id, ignore_missing=False)
        elif kind is StorageResourceKind.QOS_SPEC:
            proxy.delete_qos_spec(resource_id, ignore_missing=False, force=force)
        else:
            raise AdapterError(status_code=405)

    def _action(
        self,
        connection: Any,
        proxy: Any,
        kind: StorageResourceKind,
        operation: str,
        resource_id: str,
        attrs: dict[str, Any],
    ) -> Any:
        if kind is StorageResourceKind.VOLUME:
            if operation == "attach":
                return connection.compute.create_volume_attachment(
                    attrs["server_id"], volumeId=resource_id, device=attrs.get("device")
                )
            if operation == "detach":
                attachment = attrs.get("attachment_id") or resource_id
                return connection.compute.delete_volume_attachment(
                    attachment, attrs["server_id"], ignore_missing=False
                )
            if operation == "extend":
                return proxy.extend_volume(resource_id, attrs["size_gib"])
            if operation == "retype":
                return proxy.retype_volume(
                    resource_id, attrs["volume_type"], attrs.get("migration_policy", "never")
                )
            if operation == "migrate":
                return proxy.migrate_volume(
                    resource_id,
                    host=attrs.get("host"),
                    cluster=attrs.get("cluster"),
                    force_host_copy=attrs.get("force_host_copy", False),
                    lock_volume=attrs.get("lock_volume", False),
                )
            if operation == "create_transfer":
                return proxy.create_transfer(volume_id=resource_id, name=attrs.get("name"))
            if operation == "accept_transfer":
                return proxy.accept_transfer(attrs["transfer_id"], attrs["auth_key"])
            if operation == "upload_to_image":
                return proxy.upload_volume_to_image(
                    resource_id,
                    attrs["image_name"],
                    disk_format=attrs.get("disk_format"),
                    container_format=attrs.get("container_format"),
                    visibility=attrs.get("visibility"),
                    protected=attrs.get("protected"),
                    force=attrs.get("force", False),
                )
            if operation == "set_bootable":
                return proxy.set_volume_bootable_status(resource_id, attrs["bootable"])
            if operation == "set_read_only":
                return proxy.set_volume_readonly(resource_id, attrs["read_only"])
            if operation == "revert_to_snapshot":
                return proxy.revert_volume_to_snapshot(resource_id, attrs["snapshot_id"])
        if kind is StorageResourceKind.BACKUP:
            if operation == "restore":
                return proxy.restore_backup(
                    resource_id, volume=attrs.get("volume_id"), name=attrs.get("volume_name")
                )
            if operation == "export_record":
                return proxy.export_record(resource_id)
        if kind is StorageResourceKind.SERVICE:
            service = self._find_service(proxy, resource_id)
            if operation == "enable":
                return proxy.enable_service(service)
            if operation == "disable":
                return proxy.disable_service(service, reason=attrs.get("disabled_reason"))
            if operation == "freeze":
                return proxy.freeze_service(service)
            if operation == "thaw":
                return proxy.thaw_service(service)
            if operation == "failover":
                return proxy.failover_service(
                    service, cluster=attrs.get("cluster"), backend_id=attrs.get("backend_id")
                )
        raise AdapterError(status_code=400)

    def _normalize(self, kind: StorageResourceKind, resource: Any) -> StorageItem:
        data = self._mapping(resource)
        if kind is StorageResourceKind.VOLUME:
            return Volume(
                id=self._required(resource, "id"),
                name=self._text(resource, "name"),
                description=self._text(resource, "description"),
                status=self._text(resource, "status") or "unknown",
                size_gib=self._integer(resource, "size") or 0,
                volume_type=self._text(resource, "volume_type"),
                availability_zone=self._text(resource, "availability_zone"),
                bootable=self._boolean(resource, "is_bootable", "bootable"),
                encrypted=self._boolean(resource, "is_encrypted", "encrypted"),
                multiattach=self._boolean(resource, "is_multiattach", "multiattach"),
                read_only=self._boolean(resource, "is_readonly", "read_only"),
                metadata=self._string_map(data.get("metadata")),
                attachments=self._attachments(data.get("attachments")),
                snapshot_id=self._text(resource, "snapshot_id"),
                source_volume_id=self._text(resource, "source_volume_id"),
                image_id=self._image_id(data),
                project_id=self._text(resource, "project_id"),
                host=self._text(resource, "host"),
                migration_status=self._text(resource, "migration_status"),
                created_at=self._datetime(resource, "created_at"),
                updated_at=self._datetime(resource, "updated_at"),
            )
        if kind is StorageResourceKind.SNAPSHOT:
            return VolumeSnapshot(
                id=self._required(resource, "id"),
                volume_id=self._required(resource, "volume_id"),
                name=self._text(resource, "name"),
                description=self._text(resource, "description"),
                status=self._text(resource, "status") or "unknown",
                size_gib=self._integer(resource, "size") or 0,
                metadata=self._string_map(data.get("metadata")),
                project_id=self._text(resource, "project_id"),
                created_at=self._datetime(resource, "created_at"),
                updated_at=self._datetime(resource, "updated_at"),
            )
        if kind is StorageResourceKind.BACKUP:
            return VolumeBackup(
                id=self._required(resource, "id"),
                volume_id=self._text(resource, "volume_id"),
                snapshot_id=self._text(resource, "snapshot_id"),
                name=self._text(resource, "name"),
                description=self._text(resource, "description"),
                status=self._text(resource, "status") or "unknown",
                size_gib=self._integer(resource, "size"),
                is_incremental=self._boolean(resource, "is_incremental", "incremental"),
                has_dependent_backups=self._boolean(resource, "has_dependent_backups"),
                container=self._text(resource, "container"),
                availability_zone=self._text(resource, "availability_zone"),
                metadata=self._string_map(data.get("metadata")),
                project_id=self._text(resource, "project_id"),
                created_at=self._datetime(resource, "created_at"),
                updated_at=self._datetime(resource, "updated_at"),
            )
        if kind is StorageResourceKind.VOLUME_TYPE:
            encryption = data.get("encryption")
            return VolumeType(
                id=self._required(resource, "id"),
                name=self._required(resource, "name"),
                description=self._text(resource, "description"),
                is_public=self._boolean(resource, "is_public"),
                extra_specs=self._string_map(data.get("extra_specs")),
                encryption=(
                    VolumeTypeEncryption.model_validate(encryption) if encryption else None
                ),
                qos_spec_id=self._text(resource, "qos_spec_id"),
            )
        if kind is StorageResourceKind.QOS_SPEC:
            reserved = {"id", "name", "consumer", "specs"}
            specs = self._string_map(data.get("specs")) or {
                str(key): str(value) for key, value in data.items() if key not in reserved
            }
            return QosSpec(
                id=self._required(resource, "id"),
                name=self._required(resource, "name"),
                consumer=cast(
                    Literal["front-end", "back-end", "both"] | None,
                    self._text(resource, "consumer"),
                ),
                specs=specs,
            )
        if kind is StorageResourceKind.POOL:
            name = self._required(resource, "name")
            capabilities = data.get("capabilities")
            return StoragePool(
                name=name,
                host=name.split("#", 1)[0],
                backend=name.split("@", 1)[-1].split("#", 1)[0] if "@" in name else None,
                capabilities=dict(capabilities) if isinstance(capabilities, Mapping) else {},
            )
        return StorageService(
            id=self._text(resource, "id"),
            host=self._required(resource, "host"),
            binary=self._required(resource, "binary"),
            zone=self._text(resource, "zone"),
            status=self._text(resource, "status"),
            state=self._text(resource, "state"),
            cluster=self._text(resource, "cluster"),
            disabled_reason=self._text(resource, "disabled_reason"),
            updated_at=self._datetime(resource, "updated_at"),
        )

    def _apply_metadata(
        self, proxy: Any, resource: str, resource_id: str, attrs: dict[str, Any]
    ) -> None:
        metadata = attrs.get("metadata")
        unset = attrs.get("unset_metadata", [])
        if metadata:
            getattr(proxy, f"set_{resource}_metadata")(resource_id, **metadata)
        if unset:
            getattr(proxy, f"delete_{resource}_metadata")(resource_id, unset)

    def _apply_type_relationships(self, proxy: Any, type_id: str, attrs: dict[str, Any]) -> None:
        if attrs.get("extra_specs"):
            proxy.update_type_extra_specs(type_id, **attrs["extra_specs"])
        for key in attrs.get("unset_extra_specs", []):
            proxy.delete_type_extra_specs(type_id, [key])
        for project_id in attrs.get("project_ids", []):
            proxy.add_type_access(type_id, project_id)
        for project_id in attrs.get("remove_project_ids", []):
            proxy.remove_type_access(type_id, project_id)
        if attrs.get("remove_encryption"):
            proxy.delete_type_encryption(type_id)
        if attrs.get("encryption"):
            encryption = attrs["encryption"]
            try:
                proxy.update_type_encryption(type_id, **encryption)
            except Exception:
                proxy.create_type_encryption(type_id, **encryption)

    def _apply_qos_relationships(self, proxy: Any, qos_id: str, attrs: dict[str, Any]) -> None:
        for type_id in attrs.get("associate_volume_type_ids", []):
            proxy.associate_qos_spec(qos_id, type_id)
        for type_id in attrs.get("disassociate_volume_type_ids", []):
            proxy.disassociate_qos_spec(qos_id, type_id)
        if attrs.get("disassociate_all"):
            proxy.disassociate_all_qos_spec(qos_id)

    def _find_service(self, proxy: Any, service_id: str) -> Any:
        service = next(
            (
                item
                for item in proxy.services()
                if service_id
                in {
                    self._text(item, "id"),
                    self._text(item, "host"),
                    f'{self._text(item, "host")}:{self._text(item, "binary")}',
                }
            ),
            None,
        )
        if service is None:
            raise AdapterError(status_code=404)
        return service

    def _volume_attrs(self, attrs: dict[str, Any]) -> dict[str, Any]:
        aliases = {"size_gib": "size", "reference": "ref"}
        return {aliases.get(key, key): value for key, value in attrs.items()}

    def _snapshot_attrs(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return dict(attrs)

    def _backup_attrs(self, attrs: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            "incremental": "is_incremental",
        }
        return {aliases.get(key, key): value for key, value in attrs.items()}

    def _result_body(self, operation: str, result: Any) -> dict[str, Any] | None:
        if operation not in {
            "create_transfer",
            "upload_to_image",
            "export_record",
            "import_record",
        }:
            return None
        return dict(self._mapping(result))

    def _api_sort(self, sort: str) -> str:
        return "created_at" if sort == "created_at" else sort

    def _required_id(self, value: str | None) -> str:
        if not value:
            raise AdapterError(status_code=400)
        return value

    def _only(self, attrs: dict[str, Any], *names: str) -> dict[str, Any]:
        return {name: attrs[name] for name in names if name in attrs}

    def _mapping(self, resource: Any) -> Mapping[str, Any]:
        if isinstance(resource, Mapping):
            return resource
        to_dict = getattr(resource, "to_dict", None)
        value = to_dict() if callable(to_dict) else getattr(resource, "__dict__", {})
        return value if isinstance(value, Mapping) else {}

    def _value(self, resource: Any, *names: str) -> Any:
        data = self._mapping(resource)
        for name in names:
            if name in data:
                return data[name]
            value = getattr(resource, name, None)
            if value is not None:
                return value
        return None

    def _text(self, resource: Any, *names: str) -> str | None:
        value = self._value(resource, *names)
        return str(value) if value is not None and str(value) else None

    def _required(self, resource: Any, *names: str) -> str:
        value = self._text(resource, *names)
        if value is None:
            raise ValueError(f"Missing required storage field: {names[0]}")
        return value

    def _integer(self, resource: Any, *names: str) -> int | None:
        value = self._value(resource, *names)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _boolean(self, resource: Any, *names: str) -> bool | None:
        value = self._value(resource, *names)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
        return None

    def _datetime(self, resource: Any, *names: str) -> datetime | None:
        value = self._value(resource, *names)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _string_map(self, value: Any) -> dict[str, str]:
        if not isinstance(value, Mapping):
            return {}
        return {str(key): str(item) for key, item in value.items()}

    def _attachments(self, value: Any) -> list[Attachment]:
        if not isinstance(value, list):
            return []
        return [
            Attachment(
                server_id=self._text(item, "server_id", "serverId"),
                attachment_id=self._text(item, "attachment_id", "attachmentId"),
                device=self._text(item, "device"),
                attached_at=self._datetime(item, "attached_at", "attachedAt"),
            )
            for item in value
            if isinstance(item, Mapping)
        ]

    def _image_id(self, data: Mapping[str, Any]) -> str | None:
        metadata = data.get("volume_image_metadata")
        return self._text(metadata, "image_id") if isinstance(metadata, Mapping) else None

    def _correlation_id(self) -> str:
        return f"req-{uuid4()}"

    def _failure(self, exc: Exception) -> AdapterError:
        if isinstance(exc, AdapterError):
            return exc
        response = getattr(exc, "response", None)
        status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
        headers = getattr(response, "headers", {})
        request_id = headers.get("x-openstack-request-id") if hasattr(headers, "get") else None
        timeout_names = {"ConnectTimeout", "ReadTimeout", "RequestTimeout", "Timeout"}
        if (
            isinstance(exc, TimeoutError)
            or exc.__class__.__name__ in timeout_names
            or status == 504
        ):
            return AdapterTimeoutError(request_id=request_id)
        if status not in {400, 401, 403, 404, 405, 409, 413, 429}:
            status = 503
        return AdapterError(status_code=status, request_id=request_id)
