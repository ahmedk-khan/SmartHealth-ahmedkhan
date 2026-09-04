"""Route-level production checklist.

This test intentionally checks the contract of every registered application
route. Feature tests remain responsible for business workflow behavior.
"""

from fastapi.routing import APIRoute
import pytest

from app.core.authorization import Permission
from app.main import app


EXPECTED_ROUTES = {
    (method, route.path)
    for route in app.routes
    if isinstance(route, APIRoute)
    and route.include_in_schema
    and not route.path.startswith(("/docs", "/redoc", "/openapi"))
    for method in route.methods
    if method != "HEAD"
}


def _dependency_calls(dependant):
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _dependency_calls(dependency)


def _openapi_operations():
    schema = app.openapi()
    return {
        (method.upper(), path): operation
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }


@pytest.mark.parametrize("method,path", sorted(EXPECTED_ROUTES))
def test_endpoint_contract(method, path):
    operations = _openapi_operations()

    assert EXPECTED_ROUTES == set(operations), "registered route is missing from OpenAPI"
    operation = operations[(method, path)]
    assert operation.get("operationId"), f"{method} {path} has no operationId"
    assert operation.get("summary"), f"{method} {path} has no summary"
    assert operation.get("tags"), f"{method} {path} has no tag"
    assert "responses" in operation, f"{method} {path} has no response contract"
    if "{" in path:
        path_parameters = [
            parameter
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        ]
        assert path_parameters, f"{method} {path} has no path parameter schema"
        assert all(parameter.get("required") for parameter in path_parameters)
    if "requestBody" in operation:
        assert operation["requestBody"].get("content"), f"{method} {path} has empty request schema"


@pytest.mark.parametrize("method,path", sorted(EXPECTED_ROUTES))
def test_endpoint_authentication_and_authorization(method, path):
    public_routes = {
        ("GET", "/"),
        ("GET", "/metrics"),
        ("GET", "/health"),
        ("GET", "/health/version"),
        ("GET", "/health/ready"),
        ("POST", "/auth/register"),
        ("POST", "/auth/login"),
        ("POST", "/auth/token"),
        ("GET", "/api/v1/public/services"),
    }
    operations = _openapi_operations()

    if (method, path) in public_routes:
        return
    operation = operations[(method, path)]
    assert operation.get("security"), f"{method} {path} is not authenticated"
    route = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == path and method in route.methods)
    guards = [
        permission
        for call in _dependency_calls(route.dependant)
        if (permission := (
            getattr(call, "__required_permission__", None)
            or getattr(call, "__name__", None)
        ))
    ]
    assert any(
        guard == "get_current_user"
        or guard == "require_admin"
        or guard in {permission.value for permission in Permission}
        for guard in guards
    ), f"{method} {path} has no authentication or authorization guard"