"""One test per bug found by real-data verification and review (see docs/VERIFICATION.md)."""

from __future__ import annotations

import pytest

from app.places import is_hospital, pick_hospitals
from app.redact import excerpt, redact
from app.themes import merge_labels, rule_themes, sounds_positive


@pytest.mark.parametrize("title,type_", [
    ("Dr Agarwals Eye Hospital", "Eye care center"),  # web check: hospital groups named after a founder were skipped
    ("Dr Parthasarathy Memorial Eye Care Hospital", "Eye care center"),
    ("Medicover Hospitals", "Orthopedic clinic"),  # Google types this hospital a clinic; its title says hospital
])
def test_real_hospitals_are_kept(title, type_):
    assert is_hospital({"title": title, "type": type_})


@pytest.mark.parametrize("title,type_", [
    ("Dr. Sarath Chandra Poodi | Best Orthopedic Surgeon in Varthur Whitefield", "Hospital"),
    ("Knee Replacement Surgeon at Apollo Hospital", "Orthopedic surgeon"),  # code review: doctor typed listing
    ("DR.HARSHA.GN", "Hospital"),
])
def test_doctor_listings_are_skipped(title, type_):
    assert not is_hospital({"title": title, "type": type_})


def test_one_branch_per_group_but_sri_prefixes_are_not_a_group():
    places = [{"title": t, "type": "Hospital", "data_id": f"id{i}", "reviews": r} for i, (t, r) in enumerate([
        ("Manipal Hospital Whitefield", 900), ("Manipal Hospital Varthur Road", 800),
        ("Sri Sai Hospital", 700), ("Sri Ramakrishna Hospital", 600)])]
    chosen, skipped = pick_hospitals(places, None, 3)
    assert [h.title for h in chosen] == ["Manipal Hospital Whitefield", "Sri Sai Hospital", "Sri Ramakrishna Hospital"]
    assert any(s["why"] == "another branch of the same hospital group" for s in skipped)


@pytest.mark.parametrize("text,leaked", [
    ("Dr shoeb only talking not give proper treatment", "shoeb"),  # web check: names left on cards
    ("The doctor bande sujeeth reddy has given wrong medicine", "sujeeth"),
    ("Dr.D hari Kishore did an excellent job", "Kishore"),
    ("treatment for depression by padmini issac", "padmini"),
    ("We consulted Harikishore reddy sir", "Harikishore"),
])
def test_names_never_reach_an_excerpt(text, leaked):
    assert leaked not in excerpt(text)


@pytest.mark.parametrize("text", [
    "Treatment under insurance was approved late", "Attended by nobody for hours", "Not seen by any doctor",
    "operated under general anaesthesia", "Surgery done by Manipal team", "surprisingly the doctor himself.",
])
def test_redaction_does_not_change_meaning(text):
    assert redact(text) == text


def test_a_low_star_review_that_praises_is_not_a_complaint():
    praise = "My father had cataract surgery with Dr [name] mam really very very good experience full satisfied"
    assert rule_themes(praise) == [] and sounds_positive(praise)
    assert not sounds_positive("Not satisfied with the treatment.")


def test_llm_labels_cannot_crash_or_cross_ids():
    junk = {"labels": [{"id": 1.0}, {"id": True}, {"id": [0]}, {"id": 0, "themes": 5, "raises_problem": "x"}]}
    out = merge_labels(junk, {0, 1})
    assert set(out) == {0} and out[0]["problem"] is True and out[0]["themes"] == []
    assert merge_labels([1, 2], {0}) == {} and merge_labels(None, {0}) == {}
