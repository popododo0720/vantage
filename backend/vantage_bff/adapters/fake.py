from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

from vantage_bff.adapters.base import (
    AdapterError,
    AuthenticationError,
    AuthResult,
    InstanceListResult,
    ScopeError,
    ScopeResult,
    normalized_quota,
)
from vantage_bff.models import (
    Instance,
    InstanceDetail,
    InstanceSort,
    InstanceVolume,
    Project,
    Quota,
    QuotaService,
    QuotaUnit,
    SortDirection,
    User,
)

_FAKE_NAMESPACE = UUID("8dfb4bd8-71ad-4fc8-9a76-d7583a842e8f")
_FAKE_INSTANCE_COUNTS = {"project-alpha": 37, "project-beta": 63}


class FakeOpenStackAdapter:
    """Deterministic development adapter. It never contains production credentials."""

    _projects = (
        Project(id="project-alpha", name="Alpha", domain_id="default", enabled=True),
        Project(id="project-beta", name="Beta", domain_id="default", enabled=True),
    )

    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        if password != "vantage":
            raise AuthenticationError
        visible = self._projects if username != "limited" else self._projects[:1]
        return AuthResult(
            user=User(id=f"user-{username}", name=username, domain_id=domain),
            projects=visible,
            regions=("RegionOne", "RegionTwo"),
            auth_context={
                "unscoped_token": secrets.token_urlsafe(32),
                "catalog": {"identity": "fake://keystone"},
            },
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult:
        projects = {project.id: project for project in self._projects}
        if project_id not in projects or region not in {"RegionOne", "RegionTwo"}:
            raise ScopeError
        return ScopeResult(
            project=projects[project_id],
            region=region,
            auth_context={
                **auth_context,
                "scoped_token": secrets.token_urlsafe(32),
                "project_id": project_id,
                "region": region,
            },
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        del auth_context, region
        multiplier = 1 if project_id == "project-alpha" else 2
        instance_count = _FAKE_INSTANCE_COUNTS[project_id]
        raw = {
            QuotaService.COMPUTE: (
                (
                    "instances",
                    instance_count,
                    0,
                    80 if project_id == "project-alpha" else 120,
                    QuotaUnit.COUNT,
                ),
                ("cores", 18 * multiplier, 2, 40, QuotaUnit.COUNT),
                ("ram_mib", 49152 * multiplier, 0, 98304, QuotaUnit.MIB),
            ),
            QuotaService.NETWORK: (
                ("floating_ips", 3 * multiplier, 0, 10, QuotaUnit.COUNT),
            ),
            QuotaService.STORAGE: (
                ("volumes", 8 * multiplier, 0, 20, QuotaUnit.COUNT),
                ("gigabytes", 460 * multiplier, 40, 1000, QuotaUnit.GIB),
                ("snapshots", 4 * multiplier, 0, 20, QuotaUnit.COUNT),
                ("backups", multiplier, 0, 10, QuotaUnit.COUNT),
                ("backup_gigabytes", 80 * multiplier, 0, 500, QuotaUnit.GIB),
            ),
        }
        return tuple(
            normalized_quota(
                service=service,
                resource=resource,
                used=used,
                reserved=reserved,
                limit=limit,
                unit=unit,
            )
            for resource, used, reserved, limit, unit in raw[service]
        )

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
        self._require_project_scope(auth_context, project_id, region)
        instances = list(self._instances(project_id))
        if name is not None:
            instances = [
                instance
                for instance in instances
                if instance.name is not None and name.casefold() in instance.name.casefold()
            ]
        if status is not None:
            instances = [instance for instance in instances if instance.status == status]
        if image_id is not None:
            instances = [instance for instance in instances if instance.image == image_id]
        instances = self._sort_instances(instances, sort, direction)

        start = 0
        if marker is not None:
            marker_index = next(
                (index for index, instance in enumerate(instances) if str(instance.id) == marker),
                None,
            )
            if marker_index is None:
                raise AdapterError(status_code=400, request_id=self._request_id())
            start = marker_index + 1
        end = start + limit
        return InstanceListResult(
            items=tuple(instances[start:end]),
            has_next=end < len(instances),
            openstack_request_id=self._request_id(),
        )

    async def get_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
    ) -> InstanceDetail:
        self._require_project_scope(auth_context, project_id, region)
        instance = next(
            (item for item in self._instances(project_id) if str(item.id) == instance_id),
            None,
        )
        if instance is None:
            raise AdapterError(status_code=404, request_id=self._request_id())
        volumes = None if instance.name is None else [
            InstanceVolume(
                id=str(uuid5(_FAKE_NAMESPACE, f"{instance.id}:volume")),
                device="/dev/vda",
            )
        ]
        return InstanceDetail(
            **instance.model_dump(),
            volumes=volumes,
            openstack_request_id=self._request_id(),
        )

    def _require_project_scope(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
    ) -> None:
        if (
            auth_context.get("project_id") != project_id
            or auth_context.get("region") != region
        ):
            raise AdapterError(status_code=401, request_id=self._request_id())

    def _instances(self, project_id: str) -> tuple[Instance, ...]:
        count = _FAKE_INSTANCE_COUNTS[project_id]
        project_label = "alpha" if project_id == "project-alpha" else "beta"
        image_id = str(uuid5(_FAKE_NAMESPACE, f"{project_id}:image"))
        statuses = ("ACTIVE", "SHUTOFF", "ACTIVE", "PAUSED", "ERROR")
        items: list[Instance] = []
        for index in range(count):
            partial = index == count - 1
            instance_id = uuid5(_FAKE_NAMESPACE, f"{project_id}:instance:{index}")
            items.append(
                Instance(
                    id=instance_id,
                    status="UNKNOWN" if partial else statuses[index % len(statuses)],
                    name=None if partial else f"{project_label}-vm-{index + 1:02d}",
                    created_at=(
                        None
                        if partial
                        else datetime(2026, 1, 1, 9, tzinfo=UTC) + timedelta(hours=index)
                    ),
                    flavor=None if partial else ("m1.medium" if index % 2 else "m1.small"),
                    image=None if partial else image_id,
                    addresses=(
                        None
                        if partial
                        else [
                            "private: "
                            f"10.{1 if project_id == 'project-alpha' else 2}.0.{index + 10}"
                        ]
                    ),
                )
            )
        return tuple(items)

    def _sort_instances(
        self,
        instances: list[Instance],
        sort: InstanceSort,
        direction: SortDirection,
    ) -> list[Instance]:
        reverse = direction is SortDirection.DESC
        if sort is InstanceSort.CREATED_AT:
            present = [instance for instance in instances if instance.created_at is not None]
            missing = [instance for instance in instances if instance.created_at is None]
            return sorted(
                present,
                key=lambda item: cast(datetime, item.created_at),
                reverse=reverse,
            ) + missing
        if sort is InstanceSort.NAME:
            named = [instance for instance in instances if instance.name is not None]
            unnamed = [instance for instance in instances if instance.name is None]
            return sorted(named, key=lambda item: item.name or "", reverse=reverse) + unnamed
        return sorted(instances, key=lambda item: item.status, reverse=reverse)

    def _request_id(self) -> str:
        return f"req-{uuid4()}"
