from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from vantage_bff.storage.models import StorageItem, StorageResourceKind


@dataclass(frozen=True, slots=True)
class StorageListResult:
    items: tuple[StorageItem, ...]
    has_next: bool = False
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class StorageMutationResult:
    resource_id: str | None = None
    resource_name: str | None = None
    request_id: str | None = None
    body: dict[str, Any] | None = None


class StorageAdapter(Protocol):
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
    ) -> StorageListResult: ...

    async def get_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        resource_id: str,
    ) -> StorageItem: ...

    async def mutate(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> StorageMutationResult: ...
