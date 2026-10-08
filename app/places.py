"""Pick the hospitals people actually choose between from a Google Maps search.

The probe showed Maps results for "knee replacement hospital in Whitefield" mix big hospitals with
individual doctors' listings that carry SEO-stuffed names ("Dr … | Best Orthopaedic surgeon") and
near-perfect ratings. We compare *hospitals*, so a place must look like one and have enough reviews.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

MIN_REVIEWS = 200
HOSPITAL_TYPE = re.compile(r"hospital|medical (?:center|centre|college)|nursing home|eye care|dialysis|"
                           r"cancer (?:treatment )?cent|maternity|health ?care|institute", re.IGNORECASE)
NOT_A_HOSPITAL = re.compile(r"clinic\b|polyclinic|pharmacy|diagnostic|laborator|scan centre|physiotherap",
                            re.IGNORECASE)
# A doctor's own listing: titled "Dr …" AND carrying a doctor marker. "Dr Agarwals Eye Hospital" and
# "Dr Parthasarathy Memorial Eye Care Hospital" are hospital groups named after a founder — keep those.
DOCTOR_NAME = re.compile(r"(?:^|\W)(?:dr\.?|doctor)(?:\s|\.)|^\s*dr\b", re.IGNORECASE)  # also "DR.HARSHA.GN"
DOCTOR_MARKER = re.compile(r"\||\b(?:surgeon|specialist|consultant|physician|orthopa?edic(?:ian)?|gyna?ecologist|"
                           r"obstetrician|urologist|nephrologist|cardiologist|ophthalmologist|oncologist|"
                           r"pediatrician|paediatrician|mbbs|m\.?s\.?|m\.?d\.?|dnb|frcs)\b", re.IGNORECASE)


def is_doctor_listing(title: str) -> bool:
    return bool(DOCTOR_NAME.search(title)) and (bool(DOCTOR_MARKER.search(title))
                                                or not re.search(r"hospital|eye care|nethralaya|institute|"
                                                                 r"medical cent", title, re.IGNORECASE))


@dataclass
class Hospital:
    title: str
    data_id: str
    place_id: str | None
    rating: float | None
    reviews: int
    type: str
    address: str
    lat: float | None
    lng: float | None
    km: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("title", "data_id", "place_id", "rating", "reviews", "type",
                                              "address", "lat", "lng", "km")}


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = (map(math.radians, a)), (map(math.radians, b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)


DOCTOR_TYPE = re.compile(r"surgeon|doctor|specialist|physician|gyn(?:a)?ecologist|obstetrician|urologist|"
                         r"nephrologist|cardiologist|ophthalmologist|oncologist|pa?ediatrician|orthopedist|dentist",
                         re.IGNORECASE)


def why_not_hospital(p: dict[str, Any]) -> str | None:
    """None if the place is a hospital we compare, else the reason it's skipped."""
    title = str(p.get("title") or "")
    primary = str(p.get("type") or "")
    types = " ".join([primary] + [str(t) for t in (p.get("types") or []) if isinstance(t, str)])
    if DOCTOR_TYPE.search(primary) or is_doctor_listing(title):
        return "a doctor's own listing"
    # Google sometimes types a hospital as a clinic ("Medicover Hospitals", type "Orthopedic clinic"): a clinic
    # type is overridden by the place's own title saying it's a hospital.
    if NOT_A_HOSPITAL.search(title) or (NOT_A_HOSPITAL.search(primary)
                                        and not re.search(r"hospital", title, re.IGNORECASE)):
        return f"{primary or 'clinic'} listing"
    # Doctor types were rejected above, so a title saying "hospital" can decide ("Knee Replacement Surgeon at X
    # Hospital" typed "Orthopedic surgeon" never gets here).
    if HOSPITAL_TYPE.search(types) or HOSPITAL_TYPE.search(title):
        return None
    return f"{primary or 'not a hospital'} listing"


def is_hospital(p: dict[str, Any]) -> bool:
    return why_not_hospital(p) is None


def review_count(v: Any) -> int:
    """37221, 37221.0, "37,221" → 37221; anything else → 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r"[,\s]", "", str(v or ""))
    return int(digits) if digits.isdigit() else 0


def pick_hospitals(local_results: list[Any], centre: tuple[float, float] | None, n: int = 3,
                   min_reviews: int = MIN_REVIEWS) -> tuple[list[Hospital], list[dict[str, Any]]]:
    """The `n` most-reviewed hospitals, and every skipped place with the reason (for transparency)."""
    picked: list[Hospital] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in local_results:
        if not isinstance(p, dict) or not isinstance(p.get("data_id"), str) or not p.get("data_id"):
            continue
        title = str(p.get("title") or "")[:90]
        reviews = review_count(p.get("reviews"))
        if p["data_id"] in seen:
            continue
        seen.add(p["data_id"])
        why = why_not_hospital(p)
        if why:
            skipped.append({"title": title, "why": why})
            continue
        if reviews < min_reviews:
            skipped.append({"title": title, "why": f"only {reviews} reviews"})
            continue
        gps = p.get("gps_coordinates") if isinstance(p.get("gps_coordinates"), dict) else {}
        lat, lng = gps.get("latitude"), gps.get("longitude")
        rating = p.get("rating") if isinstance(p.get("rating"), (int, float)) else None
        h = Hospital(title, str(p["data_id"]), p.get("place_id"), rating, reviews, str(p.get("type") or ""),
                     str(p.get("address") or "")[:120], lat, lng)
        if centre and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            h.km = _km(centre, (lat, lng))
        picked.append(h)
    picked.sort(key=lambda h: -h.reviews)
    chosen: list[Hospital] = []
    for h in picked:
        if len(chosen) >= n:
            skipped.append({"title": h.title, "why": f"fewer reviews than the top {n}"})
        elif any(chain(h.title) == chain(c.title) for c in chosen):
            skipped.append({"title": h.title, "why": "another branch of the same hospital group"})
        else:
            chosen.append(h)
    return chosen, skipped


_GENERIC_FIRST = {"sri", "shri", "sree", "shree", "st", "saint", "the", "dr", "new", "govt", "government", "general",
                  "city", "district", "holy", "national", "smt", "late"}


def chain(title: str) -> str:
    """'Manipal Hospital Whitefield' and 'Manipal Hospital Varthur Road' are one group: compare groups once.
    Generic leading words don't define a group ("Sri Sai Hospital" ≠ "Sri Ramakrishna Hospital")."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    meaningful = [w for w in words if w not in _GENERIC_FIRST]
    return (meaningful or words or [title])[0]
