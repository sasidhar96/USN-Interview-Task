# Results Analysis — Water-Value Run, 4-Generator Fleet, Dec+Jan+Jun+Jul

Source: `results/monthly_hourly_waterval.csv` (2,915 hours solved, 37 skipped),
produced by `python run_monthly_analysis.py --water-value` after the full
review-driven fix pass (pi_cap, demand power-factor bias, r_a_pu, Figure 3
filtering, cost-recovery accounting, s_interface_max units, water-value
convention applied consistently). This is the first run on the corrected
code — read it as "does the model now behave sensibly," not as final results
for the deck.

## 1. Run reliability

- **2,915/2,952 hours solved (98.7%), 37 skipped (1.25%).**
- Skips are scattered across December (32 of 37), no clustering by day or
  load level — consistent with the already-diagnosed IPOPT ill-conditioning
  at isolated hard hours, not a new systemic problem. January/June/July
  contributed only 5 skips combined.
- This is a healthy result. The earlier c^P=0 run's pathology (100% line
  loading, voltage pinned at the 1.05 ceiling in every single hour) **does
  not appear here** — see below.

## 2. How the optimization actually behaved

### Generation mix: pinned at the floor, as designed

| Gen | P range (MW) | P pinned at p_min? |
|---|---|---|
| G1 | 1.20 – 2.01 (p_min=1.2) | No — varies, sometimes well above |
| G2 | 0.75 – 0.90 (p_min=0.75) | Mostly, small variation |
| G3 | exactly 0.90, every hour | **Yes, literally every hour** |
| G4 | exactly 0.45, every hour | **Yes, literally every hour** |

This is the water-value convention working exactly as intended: with
`c_g^P = λ_E`, active energy itself is worth nothing extra to generate, so
machines sit at their prime-mover floor unless generating more *locally*
measurably cuts network losses or reactive import cost. G1 (closest to the
load, largest unit) is the only machine that regularly earns its way above
the floor. G3/G4 never do, at all, across 2,915 hours — worth a sentence on
the slide ("only the best-placed unit ever deviates from minimum output"),
and worth double-checking it isn't an unduly restrictive p_min/p_max spread
if you want to see more active variation.

### Losses: coordination is a wash, not a win, on this fleet/period

- Baseline mean loss: 0.0471 MW. Coordinated mean loss: 0.0459 MW.
- Mean delta is small and slightly favorable (−0.0012 MW), but **coordinated
  has *higher* losses than baseline in 46% of hours** — it's close to a coin
  flip, not a clear win.
- Mechanism (confirmed on the single-hour spot check, holds up in aggregate):
  coordinated dispatch will accept higher network losses when it buys a
  bigger cut in reactive-power import cost at the interface. It optimizes
  **total cost**, not losses — a genuinely different metric than SysOpt's
  6.8%–13.3% loss-reduction claim, and this fleet/period does not reproduce
  that number. That's a fine, reportable finding as long as it's framed as
  "we found losses to be roughly a wash while reactive costs dropped," not
  as a loss-reduction result.

### Voltage and congestion: healthy, unlike the earlier degenerate run

- Baseline never approaches either voltage limit (max 1.037 pu, min never
  below 1.009).
- Coordinated pushes to the 1.05 pu ceiling in **40% of hours** — voltage
  support is clearly one of the tools the optimizer is actively using to cut
  losses/reactive cost, not a coincidence.
- **No congestion anywhere**: max line loading never exceeds 46.9% under
  coordination, 96.4% under baseline (highest single hour, not a plateau).
  This directly contradicts the earlier c^P=0 finding of persistent 100%
  trunk loading — that pathology is gone under the water-value convention,
  which is a good independent confirmation that the c^P=0 regime really was
  the degenerate one, not this one.

## 3. Reactive pricing — the actual headline number

| Gen | mean λ^Q (EUR/MVArh) | median | range |
|---|---|---|---|
| G1 | 0.142 | 0.122 | 0.103 – 0.241 |
| G2 | 0.115 | 0.115 | −0.164 – 0.186 |
| G3 | 0.179 | 0.123 | 0.120 – 0.309 |
| G4 | 0.100 | 0.121 | −0.122 – 0.159 |

**These numbers bracket the SysOpt Nordic-44 "equitable price" anchor of
0.28 EUR/MVArh reasonably** — G3's own range (0.12–0.31) straddles it
directly, and the fleet-wide numbers sit in the same order of magnitude,
which is exactly the sanity check CLAUDE.md asks for. This is the strongest
piece of evidence so far that the physical cost model is producing credible
prices, not numerology.

**G2 and G4 go negative in a small fraction of hours** (0.1% and 7.0%
respectively, magnitude under 0.16 EUR/MVArh) — meaning at those hours the
system would rather these machines absorb *more* reactive power, not less.
Worth a sentence of explanation on the slide (it's a real, small, physically
sensible edge case near each machine's own Q*, not an error) but not worth
building a whole finding around given the tiny magnitude.

## 4. Settlement scheme comparison — cost recovery, not incentive response

Remember from earlier: schemes 1/2a/3 all settle the *same* coordinated
dispatch, so this section answers "how well does each scheme compensate
generators for a fixed physical outcome," not "which scheme changes
behavior" (see the settlement-architecture discussion from earlier in this
session).

| Scheme | Total payment (EUR, 2,915 h) | Recovery vs. total service cost (1,642 EUR) |
|---|---|---|
| 0 baseline | 0 | 0% (no payment scheme at all) |
| 1 capacity (real Statnett rate) | 159 | **9.7%** |
| 2a variable/nodal | 1,326 | **80.7%** |
| 3 hybrid | 1,485 | **90.4%** |

This is a clean, honest, and useful result: **the real Statnett capacity
rate, applied to this fleet, would compensate generators for under 10% of
their actual reactive-service cost** — a direct, quantified illustration of
the gap the whole project is about (fos §15 doesn't cover sub-10MVA
distribution-connected units in the first place, and even where it applies
conceptually, the rate is far too low to matter). Nodal utilisation pricing
does much better (81%), and hybrid (capacity + utilisation stacked) gets
closest to full cost recovery at 90%.

**What's still missing**: this recovery ratio is generator-side only
(payment vs. the generators' own service cost). The load-side counterparty
check added to `run_experiments.run_schemes()` this session was **not**
wired into `run_monthly_analysis.py`, so this run can't yet say whether
*loads* were charged enough to cover these payments — the single-hour base
case found a ~30x mismatch there. That's a concrete, cheap follow-up (the
`load_side_charge`/`cost_recovery` functions already exist in
`src/settlement.py`; they just need the same wiring into `solve_hour`).

## 5. What this run establishes

- The water-value convention (`c_g^P=λ_E`) produces a well-behaved, non-degenerate
  operating regime across a full 4-month, 2,915-hour real-data run — congestion-free,
  voltage-healthy, 98.7% solve rate.
- Reactive prices land in the same order of magnitude as the published
  Nordic-44 anchor, at a completely different (smaller, distribution-level)
  network — a genuine, if modest, credibility signal for the physical cost
  model.
- The real Statnett capacity rate under-compensates this fleet by an order
  of magnitude; nodal/hybrid utilisation pricing does far better. This is
  probably the single most defensible, quantified claim available right now
  for the "how should reactive power be incentivized" question.
- Coordination does **not** reliably reduce network losses on this
  fleet/period — it reduces total system cost by trading losses against
  reactive import cost. This needs to be the framing on the slide, not
  "coordination reduces losses like SysOpt found," which this run does not
  support.

## 6. Open questions / recommended next steps

1. **Wire `load_side_charge`/`cost_recovery` into `run_monthly_analysis.py`**
   so the counterparty question (are loads charged enough to cover
   generator payments?) can be answered at full-period scale, not just for
   one base-case hour.
2. **G3/G4 never leave their P floor across 2,915 hours** — worth a quick
   look at whether that's the expected physical story (they're just poorly
   placed/too small to matter) or an artifact worth a sensitivity check.
3. **Decide how to frame the loss result** — "roughly a wash, reactive-cost
   savings drive the total-cost improvement" is the honest framing; don't
   let a slide imply a SysOpt-style loss-reduction number that this data
   doesn't show.
4. **The field-limit story is still absent** in this run too (not
   specifically re-checked here, but nothing above shows field binding
   anywhere) — same open decision flagged earlier: report "not reached at
   these parameters" honestly, or deliberately re-tune to find a genuine
   binding case.
5. Once 1–3 are resolved, this single-config run is a reasonable basis to
   decide whether to re-run the full 4-fleet-config sweep (the one that was
   killed earlier) under the now-corrected code, or to scope the final
   deliverable to just this 4-generator configuration.
