# Idea iterations

Each round: **Idea → Strongest objection → Answer / change.** Evidence: two research agents (pain points; SerpApi docs + BuiltWithSerpApi gallery) and a 5-credit live probe in `probe/raw/` (scrubbed).

## Round 1 — pick the problem (Travel & Local Discovery track)
**Idea.** Shortlist (ranked frequency × intensity × solvable-with-search × timeliness): festival crowd timing; **which hospital to pick for a procedure**; solo-women hotel safety; broken EV highway chargers; route disruption; Jain/veg food.
**Objection.** Crowd timing relies on `popular_times`, a *typical week*, not a festival day — its core claim can't be verified. Hotel-safety categories may not exist for Indian hotels. EV chargers is niche.
**Answer.** Hospitals. LocalCircles (12 Aug 2026, 23,084 responses): *"Over 6 in 10 families"* faced billing problems at private hospitals; 68% found prices excessive, 40% hit "unexpected or unknown charges". On Practo, a Trustpilot reviewer: *"The reviews are paid and bought, honest reviews with bills and pictures are not uploaded."* Choosing a hospital for a planned procedure (knee replacement, cataract, delivery) is a high-stakes **local discovery** decision people make from Google Maps stars. Different from our other entries (commerce price check; helpline-scam check): this is about *experiences*, not fraud.

## Round 2 — is it already done?
**Objection.** Practo, Google ratings, hospital websites.
**Answer.** Gallery check (~190 projects): no hospital/doctor discovery (Hippocrate explains records, BillShield reviews bills). Practo shows doctor reviews it moderates; Google shows one star average dominated by OPD visits. Nobody shows *what patients who had **your** procedure complained about*, per hospital, side by side.

## Round 3 — can the data support it? (live probe, 5 credits)
- `google_maps` "knee replacement hospital in Whitefield Bengaluru" → 20 pins: big hospitals (Manipal Whitefield 4.7★ / 37,221 reviews; Aster Whitefield 4.7★ / 11,001) mixed with individual doctors' listings with SEO-stuffed names ("Dr … | Best Orthopaedic surgeon", 4.9–5★ on 40–370 reviews).
- `google_maps_reviews` Manipal, `query=knee` (default sort) → **20/20 are 5★ and name a doctor** ("excellent job done by Dr …") — the signature of solicited post-discharge reviews.
- Same with `sort_by=ratingLow` → only **5 of 20** are 1★, all from 2021–22 and about OPD waiting; then 4–5★ knee-replacement praise.
- Aster, `query=knee` → *"No reviews"* (filter is flaky); `query=surgery`, `ratingLow` → **20/20 are 1★**, 9 since 2025: *"Fraudulent activities by insurance team…"*, *"room charges are taken for 6 days where the room is also not allotted"*, *"Horrible Hospital for In-patients, For OPD it is fine"*.
**Answer.** The star average hides everything; the default review order hides it again (solicited praise). **One call per hospital — `query=<procedure>` + `sort_by=ratingLow` — returns the 20 worst things patients said about that procedure.** How fast that list turns from 1★ into 4–5★ is itself the signal ("only 5 complaints, newest 2022" vs "20 of 20 are 1★, 9 this year").

## Round 4 — what breaks the obvious version?
**Objections & answers.**
- *Keyword filter flakiness* (Aster "knee" → none): each procedure has a keyword ladder (knee replacement → `knee` → `orthopaedic` → `surgery`); stop at the first non-empty answer; label which keyword was used. ≤ 1 fallback per hospital (credit cap).
- *Doctor listings and clinics* in the Maps results: keep only places whose type is a hospital (Hospital / Private hospital / Multispecialty / Medical Center) with ≥ 200 reviews; pick the top 3 by review count — the places people actually choose between.
- *Old complaints*: every count is split into "last 24 months" vs older; dates shown on every quote.
- *Reviews not about the procedure* (the filter matches "knee" in an OPD complaint): the LLM marks whether each review describes the procedure/admission or only an OPD visit; both are shown, separately counted.

## Round 5 — harm, legal & tone
**Objection.** Publishing hospital complaints can be defamatory; it can scare people away from good care; it's medical-adjacent.
**Answer.** We never rate a hospital or say "bad/avoid/fraud". We show counts and **verbatim, dated, attributed** Google reviews ("a Google review, Jun 2026"), the overall Google rating next to them, and an explicit note: *"Reviews are individual experiences, not medical evidence. Talk to your doctor; ask the hospital for a written cost estimate and your insurer for cashless approval before admission."* The LLM only labels themes; it writes no judgement. Banned words in any generated text: fraud, scam, cheat, worst, avoid, negligent.

## Round 6 — is SerpApi core? Agent or pipeline?
**Answer.** Without SerpApi there is nothing: `google_maps` finds the hospitals near the user, `google_maps_reviews` (keyword filter + lowest-first sort) gives the procedure-specific critical reviews. It's an honest pipeline with one batched LLM labelling step — Travel & Local Discovery track, not AI Agents.

## Round 7 — can a judge trust the numbers?
**Answer.** Code computes every number (how many of the 20 lowest are 1–2★, how many in 24 months, theme counts). The LLM returns only labels per review id (strict JSON schema, enumerated themes, ≤ 12-word reason) — the input reviews are untrusted data. Without an LLM, keyword rules label themes (billing/insurance, waiting, staff/nursing, communication, outcome/complication, hygiene, discharge/admin, emergency).

## Round 8 — credits
**Answer.** Per check: 1 Maps search + 3 hospitals × 2 review calls (lowest-first and newest-first, same keyword) = **7 credits**, enforced as a per-check budget; results cached for a week, plus a server-wide hourly (30) and daily (60) cap. (An earlier draft had a per-hospital keyword ladder; dropped in Round 11.)

## Round 9 — the killer screen
**Answer.** A **theme grid**: rows = 3 hospitals (with Google ★ and review count), columns = complaint themes, cells = number of 1–2★ procedure reviews in the last 24 months; click a cell → the dated quotes. Above it: *"Manipal: 5 of its 20 lowest-rated knee reviews are complaints, newest Oct 2022 · Aster: 20 of 20, 9 since 2025 — mostly insurance/billing and in-patient care."*

## Round 10 — name
**Objection.** Must be instantly understood, with no conflicts.
**Answer.** *Discharge Summary* (medical pun) collides with ~270 discharge-document-generator repos — judges would assume it writes discharge notes. *AdmitOne* is a ticketing company's brand. **Bedside Manner** — the idiom everyone knows for how doctors treat patients; the app shows how hospitals treated patients who had your procedure. GitHub: 3–6 tiny repos (0–1★), web search: no app or service. Chosen.

## Round 11 — skeptical-judge critique (independent agent, checked against the probe JSON)
**Objections.**
1. **Apples to oranges:** Round 3 compared Manipal on `knee` with Aster on `surgery`. Only 1 of Aster's 20 "surgery" complaints mentions a knee (the rest: oncology, paediatrics, childbirth, piles, dialysis access). A per-hospital keyword ladder manufactures contrast.
2. **The 20 cap biases against big hospitals:** "20/20 are 1★" means *at least* 20; any 11k-review hospital hits it with a broad keyword.
3. **Defamation / ethics:** negative reviews name doctors; headlining "Fraudulent activities…" contradicts our own banned-words rule; calling reviews "solicited" is an accusation on circumstantial evidence.
4. **Dates:** a 2021 review was edited in 2025 — count by original date, show the edit date. Manipal has **0** knee complaints in the last 24 months.
5. **Usefulness:** a theme grid of small numbers won't change a decision.
Fact errors in this doc: newest Manipal knee complaint is **13 Nov 2022** (not Oct); **10** Aster complaints since 2025 (not 9); none of Manipal's five 1★ is about knee replacement; one Aster quote was paraphrased ("In-pateints" in the original).

**Answer / changes adopted.**
- **One keyword per comparison, same for every hospital**; no ladder. A zero result reads *"Google's filter returned no reviews — unknown"*, never "no complaints".
- **Two calls per hospital, same keyword:** (A) lowest-rated first → 1–2★ reviews about the procedure/admission in the last 24 months, shown as exact when the list reaches ≥3★ before 20, else "≥N"; plus the **hospital's reply rate to complaints** (volume-independent: Manipal replied to 19 of its 20 lowest, Aster to 1 of 20). (B) newest first → "k of the 20 newest are 1–2★" and the date span they cover. Overall ★ and review count as context only. **No score, no ranking.**
- Each complaint is tagged by the LLM as procedure/admission vs OPD vs other; only the first is headline-counted.
- **Doctor and staff names are redacted** in excerpts; excerpts ≤ 2 sentences, dated (original date; edit date shown), linked to the Google review. No "fraud/solicited/avoid/worst" in our words; quotes are never used as headlines.
- **"Ask before you admit"**: complaint themes become concrete questions ("Are room charges billed while the patient is in ICU?", "Get cashless pre-authorisation confirmed in writing"), each with how many recent complaints raised it.
- Hospital filter: primary type must be a hospital, titles starting "Dr" or containing "| Best" dropped, one branch per chain.
- Killer screen: **"Same 4.7★. Different stories."** — 3 cards (★, procedure complaints in 24 months, reply rate, newest-20 snapshot, 2 redacted excerpts) + "Ask before you admit". Theme grid secondary.
- Credits: 1 + 3 × 2 = 7 per comparison, cached a week.
