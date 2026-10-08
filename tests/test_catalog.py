"""app/catalog.py — procedures, their single review keyword, and city centres."""

from __future__ import annotations

import pytest

from app.catalog import CITIES, PROCEDURES, Procedure


def test_catalog_not_empty():
    assert len(PROCEDURES) >= 5 and len(CITIES) >= 5


@pytest.mark.parametrize("pid", list(PROCEDURES))
def test_procedure_has_keyword(pid):
    p = PROCEDURES[pid]
    assert isinstance(p, Procedure)
    assert p.keywords and all(isinstance(k, str) and k.strip() == k and k for k in p.keywords)
    assert p.keyword == p.keywords[0]


@pytest.mark.parametrize("pid", list(PROCEDURES))
def test_procedure_fields(pid):
    p = PROCEDURES[pid]
    assert p.id == pid
    assert p.label and p.search and p.words
    assert "hospital" in p.search or "centre" in p.search
    assert all(w == w.lower() for w in p.words)


@pytest.mark.parametrize("pid", list(PROCEDURES))
def test_keyword_is_a_single_review_filter_word(pid):
    kw = PROCEDURES[pid].keyword
    assert " " not in kw and kw == kw.lower()


@pytest.mark.parametrize("pid", list(PROCEDURES))
def test_keyword_counts_as_procedure_word(pid):
    p = PROCEDURES[pid]
    assert any(w.strip() in p.keyword or p.keyword in w for w in p.words)


def test_procedure_is_frozen():
    with pytest.raises(AttributeError):
        PROCEDURES["knee"].keywords = ("x",)  # type: ignore[misc]


def test_unique_labels_and_keywords_known():
    labels = [p.label for p in PROCEDURES.values()]
    assert len(labels) == len(set(labels))
    assert PROCEDURES["knee"].keyword == "knee"
    assert PROCEDURES["delivery"].keyword == "delivery"


@pytest.mark.parametrize("city", list(CITIES))
def test_city_has_coordinates_in_india(city):
    lat, lng = CITIES[city]
    assert isinstance(lat, float) and isinstance(lng, float)
    assert 6 < lat < 37 and 68 < lng < 98


def test_bengaluru_present():
    assert CITIES["Bengaluru"] == pytest.approx((12.9716, 77.5946))


def test_city_names_short_enough_for_api():
    assert all(len(c) <= 20 for c in CITIES)
    assert all(len(p) <= 20 for p in PROCEDURES)
