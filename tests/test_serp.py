"""app/serp.py — cache, replay, credit budget, refunds, hourly cap and key scrubbing (never the network)."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from app.serp import (
    ACCOUNT_URL,
    SERPAPI_URL,
    BudgetExceeded,
    CreditBudget,
    ReplayMiss,
    SerpCall,
    SerpClient,
    SerpError,
    _count_results,
    cache_key,
    scrub,
)

from .helpers import load_payload, write_serp_fixture

KEY = "test-secret-key-123"
PARAMS = {"data_id": "0xabc:0xdef", "query": "knee", "sort_by": "ratingLow", "hl": "en", "num": 20}


class FakeSerpApi:
    """httpx.MockTransport handler standing in for serpapi.com."""

    def __init__(self, payload=None, status=200, *, error=None, fail_times=0, raw=None):
        self.payload = payload if payload is not None else load_payload("rev_manipal_low")
        self.status = status
        self.error = error
        self.fail_times = fail_times
        self.raw = raw
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_times:
            self.fail_times -= 1
            raise httpx.ConnectError("boom", request=request)
        if self.raw is not None:
            return httpx.Response(self.status, content=self.raw)
        body = dict(self.payload)
        body["search_parameters"] = {**dict(request.url.params)}  # SerpApi echoes params, incl. the key
        if self.error:
            body["error"] = self.error
        return httpx.Response(self.status, json=body)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def client(dirs, fake=None, *, mode="auto", key=KEY, ttl=168.0, live_per_hour=0, fixtures=True):
    cache, fx = dirs
    return SerpClient(key, cache, fx if fixtures else None, mode=mode, ttl_hours=ttl,
                      transport=(fake or FakeSerpApi()).transport, live_per_hour=live_per_hour)


def all_text(path):
    return "\n".join(p.read_text(encoding="utf-8") for p in path.rglob("*") if p.is_file())


# --- cache_key / scrub / counting ------------------------------------------------------------------

def test_cache_key_ignores_api_key_and_order():
    a = cache_key("google_maps", {"q": "x", "hl": "en", "api_key": "secret"})
    b = cache_key("google_maps", {"hl": "en", "q": "x"})
    assert a == b and len(a) == 24


@pytest.mark.parametrize("other", [
    ("google_maps_reviews", PARAMS),
    ("google_maps", {**PARAMS, "sort_by": "newestFirst"}),
    ("google_maps", {**PARAMS, "query": "hip"}),
    ("google_maps", {**PARAMS, "num": "20"}),
    ("google_maps", {k: v for k, v in PARAMS.items() if k != "hl"}),
])
def test_cache_key_differs(other):
    assert cache_key("google_maps", PARAMS) != cache_key(*other)


def test_cache_key_unicode_stable():
    assert cache_key("google_maps", {"q": "अस्पताल"}) == cache_key("google_maps", {"q": "अस्पताल"})


def test_scrub_removes_api_key_only():
    data = {"search_parameters": {"api_key": KEY, "q": "x"}, "reviews": [1]}
    out = scrub(data)
    assert out == {"search_parameters": {"q": "x"}, "reviews": [1]}
    assert data["search_parameters"]["api_key"] == KEY  # input not mutated


def test_scrub_without_search_parameters():
    assert scrub({"reviews": []}) == {"reviews": []}


@pytest.mark.parametrize("data,n", [
    ({"reviews": [1, 2, 3]}, 3),
    ({"local_results": [1]}, 1),
    ({"organic_results": []}, 0),
    ({"search_information": {"reviews_results_state": "No reviews"}}, 0),
    ({"reviews": "oops", "local_results": [1, 2]}, 2),
    ({"product_results": {"stores": [1, 2]}}, 2),
    ({"product_results": {"title": "x"}}, 1),
    ({}, 0),
])
def test_count_results(data, n):
    assert _count_results(data) == n


def test_count_results_probe():
    assert _count_results(load_payload("maps")) == 20
    assert _count_results(load_payload("rev_aster")) == 0
    assert _count_results(load_payload("rev_aster2")) == 20


# --- budget ----------------------------------------------------------------------------------------

def test_budget_reserve_and_refund():
    b = CreditBudget(2)
    b.reserve()
    b.reserve()
    with pytest.raises(BudgetExceeded):
        b.reserve()
    assert b.spent == 2
    b.refund()
    b.refund()
    b.refund()
    assert b.spent == 0


def test_budget_zero():
    with pytest.raises(BudgetExceeded):
        CreditBudget(0).reserve()


@pytest.mark.parametrize("source,ok,credit", [("live", True, True), ("live", False, False), ("cache", True, False),
                                              ("fixture", True, False)])
def test_call_event_credit_flag(source, ok, credit):
    ev = SerpCall("google_maps", "p", {"q": "x"}, source, 5, ok).to_event()
    assert ev["credit"] is credit
    assert set(ev) == {"engine", "purpose", "params", "source", "ms", "ok", "error", "result_count", "credit"}


# --- modes ---------------------------------------------------------------------------------------

def test_unknown_mode_rejected(dirs):
    with pytest.raises(ValueError):
        SerpClient(KEY, dirs[0], mode="turbo")


@pytest.mark.parametrize("mode", ["auto", "live", "replay"])
def test_no_key_forces_replay(dirs, mode):
    assert SerpClient(None, dirs[0], mode=mode).mode == "replay"
    assert SerpClient("", dirs[0], mode=mode).mode == "replay"


@pytest.mark.parametrize("mode", ["auto", "live", "replay"])
def test_key_keeps_mode(dirs, mode):
    assert SerpClient(KEY, dirs[0], mode=mode).mode == mode


def test_cache_dir_created(tmp_path):
    SerpClient(None, tmp_path / "a" / "b")
    assert (tmp_path / "a" / "b").is_dir()


# --- replay ----------------------------------------------------------------------------------------

async def test_replay_fixture_hit(dirs):
    write_serp_fixture(dirs[1], "google_maps_reviews", PARAMS, load_payload("rev_aster2"))
    fake = FakeSerpApi()
    c = client(dirs, fake, mode="replay")
    calls = []
    data = await c.search("google_maps_reviews", PARAMS, purpose="p", on_call=calls.append)
    assert len(data["reviews"]) == 20 and fake.requests == []
    assert calls[0].source == "fixture" and calls[0].ok and calls[0].result_count == 20
    await c.aclose()


async def test_replay_miss_raises_and_reports(dirs):
    c = client(dirs, mode="replay")
    calls = []
    with pytest.raises(ReplayMiss):
        await c.search("google_maps", {"q": "x"}, purpose="p", on_call=calls.append)
    assert len(calls) == 1 and not calls[0].ok and calls[0].source == "fixture"
    assert calls[0].to_event()["credit"] is False


async def test_replay_never_spends_budget(dirs):
    c = client(dirs, mode="replay")
    b = CreditBudget(5)
    with pytest.raises(ReplayMiss):
        await c.search("google_maps", {"q": "x"}, purpose="p", budget=b)
    assert b.spent == 0


async def test_replay_uses_stale_cache(dirs):
    c = client(dirs, mode="auto")
    await c.search("google_maps_reviews", PARAMS, purpose="p")
    rec = next(dirs[0].glob("*.json"))
    d = json.loads(rec.read_text(encoding="utf-8"))
    d["ts"] = 0
    rec.write_text(json.dumps(d), encoding="utf-8")
    r = client(dirs, mode="replay")
    calls = []
    await r.search("google_maps_reviews", PARAMS, purpose="p", on_call=calls.append)
    assert calls[0].source == "cache"


async def test_none_params_dropped_before_key(dirs):
    write_serp_fixture(dirs[1], "google_maps", {"q": "x"}, {"local_results": []})
    c = client(dirs, mode="replay")
    assert await c.search("google_maps", {"q": "x", "ll": None}, purpose="p") == {"local_results": []}
    assert cache_key("google_maps", {"q": "x"}) in c.used_keys


async def test_fixture_dir_optional(dirs):
    c = client(dirs, mode="replay", fixtures=False)
    with pytest.raises(ReplayMiss):
        await c.search("google_maps", {"q": "x"}, purpose="p")


# --- live + cache --------------------------------------------------------------------------------

async def test_live_call_spends_one_credit_and_caches(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake)
    b = CreditBudget(3)
    calls = []
    data = await c.search("google_maps_reviews", PARAMS, purpose="Lowest", budget=b, on_call=calls.append)
    assert len(data["reviews"]) == 20
    assert b.spent == 1 and len(fake.requests) == 1
    assert calls[0].source == "live" and calls[0].to_event()["credit"] is True
    again = await c.search("google_maps_reviews", PARAMS, purpose="Lowest", budget=b, on_call=calls.append)
    assert again["reviews"] == data["reviews"]
    assert b.spent == 1 and len(fake.requests) == 1 and calls[1].source == "cache"


async def test_live_request_shape(dirs):
    fake = FakeSerpApi()
    await client(dirs, fake).search("google_maps_reviews", PARAMS, purpose="p")
    req = fake.requests[0]
    assert str(req.url).startswith(SERPAPI_URL)
    q = dict(req.url.params)
    assert q["engine"] == "google_maps_reviews" and q["api_key"] == KEY
    assert q["query"] == "knee" and q["sort_by"] == "ratingLow" and q["num"] == "20"


async def test_api_key_never_written(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake)
    await c.search("google_maps_reviews", PARAMS, purpose="p")
    await c.search("google_maps", {"q": "x", "api_key": KEY}, purpose="p")
    text = all_text(dirs[0])
    assert text and KEY not in text and "api_key" not in text
    rec = json.loads(next(dirs[0].glob("*.json")).read_text(encoding="utf-8"))
    assert set(rec) == {"ts", "fetched_at", "engine", "params", "response"}


async def test_api_key_param_does_not_split_cache(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake)
    await c.search("google_maps_reviews", PARAMS, purpose="p")
    await c.search("google_maps_reviews", {**PARAMS, "api_key": "other"}, purpose="p")
    assert len(fake.requests) == 1


async def test_cache_written_atomically(dirs):
    await client(dirs).search("google_maps_reviews", PARAMS, purpose="p")
    assert not list(dirs[0].glob("*.tmp"))
    assert (dirs[0] / f"{cache_key('google_maps_reviews', PARAMS)}.json").exists()


async def test_live_mode_bypasses_cache(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake, mode="live")
    await c.search("google_maps_reviews", PARAMS, purpose="p")
    await c.search("google_maps_reviews", PARAMS, purpose="p")
    assert len(fake.requests) == 2


async def test_auto_prefers_fixture(dirs):
    write_serp_fixture(dirs[1], "google_maps_reviews", PARAMS, load_payload("rev_aster"))
    fake = FakeSerpApi()
    data = await client(dirs, fake).search("google_maps_reviews", PARAMS, purpose="p", budget=CreditBudget(0))
    assert fake.requests == [] and data["search_information"]["reviews_results_state"] == "No reviews"


async def test_ttl_expiry_goes_live(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake, ttl=1)
    await c.search("google_maps_reviews", PARAMS, purpose="p")
    rec = next(dirs[0].glob("*.json"))
    d = json.loads(rec.read_text(encoding="utf-8"))
    d["ts"] = time.time() - 7200
    rec.write_text(json.dumps(d), encoding="utf-8")
    await c.search("google_maps_reviews", PARAMS, purpose="p")
    assert len(fake.requests) == 2


async def test_budget_exceeded_before_http(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake)
    calls = []
    with pytest.raises(BudgetExceeded):
        await c.search("google_maps", {"q": "x"}, purpose="p", budget=CreditBudget(0), on_call=calls.append)
    assert fake.requests == [] and not calls[0].ok and "budget" in calls[0].error


@pytest.mark.parametrize("status,error", [(500, None), (401, "Invalid API key."), (200, "Your account has run out"),
                                          (429, "rate limit")])
async def test_failed_search_refunded(dirs, status, error):
    fake = FakeSerpApi(status=status, error=error)
    c = client(dirs, fake)
    b = CreditBudget(1)
    calls = []
    with pytest.raises(SerpError):
        await c.search("google_maps", {"q": "x"}, purpose="p", budget=b, on_call=calls.append)
    assert b.spent == 0
    assert not list(dirs[0].glob("*.json"))
    assert calls[0].ok is False and calls[0].to_event()["credit"] is False


async def test_error_message_does_not_leak_key(dirs):
    fake = FakeSerpApi(status=401, error="Invalid API key.")
    with pytest.raises(SerpError) as e:
        await client(dirs, fake).search("google_maps", {"q": "x"}, purpose="p")
    assert KEY not in str(e.value)


async def test_non_json_response(dirs):
    fake = FakeSerpApi(status=502, raw=b"<html>bad gateway</html>")
    b = CreditBudget(1)
    with pytest.raises(SerpError, match="non-JSON"):
        await client(dirs, fake).search("google_maps", {"q": "x"}, purpose="p", budget=b)
    assert b.spent == 0


async def test_transport_error_retried_once(dirs):
    fake = FakeSerpApi(fail_times=1)
    data = await client(dirs, fake).search("google_maps_reviews", PARAMS, purpose="p")
    assert len(fake.requests) == 2 and data["reviews"]


async def test_transport_error_twice_refunds(dirs):
    fake = FakeSerpApi(fail_times=2)
    b = CreditBudget(1)
    with pytest.raises(SerpError, match="network error: ConnectError"):
        await client(dirs, fake).search("google_maps", {"q": "x"}, purpose="p", budget=b)
    assert b.spent == 0 and len(fake.requests) == 2


async def test_no_results_is_a_valid_billed_answer(dirs):
    fake = FakeSerpApi(payload={}, error="Google hasn't returned any results for this query.")
    c = client(dirs, fake)
    b = CreditBudget(2)
    data = await c.search("google_maps_reviews", PARAMS, purpose="p", budget=b)
    assert "hasn't returned any results" in data["error"] and b.spent == 1
    await c.search("google_maps_reviews", PARAMS, purpose="p", budget=b)
    assert len(fake.requests) == 1  # cached


async def test_hourly_cap(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake, live_per_hour=2)
    b = CreditBudget(10)
    for i in range(2):
        await c.search("google_maps", {"q": f"x{i}"}, purpose="p", budget=b)
    with pytest.raises(BudgetExceeded, match="hourly"):
        await c.search("google_maps", {"q": "x9"}, purpose="p", budget=b)
    assert b.spent == 2 and len(fake.requests) == 2
    # cached queries still work after the cap
    await c.search("google_maps", {"q": "x0"}, purpose="p", budget=b)


async def test_hourly_cap_window_slides(dirs):
    c = client(dirs, live_per_hour=1)
    await c.search("google_maps", {"q": "a"}, purpose="p")
    c._live_times[0] -= 3601
    await c.search("google_maps", {"q": "b"}, purpose="p")


async def test_hourly_cap_zero_means_unlimited(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake, live_per_hour=0)
    for i in range(5):
        await c.search("google_maps", {"q": f"x{i}"}, purpose="p")
    assert len(fake.requests) == 5


async def test_async_on_call_awaited(dirs):
    seen = []

    async def on_call(call):
        seen.append(call.source)

    await client(dirs).search("google_maps", {"q": "x"}, purpose="p", on_call=on_call)
    assert seen == ["live"]


async def test_used_keys_recorded(dirs):
    c = client(dirs)
    await c.search("google_maps", {"q": "x"}, purpose="p")
    assert c.used_keys == {cache_key("google_maps", {"q": "x"})}


# --- account ---------------------------------------------------------------------------------------

async def test_account_without_key(dirs):
    assert await SerpClient(None, dirs[0]).account() is None


async def test_account_parsed(dirs):
    def handler(request):
        assert str(request.url).startswith(ACCOUNT_URL)
        return httpx.Response(200, json={"plan_name": "Free", "total_searches_left": 93, "this_hour_searches": 2,
                                         "account_rate_limit_per_hour": 100, "api_key": KEY})

    c = SerpClient(KEY, dirs[0], transport=httpx.MockTransport(handler))
    assert await c.account() == {"plan": "Free", "searches_left": 93, "this_hour": 2, "hourly_limit": 100}


async def test_account_failure_is_none(dirs):
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    c = SerpClient(KEY, dirs[0], transport=httpx.MockTransport(handler))
    assert await c.account() is None


# --- daily cap and slot release ----------------------------------------------------------------------

async def test_daily_cap(dirs):
    fake = FakeSerpApi()
    c = client(dirs, fake)
    c.live_per_day = 2
    for i in range(2):
        await c.search("google_maps", {"q": f"d{i}"}, purpose="p")
    with pytest.raises(BudgetExceeded, match="daily"):
        await c.search("google_maps", {"q": "d9"}, purpose="p")
    assert len(fake.requests) == 2


async def test_daily_cap_window_is_a_day(dirs):
    c = client(dirs)
    c.live_per_day = 1
    await c.search("google_maps", {"q": "a"}, purpose="p")
    c._live_times[0] -= 3601  # an hour ago still counts towards the day
    with pytest.raises(BudgetExceeded, match="daily"):
        await c.search("google_maps", {"q": "b"}, purpose="p")
    c._live_times[0] -= 86400
    await c.search("google_maps", {"q": "b"}, purpose="p")


async def test_failed_search_releases_cap_slot(dirs):
    class Flaky(FakeSerpApi):
        def __call__(self, request):
            if not self.requests:
                self.requests.append(request)
                return httpx.Response(500, json={"error": "Internal error"})
            return super().__call__(request)

    c = client(dirs, Flaky(), live_per_hour=1)
    with pytest.raises(SerpError):
        await c.search("google_maps", {"q": "a"}, purpose="p")
    await c.search("google_maps", {"q": "a"}, purpose="p")  # the failed try didn't use the only slot
    with pytest.raises(BudgetExceeded):
        await c.search("google_maps", {"q": "b"}, purpose="p")
