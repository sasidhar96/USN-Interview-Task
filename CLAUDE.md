# Reactive Power Pricing for Dispatchable Hydro — What We Built

**Purpose:** an AC OPF that prices reactive power from synchronous hydro generators using a **physically derived** cost function, compared against the **assumed** cost coefficient from the reference literature, and against real Norwegian settlement mechanisms.

**Deliverable:** a public GitHub repo + figures + results tables, supporting a 5-slide presentation.
**Deadline:** submit Thu 13 Aug 09:00.

**Audience for the output:** USN / CoordQ WP4 interview panel (Thomas Øyvang, Sambeet Mishra). Øyvang's group authored the hydrogenerator loss-cost modelling this builds on. Keep it small, correct, and honest about assumptions.

**Status note (this section didn't exist in the original spec):** this document originally described a hand-built 3-bus, 2-generator toy system. The project outgrew that design early — the actual implementation uses a real benchmark network (CIGRE MV) driven by real Norwegian household demand data (CINELDI), a 4-generator fleet, four swappable cost models, and six settlement schemes, validated across a 2,915-hour real-data study. This document has been rewritten to describe what actually exists, not the original toy design. See `RESULTS_ANALYSIS.md` and `TECHNICAL_VALIDATION.md` for the results and validation this spec led to.

---

## 0. The one-sentence thesis

> Potter et al. (2023) *assume* the reactive cost coefficient — $b^Q = 0.1\,b^P$ — citing a FERC observation that reactive prices are often one-tenth of real power prices. For dispatchable synchronous hydro, that coefficient can be **derived from the machine**: incremental copper losses inside the field limit, and forgone active energy on it. Deriving it changes both the reactive dispatch and the resulting price.

**This is no longer just a claim — it's measured.** On this network and fleet, the physically-derived price is ~28× *smaller* than Potter's assumed 0.1×λ_E convention at typical load (0.248 vs 7.0 EUR/MVArh, G1, median load) — not just a different shape, a different order of magnitude. See `TECHNICAL_VALIDATION.md` §4.

---

## 1. Environment

```bash
python >= 3.10
pip install pyomo numpy scipy matplotlib pandas pandapower
# IPOPT solver:
pip install cyipopt          # or: conda install -c conda-forge ipopt
```

`pandapower` is **required**, not optional — the study network is pandapower's built-in CIGRE MV benchmark, and the demand data is loaded via pandas from the CINELDI dataset. `scipy` is used for `differential_evolution` (an independent, gradient-free optimality cross-check against IPOPT — see §10).

`syngenlib` (Melfald, Øyvang & Mishra) turned out to be installed and pinned in `requirements.txt` despite earlier project notes assuming it was unavailable — its loss/capability formulas were cross-checked against `src/machine.py` and confirmed structurally identical.

---

## 2. Test system

**Topology — CIGRE MV benchmark** (via `pandapower.networks.create_cigre_network_mv`). 15 buses, 110 kV upstream via two independent 25 MVA transformers down to a 20 kV distribution level, radial after switches open, R/X ≈ 0.70. 44.74 MW / 11.04 MVAr nominal load. This is the standard benchmark the distribution reactive-power literature uses, and a voltage level at which synchronous hydro actually connects — chosen specifically over a hand-built toy network so the topology itself isn't a source of "is this realistic" pushback.

**Demand — real Norwegian data, not synthetic.** CINELDI 50-bus rural reference grid (Engan et al. 2025, Zenodo 14528192): 8,760 measured hourly P and Q observations from a real Lede-network rural feeder, used as a *shape*, not a topology (the CINELDI network itself is 230V LV — wrong voltage class and R/X ratio for this study; see `src/case_data.py`'s module docstring for why). 21 real household demand columns are grouped and mapped onto CIGRE MV's 13 load buses (`CIGRE_TO_CINELDI_GROUPS`), weighted toward the two dominant buses getting more households summed (physical aggregation smooths the shape, matching real diversity-factor behaviour).

Base MVA = 1.0 (pandapower's own CIGRE MV convention — not the round 100 MVA the original 3-bus design used).

### 2.1 Energy price

| Quantity | Value |
|---|---|
| Energy price $\lambda_E$ | **70 €/MWh** |

Unchanged from the original design: SysOpt WP4 used 70 €/MWh and found an equitable reactive price of 0.28 €/MVArh on Nordic-44 — this remains the anchor for sanity-checking our own €/MVArh numbers.

### 2.2 Generator fleet — G1–G4, two real-cited machine types

Four hydro units, not two — deliberately diverse on **both** capacity and feeder location, a direct miniature of the SysOpt finding that uncoordinated units end up shouldering disproportionate reactive output.

| Machine | Rated | Bus | Feeder | Type |
|---|---|---|---|---|
| G1 | 8 MVA | 3 | 1 (near head) | A |
| G2 | 5 MVA | 10 | 1 (distant) | B |
| G3 | 6 MVA | 13 | 2 (separate transformer) | A |
| G4 | 3 MVA | 14 | 2 (far end) | B |

**Type A (G1, G3) — cited to Karekezi, Melfald, Øyvang & Nøland (2023), IEEE Trans. Energy Conversion 38(2), Tables I–II**, their 103 MVA, 11 kV, 500 rpm reference machine — verified directly against the PDF, not a summary:

- $\cos\varphi = 0.90$, $X_d = 1.087$ pu
- $r_a^{pu} = (P_a^* + P_s^*)/S_{rated} = 276.62\text{ kW}/103{,}000\text{ kW} = 0.0026862$ pu — the paper's **combined** armature + stray-load loss (Table I), not Table II's standalone $R_a=0.002$pu. This mattered: the paper's own stator-loss equation scales the *combined* 276.62 kW figure by $(I_a/I_a^*)^2$, not $R_a I_a^2$ directly (Table II's $R_a$ is used elsewhere, for the Potier field-current estimate). Using the bare Table II value understates stator-side loss by the missing 70.6 kW stray-load component and puts $Q^\star$ outside the paper's own reported range; using the combined figure reproduces it (see §9).
- rotor_loss_frac $= (P_{ex}^* + P_f^* + P_{br}^*)/S_{rated} = (15.88+175.78)\text{ kW}/103{,}000\text{ kW} = 0.001861$ pu

**Type B (G2, G4) — illustrative deviation**, no second real reference machine exists: $X_d$ bumped up, rotor_loss_frac ~30% higher, same cited $R_a$/$\cos\varphi$ as Type A ("no reason to vary a cited number without cause"). **Say this plainly if asked — Type A parameters are real and cited; Type B are illustrative.**

$E_{f,max}$ and $k_f$ are *derived*, not assumed, from $\cos\varphi$/$X_d$/rotor_loss_frac (see `Machine.from_nameplate`'s docstring) — picking $E_{f,max}$ by hand tends to make it too generous and the field limit never binds, which turned out to be exactly what happened anyway at this study's demand levels (§9).

**Active energy cost $c_g^P$** — set to $\lambda_E$ (the water-value convention, not 0), by default in `run_experiments.solve()`. See §4.3.

### 2.3 Load

Real hourly demand, both a scalar sweep (`build_case`, for the load-sweep/sensitivity experiments) and per-bus-real-shape hourly cases (`build_case_from_hour`, for the main monthly study). No synthetic power-factor assumption — actual measured tan(φ), fixed this session after a normalization bug (independent per-bus/per-series peak normalization) introduced a spurious constant bias; see §9.

---

## 3. The reactive cost model — the contribution

**Unchanged from the original design and independently verified this session** (re-derived from scratch by a blind reviewer with no context on this project; matched term-for-term and sign-for-sign).

### 3.1 Machine loss as a function of (P, Q)

Per unit, with terminal voltage $V_t$:

$$P_{cu,s} = R_a\,\frac{P^2 + Q^2}{V_t^2} \qquad\text{(stator/armature copper loss)}$$

$$E_f^2 = \left(V_t + \frac{X_s Q}{V_t}\right)^2 + \left(\frac{X_s P}{V_t}\right)^2, \qquad P_{cu,f} = k_f E_f^2 \qquad\text{(field/rotor copper loss)}$$

$$P_{loss}(P,Q) = R_a\frac{P^2+Q^2}{V_t^2} + k_f\left[\left(V_t + \frac{X_s Q}{V_t}\right)^2 + \left(\frac{X_s P}{V_t}\right)^2\right] + P_{const}$$

Round-rotor approximation ($X_s=X_d$), declared not hidden — real salient-pole machines have $X_d\neq X_q$.

### 3.2 The minimum-loss point is NOT at Q = 0

$$\boxed{\;Q^\star(V) = -\,\frac{k_f X_s V^2}{R_a + k_f X_s^2}\;}$$

Negative — slightly underexcited. For G1 (machine's own base): $Q^\star=-0.191$ pu, inside the Karekezi paper's own reported $-0.194$ to $-0.202$ pu (with saturation) range. Cost is defined relative to $Q^\star$, not zero:

$$C_g^Q(P_g,Q_g,V_g) = \lambda_E\left[P_{loss}(P_g,Q_g,V_g) - P_{loss}\big(P_g,\,Q^\star(V_g),\,V_g\big)\right]$$

Non-negative by construction (verified by test and by an independent re-derivation), physically meaningful zero-cost point, contradicts the standard PF-deadband practice of assuming zero cost inside a band.

### 3.3 Marginal cost

$$\frac{\partial C^Q}{\partial Q} = \lambda_E\left[2k_fX_s + \frac{2\left(R_a + k_fX_s^2\right)}{V^2}\,Q\right]$$

Linear in Q, non-zero intercept, different slope per machine (different $R_a,X_s,k_f$) — this is why the optimiser prefers one machine over another.

### 3.4 Opportunity cost — still no separate term

Confirmed by an independent review of `src/opf.py`: no explicit opportunity-cost term is added anywhere, and none is needed — it emerges automatically from the constrained optimisation. Verified no double-counting anywhere in the objective.

---

## 4. The optimisation problem

### 4.1 Formulation (as actually implemented, `src/opf.py`)

$$\min_{P_g,Q_g,V,\theta}\;\; s_{base}\left[\lambda_E P_{slack} + \pi_Q\sqrt{Q_{slack}^2+\varepsilon} + \sum_{g}\Big(c_g^P P_g + C_g^Q(P_g,Q_g,V_g)\Big)\right]$$

Same power-balance constraints, voltage limits (0.95–1.05 pu), stator/field/underexcitation limits, and prime-mover limits as the original design — **independently re-derived and confirmed correct** by review, including the pandapower→internal bus-index mapping (a subtlety: CIGRE MV has 18 internal `ppc` rows for 15 pandapower buses; a naive submatrix silently breaks the power balance, verified this is handled correctly).

**Additions beyond the original 3-bus spec:**

- **$\pi_Q$ — interface reactive price** (`q_import_price`, EUR/MVArh): charges reactive exchange at the TSO–DSO interface in both directions. Without it the upstream grid is an infinite free reactive source and no local capability limit can ever bind. Sourced from Lnett's real HV tariff (40 NOK/kVAr/month winter, 5 NOK/kVAr/month summer) — a *withdrawal* tariff reused as a proxy for reactive value, not a real payment; caveated in code.
- **$s_{interface\_max}$ — 50 MVA thermal cap** on the two real 25 MVA transformers' combined capacity, both directions on $\sqrt{P_{slack}^2+Q_{slack}^2}$. A unit bug here (per-unit vs. MVA comparison, silently correct only because $s_{base}=1$) was found and fixed this session — see §9.
- **Water-value convention**: $c_g^P=\lambda_E$ by default (§4.3), not 0.
- **Baseline (uncoordinated) convention**: only the single largest machine in the fleet holds a fixed voltage setpoint (1.02 pu); everyone else runs unity PF — root-caused across real hours (all-fixed is frequently infeasible at light load; only-largest-fixed fails only 0.5% of sampled hours). This is "today's practice" for the Scheme-0/Case-0 comparison.

### 4.2 The price

$\lambda_i^Q$ (the dual on the reactive balance at bus $i$) is the nodal reactive price. **Unit conversion independently re-derived from scratch and verified by re-basing the whole problem to 100 MVA — bit-identical to 5 decimals.** This was flagged in the original spec as the single most likely silent bug; it checks out.

```
EUR/MVArh = -dual_pu / s_base_mva
```

(negation required by the injection−supply+load==0 constraint orientation.)

### 4.3 Solver — including a real convergence issue and its fix

IPOPT via Pyomo, `Suffix(direction=Suffix.IMPORT)` for duals, termination condition checked and failures recorded (never silently dropped).

**The water-value convention ($c_g^P=\lambda_E$) causes real ill-conditioning.** At exactly this value the linear term in $P_g$ vanishes from the objective's gradient in the P-direction, leaving it an order of magnitude smaller than the Q/V directions — diagnosed (not guessed) as a scaling problem, not a centrality problem (`mu_strategy=monotone` made no difference; `nlp_scaling_method=none` cut a hard-hour failure sample from 25/25 to 11/25 but is not a safe global default, since it introduces new failures on already-easy hours). **Fix implemented as a fallback, not a global option**: try IPOPT's default settings first; only on failure, retry once with `nlp_scaling_method=none`. Never regresses an easy case.

**Multiple independent optimality checks**, strengthened this session from a single base-case spot check to a real sample:
- Multi-start (5 randomized initial points × 12 real hours spanning all 4 study months and the demand range): all 12 hours agree to a relative objective spread ≤2.5×10⁻¹².
- Differential evolution (gradient-free, no relation to IPOPT's algorithm) on the base case: agrees with IPOPT to 0.00075%.

Neither is a formal global-optimality proof, but together they are real evidence against the specific failure mode (a silently-reported bad local optimum) that would undermine every other number in this study.

---

## 5. The cost models — four, not two

Implemented as swappable strategy objects in `src/cost_models.py`, exactly per the original architecture requirement (switching is a one-line change):

| Class | Case | Formula |
|---|---|---|
| `NoCost` | 0 | $C^Q=0$ — today's practice inside the deadband |
| `AssumedCost` | A | $C^Q = 0.1\,\lambda_E\sqrt{Q^2+\varepsilon}$ — Potter et al. 2023 |
| `DeadbandCost` | D | Free inside a PF-based deadband (0.30, Lnett's own threshold); Case A's rate beyond it |
| `PhysicalCost` | B | $C^Q = \lambda_E[P_{loss}(P,Q,V) - P_{loss}(P,Q^\star,V)]$ — this work |

`DeadbandCost` didn't exist in the original 3-bus spec — added to directly demonstrate the claim that a PF deadband assumes zero cost where the physical model shows a real, asymmetric one, using Norway's actual real consumer-facing deadband structure (applied here to generation, which Norway does not do today).

---

## 6. Settlement schemes — new since the original spec

The original design only asked for a cost *model* comparison (§5). The project grew a second, related axis: given the least-cost physical dispatch (always cleared against `PhysicalCost`), how should a DSO actually **pay** for it? Implemented in `src/settlement.py`, following Wolgast et al. (2022)'s taxonomy — capacity / utilisation / hybrid service component, crossed with nodal / uniform / area-wise-uniform pricing basis for utilisation.

| Scheme | What it pays | Rate source |
|---|---|---|
| 0 baseline | Nothing (uncoordinated fixed-voltage dispatch, §4.1) | — |
| 1 capacity | Flat, per installed MVA, independent of use | Statnett fos §15 (real: 250 NOK/MVA/year); **caveat: this real mechanism only applies to ≥10 MVA transmission-connected plants — this whole fleet is below that threshold, which is precisely the gap this project studies, not something to resize around** |
| 2a/2b/2c variable | price × delivered Q, at nodal / uniform / area-wise-uniform price | This work's own $\lambda^Q$ |
| 3 hybrid | Capacity + variable, stacked (not blended) | Both above |

**Important architectural fact, worth stating plainly if asked**: schemes 1/2a/2b/2c/3 are all *payment formulas* applied to the **same** coordinated dispatch — they answer "how should the DSO split payment for an already-optimal outcome," not "does the payment scheme change generator behaviour." A genuine behavioural-response comparison would need a bilevel/best-response reformulation, out of scope for this deadline; the post-hoc framing is honest and literature-grounded (Wolgast et al.'s own taxonomy treats capacity/utilisation/hybrid as a payment-structure question, not a dispatch-objective question), but don't overclaim it on the slide.

**Cost-recovery accounting** (`load_side_charge`/`cost_recovery`, added this session): checks whether loads are charged enough, at the same nodal prices, to cover what's paid to generators. On the 4-month real-data run: capacity payment recovers **9.7%** of generators' own service cost; nodal utilisation 80.7%; hybrid 90.4%. This is probably the single strongest, most defensible quantified answer to "how should reactive power be incentivized" available right now — the real Statnett rate underpays this population by roughly an order of magnitude.

---

## 7. Experiments actually run

Beyond the original three:

- **Base case** and **load sweep** (40 steps, 0.4×–1.6× nominal) — as designed, all four cost models.
- **Sensitivity**: $\lambda_E\in\{40,70,100\}$.
- **Schemes** (`run_experiments.run_schemes`): base case settled all 4 real ways + cost recovery.
- **Seasonal**: winter/summer peak/median representative hours, season-appropriate Lnett tariff.
- **Full monthly hourly study** (`run_monthly_analysis.py --water-value`): **2,915 of 2,952 real hours solved (98.7%)** across Dec+Jan+Jun+Jul, one full AC-OPF pair (baseline+coordinated) per hour, all settlement schemes, per-generator voltage and binding-constraint flags, cost recovery. This is the main evidence base for `RESULTS_ANALYSIS.md` and `TECHNICAL_VALIDATION.md`.
- **Generator-count comparison**: 2/3/4-generator fleet configurations at representative hours.
- **Multi-start and differential-evolution optimality checks** (§4.3).

**The expected "G1 hits its field limit → price jumps" divergence (original §6, Run 2) does not appear** in the real-data version, and this is now *explained*, not just observed: the field limit genuinely is tighter than the stator limit at each machine's rated point (verified geometrically), but no generator is ever dispatched near its own $P_{max}$ under real demand — installed capacity exceeds real feeder demand most hours. The rule is fine; report "not reached at these parameters," honestly, per this document's own original guidance in §6.

---

## 8. Figures

The original three (`src/plotting.py`, `figure1`/`figure2`/`figure3`) plus `figure4_dispatch_split` and `figure0_demand`/`figure_bus_profiles` (demand-data sanity figures), all still built and correct. **Figure 3's field-limit shading was found to be drawn entirely from non-converged (infeasible) sweep rows** — fixed by filtering to `status=="optimal"` before plotting in both `figure3` and `figure4_dispatch_split`.

Six additional diagnostic figures from the 4-month study (`analyze_waterval_results.py`, `results/figures/waterval_*.png`): dispatch by month, line-loading distribution, loss composition (network vs. machine stator vs. field), avoidable-loss (actual dispatch vs. each machine's own $Q^\star$), settlement scheme payment/cost-recovery comparison, and the Case A vs. Case B price-magnitude comparison.

---

## 9. Repository structure (as it actually is)

```
USN-Interview-Task/
├── README.md
├── CLAUDE.md                        # this file
├── DESIGN.md, IMPLEMENTATION_PLAN.md
├── RESULTS_ANALYSIS.md              # 4-month study results, read this first
├── TECHNICAL_VALIDATION.md          # does the optimization make sense (loss, optimality, economics)
├── requirements.txt
├── data/raw/cineldi_lv/             # real CINELDI dataset
├── src/
│   ├── case_data.py                 # CIGRE MV + CINELDI integration
│   ├── machine.py                   # loss model, Q_star, capability limits
│   ├── cost_models.py               # NoCost / AssumedCost / DeadbandCost / PhysicalCost
│   ├── opf.py                       # Pyomo model, solve, dual extraction, solver fallback
│   ├── settlement.py                # 6 settlement schemes + cost-recovery accounting
│   └── plotting.py                  # figures
├── run_experiments.py               # base case, sweep, sensitivity, schemes, seasonal
├── run_monthly_analysis.py          # the 4-month, 2,915-hour real-data study
├── analyze_waterval_results.py      # diagnostic figures from the 4-month study
├── verify_with_metaheuristic.py     # DE cross-check
├── results/                         # csv outputs + figures/
├── review/                          # 4 independent blind-review reports + synthesis
└── tests/
    └── test_machine.py              # 22 tests, see §10
```

`src/network.py` from the original spec does not exist — superseded by `case_data.py`, since the network is now a real pandapower benchmark rather than a hand-built Y-bus.

---

## 10. Tests

22 tests in `tests/test_machine.py`, extending the original six:

- The original six (Q* negative, loss-minimum-at-Q*, cost non-negative, capability-limit geometry, power-flow residual, unit conversion) — all still present, all pass.
- **`test_q_star_scales_with_v_squared`** — added this session after a mutation-testing pass found 5 of 7 single-token mutations (including $V^2\to V$ in `q_star`, which would silently move every downstream price) survived the entire original suite, because every original test ran at $V=1.0$ where $V$ and $V^2$ are numerically indistinguishable.
- Settlement double-counting check, four-generator fleet solve, deadband cost behaviour, thermal-limit enforcement, cost-model-actually-swaps.

Run: `.venv/bin/python -m pytest tests/ -v` (needs the venv — bare `python`/`python3` on this machine lack the dependencies).

---

## 11. What actually went wrong, and what fixed it

An independent 4-agent blind review (zero shared context, each reading only its own slice of the codebase) found real issues, all fixed and tested this session:

| Issue | Fix |
|---|---|
| `pi_cap` used the wrong rate in one of two call sites (~1400× off) — flipped which settlement scheme looked dominant | Both call sites now use the same, real, Statnett-sourced rate |
| Demand P/Q normalized independently by each series' own peak — introduced a constant, physically-meaningless bias in modelled tan(φ) | Both p_scale and q_scale forced to the same mean, plus winsorized to neutralise a few degenerate near-all-zero reactive channels |
| Figure 3's field-limit shading came entirely from non-converged (infeasible) sweep rows | Filter to `status=="optimal"` before any sweep-derived plot |
| No check on whether loads are charged enough to cover generator payments | Added `load_side_charge`/`cost_recovery`, wired into every settlement path |
| `r_a_pu` used Table II's bare value, silently dropping the paper's stray-load-loss component | Corrected to the paper's combined armature+stray-load figure; $Q^\star$ moved into the paper's own reported range |
| Mutation testing found the test suite blind to a $V\to V^2$ sign error | Added a voltage-sensitivity test |
| `s_interface_max` compared a per-unit quantity against an MVA-documented value — silently correct only because $s_{base}=1$ | Fixed the unit conversion explicitly |
| IPOPT ill-conditioning at $c_g^P=\lambda_E$ (§4.3) | Fallback retry with `nlp_scaling_method=none` on failure only |

Full detail and reasoning in `review/00_synthesis.md` and `review/01`–`04`.

---

## 12. What to report honestly

**Say on the slide:**
- Type A machine parameters (G1, G3) are real, cited, and verified against the source paper; Type B (G2, G4) are illustrative, stated as such.
- Round-rotor approximation on salient-pole machines, single-period study, real (not synthetic) demand data but one representative year.
- The network is a standard, real benchmark (CIGRE MV), not an invented one — but the demand-to-bus mapping (which real households represent which CIGRE bus) is a stated, arbitrary-within-group-size assignment.
- **The field limit never binds at these demand levels** — explained, not glossed over: the fleet's installed capacity exceeds real feeder demand most hours, so no machine is ever pushed near its own rated point. This is itself informative, not a failure.
- **Coordination does not reliably reduce average network losses** (worse in 46% of the 2,915 real hours) — it trades losses for reduced reactive-import cost at the interface. It **does** reliably reduce peak line congestion (max loading 96% baseline vs. 47% coordinated) — that's the honest "coordination helps" claim, framed as congestion management, not loss reduction.
- The real Statnett capacity mechanism recovers only 9.7% of this fleet's actual reactive-service cost — a genuine, quantified illustration of the gap CoordQ exists to close.

**And close with:** the model works because hydro's reactive cost is computable from the machine, and it's now validated three ways — independently re-derived by blind review, cross-checked by an unrelated optimization algorithm, and shown to reproduce a published machine's own reported optimal point. The general coordination problem is harder precisely because the other half — distribution inverters — has heterogeneous, unobservable costs. That is the research direction, and it is what makes the TSO–DSO coupling in CoordQ difficult.

---

## 13. Current status

All experiments in §7 have run; all fixes in §11 are applied and tested (22/22 passing); figures in §8 are generated. Outstanding, lower-priority items (see `review/00_synthesis.md` for full detail, none of them change a headline number):

- Two CINELDI household buses (4, 10) still carry somewhat elevated, residual reactive-demand noise after winsorization — a genuine source-data limitation, not a code bug.
- The stator limit is modelled as a fixed-MVA circle rather than a true current limit (ignores voltage); core loss (~212 kW at rated, larger than modelled rotor loss) is unmodelled — doesn't affect prices (voltage-only terms cancel out of $C^Q$), does affect any absolute efficiency figure, so don't quote one from this model.
- The full 4-fleet-configuration × 4-month sweep (2/3/4-generator comparisons at full hourly resolution, as opposed to representative-hour only) has not been re-run under the corrected code — the single 4-generator configuration has been, and is the basis for all current results.
