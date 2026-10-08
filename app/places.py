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
NOT_A_HOSPITAL = re.compile(r"(?:^|\W)(?:dr\.?|doctor)\s|\|\s*best\b|clinic\b|polyclinic|pharmacy|diagnostic|"
                            r"laborator|scan centre|physiotherap", re.IGNORECASE)


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


def is_hospital(p: dict[str, Any]) -> bool:
    title = str(p.get("title") or "")
    types = " ".join([str(p.get("type") or "")] + [str(t) for t in (p.get("types") or []) if isinstance(t, str)])
    return bool(HOSPITAL_TYPE.search(types) or HOSPITAL_TYPE.search(title)) and not NOT_A_HOSPITAL.search(title)


def pick_hospitals(local_results: list[Any], centre: tuple[float, float] | None, n: int = 3,
                   min_reviews: int = MIN_REVIEWS) -> tuple[list[Hospital], list[dict[str, Any]]]:
    """The `n` most-reviewed hospitals, and every skipped place with the reason (for transparency)."""
    picked: list[Hospital] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in local_results:
        if not isinstance(p, dict) or not p.get("data_id"):
            continue
        title = str(p.get("title") or "")[:90]
        reviews = int(p.get("reviews") or 0) if str(p.get("reviews") or "0").isdigit() else 0
        if p["data_id"] in seen:
            continue
        seen.add(p["data_id"])
        if not is_hospital(p):
            skipped.append({"title": title, "why": f"{p.get('type') or 'not a hospital'} listing"})
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


def chain(title: str) -> str:
    """'Manipal Hospital Whitefield' and 'Manipal Hospital Varthur Road' are one group: compare groups once."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    return words[0] if words else title
