# Review 04 — Settlement schemes

**Scope reviewed:** `src/settlement.py`, `run_monthly_analysis.py`, settlement-bearing outputs
under `results/`. Read as supporting context (not reviewed for their own sake):
`src/opf.py`, `src/cost_models.py`, `src/machine.py`, `src/case_data.py`,
`run_experiments.py` (`run_schemes`, `run_seasonal`, constants), `tests/test_machine.py`,
`README.md §6`, `CLAUDE.md`.

**Reviewer stance:** first look, no prior context. I formed my own view from the code and
re-ran one OPF myself to check a claim the code never checks (revenue adequacy).

**One-line verdict.** The settlement layer is clean, readable, and unusually honest in its
docstrings — but it is a *pure post-hoc accounting layer*. Five of the six "schemes" are
five arithmetic formulas applied to one and the same dispatch. Nothing in the settlement
module can change a generator's behaviour, so the comparison cannot, as currently built,
answer "how should a reactive power market be incentivized." It answers a narrower and
still-useful question — "given an efficient dispatch, how does the money split under
different payment rules" — and the write-up should be scoped to exactly that unless the
structural change in §8.1 is made.

---

## 1. What is actually implemented

### 1.1 The schemes

`src/settlement.py` is 176 lines and defines exactly **three payment functions**, one of
which takes a three-way `pricing` argument, giving five distinct payment formulas. The
sixth ("Scheme 0") is not in this module at all.

| # | Label in output | Where implemented | Payment to generator *g* | Priced on |
|---|---|---|---|---|
| 0 | `0_baseline` | **Not in `settlement.py`.** Hand-rolled rows in `run_experiments.run_schemes` (l.270–279) and `run_monthly_analysis.solve_hour` (l.93–113); enabled by `opf.build_model`'s `fixed_voltage_buses` / `unity_pf_buses` | `0.0`, hardcoded | nothing |
| 1 | `1_capacity` | `settlement.capacity`, l.83–95 | `pi_cap * m.s_rated` | nameplate **apparent** power, dispatch-independent |
| 2a | `2a_variable_nodal` | `settlement.variable(pricing="nodal")`, l.133–135 | `r.q_price[b] * r.q_gen[b]` | own-bus dual of the reactive balance × delivered Q |
| 2b | `2b_variable_uniform` | `settlement.variable(pricing="uniform")` → `_uniform_price`, l.98–108 | `mean_over_machines(λ^Q) * r.q_gen[b]` | unweighted arithmetic mean of the *providers'* nodal duals |
| 2c | `2c_variable_awu` | `settlement.variable(pricing="awu")` → `_awu_price`, l.111–119 | `mean_over_zone(λ^Q) * r.q_gen[b]` | same, averaged within a hardcoded feeder zone |
| 3 | `3_hybrid` | `settlement.hybrid`, l.149–176 | `capacity_weight * pi_cap * m.s_rated + price[b] * r.q_gen[b]` | 1 + 2, stacked additively |

Everything else in the module is bookkeeping around those formulas:

- `_settle` (l.71–80) assembles a `Settlement` dataclass and computes
  `profit = revenue_p + payment − service_cost − gen_cost`, where
  `revenue_p = energy_price * P_g` and `gen_cost = p_cost_gen * P_g`.
- `_service_cost` (l.43–45) re-evaluates **`PhysicalCost`, hardcoded**, at the realised
  dispatch. Note this is hardcoded regardless of what cost model the OPF actually cleared
  against — settle a dispatch cleared under `AssumedCost` and the settlement will charge it
  physical costs. No caller does this today, but the coupling is a latent trap.
- `loss_of_opportunity_cost` (l.48–68) reports `λ_E * max(0, P_max − P_g)` when the field
  limit binds. Explicitly *not* added to profit (correctly — `revenue_p` already uses the
  reduced `P_g`). It is `0.0` in every row of `results/schemes.csv`.

### 1.2 Who pays

**Nobody.** There is no counterparty anywhere in the codebase. `Settlement.payment` is a
`{bus: EUR/h}` dict of money flowing *to* generators; no load charge, no DSO tariff
recovery, no offsetting revenue stream is ever computed. See §5.1.

---

## 2. Per-scheme assessment

### Scheme 0 — baseline (fixed voltage on G1, unity PF on G2/G3/G4)

**Coherent as a physical convention; not a settlement scheme, and not a clean control.**

This is the *only* one of the six that changes the dispatch, and it does so through
constraints (`m.v[...].fix(v_setpoint)`, `m.qg[...].fix(0.0)`), not through a payment.
Physically it is a defensible picture of today's practice — Statnett's fos §15 regulated
obligation for the large unit, unity PF for the rest, with a well-documented root-cause
note in `run_experiments.py` l.28–46 explaining why only G1 holds the setpoint (joint
infeasibility at light load otherwise). That reasoning is careful and I believe it.

Three problems remain:

1. **P is still fully optimised in the baseline.** Only Q/V is pinned. So "baseline" is
   not "what would happen today" — it is "today's reactive convention, with a
   perfectly-optimised active dispatch on top". Every comparison against it therefore
   mixes a reactive-coordination effect with an active-dispatch effect.
2. **The baseline generators' `C^Q` is excluded from the objective they are optimised
   under** (`opf.py` l.285: `0.0 if g in fixed_gens else cost_model(...)`) but is then
   *charged to them* in settlement (`run_monthly_analysis` l.93–94). That is internally
   consistent as accounting, but it means the baseline dispatch is not the optimum of
   anything the generator would have chosen, and its reported "profit" is the profit of an
   agent acting against its own interest.
3. **It is defensible but it is doing double duty**: it is simultaneously the "no
   compensation" control *and* the "no coordination" control. Those are different
   counterfactuals and the results conflate them (see §4).

### Scheme 1 — capacity (`pi_cap * s_rated`)

**Internally coherent; incentive-wise the weakest of the set, and it has a real perverse
edge the code does not flag.**

- It is a lump-sum transfer proportional to **apparent-power nameplate**. But what is being
  procured is *reactive capability*, which is not proportional to `s_rated` — it is set by
  the field limit and by how much of the machine is already committed to `P`. A machine
  dispatched at `P = P_max` has almost no Q headroom and still collects the full payment.
  **The scheme therefore pays for a nameplate, not for headroom, and creates no incentive
  whatsoever to preserve headroom.**
- There is **no availability test, no delivery obligation, and no penalty**. A generator
  that collects `pi_cap * s_rated` and then does nothing is paid identically to one that
  works. Free-riding is not merely possible, it is the dominant strategy. Real capacity
  markets (the New England VAR example the docstring cites) attach a must-follow-dispatch
  obligation and non-performance penalties; those are the parts that make a capacity
  payment a mechanism rather than a subsidy, and they are exactly the parts omitted.
- In the output it is literally a **two-valued column**: 76.5217 EUR/h in winter, 9.5652 in
  summer, in all 2947 hourly rows (see §6.2). 2947 AC OPF solves produce two numbers.
- **The rate is inconsistent between two parts of the same repo** — see Issue #3.

### Scheme 2a — utilisation, nodal

**The most economically defensible of the five, and the one worth building the argument
on. Two substantive caveats.**

- `λ^Q_g · Q_g` is the textbook locational settlement and matches Potter et al.'s rule.
  It reflects location (which the code's own numbers show dramatically — see §6.4), and it
  correctly charges generators that *absorb* at a positive-price bus (G2 in
  `schemes.csv`: `payment = −0.0263 EUR/h`). That sign convention is right, not a bug.
- **Caveat 1 — it fails cost recovery for most of the fleet.** In `results/schemes.csv` at
  nominal load, comparing `payment` against `service_cost`:

  | gen | service_cost | 2a payment | net |
  |---|---|---|---|
  | G1 | 0.3084 | 0.2736 | **−0.035** |
  | G2 | 0.0544 | −0.0263 | **−0.081** |
  | G3 | 0.3702 | 0.4156 | +0.045 |
  | G4 | 0.0258 | 0.1685 | +0.143 |

  Two of four generators are worse off providing the service than not; G2 is *charged*
  while also bearing a physical cost. Over the water-value-corrected 4-month run the fleet
  mean profit under 2a is **−0.21 EUR/h** (`monthly_hourly_waterval.csv`) — i.e. negative
  on average across 2793 hours. A voluntary mechanism with a negative expected participation
  payoff will not attract participation. The code never checks this and the write-up
  never reports it.
- **Caveat 2 — the price is a dual, not a market price.** `λ^Q` here is the shadow price of
  an operator-solved, cost-based, non-convex AC OPF with perfect knowledge of every
  machine's `k_f`, `X_s`, `R_a`. It is a *reference* price, not an outcome any decentralised
  process would produce. With four machines on one 20 kV feeder, each of them locally
  pivotal, a bid-based version of this would be a textbook local-market-power problem —
  and because the AC OPF is non-convex, a generator that withholds Q moves its own `λ^Q`.
  None of that is testable in the current setup because there is no bid layer.

### Scheme 2b — utilisation, uniform

**Not a coherent mechanism as implemented. This is the weakest link in the set.**

`_uniform_price` is the *unweighted arithmetic mean of the nodal duals at the buses of the
machines being settled*. That is not a uniform price in any market sense — a uniform price
is set by the marginal accepted offer (or by a system-wide reference), not by averaging over
whoever happens to be participating. The docstring is honest that it's a stand-in, but the
consequences are more serious than "an approximation":

1. **The price depends on the set of providers, not on the system.** Adding a fifth machine
   at a low-price bus lowers everyone else's payment. That is a direct manipulation vector
   and it violates the most basic independence property you would want.
2. **A single negative-price bus poisons the whole pool.** At nominal load the four nodal
   prices are `{G1 0.1627, G2 0.0920, G3 0.2063, G4 −0.1114}`; the mean is `0.0874`, i.e.
   **G4's negative price drags the uniform price down ~35%** for everyone. In the
   `c^P = 0` monthly dataset G4's `λ^Q` averages **−5.44 EUR/MVArh** against +0.07 at G1 —
   an unweighted mean over that set would be wildly negative and would flip the sign of
   every payment in the fleet. (2b is not run on the monthly dataset, which conceals this.)
3. **It is not budget-comparable to 2a.** Totals at nominal load: nodal 0.8314, uniform
   0.1658, AWU 0.2016 EUR/h. Uniform pays **5× less in total money** than nodal. So
   "nodal vs uniform" as presented is not a distributional comparison at constant revenue —
   it changes the size of the pie *and* its slicing simultaneously, and the two effects are
   not separated. Any statement of the form "pricing basis is a pure distributional choice"
   (README §6 bullet) is not supported by these numbers.
4. It is unweighted by quantity, so a machine delivering 0.01 MVAr has equal weight in
   setting the price as one delivering 3 MVAr.

### Scheme 2c — utilisation, area-wise-uniform

**Same structural problems as 2b, confined to a zone, plus a hardcoding issue.**

`FEEDER_ZONES` (l.29) is `{b: "feeder1" if b <= 11 else "feeder2" for b in range(1, 15)}` —
a module-level constant hardwired to CIGRE MV's bus numbering. It will `KeyError` on bus 0
and will silently mis-zone any other network. The topological justification (two separate
110/20 kV transformers) is genuinely good and I verified it against `net.trafo` (two 25 MVA
units, HV bus 0 → LV buses 1 and 12). But zone *boundaries* are the entire policy content of
an AWU scheme and no alternative zoning is tested, so the scheme's most interesting degree
of freedom is fixed by fiat.

### Scheme 3 — hybrid

**Arithmetically degenerate. It contributes no information.**

With `capacity_weight = 1.0` (the default, and what every caller uses), `hybrid` is
*exactly* `capacity + variable`. Verified in `schemes.csv`: G1, `0.0199 + 0.2736 = 0.2935`.
The dispatch is identical to 1 and 2a because none of them affect dispatch. So scheme 3's
row is the sum of two other rows in the same file — there is nothing to learn from it that
is not already in schemes 1 and 2a. The docstring's justification (PJM stacks capacity and
energy) is fine as far as it goes, but in a real stacked market the capacity obligation
*constrains* the energy dispatch (you must be available, you must follow), which is
precisely the coupling that would make the hybrid non-trivial and is precisely what is
missing.

The `capacity_weight` parameter is the one hook that could make this interesting (a budget
split between availability and delivery) and it is never varied.

---

## 3. Connection to the OPF — the central structural finding

**The scheme choice does not change the dispatch. It is post-hoc accounting on a single
solve.**

Read `run_monthly_analysis.solve_hour` (l.77–92): there are exactly **two** OPF solves per
hour — `coordinated` and `baseline` — both cleared against `PhysicalCost(ENERGY_PRICE)`.
Schemes 1, 2a and 3 are then three formulas applied to the *same* `coordinated` result.
`run_experiments.run_schemes` does the same with five formulas. Confirmed directly in the
data: in `results/schemes.csv`, `p_mw` and `q_mvar` are byte-identical across
`1_capacity`, `2a_variable_nodal`, `2b_variable_uniform`, `2c_variable_awu` and `3_hybrid`
(G1: `6.800000019183685`, `1.6821602090109358` in all five rows).

To be fair to the author, this is **stated plainly** in the module docstring
("not six different dispatch objectives") and in README §6 ("computed **after** clearing,
as a settlement-layer readout"). The honesty is real and I want to credit it. But the
consequence needs to be stated equally plainly in the conclusions, and currently it is not:

> **What can be claimed:** given a dispatch that is efficient under the physical cost model,
> the five payment rules distribute a small amount of money very differently, and nodal
> pricing is the only one whose distribution tracks locational cost.
>
> **What cannot be claimed:** that any scheme "encourages efficient Q provision", "changes
> how generators are dispatched", or is better or worse *as an incentive*. No generator in
> this study ever responds to a payment. The response function is not modelled.

The task brief I was given asserts that "compensation terms feed into the OPF objective
function and therefore change the optimal dispatch itself." **They do not.** The only thing
that enters the objective is the *cost model* (`AssumedCost` / `PhysicalCost` /
`DeadbandCost` / `NoCost`, `opf.py` l.285), and that axis is compared in a completely
different experiment (`run_base_case`, `run_load_sweep`) that has no settlement in it. The
repo has two orthogonal axes — cost model (changes dispatch, no payments) and settlement
scheme (changes payments, no dispatch) — **and they are never crossed.** That is the single
biggest gap.

---

## 4. Is the baseline a genuine no-compensation baseline?

**Partly. It is a genuine no-*coordination* baseline; it is not a clean no-*compensation*
baseline, and in the headline dataset it is confounded.**

It is *not* merely Case B relabelled with zero payments — credit where due, it is a separate
OPF solve with real behavioural constraints (`fixed_voltage_buses` / `unity_pf_buses`), and
those constraints are a reasonable model of the status quo. That is more than most studies
of this kind do.

But:

1. **P is optimised in the baseline too** (§2, Scheme 0). The counterfactual is therefore
   "coordination of Q only", not "no incentive".
2. **In `results/monthly_hourly.csv` (the `c^P = 0` run) the "coordinated" case has *higher*
   losses than the baseline in 100.0% of 2947 hours** (mean 0.534 vs 0.362 MW, +48%). The
   README root-causes this to voltage headroom and argues the correct claim is
   "coordination minimises total cost, not losses" — that reasoning is sound and I agree
   with the direction. But see §6.1: in that dataset the network is thermally pinned at
   exactly 100% loading in every single hour, which means the baseline-vs-coordinated
   comparison there is not measuring reactive coordination at all.
3. **The obvious missing baseline is absent.** Norway's actual instrument — the Lnett/Elvia
   `tan φ > 0.30` withdrawal deadband — exists in the codebase as `DeadbandCost` (a *cost
   model*) but is never evaluated as a *settlement scheme*. That is the real status quo and
   the most policy-relevant comparator for a Norwegian panel, and it is sitting one function
   call away from being included.

---

## 5. The comparison logic and its metrics

`run_monthly_analysis.solve_hour` records per scheme: `total_payment_eur_h`,
`total_revenue_p_eur_h`, `total_profit_eur_h`. Plus per-hour system quantities (losses,
Vmin/Vmax, max line loading) and per-generator `p`, `q`, `λ^Q` for the coordinated solve
only.

### 5.1 What is measured, and whether it is the right thing

| Metric present | Verdict |
|---|---|
| Total payment (EUR/h) per scheme | Necessary but not sufficient. Tells you the size of the transfer, nothing about whether it buys anything. |
| Total profit per scheme | **Actively misleading in the `c^P = 0` run.** `profit ≈ 70 · P` dominates: fleet profit is ~744–990 EUR/h while the entire reactive payment is 0.36–50 EUR/h. Scheme differences are 0.05–5% of a number driven almost entirely by active energy. The `--water-value` run fixes this correctly (`revenue_p − gen_cost = (70−70)·P = 0`), and that run is the only one where profit is a meaningful scheme metric. Both files are shipped; only one should be quoted. |
| Loss, V range, line loading | System metrics, fine, but they are identical across schemes 1/2a/3 by construction. Reporting them per scheme invites the reader to think the scheme caused them. |

| Metric **absent** | Why it matters |
|---|---|
| **Per-generator payment in the 4-month run** | Only fleet totals are recorded (`sum(s.payment.values())`). So **distributional/fairness analysis across the four deliberately-heterogeneous generators is impossible from the main dataset.** The fleet was designed (two sizes × two feeders) precisely to make a fairness point, and the data thrown away is exactly the data needed to make it. Per-generator payments exist only in `schemes.csv` — a single hour. |
| **Cost recovery / individual rationality** | `payment_g − service_cost_g` is never computed or reported, despite both being fields on the same dataclass. It is negative for 2 of 4 generators (§2, 2a). |
| **Revenue adequacy / budget balance** | See below — never computed anywhere. |
| **Price volatility** | 2947 hourly `λ^Q` values sit in the CSV and no dispersion statistic is taken, despite volatility being one of the standard arguments *against* nodal pricing and *for* uniform/administered rates. This is the cheapest missing analysis in the whole project. |
| **Pricing-basis axis in the monthly run** | `run_monthly_analysis` settles only `1_capacity`, `2a_variable_nodal`, `3_hybrid`. Schemes 2b and 2c — the nodal-vs-uniform question, arguably the most policy-relevant one — appear **only in the single-hour `schemes.csv`**. |

### 5.2 Revenue adequacy — I computed what the code does not

I re-solved the nominal base case and read `λ^Q` at **every** bus (the code only ever stores
generator buses):

```
bus  0 (slack/HV)  λ^Q =  3.4783   ← exactly Q_IMPORT_PRICE, as it must be
bus  1 (fdr-1 head) λ^Q =  3.4962
bus 12 (fdr-2 head) λ^Q =  1.9658
bus  3 (G1)        λ^Q =  0.1627   V = 1.0500  (ceiling binding)
bus 10 (G2)        λ^Q =  0.0920   V = 1.0500  (ceiling binding)
bus 13 (G3)        λ^Q =  0.2063   V = 1.0474
bus 14 (G4)        λ^Q = -0.1114   V = 1.0500  (ceiling binding)

nodal payment TO generators : 0.8314 EUR/h
nodal charge   TO loads     : 25.6053 EUR/h
merchandising surplus       : +24.77 EUR/h   (DSO over-collects ~30×)
total fleet service cost    : 0.7588 EUR/h
```

Two things fall out of this that the project should be making much more of:

1. **The scheme is massively revenue-*over*-adequate**, not inadequate. Under a consistent
   nodal settlement the network operator collects ~31× what it pays out. That surplus is
   real and has to go somewhere; a regulator will ask about it immediately. Nothing in the
   code computes it.
2. **The generators are sited where reactive power is worthless.** `λ^Q` is 3.50 at bus 1
   and 0.16 at bus 3 — a 21× collapse over two hops — because the generator buses are all
   pinned at the 1.05 voltage ceiling, so a marginal MVAr there has essentially no value.
   **The reactive prices at the generator buses are largely shadow prices of the voltage
   upper bound, not of reactive scarcity.** This explains, in one line, why every
   utilisation payment in the study is tiny and why cost recovery fails. It is a genuine,
   reportable finding — and it is also a caveat that undercuts the current framing, so it
   needs to be stated, not discovered by a panellist.

---

## 6. Data sanity check on `results/`

**Files containing settlement output:** `schemes.csv` (24 rows, 6 schemes × 4 gens, one
nominal hour), `seasonal.csv` (12 rows, 4 points × 3 schemes), `monthly_hourly.csv`
(2947 rows, `c^P = 0`), `monthly_hourly_waterval.csv` (2793 rows, `c^P = 70`),
`monthly_hourly_pilot.csv` (**1 byte — empty; all 48 pilot hours failed**),
`generator_count_comparison.csv` (no settlement columns). No NaNs in any settlement column
in either monthly file.

### 6.1 `monthly_hourly.csv` (the `c^P = 0` run) is not usable for the settlement question

Every one of the following is true in **100.0%** of its 2947 hours:

- `max_line_loading_pct == 100.0000` (both baseline and coordinated),
- `coordinated_vmax >= 1.0499`,
- `coordinated_loss_mw > baseline_loss_mw`.

A distribution feeder sitting at exactly its thermal limit for 2947 consecutive hours,
including summer minimum load (12.9 MW against 44.7 MW nominal), is not an operating
regime — it is the optimiser exporting until something stops it, because active energy is
free at the generator (`c^P = 0`) and paid for at the slack. Every `λ^Q` in that file is
therefore a congestion shadow price of a degenerate export-maximising dispatch. That is the
direct cause of the implausible `λ^Q` values:

- `lambda_q_g4`: mean **−5.44**, min **−6.75** EUR/MVArh
- `lambda_q_g2`: mean −0.62, min −5.63
- `lambda_q_g1`: mean +0.073, `lambda_q_g3`: mean +0.066

A ~100× spread and sign flip between two buses on the same 20 kV feeder is not a locational
signal anyone would defend. **Recommendation: retire this file from the settlement
analysis entirely, or relabel it as a degenerate-case diagnostic.**

The `--water-value` run is the credible one: `λ^Q` in 0.08–0.27 EUR/MVArh across all four
machines, line loading 16–45%, no pinning. Every settlement number quoted anywhere should
come from that file.

### 6.2 The capacity rate is inconsistent by a factor of ~1400 between two callers

- `run_experiments.run_schemes` passes `PI_CAP = 250 NOK/MVA/yr / 11.5 / 8760 = 0.00248`
  EUR/MVArh — the real, generator-facing Statnett fos §15 rate, carefully sourced and
  caveated at `run_experiments.py` l.64–83.
- `run_experiments.run_seasonal` (l.354) and `run_monthly_analysis.solve_hour` (l.89, l.91)
  pass **`q_price`** instead — the Lnett *withdrawal* tariff, 3.478 (winter) / 0.4348
  (summer) EUR/MVArh.

Both produce rows labelled `1_capacity`. The resulting numbers differ by ~1400×:
`schemes.csv` capacity payments are 0.007–0.020 EUR/h; `seasonal.csv` and the monthly runs
give 76.52 / 9.57 EUR/h. Annualised, 76.52 EUR/h × 8760 h ÷ 22 MVA = **30,470 EUR/MVA/yr,
against Statnett's actual 21.7 EUR/MVA/yr.** The `run_seasonal` comment defends the choice
(so the seasonal ratio shows up), but the effect is that the *headline* capacity number is
~1400× the real instrument it claims to represent, while a correctly-sourced number sits in
a different file under the same label. **This is the single most quotable-out-of-context
number in the repo.**

It also drives the entire scheme ranking: in the water-value run, mean profit is
`1_capacity +40.98`, `3_hybrid +41.34`, `2a_variable_nodal −0.21`, `0_baseline −0.24`
EUR/h. "Capacity beats utilisation by 200×" is not a finding about mechanism structure —
it is a finding about which of two unrelated tariffs was typed into `pi_cap`. Rerun with
`PI_CAP` and capacity collapses to ~0.055 EUR/h and the ranking inverts.

### 6.3 Missing hours are non-randomly the peak hours

`monthly_hourly_waterval.csv` drops 158 hours. They are not spread evenly:

| month | skipped |
|---|---|
| Jan | 101 |
| Dec | 53 |
| Jun | 3 |
| Jul | 2 |

Mean `p_demand_mw` of the skipped hours (recovered from the `c^P = 0` run, which solved
them) is **23.2 MW vs 14.8 MW for the hours that were kept** — the skipped set sits at the
**80th percentile of demand**. The code is admirably careful never to write a partial row
(`solve_hour` returns `None` on non-optimal, l.86) and logs every skip. But the effect is a
systematic censoring of exactly the tight winter hours where reactive scarcity, price
spikes and capability-limit binding would appear. Every mean, and any annualised total, in
that file is biased low and understates the tail. This must be stated wherever the file's
aggregates are quoted.

`monthly_hourly_pilot.csv` is 1 byte — all 48 pilot hours failed and the empty file was
written anyway. Harmless, but it should not be in `results/`.

### 6.4 `seasonal.csv` annualisation

`hours_in_season = 6 * 30 * 24 = 4320` (not 4380), applied identically to the "peak" and
"median" representative hour of the same season — so the two rows are alternative estimates
of the same 4320 hours, not additive, and nothing in the column name says so. A reader
summing `total_payment_eur_annualised` over the four seasonal rows would double-count each
season. `run_seasonal`'s docstring does warn the column is order-of-magnitude only; the
column name does not.

### 6.5 Smaller things

- `results/schemes.csv` has `loc == 0.0` in all 24 rows — the LOC diagnostic never fires.
- `generator_count_comparison.csv`: `coord_max_line_loading_pct == 100.0000005` in all 16
  rows, same pinning as §6.1; and the 4-gen config shows coordinated loss 0.543 vs baseline
  0.365 MW, consistent with the same artefact.
- `run_all_configs_parallel` (l.161–206) has **no CLI entry point** — `__main__` dispatches
  only `--gen-count` and `main()`. Its output is not in `results/`. Judging by
  `all_configs_run.log` / `shard_local_run.log` it was driven manually; the log ends in
  `maxIterations` warnings and a `BrokenPipeError`. Whatever it produced is not reproducible
  from the documented commands.
- One settlement test exists (`test_settlement_profit_does_not_double_count_loc`). There is
  no test for the payment formulas, no test for cost recovery, no test for the uniform-price
  definition, and no test that `pi_cap`'s units are consistent with `s_rated`'s.
- **Latent unit bug.** `Machine.s_rated`, `p_max`, `k_f`, `x_s`, `r_a` are **pu on the system
  base**; `OPFResult.p_gen`/`q_gen` are in **MW/MVAr**. `_service_cost` feeds MW/MVAr into
  `machine.loss` (pu coefficients); `capacity` multiplies `pi_cap [EUR/MVArh]` by
  `s_rated [pu]`; `loss_of_opportunity_cost` compares `m.p_max [pu]` with `r.p_gen [MW]`.
  All three are correct **only because `S_BASE = 1.0` MVA**. At any other base they break —
  and not by a clean scale factor: `field_loss` contains `(v + x_s·q/v)²`, which is not
  homogeneous in `q`, so it would be structurally wrong, not just mis-scaled. This is a
  time-bomb the moment anyone runs the pipeline on a network with `sn_mva ≠ 1`.

---

## 7. Ranked issues

1. **Schemes do not affect dispatch.** Five of six are post-hoc formulas on one solve. No
   incentive claim of any kind is supported. (§3)
2. **`monthly_hourly.csv` (`c^P = 0`) is a degenerate export-limited regime** — 100% line
   loading and 100% voltage-ceiling binding in every one of 2947 hours, `λ^Q` = −5.4 at one
   bus and +0.07 at another. Not usable. (§6.1)
3. **`pi_cap` is inconsistent by ~1400× between `run_schemes` (correct, `PI_CAP`) and
   `run_seasonal`/`run_monthly_analysis` (`q_price`, a withdrawal tariff).** It determines
   the entire scheme ranking. (§6.2)
4. **No revenue adequacy / budget balance / counterparty anywhere.** My own solve shows a
   ~31× merchandising over-collection under consistent nodal settlement. (§5.2)
5. **No cost-recovery (individual rationality) check.** 2a is net-negative for 2 of 4
   generators at nominal load and −0.21 EUR/h fleet-mean over the 4-month water-value run.
   (§2, §5.1)
6. **`_uniform_price` is not a uniform price** — it is an unweighted average over
   participants, manipulable by set composition, poisoned by a single negative-price bus,
   and not budget-comparable to nodal (5× less total money). (§2)
7. **Per-generator payments are discarded in the 4-month run.** Fairness across the
   heterogeneous fleet — the thing the fleet was designed to show — is unanalysable from the
   main dataset. (§5.1)
8. **158 skipped hours are non-randomly the peak winter hours** (80th demand percentile),
   biasing every aggregate in the water-value file. (§6.3)
9. **Scheme 3 is arithmetically `1 + 2a`** with the default weight and contributes no
   information. (§2)
10. **The pricing-basis axis (2b/2c) exists only at one hour**, not in the 4-month dataset.
    (§5.1)
11. **The real Norwegian status quo (`tan φ` deadband) is never settled**, only implemented
    as a cost model. (§4)
12. **Latent pu/MVA unit coupling** that holds only because `S_BASE = 1.0`. (§6.5)
13. **`_service_cost` hardcodes `PhysicalCost`** regardless of the clearing cost model. (§1.1)
14. **`FEEDER_ZONES` hardcoded to CIGRE MV bus indices**; `KeyError` on bus 0. (§2)
15. **`run_all_configs_parallel` is unreachable from the CLI**; `monthly_hourly_pilot.csv`
    is an empty artefact. (§6.5)

---

## 8. What to add or change — prioritised

This is the section that matters. Ordered by *argument strength gained per hour of work*.

### 8.1 Tier 1 — do these or the core claim stays unsupported

**(a) Make at least one scheme actually change the dispatch. [highest value, ~half a day]**

The minimum viable version: model the generator as a price-taker responding to the payment
rule, rather than as an obedient component of the operator's objective. Concretely, add a
`settlement_term(machine, p, q, v) -> Pyomo expr` to each scheme and subtract it from the
objective for that generator:

```
min  Σ_g [ c_g^P·P_g + C_g^Q(P_g,Q_g) − payment_g(P_g, Q_g, λ̂^Q) ] + λ_E·P_slack + ...
```

with `λ̂^Q` taken as a fixed (previous-iteration or announced) price so the problem stays
well-posed. Then:

- **Capacity** contributes a constant → dispatch is *identical to a zero-payment run*.
  That is the result: **a pure capacity payment provides no marginal incentive at all**, and
  you can now *show* it rather than assert it.
- **Nodal utilisation** shifts each machine's optimal Q to where marginal physical cost
  equals `λ̂^Q` — a visible, quantifiable behavioural response.
- **Deadband** produces a flat spot with a kink at `tan φ = 0.30` and bunching at the
  threshold — the classic distortion, and directly relevant to Norwegian practice.

Even one iteration of this converts "here is how the money splits" into "here is how the
dispatch differs under different incentives", which is the actual research question. If the
full fixed-point is too much, a **single best-response step from the coordinated dispatch**
is enough to make the point and is honest if labelled as such.

**(b) Add a revenue-adequacy and budget-balance ledger. [~2 hours]**

Extend `Settlement` with the counterparty side:

```python
charge_load:  dict   # λ^Q_i · Q_D,i at every load bus
charge_interface: float  # λ^Q_slack · Q_slack
surplus: float       # Σ charges − Σ payments
```

`opf.py` already returns `q_price` for every bus; the loads are in `net.load`. This is
~15 lines and it produces the number a regulator asks first. As shown in §5.2 the answer is
a ~31× over-collection, which is itself a headline-worthy result and reframes the study:
*the problem is not that reactive power is expensive, it is that the value is concentrated
at buses where no generator sits.*

**(c) Fix `pi_cap` to one defensible value and rerun. [~1 hour + solve time]**

Use `PI_CAP` (the real Statnett rate) everywhere, and if the seasonal ratio matters, add a
**separate, explicitly-labelled sensitivity** over `pi_cap ∈ {PI_CAP, Lnett_winter,
Lnett_summer}` rather than silently substituting one for the other. Report the resulting
scheme ranking as a *function of* `pi_cap`, since that is what it actually is.

**(d) Retire `monthly_hourly.csv` from the settlement analysis. [~0 hours]**

Quote only the water-value run, and state the peak-hour censoring (§6.3) wherever its means
appear. Optionally add `s_interface_max` tightening or a `c^P` floor so the `c^P = 0` case
stops pinning at the thermal limit — but the simplest honest move is to drop it.

**(e) Record per-generator payments in the 4-month run. [~15 minutes]**

`solve_hour` already has the full `Settlement` objects; it collapses them with
`sum(s.payment.values())`. Emit `{label}_payment_{gen}` and `{label}_cost_{gen}` columns.
This unlocks every fairness and cost-recovery analysis below at essentially zero cost, and
its absence is the reason those analyses do not exist.

### 8.2 Tier 2 — the metrics a market-design panel will ask for

**(f) Cost-recovery / participation-constraint table.** Per generator, per scheme:
`payment − service_cost`, and the fraction of hours it is negative. Both quantities are
already fields on `Settlement`. Report: *does any scheme leave every provider willingly
participating?* Right now the answer appears to be **no**, and that is a finding.

**(g) Fairness metrics across the heterogeneous fleet.** The fleet is deliberately two
sizes × two feeders — use it. Per scheme, report:
- payment per MVA of nameplate (does capacity favour big machines? by construction, yes),
- payment per MVArh delivered (does capacity reward non-delivery? yes),
- payment ÷ own service cost (the equity ratio that actually matters),
- a dispersion statistic (Gini or max/min ratio) across the four machines.

This is exactly where nodal will look "unfair" and capacity will look "unfair differently",
and articulating that trade-off *is* the mechanism-design contribution.

**(h) Price volatility.** From the 2793 hourly `λ^Q` values already on disk: std, CoV, P95/P5
ratio, count of sign changes, per generator. Then state the trade-off explicitly — nodal is
efficient and volatile, uniform/administered is stable and distorted. Cheapest strong result
available; roughly an hour of pandas.

**(i) Redefine `_uniform_price` properly, or drop it.** Two defensible options:
1. **Marginal price**: `max` over accepted providers' nodal prices (the actual uniform-price
   clearing rule), which makes it revenue-*over*-adequate versus nodal in a way you can then
   quantify; or
2. **Revenue-neutral uniform**: `λ̄ = Σ λ_g Q_g / Σ Q_g` (quantity-weighted), which holds
   the total payment fixed at the nodal total and turns 2b into a *pure* distributional
   comparison — which is what the README already claims it is.

Option 2 is the one that makes the existing claim true. Either way, add a test that the
uniform price is invariant to adding a zero-quantity participant.

**(j) Settle the Norwegian deadband as a scheme.** `DeadbandCost` already exists. Add
`settlement.deadband(machines, r, energy_price, threshold=0.30, rate=0.1*λ_E)` paying only
on `|Q| − 0.30·P` beyond the band. This gives the panel a direct comparison against the
instrument their own DSOs actually use, and it is ~10 lines.

### 8.3 Tier 3 — what makes it a mechanism-design paper rather than a costing study

**(k) Add a bid layer and test gaming resistance.** The elephant. Currently every price is a
dual of an operator-solved OPF that already knows every machine's `k_f`, `X_s`, `R_a`. Two
tractable steps:

1. **Information audit** (nearly free, high credibility): state explicitly, in a table, what
   each scheme requires the operator to know. Capacity needs only nameplate — verifiable
   from a plate. Nodal utilisation needs the full loss model *per machine*, plus a converged
   AC OPF, plus metered MVArh. **That informational asymmetry is the real argument for
   capacity payments and against nodal**, and it is the bridge to the CoordQ TSO–DSO
   framing (distribution inverters have heterogeneous, unobservable costs). Making this
   table is maybe two hours and it is the most panel-relevant thing missing.
2. **A withholding experiment** (~half a day): let one generator report `k_f` inflated by
   x%, re-clear, and plot its payment and the system cost against x. If payment rises with
   the misreport, the mechanism is not incentive-compatible — say so, and note that a
   VCG/pay-as-cleared alternative would be the fix. With four pivotal machines on one
   feeder I expect this to bite hard, which makes it a *result*, not a caveat.

**(l) Add a non-performance leg to the capacity scheme.** `payment = pi_cap·Q_capability −
penalty·max(0, Q_requested − Q_delivered)`, where `Q_capability` is the field-limited
reactive headroom at the dispatched `P`, not the apparent-power nameplate. This turns
Scheme 1 from a subsidy into a mechanism and fixes the perverse "paid for nameplate, not
headroom" incentive in §2. It also makes Scheme 3 non-degenerate, because the capacity leg
now couples to the dispatch.

**(m) Cross the two axes that currently never meet.** Run the settlement layer on dispatches
cleared under `AssumedCost` and `DeadbandCost`, not only `PhysicalCost`. This answers
"how much does getting the cost model right change the money?", which is the project's
stated thesis and is currently untested at the settlement layer. Requires fixing the
hardcoded `PhysicalCost` in `_service_cost` first (Issue #13).

**(n) Long-run / investment signal.** Every scheme is evaluated on a single hour's operating
economics. A regulator will ask whether the payment stream supports the *investment* —
e.g. annualised revenue under each scheme against the cost of the extra excitation capacity
or synchronous-condenser capability being incentivised. With per-generator hourly payments
(item e) this is a sum and a division.

### 8.4 Hygiene

- Add settlement tests: payment formulas, `hybrid == capacity + variable` at weight 1.0
  (assert the degeneracy so nobody mistakes it for a finding), uniform-price invariance,
  and a `pi_cap`/`s_rated` unit check.
- Convert `p_gen`/`q_gen` to pu at the settlement boundary (or carry both), so the pipeline
  stops depending on `S_BASE == 1.0` (Issue #12).
- Parameterise `FEEDER_ZONES` — pass zones in, derive them from `net.trafo`, default to
  CIGRE MV.
- Give `run_all_configs_parallel` a CLI flag and write its output to `results/`, or delete
  it. Delete `monthly_hourly_pilot.csv`.
- Rename `total_payment_eur_annualised` to something that cannot be summed by accident
  (`payment_eur_if_season_at_this_hour`), and fix 4320 → 4380.

---

## 9. Bottom line

The engineering is good and the docstrings are more honest than most published work — the
author repeatedly flags their own approximations, and Scheme 0 is a real second solve rather
than a relabelling, which is better than I expected. But as a *mechanism* comparison the
current design has one dispatch and five spreadsheets, and the ranking it produces is
determined by a single mis-typed rate constant rather than by any structural property of the
mechanisms.

Two changes carry most of the value: **(1) let at least one payment rule feed back into the
dispatch**, and **(2) add the counterparty side of the ledger** so revenue adequacy, cost
recovery and budget balance can be stated. With those, plus the per-generator payment
columns and the informational-requirements table, this becomes a defensible answer to "how
should reactive power be incentivized for hydro." Without them, the honest framing is:
*"here is a physically-derived reactive cost, here is what an efficient dispatch looks like
under it, and here is how differently five payment rules would divide a surprisingly small
amount of money — none of which currently covers the providers' own costs."* That is still a
real contribution, and stated that way it will survive scrutiny far better than an incentive
claim the code does not support.
