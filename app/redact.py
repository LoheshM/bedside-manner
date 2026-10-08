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
_BY_PERSON = re.compile(r"\b((?i:consult\w*|treat\w*|operat\w*|surger\w*|deliver\w*|check\w*|depression|examin\w*|"
                        r"attend\w*|handled|seen|diagnos\w*|done|performed)(?:\s+\w+){0,3}?\s+(?i:by|under)\s+)"
                        # only a Capitalised name ("under insurance", "by nobody" stay), and not "Manipal team"
                        r"([A-Z][a-z]{2,}\b(?:\s+[A-Z][a-z]{2,}\b)?)(?!\s+(?i:team|hospital|staff|icu|group|"
                        r"department|insurance))")
_NAME_SIR = re.compile(r"\b(?!(?:Doctor|Thank|Thanks|Dear|Respected|Hello|Hi|Yes|No|Sorry|Madam|Mam)\b)"
                       r"([A-Z][a-z]{2,})\s+(sir|mam|madam|ma'am)\b")
# "Dr shoeb only talking", "the doctor bande sujeeth reddy has given": lowercase names after dr/doctor. Up to
# three following words are a name until a common word, a verb form or punctuation ends it.
_DR_ANY = re.compile(r"\b(dr|doctor)\b\.?\s*((?:[a-z][a-z'.-]*\s*){1,3})", re.IGNORECASE)
_COMMON = set("""a an the and or but so to of in on at for from with without by as is was were be been being am are
has have had do did does done not no never only also just very too still always even then than this that these those
he she they we you i it his her their our my your me him them us who whom whose which what when where why how sir
madam mam ji said told says say asked gave given give gives came come comes went go goes saw see sees seen checked
check refused attended treated treat operated performed advised suggested prescribed explained ignored behaved
behaviour behavior rude good bad best worst great nice poor kind helpful busy late available not's isn't wasn't didn't
doesn't don't couldn't wouldn't won't can could would will shall should may might must here there all any some one
two three after before during while because if please team staff nurse nurses hospital patient patients consultation
fees fee charges charged""".split())  # noqa: SIM905 - readable word list
_CAPS_STOP = {"I", "The", "My", "We", "He", "She", "They", "It", "This", "That", "Our", "His", "Her", "Very"}


def redact(text: str) -> str:
    def titled(m: re.Match[str]) -> str:
        words = m.group(2).split()
        if words and words[0] in _CAPS_STOP:
            return m.group(0)
        name = []  # at most 3 words, ending at a common word: "Dr Ramesh Kumar In ICU Never Came"
        for w in words[:3]:
            if name and w.strip(".,'").lower() in _COMMON | {"icu", "opd", "ot", "er"}:
                break
            name.append(w)
        rest = " ".join(words[len(name):])
        return f"{m.group(1)} [name]" + (f" {rest}" if rest else "")

    t = _TITLED.sub(titled, text or "")
    t = _ROLE_NAMED.sub(lambda m: f"{m.group(1)} [name]", t)
    t = _LOWER_DR.sub("Dr [name]", t)
    t = _BY_PERSON.sub(lambda m: f"{m.group(1)}[name]", t)
    t = _NAME_SIR.sub(lambda m: f"[name] {m.group(2)}", t)
    t = _DR_ANY.sub(_dr_any, t)
    return t


def _dr_any(m: re.Match[str]) -> str:
    words = m.group(2).split()
    name = []
    for w in words:
        core = w.strip(".,'").lower()
        if not core or core in _COMMON or core.endswith(("ed", "ing", "n't")) or core == "[name]":
            break
        name.append(w)
    if not name:
        return m.group(0)
    tail = m.group(2).split(None, len(name))[len(name)] if len(m.group(2).split()) > len(name) else ""
    return f"{m.group(1)} [name] {tail}".rstrip() + (" " if m.group(0).endswith(" ") else "")


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
