from __future__ import annotations

from datetime import datetime

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


class Problem(StrictModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str
    trace_id: str
    openstack_request_id: str | None = None
