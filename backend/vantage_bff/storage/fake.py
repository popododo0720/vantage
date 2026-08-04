from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from vantage_bff.adapters.base import AdapterError
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
)


class FakeStorageAdapter:
    """Mutable, credential-free Cinder simulator scoped by project and region."""

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str, StorageResourceKind], dict[str, StorageItem]] = {}

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
        self._require_scope(auth_context, project_id, region)
        del all_projects
        items = list(self._collection(project_id, region, kind).values())
        for field, expected in filters.items():
            items = [item for item in items if self._matches(item, field, expected)]
        items.sort(key=lambda item: self._sort_value(item, sort), reverse=direction == "desc")
        start = 0
        if marker:
            index = next(
                (i for i, item in enumerate(items) if self._identity(item) == marker), None
            )
            if index is None:
                raise AdapterError(status_code=400, request_id=self._request_id())
            start = index + 1
        page = items[start : start + limit]
        return StorageListResult(
            items=tuple(page),
            has_next=start + limit < len(items),
            request_id=self._request_id(),
        )

    async def get_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        resource_id: str,
    ) -> StorageItem:
        self._require_scope(auth_context, project_id, region)
        resource = self._collection(project_id, region, kind).get(resource_id)
        if resource is None:
            raise AdapterError(status_code=404, request_id=self._request_id())
        return resource

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
        self._require_scope(auth_context, project_id, region)
        collection = self._collection(project_id, region, kind)
        request_id = self._request_id()
        if operation in {"create", "manage", "import_record"}:
            resource = self._create(kind, project_id, payload)
            collection[self._identity(resource)] = resource
            return StorageMutationResult(
                resource_id=self._identity(resource),
                resource_name=getattr(resource, "name", None),
                request_id=request_id,
                body=(resource.model_dump(mode="json") if operation == "import_record" else None),
            )
        if resource_id is None or resource_id not in collection:
            raise AdapterError(status_code=404, request_id=request_id)
        resource = collection[resource_id]
        if operation in {"delete", "force_delete", "unmanage"}:
            status = getattr(resource, "status", None)
            if operation == "delete" and status not in {None, "available", "error"}:
                raise AdapterError(status_code=409, request_id=request_id)
            if operation == "delete" and isinstance(resource, Volume) and resource.attachments:
                raise AdapterError(status_code=409, request_id=request_id)
            del collection[resource_id]
            return StorageMutationResult(resource_id=resource_id, request_id=request_id)
        if operation == "update":
            updated = self._update(resource, payload)
            collection[resource_id] = updated
            return StorageMutationResult(
                resource_id=resource_id,
                resource_name=getattr(updated, "name", None),
                request_id=request_id,
            )
        updated, body = self._action(resource, operation, payload)
        collection[resource_id] = updated
        return StorageMutationResult(
            resource_id=resource_id,
            resource_name=getattr(updated, "name", None),
            request_id=request_id,
            body=body,
        )

    def _collection(
        self, project_id: str, region: str, kind: StorageResourceKind
    ) -> dict[str, StorageItem]:
        key = (project_id, region, kind)
        if key not in self._resources:
            self._resources[key] = {
                self._identity(item): item for item in self._seed(project_id, kind)
            }
        return self._resources[key]

    def _seed(self, project_id: str, kind: StorageResourceKind) -> tuple[StorageItem, ...]:
        if kind is StorageResourceKind.VOLUME:
            return tuple(
                Volume(
                    id=str(uuid5(NAMESPACE_URL, f"{project_id}:volume:{index}")),
                    name=f"{project_id.removeprefix('project-')}-volume-{index + 1:02d}",
                    description="Development volume",
                    status="in-use" if index == 0 else "available",
                    size_gib=20 + index,
                    volume_type="__DEFAULT__",
                    availability_zone="nova",
                    bootable=index == 0,
                    encrypted=False,
                    multiattach=False,
                    metadata={"environment": "development"},
                    attachments=(
                        [Attachment(server_id="fake-server", device="/dev/vdb")]
                        if index == 0
                        else []
                    ),
                    project_id=project_id,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
                )
                for index in range(31)
            )
        if kind is StorageResourceKind.SNAPSHOT:
            volume_id = str(uuid5(NAMESPACE_URL, f"{project_id}:volume:1"))
            return tuple(
                VolumeSnapshot(
                    id=str(uuid5(NAMESPACE_URL, f"{project_id}:snapshot:{index}")),
                    volume_id=volume_id,
                    name=f"snapshot-{index + 1:02d}",
                    status="available",
                    size_gib=21,
                    project_id=project_id,
                    created_at=datetime(2026, 2, 1, tzinfo=UTC) + timedelta(days=index),
                )
                for index in range(12)
            )
        if kind is StorageResourceKind.BACKUP:
            volume_id = str(uuid5(NAMESPACE_URL, f"{project_id}:volume:2"))
            return tuple(
                VolumeBackup(
                    id=str(uuid5(NAMESPACE_URL, f"{project_id}:backup:{index}")),
                    volume_id=volume_id,
                    name=f"backup-{index + 1:02d}",
                    status="available",
                    size_gib=22,
                    is_incremental=index > 0,
                    container="volumebackups",
                    project_id=project_id,
                    created_at=datetime(2026, 3, 1, tzinfo=UTC) + timedelta(days=index),
                )
                for index in range(12)
            )
        if kind is StorageResourceKind.VOLUME_TYPE:
            return (
                VolumeType(id="type-default", name="__DEFAULT__", is_public=True),
                VolumeType(
                    id="type-fast",
                    name="fast",
                    description="Example non-backend-specific type",
                    is_public=True,
                    extra_specs={"capabilities:performance": "high"},
                ),
            )
        if kind is StorageResourceKind.QOS_SPEC:
            return (QosSpec(id="qos-standard", name="standard", consumer="both"),)
        if kind is StorageResourceKind.POOL:
            return (
                StoragePool(
                    name="cinder@backend#pool",
                    host="cinder@backend",
                    backend="backend",
                    capabilities={"volume_backend_name": "backend", "free_capacity_gb": 512},
                ),
            )
        return (
            StorageService(
                id="cinder-volume@backend",
                host="cinder",
                binary="cinder-volume",
                zone="nova",
                status="enabled",
                state="up",
            ),
        )

    def _create(
        self, kind: StorageResourceKind, project_id: str, payload: dict[str, Any]
    ) -> StorageItem:
        identifier = str(uuid4())
        now = datetime.now(UTC)
        if kind is StorageResourceKind.VOLUME:
            return Volume(
                id=identifier,
                name=payload.get("name"),
                description=payload.get("description"),
                status="creating",
                size_gib=int(payload.get("size_gib", 1)),
                volume_type=payload.get("volume_type"),
                availability_zone=payload.get("availability_zone"),
                metadata=payload.get("metadata", {}),
                snapshot_id=payload.get("snapshot_id"),
                source_volume_id=payload.get("source_volume_id"),
                image_id=payload.get("image_id"),
                multiattach=payload.get("multiattach"),
                project_id=project_id,
                created_at=now,
            )
        if kind is StorageResourceKind.SNAPSHOT:
            return VolumeSnapshot(
                id=identifier,
                volume_id=str(payload["volume_id"]),
                name=payload.get("name"),
                description=payload.get("description"),
                status="creating",
                size_gib=1,
                metadata=payload.get("metadata", {}),
                project_id=project_id,
                created_at=now,
            )
        if kind is StorageResourceKind.BACKUP:
            return VolumeBackup(
                id=identifier,
                volume_id=payload.get("volume_id"),
                snapshot_id=payload.get("snapshot_id"),
                name=payload.get("name"),
                description=payload.get("description"),
                status="creating",
                is_incremental=payload.get("incremental", False),
                container=payload.get("container"),
                availability_zone=payload.get("availability_zone"),
                metadata=payload.get("metadata", {}),
                project_id=project_id,
                created_at=now,
            )
        if kind is StorageResourceKind.VOLUME_TYPE:
            return VolumeType(
                id=identifier,
                name=str(payload["name"]),
                description=payload.get("description"),
                is_public=payload.get("is_public", True),
                extra_specs=payload.get("extra_specs", {}),
                project_ids=payload.get("project_ids", []),
                encryption=payload.get("encryption"),
            )
        if kind is StorageResourceKind.QOS_SPEC:
            return QosSpec(
                id=identifier,
                name=str(payload["name"]),
                consumer=payload.get("consumer", "both"),
                specs=payload.get("specs", {}),
                volume_type_ids=payload.get("associate_volume_type_ids", []),
            )
        raise AdapterError(status_code=405, request_id=self._request_id())

    def _update(self, resource: StorageItem, payload: dict[str, Any]) -> StorageItem:
        values = resource.model_dump()
        for key, value in payload.items():
            if key.startswith("unset_") or key.startswith("remove_") or value is None:
                continue
            if key in values:
                values[key] = value
        for field in ("metadata", "extra_specs", "specs"):
            unset = payload.get(f"unset_{field}", [])
            if field in values and isinstance(values[field], dict):
                values[field] = {k: v for k, v in values[field].items() if k not in unset}
        return type(resource).model_validate(values)

    def _action(
        self, resource: StorageItem, operation: str, payload: dict[str, Any]
    ) -> tuple[StorageItem, dict[str, Any] | None]:
        values = resource.model_dump()
        body: dict[str, Any] | None = None
        if operation == "attach" and isinstance(resource, Volume):
            values["attachments"] = [
                *resource.attachments,
                Attachment(server_id=payload.get("server_id"), device=payload.get("device")),
            ]
            values["status"] = "in-use"
        elif operation == "detach" and isinstance(resource, Volume):
            server = payload.get("server_id")
            values["attachments"] = [a for a in resource.attachments if a.server_id != server]
            values["status"] = "available" if not values["attachments"] else "in-use"
        elif operation == "extend" and isinstance(resource, Volume):
            size = int(payload.get("size_gib", 0))
            if size <= resource.size_gib:
                raise AdapterError(status_code=409, request_id=self._request_id())
            values["size_gib"] = size
            values["status"] = "extending"
        elif operation == "retype" and isinstance(resource, Volume):
            values["volume_type"] = payload.get("volume_type")
            values["status"] = "retyping"
        elif operation == "migrate" and isinstance(resource, Volume):
            values["migration_status"] = "starting"
        elif operation == "set_bootable" and isinstance(resource, Volume):
            values["bootable"] = payload.get("bootable")
        elif operation == "set_read_only" and isinstance(resource, Volume):
            values["read_only"] = payload.get("read_only")
        elif operation == "create_transfer":
            body = {"transfer_id": str(uuid4()), "auth_key": "shown-once-fake-auth-key"}
        elif operation == "upload_to_image":
            body = {"image_id": str(uuid4()), "image_name": payload.get("image_name")}
        elif operation == "export_record":
            body = {"backup_service": "fake", "backup_metadata": "shown-once-fake-record"}
        elif operation == "restore":
            values["status"] = "restoring"
        elif operation in {"enable", "disable", "freeze", "thaw", "failover"}:
            if operation in {"enable", "disable"}:
                values["status"] = f"{operation}d"
            elif operation in {"freeze", "thaw"}:
                values["state"] = "down" if operation == "freeze" else "up"
        elif operation in {"accept_transfer", "revert_to_snapshot"}:
            pass
        else:
            raise AdapterError(status_code=400, request_id=self._request_id())
        return type(resource).model_validate(values), body

    def _require_scope(self, auth: dict[str, Any], project_id: str, region: str) -> None:
        if auth.get("project_id") != project_id or auth.get("region") != region:
            raise AdapterError(status_code=401, request_id=self._request_id())

    def _identity(self, item: Any) -> str:
        return str(getattr(item, "id", None) or getattr(item, "name", None) or item.host)

    def _sort_value(self, item: StorageItem, sort: str) -> tuple[bool, str]:
        field = "created_at" if sort == "created_at" else sort
        value = getattr(item, field, None)
        return value is None, str(value or "").casefold()

    def _matches(self, item: StorageItem, field: str, expected: str) -> bool:
        value = getattr(item, field, None)
        if field == "name":
            return expected.casefold() in str(value or "").casefold()
        return str(value or "").casefold() == expected.casefold()

    def _request_id(self) -> str:
        return f"req-{uuid4()}"
