from __future__ import annotations

import hashlib
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
    KeyPairCreateResult,
    MutationResult,
    ProvisioningListResult,
    ScopeError,
    ScopeResult,
    normalized_quota,
)
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
        self._keypair_state: dict[tuple[str, str], dict[str, KeyPair]] = {}

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
        return InstanceDetail(
            **instance.model_dump(),
            volumes=volumes,
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
        items = list(self._keypairs(project_id, region))
        return self._page_resources(items, limit, marker)

    async def create_keypair(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        name: str,
        key_type: KeyPairType,
        public_key: str | None,
    ) -> KeyPairCreateResult:
        self._require_project_scope(auth_context, project_id, region)
        records = self._keypair_records(project_id, region)
        if name in records:
            raise AdapterError(status_code=409, request_id=self._request_id())

        generated_public_key = (
            f"ssh-rsa {secrets.token_urlsafe(48)}"
            if key_type is KeyPairType.SSH
            else (
                "-----BEGIN CERTIFICATE-----\n"
                f"{secrets.token_urlsafe(48)}\n"
                "-----END CERTIFICATE-----"
            )
        )
        public_material = public_key if public_key is not None else generated_public_key
        keypair = KeyPair(
            name=name,
            type=key_type,
            fingerprint=f"SHA256:{hashlib.sha256(public_material.encode()).hexdigest()[:32]}",
            public_key_preview=(
                f"{public_material[:61]}..."
                if len(public_material) > 64
                else public_material
            ),
            created_at=datetime.now(UTC),
            last_used_at=None,
        )
        records[name] = keypair
        private_key = None
        if public_key is None:
            private_key = (
                (
                    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                    f"{secrets.token_urlsafe(96)}\n"
                    "-----END OPENSSH PRIVATE KEY-----"
                )
                if key_type is KeyPairType.SSH
                else (
                    "-----BEGIN PRIVATE KEY-----\n"
                    f"{secrets.token_urlsafe(96)}\n"
                    "-----END PRIVATE KEY-----"
                )
            )
        return KeyPairCreateResult(
            keypair=keypair,
            private_key=private_key,
            openstack_request_id=self._request_id(),
        )

    async def delete_keypair(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        name: str,
    ) -> MutationResult:
        self._require_project_scope(auth_context, project_id, region)
        records = self._keypair_records(project_id, region)
        if records.pop(name, None) is None:
            raise AdapterError(status_code=404, request_id=self._request_id())
        return MutationResult(openstack_request_id=self._request_id())

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

    def _initial_keypairs(self, project_id: str) -> tuple[KeyPair, ...]:
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

    def _keypairs(self, project_id: str, region: str) -> tuple[KeyPair, ...]:
        return tuple(self._keypair_records(project_id, region).values())

    def _keypair_records(self, project_id: str, region: str) -> dict[str, KeyPair]:
        if not hasattr(self, "_keypair_state"):
            self._keypair_state = {}
        scope = (project_id, region)
        records = self._keypair_state.get(scope)
        if records is None:
            records = {item.name: item for item in self._initial_keypairs(project_id)}
            self._keypair_state[scope] = records
        return records

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
