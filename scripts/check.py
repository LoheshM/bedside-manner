"""Run one comparison from the command line and print a summary.

    uv run python -m scripts.check knee "Whitefield" Bengaluru [--json out.json]
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.config import load_settings
from app.deps import build_deps
from app.pipeline import run

sys.stdout.reconfigure(encoding="utf-8")


async def main(argv: list[str]) -> None:
    out = None
    if "--json" in argv:
        i = argv.index("--json")
        out = argv[i + 1]
        del argv[i:i + 2]
    proc, area, city = (argv + ["", "", ""])[:3]
    deps = build_deps(load_settings())
    events = []

    async def emit(event: str, data: dict) -> None:
        events.append({"event": event, "data": data})
        if event == "serp_call":
            print(f"  [{data['source']:>7}{' · 1 credit' if data['credit'] else ''}] {data['engine']}: "
                  f"{data['purpose']} ({data['ms']} ms, {data['result_count']} results)"
                  f"{'  ERROR ' + str(data['error']) if not data['ok'] else ''}")
        elif event in ("notice", "error"):
            print(f"  {event}: {json.dumps(data, ensure_ascii=False)[:240]}")

    res = await run(proc, area, city, deps, emit)
    for c in (res or {}).get("hospitals", []):
        ge = "" if c["complete"] else "≥"
        print(f"\n## {c['title']} — {c['rating']}★ ({c['reviews']}) · status={c['status']}")
        print(f"   lowest {c['low_read']}: complaints {ge}{c['complaints']} · last 24 mo {ge}{c['complaints_recent']}"
              f" · about the procedure/admission {ge}{c['complaints_recent_procedure']} · newest {c['newest_complaint']}"
              f" · replied {c['replied']}/{c['complaints']}")
        print(f"   newest {c['new_read']}: {c['new_critical']} are 1–2★ · span {c['new_span']}")
        print("   themes:", {k: v for k, v in c["themes"].items() if v})
        for r in c["excerpts"][:2]:
            print(f"   - {r['stars']}★ {r['date']} {r['scope']} {r['themes']} | {r['excerpt'][:140]}")
    if res:
        print("\nASK:", [(a["label"], a["count"]) for a in res["asks"]])
        print("labels:", res["label_source"], "credits:", res["credits_spent"], "ms:", res["ms"])
    if out:
        with open(out, "w", encoding="utf-8") as f:  # noqa: ASYNC230 - CLI script
            json.dump(events, f, ensure_ascii=False, indent=1)
    await deps.serp.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
