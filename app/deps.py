"""Wire settings into pipeline dependencies (shared by the web app and the scripts)."""

from __future__ import annotations

from .config import Settings
from .llm import LLM
from .pipeline import Deps
from .serp import SerpClient


def build_deps(s: Settings) -> Deps:
    mode = s.effective_mode
    serp = SerpClient(s.serpapi_key, s.cache_dir, s.fixtures_dir, mode=mode, ttl_hours=s.cache_ttl_hours,
                      live_per_hour=s.live_per_hour)
    serp.live_per_day = s.live_per_day
    llm = LLM(s.llm_key, s.llm_model, s.cache_dir, s.fixtures_dir, replay=(mode == "replay"), base_url=s.llm_base_url)
    return Deps(serp=serp, llm=llm, credits_per_check=s.credits_per_check)
