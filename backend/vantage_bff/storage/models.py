from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from vantage_bff.models import PageInfo, StrictModel


class StorageSort(StrEnum):
    CREATED_AT = "created_at"
    NAME = "name"
    STATUS = "status"


class StorageResourceKind(StrEnum):
    VOLUME = "volume"
    SNAPSHOT = "snapshot"
    BACKUP = "backup"
    VOLUME_TYPE = "volume_type"
    QOS_SPEC = "qos_spec"
    POOL = "pool"
    SERVICE = "service"


class Attachment(StrictModel):
    server_id: str | None = None
    attachment_id: str | None = None
    device: str | None = None
    attached_at: datetime | None = None


class Volume(StrictModel):
    id: str
    name: str | None = None
    description: str | None = None
    status: str
    size_gib: int = Field(ge=0)
    volume_type: str | None = None
    availability_zone: str | None = None
    bootable: bool | None = None
    encrypted: bool | None = None
    multiattach: bool | None = None
    read_only: bool | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    attachments: list[Attachment] = Field(default_factory=list)
    snapshot_id: str | None = None
    source_volume_id: str | None = None
    image_id: str | None = None
    project_id: str | None = None
    host: str | None = None
    migration_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    openstack_request_id: str | None = None


class VolumeSnapshot(StrictModel):
    id: str
    volume_id: str
    name: str | None = None
    description: str | None = None
    status: str
    size_gib: int = Field(ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)
    project_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    openstack_request_id: str | None = None


class VolumeBackup(StrictModel):
    id: str
    volume_id: str | None = None
    snapshot_id: str | None = None
    name: str | None = None
    description: str | None = None
    status: str
    size_gib: int | None = Field(default=None, ge=0)
    is_incremental: bool | None = None
    has_dependent_backups: bool | None = None
    container: str | None = None
    availability_zone: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    project_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    openstack_request_id: str | None = None


class VolumeTypeEncryption(StrictModel):
    provider: str
    cipher: str | None = None
    key_size: int | None = Field(default=None, ge=1)
    control_location: Literal["front-end", "back-end"] | None = None


class VolumeType(StrictModel):
    id: str
    name: str
    description: str | None = None
    is_public: bool | None = None
    extra_specs: dict[str, str] = Field(default_factory=dict)
    project_ids: list[str] = Field(default_factory=list)
    encryption: VolumeTypeEncryption | None = None
    qos_spec_id: str | None = None
    openstack_request_id: str | None = None


class QosSpec(StrictModel):
    id: str
    name: str
    consumer: Literal["front-end", "back-end", "both"] | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    volume_type_ids: list[str] = Field(default_factory=list)
    openstack_request_id: str | None = None


class StoragePool(StrictModel):
    name: str
    host: str | None = None
    backend: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class StorageService(StrictModel):
    id: str | None = None
    host: str
    binary: str
    zone: str | None = None
    status: str | None = None
    state: str | None = None
    cluster: str | None = None
    disabled_reason: str | None = None
    updated_at: datetime | None = None


StorageItem = (
    Volume | VolumeSnapshot | VolumeBackup | VolumeType | QosSpec | StoragePool | StorageService
)


class StoragePage(StrictModel):
    items: list[StorageItem]
    page: PageInfo
    partial_errors: list[dict[str, str]] = Field(default_factory=list)


class VolumeCreate(StrictModel):
    size_gib: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    volume_type: str | None = None
    availability_zone: str | None = None
    snapshot_id: str | None = None
    source_volume_id: str | None = None
    backup_id: str | None = None
    image_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    scheduler_hints: dict[str, Any] = Field(default_factory=dict)
    multiattach: bool | None = None

    @model_validator(mode="after")
    def one_source(self) -> VolumeCreate:
        sources = [self.snapshot_id, self.source_volume_id, self.backup_id, self.image_id]
        if sum(value is not None for value in sources) > 1:
            raise ValueError("Only one volume source may be selected")
        return self


class VolumePatch(StrictModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, str] | None = None
    unset_metadata: list[str] = Field(default_factory=list)


class VolumeAction(StrEnum):
    ATTACH = "attach"
    DETACH = "detach"
    EXTEND = "extend"
    RETYPE = "retype"
    MIGRATE = "migrate"
    CREATE_TRANSFER = "create_transfer"
    ACCEPT_TRANSFER = "accept_transfer"
    UPLOAD_TO_IMAGE = "upload_to_image"
    SET_BOOTABLE = "set_bootable"
    SET_READ_ONLY = "set_read_only"
    FORCE_DELETE = "force_delete"
    REVERT_TO_SNAPSHOT = "revert_to_snapshot"
    UNMANAGE = "unmanage"


class VolumeActionRequest(StrictModel):
    action: VolumeAction
    server_id: str | None = None
    attachment_id: str | None = None
    device: str | None = None
    size_gib: int | None = Field(default=None, ge=1)
    volume_type: str | None = None
    migration_policy: Literal["never", "on-demand"] | None = None
    host: str | None = None
    cluster: str | None = None
    force_host_copy: bool = False
    lock_volume: bool = False
    transfer_id: str | None = None
    auth_key: str | None = None
    image_name: str | None = None
    disk_format: str | None = None
    container_format: str | None = None
    visibility: Literal["private", "shared", "community", "public"] | None = None
    protected: bool | None = None
    bootable: bool | None = None
    read_only: bool | None = None
    snapshot_id: str | None = None
    force: bool = False
    confirmation: str | None = None


class SnapshotCreate(StrictModel):
    volume_id: str
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    force: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


class SnapshotPatch(StrictModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, str] | None = None
    unset_metadata: list[str] = Field(default_factory=list)
    state: str | None = None


class SnapshotActionRequest(StrictModel):
    action: Literal["force_delete", "unmanage"]
    confirmation: str


class BackupCreate(StrictModel):
    volume_id: str | None = None
    snapshot_id: str | None = None
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    container: str | None = None
    availability_zone: str | None = None
    incremental: bool = False
    force: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_required(self) -> BackupCreate:
        if (self.volume_id is None) == (self.snapshot_id is None):
            raise ValueError("Exactly one of volume_id or snapshot_id is required")
        return self


class BackupPatch(StrictModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, str] | None = None
    unset_metadata: list[str] = Field(default_factory=list)
    state: Literal["available", "error"] | None = None


class BackupActionRequest(StrictModel):
    action: Literal["restore", "force_delete", "export_record"]
    volume_id: str | None = None
    volume_name: str | None = None
    force: bool = False
    confirmation: str | None = None


class BackupImport(StrictModel):
    backup_service: str
    backup_metadata: str


class ManagedVolumeCreate(StrictModel):
    host: str
    reference: dict[str, str]
    name: str | None = None
    description: str | None = None
    volume_type: str | None = None
    availability_zone: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class VolumeTypeWrite(StrictModel):
    name: str
    description: str | None = None
    is_public: bool = True
    extra_specs: dict[str, str] = Field(default_factory=dict)
    unset_extra_specs: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    remove_project_ids: list[str] = Field(default_factory=list)
    encryption: VolumeTypeEncryption | None = None
    remove_encryption: bool = False


class QosSpecWrite(StrictModel):
    name: str
    consumer: Literal["front-end", "back-end", "both"] = "both"
    specs: dict[str, str] = Field(default_factory=dict)
    unset_specs: list[str] = Field(default_factory=list)
    associate_volume_type_ids: list[str] = Field(default_factory=list)
    disassociate_volume_type_ids: list[str] = Field(default_factory=list)
    disassociate_all: bool = False


class ServiceActionRequest(StrictModel):
    action: Literal["enable", "disable", "freeze", "thaw", "failover"]
    disabled_reason: str | None = None
    cluster: str | None = None
    backend_id: str | None = None
    confirmation: str


class OperationView(StrictModel):
    id: str
    kind: str
    status: str
    submitted_at: datetime
    updated_at: datetime
    resource_type: str
    resource_id: str | None = None
    resource_name: str | None = None
    openstack_request_ids: list[str] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    problem: dict[str, Any] | None = None
