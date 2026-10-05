import json
from pathlib import Path

from hamcrest import assert_that, equal_to

from api.api_app import create_app


def test_v1_operation_inventory_is_reviewed():
    app = create_app()
    subapi = next(route.app for route in app.routes if getattr(route, "path", None) == "/api/v1")
    schema = subapi.openapi()
    actual = sorted(
        (method.upper(), path, operation["operationId"])
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if method in {"get", "post", "put", "patch", "delete"}
    )
    baseline = json.loads((Path(__file__).resolve().parents[2] / "developer_docs/operations-v1.json").read_text())
    assert_that([list(item) for item in actual], equal_to(baseline))
    assert_that(len({item[2] for item in actual}), equal_to(len(actual)))
