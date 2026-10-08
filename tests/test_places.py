"""app/places.py — which Maps pins are hospitals people choose between."""

from __future__ import annotations

import pytest

from app.places import MIN_REVIEWS, Hospital, _km, chain, is_hospital, pick_hospitals

from .helpers import ASTER, MANIPAL_VARTHUR, MANIPAL_WF, SATHYA, load_payload, place

MAPS = load_payload("maps")["local_results"]
BY_TITLE = {p["title"]: p for p in MAPS}


# --- is_hospital: real probe pins ---------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Manipal Hospital Whitefield",
    "Aster Hospital Whitefield Bangalore",
    "Svastha Hospital",
    "Manipal Hospital Varthur Road",
    "Sathya Sai Orthopaedic & Multispeciality Hospital",
    "MTB Orthopaedic Hospital",
])
def test_probe_hospitals_are_hospitals(title):
    assert is_hospital(BY_TITLE[title])


@pytest.mark.parametrize("title", [
    "DR.HARSHA.GN",
    "Dr. Karan Kukreja | Best Orthopaedic surgeon in Whitefield | Manipal Hospital Whitefield",
    "Dr Kumardev Arvind Rajamanya",
    "Dr. Sarath Chandra Poodi | Best Orthopedic Surgeon in Varthur Whitefield",
    "Dr. Bharat P Sarkar | Best Spine, Back & Neck Pain Surgeon in Whitefield | Manipal Hospitals Whitefield",
    "Dr Ramachandran - Spine, Spinal Neuro, and Scoliosis surgeon",
    "Dr. D. Harikishore Reddy | Best Orthopedic surgeon in Whitefield | Manipal Hospital Whitefield",
    "PVR POLYCLINIC ( ortho & maternity )",
])
def test_probe_doctor_listings_and_clinics_are_not_hospitals(title):
    assert not is_hospital(BY_TITLE[title])


def test_probe_dr_titles_with_unicode_dash_are_not_hospitals():
    for p in MAPS:
        if p["title"].startswith(("Dr Kiran", "Dr. Ajay")):
            assert not is_hospital(p), p["title"]


# --- is_hospital: synthetic -------------------------------------------------------------------------

@pytest.mark.parametrize("title,type_", [
    ("City Hospital", "Hospital"),
    ("Sunrise Care", "Private hospital"),
    ("Sunrise Care", "General hospital"),
    ("St. Martha's", "Specialized hospital"),
    ("Kidwai", "Cancer treatment center"),
    ("Narayana Nethralaya", "Eye care center"),
    ("Cloudnine", "Maternity hospital"),
    ("NephroPlus", "Dialysis center"),
    ("KIMS", "Medical Center"),
    ("Ramaiah", "Medical college"),
    ("Sri Sai Nursing Home", "Nursing home"),
    ("Apollo Health City", "Health care"),
    ("Institute of Nephrourology", ""),
    ("Dr Agarwals Eye Hospital", "Eye care center"),
    ("Dr Parthasarathy Memorial Eye Care Hospital", "Eye care center"),
])
def test_hospital_types_and_titles_accepted(title, type_):
    assert is_hospital({"title": title, "type": type_})


@pytest.mark.parametrize("title,type_", [
    ("Dr. Ravi | Best Orthopaedic Surgeon", "Hospital"),
    ("Dr Ravi Kumar", "Hospital"),
    ("dr ravi kumar", "Hospital"),
    ("Dr. Ravi Kumar MS Ortho | Sunrise Hospital", "Hospital"),
    ("Dr Kiran, Orthopaedic Surgeon at City Hospital", "Hospital"),
    ("Knee Replacement Surgeon at Sunrise Hospital", "Orthopedic surgeon"),
    ("Sunrise Hospital", "Orthopedic surgeon"),
    ("Sunrise Hospital", "Obstetrician-gynecologist"),
    ("Rainbow Children's Hospital", "Pediatrician"),
    ("Smile Dental Clinic", "Hospital"),
    ("Sunrise Polyclinic", "Hospital"),
    ("Apollo Pharmacy", "Hospital"),
    ("Vijaya Diagnostic Centre", "Hospital"),
    ("Thyrocare Laboratory", "Hospital"),
    ("Aarthi Scan Centre", "Hospital"),
    ("Healing Hands Physiotherapy", "Hospital"),
    ("Ravi Bone Care", "Orthopedic surgeon"),
    ("Sunrise", "Doctor"),
    ("", ""),
])
def test_non_hospitals_rejected(title, type_):
    assert not is_hospital({"title": title, "type": type_})


def test_types_list_counts_and_ignores_non_strings():
    assert is_hospital({"title": "Sunrise", "type": "", "types": ["Medical group", "Private hospital"]})
    assert not is_hospital({"title": "Sunrise", "type": "Health consultant", "types": [None, 3, {"x": "hospital"}]})


def test_title_alone_can_make_a_hospital():
    assert is_hospital({"title": "Sunrise Hospital"})


@pytest.mark.parametrize("p", [{}, {"title": None, "type": None, "types": None}, {"types": "hospital"}])
def test_is_hospital_tolerates_missing_fields(p):
    assert is_hospital(p) in (True, False)


@pytest.mark.parametrize("title", [
    ("Dr.Krishna Kumar MS |Robotic Joint Replacement |Arthroscopy Sports Medicine |Orthopedic surgeon|"
     "Medicover Hospital Whitefield"),
    "DR.HARSHA.GN",
])
def test_titles_starting_dr_without_space_are_not_hospitals(title):
    assert not is_hospital({"title": title, "type": "Hospital"})


# --- pick_hospitals on the probe -------------------------------------------------------------------

def test_probe_picks_top3_hospitals():
    chosen, _ = pick_hospitals(MAPS, None)
    assert [h.data_id for h in chosen] == [MANIPAL_WF, ASTER, SATHYA]
    assert [h.reviews for h in chosen] == [37221, 11001, 5800]
    assert all(isinstance(h, Hospital) for h in chosen)


def test_probe_skips_second_manipal_branch():
    chosen, skipped = pick_hospitals(MAPS, None)
    assert MANIPAL_VARTHUR not in {h.data_id for h in chosen}
    assert {"title": "Manipal Hospital Varthur Road", "why": "another branch of the same hospital group"} in skipped


def test_probe_skip_reasons():
    _, skipped = pick_hospitals(MAPS, None)
    why = {s["title"]: s["why"] for s in skipped}
    assert why["MTB Orthopaedic Hospital"] == "only 188 reviews"
    assert why["Svastha Hospital"] == "fewer reviews than the top 3"
    assert why["PVR POLYCLINIC ( ortho & maternity )"].endswith("listing")
    for title, reason in why.items():
        if title.lower().startswith("dr"):
            assert "listing" in reason, title
    assert all(isinstance(s["why"], str) and s["why"] for s in skipped)


def test_probe_every_place_accounted_for():
    chosen, skipped = pick_hospitals(MAPS, None)
    assert len(chosen) + len(skipped) == len(MAPS) == 20


def test_probe_no_doctor_listing_chosen():
    chosen, _ = pick_hospitals(MAPS, None)
    assert not any(h.title.lower().startswith("dr") or "| best" in h.title.lower() for h in chosen)


def test_probe_fields_and_distance():
    chosen, _ = pick_hospitals(MAPS, (12.9698, 77.75))
    m = chosen[0]
    assert m.title == "Manipal Hospital Whitefield"
    assert m.rating == 4.7 and m.type == "Private hospital"
    assert m.place_id and m.address.startswith("ITPL Main Rd")
    assert m.lat == pytest.approx(12.988, abs=1e-3) and m.lng == pytest.approx(77.7288, abs=1e-3)
    assert m.km == pytest.approx(3.1, abs=0.1)
    d = m.to_dict()
    assert set(d) == {"title", "data_id", "place_id", "rating", "reviews", "type", "address", "lat", "lng", "km"}


def test_no_centre_leaves_km_none():
    chosen, _ = pick_hospitals(MAPS, None)
    assert all(h.km is None for h in chosen)


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_n_limits_choice(n):
    chosen, _ = pick_hospitals(MAPS, None, n=n)
    available = len(pick_hospitals(MAPS, None, n=99)[0])
    assert available >= 3
    assert len(chosen) == min(n, available)
    assert sorted((h.reviews for h in chosen), reverse=True) == [h.reviews for h in chosen]


@pytest.mark.parametrize("min_reviews,expected", [(200, 3), (6000, 2), (12000, 1), (40000, 0)])
def test_min_reviews_threshold(min_reviews, expected):
    chosen, _ = pick_hospitals(MAPS, None, min_reviews=min_reviews)
    assert len(chosen) == expected


# --- pick_hospitals: synthetic edge cases -------------------------------------------------------------

def test_min_reviews_constant():
    assert MIN_REVIEWS == 200


@pytest.mark.parametrize("reviews,ok", [(199, False), (200, True), (201, True), ("200", True), ("5000", True),
                                        ("37,221", True), (None, False), ("abc", False), (-5, False),
                                        (250.0, True), ([], False), (True, False), ("", False)])
def test_review_count_parsing(reviews, ok):
    chosen, skipped = pick_hospitals([place("Alpha Hospital", "a", reviews)], None)
    assert (len(chosen) == 1) is ok
    if not ok:
        assert skipped[0]["why"].startswith("only ")


def test_string_review_count_is_converted():
    chosen, _ = pick_hospitals([place("Alpha Hospital", "a", "5000")], None)
    assert chosen[0].reviews == 5000


@pytest.mark.parametrize("bad", [None, "Alpha Hospital", 42, ["x"], ("a",), 3.5])
def test_non_dict_entries_ignored(bad):
    chosen, skipped = pick_hospitals([bad, place("Alpha Hospital", "a")], None)
    assert [h.data_id for h in chosen] == ["a"] and skipped == []


@pytest.mark.parametrize("data_id", [None, "", 0])
def test_missing_data_id_ignored(data_id):
    p = place("Alpha Hospital", "a")
    p["data_id"] = data_id
    assert pick_hospitals([p], None) == ([], [])


def test_data_id_absent_ignored():
    p = place("Alpha Hospital", "a")
    del p["data_id"]
    assert pick_hospitals([p], None) == ([], [])


def test_duplicate_data_id_counted_once():
    chosen, skipped = pick_hospitals([place("Alpha Hospital", "a", 900), place("Alpha Hospital", "a", 900),
                                      place("Beta Hospital", "b", 800)], None)
    assert [h.data_id for h in chosen] == ["a", "b"] and skipped == []


def test_top_by_review_count_not_position():
    ps = [place(f"{name} Hospital", name, n) for name, n in
          [("Alpha", 300), ("Beta", 9000), ("Gamma", 450), ("Delta", 12000), ("Epsilon", 700)]]
    chosen, skipped = pick_hospitals(ps, None)
    assert [h.data_id for h in chosen] == ["Delta", "Beta", "Epsilon"]
    assert {s["title"] for s in skipped} == {"Gamma Hospital", "Alpha Hospital"}


@pytest.mark.parametrize("a,b", [
    ("Manipal Hospital Whitefield", "Manipal Hospital Varthur Road"),
    ("Manipal Hospital Whitefield", "Manipal Hospitals - Old Airport Road"),
    ("Aster Hospital Whitefield Bangalore", "Aster CMI Hospital"),
    ("Apollo Hospitals, Bannerghatta", "Apollo Hospital Jayanagar"),
    ("Fortis Hospital", "FORTIS HOSPITAL CUNNINGHAM ROAD"),
])
def test_chain_same_group(a, b):
    assert chain(a) == chain(b)


@pytest.mark.parametrize("a,b", [
    ("Manipal Hospital Whitefield", "Aster Hospital Whitefield"),
    ("Sakra World Hospital", "Narayana Health City"),
    ("Cloudnine Hospital", "Motherhood Hospital"),
])
def test_chain_different_groups(a, b):
    assert chain(a) != chain(b)


@pytest.mark.parametrize("title,expected", [("Manipal Hospital", "manipal"), ("  ", "  "), ("", ""),
                                            ("#1 Care", "1"), ("St. John's Hospital", "john"),
                                            ("Sri Sathya Sai Hospital", "sathya")])
def test_chain_key(title, expected):
    assert chain(title) == expected


@pytest.mark.parametrize("a,b", [
    ("St. John's Medical College Hospital", "St. Martha's Hospital"),
    ("Sri Sathya Sai Hospital", "Sri Ramakrishna Hospital"),
    ("The Bangalore Hospital", "The Oxford Hospital"),
])
def test_chain_does_not_merge_generic_prefixes(a, b):
    chosen, _ = pick_hospitals([place(a, "a", 9000), place(b, "b", 8000)], None)
    assert len(chosen) == 2


def test_chain_dedupe_keeps_most_reviewed_branch():
    ps = [place("Manipal Hospital Varthur Road", "v", 25652), place("Manipal Hospital Whitefield", "w", 37221),
          place("Aster Hospital", "a", 11001)]
    chosen, skipped = pick_hospitals(ps, None)
    assert [h.data_id for h in chosen] == ["w", "a"]
    assert skipped == [{"title": "Manipal Hospital Varthur Road", "why": "another branch of the same hospital group"}]


def test_branch_fills_slot_with_next_hospital():
    ps = [place("Manipal A Hospital", "m1", 9000), place("Manipal B Hospital", "m2", 8000),
          place("Aster Hospital", "a", 7000), place("Sakra Hospital", "s", 6000), place("Fortis Hospital", "f", 500)]
    chosen, skipped = pick_hospitals(ps, None)
    assert [h.data_id for h in chosen] == ["m1", "a", "s"]
    assert {s["why"] for s in skipped} == {"another branch of the same hospital group", "fewer reviews than the top 3"}


def test_non_numeric_rating_becomes_none():
    chosen, _ = pick_hospitals([place("Alpha Hospital", "a", rating="4.5")], None)
    assert chosen[0].rating is None


@pytest.mark.parametrize("gps", [None, "12,77", [12, 77], {"latitude": "12.9", "longitude": 77.7}, {}])
def test_bad_gps_does_not_crash(gps):
    p = place("Alpha Hospital", "a")
    p["gps_coordinates"] = gps
    chosen, _ = pick_hospitals([p], (12.97, 77.59))
    assert chosen[0].km is None


def test_long_title_and_address_truncated():
    p = place("Alpha Hospital " + "x" * 200, "a")
    p["address"] = "y" * 500
    chosen, _ = pick_hospitals([p], None)
    assert len(chosen[0].title) == 90 and len(chosen[0].address) == 120


def test_skipped_doctor_listing_reason():
    _, skipped = pick_hospitals([place("Dr Ravi | Best Ortho", "d", 900, type_="Orthopedic surgeon")], None)
    assert skipped[0]["title"] == "Dr Ravi | Best Ortho" and "doctor" in skipped[0]["why"]


@pytest.mark.parametrize("p", [{"title": "Smile Dental Clinic", "data_id": "x", "reviews": 900},
                               {"title": "Sunrise", "data_id": "x", "reviews": 900, "type": "Gym"}])
def test_skipped_listing_reason_names_a_listing(p):
    _, skipped = pick_hospitals([p], None)
    assert len(skipped) == 1 and skipped[0]["why"].endswith("listing")


@pytest.mark.parametrize("data_id", [["x"], {"x": 1}, 12345])
def test_non_string_data_id_does_not_crash(data_id):
    p = place("Alpha Hospital", "a")
    p["data_id"] = data_id
    chosen, _ = pick_hospitals([p, place("Beta Hospital", "b")], None)
    assert "b" in [h.data_id for h in chosen]


def test_empty_input():
    assert pick_hospitals([], None) == ([], [])


@pytest.mark.parametrize("a,b,km", [((12.9716, 77.5946), (12.9716, 77.5946), 0.0),
                                    ((12.9716, 77.5946), (13.0827, 80.2707), 290.2),
                                    ((19.0760, 72.8777), (18.5204, 73.8567), 119.9)])
def test_haversine(a, b, km):
    assert _km(a, b) == pytest.approx(km, abs=1.5)
