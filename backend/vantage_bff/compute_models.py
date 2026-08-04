from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from vantage_bff.models import StrictModel


class NetworkAttachmentRequest(StrictModel):
    network_id: UUID | None = None
    subnet_id: UUID | None = None
    port_id: UUID | None = None
    fixed_ip: str | None = Field(default=None, max_length=64)
    tag: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def one_attachment_source(self) -> NetworkAttachmentRequest:
        if self.port_id is not None:
            if (
                self.network_id is not None
                or self.subnet_id is not None
                or self.fixed_ip is not None
            ):
                raise ValueError("port_id cannot be combined with network, subnet, or fixed_ip")
        elif self.network_id is None:
            raise ValueError("network_id or port_id is required")
        return self


class ImageBootSource(StrictModel):
    type: Literal["image"]
    image_id: UUID
    create_boot_volume: bool = False
    volume_size_gib: int | None = Field(default=None, ge=1)
    volume_type: str | None = Field(default=None, max_length=255)
    delete_on_termination: bool = True


class VolumeBootSource(StrictModel):
    type: Literal["volume"]
    volume_id: UUID
    delete_on_termination: bool = False


class VolumeSnapshotBootSource(StrictModel):
    type: Literal["volume_snapshot"]
    snapshot_id: UUID
    volume_size_gib: int | None = Field(default=None, ge=1)
    volume_type: str | None = Field(default=None, max_length=255)
    delete_on_termination: bool = True


BootSource = Annotated[
    ImageBootSource | VolumeBootSource | VolumeSnapshotBootSource,
    Field(discriminator="type"),
]


class BlockDeviceRequest(StrictModel):
    source_type: Literal["blank", "image", "volume", "snapshot"]
    source_id: UUID | None = None
    destination_type: Literal["local", "volume"]
    boot_index: int = Field(ge=-1)
    device_name: str | None = Field(default=None, max_length=255)
    volume_size_gib: int | None = Field(default=None, ge=1)
    volume_type: str | None = Field(default=None, max_length=255)
    delete_on_termination: bool = False
    tag: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def source_is_complete(self) -> BlockDeviceRequest:
        if self.source_type != "blank" and self.source_id is None:
            raise ValueError("source_id is required for non-blank block devices")
        return self


class CreateInstanceRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)
    hostname: str | None = Field(default=None, max_length=255)
    count: int = Field(default=1, ge=1, le=100)
    boot_source: BootSource
    flavor_id: str = Field(min_length=1, max_length=255)
    availability_zone: str | None = Field(default=None, max_length=255)
    networks: list[NetworkAttachmentRequest] = Field(min_length=1, max_length=64)
    security_group_ids: list[UUID] = Field(default_factory=list, max_length=64)
    keypair_name: str | None = Field(default=None, max_length=255)
    metadata: dict[str, str] = Field(default_factory=dict)
    config_drive: bool = False
    user_data: SecretStr | None = Field(default=None, max_length=65535)
    block_devices: list[BlockDeviceRequest] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def port_security_groups_are_owned_by_neutron(self) -> CreateInstanceRequest:
        if self.security_group_ids and any(item.port_id is not None for item in self.networks):
            raise ValueError(
                "security_group_ids cannot modify an existing port; update the port via Network"
            )
        return self


class UpdateInstanceRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)
    metadata: dict[str, str] | None = None
    unset_metadata: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_change(self) -> UpdateInstanceRequest:
        if (
            self.name is None
            and self.description is None
            and self.metadata is None
            and not self.unset_metadata
        ):
            raise ValueError("at least one change is required")
        return self


class InstanceAction(StrEnum):
    START = "start"
    STOP = "stop"
    SOFT_REBOOT = "soft_reboot"
    HARD_REBOOT = "hard_reboot"
    PAUSE = "pause"
    UNPAUSE = "unpause"
    SUSPEND = "suspend"
    RESUME = "resume"
    SHELVE = "shelve"
    UNSHELVE = "unshelve"
    RESCUE = "rescue"
    UNRESCUE = "unrescue"
    LOCK = "lock"
    UNLOCK = "unlock"


class InstanceActionRequest(StrictModel):
    action: InstanceAction
    image_id: UUID | None = None
    locked_reason: str | None = Field(default=None, max_length=255)


class ResizeInstanceRequest(StrictModel):
    flavor_id: str = Field(min_length=1, max_length=255)


class RebuildInstanceRequest(StrictModel):
    image_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, str] | None = None
    preserve_ephemeral: bool = False
    user_data: SecretStr | None = Field(default=None, max_length=65535)


class SnapshotInstanceRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    metadata: dict[str, str] = Field(default_factory=dict)


class ConsoleRequest(StrictModel):
    protocol: Literal["vnc"] = "vnc"
    type: Literal["novnc"] = "novnc"


class ConsoleSession(StrictModel):
    instance_id: UUID
    type: Literal["novnc"] = "novnc"
    url: str
    expires_at: datetime
    openstack_request_id: str | None = None


class DeletePreview(StrictModel):
    instance_id: UUID
    attached_volume_ids: list[str]
    network_contract: str = "/api/v1/instances/{instance_id}/interfaces"
    floating_ip_contract: str = "/api/v1/floating-ips?instance_id={instance_id}"
    warning: str


class ImageCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    disk_format: str = Field(min_length=1, max_length=32)
    container_format: str = Field(default="bare", min_length=1, max_length=32)
    visibility: Literal["private", "shared", "community", "public"] = "private"
    min_disk_gib: int = Field(default=0, ge=0)
    min_ram_mib: int = Field(default=0, ge=0)
    protected: bool = False
    properties: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    import_uri: str | None = Field(default=None, max_length=2048)


class ImageUpdateRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: Literal["private", "shared", "community", "public"] | None = None
    min_disk_gib: int | None = Field(default=None, ge=0)
    min_ram_mib: int | None = Field(default=None, ge=0)
    protected: bool | None = None
    properties: dict[str, str] | None = None
    unset_properties: list[str] = Field(default_factory=list)
    tags: list[str] | None = None

    @model_validator(mode="after")
    def has_change(self) -> ImageUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        return self


class ImageActionRequest(StrictModel):
    action: Literal["deactivate", "reactivate"]


class ImageMemberRequest(StrictModel):
    project_id: str = Field(min_length=1, max_length=255)


class FlavorCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    id: str | None = Field(default=None, max_length=255)
    vcpus: int = Field(ge=1)
    ram_mib: int = Field(ge=1)
    disk_gib: int = Field(default=0, ge=0)
    ephemeral_gib: int = Field(default=0, ge=0)
    swap_mib: int = Field(default=0, ge=0)
    rxtx_factor: float = Field(default=1.0, gt=0)
    is_public: bool = True
    description: str | None = Field(default=None, max_length=65535)
    extra_specs: dict[str, str] = Field(default_factory=dict)
    access_project_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def access_requires_private_flavor(self) -> FlavorCreateRequest:
        if self.is_public and self.access_project_ids:
            raise ValueError("project access applies only to private flavors")
        return self


class FlavorUpdateRequest(StrictModel):
    description: str | None = Field(default=None, max_length=65535)

    @model_validator(mode="after")
    def has_change(self) -> FlavorUpdateRequest:
        if "description" not in self.model_fields_set:
            raise ValueError("description is required")
        return self


class FlavorExtraSpecsRequest(StrictModel):
    specs: dict[str, str] = Field(min_length=1)


class FlavorAccessRequest(StrictModel):
    project_id: str = Field(min_length=1, max_length=255)


class OperationTargetResponse(StrictModel):
    resource_type: str
    resource_id: str | None = None
    resource_name: str | None = None


class OperationProblemResponse(StrictModel):
    status: int
    code: str
    title: str
    detail: str
    openstack_request_id: str | None = None


class OperationResponse(StrictModel):
    id: UUID
    kind: str
    status: str
    submitted_at: datetime
    updated_at: datetime
    target: OperationTargetResponse
    trace_id: str
    openstack_request_ids: list[str]
    problem: OperationProblemResponse | None = None


class MutationResult(StrictModel):
    resource_id: str | None = None
    resource_name: str | None = None
    openstack_request_id: str | None = None


class RemoteConsoleResult(StrictModel):
    url: str
    openstack_request_id: str | None = None
