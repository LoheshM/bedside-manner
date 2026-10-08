# Bedside Manner — plan

**Track:** Travel & Local Discovery. **One line:** pick a procedure and an area; Bedside Manner compares the 3 most-reviewed hospitals near you by what patients who mentioned *that procedure* complained about — counted by code from Google Maps reviews, dated, with names removed — and turns the complaints into questions to ask before admission.

## 1. Problem (evidence: docs/IDEA_ITERATIONS.md)
- LocalCircles, 12 Aug 2026, 23,084 respondents: over 6 in 10 families had issues with private-hospital bills in the last 3 years; 68% excessive treatment prices, 56% excessive ICU/room charges, 40% unexpected or unknown charges ([source](https://www.localcircles.com/a/press/page/private-hospital-loot)).
- People choose a hospital for a planned procedure from Google stars — which blur thousands of OPD visits, and whose default review order shows a wall of 5★ reviews naming doctors (probe: Manipal Whitefield, 20/20).

## 2. What it is / isn't
- **Is:** a side-by-side reading of what patients said about one procedure at nearby hospitals; counts + dated excerpts + reply rate + "ask before you admit".
- **Isn't:** a rating, ranking, recommendation or medical advice. It never calls a hospital good or bad; it never names doctors.

## 3. User flow
Procedure (11 common planned procedures) + optional area + city → live trail (each SerpApi call: engine, purpose, live · 1 credit / cached · free) → headline ("3 hospitals … all rated 4.6–4.7★ …") → 3 cards → Ask before you admit → theme grid → more quotes → how this was checked.

## 4. Architecture
```
web/ (vanilla JS, no build) ── EventSource SSE ──► FastAPI app/main.py  (/api/compare/stream, /api/status, /api/examples)
 app/pipeline.py  run(procedure, area, city)
   ├─ google_maps  "<procedure search> in <area>, <city>"      → app/places.py: hospitals only, ≥200 reviews,
   │                                                              no doctors' listings, one branch per group, top 3
   ├─ google_maps_reviews ×2 per hospital, SAME keyword:  sort=ratingLow (20) · sort=newestFirst (20)
   ├─ app/themes.py  one batched Gemini 2.5 Flash call: per 1–2★ review → scope + themes (labels only)
   │                 keyword rules if no LLM
   ├─ app/redact.py  excerpts: ≤2 sentences, names after titles/roles/"by|under" removed
   └─ counts, reply rates, newest-20 snapshot, asks — all in code
 app/serp.py  disk cache (1 week) · replay fixtures · per-check budget (7) · hourly cap · api_key scrub
```

## 5. Metrics (per hospital, all from the two calls)
- **Recent procedure complaints:** 1–2★ reviews in the lowest-first list, posted in the last 24 months, labelled about the procedure/stay. Exact if the list reaches a ≥3★ review or ends before 20; otherwise shown as "≥N".
- **Complaints replied to:** of the 1–2★ reviews in the lowest-first list, how many carry an owner response.
- **Newest snapshot:** k of the newest ≤20 matching reviews are 1–2★, and the dates they span.
- **Unknown, not zero:** a slice that Google's filter returns empty is labelled unknown.
- Google ★ and review count: context only. No composite score, no ranking.

## 6. Credits
1 + 3 × 2 = 7 per comparison (budget enforced; hourly cap 30, daily cap 60). Project total: 36 credits (probe 5, dev/iterations ~10, four recorded comparisons incl. re-selection after fixes ~21).

## 7. Tests / verification
Offline pytest suite (no network, no keys); 4 real comparisons dumped to `results/`; independent web verification and code/security review agents; Playwright screenshots (desktop light/dark, mobile; fail on console errors / overflow).
