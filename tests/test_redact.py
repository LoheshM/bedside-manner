"""app/redact.py — names of doctors and staff never reach the screen; excerpts stay short."""

from __future__ import annotations

import pytest

from app.redact import excerpt, redact

from .helpers import load_payload

# (input, name that must disappear, expected substring after redaction)
NAMED = [
    ("Dr Somshekar was rude to us", "Somshekar", "Dr [name] was rude"),
    ("My mother underwent surgery under Dr Somshekar surgical oncologist.", "Somshekar", "under Dr [name]"),
    ("Dr. D. Harikishore Reddy did the surgery", "Harikishore", "Dr [name] did"),
    ("Thanks to Dr. D. Harikishore Reddy and team", "Reddy", "Dr [name] and team"),
    ("dr shiva reddy sir was very good", "shiva", "Dr [name] sir"),
    ("dr shiva reddy sir was very good", "reddy", "Dr [name] sir"),
    ("knee replacement under dr shiva reddy and his team", "shiva", "Dr [name] and his team"),
    ("Dr.Shiva Reddy sir did wonderful job", "Shiva", "Dr [name] sir"),
    ("Sister Megha was very quick to respond", "Megha", "Sister [name] was"),
    ("Ms. Nagina from the Housekeeping team", "Nagina", "Ms [name] from"),
    ("My mother, Mrs. Lakshmi Devi, was admitted", "Lakshmi", "Mrs [name]"),
    ("Mr. Ravi Kumar at billing desk", "Ravi", "Mr [name] at billing"),
    ("Nurse Priya ignored the call bell", "Priya", "Nurse [name] ignored"),
    ("Prof. Rao explained", "Rao", "Prof [name] explained"),
    ("Doctor VG Rajan performed bilateral knee surgery", "Rajan", "Doctor [name] performed"),
    ("The physiotherapist Lokesh Arumugam is technically very sound", "Lokesh", "physiotherapist [name] is"),
    ("The physiotherapist Lokesh Arumugam is technically very sound", "Arumugam", "physiotherapist [name] is"),
    ("the surgeon Ramesh refused to see us", "Ramesh", "surgeon [name] refused"),
    ("a nurse named Kavya shouted", "Kavya", "nurse [name] shouted"),
    ("the billing executive called Suresh Babu was rude", "Suresh", "executive [name] was rude"),
    ("the coordinator Mr. Anil never called back", "Anil", "[name] never called back"),
    ("the receptionist Divya made us wait", "Divya", "receptionist [name]"),
    ("consultation by Girish they didnt explain anything", "Girish", "consultation by [name] they"),
    ("was operated under Kumar last year", "Kumar", "operated under [name]"),
    ("surgery done by Venkatesh and team", "Venkatesh", "done by [name] and team"),
    ("I was examined by Anand who said", "Anand", "examined by [name] who"),
    ("treated by Dr Kumar", "Kumar", "treated by Dr [name]"),
    ("excellent job done by Shiva Reddy. My surgery went on well.", "Shiva", "done by [name]."),
    ("Dr ayyapan and after that", "ayyapan", "Dr [name] and after"),
    ("Dr. Girish BA's examination", "Girish", "Dr [name] examination"),
]


@pytest.mark.parametrize("text,name,expected", NAMED)
def test_names_redacted(text, name, expected):
    out = redact(text)
    assert name not in out
    assert expected in out


@pytest.mark.parametrize("text", [
    "the doctor was rude",
    "The doctor was rude and the nurse was worse",
    "I met Dr. The doctor said nothing",
    "operated by the hospital team",
    "treated by them",
    "treated by their junior staff",
    "seen by a junior doctor",
    "checked by the duty doctor",
    "handled by nurses at night",
    "operated by doctors who were excellent",
    "examined by someone new",
    "treated by an intern",
    "done by management decision",
    "Doctor said nothing about the bill",
    "Dr. The best in town",
    "Dr. I would not recommend",
    "Dr. My mother was fine",
    "Dr. We waited two hours",
    "dr was not available",
    "dr is rude",
    "the dr. the nurse and the staff",
    "Billing staff were rude",
    "Nursing staff very good",
    "No reviews here, nothing to redact.",
    "",
])
def test_ordinary_text_unchanged(text):
    assert redact(text) == text


@pytest.mark.parametrize("value", [None, ""])
def test_redact_empty(value):
    assert redact(value) == ""


def test_redact_is_idempotent():
    once = redact("Dr Somshekar and Sister Megha and the physiotherapist Lokesh Arumugam")
    assert redact(once) == once
    assert once.count("[name]") == 3


def test_redact_keeps_surrounding_text():
    assert redact("We met Dr Somshekar on Monday.") == "We met Dr [name] on Monday."


def test_probe_aster_names_redacted():
    text = " ".join(r["snippet"] for r in load_payload("rev_aster2")["reviews"])
    out = redact(text)
    for name in ("Somshekar",):
        assert name in text and name not in out


@pytest.mark.parametrize("snippet_start,name", [
    ("My both knee replacement surgery done in Manipal Whitefield under Dr Shiva Reddy", "Shiva"),
    ("I would like to sincerely appreciate Ms. Nagina", "Nagina"),
    ("The physiotherapist Lokesh Arumugam", "Lokesh"),
    ("We are very thankful to Dr. Siva Reddy", "Siva"),
    ("My elderly mother underwent bilateral knee surgery with Dr. Harikishor Reddy", "Harikishor"),
])
def test_probe_manipal_excerpts_redacted(snippet_start, name):
    r = next(r for r in load_payload("rev_manipal")["reviews"] if r["snippet"].startswith(snippet_start))
    assert name in r["snippet"]
    assert name not in excerpt(r["snippet"])


# --- known leaks in the probe data ------------------------------------------------------------------

def test_initial_then_lowercase_name_redacted():
    out = redact("Dr.D hari Kishore did an excellent job")
    assert "Kishore" not in out and "hari" not in out


@pytest.mark.parametrize("text,name", [
    ("I highly recommend dr Rajan for TKR", "Rajan"),
    ("I met doctor Girisha and gave suggested for exercise", "Girisha"),
    ("Dr shoeb only talking about money", "shoeb"),
    ("the doctor bande sujeeth reddy has given wrong advice", "sujeeth"),
    ("I met Jonathan sir for physiotherapy", "Jonathan"),
])
def test_lowercase_titles_and_sir_redacted(text, name):
    assert name not in redact(text)


@pytest.mark.parametrize("name", ["padmini", "issac"])
def test_lowercase_name_after_by_redacted(name):
    assert name not in redact("treatment for depression by padmini issac was useless")


def test_name_with_sir_honorific_redacted():
    assert "Harikishore" not in redact("We consulted Harikishore reddy sir for my mother's knee replacement surgery.")


# --- excerpt --------------------------------------------------------------------------------------

def test_excerpt_two_sentences_with_ellipsis():
    assert excerpt("One. Two. Three.") == "One. Two. …"


def test_excerpt_exactly_two_sentences_no_ellipsis():
    assert excerpt("One. Two.") == "One. Two."


def test_excerpt_single_sentence():
    assert excerpt("Just one sentence without a stop") == "Just one sentence without a stop"


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_excerpt_sentence_limit(n):
    text = " ".join(f"Sentence {i}." for i in range(6))
    out = excerpt(text, max_sentences=n)
    assert out.endswith(" …")
    assert out.count("Sentence") == n


@pytest.mark.parametrize("end", ["!", "?", "."])
def test_excerpt_splits_on_all_terminators(end):
    assert excerpt(f"Bad{end} Worse{end} Worst{end}") == f"Bad{end} Worse{end} …"


def test_excerpt_char_limit_cuts_at_word_boundary():
    text = "word " * 200
    out = excerpt(text)
    assert out.endswith(" …")
    body = out[:-2]
    assert len(body) <= 300
    assert body.split() == ["word"] * len(body.split())


@pytest.mark.parametrize("max_chars", [20, 50, 100, 300])
def test_excerpt_char_limit_param(max_chars):
    out = excerpt("alpha beta gamma delta " * 40, max_chars=max_chars)
    assert len(out) <= max_chars + 2
    assert out.endswith(" …")


def test_excerpt_long_word_without_spaces():
    out = excerpt("x" * 400)
    assert out == "x" * 300 + " …"


def test_excerpt_collapses_whitespace_and_newlines():
    assert excerpt("Charitable Hospital\n\nIt looks   like\tpaid reviews.") == \
        "Charitable Hospital It looks like paid reviews."


@pytest.mark.parametrize("value", ["", "   ", "\n\n"])
def test_excerpt_empty(value):
    assert excerpt(value) == ""


def test_excerpt_redacts_before_cutting():
    out = excerpt("Dr Somshekar did my knee surgery. It went badly. I am still in pain.")
    assert out == "Dr [name] did my knee surgery. It went badly. …"


def test_excerpt_title_abbreviation_does_not_split_after_redaction():
    # "Dr." would otherwise be a sentence end; redaction removes the dot.
    out = excerpt("I met Dr. Ravi Kumar today. He was late. Then billing.")
    assert out == "I met Dr [name] today. He was late. …"


@pytest.mark.parametrize("name", ["rev_manipal", "rev_manipal_low", "rev_aster2"])
def test_probe_excerpts_short(name):
    for r in load_payload(name)["reviews"]:
        out = excerpt(r["snippet"])
        assert len(out) <= 302
        assert "\n" not in out
