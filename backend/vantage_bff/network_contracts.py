from __future__ import annotations

from dataclasses import dataclass

from vantage_bff.network_models import NetworkField, NetworkResourceContract, ResourceKind


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    service: str
    create_fields: frozenset[str]
    update_fields: frozenset[str]
    required_fields: frozenset[str] = frozenset()
    admin_fields: frozenset[str] = frozenset()
    parent_required: bool = False
    actions: tuple[str, ...] = ()


def _spec(
    service: str,
    create: str,
    update: str,
    *,
    required: str = "",
    admin: str = "",
    parent: bool = False,
    actions: tuple[str, ...] = (),
) -> ResourceSpec:
    def words(value: str) -> frozenset[str]:
        return frozenset(value.split())

    return ResourceSpec(
        service=service,
        create_fields=words(create),
        update_fields=words(update),
        required_fields=words(required),
        admin_fields=words(admin),
        parent_required=parent,
        actions=actions,
    )


RESOURCE_SPECS: dict[ResourceKind, ResourceSpec] = {
    ResourceKind.NETWORK: _spec(
        "network",
        "name description admin_state_up is_shared is_router_external is_default mtu "
        "port_security_enabled "
        "dns_domain qos_policy_id provider_network_type provider_physical_network "
        "provider_segmentation_id tags",
        "name description admin_state_up is_shared is_router_external is_default mtu "
        "port_security_enabled "
        "dns_domain qos_policy_id tags",
        admin="is_shared is_router_external is_default provider_network_type "
        "provider_physical_network "
        "provider_segmentation_id",
    ),
    ResourceKind.SUBNET: _spec(
        "network",
        "name description network_id cidr ip_version gateway_ip enable_dhcp allocation_pools "
        "dns_nameservers host_routes ipv6_address_mode ipv6_ra_mode subnet_pool_id prefixlen "
        "segment_id service_types tags",
        "name description gateway_ip enable_dhcp allocation_pools dns_nameservers host_routes "
        "service_types tags",
        required="network_id ip_version",
    ),
    ResourceKind.PORT: _spec(
        "network",
        "name description network_id admin_state_up mac_address fixed_ips device_id device_owner "
        "vnic_type host_id profile numa_affinity_policy hints trusted dns_name qos_policy_id "
        "security_group_ids port_security_enabled allowed_address_pairs extra_dhcp_opts "
        "data_plane_status propagate_uplink_status tags",
        "name description admin_state_up mac_address fixed_ips device_id device_owner vnic_type "
        "host_id profile numa_affinity_policy hints trusted dns_name qos_policy_id "
        "security_group_ids port_security_enabled allowed_address_pairs extra_dhcp_opts "
        "data_plane_status propagate_uplink_status tags",
        required="network_id",
        admin="device_id device_owner vnic_type host_id profile numa_affinity_policy trusted "
        "data_plane_status",
        actions=("attach_instance", "detach_instance", "add_fixed_ip", "remove_fixed_ip"),
    ),
    ResourceKind.ROUTER: _spec(
        "network",
        "name description admin_state_up distributed ha routes external_gateway_info "
        "enable_ndp_proxy enable_default_route_ecmp enable_default_route_bfd tags",
        "name description admin_state_up distributed ha routes external_gateway_info "
        "enable_ndp_proxy enable_default_route_ecmp enable_default_route_bfd tags",
        admin="distributed ha",
        actions=("add_interface", "remove_interface", "set_gateway", "clear_gateway"),
    ),
    ResourceKind.FLOATING_IP: _spec(
        "network",
        "floating_network_id subnet_id floating_ip_address port_id fixed_ip_address description "
        "qos_policy_id tags",
        "port_id fixed_ip_address description qos_policy_id tags",
        required="floating_network_id",
        actions=("associate", "disassociate"),
    ),
    ResourceKind.SECURITY_GROUP: _spec(
        "network", "name description stateful tags", "name description stateful tags"
    ),
    ResourceKind.SECURITY_GROUP_RULE: _spec(
        "network",
        "security_group_id direction ethertype protocol port_range_min port_range_max "
        "remote_ip_prefix remote_group_id remote_address_group_id description",
        "",
        required="security_group_id direction",
    ),
    ResourceKind.QOS_POLICY: _spec(
        "network",
        "name description is_shared is_default tags",
        "name description is_shared is_default tags",
        required="name",
        admin="is_shared is_default",
    ),
    ResourceKind.QOS_RULE: _spec(
        "network",
        "rule_type max_kbps max_burst_kbps direction dscp_mark min_kbps min_kpps max_kpps "
        "max_burst_kpps",
        "max_kbps max_burst_kbps direction dscp_mark min_kbps min_kpps max_kpps max_burst_kpps",
        required="rule_type",
        parent=True,
    ),
    ResourceKind.RBAC_POLICY: _spec(
        "network",
        "object_id object_type action target_project_id target_all_projects target_project_domain",
        "target_project_id target_all_projects target_project_domain",
        required="object_id object_type action",
    ),
    ResourceKind.LOAD_BALANCER: _spec(
        "load-balancer",
        "name description vip_subnet_id vip_network_id vip_port_id vip_address provider flavor_id "
        "availability_zone admin_state_up tags",
        "name description admin_state_up tags",
        actions=("failover",),
    ),
    ResourceKind.LISTENER: _spec(
        "load-balancer",
        "name description load_balancer_id protocol protocol_port connection_limit "
        "default_pool_id default_tls_container_ref sni_container_refs insert_headers "
        "allowed_cidrs timeout_client_data timeout_member_connect timeout_member_data "
        "timeout_tcp_inspect client_ca_tls_container_ref client_authentication "
        "client_crl_container_ref tls_ciphers tls_versions alpn_protocols admin_state_up tags",
        "name description connection_limit default_pool_id default_tls_container_ref "
        "sni_container_refs insert_headers allowed_cidrs timeout_client_data "
        "timeout_member_connect timeout_member_data timeout_tcp_inspect "
        "client_ca_tls_container_ref "
        "client_authentication client_crl_container_ref tls_ciphers tls_versions alpn_protocols "
        "admin_state_up tags",
        required="load_balancer_id protocol protocol_port",
    ),
    ResourceKind.POOL: _spec(
        "load-balancer",
        "name description listener_id load_balancer_id protocol lb_algorithm session_persistence "
        "tls_enabled tls_container_ref ca_tls_container_ref crl_container_ref tls_ciphers "
        "tls_versions alpn_protocols admin_state_up tags",
        "name description lb_algorithm session_persistence tls_enabled tls_container_ref "
        "ca_tls_container_ref crl_container_ref tls_ciphers tls_versions alpn_protocols "
        "admin_state_up tags",
        required="protocol lb_algorithm",
    ),
    ResourceKind.MEMBER: _spec(
        "load-balancer",
        "name address protocol_port subnet_id weight backup monitor_address monitor_port "
        "admin_state_up tags",
        "name weight backup monitor_address monitor_port admin_state_up tags",
        required="address protocol_port",
        parent=True,
    ),
    ResourceKind.HEALTH_MONITOR: _spec(
        "load-balancer",
        "name pool_id type delay timeout max_retries max_retries_down http_method url_path "
        "expected_codes http_version domain_name admin_state_up tags",
        "name delay timeout max_retries max_retries_down http_method url_path expected_codes "
        "http_version domain_name admin_state_up tags",
        required="pool_id type delay timeout max_retries",
    ),
    ResourceKind.L7_POLICY: _spec(
        "load-balancer",
        "name description listener_id action redirect_pool_id redirect_url redirect_prefix "
        "redirect_http_code position admin_state_up tags",
        "name description action redirect_pool_id redirect_url redirect_prefix redirect_http_code "
        "position admin_state_up tags",
        required="listener_id action",
    ),
    ResourceKind.L7_RULE: _spec(
        "load-balancer",
        "type compare_type key value invert admin_state_up tags",
        "type compare_type key value invert admin_state_up tags",
        required="type compare_type value",
        parent=True,
    ),
}


def resource_contract(
    kind: ResourceKind, *, neutron: bool, octavia: bool
) -> NetworkResourceContract:
    spec = RESOURCE_SPECS[kind]
    available = neutron if spec.service == "network" else octavia
    fields = []
    for name in sorted(spec.create_fields | spec.update_fields):
        update = name in spec.update_fields
        fields.append(
            NetworkField(
                name=name,
                create=name in spec.create_fields,
                update=update,
                required=name in spec.required_fields,
                admin_only=name in spec.admin_fields,
                immutable_reason_en=None
                if update
                else "OpenStack does not allow this field to be edited.",
                immutable_reason_ko=None
                if update
                else "OpenStack에서 이 필드의 편집을 허용하지 않습니다.",
            )
        )
    return NetworkResourceContract(
        resource_type=kind,
        service=spec.service,
        available=available,
        parent_required=spec.parent_required,
        fields=fields,
        actions=list(spec.actions),
    )


def validate_attributes(
    kind: ResourceKind,
    attributes: dict[str, object],
    *,
    create: bool,
) -> tuple[set[str], set[str], set[str]]:
    spec = RESOURCE_SPECS[kind]
    allowed = spec.create_fields if create else spec.update_fields
    supplied = set(attributes)
    unknown = supplied - allowed
    missing = set(spec.required_fields - supplied) if create else set()
    admin_only = supplied & spec.admin_fields
    return unknown, missing, admin_only
