"""Live data probe: cached + scrubbed raw JSON to probe/raw/<name>.json."""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv
sys.path.insert(0, ".")
from app.serp import SerpClient
load_dotenv(".env")

async def main(name, engine, params):
    c = SerpClient(os.environ["SERPAPI_API_KEY"], Path("data/cache"))
    d = await c.search(engine, json.loads(params), purpose="probe")
    Path("probe/raw").mkdir(parents=True, exist_ok=True)
    Path(f"probe/raw/{name}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    await c.aclose()
    print("ok", name, [k for k in d if k not in ("search_metadata", "search_parameters")])
asyncio.run(main(*sys.argv[1:4]))
