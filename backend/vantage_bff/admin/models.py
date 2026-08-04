from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from vantage_bff.models import PageInfo, QuotaService, StrictModel, WidgetError


class AdminScopeType(StrEnum):
    SYSTEM = "system"
    DOMAIN = "domain"
    PROJECT = "project"


class AdminScope(StrictModel):
    type: AdminScopeType
    id: str
    name: str


class AdminSession(StrictModel):
    available_scopes: list[AdminScope]
    active_scope: AdminScope | None = None


class AdminScopeRequest(StrictModel):
    type: AdminScopeType
    id: str = Field(min_length=1, max_length=255)


IdentityKind = Literal["projects", "users", "groups", "roles"]


class IdentityResource(StrictModel):
    id: str
    name: str
    description: str | None = None
    domain_id: str | None = None
    enabled: bool | None = None
    default_project_id: str | None = None
    email: str | None = None
    parent_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class IdentityPage(StrictModel):
    items: list[IdentityResource]
    page: PageInfo


class IdentityCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    domain_id: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    default_project_id: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, min_length=1)
    parent_id: str | None = Field(default=None, max_length=255)


class IdentityUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    enabled: bool | None = None
    default_project_id: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_change(self) -> IdentityUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class RoleAssignment(StrictModel):
    id: str
    role_id: str
    actor_type: Literal["user", "group"]
    actor_id: str
    scope_type: AdminScopeType
    scope_id: str
    inherited: bool = False


class RoleAssignmentPage(StrictModel):
    items: list[RoleAssignment]
    page: PageInfo


class RoleAssignmentCreate(StrictModel):
    role_id: str = Field(min_length=1, max_length=255)
    actor_type: Literal["user", "group"]
    actor_id: str = Field(min_length=1, max_length=255)
    scope_type: AdminScopeType
    scope_id: str = Field(min_length=1, max_length=255)
    inherited: bool = False

    @model_validator(mode="after")
    def validate_system_scope(self) -> RoleAssignmentCreate:
        if self.scope_type is AdminScopeType.SYSTEM:
            if self.scope_id != "all":
                raise ValueError("System role assignments require scope_id 'all'")
            if self.inherited:
                raise ValueError("System role assignments cannot be inherited")
        return self


class AdminQuota(StrictModel):
    service: QuotaService
    resource: str
    limit: int | None
    used: int | None = Field(default=None, ge=0)
    reserved: int | None = Field(default=None, ge=0)
    default: int | None = None
    user_id: str | None = None


class AdminQuotaCollection(StrictModel):
    project_id: str
    generated_at: datetime
    quotas: list[AdminQuota]
    partial_errors: list[WidgetError]


class QuotaUpdate(StrictModel):
    values: dict[str, int]
    user_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_values(self) -> QuotaUpdate:
        if not self.values:
            raise ValueError("At least one quota value is required")
        return self


class Confirmation(StrictModel):
    confirm: str = Field(min_length=1, max_length=255)


class OperationAck(StrictModel):
    operation_id: UUID
    status: str
    trace_id: str
    replayed: bool = False


class AdminOperation(StrictModel):
    id: UUID
    kind: str
    status: str
    submitted_at: datetime
    updated_at: datetime
    target_type: str
    target_id: str | None = None
    target_name: str | None = None
    trace_id: str
    openstack_request_ids: list[str]
    problem: dict[str, Any] | None = None


class AdminListResult(StrictModel):
    items: list[IdentityResource | RoleAssignment]
    next_cursor: str | None = None
    openstack_request_id: str | None = None


class AdminMutationResult(StrictModel):
    resource: IdentityResource | RoleAssignment | None = None
    openstack_request_ids: list[str] = Field(default_factory=list)
