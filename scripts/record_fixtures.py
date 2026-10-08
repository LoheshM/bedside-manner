"""Record the example comparisons into data/fixtures/ so the app runs with no keys (replay mode).

    uv run python -m scripts.record_fixtures

Uses the warm disk cache (free). Refuses to write any fixture that contains an api_key.
"""

from __future__ import annotations

import asyncio
import shutil
import sys

from app.config import load_settings
from app.deps import build_deps
from app.main import EXAMPLES
from app.pipeline import run

sys.stdout.reconfigure(encoding="utf-8")


def _copy(src, dst) -> bool:
    if not src.exists():
        return False
    assert "api_key" not in src.read_text(encoding="utf-8"), f"refusing to write {src.name}: contains api_key"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


async def main() -> None:
    s = load_settings()
    deps = build_deps(s)
    fx = s.fixtures_dir

    async def emit(event: str, data: dict) -> None:
        if event == "serp_call" and data["source"] == "live":
            print(f"   LIVE (1 credit) {data['engine']}: {data['purpose']}")
        elif event == "result":
            print("   " + " | ".join(f"{h['title'][:28]}: {h['complaints_recent_procedure']} recent proc."
                                    for h in data["hospitals"]))

    for e in EXAMPLES:
        print(f"> {e['procedure']} {e['area']} {e['city']}")
        await run(e["procedure"], e["area"], e["city"], deps, emit)
    n = sum(_copy(s.cache_dir / f"{k}.json", fx / f"{k}.json") for k in deps.serp.used_keys)
    n += sum(_copy(s.cache_dir / "llm" / f"{k}.json", fx / "llm" / f"{k}.json") for k in deps.llm.used_keys)
    (fx / "llm").mkdir(parents=True, exist_ok=True)
    (fx / "llm" / "MODEL").write_text(deps.llm.model, encoding="utf-8")
    print(f"wrote {n} fixture files to {fx}")
    await deps.serp.aclose()


if __name__ == "__main__":
    asyncio.run(main())
