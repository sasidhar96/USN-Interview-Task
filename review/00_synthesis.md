# Synthesis — 4 independent blind reviews (Opus 5, zero shared context)

Four agents, each reading only their own slice of the codebase with no
knowledge of each other's findings or of any prior design discussion,
reviewed: (1) network + demand data + case integration, (2) the hydro
generator loss/capability model, (3) the AC-OPF formulation and solver,
(4) the reactive-power settlement schemes. Full detail in `01`–`04`.

This file pulls out what matters across all four, ranked by how much it
would change a number that ends up on a slide.

## Must fix before the panel sees this

1. **Figure 3's headline result ("field limit binds → price jumps") is
   drawn from failed IPOPT solves, not real dispatch.** [03] All 8 rows
   where `g1_field_binding == True` in the sweep are the exact 8 rows with
   `status == "infeasible"` — the top load points, which overshoot the 50
   MVA interface limit. `solve()` returns fully-populated duals from a
   failed restoration with only a status string distinguishing them, and
   the plotting code doesn't filter on it. Re-solving those points gives
   different numbers. This is the same convergence-failure family
   diagnosed earlier this session (the `nlp_scaling_method` fallback) —
   now shown to be directly inside a headline figure, not just a nuisance
   skip rate. **Fix: filter non-optimal rows out of every figure/table
   before plotting, and re-run the sweep within the feasible interface
   envelope so a real binding event can be found (or honestly reported as
   not occurring at these parameters).**

2. **`pi_cap` is inconsistent by ~1400× between two call sites.** [04]
   `run_experiments.run_schemes` uses the correct Statnett rate
   (0.00248 EUR/MVArh); `run_seasonal`/`run_monthly_analysis` pass the
   Lnett *withdrawal* tariff (3.478) into the same `1_capacity` label.
   This is what's currently driving "capacity payment dominates" in the
   water-value run. **Fix: one value, everywhere; make any deliberate
   variant an explicitly labelled sensitivity, not a silent substitution.**

3. **The demand pipeline inflates reactive demand by ~1.8× in a way that
   flatters the study's own conclusion.** [01] `p_scale`/`q_scale` are
   each normalized by their own annual peak, which fall in different
   hours — this multiplies modelled tan φ by a constant factor across
   every hour (median tan φ 0.150 → 0.271; worst hour hits pf 0.76 on a
   feeder whose real deadband is pf 0.96). Undocumented anywhere. It
   biases toward finding reactive scarcity, which is the direction that
   makes the "reactive power needs pricing" thesis look stronger — worth
   fixing or disclosing prominently regardless of intent.

4. **No counterparty accounting anywhere in the settlement layer.** [04]
   Re-solving the base case: generators receive 0.83 EUR/h in nodal Q
   payments while loads are charged 25.61 EUR/h at the same nodal
   prices — a ~31× over-collection never computed in the code. 2 of 4
   generators are net-negative under nodal pricing over the 4-month
   water-value run. If the deliverable is going to claim a scheme
   "incentivizes" generators, cost recovery and who pays needs to be in
   the numbers, not just generator-side payments.

## Should fix — changes a number, not the headline story

5. **`r_a_pu` drops the stray-load-loss term the source paper includes.**
   [02] The paper's eq. (4) uses armature + stray load loss (276.62 kW);
   the code uses armature alone (0.002 pu, missing 70.6 kW). Restoring it
   moves Q* from −0.239 to −0.191 pu — into agreement with the paper's
   own "about −0.2 pu" statement. The docstring's claim that the gap is
   "structural, not a bug" is not accurate; it's mostly this one
   parameter. Moves marginal-cost slope ~20%, the zero-cost point ~25%.

6. **Test suite has a real blind spot.** [02] Every `test_machine.py`
   assertion runs at `v=1.0`, where `V` and `V²` are numerically
   indistinguishable. Mutation testing: 5 of 7 single-token mutations
   (including `V² → V` in `q_star`, which would silently move every
   downstream price) pass all 21 tests. Cheap fix: add one test at
   `v != 1.0`.

7. **`s_interface_max` compares a per-unit slack quantity against a value
   documented as MVA.** [03] Only survives because `baseMVA == 1`;
   demonstrated to silently violate an intended 20 MVA limit by 89% at a
   100 MVA base while still reporting `optimal`. Latent, not currently
   triggered, but a landmine for any future re-basing (which [03] also
   recommends independently — see below).

8. **Reactive-demand data has degenerate channels at specific buses.** [01]
   CIGRE bus 6 inherits a household meter with only 3 unique Q readings
   all year; one 56 VAr sample gets amplified ~2450× into a full-nominal
   spike. Buses 4/10 sit at zero Q for 49–67% of the year. Cross-bus
   reactive correlation median 0.01 — implausible, and it's exactly the
   signal being priced. Worth at minimum flagging which buses' Q traces
   are trustworthy.

9. **Settlement schemes don't feed back into dispatch.** [04] All 5
   payment rules are applied post-hoc to one fixed `PhysicalCost` solve —
   confirmed by byte-identical p_mw/q_mvar across schemes in
   `results/schemes.csv`. Reasonable as a first pass (and the code is
   honest about it), but any slide claiming a scheme "changes how much
   reactive power gets produced" needs to be reworded, or the
   feedback loop needs to actually be built for at least one scheme.

## Confirmed correct (worth stating on a slide as validated, not asserted)

- **EUR/MVArh unit conversion is correct.** [03] Independently re-derived
  from scratch and cross-checked by re-basing the whole problem to 100
  MVA — bit-identical to 5 decimals. This was flagged in the project spec
  as the single most likely silent bug; it isn't one.
- **No double-counting in the objective.** [03] No separate opportunity-
  cost term layered on top of the constrained formulation; it emerges
  correctly from the constraints alone, as intended.
- **Machine loss physics (field EMF, Q\*, marginal cost, capability
  circles) is correct term-for-term and sign-for-sign** against an
  independent re-derivation, and matches `syngenlib`'s own formulas
  structurally. [02]
- **Machine parameters are genuinely sourced from the cited paper**, not
  illustrative placeholders — verified against the paper's own rendered
  tables. [02] Note: `syngenlib` turned out to actually be installed and
  pinned in `requirements.txt`, contrary to the project notes' assumption
  that it was unavailable — worth adding a direct cross-validation test
  against it now that it's confirmed present.
- **AC power balance, slack handling, and the pandapower→ppc bus mapping**
  are correct, including a subtlety (18 ppc rows vs 15 buses on CIGRE MV)
  that would silently break the balance under a naive submatrix. [03]
- **Per-unit convention, CINELDI impedances, and the kWh/h-vs-MW unit
  handling are all correct** — two of these were flagged by the reviewer
  as things that look like bugs to a checker who hasn't read the source
  paper closely (base MVA 0.0344 vs the paper's stated 0.0334; the file
  is right, verified against three independent published statistics). [01]

## Documentation housekeeping

- `CLAUDE.md` describes a 3-bus/132kV/2-generator toy system with a
  `src/network.py` that doesn't exist in the actual implementation
  (CIGRE MV 15-bus + CINELDI data instead), and is never marked
  superseded despite being loaded as authoritative project instructions.
- `DESIGN.md`'s limitations section doesn't mention the demand pipeline
  at all — which is exactly where H1/H2 above live. The README documents
  the mapping correctly; the design doc just hasn't caught up to it.

## Cross-cutting root cause worth naming explicitly

Three of the four "must fix" items (1, 3, and indirectly 9) share a
pattern: **a modeling choice that happens to bias results in the
direction the study's own thesis wants** (more reactive scarcity, a
bigger field-limit event, a cleaner capacity-payment win), each currently
undocumented. None look deliberate — they look like ordinary pipeline
bugs — but a panel that builds these models for a living will check
exactly these things first. Fixing 1–4 and disclosing 5–9 is the honest
and also the more defensible path, per the project's own stated priority
on being "small, correct, and honest about assumptions."
