"""app/llm.py, app/config.py, app/deps.py — keyless replay, prompt-hash cache, provider selection."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import config
from app.config import GEMINI_OPENAI_BASE, Settings, load_settings
from app.deps import build_deps
from app.llm import LLM, _strip_fence
from app.themes import LABEL_SCHEMA, LABEL_SYSTEM

from .helpers import write_llm_fixture

ENV = ("SERPAPI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_MODEL", "BEDSIDE_MODE",
       "BEDSIDE_CREDITS_PER_CHECK", "BEDSIDE_CACHE_DIR", "BEDSIDE_CACHE_TTL_HOURS", "BEDSIDE_LIVE_PER_HOUR",
       "BEDSIDE_LIVE_PER_DAY")


@pytest.fixture
def clean_env(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


# --- _strip_fence ----------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', '{"a": 1}'),
    ('```json\n{"a": 1}\n```', '{"a": 1}\n'),
    ('```\n{"a": 1}\n```', '{"a": 1}\n'),
    ('  ```json\n{"a": 1}```  ', '{"a": 1}'),
    ('```{"a": 1}```', '{"a": 1}'),
])
def test_strip_fence(text, expected):
    assert _strip_fence(text) == expected
    assert json.loads(_strip_fence(text)) == {"a": 1}


# --- cache / replay --------------------------------------------------------------------------------

def test_key_is_stable_and_depends_on_inputs(dirs):
    llm = LLM(None, "m", *dirs, replay=True)
    k = llm._key("s", "u", {"x": 1})
    assert k == llm._key("s", "u", {"x": 1}) and len(k) == 24
    assert k != llm._key("s", "u2", {"x": 1})
    assert k != llm._key("s2", "u", {"x": 1})
    assert k != LLM(None, "other-model", *dirs, replay=True)._key("s", "u", {"x": 1})


async def test_replay_without_fixture_is_unavailable(dirs):
    llm = LLM(None, "m", *dirs, replay=True)
    assert not llm.available
    assert await llm.json(LABEL_SYSTEM, "u", LABEL_SCHEMA, "review_labels") == (None, "unavailable")
    assert len(llm.used_keys) == 1


async def test_replay_reads_fixture(dirs):
    llm = LLM(None, "m", *dirs, replay=True)
    key = llm._key(LABEL_SYSTEM, "u", LABEL_SCHEMA)
    write_llm_fixture(dirs[1], key, {"labels": []})
    assert await llm.json(LABEL_SYSTEM, "u", LABEL_SCHEMA, "review_labels") == ({"labels": []}, "cache")


async def test_cache_dir_wins_over_fixture(dirs):
    llm = LLM(None, "m", *dirs, replay=True)
    key = llm._key("s", "u", {})
    write_llm_fixture(dirs[1], key, {"from": "fixture"})
    (dirs[0] / "llm" / f"{key}.json").write_text('{"from": "cache"}', encoding="utf-8")
    assert (await llm.json("s", "u", {}, "n"))[0] == {"from": "cache"}


def test_recorded_model_used_for_replay_key(dirs):
    (dirs[1] / "llm").mkdir()
    (dirs[1] / "llm" / "MODEL").write_text("gemini-2.5-flash\n", encoding="utf-8")
    replay = LLM(None, "gpt-5.4-mini", *dirs, replay=True)
    recorded = LLM(None, "gemini-2.5-flash", *dirs, replay=True)
    assert replay.key_model == "gemini-2.5-flash"
    assert replay._key("s", "u", {}) == recorded._key("s", "u", {})
    assert LLM(None, "gpt-5.4-mini", *dirs, replay=False).key_model == "gpt-5.4-mini"


def test_no_fixtures_dir(dirs):
    llm = LLM(None, "m", dirs[0], None, replay=True)
    assert llm.fixtures_dir is None and llm.key_model == "m"


def test_key_without_replay_creates_client_but_no_network(dirs):
    llm = LLM("fake-key", "gemini-2.5-flash", *dirs, replay=False, base_url=GEMINI_OPENAI_BASE)
    assert llm.available
    assert not LLM("fake-key", "m", *dirs, replay=True).available


class FakeCompletions:
    def __init__(self, content=None, exc=None):
        self.content, self.exc, self.kwargs = content, exc, []

    async def create(self, **kwargs):
        self.kwargs.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


def fake_llm(dirs, model="gemini-2.5-flash", **kw):
    llm = LLM(None, model, *dirs, replay=False)
    comp = FakeCompletions(**kw)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return llm, comp


async def test_live_call_parses_and_caches(dirs):
    llm, comp = fake_llm(dirs, content='```json\n{"labels": []}\n```')
    assert await llm.json("s", "u", LABEL_SCHEMA, "review_labels") == ({"labels": []}, "live")
    sent = comp.kwargs[0]
    assert sent["response_format"]["json_schema"] == {"name": "review_labels", "schema": LABEL_SCHEMA, "strict": True}
    assert sent["messages"] == [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert sent["reasoning_effort"] == "low"
    assert await llm.json("s", "u", LABEL_SCHEMA, "review_labels") == ({"labels": []}, "cache")
    assert len(comp.kwargs) == 1


@pytest.mark.parametrize("model,effort", [("gemini-2.5-flash", True), ("gemini-3-pro", True), ("gpt-5.4-mini", True),
                                          ("o4-mini", True), ("gpt-4o-mini", False), ("gemini-2.0-flash", False)])
async def test_reasoning_effort_only_for_reasoning_models(dirs, model, effort):
    llm, comp = fake_llm(dirs, model=model, content="{}")
    await llm.json("s", "u", {}, "n")
    assert ("reasoning_effort" in comp.kwargs[0]) is effort


@pytest.mark.parametrize("kw", [{"exc": RuntimeError("quota")}, {"content": "not json"}, {"content": "```json\n{"}])
async def test_live_failure_degrades(dirs, kw):
    llm, _ = fake_llm(dirs, **kw)
    assert await llm.json("s", "u", {}, "n") == (None, "error")
    assert not list((dirs[0] / "llm").glob("*.json"))


async def test_empty_content_is_empty_object(dirs):
    llm, _ = fake_llm(dirs, content=None)
    assert await llm.json("s", "u", {}, "n") == ({}, "live")


# --- config / deps ---------------------------------------------------------------------------------

def test_settings_no_keys(clean_env):
    s = load_settings()
    assert s.serpapi_key is None and s.llm_key is None
    assert s.llm_model == "gemini-2.5-flash" and s.llm_base_url == GEMINI_OPENAI_BASE
    assert s.mode == "auto" and s.effective_mode == "replay"
    assert s.credits_per_check == 7 and s.cache_ttl_hours == 168 and s.live_per_hour == 30
    assert s.fixtures_dir == config.ROOT / "data" / "fixtures"


def test_settings_gemini(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "g")
    s = load_settings()
    assert s.llm_key == "g" and s.llm_base_url == GEMINI_OPENAI_BASE and s.llm_model.startswith("gemini")


def test_settings_openai_only(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "o")
    s = load_settings()
    assert s.llm_key == "o" and s.llm_base_url is None and s.llm_model == "gpt-5.4-mini"


def test_settings_both_prefers_gemini(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "o")
    clean_env.setenv("GEMINI_API_KEY", "g")
    assert load_settings().llm_key == "g"


def test_settings_blank_keys_are_none(clean_env):
    for k in ("SERPAPI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        clean_env.setenv(k, "")
    s = load_settings()
    assert s.serpapi_key is None and s.llm_key is None


def test_settings_overrides(clean_env, tmp_path):
    clean_env.setenv("SERPAPI_API_KEY", "s")
    clean_env.setenv("BEDSIDE_MODE", "live")
    clean_env.setenv("LLM_MODEL", "custom")
    clean_env.setenv("BEDSIDE_CREDITS_PER_CHECK", "3")
    clean_env.setenv("BEDSIDE_CACHE_DIR", str(tmp_path / "c"))
    clean_env.setenv("BEDSIDE_CACHE_TTL_HOURS", "1.5")
    clean_env.setenv("BEDSIDE_LIVE_PER_HOUR", "0")
    s = load_settings()
    assert s.effective_mode == "live" and s.llm_model == "custom" and s.credits_per_check == 3
    assert s.cache_dir == tmp_path / "c" and s.cache_ttl_hours == 1.5 and s.live_per_hour == 0


def _settings(tmp_path, serp=None, llm=None, mode="auto"):
    return Settings(serpapi_key=serp, llm_key=llm, llm_model="gemini-2.5-flash", llm_base_url=GEMINI_OPENAI_BASE,
                    mode=mode, credits_per_check=7, cache_dir=tmp_path / "cache", fixtures_dir=tmp_path / "fx",
                    cache_ttl_hours=168, live_per_hour=30)


async def test_build_deps_replay_without_keys(tmp_path):
    d = build_deps(_settings(tmp_path, llm="g"))
    assert d.serp.mode == "replay" and d.llm.replay is True and not d.llm.available
    assert d.credits_per_check == 7 and d.serp.live_per_hour == 30
    await d.serp.aclose()


async def test_build_deps_auto_with_keys(tmp_path):
    d = build_deps(_settings(tmp_path, serp="s", llm="g"))
    assert d.serp.mode == "auto" and d.llm.replay is False and d.llm.available
    await d.serp.aclose()


def test_settings_daily_cap(clean_env):
    assert load_settings().live_per_day == 60
    clean_env.setenv("BEDSIDE_LIVE_PER_DAY", "5")
    assert load_settings().live_per_day == 5


async def test_build_deps_sets_daily_cap(tmp_path):
    s = _settings(tmp_path, serp="s")
    d = build_deps(s)
    assert d.serp.live_per_day == s.live_per_day
    await d.serp.aclose()
