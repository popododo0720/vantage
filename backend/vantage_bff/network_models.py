from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vantage_bff.models import PageInfo, StrictModel


class ResourceKind(StrEnum):
    NETWORK = "network"
    SUBNET = "subnet"
    PORT = "port"
    ROUTER = "router"
    FLOATING_IP = "floating_ip"
    SECURITY_GROUP = "security_group"
    SECURITY_GROUP_RULE = "security_group_rule"
    QOS_POLICY = "qos_policy"
    QOS_RULE = "qos_rule"
    RBAC_POLICY = "rbac_policy"
    LOAD_BALANCER = "load_balancer"
    LISTENER = "listener"
    POOL = "pool"
    MEMBER = "member"
    HEALTH_MONITOR = "health_monitor"
    L7_POLICY = "l7_policy"
    L7_RULE = "l7_rule"


class NetworkResource(StrictModel):
    id: str
    resource_type: ResourceKind
    name: str | None = None
    project_id: str | None = None
    status: str | None = None
    provisioning_status: str | None = None
    operating_status: str | None = None
    revision_number: int | None = Field(default=None, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    openstack_request_id: str | None = None


class NetworkResourcePage(StrictModel):
    items: list[NetworkResource]
    page: PageInfo


class NetworkField(StrictModel):
    name: str
    create: bool
    update: bool
    required: bool = False
    admin_only: bool = False
    extension: str | None = None
    immutable_reason_en: str | None = None
    immutable_reason_ko: str | None = None


class NetworkResourceContract(StrictModel):
    resource_type: ResourceKind
    service: str
    available: bool
    parent_required: bool
    fields: list[NetworkField]
    actions: list[str]


class NetworkCapabilities(StrictModel):
    neutron: bool
    octavia: bool
    resources: list[NetworkResourceContract]


class ResourceMutationRequest(StrictModel):
    parent_id: str | None = None
    rule_type: str | None = Field(default=None, max_length=64)
    attributes: dict[str, Any] = Field(default_factory=dict)
    revision_number: int | None = Field(default=None, ge=0)


class ResourceActionRequest(StrictModel):
    action: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    revision_number: int | None = Field(default=None, ge=0)


class ResourceDeleteRequest(StrictModel):
    confirmation: str = Field(min_length=1, max_length=255)
    parent_id: str | None = None
    rule_type: str | None = Field(default=None, max_length=64)
    revision_number: int | None = Field(default=None, ge=0)
    cascade: bool = False


class DeletePreview(StrictModel):
    resource: NetworkResource
    dependencies: list[dict[str, str]]
    confirmation_value: str


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
    resource_type: str
    resource_id: str | None = None
    resource_name: str | None = None
    trace_id: str
    openstack_request_ids: list[str]
    problem: OperationProblemResponse | None = None
