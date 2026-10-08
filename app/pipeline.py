"""The Bedside Manner pipeline.

procedure + area ─ google_maps "<procedure> hospital in <area>"            → the hospitals people choose between
                 ─ per hospital, ONE keyword for all of them (google_maps_reviews, query=<keyword>):
                     A. sort=ratingLow   → the lowest-rated reviews that mention the procedure
                     B. sort=newestFirst → the newest reviews that mention it (what recent patients say)
                 ─ one batched LLM call labels each 1–2★ review: about the procedure/admission or only an
                   OPD visit, and which complaint themes it raises (labels only — never a number)
                 → counts, reply rates, dated + name-redacted excerpts, "ask before you admit" (all in code)

No score, no ranking: Google's star rating and review count are shown as context only.
Every engine failure becomes a `notice`; the pipeline never crashes on an odd payload.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from . import themes as th
from .catalog import CITIES, PROCEDURES, Procedure
from .llm import LLM
from .places import Hospital, pick_hospitals
from .redact import excerpt
from .serp import BudgetExceeded, CreditBudget, ReplayMiss, SerpCall, SerpClient

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
log = logging.getLogger(__name__)

N_HOSPITALS = 3
RECENT_MONTHS = 24
CRITICAL_MAX_STARS = 2
PAGE = 20  # Google returns at most 20 reviews per request


@dataclass
class Deps:
    serp: SerpClient
    llm: LLM
    credits_per_check: int = 7


def _parse_date(s: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


async def run(procedure_id: str, area: str, city: str, deps: Deps, emit: Emit,
              now: datetime | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    now = now or datetime.now(UTC)
    proc: Procedure | None = PROCEDURES.get(procedure_id)
    city = city if city in CITIES else "Bengaluru"
    area = " ".join((area or "").split())[:50]
    budget = CreditBudget(deps.credits_per_check)
    calls: list[SerpCall] = []

    async def on_call(c: SerpCall) -> None:
        calls.append(c)
        await emit("serp_call", c.to_event())

    async def notice(text: str, level: str = "warn") -> None:
        await emit("notice", {"level": level, "text": text})

    async def step(sid: str, label: str, status: str = "running") -> None:
        await emit("step", {"id": sid, "label": label, "status": status})

    async def search(engine: str, params: dict[str, Any], purpose: str) -> dict[str, Any] | None:
        try:
            return await deps.serp.search(engine, params, purpose=purpose, budget=budget, on_call=on_call)
        except BudgetExceeded as e:
            await notice(f"Skipped “{purpose}”: {e}.")
        except ReplayMiss:
            await notice(f"Skipped “{purpose}”: not recorded (replay mode has no API key).")
        except Exception as e:  # noqa: BLE001 - one engine failing must not end the check
            await notice(f"“{purpose}” failed: {str(e)[:120]}")
        return None

    if proc is None:
        await emit("error", {"text": "Pick a procedure from the list."})
        return {}
    place = f"{area}, {city}" if area else city
    kw = proc.keyword
    await emit("start", {"procedure": proc.label, "place": place, "keyword": kw, "mode": deps.serp.mode})

    # 1. Hospitals near the user -------------------------------------------------------------------
    await step("find", f"Finding hospitals for {proc.label.lower()} near {place}")
    lat, lng = CITIES[city]
    maps = await search("google_maps", {"type": "search", "q": f"{proc.search} in {place}",
                                        "ll": f"@{lat},{lng},12z", "hl": "en", "gl": "in"},
                        f"Hospitals for “{proc.label}” near {place}")
    local = (maps or {}).get("local_results")
    hospitals, skipped = pick_hospitals(local if isinstance(local, list) else [], None, N_HOSPITALS)
    await emit("hospitals", {"hospitals": [h.to_dict() for h in hospitals], "skipped": skipped[:25]})
    await step("find", f"Comparing {len(hospitals)} hospitals · skipped {len(skipped)} doctors' listings, clinics, "
                       "small places and extra branches", "done")
    if not hospitals:
        await notice("No hospital with enough Google reviews was found for this search. Try a nearby area or "
                     "the city name only.")

    # 2. Two review slices per hospital, same keyword, all in parallel ----------------------------------
    await step("reviews", f"Reading reviews that mention “{kw}”: lowest-rated first, and newest first")
    slices = await asyncio.gather(*(
        search("google_maps_reviews", {"data_id": h.data_id, "query": kw, "sort_by": sort, "hl": "en", "num": PAGE},
               f"{label} “{kw}” reviews · {short(h.title)}")
        for h in hospitals for sort, label in (("ratingLow", "Lowest-rated"), ("newestFirst", "Newest"))))
    low = [_reviews(slices[2 * i]) for i in range(len(hospitals))]
    new = [_reviews(slices[2 * i + 1]) for i in range(len(hospitals))]
    await step("reviews", "Read " + " · ".join(f"{short(h.title)}: {len(low[i])} + {len(new[i])}"
                                               for i, h in enumerate(hospitals)), "done")

    # 3. Labels for every 1–2★ review (one LLM call; keyword rules if no LLM) ------------------------
    await step("label", "Reading what each complaint is about")
    crit: dict[str, tuple[str, str]] = {}  # review id -> (hospital, snippet)
    for i, h in enumerate(hospitals):
        for r in low[i] + new[i]:
            s = _stars(r)
            if s is not None and s <= CRITICAL_MAX_STARS and r["_id"] not in crit:
                crit[r["_id"]] = (h.title, str(r.get("snippet") or ""))
    ids = list(crit)
    labels: dict[int, dict[str, Any]] = {}
    if ids:
        data, _src = await deps.llm.json(
            th.LABEL_SYSTEM, th.label_prompt(f"{proc.label} (reviews matched the keyword “{kw}”)",
                                             [(n, crit[k][0], crit[k][1]) for n, k in enumerate(ids)]),
            th.LABEL_SCHEMA, "review_labels")
        labels = th.merge_labels(data, set(range(len(ids))))
    by_id = {ids[n]: lab for n, lab in labels.items()}
    label_source = "llm" if by_id else "rules"
    await step("label", f"{len(ids)} complaints labelled by "
                        + ("Gemini (labels only; every count is computed by code)" if by_id else "keyword rules"),
               "done")

    # 4. Facts (code only) ---------------------------------------------------------------------------
    cutoff = now - timedelta(days=round(30.44 * RECENT_MONTHS))
    cards = [_card(h, low[i], new[i], by_id, proc, cutoff, slices[2 * i] is not None)
             for i, h in enumerate(hospitals)]
    result = {
        "procedure": proc.label, "procedure_id": proc.id, "keyword": kw, "place": place, "city": city,
        "hospitals": cards, "skipped": skipped[:25], "themes": th.THEMES, "asks": _asks(cards),
        "label_source": label_source, "recent_months": RECENT_MONTHS, "as_of": now.date().isoformat(),
        "credits_spent": sum(1 for c in calls if c.source == "live" and c.ok),
        "searches": len(calls), "ms": int((time.perf_counter() - t0) * 1000),
    }
    await emit("result", result)
    await emit("done", {"credits_spent": result["credits_spent"], "ms": result["ms"]})
    return result


def short(title: str) -> str:
    return title.split(",")[0].split(" - ")[0].split(" | ")[0][:40]


def _stars(r: dict[str, Any]) -> float | None:
    v = r.get("rating")
    return float(v) if isinstance(v, (int, float)) else None


def _reviews(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    out = []
    for n, r in enumerate((data or {}).get("reviews") or []):
        if isinstance(r, dict):
            out.append({**r, "_id": str(r.get("review_id") or f"{id(data)}-{n}")})
    return out


def _view(r: dict[str, Any], lab: dict[str, Any] | None, proc: Procedure, cutoff: datetime) -> dict[str, Any]:
    snippet = str(r.get("snippet") or "")
    when = _parse_date(r.get("iso_date"))
    edited = _parse_date(r.get("iso_date_of_last_edit"))
    stars = _stars(r)
    critical = stars is not None and stars <= CRITICAL_MAX_STARS
    by = "llm" if lab is not None else None
    if critical and lab is None:
        lab = {"themes": th.rule_themes(snippet), "scope": th.rule_scope(snippet, proc.words), "reason": ""}
        by = "rules"
    resp = r.get("response") if isinstance(r.get("response"), dict) else None
    link = str(r.get("link") or "")
    return {
        "id": r["_id"], "stars": stars, "critical": critical,
        "date": when.date().isoformat() if when else None,
        "edited": edited.date().isoformat() if edited and when and (edited - when).days > 7 else None,
        "recent": bool(when and when >= cutoff),
        "excerpt": excerpt(snippet), "link": link if link.startswith("https://www.google.com/") else None,
        "themes": (lab or {}).get("themes", []) if critical else [],
        "scope": (lab or {}).get("scope", "other") if critical else None,
        "replied": bool(resp and (resp.get("snippet") or resp.get("extracted_snippet"))),
        "label_by": by if critical else None,
    }


def _card(h: Hospital, low: list[dict[str, Any]], new: list[dict[str, Any]], labels: dict[str, dict[str, Any]],
          proc: Procedure, cutoff: datetime, answered: bool) -> dict[str, Any]:
    lv = [_view(r, labels.get(r["_id"]), proc, cutoff) for r in low]
    nv = [_view(r, labels.get(r["_id"]), proc, cutoff) for r in new]
    crit = [r for r in lv if r["critical"]]
    # The lowest-first list holds every 1–2★ match once it reaches a ≥3★ review (or ends before 20).
    complete = len(lv) < PAGE or any(not r["critical"] for r in lv)
    recent_proc = [r for r in crit if r["recent"] and r["scope"] == "procedure_or_admission"]
    recent_any = [r for r in crit if r["recent"]]
    newest_dates = [r["date"] for r in nv if r["date"]]
    themes = {t: sum(1 for r in recent_proc if t in r["themes"]) for t in th.THEMES}
    pool = sorted(recent_proc, key=lambda r: r["date"] or "", reverse=True) + \
        sorted([r for r in recent_any if r not in recent_proc], key=lambda r: r["date"] or "", reverse=True)
    return {
        **h.to_dict(),
        "status": "ok" if lv else ("no_reviews" if answered else "failed"),
        "low_read": len(lv), "complete": complete,
        "complaints": len(crit),
        "complaints_recent": len(recent_any),
        "complaints_recent_procedure": len(recent_proc),
        "newest_complaint": max((r["date"] for r in crit if r["date"]), default=None),
        "replied": sum(1 for r in crit if r["replied"]),
        "new_read": len(nv),
        "new_critical": sum(1 for r in nv if r["critical"]),
        "new_span": [min(newest_dates), max(newest_dates)] if newest_dates else None,
        "themes": themes,
        "excerpts": pool[:6],
        "lowest": lv, "newest": nv,
    }


def _asks(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Questions to ask before admission, for themes that recent procedure complaints actually raised."""
    out = []
    for t, q in th.QUESTIONS.items():
        n = sum(c["themes"].get(t, 0) for c in cards)
        if n:
            out.append({"theme": t, "label": th.THEMES[t], "question": q, "count": n,
                        "hospitals": [short(c["title"]) for c in cards if c["themes"].get(t)]})
    return sorted(out, key=lambda a: -a["count"])[:5]
