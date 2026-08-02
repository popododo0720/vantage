from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, NotRequired, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    domain: str = Field(min_length=1, max_length=255)


class SessionPreferenceRequest(StrictModel):
    locale: str = Field(pattern="^(en|ko)$")


class User(StrictModel):
    id: str
    name: str
    domain_id: str | None = None


class Project(StrictModel):
    id: str
    name: str
    domain_id: str | None = None
    enabled: bool | None = None


class ScopeRequest(StrictModel):
    project_id: str
    region: str


class Scope(StrictModel):
    project: Project
    region: str


class SessionResponse(StrictModel):
    user: User
    active_scope: Scope | None = None
    expires_at: datetime
    regions: list[str]
    locale: str


class PageInfo(StrictModel):
    number: int
    size: int
    item_from: int
    item_to: int
    total_items: int | None
    total_pages: int | None
    has_previous: bool
    has_next: bool
    navigable_pages: list[int]
    openstack_request_id: str | None = None


class ProjectPage(StrictModel):
    items: list[Project]
    page: PageInfo


class QuotaService(StrEnum):
    COMPUTE = "compute"
    NETWORK = "network"
    STORAGE = "storage"


class QuotaUnit(StrEnum):
    COUNT = "count"
    MIB = "MiB"
    GIB = "GiB"


class QuotaState(StrEnum):
    NORMAL = "normal"
    WATCH = "watch"
    HIGH = "high"
    UNKNOWN = "unknown"


QuotaResource = Literal[
    "instances",
    "cores",
    "ram_mib",
    "volumes",
    "gigabytes",
    "snapshots",
    "backups",
    "backup_gigabytes",
    "floating_ips",
]


class Quota(StrictModel):
    service: QuotaService
    resource: QuotaResource
    used: int = Field(ge=0)
    reserved: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=0)
    unit: QuotaUnit
    state: QuotaState


class WidgetError(TypedDict):
    code: str
    message: str
    openstack_request_id: NotRequired[str]


class InstanceSummary(StrictModel):
    total: int = Field(ge=0)
    active: int | None = Field(default=None, ge=0)
    stopped: int | None = Field(default=None, ge=0)
    error: int | None = Field(default=None, ge=0)


class ProjectOverview(StrictModel):
    scope: Scope
    generated_at: datetime
    stale: bool = False
    quotas: list[Quota]
    instance_summary: InstanceSummary | None = None
    partial_errors: list[WidgetError]


class QuotaCollection(StrictModel):
    scope: Scope
    generated_at: datetime
    stale: bool = False
    quotas: list[Quota]
    partial_errors: list[WidgetError]


class InstanceSort(StrEnum):
    CREATED_AT = "created_at"
    NAME = "name"
    STATUS = "status"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class Instance(StrictModel):
    id: UUID
    status: str
    name: str | None
    created_at: datetime | None
    flavor: str | None
    image: str | None
    addresses: list[str] | None


class InstanceVolume(StrictModel):
    id: str
    device: str | None = None


class InstancePage(StrictModel):
    items: list[Instance]
    page: PageInfo


class InstanceDetail(Instance):
    volumes: list[InstanceVolume] | None
    openstack_request_id: str | None


class ImageVisibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    COMMUNITY = "community"
    PUBLIC = "public"


class Image(StrictModel):
    id: UUID
    name: str | None = None
    status: str | None = None
    visibility: ImageVisibility | None = None
    disk_format: str | None = None
    container_format: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    min_disk_gib: int | None = Field(default=None, ge=0)
    min_ram_mib: int | None = Field(default=None, ge=0)
    created_at: datetime | None = None


class ImagePage(StrictModel):
    items: list[Image]
    page: PageInfo


class Flavor(StrictModel):
    id: str
    name: str | None = None
    vcpus: int | None = Field(default=None, ge=1)
    ram_mib: int | None = Field(default=None, ge=1)
    disk_gib: int | None = Field(default=None, ge=0)
    ephemeral_gib: int | None = Field(default=None, ge=0)
    is_public: bool | None = None


class FlavorPage(StrictModel):
    items: list[Flavor]
    page: PageInfo


class KeyPairType(StrEnum):
    SSH = "ssh"
    X509 = "x509"


class KeyPair(StrictModel):
    name: str
    type: KeyPairType | None = None
    fingerprint: str | None = None
    public_key_preview: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class KeyPairPage(StrictModel):
    items: list[KeyPair]
    page: PageInfo


class Network(StrictModel):
    id: UUID
    name: str | None = None
    status: str | None = None
    shared: bool | None = None
    external: bool | None = None
    mtu: int | None = Field(default=None, ge=0)
    subnet_count: int | None = Field(default=None, ge=0)


class NetworkPage(StrictModel):
    items: list[Network]
    page: PageInfo


class SecurityGroup(StrictModel):
    id: UUID
    name: str | None = None
    description: str | None = None
    rule_count: int | None = Field(default=None, ge=0)
    revision_number: int | None = Field(default=None, ge=0)


class SecurityGroupPage(StrictModel):
    items: list[SecurityGroup]
    page: PageInfo


class Problem(StrictModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str
    trace_id: str
    openstack_request_id: str | None = None
