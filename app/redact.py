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
_NAME_SIR = re.compile(r"\b(?!(?:Doctor|Thank|Thanks|Dear|Respected|Hello|Hi|Yes|No|Sorry|Madam|Mam|Good|Ok|"
                       r"Okay|Please|Sir)\b)([A-Z][a-z]{2,}(?:\s+[a-zA-Z]{3,})?)\s+(sir|mam|madam|ma'am)\b")
# "depression by padmini issac": a lowercase name after a care verb + by/under (checked against common words)
_BY_LOWER = re.compile(r"\b((?i:consult\w*|treat\w*|operat\w*|surger\w*|deliver\w*|check\w*|depression|examin\w*|"
                       r"attend\w*|handled|seen|diagnos\w*|done|performed)(?:\s+\w+){0,3}?\s+(?i:by|under)\s+)"
                       r"([a-z]{3,}(?:\s+[a-z]{3,})?)\b")
_NOT_NAMES = {"insurance", "general", "anaesthesia", "anesthesia", "nobody", "anyone", "everyone", "mistake",
              "local", "cashless", "emergency", "scheme", "package", "observation", "supervision", "pressure",
              "management", "someone", "somebody", "doctors", "doctor", "juniors", "junior", "duty", "interns",
              "residents", "decision", "new", "senior", "seniors", "people", "family", "relatives"}
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
fees fee charges charged himself herself themselves itself myself yourself ourselves visit visited appointment
report reports advice prescription medicine medicines treatment surgery operation also sahab saab""".split())  # noqa: SIM905
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

    t = _INITIAL_NAME.sub(_initial_name, text or "")
    t = _TITLED.sub(titled, t)
    t = _ROLE_NAMED.sub(lambda m: f"{m.group(1)} [name]", t)
    t = _LOWER_DR.sub("Dr [name]", t)
    t = _BY_PERSON.sub(lambda m: f"{m.group(1)}[name]", t)
    t = _BY_LOWER.sub(_by_lower, t)
    t = _NAME_SIR.sub(_name_sir, t)
    t = _DR_ANY.sub(_dr_any, t)
    return t


def _plain(w: str) -> bool:
    """A word that can't be part of a name here: common, a verb form, or a known non-name."""
    c = w.strip(".,'!?").lower()
    return not c or c in _COMMON or c in _NOT_NAMES or c.endswith(("ed", "ing", "n't"))


def _by_lower(m: re.Match[str]) -> str:
    words = m.group(2).split()
    name = []
    for w in words:
        if _plain(w):
            break
        name.append(w)
    if not name:
        return m.group(0)
    return m.group(1) + "[name]" + "".join(" " + w for w in words[len(name):])


def _name_sir(m: re.Match[str]) -> str:
    words = m.group(1).split()
    if len(words) == 2 and _plain(words[1]):
        return f"{words[0]} [name] {m.group(2)}" if not _plain(words[0]) else m.group(0)
    return f"[name] {m.group(2)}"


# "Dr.D hari Kishore did …": an initial followed by a lowercase name. Matched on the ORIGINAL text, before the
# titled rule turns the initial alone into "[name]".
_INITIAL_NAME = re.compile(r"\b(Dr|Doctor)\b\.?\s*[A-Z]\.?\s+((?:[A-Za-z][a-z'-]{2,}\s*){1,2})")


def _initial_name(m: re.Match[str]) -> str:
    words = m.group(2).split()
    n = 0
    for w in words:
        if _plain(w):
            break
        n += 1
    if n == 0:
        return m.group(0)
    return f"{m.group(1)} [name]" + "".join(" " + w for w in words[n:]) + (" " if m.group(0).endswith(" ") else "")



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
