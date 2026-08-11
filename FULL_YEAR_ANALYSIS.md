# Full-Year Analysis (8,672 hours, 4-generator fleet)

Source: `results/full_year_hourly.csv` (2021, all 12 months, standard 4-gen
fleet, water-value convention). Cost/recovery figures below are corrected
post-hoc for the Q_ref infeasibility fix (dispatch itself is from the
pre-fix code, verified elsewhere in this session to shift by <0.02 MVAr per
generator — a cost-level correction, not a redispatch). This supersedes the
4-month subset in `RESULTS_ANALYSIS.md`/`TECHNICAL_VALIDATION.md` wherever
the two disagree; those remain valid as the earlier, smaller-sample version
of the same story.

## 1. Coverage

**8,672/8,760 hours solved (99.0%), 88 skipped, 0 unhandled errors.** Every
month has 662–744 hours represented (full or near-full coverage) — no month
is thin enough to bias the annual picture.

## 2. Settlement schemes, corrected, full year

| Scheme | Mean payment (EUR/h) | Recovery | c_v | Hours unprofitable | Hours profitable |
|---|---|---|---|---|---|
| baseline | 0.000 | — | — | 100% | 0 |
| capacity | 0.055 | **11.4%** | 0.000 | 100% | 0 |
| nodal | 0.459 | **95.6%** | 0.968 | 67.7% | 2,800 |
| uniform | 0.310 | 64.6% | 0.806 | 100% | 0 |
| AWU (2-zone) | 0.315 | 65.5% | 0.804 | 100% | 0 |
| hybrid (=capacity+nodal) | 0.514 | 107.0% | 0.865 | 61.4% | 3,349 |

This is the same qualitative story as the 4-month sample, now with 3x the
data and full seasonal coverage — **and it's essentially unchanged**, which
is itself a good sign: capacity payment never once breaks even across
8,672 real hours; nodal gets close to full recovery on average (95.6%,
even closer than the 4-month figure) while still losing money in about
2 hours out of 3; uniform and AWU sit in between, always in the red every
single hour (0/8672 profitable) despite averaging 65% recovery — because
they smooth away exactly the locational price spikes that made nodal's
profitable hours possible in the first place. That's a real, now
well-evidenced structural difference between the pricing bases, not noise.

## 3. Loss composition, full year

- Mean network loss: 0.0448 MW. Mean machine loss (all 4 generators):
  0.0208 MW — same ~2:1 ratio as the 4-month sample.
- **33.0%** of machine loss sits above each generator's own Q_ref (the
  loss-minimizing, feasible reference point) — the physical cost of
  reactive service the whole pricing exercise is about, confirmed at full
  annual scale.

## 4. Dispatch, full year — the water-value story holds up completely

| Gen | p_min (MW) | Mean P | Max P | % of year at floor |
|---|---|---|---|---|
| G1 | 1.20 | 1.229 | 2.014 | 88.0% |
| G2 | 0.75 | 0.751 | 1.016 | 99.0% |
| G3 | 0.90 | 0.900 | 0.900 | **100.0%** |
| G4 | 0.45 | 0.450 | 0.450 | **100.0%** |

G3 and G4 sit at their prime-mover floor in literally every one of the
8,672 solved hours, all year, every season. G1 is the only unit that
regularly earns its way above the floor (88% of the year still at floor,
but the other 12% reaches up to 68% above its own minimum). This is not a
4-month artifact — it's the fleet's actual year-round behavior.

## 5. Capability constraints, full year

**Field limit: 0.00% binding, all four generators, all 8,672 hours.**
Confirms — at full annual resolution, not just a sample — that this
fleet's installed capacity exceeds what real demand ever asks of it, in
every season, not only the ones already checked. Stator limit: also 0.00%
across the board. G4's underexcitation floor binds **21.56%** of the year
(close to the 19.2% found in the 4-month sample) — the one capability
constraint that's actually live, consistently, across the full annual
cycle.

## 6. Spatial pattern, full year, all 15 buses (not a 3-hour sample anymore)

| Hops to nearest generator | Mean λ^Q (EUR/MVArh) | Mean V (pu) |
|---|---|---|
| 0 | 0.132 | 1.042 |
| 1 | 0.454 | 1.039 |
| 2 | 0.798 | 1.035 |
| 3 | 0.140 | 1.041 |

Correlation(hop-distance, price) = **+0.298**; correlation(hop-distance,
voltage) = **−0.283**, computed over every bus, every solved hour of the
year. Same shape as the earlier 3-hour spot check: price rises with
distance up to 2 hops, then drops back down at hop 3 — and that dip is the
same known bus (6) with the degenerate, near-all-zero real reactive-demand
meter (H2 from the original review), not a new anomaly. A real, if modest,
locational effect (r≈0.3, not r≈0.9) — worth stating as "detectable and
directionally consistent," not "strong."

## 7. Annual demand/loss/price cycle (see `results/figures/fullyear_annual_cycle.png`)

Demand peaks in January/February (25.7 / 24.4 MW mean), falls through
spring, bottoms out June–September (8.3–10.0 MW), rises again
October–December. This is the textbook Norwegian electric-heating-driven
seasonal pattern, and it comes through cleanly at full-year resolution —
independent validation that the CINELDI-derived demand mapping is behaving
physically, not an artifact of the 4-month window chosen earlier. Nodal
payment and network losses both track this cycle almost exactly (compare
1.17 EUR/h mean nodal payment in January vs. 0.096 in July — a 12x swing
that follows demand, not noise).

## 8. Violations — none, full year

Max line loading across all 8,672 hours: **46.9%** (never close to 100%).
Voltage: min 1.0096, max 1.0500 (the max is the solver's own tolerance at
the ceiling, not a real breach — confirmed to ~1e-8 pu in earlier spot
checks). Zero real voltage-limit or line-thermal violations anywhere in a
full year of real demand.

## 9. Bottom line

Every finding from the 4-month study replicates at full-year scale, most
of them *more cleanly* (nodal recovery actually improves slightly to
95.6%; the spatial correlation is now backed by 8,672 hours across all 15
buses instead of 3 sample hours; the annual demand cycle is now visible
directly rather than inferred from two seasons). Nothing in the full-year
run overturns a conclusion already reported — it strengthens the evidence
behind each one. The two open items are unchanged: the field-limit story
still doesn't appear (now confirmed absent in literally every hour of the
year, not just a sample), and the pre-fix dispatch this run used is a
valid proxy but not the final, fully-corrected number.

## Still pending (running now)

- **Pricing-mechanism comparison** (4 real mechanisms including the two new
  ones — 3-zone AWU, performance-adjusted capacity) — running locally,
  ~68% done.
- **Placement experiment** — running on sassy, progressing far slower than
  expected (200/20,664 in 27 minutes); investigating separately, not a
  reason to hold back this report.
