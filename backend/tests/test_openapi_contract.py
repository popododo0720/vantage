from pathlib import Path

import yaml
from fastapi.routing import APIRoute
from openapi_spec_validator import validate
from vantage_bff.app import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


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
        (route.path, method)
        for route in create_app().routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
        for method in route.methods
    }

    assert runtime_routes == contract_routes
