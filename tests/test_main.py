"""app/main.py through FastAPI's TestClient with injected, offline dependencies."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app import pipeline
from app.catalog import CITIES, PROCEDURES
from app.config import load_settings
from app.llm import LLM
from app.serp import SerpClient

from .helpers import make_deps, parse_sse, probe_responder, run_replay


@pytest.fixture
def recorded(dirs):
    """Fixtures for knee / Whitefield / Bengaluru recorded with a throwaway client (fresh event loop)."""

    async def record():
        deps = make_deps(dirs)
        await run_replay(deps, dirs[1], probe_responder(aster_low="rev_aster2"))
        await deps.serp.aclose()

    asyncio.run(record())
    return dirs


@pytest.fixture
def client(recorded):
    deps = make_deps(recorded)
    app = main_mod.create_app(settings=load_settings(), deps=deps)
    with TestClient(app) as c:
        yield c


def stream(client, **params):
    r = client.get("/api/compare/stream", params=params)
    return r, parse_sse(r.text)


# --- status / examples -----------------------------------------------------------------------------

def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "replay" and body["llm"] is None and body["account"] is None
    assert body["credits_per_check"] == 7
    assert body["cities"] == list(CITIES)
    assert [p["id"] for p in body["procedures"]] == list(PROCEDURES)
    assert all(p["label"] == PROCEDURES[p["id"]].label for p in body["procedures"])


def test_status_live_account_cached(dirs):
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx.Response(200, json={"plan_name": "Free", "total_searches_left": 93, "api_key": "secret"})

    serp = SerpClient("secret", dirs[0], dirs[1], mode="auto", transport=httpx.MockTransport(handler))
    deps = pipeline.Deps(serp=serp, llm=LLM(None, "m", *dirs, replay=True))
    with TestClient(main_mod.create_app(settings=load_settings(), deps=deps)) as c:
        first = c.get("/api/status").json()
        second = c.get("/api/status").json()
    assert first["mode"] == "auto" and first["account"]["searches_left"] == 93
    assert second == first and len(hits) == 1
    assert "secret" not in str(first)


def test_examples(client):
    r = client.get("/api/examples")
    assert r.status_code == 200
    examples = r.json()
    assert examples and examples == main_mod.EXAMPLES


@pytest.mark.parametrize("ex", main_mod.EXAMPLES, ids=lambda e: e["label"])
def test_examples_are_valid_requests(ex):
    assert ex["procedure"] in PROCEDURES and ex["city"] in CITIES
    assert len(ex["area"]) <= 50 and not any(c in ex["area"] for c in "<>{}[]\\")
    assert ex["label"] and ex["hint"]


# --- SSE ---------------------------------------------------------------------------------------------

def test_compare_stream_events(client):
    r, events = stream(client, procedure="knee", area="Whitefield", city="Bengaluru")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    names = [e for e, _ in events]
    assert names[0] == "start" and names[-1] == "done" and "result" in names and "hospitals" in names
    assert "serp_call" in names and "step" in names
    result = dict(events)["result"]
    assert result["procedure_id"] == "knee" and result["keyword"] == "knee"
    assert [h["title"] for h in result["hospitals"]][:2] == ["Manipal Hospital Whitefield",
                                                            "Aster Hospital Whitefield Bangalore"]
    assert result["credits_spent"] == 0
    assert all(not d["credit"] for e, d in events if e == "serp_call")


def test_compare_stream_unrecorded_place_gives_notices(client):
    _, events = stream(client, procedure="hip", area="Koramangala", city="Bengaluru")
    names = [e for e, _ in events]
    assert names[-1] == "done" and "notice" in names
    assert dict(events)["result"]["hospitals"] == []


def test_compare_stream_unicode_area(client):
    r, events = stream(client, procedure="knee", area="Whitefield — East", city="Bengaluru")
    assert r.status_code == 200 and dict(events)["start"]["place"] == "Whitefield — East, Bengaluru"


def test_pipeline_crash_becomes_failure_event(client, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(pipeline, "run", boom)
    r, events = stream(client, procedure="knee", area="Whitefield", city="Bengaluru")
    assert r.status_code == 200
    assert [e for e, _ in events] == ["failure"]
    assert "secret internals" not in r.text


# --- validation --------------------------------------------------------------------------------------

@pytest.mark.parametrize("params,err", [
    ({"procedure": "liposuction"}, "unknown procedure"),
    ({"procedure": "KNEE"}, "unknown procedure"),
    ({"procedure": ""}, "unknown procedure"),
    ({"procedure": "knee", "city": "Atlantis"}, "unknown city"),
    ({"procedure": "knee", "city": "bengaluru"}, "unknown city"),
    ({"procedure": "knee", "area": "<script>"}, "area must be a locality name"),
    ({"procedure": "knee", "area": "a{b}"}, "area must be a locality name"),
    ({"procedure": "knee", "area": "x[1]"}, "area must be a locality name"),
    ({"procedure": "knee", "area": "back\\slash"}, "area must be a locality name"),
    ({"procedure": "knee", "area": "Sector 1234567"}, "area must be a locality name"),
])
def test_bad_requests_400(client, params, err):
    r = client.get("/api/compare/stream", params=params)
    assert r.status_code == 400 and r.json() == {"error": err}
    assert r.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("params", [{}, {"procedure": "k" * 21}, {"procedure": "knee", "area": "a" * 51},
                                    {"procedure": "knee", "city": "c" * 21}])
def test_oversized_or_missing_params_422(client, params):
    assert client.get("/api/compare/stream", params=params).status_code == 422


@pytest.mark.parametrize("area", ["560066", "HSR Layout Sector 2", "", "St. John's Road", "Whitefield, East"])
def test_valid_areas_accepted(client, area):
    r, events = stream(client, procedure="knee", area=area, city="Bengaluru")
    assert r.status_code == 200 and events[-1][0] == "done"


# --- security headers / cross-site -------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/status", "/api/examples", "/api/compare/stream?procedure=knee"])
def test_cross_site_api_forbidden(client, path):
    r = client.get(path, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and "cross-site" in r.json()["error"]


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_same_site_allowed(client, site):
    assert client.get("/api/status", headers={"Sec-Fetch-Site": site}).status_code == 200


def test_cross_site_page_load_allowed(client):
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


@pytest.mark.parametrize("path", ["/", "/api/status", "/api/examples", "/static/app.js"])
def test_security_headers(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_static_missing_404(client):
    assert client.get("/static/does-not-exist.js").status_code == 404


def test_module_app_builds_without_keys():
    assert main_mod.app.title == "Bedside Manner"
