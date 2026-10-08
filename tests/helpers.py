"""Shared test helpers: probe payloads, fixture writers, review builders and a replay driver."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app import pipeline
from app.llm import LLM
from app.serp import SerpClient, cache_key

DATA = Path(__file__).parent / "data"

# A fixed "today" for every date-dependent assertion (cutoff = NOW - 731 days = 2024-10-08).
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

# data_ids in probe/raw/maps.json
MANIPAL_WF = "0x3bae11fc05fbc8a1:0xd4c8ae89f2811666"
MANIPAL_VARTHUR = "0x3bae0df61d3a1a4b:0x24f86d9cf8e48abb"
ASTER = "0x3bae11a84d4cb329:0xb1b44545b4227d0d"
SATHYA = "0x3bae104dbb3a3807:0x39aea21265696d1"

Responder = Callable[[str, dict[str, Any]], dict[str, Any] | None]


def load_payload(name: str) -> dict[str, Any]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def write_serp_fixture(fixtures_dir: Path, engine: str, params: dict[str, Any], response: Any) -> Path:
    clean = {k: v for k, v in params.items() if v is not None}
    path = fixtures_dir / f"{cache_key(engine, clean)}.json"
    path.write_text(json.dumps({"engine": engine, "params": clean, "response": response}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def write_llm_fixture(fixtures_dir: Path, key: str, data: dict[str, Any]) -> Path:
    d = fixtures_dir / "llm"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def rev(rating: Any, date: str | None, snippet: str = "", rid: str | None = None, *, edited: str | None = None,
        reply: bool = False, link: str | None = None) -> dict[str, Any]:
    """A google_maps_reviews item shaped like the probe JSON."""
    r: dict[str, Any] = {"rating": rating, "snippet": snippet}
    if rid is not None:
        r["review_id"] = rid
    if date is not None:
        r["iso_date"] = date
        r["iso_date_of_last_edit"] = edited or date
    if reply:
        r["response"] = {"iso_date": date, "snippet": "We are sorry to hear this. Please write to us."}
    r["link"] = link if link is not None else f"https://www.google.com/maps/reviews/data={rid or 'x'}"
    return r


def reviews_payload(reviews: list[Any] | Any) -> dict[str, Any]:
    return {"search_parameters": {"engine": "google_maps_reviews"}, "reviews": reviews}


NO_REVIEWS = {"search_parameters": {"engine": "google_maps_reviews"},
              "search_information": {"reviews_results_state": "No reviews"}}


def place(title: str, data_id: str, reviews: Any = 5000, *, type_: str = "Hospital", rating: Any = 4.5,
          types: list[Any] | None = None, lat: float = 12.97, lng: float = 77.75) -> dict[str, Any]:
    return {"title": title, "data_id": data_id, "place_id": f"pid-{data_id}", "rating": rating, "reviews": reviews,
            "type": type_, "types": types if types is not None else [type_], "address": f"{title} Road, Bengaluru",
            "gps_coordinates": {"latitude": lat, "longitude": lng}}


def maps_payload(places: list[Any]) -> dict[str, Any]:
    return {"search_parameters": {"engine": "google_maps"}, "local_results": places}


def make_deps(dirs: tuple[Path, Path], *, credits: int = 7, llm: LLM | None = None, mode: str = "replay",
              api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
              live_per_hour: int = 0) -> pipeline.Deps:
    cache, fixtures = dirs
    serp = SerpClient(api_key, cache, fixtures, mode=mode, ttl_hours=168, transport=transport,
                      live_per_hour=live_per_hour)
    llm = llm or LLM(None, "test-model", cache, fixtures, replay=True)
    return pipeline.Deps(serp=serp, llm=llm, credits_per_check=credits)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, copy.deepcopy(data)))

    def of(self, name: str) -> list[dict[str, Any]]:
        return [d for e, d in self.events if e == name]

    @property
    def names(self) -> list[str]:
        return [e for e, _ in self.events]


async def run_replay(deps: pipeline.Deps, fixtures: Path, responder: Responder, procedure: str = "knee",
                     area: str = "Whitefield", city: str = "Bengaluru", now: datetime = NOW,
                     max_rounds: int = 6) -> tuple[dict[str, Any], Recorder]:
    """Run the pipeline in replay mode, recording a fixture for every miss the responder can answer, until a run
    has no answerable misses. The params come from the pipeline's own `serp_call` events, so the fixtures are
    keyed exactly as the pipeline asks for them."""
    for _ in range(max_rounds):
        rec = Recorder()
        result = await pipeline.run(procedure, area, city, deps, rec, now=now)
        new = 0
        for call in rec.of("serp_call"):
            if call["ok"]:
                continue
            resp = responder(call["engine"], call["params"])
            if resp is None:
                continue
            path = fixtures / f"{cache_key(call['engine'], call['params'])}.json"
            if not path.exists():
                write_serp_fixture(fixtures, call["engine"], call["params"], resp)
                new += 1
        if not new:
            return result, rec
    raise AssertionError("replay fixtures did not converge")


def table_responder(maps: dict[str, Any] | None, reviews: dict[tuple[str, str], Any]) -> Responder:
    """reviews: {(data_id, sort_by): payload}; (data_id, '*') answers both sorts."""

    def respond(engine: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if engine == "google_maps":
            return maps
        key = (params.get("data_id"), params.get("sort_by"))
        if key in reviews:
            return reviews[key]
        return reviews.get((params.get("data_id"), "*"))

    return respond


def probe_responder(aster_low: str = "rev_aster", aster_new: str = "rev_aster") -> Responder:
    """Realistic: Manipal answers both slices, Aster's filter says "No reviews", Sathya Sai is never recorded."""
    return table_responder(load_payload("maps"), {
        (MANIPAL_WF, "ratingLow"): load_payload("rev_manipal_low"),
        (MANIPAL_WF, "newestFirst"): load_payload("rev_manipal"),
        (ASTER, "ratingLow"): load_payload(aster_low),
        (ASTER, "newestFirst"): load_payload(aster_new),
    })


def card(result: dict[str, Any], data_id: str) -> dict[str, Any]:
    return next(c for c in result["hospitals"] if c["data_id"] == data_id)


def parse_sse(text: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for block in re.split(r"\r?\n\r?\n", text):
        event, data = None, []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if event:
            out.append((event, json.loads("\n".join(data)) if data else None))
    return out
