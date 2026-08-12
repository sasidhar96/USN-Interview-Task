# Reactive power pricing for dispatchable hydro — Norwegian MV context

Written for a reviewer with no prior context. Every numeric input below is
tagged **[SOURCED]** (verified against a primary document), **[DERIVED]**
(computed from a sourced quantity by a stated formula), or **[ASSUMED]** (no
source found; stated explicitly as a limitation). Nothing in the code should
be trusted at a higher confidence than its tag here.

**Read in this order:**
1. This file — network, data, machine, and OPF provenance (what's real vs. illustrative).
2. [`CASE_STUDY_AND_METHODOLOGY.md`](CASE_STUDY_AND_METHODOLOGY.md) — the current, full-year
   (8,675-hour) study end to end: formulation, every settlement scheme, the ownership-fairness
   finding, system-cost and reactive-procurement-cost savings, and the active-vs-reactive
   locational-pricing comparison. This supersedes the numbers in §7 below wherever they disagree
   — this file's §7 is the original, smaller-sample study kept for provenance.
3. [`KEY_FINDINGS.md`](KEY_FINDINGS.md) — every distinct finding from the project, one line
   each, grouped by theme, for pulling into slides without re-deriving anything.
4. [`CLAUDE.md`](CLAUDE.md) — the full implementation spec as actually built, including every fix applied and why.
5. [`RESULTS_ANALYSIS.md`](RESULTS_ANALYSIS.md) — the original 2,915-hour real-data study results.
6. [`TECHNICAL_VALIDATION.md`](TECHNICAL_VALIDATION.md) — does the optimization actually make sense (optimality, losses, settlement economics, capability limits).
7. [`MECHANISM_DESIGN_DISCUSSION.md`](MECHANISM_DESIGN_DISCUSSION.md) — LOC, bid-market feasibility with few participants, and post-hoc vs. game-theoretic settlement, grounded in the literature.
8. [`review/00_synthesis.md`](review/00_synthesis.md) — 4 independent blind-review reports (zero shared context) and how each finding was fixed.

**Not in this repo, intentionally:** the source PDFs used for citation
(Karekezi et al. 2023, Potter et al. 2023, and others) are excluded from
version control — they are third-party copyrighted journal articles, not
something to redistribute from a public repo. Every number sourced from them
is quoted and cited by DOI/title in this README and `CLAUDE.md` instead; the
citations are enough to locate and verify each one independently.

## 1. The question

How can reactive power from dispatchable hydro be incentivised in a
Nordic/Arctic distribution system? This is a mechanism-design question — the
deliverable is a **regulated-obligation baseline** plus **five incentive
schemes** (six total — see §6), compared on a network of **four hydro
units**, answering: what does the generator do, what does the system pay,
and would the generator actually participate.

## 2. Network — CIGRE MV benchmark

**[SOURCED]** CIGRE Technical Brochure 575, Task Force C6.04.02 (convened by
Kai Strunz), *"Benchmark Systems for Network Integration of Renewable and
Distributed Energy Resources,"* Paris, 2014.
PDF: https://web.nit.ac.ir/~shahabi.m/M.Sc%20and%20PhD%20materials/DGs%20and%20MicroGrids%20Course/2014-Cigre_575_Benchmark%20Systems%20for%20Network%20Integration%20of%20Renewable%20and%20Distributed%20Energy%20Resources.pdf
Implemented via `pandapower.networks.create_cigre_network_mv()`
(https://pandapower.readthedocs.io/en/v2.0.0/networks/cigre.html) — every R,
X, and per-load P/Q base value comes directly from this report, not invented
and not a pandapower default.

| Property | Value | Verified |
|---|---|---|
| Total buses | 15 | `len(net.bus)` |
| Voltage levels | 1× 110 kV (slack) + 14× 20 kV | `net.bus.vn_kv.unique()` |
| Lines | 15 | `len(net.line)` |
| Transformers | 2, both 110/20 kV, 25 MVA | `net.trafo` |
| Load buses | 13 of 15 (18 load rows — several buses carry two customer classes) | `net.load` |
| Load-only buses | 11 | computed |
| Generator buses (also carry local load) | 4 — bus 3, 10 (feeder 1), bus 13, 14 (feeder 2) | `GEN_BUSES` in `src/case_data.py` |
| Pass-through bus (neither load nor generator) | 1 — bus 2 | computed |
| Nominal total demand | 44.74 MW / 11.04 MVAr | `net.load.p_mw.sum()`, `.q_mvar.sum()` |
| Branch R/X | median 0.70 (min 0.70, max 1.39) | computed from `net.line` |
| Per-load power factor | varies 0.85–0.98 by customer class (residential/commercial/industrial) | computed from `net.load` — **[SOURCED]**, not a pandapower artifact |

**Why MV, not LV, and why this specific benchmark** — full reasoning in
`DESIGN.md` §2.4 and this session's transcript; short version: (a) LV cable
R/X ≈ 7.5 (measured, see §3) makes reactive power nearly powerless to move
voltage there; (b) the smallest credible synchronous machine (100 kVA) has
~8× the entire measured LV feeder's peak reactive demand — no scarcity to
price; (c) as a matter of interconnection practice, a machine large enough
for its reactive capability to matter is not connected at 230 V in the first
place — **[ASSUMED]**, engineering convention, not tied to a specific
citation checked this session.

## 3. Demand data — what is real, what is derived

**[SOURCED]** Engan, Ekrheim, Bjarghov, Klemets, Schytte & Kjølle (2025),
*"Reference dataset for semi-urban and rural Norwegian low voltage
distribution grids,"* Data in Brief 59, 111453.
DOI: https://doi.org/10.1016/j.dib.2025.111453
Data: Zenodo https://doi.org/10.5281/zenodo.14528192 — checked against the
Zenodo API this session (title/authors/DOI match exactly).

We use the **50-bus rural reference grid**'s hourly P and Q, 8760 hours,
2021, price area NO2 — read the paper directly (not summarised): §3.1
states the two *semi-urban* grids assume a constant PF of 0.98. The two
*rural* grids (including the one used here) instead **"have their original
load profiles"** — i.e. not PF-derived. Verified independently this session
by computing the implied power factor at every bus, every hour, directly
from `p_load.csv`/`q_load.csv`: it is **not constant** (std 0.09 across all
buses/hours, individual buses ranging 0.38–1.00). See
`results/figures/fig0_demand_data.png` — total P and Q over the measured
year, and the implied aggregate power factor (which stays closer to 1.0 than
any single bus, since aggregation across many buses averages out local
variability — expected, and visible directly in the figure).

**How it is applied to CIGRE MV** — **[DERIVED]**, `src/case_data.py`.
**The absolute MW/MVAr values used in every solve are CIGRE's own published
MV-level values — never the LV dataset's absolute values.** Only the temporal
*shape* (how demand moves hour to hour) is borrowed from the real Norwegian
data.

Two generations of this mapping exist in the code, and the second replaced
the first mid-session after a real methodological problem was caught:

1. `demand_shapes()` / `build_case(p_scale, q_scale)` — ONE national shape
   (all 21 real CINELDI load buses summed, then normalised) applied
   uniformly to every CIGRE bus. Kept, but **only for the uniform load
   SWEEP** (`run_load_sweep`), where a deliberate system-wide stress
   multiplier is the right tool. Applying this to a single "real" hour was
   the original approach and is no longer used for that, because it forces
   every CIGRE bus to move in perfect lockstep (correlation 1.0), which is
   not real — measured CINELDI bus-to-bus correlation is 0.24–0.47.

2. `bus_demand_shapes()` / `build_case_from_hour(timestamp)` — **the one
   used for any single real hour** (base case, seasonal runs, scheme
   settlement). Each of CIGRE's 13 load buses gets its own real CINELDI
   household group, summed (not averaged — summing raw kW is what physical
   aggregation actually is) then normalised by that group's own peak.
   Group sizes are matched to each CIGRE bus's own scale: CIGRE MV is
   extremely skewed (buses 1 and 12 alone are 89% of total demand, 19.84
   and 20.01 MW; the other 11 buses are all under 1 MW), so the two
   dominant buses each get 4 real households summed (smoother, appropriate
   for buses representing many aggregated customers — the diversity/
   coincidence-factor effect), the next two largest get 2, and the
   remaining 9 (already close to single-household scale) get 1 each.
   `4+4+2+2+9×1 = 21` — every one of the 21 real households used exactly
   once. Mapping: `CIGRE_TO_CINELDI_GROUPS` in `src/case_data.py`; the
   specific column-to-bus pairing beyond the group sizes is arbitrary and
   stated as such.

**Realism check, run directly against this mapping (not asserted):**
network-wide winter:summer active-demand ratio = **1.647**, computed by
summing all 13 buses' real hourly shapes across the full year — the correct
direction and a plausible magnitude for Norway's electric-heating-dominated
seasonal pattern. `results/figures/fig_bus_profiles.png` plots the annual
profile for a sample of buses directly: buses 1 and 12 (4-household groups)
show a clean textbook Norwegian seasonal curve. Two single-household buses
are visibly atypical — bus 9 goes near-zero for June–August (a real,
documented pattern: `load_bus_extra.csv` categorises rural loads as
*"private building... residential houses, holiday homes, and farms"* — this
is a holiday home, unoccupied in summer) and bus 11 is very spiky (CoV
1.53, mostly near zero with occasional large draws — plausibly a farm
outbuilding). These are real, explained by the dataset's own metadata, not
fabricated — but they are a genuine simplification: a single real
household's pattern, however real, is not the same thing as what an
actual aggregated MV substation would show. Checked specifically where it
would matter most — the two GENERATOR buses (3 and 10) — and neither shows
this effect: bus 3's household is active year-round (0% near-zero hours,
CoV 0.43); bus 10's is somewhat more variable (CoV 0.80, 9.8% near-zero
hours) but has no extended dead season. The atypical households sit away
from the generators, not at them.

Limitation, stated rather than hidden: one real shape (or small real group)
per bus, not a true continuous statistical distribution of many customers;
and customer-class distinctions (residential vs commercial vs industrial,
which CIGRE's own base values do carry) are not preserved in the shape
itself.

## 4. Machine model

**[SOURCED, primary]** Karekezi, Melfald, Oyvang & Noland (2023), "Loss
Modeling of Large Hydrogenerators for Cost Estimation of Reactive Power
Services and Identification of Optimal Operation," IEEE Trans. Energy
Conversion 38(2):1350-1360. DOI: 10.1109/TEC.2022.3230763. PDF
`Loss_Modeling_of_Large_Hydrogenerators_for_Cost_Estimation_of_Reactive_Power_Services_and_Identification_of_Optimal_Operation.pdf`
in this repo -- read directly, page by page (Tables I and II independently
verified against the raw text this session, not taken from a summary). Their
103 MVA, 11 kV, 500 rpm hydrogenerator case study is G1's reference machine.

Companion paper, used for cross-checking Q* only (see below): Karekezi,
Oyvang & Noland (2022), "The Energy Transition's Impact on the Accumulated
Average Efficiency of Large Hydrogenerators," IEEE Trans. Energy Conversion
37(3):2069-2079. DOI: 10.1109/TEC.2022.3158566. PDF
`The_Energy_Transitions_Impact_on_the_Accumulated_Average_Efficiency_of_Large_Hydrogenerators.pdf`
in this repo.

**Simplified round-rotor loss model actually implemented** (`src/machine.py`),
following the closed form SynGenLib's own `archive/pyomo_generator_loss_model.py`
uses:

```
P_cu,stator = R_a (P^2 + Q^2) / V^2
E_f^2       = (V + X_s*Q/V)^2 + (X_s*P/V)^2
P_cu,field  = k_f * E_f^2
```

**This is a deliberate simplification against the primary source above, not
their model.** Karekezi et al.'s actual rotor loss (their eq. 5) is
linear-plus-quadratic in field CURRENT, not purely quadratic in EMF:
`P_l,r = P_ex*(I_f/I_f*) + (P_f*+P_br*)(I_f/I_f*)^2`, with `I_f` obtained from
a saturated Potier-triangle construction (their eqs. 21-23) that is an
implicit relation, not a closed form -- embedding it directly in Pyomo would
face the same differentiability problem that keeps SynGenLib itself from
being called directly inside an OPF (see SS5). They also use a true
salient-pole model (X_d != X_q, a 38% difference for their reference machine
-- not a small one). Neither is implemented here; the closed-form,
differentiable E_f^2 model is kept instead, at the cost of that fidelity.

Extended from 2 to 4 machines (G3, G4 added after the initial build) to give
a genuine multi-generator economics story -- capacity size and feeder
location as the two axes of difference, deliberately *not* inventing
per-unit condition-management differences beyond that. Two machine "types"
are reused at four sizes rather than four independent parameter sets: Type A
(G1, G3) is the Karekezi-cited reference machine; Type B (G2, G4) is the same
illustrative deviation used throughout. G3/G4 sit on **feeder 2** -- CIGRE
MV's second, independently-transformed feeder (`net.trafo` has two separate
110/20 kV units; feeder 2's head is bus 12, not bus 1) -- not just a third
and fourth copy of G1/G2's story on the same trunk.

| Parameter | G1 | G2 | G3 | G4 | Status | Source |
|---|---|---|---|---|---|---|
| Type | A | B | A | B | | |
| S_rated | 8 MVA | 5 MVA | 6 MVA | 3 MVA | **[ASSUMED]** | chosen to fit this feeder's scale |
| Bus (feeder) | 3 (feeder 1) | 10 (feeder 1) | 13 (feeder 2) | 14 (feeder 2) | **[ASSUMED]** | electrical-distance and feeder-topology contrast |
| cos phi | 0.90 | 0.90 | 0.90 | 0.90 | **[SOURCED]** | Table II, exact |
| X_d | **1.087 pu** | 1.3 pu | **1.087 pu** | 1.3 pu | G1/G3 **[SOURCED]**, Table II, exact; G2/G4 **[ASSUMED]** (no second real reference machine -- explicit, stated deviation from Type A) |
| R_a | **0.0026862 pu** | 0.0026862 pu | **0.0026862 pu** | 0.0026862 pu | **[SOURCED]**, corrected — Table I's *combined* armature+stray-load loss, `(P_a*+P_s*)/S_rated = 276.62 kW / 103,000 kW`, not Table II's standalone `R_a=0.002pu` (Table II's value is used in the paper only for the Potier field-current estimate, not as the stator I²R coefficient this model's `stator_loss()` needs — an earlier version of this file used the bare Table II value, which understated stator loss by the missing 70.6 kW stray-load component; caught by independent blind review, see `review/02_generator_model_review.md`) |
| E_f,max | derived | derived | derived | derived | **[DERIVED]** | `E_f,max^2 = (1 + X_d*sinphi)^2 + (X_d*cosphi)^2` -- the rated point sits exactly on the field-limit corner by construction; test: `test_ef_max_derived_from_rated_point` |
| rotor_loss_frac (-> k_f) | **0.001861 pu** | 0.0024 | **0.001861 pu** | 0.0024 | G1/G3 **[SOURCED]**, Table I: (P_ex* + P_f* + P_br*) / S_rated = (15.88 + 175.78) kW / 103,000 kW, exact; G2/G4 **[ASSUMED]**, ~30% above Type A's cited value | `k_f = rotor_loss_frac / E_f,max^2` |
| pf_lead,max | 0.86 | 0.86 | 0.86 | 0.86 | **[SOURCED]** | de Brito, Baltensperger & Uhlen (2025), CIGRE Trondheim, paper 1120, eq. (6): "maximum leading power factor phi_lead^max = 0.86 as per the Norwegian grid code" -- full text read via https://arxiv.org/abs/2502.10220 (ar5iv HTML mirror; the raw PDF did not parse) |
| P_max, P_min | 0.85, 0.15 pu of S_rated, all four | **[ASSUMED]** | illustrative | | | |

Combined nameplate: 22 MVA vs. 44.74 MW nominal feeder demand (49%, up from
29% with just G1/G2) -- enough local capacity that it materially changes the
congestion picture (see OPF formulation, below).

Q* (loss-minimising reactive point) is derived analytically, not fit:
`Q* = -k_f*X_s*V^2 / (R_a + k_f*X_s^2)`. Tested against a numerical sweep
(`test_loss_minimum_at_q_star`) and confirmed negative (`test_q_star_is_negative`).

**Cross-checked against the primary source, not just declared.** With G1's
corrected parameters above, this simplified model's analytical Q* = **-0.191 pu**
(machine base) against the paper's own reported range for their real 103 MVA
machine: **-0.194 to -0.202 pu** (with saturation) and **-0.152 to -0.157 pu**
(without saturation -- the fairer comparison, since this model has no
saturation either; both read from the paper's Fig. 2, not tabulated). **This
now falls inside the saturated range**, not just "same order of magnitude" --
before the R_a correction above, the bare-Table-II value put Q* at -0.239 pu,
outside the paper's own reported range entirely. The paper independently
states "the minimum losses for the studied generator is around -0.2 pu
reactive power, regardless of the active power level" -- the corrected model
now reproduces that number directly, not just its sign and order of
magnitude.

**Approximation stated explicitly, and now quantified:** round-rotor form
(X_d = X_q). Karekezi et al.'s actual 103 MVA machine has X_d = 1.087 pu,
X_q = 0.676 pu -- a 38% difference, a real and sizeable simplification, not a
minor one. Declared per CLAUDE.md's original guidance that this is defensible
for a steady-state cost study as long as it is stated plainly, which it now
is with the real numbers behind it.

## 5. OPF formulation

Exact non-convex AC OPF, Pyomo + IPOPT 3.14.19, `src/opf.py`.

**Decision variables:** `V_i, θ_i` (state — determined by the balance
equations, not chosen) at every bus; `P_g, Q_g` (control) per machine;
`P_import, Q_import` at the slack.

**Objective:**
```
min  λ_E · P_import  +  Σ_g [ c^P_g · P_g + C_g^Q(P_g, Q_g, V_g) ]  +  π_Q · |Q_import|
```
Losses are inside `P_import` — no separate loss term (would double-count).
Voltage is a **constraint only**, never an objective term — matching Potter
et al. (2023, their eq. 1) and Zhang et al. (2024)'s joint P+Q market, both
confirmed directly against Brain notes this session: both minimise system
cost subject to an ANSI/0.90–1.05 pu voltage band, not a voltage-support
objective.

**Constraints, every bus:** AC active and reactive power balance (built over
the full internal ppc bus set, not a `net.bus` submatrix — pandapower
expands transformers into auxiliary star-point buses; using a submatrix
silently broke power balance during development, residual 938 pu; over the
full ppc set the residual is 5×10⁻¹³ pu, confirmed by `test_power_flow_residual`).
`0.95 ≤ V ≤ 1.05` pu. Per machine: stator circle (`P²+Q² ≤ S_rated²`); field
circle (centre `(0, -V²/X_s)`, radius `V·E_f,max/X_s`); underexcitation ray
(`Q ≥ -P·tan(acos(0.86))`, replacing an earlier invented `0.75·V²/X_s`
constant); `P_min ≤ P_g ≤ P_max`; slack angle fixed at 0, slack voltage fixed
at its power-flow value (an unconstrained slack voltage would let the OPF
"buy" free voltage support).

**Convexity:** genuinely non-convex (products of `V_i·V_k` and `cos/sin` of
angle differences). No relaxation used — Potter convexifies (current
injection + McCormick) to get a global guarantee at the cost of an
unquantified relaxation gap (their own stated limitation #3); our cost
function is a machine loss curve the McCormick route cannot carry, so exact
physics was kept and the global guarantee given up. Mitigated by
warm-starting from a converged power flow and replaying every solution in
pandapower (`test_power_flow_residual`).

**Branch thermal limits** (added after the initial build): every `net.line`
current is constrained, `|I| ≤ max_i_ka`, at both ends (`Yf`/`Yt` from
pypower's own `makeYbus` — the same construction pypower's OPF itself uses
for line-flow limits, not a hand-derived pi-model formula). This is a
standard AC-OPF constraint (Frank et al. 2012, Table 3; enforced explicitly
in Potter et al. 2023's own reactive-market OPF) that the first build of this
study omitted. Checking it mattered: replaying the unconstrained OPF's own
solution in pandapower showed the feeder-1 trunk (lines 1–2, 2–3) at **128%**
of thermal rating at nominal load — a real violation, not a rounding
artefact. With the constraint enforced, **congestion on that trunk — not any
generator's own field limit — is the actual binding constraint across almost
the entire load sweep** (100% loading from load scale 0.40 to ~1.30; the
field limit never binds anywhere in the sweep with the current machine
sizing). This reverses the "field limit binds at high load" story the
original 3-bus spec anticipated; on this richer network, feeder thermal
capacity is the scarcer resource. Transformer ratings are not constrained
(out of scope; each has its own `sn_mva` pandapower already tracks
separately).

**Local-optimum check** (`run_local_optimum_check()` in `run_experiments.py`):
8 solves of the base case from randomly perturbed starting points (voltage
±0.03 pu, angle ±0.1 rad, seeded). Result: objective range
2438.1241–2438.1241 EUR/h, relative spread 3.5×10⁻¹⁴ (machine precision) —
all 8 starts land on the same point. **This is evidence, not proof, of a
robust/likely-global optimum** — it does not constitute a rigorous global
optimality certificate.

## 6. Incentive schemes

The **OPF's own objective stays cost-minimisation** (`λ_E·P_import + ΣC_g^Q +
π_Q·|Q_import|`), matching ~30 published reactive-market OPF designs surveyed
in Wolgast et al. (2022) — folding a generator's own *profit* directly into
the market-clearing objective is a named, still-open research gap in that
review (their gap A), not standard practice; it needs a bi-level/Stackelberg
formulation, a different and harder problem than this study's scope. Profit
is computed **after** clearing, as a settlement-layer readout — the standard
two-layer "smart market" pattern (system-cost-minimising OPF, then a
separate payment rule on top of its output).

**Six schemes**, crossing two axes from Wolgast et al.'s own taxonomy:
service component (what is paid for) and, for the utilisation leg, pricing
basis (how the price multiplying delivered Q is computed).

| # | Scheme | Formula | Basis |
|---|---|---|---|
| 0 | Regulated obligation (baseline) | `V_g` fixed (PV bus); `Q_g` free, unpriced; `payment = 0` | Statnett fos §15: *"holds an agreed voltage setpoint and has no delivery of reactive power"* |
| 1 | Capacity | `payment_g = π_cap · S_rated,g` — flat, independent of dispatch | Lnett kr/kVAr tariff structure (a capacity/peak basis), reused as a supply-side proxy |
| 2a | Utilisation, nodal | `payment_g = λ_g^Q · Q_g` (own-bus OPF dual × delivered Q) | This work's proposal; identical settlement rule to Potter et al. (payment = d-LMP × Q) |
| 2b | Utilisation, uniform | `payment_g = λ̄^Q · Q_g` (one averaged price for every machine) | Wolgast's "uniform price" category — the single most literature-common pricing basis, though normally set by bid-clearing; we have no bid layer, so this is the average of the OPF's own nodal values, stated as an approximation |
| 2c | Utilisation, area-wise-uniform (AWU) | `payment_g = λ̄^Q_zone(g) · Q_g` (averaged within G's feeder zone) | Wolgast's AWU category — CIGRE MV's two independently-transformed feeders are the zone boundary, a real topological split, not an arbitrary one |
| 3 | Hybrid | `payment_g = π_cap·S_rated,g + λ_g^Q·Q_g` (full stack, nodal pricing, not blended) | Standard real capacity+energy ancillary market structure (e.g. PJM): two separate, additive revenue streams |

Two more were added later, once the settlement code was generalised past the two-feeder split
(`src/settlement.py:THREE_ZONES`, `performance_adjusted_capacity`):

| 2d | Utilisation, AWU 3-zone | same as 2c, but feeder 1 split into near/far by real BFS hop-distance from its head, feeder 2 kept whole | Splits two generators (G1, G2) a 2-zone split blends together despite a real ~24% price difference between them |
| 4 | Performance-adjusted capacity | `payment_g = π_cap · |Q_g|` | Fixes flat capacity's zero-marginal-incentive flaw, but at the real Statnett rate recovers *less* than plain capacity (§7) — a real rate-vs-formula trade-off, not a bug |

**Hybrid turned out to be exactly redundant as a distinct number** — `payment_hybrid = payment_capacity + payment_nodal`
to 4.4e-16 precision, checked directly, not assumed — so it carries no information the two
component schemes don't already have on their own. Its *component* effect is still worth
knowing: the capacity floor materially helps the two chronically underpaid generators (§7),
even though the combined total is just arithmetic.

**Full generator profit** (`src/settlement.py`):
```
profit_g = revenue_p,g + payment_g − service_cost_g − gen_cost_g
revenue_p,g = λ_E · P_g            (active-power revenue — the existing energy market)
payment_g   = the scheme above     (reactive-power revenue — what this study adds)
service_cost_g = C_g^Q(P_g,Q_g,V_g)  (physical loss/degradation cost of providing Q)
gen_cost_g  = c_g^P · P_g          (water value; 0 in every run except the water-value sweep)
```
**Loss of opportunity cost** is reported (`src/settlement.py:loss_of_opportunity_cost`,
`LOC_g = λ_E · max(0, P_max,g − P_g)` when the field limit binds) but is
**not** subtracted a second time in `profit` — `revenue_p` already uses the
generator's actual, possibly-reduced `P_g`, so subtracting LOC again would
double-count the same foregone revenue. LOC is purely a diagnostic: how much
more this generator could have earned running flat-out. Also **not** added to
the OPF objective, per CLAUDE.md §3.4 — it already emerges as a step change
in the dual when the field limit engages.

**Why not a bid-clearing market?** Considered and rejected for this scope.
Per Wolgast et al.'s own 25-year review, bid-based reactive markets are
*"essentially absent from real-world deployment"* — the literature's own
research gaps (A: no autonomous profit-maximising bidder is modelled in most
designs; C: gaming/market-power analysis is largely unaddressed; D:
mechanism design proper is almost never applied) show that doing this
properly is a distinct, larger research problem, not an incremental add-on
two days from a deadline. Every scheme above is administratively set (a rate
or a rule), which is also what >90% of real-world reactive-power procurement
actually is — closer to current practice, not a step away from it.

That said, the gap this leaves is real and was tested directly, not just
argued: `withholding_experiment.py` has a generator misreport its own cost
under nodal settlement — profitable in 84 of 84 trials. And the fleet-aggregate
recovery numbers in §7 hide a generator (G2) that fails individual rationality
even under the best-performing scheme tested — a rational independent owner
has no reason to participate voluntarily at that price. Both are evidence for,
not against, eventually needing the bid-clearing layer above — `game_theory_approach/`
is a first, unreviewed step in that direction (CI-OPF + McCormick convexification);
it self-gates honestly (flags `REJECT_FOR_KKT_MPEC` rather than silently reporting a
bad relaxation) but hasn't had its own adversarial review yet and shouldn't be quoted
as validated.

`π_cap` and the TSO-DSO interface charge `π_Q` both use the **same** Lnett
HV rate (verified against `tariffhefte fra 1. januar 2026`): **40 kr/kVAr
winter (Oct–Mar), 5 kr/kVAr summer (Apr–Sep)**, converted at an
**[ASSUMED, not live-verified]** FX rate of 11.5 NOK/EUR. This is a
withdrawal tariff charged to consumers, reused here as an upper-bound proxy
for the value of reactive supply — no verified Norwegian rate exists for
paying a distribution-connected generator. Flagged, not hidden.

## 7. Results — see `CASE_STUDY_AND_METHODOLOGY.md` for the current, full-year study

**Everything below this line is the original, smaller-sample study, kept for provenance.**
It was superseded by a full 8,675-hour (99.0% of the year), 4-generator run once the Q_ref
infeasibility bug (§4) was fixed — read `CASE_STUDY_AND_METHODOLOGY.md` Part 6 for the
current numbers, not these. The headline differences, so you don't have to cross-reference:

- Capacity recovers 11.4% of real service cost (not 9.7%), nodal 95.7% (not 80.7%), hybrid
  107.0% (not 90.4%) — corrected once Q_ref replaced the infeasible bare Q* reference point.
- Fleet-aggregate 95.7% nodal recovery hides a 0.3%–120.6% spread across the four individual
  generators — not visible in the original study, which only reported fleet totals.
- Reactive-power procurement cost specifically (not diluted by active-power cost) drops 84%
  under coordination, full year — 71,041.93 → 11,244.93 EUR/year.
- Active power's locational price is ~50x flatter across the network than reactive power's
  (CV 0.53% vs 26.62%) — the quantified reason the pricing *basis* choice matters enormously
  for Q and barely at all for P.

What still holds, unchanged, at full-year scale — everything below this point remains true,
just re-verified at 3x the sample size:

- **99.0% solve rate** (8,675/8,760 real hours), skips scattered not clustered.
- **Coordination does not reliably reduce network losses** — it trades losses for reduced
  reactive-import cost at the TSO-DSO interface. It **does** reliably cap peak line congestion
  (47.1% max coordinated vs. 99.75% max baseline, i.e. baseline gets to within a quarter
  percent of a real thermal violation at least once in the year) — congestion management, not
  loss reduction, is the honest "coordination helps" claim.
- **The field-current limit never binds**, any of the 8,675 hours, any of the 4 generators —
  not because the limit is mis-specified (verified geometrically to be the tighter constraint
  at each machine's own rated point) but because this fleet's installed capacity exceeds real
  feeder demand almost every hour of the year. Loss-of-opportunity-cost is therefore correctly
  ~0 throughout — see `MECHANISM_DESIGN_DISCUSSION.md` §2 for why that's the right behaviour.
- **Optimality**: 12 real hours × 5 randomized restarts each agree to a relative spread
  ≤2.5×10⁻¹²; an independent differential-evolution cross-check agrees with IPOPT to 0.00075%.

### Original scoping results (2-generator / base-case, kept for provenance)

| File | What it is |
|---|---|
| `base_case.csv` | one solve per Q-cost model (free / assumed-Potter / physical-derived) at nominal load |
| `load_sweep.csv` | 120 solves, load 0.4x-1.5x nominal, 0 non-optimal, includes per-generator LOC |
| `sensitivity.csv` | lambda_E in {40, 70, 100} EUR/MWh |
| `water_value_sensitivity.csv` | c^P in {0, 35, 70} EUR/MWh |
| `schemes.csv` | baseline vs coordinated dispatch, settled all 4 ways, with LOC |
| `seasonal.csv` | winter/summer x peak/median hour, real Lnett seasonal tariff ratio applied |
| `local_optimum_check.csv` | 8-start robustness check |
| `figures/fig0_demand_data.png` | the source data: P, Q and implied PF over the measured year |
| `figures/fig_bus_profiles.png` | annual profile for a sample of CIGRE buses under the per-bus real mapping, including the two atypical (holiday-home-like) buses -- the realism check |
| `figures/fig1_capability.png`, `fig2_marginal_cost.png`, `fig3_price_vs_load.png` | the three required figures, now over all 4 generators |
| `figures/fig4_dispatch_split.png` | backup figure (CLAUDE.md SS7): each generator's own Q dispatch across the load sweep, physical-cost case |

Diagnostic, not part of the main study: `explore_lv_case.py` runs the same
machine/OPF/settlement pipeline directly on the CINELDI 50-bus rural grid
itself (real topology, real load, no CIGRE) to test the LV-vs-MV argument in
SS2 empirically. Confirms it: with machines sized to local load it solves
cleanly and shows real capability binding, but needed its own voltage band
(0.90-1.05, not CIGRE's 0.95-1.05 -- a plain power flow with zero local
generation already sits at Vmin=0.9213 on this network) and its own
no-incentive baseline convention (unity power factor, not a fixed voltage
setpoint -- holding several independent voltage setpoints at once proved
jointly infeasible on this small, tightly-coupled network).

**Headline findings (4-generator fleet, thermal limits enforced):**
- **Feeder-1 trunk congestion, not any generator's field limit, is the binding constraint across nearly the whole load sweep** (100% line loading from load scale 0.40 to ~1.30; field limit never binds). See OPF formulation, above.
- **Coordination increases raw network losses by 14.2%** at nominal load (0.5032 → 0.5746 MW) — the *opposite* sign from the earlier 2-generator result (which showed a 12% reduction, in the direction of SysOpt's published 6.8–13.3% finding). Root-caused, not just observed: freeing voltage (rather than pinning it to the Scheme-0 setpoint of 1.02 pu) lets the coordinated OPF push every generator's voltage toward the top of the allowed band (1.05 pu), which **widens each machine's own field-limit envelope** (its radius scales with V) — G3 in particular flips from *absorbing* −0.93 MVAr under the fixed-setpoint baseline to *delivering* +2.01 MVAr once free. That extra reactive power flowing through the network raises total I²R losses even though it lowers total system cost. Confirmed not to be a "chasing free energy" artefact: the sign holds (and worsens) across a water-value sweep from 0 to λ_E. **The correct, general claim is "coordination minimises total system cost," not "coordination minimises losses" — losses are one term in that cost and can rationally go either way** depending on how much local capacity is available to trade off against them. Worth stating plainly on the slide: this is a more honest and more general finding than the narrower one it replaces.
- Derived cost (Scheme 2a, unconstrained regime) gives reactive prices 0.09–0.23 EUR/MVArh across the λ_E sensitivity -- inside Wolgast et al.'s cited "<1% of active price" rule of thumb. Potter's assumed `0.1*lambda_E` coefficient gives exactly 10%, an order of magnitude above it.
- **Case D (Norwegian deadband, symmetrically extended to generation) prices the same physically-costly dispatch at ~0.001 EUR/MVArh** — effectively zero — against Case B's 0.16 EUR/MVArh at the identical operating point. Direct, numeric demonstration of CLAUDE.md's deadband claim using Lnett's actual verified 30% threshold, not a hypothetical.
- Pricing basis (2a nodal vs. 2b uniform vs. 2c AWU) changes each generator's *payment* materially (e.g. G4: nodal 0.17, uniform −0.13, AWU −0.07 EUR/h at nominal load) while dispatch is identical across all three — pricing basis is a pure distributional choice once Scheme 2's service component is fixed, exactly what the two-axis taxonomy predicts.
- Real Lnett seasonal ratio (8:1 winter:summer at HV) carries directly into the capacity/hybrid payment: 76.5 -> 9.57 EUR/h between winter and summer peak hours (4-generator fleet).
- Network-wide winter:summer active-demand ratio from the real per-bus mapping: 1.647 -- the right direction and a plausible magnitude for Norway's electric-heating-dominated seasonal pattern (SS3).
- One seasonal point (summer, median load) is a genuine, reported infeasibility: pinning G3 and G4 -- both on feeder 2 -- to the same fixed voltage setpoint simultaneously has no solution at very light load (their AVRs conflict). Skipped and logged explicitly rather than silently included; a real illustration of the fixed-setpoint baseline's own fragility, and if anything an argument *for* coordinated Q dispatch, which has no such failure mode.

## 8. Known open items -- not yet done

- FX rate (11.5 NOK/EUR) not live-verified.
- Transformer thermal limits not enforced (each carries its own pandapower `sn_mva`; only `net.line` current is constrained).
- The LV diagnostic (`explore_lv_case.py`) still uses the original 2-generator, pre-Karekezi machine parameters -- not yet updated to match `run_experiments.py`'s 4-generator fleet.
- `game_theory_approach/` (bilevel/CI-OPF exploration, built separately) has not had its own adversarial review -- don't quote numbers from it.
- Two citations weren't independently re-verified in the most recent pass: the 0.86
  leading-power-factor grid-code figure (de Brito et al. 2025) and the Lnett tariff numbers
  (checked against the primary tariff sheet in an earlier session, not re-checked since) --
  everything else in `CASE_STUDY_AND_METHODOLOGY.md`'s citation table was checked directly
  against the source PDF this pass, these two weren't.
- Placement experiment only covers a 4-month sample (2/3/4-generator fleets x 7 bus layouts);
  a full-year rerun wasn't done given how much slower it is than the pricing-scheme run alone.

Resolved since the paragraphs above were written, kept here as a change log rather than
silently deleted: the 8760-hour annual integration now exists (`run_fullyear_pricing.py`,
§9); the network diagram is regenerated from the actual loaded topology rather than
pandapower's auto-layout (`scripts/make_network_diagram.py`); and the loss-increase
mechanism (§7's "coordination increases losses" line) is now understood as one symptom of
the more general and more defensible finding -- coordination minimises total system cost,
and losses are just one term in that cost that can rationally go either way.

## 9. Reproduce

```bash
pip install -r requirements.txt
pytest tests/ -q                          # 22 tests
python run_experiments.py                 # base case, sweep, sensitivity, schemes, figures 0-4
python run_monthly_analysis.py --water-value   # the original 2,915-hour real-data study (~1 hour)
python analyze_waterval_results.py        # 7 diagnostic figures from that study
python verify_with_metaheuristic.py       # independent differential-evolution optimality cross-check
```

**The current, full-year study** (what `CASE_STUDY_AND_METHODOLOGY.md` and `KEY_FINDINGS.md`
are built from) needs one more run, and it's slow enough on a laptop that it's worth doing on
a second machine if you have one — see `run_fullyear_pricing.py`'s own comments for what it
solves (two AC-OPFs, baseline and coordinated, times 8,760 hours):

```bash
python run_fullyear_pricing.py            # writes results/pricing_mechanisms_fullyear.csv (~1.5-2h, 12 workers)
python placement_experiment.py            # generator-siting sensitivity, 7 layouts x 4 months (~3.5h, 12 workers)
python scripts/make_network_diagram.py    # results/figures/network_diagram.png
python scripts/make_slide_figures.py      # recovery-by-scheme, recovery-per-generator, dispatch-by-machine
python scripts/make_system_cost_figure.py # results/figures/fig_system_cost.png
python scripts/make_p_vs_q_figure.py      # the active-vs-reactive locational-pricing figures
python withholding_experiment.py          # the 84/84 gameability check under nodal settlement
```

The `scripts/` ones need to run from the repo root (they import `run_experiments`/`src.*` by
adding the parent directory to `sys.path`, same as any other script here) — `results/figures/`
paths are all relative to wherever you invoke Python from, not to the script's own location.

The CINELDI dataset subset actually used (`data/raw/cineldi_lv/dataset/50_bus_rural_reference_grid/`)
is included in this repo for reproducibility; the other three grid variants
in the same Zenodo release are not used by any code here and are excluded to
keep the repo lean (their DOI is in §3 if needed).
