from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

from vantage_bff.adapters.base import (
    AdapterError,
    AuthenticationError,
    AuthResult,
    InstanceListResult,
    ProvisioningListResult,
    ScopeError,
    ScopeResult,
    normalized_quota,
)
from vantage_bff.compute_models import MutationResult, RemoteConsoleResult
from vantage_bff.models import (
    Flavor,
    Image,
    ImageVisibility,
    Instance,
    InstanceDetail,
    InstanceSort,
    InstanceVolume,
    KeyPair,
    KeyPairType,
    Network,
    Project,
    Quota,
    QuotaService,
    QuotaUnit,
    SecurityGroup,
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

    def __init__(self) -> None:
        self._created: dict[str, list[Instance]] = {}
        self._deleted: set[UUID] = set()
        self._instance_updates: dict[UUID, dict[str, Any]] = {}

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
            QuotaService.NETWORK: (("floating_ips", 3 * multiplier, 0, 10, QuotaUnit.COUNT),),
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
        self._ensure_state()
        self._require_project_scope(auth_context, project_id, region)
        instance = next(
            (item for item in self._instances(project_id) if str(item.id) == instance_id),
            None,
        )
        if instance is None:
            raise AdapterError(status_code=404, request_id=self._request_id())
        volumes = (
            None
            if instance.name is None
            else [
                InstanceVolume(
                    id=str(uuid5(_FAKE_NAMESPACE, f"{instance.id}:volume")),
                    device="/dev/vda",
                )
            ]
        )
        updates = self._instance_updates.get(instance.id, {})
        return InstanceDetail(
            **instance.model_copy(
                update={key: updates[key] for key in ("name", "status") if key in updates}
            ).model_dump(),
            volumes=volumes,
            description=updates.get("description"),
            metadata=updates.get("metadata"),
            openstack_request_id=self._request_id(),
        )

    async def create_instances(
        self, auth_context: dict[str, Any], project_id: str, region: str, payload: dict[str, Any]
    ) -> MutationResult:
        self._ensure_state()
        self._require_project_scope(auth_context, project_id, region)
        count = int(payload.get("count", 1))
        created: list[Instance] = []
        for index in range(count):
            instance_id = uuid4()
            name = str(payload["name"])
            created.append(
                Instance(
                    id=instance_id,
                    status="BUILD",
                    name=name if count == 1 else f"{name}-{index + 1}",
                    created_at=datetime.now(UTC),
                    flavor=str(payload["flavor_id"]),
                    image=str(payload.get("boot_source", {}).get("image_id") or "volume"),
                    addresses=[],
                )
            )
        self._created.setdefault(project_id, []).extend(created)
        return MutationResult(
            resource_id=str(created[0].id),
            resource_name=created[0].name,
            openstack_request_id=self._request_id(),
        )

    async def update_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
        payload: dict[str, Any],
    ) -> MutationResult:
        instance = await self.get_instance(auth_context, project_id, region, instance_id)
        updates = self._instance_updates.setdefault(instance.id, {})
        if payload.get("name") is not None:
            updates["name"] = payload["name"]
        if "description" in payload and payload["description"] is not None:
            updates["description"] = payload["description"]
        if payload.get("metadata") is not None or payload.get("unset_metadata"):
            metadata = dict(updates.get("metadata", instance.metadata or {}))
            metadata.update(payload.get("metadata") or {})
            for key in payload.get("unset_metadata", []):
                metadata.pop(key, None)
            updates["metadata"] = metadata
        return MutationResult(
            resource_id=instance_id,
            resource_name=str(updates.get("name", instance.name or "")) or None,
            openstack_request_id=self._request_id(),
        )

    async def delete_instance(
        self, auth_context: dict[str, Any], project_id: str, region: str, instance_id: str
    ) -> MutationResult:
        instance = await self.get_instance(auth_context, project_id, region, instance_id)
        self._deleted.add(instance.id)
        return MutationResult(resource_id=instance_id, openstack_request_id=self._request_id())

    async def instance_action(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> MutationResult:
        del payload
        instance = await self.get_instance(auth_context, project_id, region, instance_id)
        status = {
            "start": "ACTIVE",
            "stop": "SHUTOFF",
            "pause": "PAUSED",
            "unpause": "ACTIVE",
            "suspend": "SUSPENDED",
            "resume": "ACTIVE",
            "shelve": "SHELVED_OFFLOADED",
            "unshelve": "ACTIVE",
            "rescue": "RESCUE",
            "unrescue": "ACTIVE",
            "resize": "VERIFY_RESIZE",
            "resize_confirm": "ACTIVE",
            "resize_revert": "ACTIVE",
            "rebuild": "REBUILD",
        }.get(action)
        if status is not None:
            self._instance_updates.setdefault(instance.id, {})["status"] = status
        return MutationResult(resource_id=instance_id, openstack_request_id=self._request_id())

    async def create_console(
        self, auth_context: dict[str, Any], project_id: str, region: str, instance_id: str
    ) -> RemoteConsoleResult:
        await self.get_instance(auth_context, project_id, region, instance_id)
        return RemoteConsoleResult(
            url=f"https://console.invalid/novnc/{secrets.token_urlsafe(24)}",
            openstack_request_id=self._request_id(),
        )

    async def image_mutation(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        action: str,
        image_id: str | None,
        payload: dict[str, Any],
    ) -> MutationResult:
        self._require_project_scope(auth_context, project_id, region)
        resource_id = image_id or str(uuid4())
        return MutationResult(
            resource_id=resource_id,
            resource_name=str(payload.get("name")) if payload.get("name") else None,
            openstack_request_id=self._request_id(),
        )

    async def flavor_mutation(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        action: str,
        flavor_id: str | None,
        payload: dict[str, Any],
    ) -> MutationResult:
        self._require_project_scope(auth_context, project_id, region)
        del action
        resource_id = flavor_id or str(payload.get("id") or uuid4())
        return MutationResult(
            resource_id=resource_id,
            resource_name=str(payload.get("name")) if payload.get("name") else None,
            openstack_request_id=self._request_id(),
        )

    async def list_images(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        visibility: ImageVisibility | None,
    ) -> ProvisioningListResult:
        self._require_project_scope(auth_context, project_id, region)
        items = list(self._images(project_id))
        if name is not None:
            items = [
                item for item in items if item.name and name.casefold() in item.name.casefold()
            ]
        if visibility is not None:
            items = [item for item in items if item.visibility is visibility]
        return self._page_resources(items, limit, marker)

    async def list_flavors(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult:
        self._require_project_scope(auth_context, project_id, region)
        items = list(self._flavors(project_id))
        return self._page_resources(items, limit, marker)

    async def list_keypairs(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult:
        self._require_project_scope(auth_context, project_id, region)
        items = list(self._keypairs(project_id))
        return self._page_resources(items, limit, marker)

    async def list_networks(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
    ) -> ProvisioningListResult:
        self._require_project_scope(auth_context, project_id, region)
        items = list(self._networks(project_id))
        if name is not None:
            items = [
                item for item in items if item.name and name.casefold() in item.name.casefold()
            ]
        if status is not None:
            items = [item for item in items if item.status == status]
        return self._page_resources(items, limit, marker)

    async def list_security_groups(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
    ) -> ProvisioningListResult:
        self._require_project_scope(auth_context, project_id, region)
        items = list(self._security_groups(project_id))
        if name is not None:
            items = [
                item for item in items if item.name and name.casefold() in item.name.casefold()
            ]
        return self._page_resources(items, limit, marker)

    def _page_resources(
        self,
        items: Sequence[Image | Flavor | KeyPair | Network | SecurityGroup],
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult:
        start = 0
        if marker is not None:
            marker_index = next(
                (
                    index
                    for index, item in enumerate(items)
                    if str(getattr(item, "id", getattr(item, "name", ""))) == marker
                ),
                None,
            )
            if marker_index is None:
                raise AdapterError(status_code=400, request_id=self._request_id())
            start = marker_index + 1
        end = start + limit
        return ProvisioningListResult(
            items=tuple(items[start:end]),
            has_next=end < len(items),
            openstack_request_id=self._request_id(),
        )

    def _images(self, project_id: str) -> tuple[Image, ...]:
        label = project_id.removeprefix("project-")
        return tuple(
            Image(
                id=uuid5(_FAKE_NAMESPACE, f"{project_id}:image:{index}"),
                name=None if index == 30 else f"{label}-image-{index + 1:02d}",
                status=None if index == 30 else "active",
                visibility=(ImageVisibility.PRIVATE if index % 2 else ImageVisibility.PUBLIC),
                disk_format=None if index == 30 else "qcow2",
                container_format=None if index == 30 else "bare",
                size_bytes=None if index == 30 else (index + 1) * 1024 * 1024,
                min_disk_gib=None if index == 30 else index % 4,
                min_ram_mib=None if index == 30 else 512,
                created_at=None
                if index == 30
                else datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            )
            for index in range(31)
        )

    def _flavors(self, project_id: str) -> tuple[Flavor, ...]:
        return tuple(
            Flavor(
                id=str(uuid5(_FAKE_NAMESPACE, f"{project_id}:flavor:{index}")),
                name=None if index == 30 else f"m1.fake-{index + 1:02d}",
                vcpus=None if index == 30 else 1 + index % 8,
                ram_mib=None if index == 30 else 1024 * (1 + index % 8),
                disk_gib=None if index == 30 else 10 + index,
                ephemeral_gib=None if index == 30 else 0,
                is_public=None if index == 30 else index % 2 == 0,
            )
            for index in range(31)
        )

    def _keypairs(self, project_id: str) -> tuple[KeyPair, ...]:
        return tuple(
            KeyPair(
                name=f"{project_id.removeprefix('project-')}-key-{index + 1:02d}",
                type=None if index == 30 else KeyPairType.SSH,
                fingerprint=None if index == 30 else f"SHA256:fake{index:02d}",
                public_key_preview=None if index == 30 else "ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB...",
                created_at=None
                if index == 30
                else datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
                last_used_at=None,
            )
            for index in range(31)
        )

    def _networks(self, project_id: str) -> tuple[Network, ...]:
        label = project_id.removeprefix("project-")
        return tuple(
            Network(
                id=uuid5(_FAKE_NAMESPACE, f"{project_id}:network:{index}"),
                name=None if index == 30 else f"{label}-network-{index + 1:02d}",
                status=None if index == 30 else ("ACTIVE" if index % 2 == 0 else "DOWN"),
                shared=None if index == 30 else False,
                external=None if index == 30 else index == 0,
                mtu=None if index == 30 else 1500,
                subnet_count=None if index == 30 else 1,
            )
            for index in range(31)
        )

    def _security_groups(self, project_id: str) -> tuple[SecurityGroup, ...]:
        label = project_id.removeprefix("project-")
        return tuple(
            SecurityGroup(
                id=uuid5(_FAKE_NAMESPACE, f"{project_id}:security-group:{index}"),
                name=None if index == 30 else f"{label}-sg-{index + 1:02d}",
                description=None if index == 30 else f"Fake security group {index + 1}",
                rule_count=None if index == 30 else index % 5,
                revision_number=None if index == 30 else index,
            )
            for index in range(31)
        )

    def _require_project_scope(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
    ) -> None:
        if auth_context.get("project_id") != project_id or auth_context.get("region") != region:
            raise AdapterError(status_code=401, request_id=self._request_id())

    def _instances(self, project_id: str) -> tuple[Instance, ...]:
        self._ensure_state()
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
        items.extend(self._created.get(project_id, ()))
        return tuple(
            item.model_copy(update=self._instance_updates.get(item.id, {}))
            for item in items
            if item.id not in self._deleted
        )

    def _ensure_state(self) -> None:
        if not hasattr(self, "_created"):
            self._created = {}
            self._deleted = set()
            self._instance_updates = {}

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
            return (
                sorted(
                    present,
                    key=lambda item: cast(datetime, item.created_at),
                    reverse=reverse,
                )
                + missing
            )
        if sort is InstanceSort.NAME:
            named = [instance for instance in instances if instance.name is not None]
            unnamed = [instance for instance in instances if instance.name is None]
            return sorted(named, key=lambda item: item.name or "", reverse=reverse) + unnamed
        return sorted(instances, key=lambda item: item.status, reverse=reverse)

    def _request_id(self) -> str:
        return f"req-{uuid4()}"
