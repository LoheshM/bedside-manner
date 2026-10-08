"""FastAPI app: an SSE endpoint for the pipeline plus the static UI."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from . import pipeline
from .catalog import CITIES, PROCEDURES
from .config import ROOT, Settings, load_settings
from .deps import build_deps

log = logging.getLogger("bedside")
WEB = ROOT / "web"

EXAMPLES: list[dict[str, str]] = [
    {"label": "Childbirth · Koramangala, Bengaluru", "procedure": "delivery", "area": "Koramangala",
     "city": "Bengaluru", "hint": "Three 4.6–4.7★ maternity hospitals"},
    {"label": "Cataract surgery · Chennai", "procedure": "cataract", "area": "", "city": "Chennai",
     "hint": "Three 4.9–5★ eye hospitals"},
    {"label": "Dialysis · Hyderabad", "procedure": "dialysis", "area": "", "city": "Hyderabad",
     "hint": "Who replies to complaints, and an unknown"},
    {"label": "Knee replacement · Whitefield, Bengaluru", "procedure": "knee", "area": "Whitefield",
     "city": "Bengaluru", "hint": "When recent complaints are rare"},
]


def create_app(settings: Settings | None = None, deps: pipeline.Deps | None = None) -> FastAPI:
    s = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.deps = deps or build_deps(s)
        yield
        await app.state.deps.serp.aclose()

    app = FastAPI(title="Bedside Manner", lifespan=lifespan)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Credit-spending endpoints must not be triggerable by other websites (<img src=…>, fetch, iframes).
        if request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "cross-site requests are not allowed"}, status_code=403)
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    def stream(runner) -> EventSourceResponse:
        queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def work() -> None:
            try:
                await runner(emit)
            except Exception:
                log.exception("pipeline failed")
                # "failure", not "error": EventSource's own `error` event would swallow it in the browser
                await queue.put(("failure", {"text": "Something went wrong while comparing hospitals."}))
            finally:
                await queue.put(None)

        async def gen():
            task = asyncio.create_task(work())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    event, data = item
                    yield {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}
            finally:
                if not task.done():
                    task.cancel()

        return EventSourceResponse(gen(), ping=15)

    @app.get("/api/compare/stream")
    async def compare(procedure: str = Query(..., max_length=20), area: str = Query("", max_length=50),
                      city: str = Query("Bengaluru", max_length=20)):
        if procedure not in PROCEDURES:
            return JSONResponse({"error": "unknown procedure"}, status_code=400)
        if city not in CITIES:
            return JSONResponse({"error": "unknown city"}, status_code=400)
        if any(c in area for c in "<>{}[]\\") or sum(ch.isdigit() for ch in area) > 6:
            return JSONResponse({"error": "area must be a locality name"}, status_code=400)
        d = app.state.deps
        return stream(lambda emit: pipeline.run(procedure, area, city, d, emit))

    acct_cache: dict[str, Any] = {"at": 0.0, "value": None}

    @app.get("/api/status")
    async def status():
        d: pipeline.Deps = app.state.deps
        acct = None
        if d.serp.mode != "replay":  # the (free) account call is cached for 5 minutes
            if time.time() - acct_cache["at"] > 300:
                acct_cache.update(at=time.time(), value=await d.serp.account())
            acct = {"searches_left": (acct_cache["value"] or {}).get("searches_left")}
        return {"mode": d.serp.mode, "llm": d.llm.model if d.llm.available else None,
                "credits_per_check": d.credits_per_check, "account": acct, "cities": list(CITIES),
                "procedures": [{"id": p.id, "label": p.label} for p in PROCEDURES.values()]}

    @app.get("/api/examples")
    async def examples():
        return EXAMPLES

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()
