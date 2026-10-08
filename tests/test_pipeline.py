"""app/pipeline.py end to end, in replay mode over tmp fixtures keyed exactly as the pipeline asks for them."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest

from app import pipeline
from app import themes as th
from app.catalog import CITIES, PROCEDURES
from app.llm import LLM
from app.pipeline import _parse_date, short

from .helpers import (
    ASTER,
    MANIPAL_WF,
    NO_REVIEWS,
    NOW,
    SATHYA,
    Recorder,
    card,
    load_payload,
    make_deps,
    maps_payload,
    place,
    probe_responder,
    rev,
    reviews_payload,
    run_replay,
    table_responder,
    write_llm_fixture,
)

KNEE = PROCEDURES["knee"]
CUTOFF = NOW - timedelta(days=round(30.44 * 24))
MANIPAL_TITLE = "Manipal Hospital Whitefield"
ASTER_TITLE = "Aster Hospital Whitefield Bangalore"


class SpyLLM(LLM):
    """Records every (system, user, schema) the pipeline sends; replays like the real LLM class."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.prompts: list[tuple[str, str, dict]] = []

    async def json(self, system, user, schema, name):
        self.prompts.append((system, user, schema))
        return await super().json(system, user, schema, name)

    def for_hospital(self, title: str) -> list[tuple[str, str, dict]]:
        return [p for p in self.prompts if title in p[1]]


def spy(dirs) -> SpyLLM:
    return SpyLLM(None, "test-model", *dirs, replay=True)


def label_all(llm: SpyLLM, fixtures, title: str, **fields) -> None:
    """Write an LLM fixture labelling ids 0..59 of the prompt(s) for one hospital (unknown ids are dropped)."""
    for system, user, schema in llm.for_hospital(title):
        labels = [{"id": i, "raises_problem": True, "scope": "other", "themes": [], "reason": "", **fields}
                  for i in range(60)]
        write_llm_fixture(fixtures, llm._key(system, user, schema), {"labels": labels})


# Synthetic hospitals for exact counting ------------------------------------------------------------

A, B, C = "0xa:0x1", "0xb:0x2", "0xc:0x3"
SYN_MAPS = maps_payload([place("Alpha Hospital", A, 9000, rating=4.7), place("Beta Hospital", B, 8000, rating=4.7),
                         place("Gamma Hospital", C, 7000, rating=4.6)])


def syn(low_a, new_a=None, low_b=NO_REVIEWS, new_b=NO_REVIEWS):
    table = {(A, "ratingLow"): low_a, (A, "newestFirst"): new_a or reviews_payload([]),
             (B, "ratingLow"): low_b, (B, "newestFirst"): new_b}
    return table_responder(SYN_MAPS, table)


def d(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


ALPHA_LOW = reviews_payload([
    rev(1.0, d(30), "Knee replacement surgery: final bill was 2 lakh over the estimate.", "a1", reply=True),
    rev(2.0, d(200), "Came for an OPD appointment for knee pain, waited 3 hours.", "a2"),
    rev(1.0, d(1000), "Knee surgery in 2023, wound infection after discharge.", "a3", reply=True),
    rev(1.0, d(400), "The nurse was rude while my father was admitted for knee replacement.", "a4"),
    rev(4.0, d(10), "Knee replacement went well.", "a5", reply=True),
    rev(5.0, d(5), "Excellent knee surgery.", "a6"),
])


def one(r):
    """A low slice holding one review, recent enough to be shown as an excerpt."""
    return syn(reviews_payload([r]))


# --- shape, params and keyword ---------------------------------------------------------------------

async def test_probe_params_same_keyword_two_sorts(dirs):
    result, rec = await run_replay(make_deps(dirs), dirs[1], probe_responder())
    calls = rec.of("serp_call")
    maps = [c for c in calls if c["engine"] == "google_maps"]
    reviews = [c for c in calls if c["engine"] == "google_maps_reviews"]
    assert len(maps) == 1 and len(reviews) == 6 and len(calls) == result["searches"] == 7
    q = maps[0]["params"]
    assert q["q"] == f"{KNEE.search} in Whitefield, Bengaluru"
    lat, lng = CITIES["Bengaluru"]
    assert q["ll"].startswith(f"@{lat},{lng},") and q["type"] == "search" and q["hl"] == "en" and q["gl"] == "in"
    assert {c["params"]["query"] for c in reviews} == {KNEE.keyword} == {result["keyword"]}
    per: dict[str, list[str]] = {}
    for c in reviews:
        per.setdefault(c["params"]["data_id"], []).append(c["params"]["sort_by"])
    assert {k: sorted(v) for k, v in per.items()} == {h: ["newestFirst", "ratingLow"]
                                                      for h in (MANIPAL_WF, ASTER, SATHYA)}
    assert all(str(c["params"]["num"]) == "20" for c in reviews)


@pytest.mark.parametrize("pid", list(PROCEDURES))
async def test_every_procedure_uses_one_keyword_for_all_hospitals(dirs, pid):
    _, rec = await run_replay(make_deps(dirs), dirs[1], syn(ALPHA_LOW), procedure=pid)
    queries = {c["params"]["query"] for c in rec.of("serp_call") if c["engine"] == "google_maps_reviews"}
    assert queries == {PROCEDURES[pid].keyword}
    start = rec.of("start")[0]
    assert start["keyword"] == PROCEDURES[pid].keyword and start["procedure"] == PROCEDURES[pid].label


async def test_event_sequence(dirs):
    _, rec = await run_replay(make_deps(dirs), dirs[1], probe_responder())
    names = rec.names
    assert names[0] == "start" and names[-2:] == ["result", "done"]
    assert names.index("hospitals") < names.index("result")
    assert rec.of("start")[0] == {"procedure": "Knee replacement", "place": "Whitefield, Bengaluru",
                                  "keyword": "knee", "mode": "replay"}
    steps = rec.of("step")
    assert [s["id"] for s in steps] == ["find", "find", "reviews", "reviews", "label", "label"]
    assert [s["status"] for s in steps] == ["running", "done"] * 3
    assert "keyword rules" in steps[-1]["label"]
    assert rec.of("done")[0]["credits_spent"] == 0
    assert "error" not in names and "failure" not in names


async def test_hospitals_event(dirs):
    _, rec = await run_replay(make_deps(dirs), dirs[1], probe_responder())
    ev = rec.of("hospitals")[0]
    assert [h["data_id"] for h in ev["hospitals"]] == [MANIPAL_WF, ASTER, SATHYA]
    assert any(s["why"] == "another branch of the same hospital group" for s in ev["skipped"])
    assert len(ev["skipped"]) <= 25


# --- realistic probe run ---------------------------------------------------------------------------

async def test_probe_result_overview(dirs):
    result, rec = await run_replay(make_deps(dirs), dirs[1], probe_responder())
    assert result["procedure"] == "Knee replacement" and result["procedure_id"] == "knee"
    assert result["place"] == "Whitefield, Bengaluru" and result["city"] == "Bengaluru"
    assert result["credits_spent"] == 0 and result["label_source"] == "rules"
    assert result["as_of"] == "2026-10-09" and result["recent_months"] == 24
    assert result["themes"] == th.THEMES
    assert [c["status"] for c in result["hospitals"]] == ["ok", "no_reviews", "failed"]
    assert rec.of("result")[0]["hospitals"][0]["complaints"] == result["hospitals"][0]["complaints"]


async def test_probe_manipal_card(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1], probe_responder())
    m = card(result, MANIPAL_WF)
    assert m["title"] == MANIPAL_TITLE and m["rating"] == 4.7 and m["reviews"] == 37221
    assert m["status"] == "ok"
    assert m["low_read"] == 20 and m["new_read"] == 20
    assert m["complaints"] == 5 and m["complete"] is True  # five 1★, then 4★ — the list is exhaustive
    assert m["complaints_recent"] == 0 and m["complaints_recent_procedure"] == 0
    assert m["newest_complaint"] == "2022-11-13"  # dated by the original review, not the 2025 edit
    assert m["replied"] == 5
    assert m["new_critical"] == 0 and m["new_span"] == ["2025-10-28", "2026-08-25"]
    assert m["excerpts"] == [] and all(v == 0 for v in m["themes"].values())


async def test_probe_aster_no_reviews_is_not_zero_complaints(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1], probe_responder())
    a = card(result, ASTER)
    assert a["status"] == "no_reviews"
    assert a["low_read"] == 0 and a["new_read"] == 0 and a["new_span"] is None and a["excerpts"] == []


async def test_probe_unrecorded_hospital_failed_with_notice(dirs):
    result, rec = await run_replay(make_deps(dirs), dirs[1], probe_responder())
    s = card(result, SATHYA)
    assert s["status"] == "failed" and s["low_read"] == 0
    notices = [n["text"] for n in rec.of("notice")]
    assert sum("not recorded" in n for n in notices) == 2
    assert all("Sathya Sai" in n for n in notices)


async def test_probe_aster_twenty_of_twenty_rules(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1], probe_responder(aster_low="rev_aster2"))
    a = card(result, ASTER)
    assert a["status"] == "ok" and a["low_read"] == 20
    assert a["complete"] is False  # "≥N": the lowest-first list never reached a 3★ review
    assert 15 <= a["complaints"] <= 20
    assert a["complaints_recent_procedure"] <= a["complaints_recent"] <= 12
    assert a["replied"] <= 1
    assert a["newest_complaint"] <= "2026-06-26"


async def test_probe_excerpts_redacted_recent_and_capped(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1], probe_responder(aster_low="rev_aster2"))
    a = card(result, ASTER)
    assert 0 < len(a["excerpts"]) <= 6
    assert all(e["recent"] and e["critical"] for e in a["excerpts"])
    procs = [e["scope"] == "procedure_or_admission" for e in a["excerpts"]]
    assert procs == sorted(procs, reverse=True)  # procedure complaints first
    assert all(e["date"] and e["link"].startswith("https://www.google.com/maps/") for e in a["excerpts"])
    blob = json.dumps(result, ensure_ascii=False)
    assert "Somshekar" not in blob
    assert '"snippet"' not in blob  # raw review text never leaves the pipeline


async def test_probe_asks_only_for_present_themes(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1], probe_responder(aster_low="rev_aster2"))
    totals = {t: sum(c["themes"][t] for c in result["hospitals"]) for t in th.THEMES}
    asks = result["asks"]
    assert len(asks) <= 5
    assert {a["theme"] for a in asks} <= {t for t, n in totals.items() if n}
    assert all(a["count"] == totals[a["theme"]] and a["question"] == th.QUESTIONS[a["theme"]] for a in asks)
    assert [a["count"] for a in asks] == sorted((a["count"] for a in asks), reverse=True)
    assert all(a["hospitals"] == [ASTER_TITLE] for a in asks)


async def test_replay_twice_is_identical_and_free(dirs):
    deps = make_deps(dirs)
    r1, _ = await run_replay(deps, dirs[1], probe_responder(aster_low="rev_aster2"))
    rec = Recorder()
    r2 = await pipeline.run("knee", "Whitefield", "Bengaluru", deps, rec, now=NOW)
    for r in (r1, r2):
        r.pop("ms")
    assert r1 == r2 and r2["credits_spent"] == 0
    assert all(c["source"] == "fixture" for c in rec.of("serp_call") if c["ok"])
    assert not any(c["credit"] for c in rec.of("serp_call"))


# --- exact counting on synthetic data --------------------------------------------------------------

async def test_counts_synthetic(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(ALPHA_LOW))
    a = card(result, A)
    assert a["low_read"] == 6 and a["complete"] is True
    assert a["complaints"] == 4
    assert a["complaints_recent"] == 3  # a1, a2, a4 (a3 is 1000 days old)
    assert a["complaints_recent_procedure"] == 2  # a1, a4 — a2 is an OPD visit
    assert a["replied"] == 2  # a1, a3 (a5 is not a complaint)
    assert a["newest_complaint"] == d(30)[:10]
    assert a["themes"]["billing"] == 1 and a["themes"]["staff"] == 1 and a["themes"]["waiting"] == 0
    assert [e["id"] for e in a["excerpts"]] == ["a1", "a4", "a2"]
    assert [x["theme"] for x in result["asks"]] == [t for t in th.QUESTIONS if a["themes"][t]]
    assert all(x["hospitals"] == ["Alpha Hospital"] for x in result["asks"])


@pytest.mark.parametrize("n,stars,complete", [(20, 1.0, False), (20, 2.0, False), (19, 1.0, True), (1, 1.0, True),
                                              (0, 1.0, False)])  # an empty lowest slice is never "complete"
async def test_complete_flag(dirs, n, stars, complete):
    low = reviews_payload([rev(stars, d(10 + i), "Billing was wrong", f"r{i}") for i in range(n)])
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(low))
    a = card(result, A)
    assert a["complete"] is complete and a["complaints"] == n


async def test_twenty_with_a_three_star_is_complete(dirs):
    low = reviews_payload([rev(1.0, d(10 + i), "Billing was wrong", f"r{i}") for i in range(19)]
                          + [rev(3.0, d(5), "ok", "r19")])
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(low))
    a = card(result, A)
    assert a["complete"] is True and a["complaints"] == 19


async def test_newest_slice(dirs):
    new = reviews_payload([rev(1.0, "2026-09-01T10:00:00Z", "Billing was a mess after knee surgery", "n1"),
                           rev(5.0, "2026-08-01T10:00:00Z", "Great", "n2"),
                           rev(2.0, "2026-07-15T10:00:00Z", "Waited hours for the doctor", "n3"),
                           rev(4.0, None, "No date", "n4")])
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(ALPHA_LOW, new_a=new))
    a = card(result, A)
    assert a["new_read"] == 4 and a["new_critical"] == 2
    assert a["new_span"] == ["2026-07-15", "2026-09-01"]
    # a recent 1★ in the newest list counts even when it isn't among the 20 lowest
    assert a["complaints"] == 6 and a["newest_complaint"] == max(d(30)[:10], "2026-09-01")


async def test_review_in_both_slices_counted_and_labelled_once(dirs):
    llm = spy(dirs)
    shared = rev(1.0, d(30), "Knee surgery bill doubled", "same")
    low = reviews_payload([shared, rev(4.0, d(3), "ok", "x")])
    result, _ = await run_replay(make_deps(dirs, llm=llm), dirs[1], syn(low, new_a=reviews_payload([shared])))
    a = card(result, A)
    assert a["complaints"] == 1 and a["new_critical"] == 1 and len(a["excerpts"]) == 1
    prompts = llm.for_hospital("Alpha Hospital")
    assert len(prompts) == 1 and prompts[0][1].count("Knee surgery bill doubled") == 1


async def test_reply_detection(dirs):
    low = reviews_payload([
        {**rev(1.0, d(5), "Billing bad", "r1"), "response": {"snippet": "Sorry"}},
        {**rev(1.0, d(5), "Billing bad", "r2"), "response": {"extracted_snippet": {"original": "Sorry"}}},
        {**rev(1.0, d(5), "Billing bad", "r3"), "response": {}},
        {**rev(1.0, d(5), "Billing bad", "r4"), "response": "Sorry"},
        {**rev(1.0, d(5), "Billing bad", "r5"), "response": None},
        {**rev(1.0, d(5), "Billing bad", "r6"), "response": {"snippet": ""}},
    ])
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(low))
    views = {v["id"]: v["replied"] for v in card(result, A)["excerpts"]}
    assert views == {"r1": True, "r2": True, "r3": False, "r4": False, "r5": False, "r6": False}
    assert card(result, A)["replied"] == 2


async def test_low_star_praise_is_not_a_complaint(dirs):
    low = reviews_payload([rev(2.0, d(10), "Father full satisfied, thank you all", "p1"),
                           rev(1.0, d(10), "Billing overcharged us", "p2")])
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(low))
    a = card(result, A)
    assert a["complaints"] == 1 and [e["id"] for e in a["excerpts"]] == ["p2"]


# --- dates -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,iso", [
    ("2021-02-15T07:08:03Z", "2021-02-15T07:08:03+00:00"),
    ("2026-05-01", "2026-05-01T00:00:00+00:00"),
    ("2026-05-01T10:00:00+05:30", "2026-05-01T10:00:00+05:30"),
])
def test_parse_date(value, iso):
    assert _parse_date(value).isoformat() == iso


@pytest.mark.parametrize("value", [None, "", "a year ago", "Edited 2 months ago", 5, "2026-13-01", {"x": 1}])
def test_parse_date_bad(value):
    assert _parse_date(value) is None


@pytest.mark.parametrize("delta,shown", [
    (timedelta(0), False),
    (timedelta(minutes=21), False),
    (timedelta(days=7), False),
    (timedelta(days=7, hours=23), False),
    (timedelta(days=8), True),
    (timedelta(days=90), True),
    (-timedelta(days=30), False),
])
async def test_edited_date_only_when_more_than_7_days_later(dirs, delta, shown):
    when = NOW - timedelta(days=100)
    edited = (when + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    result, _ = await run_replay(make_deps(dirs), dirs[1],
                                 one(rev(1.0, when.strftime("%Y-%m-%dT%H:%M:%SZ"), "Billing bad", "r", edited=edited)))
    v = card(result, A)["excerpts"][0]
    assert v["date"] == when.date().isoformat()
    assert v["edited"] == ((when + delta).date().isoformat() if shown else None)


async def test_old_review_edited_recently_is_not_recent(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1],
                                 one(rev(1.0, "2021-02-15T07:08:03Z", "Billing bad", "r", edited=d(10))))
    a = card(result, A)
    assert a["complaints"] == 1 and a["complaints_recent"] == 0 and a["newest_complaint"] == "2021-02-15"


@pytest.mark.parametrize("offset,recent", [(timedelta(0), True), (timedelta(seconds=-1), False),
                                           (timedelta(days=1), True), (timedelta(days=-400), False)])
async def test_recent_cutoff_boundary(dirs, offset, recent):
    when = (CUTOFF + offset).strftime("%Y-%m-%dT%H:%M:%SZ")
    result, _ = await run_replay(make_deps(dirs), dirs[1], one(rev(1.0, when, "Billing bad", "r")))
    assert card(result, A)["complaints_recent"] == int(recent)
    assert len(card(result, A)["excerpts"]) == int(recent)


async def test_now_drives_recency_without_fetch_time(dirs):
    deps = make_deps(dirs)
    await run_replay(deps, dirs[1], one(rev(1.0, "2025-01-01T00:00:00Z", "Knee surgery bill", "r")))
    later = await pipeline.run("knee", "Whitefield", "Bengaluru", deps, Recorder(), now=NOW + timedelta(days=800))
    assert card(later, A)["complaints_recent"] == 0
    assert later["as_of"] == (NOW + timedelta(days=800)).date().isoformat()


async def test_recency_measured_from_fetch_time(dirs):
    low = reviews_payload([rev(1.0, "2025-06-01T00:00:00Z", "Knee surgery bill", "r")])
    low["search_metadata"] = {"created_at": "2026-10-08 20:20:29 UTC"}
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(low), now=NOW + timedelta(days=3000))
    assert result["as_of"] == "2026-10-08"
    assert card(result, A)["complaints_recent"] == 1


@pytest.mark.parametrize("meta", [None, "x", {"created_at": "garbage"}, {"created_at": None}, {}])
async def test_bad_fetch_time_falls_back_to_now(dirs, meta):
    low = reviews_payload([rev(1.0, d(10), "Billing bad", "r")])
    low["search_metadata"] = meta
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(low))
    assert result["as_of"] == NOW.date().isoformat()


# --- odd payloads ----------------------------------------------------------------------------------

@pytest.mark.parametrize("reviews", ["oops", None, {"a": 1}, [None, 1, "x", []], [], 5, 3.5, True])
async def test_reviews_not_a_list_of_dicts(dirs, reviews):
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(reviews_payload(reviews)))
    a = card(result, A)
    assert a["low_read"] == 0 and a["status"] == "no_reviews" and a["complaints"] == 0


@pytest.mark.parametrize("rating,critical", [("1", True), ("1.0", True), (None, False), (2, True), (2.5, False),
                                             (1, True), (3.0, False), ([], False), (True, False), ("bad", False)])
async def test_rating_types(dirs, rating, critical):
    result, _ = await run_replay(make_deps(dirs), dirs[1], one(rev(rating, d(10), "Billing bad", "r")))
    assert card(result, A)["complaints"] == int(critical)
    assert card(result, A)["low_read"] == 1


async def test_missing_dates_and_ids(dirs):
    low = reviews_payload([{"rating": 1.0, "snippet": "No date, no id, knee surgery bill"},
                           {"rating": 1.0}, {"rating": 1.0, "iso_date": "garbage", "snippet": None},
                           {"rating": 2.0, "iso_date": None, "iso_date_of_last_edit": "2026-01-01T00:00:00Z"}])
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(low))
    a = card(result, A)
    assert a["low_read"] == 4 and a["complaints_recent"] == 0 and a["newest_complaint"] is None
    assert a["complaints"] <= 4 and a["excerpts"] == []


@pytest.mark.parametrize("link,kept", [("https://www.google.com/maps/reviews/x", True),
                                       ("javascript:alert(1)", False), ("http://www.google.com/maps/x", False),
                                       ("https://evil.example/https://www.google.com/maps/", False), (None, False),
                                       (5, False)])
async def test_only_google_links_kept(dirs, link, kept):
    r = rev(1.0, d(10), "Billing bad", "r")
    r["link"] = link
    result, _ = await run_replay(make_deps(dirs), dirs[1], one(r))
    assert (card(result, A)["excerpts"][0]["link"] is not None) is kept


@pytest.mark.parametrize("maps", [{}, {"local_results": "oops"}, {"local_results": None}, {"local_results": [1, None]},
                                  {"error": "Google hasn't returned any results for this query."}])
async def test_odd_maps_payload(dirs, maps):
    result, rec = await run_replay(make_deps(dirs), dirs[1], table_responder(maps, {}))
    assert result["hospitals"] == [] and result["asks"] == []
    assert any("No hospital" in n["text"] for n in rec.of("notice"))
    assert rec.names[-1] == "done"


async def test_maps_search_failed(dirs):
    result, rec = await run_replay(make_deps(dirs), dirs[1], table_responder(None, {}))
    assert result["hospitals"] == [] and result["searches"] == 1
    texts = [n["text"] for n in rec.of("notice")]
    assert any("not recorded" in t for t in texts) and any("No hospital" in t for t in texts)


async def test_fixture_with_string_ratings_and_bad_gps(dirs):
    maps = maps_payload([{**place("Alpha Hospital", A, "9000"), "rating": "4.7", "gps_coordinates": "x"}])
    result, _ = await run_replay(make_deps(dirs), dirs[1], table_responder(maps, {(A, "*"): reviews_payload([])}))
    a = card(result, A)
    assert a["rating"] is None and a["reviews"] == 9000 and a["status"] == "no_reviews"


async def test_low_failed_but_newest_answered(dirs):
    new = reviews_payload([rev(1.0, d(5), "Billing bad", "n")])
    responder = table_responder(SYN_MAPS, {(A, "newestFirst"): new})
    result, _ = await run_replay(make_deps(dirs), dirs[1], responder)
    a = card(result, A)
    assert a["low_read"] == 0 and a["new_read"] == 1
    assert a["status"] != "no_reviews"  # one failed slice must not read as "Google found nothing"
    if "low_status" in a:
        assert a["low_status"] == "failed"


# --- inputs ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("pid", ["", "liposuction", "KNEE", None, "knee "])
async def test_unknown_procedure_error_event(dirs, pid):
    rec = Recorder()
    out = await pipeline.run(pid, "Whitefield", "Bengaluru", make_deps(dirs), rec, now=NOW)
    assert out == {} and len(rec.names) == 1 and rec.names[0] in ("error", "failure")
    assert rec.events[0][1]["text"]


@pytest.mark.parametrize("city", ["Atlantis", "", "bengaluru", None])
async def test_unknown_city_falls_back_to_bengaluru(dirs, city):
    result, _ = await run_replay(make_deps(dirs), dirs[1], syn(ALPHA_LOW), city=city)
    assert result["city"] == "Bengaluru" and result["place"] == "Whitefield, Bengaluru"


@pytest.mark.parametrize("area,place_", [("", "Bengaluru"), (None, "Bengaluru"), ("   ", "Bengaluru"),
                                         ("  Whitefield   East ", "Whitefield East, Bengaluru"),
                                         ("x" * 80, "x" * 50 + ", Bengaluru")])
async def test_area_normalised(dirs, area, place_):
    result, rec = await run_replay(make_deps(dirs), dirs[1], syn(ALPHA_LOW), area=area)
    assert result["place"] == place_
    maps = next(c for c in rec.of("serp_call") if c["engine"] == "google_maps")
    assert maps["params"]["q"] == f"{KNEE.search} in {place_}"


@pytest.mark.parametrize("city", ["Mumbai", "Delhi", "Kochi"])
async def test_city_centre_in_maps_params(dirs, city):
    _, rec = await run_replay(make_deps(dirs), dirs[1], syn(ALPHA_LOW), city=city)
    maps = next(c for c in rec.of("serp_call") if c["engine"] == "google_maps")
    lat, lng = CITIES[city]
    assert maps["params"]["ll"].startswith(f"@{lat},{lng},")


@pytest.mark.parametrize("title,expected", [("Manipal Hospital Whitefield", "Manipal Hospital Whitefield"),
                                            ("Aster CMI, Hebbal", "Aster CMI"),
                                            ("Fortis - Bannerghatta", "Fortis"),
                                            ("Sakra | World Hospital", "Sakra"), ("x" * 60, "x" * 40)])
def test_short(title, expected):
    assert short(title) == expected


# --- budget ----------------------------------------------------------------------------------------

async def record_maps(dirs):
    """Record the probe Maps answer as a replay fixture, so live-mode tests only go live for reviews."""
    await run_replay(make_deps(dirs), dirs[1], table_responder(load_payload("maps"), {}))


def _never(request):  # pragma: no cover - a request here is a test failure
    raise AssertionError(f"unexpected live request {request.url}")


async def test_budget_zero_gives_notices_not_crash(dirs):
    deps = make_deps(dirs, credits=0, mode="auto", api_key="k", transport=httpx.MockTransport(_never))
    # maps answered by a fixture (free); every review call needs a credit
    result, rec = await run_replay(deps, dirs[1], table_responder(load_payload("maps"), {}))
    assert [c["status"] for c in result["hospitals"]] == ["failed"] * 3
    budget = [n for n in rec.of("notice") if "credit budget of 0 reached" in n["text"]]
    assert len(budget) == 6 and result["credits_spent"] == 0
    assert rec.names[-1] == "done"


async def test_budget_partial(dirs):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=load_payload("rev_manipal_low"))

    await record_maps(dirs)
    deps = make_deps(dirs, credits=2, mode="auto", api_key="k-secret", transport=httpx.MockTransport(handler))
    result, rec = await run_replay(deps, dirs[1], table_responder(load_payload("maps"), {}))
    assert result["credits_spent"] == 2 and len(seen) == 2
    assert sum("credit budget" in n["text"] for n in rec.of("notice")) == 4
    assert [c["status"] for c in result["hospitals"]] == ["ok", "failed", "failed"]
    assert all(s["api_key"] == "k-secret" for s in seen)
    assert not any("k-secret" in p.read_text(encoding="utf-8") for p in dirs[0].rglob("*.json"))
    assert "k-secret" not in json.dumps(rec.events)


async def test_live_errors_become_notices(dirs):
    def handler(request):
        if request.url.params.get("sort_by") == "newestFirst":
            return httpx.Response(500, json={"error": "Internal error"})
        return httpx.Response(200, json=load_payload("rev_aster2"))

    await record_maps(dirs)
    deps = make_deps(dirs, mode="auto", api_key="k", transport=httpx.MockTransport(handler))
    result, rec = await run_replay(deps, dirs[1], table_responder(load_payload("maps"), {}))
    assert result["credits_spent"] == 3
    failed = [n for n in rec.of("notice") if "failed" in n["text"]]
    assert len(failed) == 3 and all("Internal error" in n["text"] for n in failed)
    assert all(c["status"] == "ok" and c["new_read"] == 0 and c["new_span"] is None for c in result["hospitals"])


# --- LLM labels ------------------------------------------------------------------------------------

async def _probe_with_labels(dirs, **per_hospital):
    """per_hospital: {"aster": {...label fields}, "manipal": {...}} written as LLM fixtures, then re-run."""
    llm = spy(dirs)
    deps = make_deps(dirs, llm=llm)
    await run_replay(deps, dirs[1], probe_responder(aster_low="rev_aster2"))
    titles = {"aster": ASTER_TITLE, "manipal": MANIPAL_TITLE}
    for k, fields in per_hospital.items():
        label_all(llm, dirs[1], titles[k], **fields)
    rec = Recorder()
    result = await pipeline.run("knee", "Whitefield", "Bengaluru", deps, rec, now=NOW)
    return result, rec, llm


async def test_llm_prompts_one_per_hospital(dirs):
    llm = spy(dirs)
    await run_replay(make_deps(dirs, llm=llm), dirs[1], probe_responder(aster_low="rev_aster2"))
    calls = llm.prompts[-2:]
    assert all(s == th.LABEL_SYSTEM and sc == th.LABEL_SCHEMA for s, _, sc in calls)
    assert len(llm.for_hospital(MANIPAL_TITLE)) >= 1 and len(llm.for_hospital(ASTER_TITLE)) >= 1
    for _, user, _ in calls:
        assert "Knee replacement" in user and "knee" in user
        assert not (MANIPAL_TITLE in user and ASTER_TITLE in user)  # one hospital per call
    aster_user = llm.for_hospital(ASTER_TITLE)[-1][1]
    assert "Fraudulent" in aster_user and "x" * 701 not in aster_user


async def test_llm_labels_drive_counts(dirs):
    result, rec, _ = await _probe_with_labels(
        dirs, aster={"scope": "procedure_or_admission", "themes": ["insurance", "billing"]},
        manipal={"scope": "opd_or_consultation", "themes": ["waiting"]})
    a, m = card(result, ASTER), card(result, MANIPAL_WF)
    assert result["label_source"] == "llm"
    assert a["complaints"] == 20 and a["complaints_recent"] == 12  # 10 since 2025 + Oct/Nov 2024
    assert a["complaints_recent_procedure"] == 12 and a["replied"] == 1
    assert a["themes"]["insurance"] == 12 and a["themes"]["billing"] == 12
    assert a["newest_complaint"] == "2026-06-26"
    assert m["complaints"] == 5 and m["complaints_recent_procedure"] == 0 and m["themes"]["waiting"] == 0
    assert [(x["theme"], x["count"]) for x in result["asks"]] == [("billing", 12), ("insurance", 12)]
    assert all(e["label_by"] == "llm" for e in a["excerpts"])
    assert "keyword rules" not in rec.of("step")[-1]["label"]
    assert result["credits_spent"] == 0


async def test_llm_no_problem_reviews_not_counted(dirs):
    result, _, _ = await _probe_with_labels(dirs, aster={"raises_problem": False, "scope": "procedure_or_admission"})
    a = card(result, ASTER)
    assert a["complaints"] == 0 and a["excerpts"] == [] and a["status"] == "ok"


async def test_llm_partial_labels_fall_back_to_rules(dirs):
    result, _, _ = await _probe_with_labels(dirs, aster={"scope": "procedure_or_admission",
                                                         "themes": ["hygiene"]})
    assert result["label_source"] == "llm"
    assert {e["label_by"] for e in card(result, ASTER)["excerpts"]} == {"llm"}
    assert card(result, ASTER)["themes"]["hygiene"] == 12


@pytest.mark.parametrize("bad", [
    {"themes": ["fraud", "scam"]},
    {"scope": "inpatient"},
    {"reason": "Fraud " * 50},
])
async def test_llm_bad_fields_sanitised(dirs, bad):
    result, _, _ = await _probe_with_labels(dirs, aster={"scope": "procedure_or_admission", **bad})
    a = card(result, ASTER)
    assert set(a["themes"]) == set(th.THEMES)
    assert all(t in th.THEMES for e in a["excerpts"] for t in e["themes"])
    assert all(e["scope"] in ("procedure_or_admission", "opd_or_consultation", "other") for e in a["excerpts"])


@pytest.mark.parametrize("data", [
    {"labels": [{"id": 0.0, "scope": "other", "themes": [], "reason": ""}]},
    {"labels": [{"id": "0", "scope": "other", "themes": 5, "reason": ""}]},
    {"labels": 5},
    [{"id": 0}],
    {"labels": [{"id": 999, "scope": "other", "themes": [], "reason": ""}]},
])
async def test_llm_malformed_fixture_falls_back_to_rules(dirs, data):
    llm = spy(dirs)
    deps = make_deps(dirs, llm=llm)
    await run_replay(deps, dirs[1], probe_responder(aster_low="rev_aster2"))
    for system, user, schema in llm.prompts:
        write_llm_fixture(dirs[1], llm._key(system, user, schema), data)
    rec = Recorder()
    result = await pipeline.run("knee", "Whitefield", "Bengaluru", deps, rec, now=NOW)
    assert result["label_source"] == "rules" and rec.names[-1] == "done"


async def test_negated_praise_one_star_is_a_complaint(dirs):
    result, _ = await run_replay(make_deps(dirs), dirs[1], one(rev(1.0, d(10), "Not satisfied with the treatment.",
                                                                   "r")))
    assert card(result, A)["complaints"] == 1


@pytest.mark.parametrize("low", ["failed", "no_reviews"])
async def test_unread_lowest_slice_is_never_complete(dirs, low):
    new = reviews_payload([rev(5.0, d(5 + i), "Great knee surgery", f"n{i}") for i in range(20)])
    table = {(A, "newestFirst"): new}
    if low == "no_reviews":
        table[(A, "ratingLow")] = NO_REVIEWS
    result, _ = await run_replay(make_deps(dirs), dirs[1], table_responder(SYN_MAPS, table))
    a = card(result, A)
    assert a["new_read"] == 20 and a["complaints_recent"] == 0
    assert a["complete"] is False
