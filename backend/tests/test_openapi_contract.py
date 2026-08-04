from pathlib import Path

import yaml
from fastapi.routing import APIRoute
from openapi_spec_validator import validate
from vantage_bff.app import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def published_route(path: str) -> str:
    """Remove Starlette-only converters that are not part of OpenAPI paths."""

    return path.replace("{keypair_name:path}", "{keypair_name}")


def test_openapi_contract_is_valid() -> None:
    document = yaml.safe_load(Path("api/openapi.yaml").read_text())
    validate(document)


def test_planned_goal1_contract_is_valid() -> None:
    document = yaml.safe_load(Path("api/openapi.goal1-mvp.yaml").read_text())
    validate(document)


def test_runtime_routes_match_the_published_contract() -> None:
    document = yaml.safe_load(Path("api/openapi.yaml").read_text())
    contract_routes = {
        (f"/api/v1{path}", method.upper())
        for path, path_item in document["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }
    runtime_routes = {
        (published_route(route.path), method)
        for route in create_app().routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
        for method in route.methods
    }

    assert runtime_routes == contract_routes


def test_keypair_request_contract_matches_runtime_defaults() -> None:
    documents = [
        yaml.safe_load(Path(path).read_text())
        for path in ("api/openapi.yaml", "api/openapi.goal1-mvp.yaml")
    ]
    for document in documents:
        schema = document["components"]["schemas"]["CreateKeyPairRequest"]

        assert schema["required"] == ["name"]
        assert schema["properties"]["type"]["default"] == "ssh"
        assert schema["properties"]["mode"]["default"] == "import"

    implemented, planned = documents
    for path in ("/keypairs", "/keypairs/{keypair_name}", "/operations/{operation_id}"):
        assert implemented["paths"][path] == planned["paths"][path]
    for name in (
        "KeyPair",
        "CreateKeyPairRequest",
        "CreatedKeyPair",
        "OperationTarget",
        "Operation",
    ):
        assert implemented["components"]["schemas"][name] == planned["components"]["schemas"][name]
