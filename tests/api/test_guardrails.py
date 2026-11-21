"""The API guardrails (design section 7A), one test each. Model calls are faked."""

import logging

from fastapi.routing import APIRoute

from app import auth
from app.api.main import ROUTERS
from tests.helpers import POSTING, as_, drain, submit

PUBLIC = {"/health", "/{path:path}"}  # the UI fallback serves only the built page


def _routes(app) -> list[APIRoute]:
    """Every API route: the app's own and those of each router it includes."""
    own = [r for r in app.routes if isinstance(r, APIRoute)]
    return [r for r in own + [r for router in ROUTERS for r in router.routes] if r.path not in PUBLIC]


def _roles(route: APIRoute) -> set:
    """The roles a route's require() dependency allows, found anywhere in its dependency tree."""
    found, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        found |= set(getattr(dep.call, "roles", ()))
        stack.extend(dep.dependencies)
    return found


async def test_every_route_declares_its_roles(api):
    """Deny by default: a new route without require(...) fails this test."""
    routes = _routes(api.app)
    assert len(routes) >= 8
    unguarded = [r.path for r in routes if not _roles(r)]
    assert unguarded == []


async def test_every_route_refuses_a_request_without_a_token(api):
    for route in _routes(api.app):
        path = route.path.replace("{job_id}", "x").replace("{batch_id}", "1")
        path = path.replace("{label_id}", "1").replace("{posting_id}", "1")
        for method in route.methods:
            response = await api.request(method, path)
            assert response.status_code == 401, (method, path)
            bad = await api.request(method, path, headers={"Authorization": "Bearer not-a-token"})
            assert bad.status_code == 401, (method, path)


async def test_the_wrong_role_is_forbidden(api):
    assert (await api.post("/v1/postings", json=POSTING, headers=as_("viewer"))).status_code == 403
    assert (await api.get("/ui/labels", headers=as_("marketplace"))).status_code == 403
    decision = {"label": "ALLOWED"}
    assert (await api.post("/ui/labels/1/decision", json=decision, headers=as_("viewer"))).status_code == 403


async def test_a_declared_oversized_body_is_refused_before_parsing(api):
    body = b'{"postings": [' + b" " * (10 * 1024 * 1024) + b"]}"
    response = await api.post(
        "/v1/postings/batch", content=body, headers={**as_("marketplace"), "content-type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


async def test_an_undeclared_oversized_body_is_refused_while_it_arrives(api):
    async def chunks():  # no Content-Length: sent in chunks
        yield b'{"postings": ['
        for _ in range(11):
            yield b" " * (1024 * 1024)
        yield b"]}"

    response = await api.post(
        "/v1/postings/batch",
        content=chunks(),
        headers={**as_("marketplace"), "content-type": "application/json"},
    )
    assert response.status_code == 413


async def test_each_client_is_rate_limited(api, monkeypatch):
    monkeypatch.setattr(auth, "RATE_LIMIT_PER_MINUTE", 3)
    codes = [
        (await api.get("/v1/postings/x/label", headers=as_("marketplace"))).status_code for _ in range(4)
    ]
    assert codes == [404, 404, 404, 429]
    # Another client has its own allowance.
    assert (await api.get("/v1/postings/x/label", headers=as_("marketplace_b"))).status_code == 404


async def test_a_crash_returns_a_code_and_request_id_only(api, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("SECRET-DETAIL from deep inside")

    monkeypatch.setattr("app.store.read_label", broken)
    response = await api.get("/v1/postings/x/label", headers=as_("marketplace"))
    assert response.status_code == 500
    body = response.json()
    assert body == {"error": "internal_error", "request_id": response.headers["X-Request-ID"]}
    assert "SECRET" not in response.text


async def test_a_validation_error_does_not_echo_the_posting(api):
    response = await api.post(
        "/v1/postings", json={**POSTING, "employment_type": "SECRET-TEXT"}, headers=as_("marketplace")
    )
    assert response.status_code == 422
    assert "SECRET-TEXT" not in response.text
    assert response.json()["details"][0]["loc"] == ["body", "employment_type"]


async def test_logs_never_carry_posting_text(api, worker, caplog):
    caplog.set_level(logging.DEBUG)
    marker = "Zanzibarquux"
    posting = {**POSTING, "description": f"{marker} {POSTING['description']}", "title": f"{marker} role"}
    await submit(api, posting)
    await drain(worker)
    await api.get("/v1/postings/p1/label", headers=as_("marketplace"))
    assert any("labeled VIOLATING" in r.getMessage() for r in caplog.records)  # the worker did log
    assert not [r.name for r in caplog.records if marker in r.getMessage()]


async def test_browser_routes_load_the_ui_and_unknown_api_paths_stay_404(api):
    page = await api.get("/labels/12")
    assert page.status_code in (200, 404)
    if page.status_code == 404:
        assert page.json() == {"error": "ui_not_built"}  # web/dist is built in phase 7 and in Docker
    assert (await api.get("/v1/nothing-here")).json()["error"] == "not_found"
    assert (await api.get("/ui/nothing-here")).json()["error"] == "not_found"


async def test_health_is_public_and_reports_live_labeling(api):
    response = await api.get("/health")
    assert response.status_code == 200
    assert response.json()["live_labeling"] is True  # the fake backend needs no keys
