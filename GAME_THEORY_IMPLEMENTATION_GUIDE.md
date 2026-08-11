# Implementation Guide: Convexified CI-OPF and Bilevel Reactive-Power Market

**For a separate implementation effort. This document is the full spec —
read it end to end before writing code. The current repo's author will
review the result against the validation criteria in §7; nothing here is
optional unless marked "if time allows."**

## 0. Context, in one paragraph

The existing repo (`src/opf.py`) solves an exact, non-convex AC-OPF
(polar power balance, Pyomo + IPOPT) that prices reactive power for
dispatchable hydro via `C_g^Q(P,Q,V)`, a physically-derived loss cost, and
settles payment to generators post-hoc (`src/settlement.py`). That
architecture is deliberately **not** a game — generators don't choose
anything; the OPF centrally dispatches against true cost, and a payment
rule is applied afterward. This guide specifies how to build the thing that
*does* let a generator act strategically: a **convexified** market-clearing
OPF (needed because a non-convex lower level breaks the standard bilevel
solution method) plus a **bilevel/Stackelberg reformulation** on top of it,
following the general approach of Potter et al. (2023) and Zhang et al.
(2024) — both already read and cited in this repo's `CLAUDE.md` and
`MECHANISM_DESIGN_DISCUSSION.md`.

**Do not start from scratch.** Reuse, unchanged, from the existing repo:
- Network topology and impedances: CIGRE MV benchmark via `pandapower`
  (`src/case_data.py`), 15 buses, `S_base = 1` MVA.
- Real demand data: CINELDI hourly per-bus shapes (`src/case_data.py`,
  `build_case_from_hour`).
- Machine parameters: `run_experiments.machines()` — `R_a, X_s(=X_d), k_f,
  E_f_max, P_min, P_max, S_rated` per generator, G1/G3 cited to Karekezi et
  al. 2023, G2/G4 illustrative.
- The loss/cost function itself: `src/machine.py`'s `Machine.loss`,
  `q_star`, and `src/cost_models.py`'s `PhysicalCost` — the *economics* of
  `C_g^Q` do not change, only how it's embedded into a convex formulation
  (§2.4 below).
- Prices: `λ_E = 70` EUR/MWh, `π_Q` (Lnett tariff, seasonal), `π_cap`
  (Statnett fos §15) — all in `run_experiments.py`.

## 1. Two deliverables, in order of rigor (build and validate #1 before #2)

1. **Part A + B**: a convex Current-Injection OPF (CI-OPF) that reproduces
   the existing exact AC-OPF's results closely enough to trust as a
   drop-in replacement for the *lower level* of a bilevel program.
2. **Part C**: the bilevel/Stackelberg reformulation on top of Part A,
   answering "if one generator could strategically report its cost instead
   of being centrally dispatched against its true cost, what would it do,
   and does the market design (which settlement scheme) resist that."

**Also read Part D** — a much cheaper, non-convexified alternative that
partially answers the same question using the *existing* exact AC-OPF,
no new convex formulation required. If Parts A–C prove too large a lift,
Part D is a legitimate fallback and should be attempted regardless, in
parallel, since it needs none of the new machinery.

---

## 2. Part A — Current Injection (CI) OPF

Notation follows Potter, Haider, Ferro, Robba & Annaswamy, *"A reactive
power market for the future grid,"* Advances in Applied Energy 9 (2023)
100114 — cited in full in this repo's `README.md` §5 as `Q_Market 2023.pdf`
(excluded from the repo itself; locate via the DOI:
`10.1016/j.adapen.2022.100114`).

### 2.1 Decision variables

For every node `j` and phase `φ` (this repo's network is single-phase
equivalent per bus — see §2.6 on the single-phase simplification):

```
I_j^R, I_j^I     -- real and imaginary parts of nodal current injection
V_j^R, V_j^I     -- real and imaginary parts of nodal voltage
P_j, Q_j         -- active/reactive power injection at node j
```

### 2.2 Equality constraints

```
V = Z I                                                (Ohm's law, network-wide, complex)
P_j = V_j^R I_j^R + V_j^I I_j^I                        (bilinear — the non-convexity)
Q_j = -V_j^R I_j^I + V_j^I I_j^R                       (bilinear — the non-convexity)
```

`Z` is the network's impedance matrix. **Build it from the same
`pandapower` network object this repo already constructs** (`src/case_data.py`),
not from scratch — pandapower exposes `Ybus`/`Zbus` construction internally
(`pandapower.pypower.makeYbus`, already used in `src/opf.py` for the exact
model's thermal-limit constraints; the CI approach needs the inverse, `Z`).

### 2.3 McCormick envelope relaxation (this is what makes it convex)

Each bilinear term `w = x·y` above (four per node: `V^R I^R`, `V^I I^I`,
`V^R I^I`, `V^I I^R`) is replaced by four **linear** inequalities, given
known bounds `x ∈ [x_L, x_U]`, `y ∈ [y_L, y_U]`:

```
w ≥ x_L·y + x·y_L − x_L·y_L
w ≥ x_U·y + x·y_U − x_U·y_U
w ≤ x_U·y + x·y_L − x_U·y_L
w ≤ x_L·y + x·y_U − x_L·y_U
```

This is an **outer approximation**, not an exact equivalence — the tighter
the bounds `[x_L,x_U],[y_L,y_U]`, the smaller the relaxation gap. **This is
the single most important source of error in the whole approach and the
easiest part to get wrong**: computing loose bounds (e.g. just using the
voltage/current limits as-is, `V ∈ [0.95, 1.05]`, `I` unbounded) will give a
large, possibly unusable optimality gap. Potter et al. use a dedicated
iterative pre-processing step (their refs [36],[37], not available in this
repo — re-derive or approximate) to tighten bounds using load/generation
forecasts before relaxing. **Minimum viable version**: derive `I` bounds
from each machine's own `S_rated` and the voltage band (`|I| ≤ S_rated / V_min`),
and iterate — solve the relaxed problem once, tighten each `[x_L,x_U]` to
the solved values ± a shrinking margin, resolve, repeat until the gap
stabilizes (a standard "bound tightening" loop). Report the number of
iterations and the final gap; don't silently accept the first pass.

### 2.4 Objective — reuse `C_g^Q`, but check convexity explicitly

Potter's own objective (their eq. 3) is a quadratic generator-cost term
plus load disutility plus network losses. **This repo's contribution is a
different, more complex cost function** — `C_g^Q(P,Q,V) = λ_E[loss(P,Q,V) −
loss(P,Q*(V),V)]`, where `loss` includes terms like `R_a(P²+Q²)/V²` and
`k_f(V + X_s Q/V)²`. **These are not jointly convex in `(P,Q,V)`** —
division by `V` and cross terms like `Q/V` break convexity once `V` is a
free variable.

**Required fix, do this — do not skip it and assume IPOPT-on-a-relaxation
is "convex enough"**: evaluate `C_g^Q` at a **fixed** voltage (recommended:
`V = 1.0` pu, or the network's own `V_slack`), not the CI-OPF's own `V`
decision variable. With `V` fixed, `loss(P,Q,1.0)` reduces to a strictly
convex quadratic in `(P,Q)` alone (`R_a(P²+Q²) + k_f(1+X_s Q)² + k_f(X_s P)²`),
and the objective becomes a proper convex QP. This is a real, stated
approximation (cost evaluated at nominal voltage rather than the network's
actual solved voltage) — the existing exact model's own results
(`results/monthly_hourly_waterval_with_losses.csv`) show voltage stays
within roughly `[0.98, 1.05]` pu in the vast majority of real hours, so the
error this introduces should be small; **quantify it directly** by
comparing `C_g^Q` evaluated at `V=1.0` vs. the exact model's own solved `V`
across the existing hourly dataset, before relying on it.
(Refinement, if time allows: an outer fixed-point loop — solve at
`V=1.0`, take the resulting solved `V`, re-evaluate `C_g^Q` at that `V`,
resolve, repeat to convergence. Still convex at each inner solve.)

### 2.5 Constraints to carry over from the exact model, reformulated for CI

Do **not** use Potter's own inverter-PF constraint (their eq. 1e) — that's
specific to DER smart inverters. Replace with this repo's actual machine
capability constraints (`src/machine.py`), rewritten in terms of `P_j, Q_j`
(these are already linear/quadratic in the CI model's own `P,Q` variables,
no new relaxation needed for these three):

```
stator limit:          P² + Q² ≤ S_rated²                          (convex, a disk)
field limit:            P² + (Q + V²/X_s)² ≤ (V·E_f_max/X_s)²        (convex ONLY if V is fixed —
                                                                       same V=1.0 substitution as §2.4)
underexcitation limit:  Q ≥ −P·tan(acos(pf_lead_max))                (linear, already convex)
prime mover:            P_min ≤ P ≤ P_max                            (linear)
voltage band:            0.95 ≤ V ≤ 1.05  →  V_min^R,I ≤ V^R,I ≤ V_max^R,I
                                                                       (a box on real/imag parts approximating
                                                                        the true circular |V| band — state this
                                                                        approximation explicitly, it's standard)
```

### 2.6 Single-phase simplification, stated explicitly

Potter's CI model is built for **unbalanced multiphase** distribution
grids — that's its main selling point over Branch Flow/SOCP models. This
repo's network (CIGRE MV via pandapower) is modeled single-phase
(balanced-equivalent), matching the existing exact AC-OPF. **Use the
single-phase form of the CI equations above** (drop the `φ` superscript) —
do not build the full three-phase version unless explicitly asked; it adds
substantial complexity for no benefit here, since the underlying network
model this repo uses is already single-phase throughout.

---

## 3. Part B — Validate the CI-OPF before building anything on top of it

**Gate, not a suggestion**: do not proceed to Part C until this passes.

1. Solve the CI-OPF and the existing exact AC-OPF (`src/opf.py`, unchanged)
   on the same set of real hours — recommend the same 12-hour representative
   sample already used for the multi-start optimality check
   (`results/multistart_check.csv`, timestamps listed there).
2. Compare, per hour: total objective value (expect a gap — Potter reports
   up to 1.2% on their own case study; report this repo's own number, don't
   assume it matches), dispatched `P_g, Q_g` per generator (expect small
   deviations, report the max), voltage profile (Potter reports up to 0.9%
   voltage error on their case study).
3. **If the gap is materially larger than ~2-3%**, the McCormick bounds are
   too loose (§2.3) or the `V=1.0` cost substitution (§2.4) is introducing
   more error than expected at that hour — diagnose before proceeding, don't
   average the error away and move on.
4. Confirm the CI-OPF's own reactive price (`Q_j`'s dual, if using a
   solver that exposes duals — Gurobi/CPLEX for QP do, or use the
   McCormick-relaxed shadow price directly) is the same order of magnitude
   as the exact model's `λ^Q` (already established: 0.10–0.31 EUR/MVArh
   range, see `TECHNICAL_VALIDATION.md` §3).

---

## 4. Part C — Bilevel / Stackelberg reformulation

### 4.1 Scope, deliberately narrow to start

**Do one generator as leader at a time, others as passive/truthful
followers within the lower-level clearing.** Do not attempt a simultaneous
multi-leader equilibrium (all 4 generators strategic at once) as a first
pass — that is a genuinely harder, open research problem (equilibrium
existence/uniqueness is not guaranteed; see
`MECHANISM_DESIGN_DISCUSSION.md` §3's Nash-equilibrium discussion). One
leader at a time directly extends this repo's own
`withholding_experiment.py`, just with the leader's report now chosen
*optimally* by an upper-level optimization instead of swept over a few
fixed factors.

### 4.2 Upper level (generator `g`'s strategic problem)

```
max_{bid_g}   λ_E · P_g  +  payment_g(scheme, λ_g^Q, Q_g)  −  C_g^Q_true(P_g, Q_g, V_g)  −  c_g^P · P_g

subject to:   bid_g ∈ [reasonable bounds — e.g. reported R_a, X_s, or k_f
              scaled by a factor in [0.5, 5]; do not allow unbounded
              misreporting, it makes the upper level unbounded and
              uninformative]

              (P_g, Q_g, V, λ^Q) = solution of the LOWER-LEVEL CI-OPF
              (§4.3), in which generator g's cost term uses bid_g instead
              of its true cost, and every other generator uses its true cost
```

`payment_g` is one of `src/settlement.py`'s existing rules — start with
scheme 2a (nodal), since that's the one already shown (this repo's own
`test_price_at_unconstrained_generator_equals_its_marginal_cost`) to be
constructed to match the centrally-cleared dispatch when reporting is
truthful. Testing scheme 1 (capacity) here is less interesting — it has
zero `Q`-dependence, so misreporting a *cost* function has no channel to
affect a capacity payment at all; if scheme 1 is tested, the manipulation
lever would have to be misreporting `S_rated` instead, a different
experiment.

### 4.3 Lower level (market clearing, the CI-OPF from Part A)

```
min_{I,V,P,Q}   bid_g(P_g,Q_g,V_g)  +  Σ_{g'≠g} C_{g'}^Q_true(P_{g'},Q_{g'},V_{g'})  +  Σ c_{g}^P P_g

subject to:      all Part A constraints (§2.2 McCormick-relaxed equalities,
                  §2.5 capability/voltage constraints)
```

This is a convex QP (given the §2.4 fix) — its KKT conditions are
necessary **and sufficient**, which is exactly what makes the KKT
reformulation below valid. If the §2.4 fix is skipped and this remains
non-convex, everything below is invalid — this is worth re-stating because
it's the single most likely place for a rushed implementation to silently
break correctness.

### 4.4 KKT reformulation (single-level MPEC)

For the lower-level QP `min_x f(x) s.t. g(x)=0, h(x)≤0`:

```
Stationarity:            ∇f(x) + μᵀ∇g(x) + λᵀ∇h(x) = 0
Primal feasibility:      g(x) = 0,  h(x) ≤ 0
Dual feasibility:        λ ≥ 0
Complementary slackness: λ_i · h_i(x) = 0   for every inequality i
```

Substitute the lower level's `argmin` in the upper-level problem (§4.2)
with these four conditions — the result is a single-level MPEC.

### 4.5 Linearizing complementarity (Big-M → MIQP)

For every inequality `h_i(x) ≤ 0` with dual `λ_i ≥ 0`, introduce a binary
`z_i`:

```
λ_i        ≤ M · z_i
−h_i(x)    ≤ M · (1 − z_i)
```

**Calibrate `M` from this problem's actual scale — do not use a generic
large constant.** Duals here are prices; this repo's own solved values put
`λ^Q` in the range 0.1–5 EUR/MVArh even at stressed/near-infeasible points
(`results/load_sweep.csv`), and `λ^P` is bounded near `λ_E = 70` EUR/MWh.
Primal slacks are bounded by the machine capability limits (`S_rated ≤ 8`
MVA, `Q` magnitudes below `S_rated`). **A calibrated `M` on the order of
`10²–10³` in the natural units of each constraint should be generous
without wrecking the LP relaxation.** After solving, check that no active
complementarity constraint sits near the `M` bound — if one does, `M` was
too tight for that constraint and needs to be increased and re-solved, not
silently accepted.

**Solver**: this is now a MIQP (quadratic objective from `C_g^Q`, linear +
binary constraints from Big-M). Use Gurobi or CPLEX if a license is
available; open-source fallback is SCIP (via Pyomo's `SolverFactory("scip")`)
or Bonmin/Couenne for a MINLP formulation if avoiding Big-M's binaries is
preferred (strong-duality substitution, §4.6, avoids binaries entirely and
may be simpler to get working first).

### 4.6 Alternative: strong-duality substitution (no binaries, try this first)

Since the lower level is a convex QP, strong duality holds: primal optimal
objective = dual optimal objective. Substitute the lower-level `argmin`
with: primal feasibility + dual feasibility + `primal objective = dual
objective` (one nonlinear equality, but no binaries). This gives a
single-level **NLP** (not MIQP) — solvable directly with IPOPT, reusing
this repo's existing solver dependency, no new solver license needed.
**Recommended as the first attempt** — smaller change, reuses existing
tooling, avoids Big-M calibration risk entirely. Fall back to §4.5 only if
convergence is a problem.

---

## 5. Part D — Cheap fallback, no convexification needed (do this regardless, in parallel)

If Parts A–C are too large a lift in the available time, or even
alongside them, this repo's *existing* exact non-convex AC-OPF
(`src/opf.py`, unchanged) can answer a narrower but still useful version of
the same question, with no new formulation:

**Single-generator best-response re-solve**: fix every generator except
`g` at their centrally-optimal dispatch from a truthful solve. Re-solve the
*same* exact AC-OPF, but replace generator `g`'s objective term with
`−[λ_E·P_g + λ^Q_ref·Q_g − C_g^Q_true(P_g,Q_g,V_g) − c_g^P P_g]` (i.e.
maximize `g`'s own profit at a **fixed reference price** `λ^Q_ref` taken
from the original truthful solve — not re-optimized simultaneously, just a
single best-response step). Compare the resulting `(P_g, Q_g)` to the
original centrally-optimal values.

- If they match: strong empirical evidence the nodal scheme is
  locally incentive-compatible for generator `g` at that hour (a
  generator gains nothing by deviating from what it was centrally told to
  do, given the price it faces) — consistent with, and a direct numerical
  confirmation of, the marginal-cost-equals-price argument already made in
  `MECHANISM_DESIGN_DISCUSSION.md` §5.
- If they diverge: quantifies exactly how much profit is left on the table
  by *not* letting the generator act for itself — a genuinely new number,
  cheap to get, no McCormick relaxation or bilevel machinery required.

This is a few hours of work reusing 100% of the existing codebase and is
the recommended immediate next step regardless of what happens with Parts
A–C.

---

## 6. Part E — Settlement mechanisms directly in the objective (a related, separate question)

The user's other framing — "can capacity/variable/fixed payment be baked
into the objective directly, instead of applied post-hoc" — has a direct
answer that does **not** require bilevel machinery at all, worth
implementing regardless of the above:

Take the *existing* exact AC-OPF and change its objective from **minimize
system cost** to **minimize system cost minus total generator payment**
(equivalently: maximize `Σ_g profit_g` instead of minimizing `Σ_g cost_g`,
for a fixed settlement rule):

```
min  Σ_g [ c_g^P P_g + C_g^Q(P,Q,V) ]  +  λ_E·P_slack  +  π_Q·|Q_slack|
     − Σ_g payment_g(scheme, λ^Q_reference_or_rate, Q_g)
```

For scheme 1 (capacity, `payment_g = π_cap·S_rated_g`): this term is a
**constant** (doesn't depend on any decision variable) — subtracting a
constant from the objective changes nothing about the optimal dispatch.
**This is itself a clean, already-derivable result, worth stating on a
slide without writing any new code**: a pure capacity payment, embedded in
the objective or not, provably cannot change dispatch, because it has no
marginal effect on any decision variable — consistent with §5's finding
that scheme 1 doesn't incentivize delivery, now shown formally rather than
just observed empirically.

For scheme 2a (nodal, `payment_g = λ_g^Q · Q_g`) using a **fixed reference
price** (not the model's own endogenous dual, to avoid circularity): this
reduces exactly to Part D's best-response check, generalized to all
generators simultaneously in one solve rather than one at a time — a
genuinely useful, still-cheap middle ground between Part D (one generator)
and Part C (full strategic bilevel with endogenous misreporting). Worth
building if Part D's single-generator result looks interesting.

---

## 7. Validation checklist (what gets checked before this is accepted)

- [ ] Part B's gap report exists and is under ~2-3% objective/dispatch
      deviation from the exact model, on the same 12-hour sample already
      used elsewhere in this repo (or a clear explanation of why not, with
      the bound-tightening iteration count and final gap shown).
- [ ] §2.4's `V=1.0` cost-convexity substitution is explicitly stated, and
      its error is quantified against the exact model's own solved
      voltages (not assumed negligible).
- [ ] The lower-level QP's convexity is verified directly (e.g. check the
      Hessian of the objective is PSD given the fixed-`V` substitution),
      not just asserted.
- [ ] Big-M values (if that route is used) are reported alongside a check
      that no complementarity constraint sits near the `M` bound at the
      solution.
- [ ] Part C's result includes, at minimum, one real hour where the
      leader's optimal bid deviates from truthful reporting, with the
      resulting profit gain reported — directly comparable to
      `results/withholding_experiment.csv`'s existing (swept, not
      optimized) profit-gain numbers, as a sanity check (the *optimized*
      profit gain should be ≥ the best swept factor already found there).
- [ ] Everything is reproducible from a script, matching this repo's own
      convention (`python <script>.py` writes to `results/`).

## 8. Suggested order of work

1. Part A (§2), single hour, no bound-tightening loop yet — get something
   that solves at all.
2. Part B (§3) on that one hour — is the gap even plausible before
   investing in bound-tightening?
3. Add the bound-tightening loop (§2.3), re-run Part B on the full 12-hour
   sample.
4. Part D (§5) — cheap, parallel-track, start this at the same time as
   step 1 since it needs none of the above.
5. Part C via §4.6 (strong duality, no binaries) on one generator, one
   hour.
6. Part C via §4.5 (Big-M) only if §4.6 doesn't converge well.
7. Part E's capacity-payment argument (§6) — no code, just confirm the
   constant-term reasoning holds for this repo's actual objective, state it.

Report back per-step, not as one final dump — each step above is a natural
checkpoint to review before the next one starts.
