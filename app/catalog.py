"""Procedures people plan hospital stays for, and the review keywords that find them.

Google Maps' review filter (`google_maps_reviews` + `query`) is a keyword match. Every hospital in one
comparison is queried with the SAME keyword (the first in `keywords`) — mixing keywords across hospitals
manufactures contrast (skeptical-judge review). It sometimes returns nothing for a hospital that clearly
has such reviews (probe: Aster Whitefield, "knee"), so an empty answer is shown as "unknown", never as
"no complaints". `words` decide whether a review is about the procedure when no LLM is available.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Procedure:
    id: str
    label: str
    search: str  # what we ask Google Maps for, before "in <area>"
    keywords: tuple[str, ...]  # keywords[0] is the review filter; the rest document alternatives
    words: tuple[str, ...]  # words that mean a review is about this procedure (for "about the procedure")

    @property
    def keyword(self) -> str:
        return self.keywords[0]


PROCEDURES: dict[str, Procedure] = {p.id: p for p in [
    Procedure("knee", "Knee replacement", "knee replacement hospital", ("knee", "orthopaedic", "surgery"),
              ("knee", "tkr", "joint replacement", "orthopaed", "orthoped", "ortho ")),
    Procedure("hip", "Hip replacement", "hip replacement hospital", ("hip", "orthopaedic", "surgery"),
              ("hip", "joint replacement", "orthopaed", "orthoped")),
    Procedure("cataract", "Cataract surgery", "cataract surgery hospital", ("cataract", "eye", "surgery"),
              ("cataract", "lens", "eye surgery", "iol")),
    Procedure("delivery", "Childbirth (normal / C-section)", "maternity hospital",
              ("delivery", "maternity", "pregnancy"),
              ("delivery", "c-section", "c section", "caesarean", "cesarean", "labour", "labor", "maternity",
               "pregnan", "baby", "newborn", "nicu")),
    Procedure("heart", "Angioplasty / stent", "angioplasty hospital", ("angioplasty", "stent", "cardiac"),
              ("angioplasty", "stent", "bypass", "cabg", "cardiac", "heart", "cardio")),
    Procedure("dialysis", "Dialysis", "dialysis centre hospital", ("dialysis", "kidney", "nephrology"),
              ("dialysis", "kidney", "nephro")),
    Procedure("stone", "Kidney stone", "kidney stone hospital", ("stone", "urology", "kidney"),
              ("stone", "urolog", "kidney", "lithotripsy", "ursl", "pcnl")),
    Procedure("gallbladder", "Gallbladder / hernia surgery", "laparoscopic surgery hospital",
              ("gallbladder", "hernia", "laparoscopic"),
              ("gallbladder", "gall bladder", "hernia", "laparoscop", "appendix", "appendicitis")),
    Procedure("cancer", "Cancer treatment", "cancer hospital", ("chemotherapy", "chemo", "oncology"),
              ("chemo", "cancer", "oncolog", "radiation", "tumour", "tumor")),
    Procedure("child", "Child admission (paediatrics)", "children hospital", ("child", "paediatric", "pediatric"),
              ("child", "kid", "son", "daughter", "baby", "paediatric", "pediatric", "infant")),
    Procedure("spine", "Spine surgery", "spine surgery hospital", ("spine", "back", "surgery"),
              ("spine", "spinal", "disc", "back pain", "slip disc")),
]}

# (lat, lng) used to centre the Maps search; the area text goes into the query itself.
CITIES: dict[str, tuple[float, float]] = {
    "Bengaluru": (12.9716, 77.5946), "Mumbai": (19.0760, 72.8777), "Delhi": (28.6139, 77.2090),
    "Chennai": (13.0827, 80.2707), "Hyderabad": (17.3850, 78.4867), "Kolkata": (22.5726, 88.3639),
    "Pune": (18.5204, 73.8567), "Ahmedabad": (23.0225, 72.5714), "Jaipur": (26.9124, 75.7873),
    "Lucknow": (26.8467, 80.9462), "Kochi": (9.9312, 76.2673), "Gurugram": (28.4595, 77.0266),
}
