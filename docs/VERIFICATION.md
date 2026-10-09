# Verification log

How Bedside Manner was checked against reality (8–9 Oct 2026):

1. **Live probe.** A 5-credit probe of real data in `probe/raw/` led to a design change: one call per hospital wasn't enough, and the default review order is solicited praise.
2. **Skeptical judge.** An independent agent critiqued the idea against the probe JSON (docs/IDEA_ITERATIONS.md, Round 11).
3. **Real comparisons.** Four comparisons were run on live SerpApi data. Event dumps are in `results/`; rerun them from cache with `scripts/check.py`.
4. **Web check.** An independent agent fact-checked the outputs on the web and sampled the LLM labels ([VERIFICATION_web_check.md](VERIFICATION_web_check.md)).
5. **Code and security review.** A read-only review, with every finding reproduced offline.
6. **Tests.** An offline suite (752 tests) with strict xfails for each bug the tests found, plus a regression test per bug (`tests/test_regressions.py`).

## Final results (after fixes)

Counts are complaints about the procedure or the stay in the last 24 months. "≥" means Google's 20-review page was full of 1–2★ reviews, so the true count may be higher.

| Comparison | Hospitals (Google ★ · reviews) | What Bedside Manner shows | Check | Result |
|---|---|---|---|---|
| **Childbirth · Koramangala, Bengaluru** (keyword "delivery") | Motherhood Sarjapur 4.6★ · 11,171 · Cloudnine Jayanagar 4.7★ · 9,003 · Apollo Cradle Koramangala 4.7★ · 7,681 | ≥8 · ≥8 · ≥3. Mostly billing and staff behaviour. Replies: 20/21, 21/22, 19/19. "Ask before you admit" led by billing (13). | All three are real maternity hospitals. Motherhood's 4.6★ / ~10.9K is confirmed by a listing site. Excerpt dates match dates mentioned in the text. Same keyword for all. "≥" only where the 20 lowest were all 1–2★. | ✅ (two picks are 4–7 km outside Koramangala; St John's never came back in the Maps results) |
| **Cataract · Chennai** ("cataract") | Dr Agarwals 4.9★ · 11,448 · Satish 5★ · 3,112 · The Eye Foundation 4.9★ · 2,745 | 1 · 1 · 0 | The first run wrongly skipped **Dr Agarwals** (and Dr Parthasarathy) as "doctor listings". Fixed: founder-named hospitals are kept. The Eye Foundation's only 2★ review is praise and is no longer counted. | ✅ after fix |
| **Dialysis · Hyderabad** ("dialysis") | AINU 4.8★ · 7,203 · SAP Kidney Center 4.7★ · 1,922 · Sathya Kidney Centre 4.4★ · 493 | 1 · 2 · 0. AINU's newest-first search returned nothing and is shown as **unknown, not zero**. | AINU's 4.8★ is consistent with an aggregator (4.8 / 6,866). The first run picked a 234-review urology centre because Sathya's "\| Best Hospital…" title was treated as a doctor's listing. Fixed. | ✅ after fix |
| **Knee replacement · Whitefield, Bengaluru** ("knee") | Manipal Whitefield 4.7★ · 37,221 · Svastha 3.8★ · 2,435 · Medicover 5★ · 410 | 0 · 0 · 0 in 24 months. Manipal's 4 older complaints (2022) are all replied to. | Medicover Whitefield is real and runs a knee programme. It was briefly dropped because Google types it "Orthopedic clinic"; fixed. Doctors' SEO listings are correctly skipped. | ✅ (Aster and Vydehi aren't in Google's top 20 for this search) |
| **Name redaction** (all excerpts) | — | Names replaced with "[name]" | The web check found "Dr shoeb…" and "doctor bande sujeeth reddy…" still showing. Fixed. A rescan of every shown excerpt found no remaining names. | ✅ after fix |
| **LLM labels** (24 sampled) | — | scope + themes | About 12% clear errors, e.g. an outpatient prescription complaint labelled as being about the procedure. The 2★ praise mis-click is now handled with an explicit "raises a problem" label. | ⚠️ ~12% |

## Bugs found, all fixed with regression tests

| Found by | Bug | Fix |
|---|---|---|
| Skeptical judge | Comparing Manipal on "knee" with Aster on "surgery" invented a contrast | One keyword for every hospital; no fallback ladder |
| Skeptical judge | "20 of 20 are 1★" really means "at least 20" | "≥" whenever Google's page is full |
| Live run | A 2★ review saying "full satisfied, thank you" counted as a complaint | A complaint must raise a problem (LLM label, or rules with negation handling) |
| Web check | Dr Agarwals Eye Hospital and Dr Parthasarathy skipped as doctors' listings | A doctor listing needs a "Dr" title **and** a doctor marker (\|, surgeon, specialist…) or a doctor type |
| Web check | Lowercase doctor names leaked ("Dr shoeb", "doctor bande sujeeth reddy") | Lowercase names after dr/doctor are redacted up to a common word |
| Web check | Red/green count boxes read like a ranking | Neutral colours |
| Code review | Recent complaints found only in the newest-first list were missed | Complaints are counted across both lists, de-duplicated |
| Code review | "As of" used today's date on cached or recorded data | The window is measured from SerpApi's `created_at` |
| Code review | "Sri Sai Hospital" was treated as a branch of "Sri Ramakrishna" | Generic leading words are ignored when detecting branches |
| Code review | Malformed LLM output (float ids, non-list themes) crashed a check | Strict label parsing; anything bad falls back to rules |
| Code review | Review text could fake entries for other hospitals in one prompt | One JSON-encoded prompt per hospital |
| Code review | Over-redaction changed meaning ("under insurance", "by nobody") | Names must be capitalised after by/under, or pass a common-word check |
| Code review | Harsh quotes ("AVOID THIS HOSPITAL") were featured first | Calmer, specific excerpts come first; every complaint is still counted |
| Code review | No daily credit cap; failed searches used up cap slots; uncached status calls | Daily cap of 60, slots released on failure, status cached for 5 minutes |
| Test suite | A failed lowest-first search marked the card "complete" and showed "no complaint" as fact | `complete` requires reviews |
| Test suite | "Not satisfied" counted as praise without an LLM | Negation-aware rule |

## Stress test for the demo (9 Oct 2026, 14 credits)

Two more live comparisons, looking for a stronger demo case than Koramangala:

| Comparison | What came back | Used as an example? |
|---|---|---|
| Childbirth · Banjara Hills, Hyderabad | Rainbow Children's Hospital (4.7★ / 27,825; ≥4 recent delivery complaints, mostly staff), a CARE outpatient centre (4.6★) and TX Hospitals (4.8★); only 7–11 matching reviews at the latter two | No: two picks aren't maternity hospitals, and the data is thin |
| Childbirth · Andheri, Mumbai | Holy Spirit Hospital (4.2★ / 2,798), Carewel (4.7★ / 275), SM Maternity & Nursing Home (4.8★ / 200), with 1, 2 and 0 recent complaints | No: small nursing homes; no like-for-like contrast |

**Conclusion:** Koramangala stays the hero case. It is the only one with three large hospitals (7.6k–11k reviews) at near-identical stars (4.6–4.7) and clearly different recent, procedure-specific stories. The app behaved correctly on the weaker cases: small places are compared honestly, and thin data shows small counts rather than inflated ones. Event dumps: `results/delivery_hyderabad.json`, `results/delivery_andheri.json`.
