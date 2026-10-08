"""Excerpts we show: short, dated, linked — and with doctors' and staff members' names removed.

Negative reviews often name an individual ("Dr X ripped off…"). Bedside Manner is about hospitals' track
records as patients describe them, not about accusing a named person, so names after a title or role
word are replaced with "[name]".
"""

from __future__ import annotations

import re

_NAME = r"(?:[A-Z][a-zA-Z'.-]*\.?)(?:\s+(?:[A-Z][a-zA-Z'.-]*\.?|[A-Z]))*"
_TITLED = re.compile(r"\b(Dr|Doctor|Doc|Prof|Sister|Nurse|Brother|Mr|Mrs|Ms|Miss|Shri|Smt)\b\.?\s*(" + _NAME + ")")
_ROLE_NAMED = re.compile(r"\b(surgeon|physiotherapist|physio|nurse|sister|staff|executive|manager|coordinator|"
                         r"receptionist|housekeeping)\s+(?:named\s+|called\s+|Mr\.?\s+|Ms\.?\s+)?([A-Z][a-z]{2,}"
                         r"(?:\s+[A-Z][a-z]{2,})?)")
_LOWER_DR = re.compile(r"\b[dD][rR]\.?\s+((?!the\b|a\b|was\b|is\b)[a-z]{3,}(?:\s+[a-z]\.?)?(?:\s+[a-z]{3,})?)\b"
                       r"(?=\s+(?:sir|madam|mam|is|was|did|has|had|and|who|performed|operated|told|asked|said))")
# "consultation by Girish", "depression by padmini issac", "operated under Kumar": a person after a care verb.
_BY_PERSON = re.compile(r"\b((?:consult\w*|treat\w*|operat\w*|surger\w*|deliver\w*|check\w*|depression|examin\w*|"
                        r"attend\w*|handled|seen|diagnos\w*|done|performed)(?:\s+\w+){0,3}?\s+(?:by|under)\s+)"
                        r"(?!the\b|them\b|their\b|a\b|an\b|hospital\b|staff\b|nurses?\b|doctors?\b|team\b|"
                        r"management\b|someone\b|junior\b|duty\b)([A-Za-z]{3,}(?:\s+(?!and\b|but\b|who\b|was\b|is\b|they\b|she\b|he\b|we\b|it\b|i\b)"
                        r"[A-Za-z]{3,})?)", re.IGNORECASE)
_CAPS_STOP = {"I", "The", "My", "We", "He", "She", "They", "It", "This", "That", "Our", "His", "Her", "Very"}


def redact(text: str) -> str:
    def titled(m: re.Match[str]) -> str:
        words = m.group(2).split()
        if words and words[0] in _CAPS_STOP:
            return m.group(0)
        return f"{m.group(1)} [name]"

    t = _TITLED.sub(titled, text or "")
    t = _ROLE_NAMED.sub(lambda m: f"{m.group(1)} [name]", t)
    t = _LOWER_DR.sub("Dr [name]", t)
    t = _BY_PERSON.sub(lambda m: f"{m.group(1)}[name]", t)
    return t


def excerpt(text: str, max_chars: int = 300, max_sentences: int = 2) -> str:
    """First sentences of a review, redacted, cut at a word boundary."""
    t = re.sub(r"\s+", " ", redact(text)).strip()
    parts = re.split(r"(?<=[.!?])\s+", t)
    out = " ".join(parts[:max_sentences])
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + " …"
    elif len(parts) > max_sentences:
        out += " …"
    return out
