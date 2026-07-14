"""CI guard: every API route must have an explicit audit decision.

Each route handler must appear in either ``AUDITED_ROUTES`` (it records an action) or
``AUDIT_EXEMPT_ROUTES`` (with a documented reason). A new endpoint added without either
fails this test — which is how the ticket's "err toward capturing more / the action set
can grow" survives future development instead of silently regressing.
"""

from fastapi.routing import APIRoute

from api.api_app import create_app
from api.domains.audit_logs.registry import AUDITED_ROUTES, AUDIT_EXEMPT_ROUTES


def _subapi_routes():
    app = create_app()
    subapi = next(r.app for r in app.routes if getattr(r, "path", "") == "/api/v1")
    return [r for r in subapi.routes if isinstance(r, APIRoute)]


def _find_unclassified(route_names: set[str], classified: set[str]) -> list[str]:
    return sorted(route_names - classified)


def test_every_route_has_an_audit_decision():
    classified = set(AUDITED_ROUTES) | set(AUDIT_EXEMPT_ROUTES)
    route_names = {r.endpoint.__name__ for r in _subapi_routes()}

    unclassified = _find_unclassified(route_names, classified)

    assert unclassified == [], (
        "These routes have no audit decision. Add each to AUDITED_ROUTES or "
        "AUDIT_EXEMPT_ROUTES in api/domains/audit_logs/registry.py: "
        f"{unclassified}"
    )


def test_registry_has_no_stale_entries():
    classified = set(AUDITED_ROUTES) | set(AUDIT_EXEMPT_ROUTES)
    route_names = {r.endpoint.__name__ for r in _subapi_routes()}

    stale = sorted(classified - route_names)

    assert stale == [], (
        "These registry entries do not match any route (rename or remove them): "
        f"{stale}"
    )


def test_a_route_maps_to_exactly_one_bucket():
    overlap = sorted(set(AUDITED_ROUTES) & set(AUDIT_EXEMPT_ROUTES))
    assert overlap == [], f"Routes both audited and exempt: {overlap}"


def test_guard_detects_an_unmapped_route():
    # The guard's logic, exercised directly: an unmapped route name is reported.
    detected = _find_unclassified({"create_agent", "brand_new_route"}, {"create_agent"})
    assert detected == ["brand_new_route"]
