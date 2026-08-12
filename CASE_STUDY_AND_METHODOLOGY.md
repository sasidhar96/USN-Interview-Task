# Case Study, Methodology and Results — Full Reference Document

**Purpose of this file:** a single, complete, source-linked account of everything in this
project — the network, the data, the generator physics, the optimization problem, the
pricing schemes, the solver, and the full-year results — written so that every claim is
either **cited to a primary source** or **explicitly marked as an assumption**, with the
reasoning behind that assumption stated. This is the source document for the interview
slide deck; every number quoted on a slide should trace back to a section here.

Companion figures: `results/figures/network_diagram.png` and the standalone slide figures
listed in the appendix at the end of this file.

---

## Part 0 — Why this project exists (Nordic / Norwegian motivation)

### 0.1 Why reactive power needs its own price signal

Three structural properties make reactive power (Q) different from active power (P) as
an economic good, and explain why it has never been priced the way P is:

1. **It is local and effectively non-tradeable.** Transporting Q consumes Q — moving it any
   distance through an inductive network absorbs part of what you're moving. Every voltage
   zone has to source its own; there is no meaningful system-wide Q price the way there is
   a system-wide (or zonal) P price.
2. **The buyer is a monopsonist.** In any given local network, the system operator (TSO or
   DSO) is the only entity that needs to procure Q for voltage control. Competitive
   auction-market theory assumes many buyers; it doesn't transfer cleanly. This is a
   mechanism-design problem, not a standard auction-design problem.
3. **It is invisible to the existing wholesale price signal.** Nordic and most wholesale
   electricity markets clear on a **DC power flow** approximation (used for LMP/day-ahead
   clearing), whose defining simplification — voltage magnitudes fixed at 1 pu, no line
   reactive losses — makes the reactive-power terms **structurally drop out of the
   formulation**. This is not an oversight in market design; it is a direct consequence of
   the approximation that makes the clearing problem convex and tractable at wholesale
   scale. Reactive power has no price because the model used to set prices cannot see it.

**The result:** reactive power has historically been procured **administratively** —
generators obliged by grid code to supply it, cost socialised into transmission tariffs —
which works while providers are few, large, and centrally dispatched, and the need is at
transmission voltage. That arrangement is what this project examines the alternative to.

### 0.2 Why Norway specifically

Norway is not the generic "declining synchronous capacity, rising inverter-based
generation" story that motivates most of the reactive-power-market literature (which is
largely written with thermal/wind-dominated systems in mind). Norway's version of the
problem is different, and sharper in one specific way:

- **~89.9% of Norwegian electricity generation is hydropower** — 145.5 TWh of 161.8 TWh
  total in 2025 (Statistics Norway, SSB, verified directly from the published national
  electricity statistics table this session). Norway is not losing synchronous, dispatchable
  capacity; if anything it has more of it, proportionally, than almost anywhere else in
  Europe. Hydro's marginal cost is **water value** — the intertemporal opportunity cost of
  stored water in a reservoir, not a fuel cost — and with ~87 TWh of reservoir storage
  against ~157 TWh annual output, this is a flexibility-rich system, not just an exporter.
- **The reactive-power problem is therefore not "who provides it" (plenty of dispatchable
  hydro exists) but "is it priced, and is it in the right place."** Norway's own real
  compensation mechanism (Statnett, forskrift om systemansvaret §15 — verified directly
  from the primary source PDF this session, see §5 below) pays a **fixed capacity rate**
  to plants ≥10 MVA on the regional/transmission network, plus a rarely-triggered variable
  payment — and nothing at all to smaller, distribution-connected generation. That gap —
  a real, dispatchable, low-marginal-cost resource that is unpriced below the 10 MVA
  threshold — is precisely the population this study's 4-generator fleet (3–8 MVA) is
  built to represent.
- **The broader system context**, for framing: Norway's growth in distributed generation —
  smaller hydro, and increasingly rooftop/ground PV — creates the same reverse-power-flow
  and local-voltage-rise problem that inverter-heavy systems elsewhere face, just later and
  at smaller scale. The conventional "obligation-based, centrally dispatched" model of
  reactive power procurement does not extend cleanly to a future with many small,
  independently-owned distributed sources — coordinating and fairly compensating them is
  exactly the TSO–DSO coordination problem the CoordQ project (which this task supports)
  exists to address. This project is a **miniature, quantified instance of that problem**:
  a handful of independently-priceable hydro units on a real distribution benchmark,
  studied under real demand, as a tractable first step before the harder problem of many
  small, heterogeneous, privately-costed DERs.

### 0.3 What this project deliberately does and does not attempt

This is stated plainly, up front, because it shapes every modelling choice below:

- **This is a centralized, cost-based dispatch study**, not a market-clearing/bidding
  study. The AC-OPF assumes each generator's true physical cost is known (derived from
  machine physics, §3), and finds the cost-minimal dispatch. Settlement (§6) is then
  computed for that same fixed dispatch under several payment formulas. This answers "how
  should you pay generators for a cost-minimal outcome," not "what happens when generators
  strategically bid." §8 discusses exactly what would be needed to extend to the latter.
- **This is single-period, hourly-resolution, not real-time.** Every result uses real
  measured hourly demand (§1) solved as an independent AC-OPF per hour — an "hourly
  operational clearing" framing, explicitly not a live/SCADA-connected system.

---

## Part 1 — The case study: network and demand data

### 1.1 Network topology — CIGRE MV benchmark

**Source:** the CIGRE Task Force C6.04.02 medium-voltage distribution network benchmark
(CIGRE Technical Brochure 575, *Benchmark Systems for Network Integration of Renewable and
Distributed Energy Resources*), loaded via `pandapower.networks.create_cigre_network_mv()`
— pandapower's own maintained, verified implementation of the published benchmark, not a
hand-built or modified network.

**Topology** (see `results/figures/network_diagram.png`, built directly from the loaded
network's own bus/line/switch tables, not a redrawn schematic):

- 15 buses total: one 110 kV upstream slack bus (bus 0) and 14 buses at 20 kV distribution
  level.
- Two independent 25 MVA, 110/20 kV transformers connect the upstream grid to two separate
  feeder heads (bus 1 and bus 12) — meaning the network has **two independently-fed
  feeders**, not one ring.
- 15 line segments, three of which carry **normally-open tie switches** (line 6–7, line
  11–4, line 14–8) — real CIGRE MV reconfiguration points, kept open throughout this study
  so the network operates in its standard **radial** configuration (the benchmark's default
  and the configuration essentially all distribution-network OPF literature uses it in).
- R/X ratio ≈ 0.70 — high relative to transmission lines, the reason voltage/reactive-power
  effects matter more here than they would upstream, and part of why CIGRE MV specifically
  (rather than a transmission-level benchmark) is the right test system for a reactive-power
  pricing study.
- Nominal aggregate load: 44.74 MW / 11.04 MVAr (the benchmark's own published figures).
- Base MVA = 1.0 — pandapower's own default convention for this benchmark, used as-is
  rather than rescaled to a round 100 MVA, since rescaling was independently verified this
  session to be a pure change of units (re-basing the whole OPF to 100 MVA reproduces
  bit-identical prices to 5 decimal places after unit conversion).

**Why this network, not a hand-built one:** CIGRE MV is the standard benchmark the
distribution-level reactive-power pricing literature already uses (chosen specifically to
avoid "is this a realistic network" pushback), and 20 kV is a voltage level at which real
synchronous hydro plants actually connect in Norway — unlike a transmission-level benchmark,
where the reactive-power-pricing question is different (and mostly already served by
existing ancillary-service markets), or a low-voltage benchmark (see §1.3), where there is
no dispatchable synchronous generation to study at all.

### 1.2 Demand data — real Norwegian household measurements (CINELDI)

**Source:** the CINELDI 50-bus rural reference grid dataset (Engan et al., 2025,
*A time-series dataset of household electricity demand and distributed energy resources for
a Norwegian low-voltage grid*, Zenodo record 14528192) — 8,760 real, measured hourly active
and reactive power observations (P and Q) for 21 individual Norwegian households on a real
Lede-network rural distribution feeder.

**Used as a temporal shape, not as a topology** (see §1.3 for why the CINELDI network itself
is not used directly). Each CIGRE MV load bus is assigned a **group** of real CINELDI
household columns, and that bus's hourly demand is the CIGRE benchmark's own nominal load
for that bus, scaled hour-by-hour by that group's real, measured shape.

**Bus grouping rationale** (from `src/case_data.py`'s `CIGRE_TO_CINELDI_GROUPS`, stated
here with the reasoning, not just the mapping):

- CIGRE MV's own nominal loads are extremely skewed: buses 1 and 12 alone account for
  ~89% of total nominal demand (19.84 MW and 20.01 MW respectively); the other 11 buses are
  all under 1 MW.
- A single real household's hourly shape is noisy and spiky relative to what buses 1/12
  represent (many aggregated real customers) — using one household's shape there would
  understate the smoothing (diversity/coincidence factor) that a real aggregate feeder
  exhibits.
- So: the two dominant buses (1, 12) each get **4** real households, **summed** (not
  averaged — summing raw kW across real households is what physical load aggregation
  actually is, and is what produces the realistic smoothing); the next two largest buses
  get **2** households each; the remaining 9 buses (all already under 0.6 MW, close to
  single-household scale) get **1** each. 4+4+2+2+9×1 = 21 — every one of the 21 available
  real households is used exactly once, none reused, none discarded.
- **The specific column-to-bus pairing beyond the group sizes is arbitrary and stated as
  such** — there is no physical correspondence between "household #42" and "CIGRE bus 3";
  only the group *size* (how many households' worth of demand a bus represents) is
  reasoned. This is a genuine, acknowledged limitation of working at this network scale
  (13 load buses, 21 real households) — not something resolvable without a larger network.

**Normalization** — each bus's group series is summed, then normalized against that
**group's own peak apparent-power hour** (shared reference for P and Q), not each series'
independently. Normalizing P and Q independently was an earlier bug (caught by internal
review this session): it multiplies every hour's real Q/P ratio by a constant, physically
meaningless bias, since each series' own peak generally occurs at a different hour. The fix
is a mean-rescale of the reactive scale factor to share the same average as the active
scale factor, plus a 99th-percentile winsorization per group to guard against two CINELDI
households (buses 4, 6) whose reactive-power meters are degenerate (near-zero for most of
the year, so an unwinsorized peak is set by one likely-noisy spike). This is a genuine,
stated source-data limitation, not a code bug — flagged honestly rather than hidden.

### 1.3 Why not use the CINELDI network's own topology

The CINELDI 50-bus grid is a real 230 V low-voltage network — the wrong voltage class and
R/X ratio for this study. Concretely: its peak demand is 114 kW active / 15.6 kVAr
reactive; even the smallest synchronous machine still worth modelling (100 kVA) has ~120
kVAr of field-limited reactive capability at that scale — roughly **eight times** the
whole feeder's peak reactive demand. There is no scarcity to price, so no interesting
reactive-power pricing question exists on that network. Its R/X ratio (~7.5 in LV cable) is
also structurally different from CIGRE MV's ~0.70, changing how voltage responds to
reactive injection. CINELDI is therefore used for its real demand *data*, mapped onto a
network (CIGRE MV) chosen for having the right electrical characteristics and voltage
class for the actual question.

### 1.4 Energy price assumption

**λ_E = 70 EUR/MWh**, used both as the interface (slack) active-energy price and, by
convention (§4.3), as each generator's own active-power cost `c_g^P` (the "water-value
convention"). This anchors to the SysOpt WP4 finding (the immediate predecessor project
this work extends) that used the same 70 EUR/MWh and found an equitable reactive price of
0.28 EUR/MVArh on the Nordic-44 network — the sanity-check reference this study's own
EUR/MVArh figures are checked against, not an independently re-derived Nordic spot price.
**Stated as an assumption inherited from the prior project's convention, not re-derived
from a live Nord Pool series.**

---

## Part 2 — The hydro generator model

### 2.1 Fleet composition — two real, two illustrative

Four generators, deliberately diverse in both size and feeder location:

| Machine | Rated (MVA) | Bus | Feeder position | Parameter source |
|---|---|---|---|---|
| G1 | 8 | 3 | Feeder 1, near head (2 hops) | **Type A — real, cited** |
| G2 | 5 | 10 | Feeder 1, distant (5 hops) | Type B — illustrative |
| G3 | 6 | 13 | Feeder 2 (3 hops) | **Type A — real, cited** |
| G4 | 3 | 14 | Feeder 2, far end (2 hops via feeder 2) | Type B — illustrative |

**Type A (G1, G3) — parameters directly cited to a peer-reviewed source**, verified
against the PDF (not a summary) this session: Karekezi, Melfald, Øyvang & Nøland (2023),
*"Loss Modeling of Large Hydrogenerators for Cost Estimation of Reactive Power Services and
Identification of Optimal Operation,"* IEEE Transactions on Energy Conversion, 38(2),
Tables I–II, their 103 MVA / 11 kV / 500 rpm reference machine:

- $\cos\varphi = 0.90$, $X_d = 1.087$ pu (their salient-pole value; this model uses the
  round-rotor simplification $X_s = X_d$, see §2.3).
- $r_a^{pu} = (P_a^* + P_s^*)/S_{rated} = 276.62\text{ kW}/103{,}000\text{ kW} = 0.0026862$ pu
  — the paper's Table I **combined armature + stray-load loss**, not Table II's standalone
  $R_a=0.002$pu. This distinction mattered: the paper's own stator-loss equation scales the
  combined 276.62 kW figure, not a bare $R_a I_a^2$ term (Table II's $R_a$ is used
  elsewhere in the paper, for a Potier field-current estimate). Using the bare Table II
  value understates stator loss by the missing 70.6 kW stray-load component and puts this
  model's own $Q^\star$ outside the paper's reported range (see §2.4 for the verification).
- rotor loss fraction $= (P_{ex}^* + P_f^* + P_{br}^*)/S_{rated} = 191.66\text{ kW}/103{,}000\text{ kW}
  = 0.001861$ pu.

**Type B (G2, G4) — illustrative, not independently cited.** They use the **same** cited
$R_a$ and $\cos\varphi$ as Type A (no reason to invent a different value for a quantity
already sourced), but $X_d$ is increased and rotor-loss fraction raised ~30%, with **no
second published machine backing that specific combination.** State this plainly if
challenged: Type A parameters are real and traceable to a table in a peer-reviewed paper;
Type B are physically plausible variations on the same machine family, used to give the
fleet genuine cost heterogeneity, not independently verified.

**Bus placement** (3/10/13/14) was itself tested against 6 alternative layouts (2/3/4-gen,
head-of-feeder vs. remote placement) — this is the layout found to have the best combined
feasibility and economic performance; see §7.7.

### 2.2 The loss physics — source, and what was changed

**Primary equations, per unit at terminal voltage $V$:**

$$P_{cu,s} = R_a\,\frac{P^2 + Q^2}{V^2} \qquad\text{(stator/armature copper loss)}$$

$$E_f^2 = \left(V + \frac{X_s Q}{V}\right)^2 + \left(\frac{X_s P}{V}\right)^2,
\qquad P_{cu,f} = k_f E_f^2 \qquad\text{(field/rotor copper loss)}$$

$$P_{loss}(P,Q,V) = P_{cu,s} + P_{cu,f} + P_{const}$$

**Source and verification, precise this time — not a general claim.** This model was
checked directly against the *installed* `syngenlib` package (Melfald, Øyvang & Mishra —
the group whose loss-cost modelling this project builds on), reading its actual source
this session rather than relying on a prior summary:

- `syngenlib/archive/pyomo_generator_loss_model.py` — an **archived, already-Pyomo-native**
  version of syngenlib's generator model — contains the identical field-EMF expression,
  term for term:
  `E_q_2_calc = V_g_pu**2*((1 + x_d*Q_g_pu/V_g_pu**2)**2 + (x_d*P_g_pu/V_g_pu**2)**2)`
  — algebraically identical to $E_f^2$ above. This file is explicitly what `src/machine.py`'s
  own docstring says it follows.
- Its stator loss constraint: `P_loss_stator = P_s_star_pu * I_a_2_pu * S_rated`, with
  `I_a_2_pu = (P^2+Q^2)/V^2` — the same $R_a(P^2+Q^2)/V^2$ shape.
- Its rotor loss constraint: `P_loss_rotor = P_r_star_pu * E_q_2_pu / E_q_nom^2 * S_rated`
  — the same $k_f E_f^2$ shape, with $k_f = P_r^{*}/E_{q,nom}^2$ (syngenlib keeps the
  nominal-loss-fraction and normalization as two separate constants; `machine.py` folds
  them into a single calibrated $k_f$ — same physics, different packaging).
- **One thing found and deliberately not carried over**: that same archived file's
  `exciter_constraint` — `(Q + V²/x_d)² + P - (E_q_max·V/x_d)² <= 0` — has `P` appearing
  un-squared next to a squared term, which is dimensionally inconsistent with a circular
  field-current limit (it should be $P^2$). This looks like a bug in syngenlib's own
  archived file, not a deliberate design choice; `src/machine.py`'s own field-limit
  constraint (§2.4) is a correct, dimensionally-consistent circle and does **not**
  reproduce this. Noted here rather than left silent, since finding and not blindly
  copying a bug in the reference implementation is itself part of the verification story.

**What had to change, and precisely why**: syngenlib's *primary, actively-used* runtime
path (`syngenlib/models/generator_calculation_model.py`) computes results by calling
`scipy.optimize.root(...)` on a generator+step-up-transformer equivalent circuit expressed
in **complex numbers**, with `if/else` branching on limit validity and `nan` sentinels for
infeasible operating points. **None of this is usable inside a Pyomo/IPOPT NLP** — IPOPT
needs closed-form, real-valued, everywhere-differentiable algebraic expressions it can
symbolically differentiate; it cannot call out to an external nonlinear solver, branch on
`if`/`nan` mid-evaluation, or differentiate complex-valued expressions. `src/machine.py`
re-derives the *same physics* (verified above, term for term, via syngenlib's own archived
Pyomo-native file) as pure closed-form real-valued expressions directly in terminal
$P,Q,V$, with no separate transformer sub-circuit — unneeded here since CIGRE MV's own
transformers are already part of the network model being solved.

**Deliberate simplification, stated plainly**: this is a **round-rotor** approximation
($X_s = X_d$). The Karekezi et al. source machine is salient-pole ($X_d=1.087$pu,
$X_q=0.676$pu — a 38% difference, not small), and its rotor loss is linear-plus-quadratic
in field *current* obtained from a saturated Potier-triangle construction (implicit, not
closed-form), not purely quadratic in EMF. Implementing that fidelity would require an
implicit/root-solve relation inside the OPF — exactly the reason syngenlib's own accurate
model cannot be embedded directly (above). The quadratic-EMF form is closed-form and
differentiable at the cost of that fidelity — declared, not hidden.

**Cross-check against the source paper's own reported operating point** (not just a
structural equation match): with G1's parameters, this model's analytical loss-minimizing
point $Q^\star$ (below) comes out to $-0.191$ pu on the machine's own base, against the
paper's own reported $-0.194$ to $-0.202$ pu (with saturation) and $-0.152$ to $-0.157$ pu
(without saturation — the more directly comparable figure, since this model has no
saturation either). Falls inside the saturated range and close to the unsaturated one; the
residual gap is attributable to the stated structural differences (round-rotor vs.
salient-pole, no saturation), not an error.

### 2.3 The loss-minimizing point is not zero reactive power

$$\boxed{\;Q^\star(V) = -\,\frac{k_f X_s V^2}{R_a + k_f X_s^2}\;}$$

Slightly negative (underexcited) — physically, a small amount of leading (underexcited)
operation reduces field current relative to unity power factor, at the cost of slightly
more stator current; the optimum trades these off. Cost is defined **relative to
$Q^\star$**, not to $Q=0$:

$$C_g^Q(P_g,Q_g,V_g) = \lambda_E\left[P_{loss}(P_g,Q_g,V_g) - P_{loss}\big(P_g,\,Q_{ref}(P_g,V_g),\,V_g\big)\right]$$

non-negative by construction, with a physically meaningful zero-cost point — directly
contradicting the standard practice (in real Norwegian tariffs and most of the literature)
of assuming zero cost inside a power-factor deadband.

**$Q_{ref}$, not bare $Q^\star$ — a real correction made this session.** $Q^\star(V)$ alone
is *infeasible* (below the underexcitation stability floor, §2.4) at every one of this
fleet's four machines' own minimum active-power output — confirmed numerically, not just
suspected. Since three of the four generators sit at their prime-mover floor in the large
majority of real hours (§7.4), this affected the whole study's cost *levels* (not the
dispatch materially — verified via an A/B solve that the fix shifts dispatch by <0.02 MVAr
per generator, a cost-accounting correction, not a redispatch). The fix — smooth
max(floor, $Q^\star$):

$$Q_{ref}(P,V) = \tfrac{1}{2}\Big(\text{floor}(P) + Q^\star(V) + \sqrt{(\text{floor}(P)-Q^\star(V))^2+\varepsilon}\Big)$$

is used everywhere in this document's results; every number below reflects it.

### 2.4 Capability limits

Four constraints per generator, all sourced against syngenlib's own capability-model
structure (§2.2), with one acknowledged simplification:

1. **Prime-mover limits**: $P_{min} \le P_g \le P_{max}$ — the hydro turbine's own real
   operating range.
2. **Stator (armature-current) limit** — a fixed-MVA circle: $P^2+Q^2 \le S_{rated}^2$.
   Simplification, stated plainly: this ignores voltage (a true current limit would be
   $P^2+Q^2 \le (V \cdot I_{a,max})^2$); doesn't affect prices (voltage-only terms cancel out
   of $C^Q$) but does affect any absolute efficiency claim, so none is quoted from this
   figure.
3. **Field (rotor-current) limit** — a circle in $(P,Q)$ centred below the origin:
   $P^2 + (Q + V^2/X_s)^2 \le (V \cdot E_{f,max}/X_s)^2$, exactly matching syngenlib's own
   `exciter_constraint` shape (with the $P^2$ correction noted in §2.2). $E_{f,max}$ and
   $k_f$ are **derived**, not assumed, from $\cos\varphi/X_d/$rotor-loss-fraction at the
   nameplate operating point — picking $E_{f,max}$ by hand tends to make it too generous and
   the limit never binds, which is in fact exactly what happens at this study's real demand
   levels (§7.5) — reported as a finding, not adjusted to force a different outcome.
4. **Underexcitation (stability) limit** — linear in $P$: syngenlib's own
   `_get_stability_limit_pu` gives $Q_{min}=mP+c$ (both $m$ and a voltage-dependent offset
   $c=-V^2/X_s$). `machine.py`'s $\cos\varphi_{lead,max}$-based floor,
   $Q_{min} = -P\tan(\arccos(\varphi_{lead,max}))$, is a **stated simplification of the same
   line** — through the origin, no $c$ term. $\varphi_{lead,max}=0.86$ is the real Norwegian
   grid-code maximum leading power factor (de Brito, Baltensperger & Uhlen, 2025), not an
   invented margin.

---

## Part 3 — The AC optimal power flow

### 3.1 Formulation, term by term

$$\min_{P_g,Q_g,V,\theta}\;\; s_{base}\left[\lambda_E P_{slack} + \pi_Q\sqrt{Q_{slack}^2+\varepsilon} + \sum_{g}\Big(c_g^P P_g + C_g^Q(P_g,Q_g,V_g)\Big)\right]$$

subject to (implemented exactly this way in `src/opf.py::build_model`, verified against the
code, not paraphrased):

- **AC power balance** at every bus, in both P and Q, written as full nonlinear
  polar-form injection equations (not a DC or linearized approximation) — the standard AC-OPF
  balance form used throughout the distribution-level reactive-power-pricing literature
  (e.g., Potter et al. 2023's own convex-relaxed OPF, and the broader Tier-1,
  OPF-duals-as-prices tradition: Dandachi's availability/utilisation split, Zhong &
  Bhattacharya's Expected Payment Function, El-Samahy's generic framework).
- **Voltage limits**: $0.95 \le V \le 1.05$ pu at every bus — the standard EN 50160-derived
  distribution voltage band.
- **Generator limits**: all four from §2.4, one set per machine.
- **Interface (TSO–DSO) reactive-import price**, $\pi_Q\sqrt{Q_{slack}^2+\varepsilon}$ —
  charges reactive exchange **in both directions** at the upstream interface. Without this
  term the upstream grid is an infinite free reactive source and no local capability limit,
  and no local generator, can ever have economic value — this term is what gives local
  coordination any reason to exist at all, not an incidental addition. Sourced from Lnett's
  real HV reactive-power tariff (40 / 5 NOK/kVAr/month, winter/summer — tariffhefte, 1 Jan
  2026) — a **withdrawal tariff repurposed as a proxy for value**, explicitly caveated in
  the code as such, not a real TSO payment rate. §7.6 quantifies how this compares to local
  generator-bus prices.
- **Interface thermal limit**: $P_{slack}^2+Q_{slack}^2 \le s_{interface,max}^2$, the real
  50 MVA combined capacity of the two 25 MVA transformers.
- **Line thermal limits**: $|I|^2 \le I_{max}^2$ at both ends of every line segment
  (matching pandapower's own `loading_percent` convention of checking both ends, since a
  π-model line's from/to currents can differ with line charging).

**What each objective term means**: $\lambda_E P_{slack}$ is the cost of active energy
imported from the upstream grid — since network losses must be supplied from somewhere, and
the slack bus is priced at the same energy rate, this term implicitly prices **all network
losses**, so no separate loss term is needed in the objective (adding one would double-count).
$c_g^P P_g$ is each generator's own active-generation cost (§3.3, the water-value
convention). $C_g^Q$ is the physically-derived reactive-service cost from Part 2. The
interface reactive term is described above. **This is total system cost minimization** — a
social-cost objective, not any individual generator's profit or revenue; profit only enters
later, at settlement (Part 4), computed on top of this already-fixed, cost-minimal outcome.

### 3.2 The price — where the reactive value comes from

$\lambda_i^Q$ — the dual variable (shadow price) on the reactive power-balance constraint
at bus $i$ — is the nodal reactive price, returned directly by the solver from a single
solve:

$$\lambda_i^Q = \frac{\partial C^*_{system}}{\partial Q_{d,i}}$$

$$\text{EUR/MVArh} = -\frac{\text{dual (per unit)}}{s_{base}\text{ (MVA)}}$$

(negation required by the constraint's injection − supply + load = 0 orientation). This is
the standard locational marginal pricing (LMP) construction, extended to reactive power —
the same underlying mechanism real ISOs use for active power, and the same one Potter et
al. (2023) use for distribution-level reactive power (their d-LMP). It is **not** a flat,
administratively-set rate: every bus gets its own price from the same single solve, and a
generator is paid at *its own bus's* price for *its own delivered* Q —
$\text{payment}_g = \lambda^Q(\text{bus}_g) \times Q_g$, nothing more elaborate. Verified
numerically on a real hour in this study: prices genuinely differ by generator bus (e.g.
0.109–0.121 EUR/MVArh across G1–G4 at one representative hour), confirming the pricing
mechanism is real and locational, not a relabeled flat coefficient.

**Unit conversion independently verified**: re-basing the whole problem to 100 MVA
reproduces bit-identical prices to 5 decimal places after unit conversion — this was
flagged early in the project as the single most likely silent bug, and checks out.

### 3.3 System cost, revenue, and profit — and why they are computed separately

**System cost** (the OPF's own objective value) is the total cost of operating the network
for one hour: upstream import cost + local generation cost + reactive service cost. It is
fixed the instant the OPF is solved and **does not depend on which settlement scheme is
later applied** (proven numerically in Part 4 — the same physical cost is recoverable from
every scheme's own accounting columns, to floating-point precision).

**Generator revenue and profit** are a *separate*, later computation (`src/settlement.py`),
per generator:
$$\text{profit}_g = \underbrace{\lambda_E P_g}_{\text{active-energy revenue}} + \underbrace{\text{payment}_g}_{\text{reactive-service payment, scheme-specific}} - \underbrace{C_g^Q}_{\text{physical reactive cost}} - \underbrace{c_g^P P_g}_{\text{active-generation cost}}$$

Under the water-value convention ($c_g^P=\lambda_E$), the active-energy revenue and
active-generation cost terms are numerically equal and cancel — so a generator's net profit
from this OPF is, in effect, driven almost entirely by whether the reactive-service payment
covers the reactive-service cost. This is a deliberate modelling choice (§3.4), not an
artefact.

### 3.4 The water-value convention, and a real solver consequence

$c_g^P = \lambda_E$ (70 EUR/MWh) by default — active generation is costed at the same rate
as the energy price it earns, rather than at zero. This causes real numerical
ill-conditioning: at exactly this value, the linear term in $P_g$ vanishes from the
objective's gradient in the P-direction, leaving it an order of magnitude smaller than the
Q/V-direction gradients. Diagnosed (via targeted IPOPT option sweeps, not guessed) as a
**scaling** problem, not a centrality problem — `mu_strategy=monotone` made no difference,
while `nlp_scaling_method=none` cut a hard-hour failure sample from 25/25 to 11/25 but is
not safe as a global default (it introduces new failures on already-easy hours). **Fix
implemented as a fallback, not a global setting**: try IPOPT's default settings first; only
on failure, retry once with `nlp_scaling_method=none`. Verified to never regress an easy
case.

---

## Part 4 — Settlement: the pricing schemes (post-hoc layer)

### 4.1 The architecture, stated precisely because it is the most important limitation

**Dispatch is solved exactly once per hour**, against the true physical reactive cost
($C_g^Q$). Every settlement scheme below is a **payment formula applied after the fact to
that same, already-fixed dispatch** — this is the standard split in the ancillary-service
literature between a capability/availability market and a utilisation/dispatch market
(Dandachi's split, formalised further in Wolgast et al. 2022's own taxonomy: service
component — capacity / utilisation / hybrid — crossed with pricing basis — nodal / uniform /
area-wise-uniform). **The schemes answer "how should the DSO split payment for an
already-optimal outcome," not "does the payment scheme change generator behaviour."** A
genuine behavioural-response comparison needs a bilevel/best-response reformulation — see
Part 8. This is standard practice in this literature, not a shortcut unique to this project;
solving for a cost-minimal reference dispatch and discussing alternative compensation
schemes over it is exactly how most of the OPF-based reactive-pricing literature (§0.1's
Tier-1 designs) proceeds.

**Proven numerically, not just architecturally**: back-computing (service cost + generation
cost) from three different schemes' own payment/profit columns agrees to
$5.7\times10^{-14}$ EUR — floating-point noise. System cost genuinely does not change
across schemes.

### 4.2 The schemes

| Scheme | Payment formula | Rate source |
|---|---|---|
| **Baseline** (today's Norwegian practice) | Nothing — largest unit holds a fixed voltage setpoint (Statnett fos §15's own description: "holds an agreed voltage setpoint... no delivery of reactive power"); all others run unity power factor (Wolgast et al. 2022: "without payment, operators set inverters to unity PF") | — |
| **Capacity (fixed)** | $\pi_{cap} \cdot S_{rated,g}$ — flat, independent of use | Statnett fos §15, 2024 decision: $B = Y(\text{MVA})\times 250$ NOK/MVA/year, verified directly from the primary Statnett PDF this session. **Caveat, verbatim from the source document: this real mechanism applies only to plants ≥10 MVA on the regional/transmission network — this fleet (3–8 MVA) is below that threshold, which is exactly the gap this project studies, not a mismatch to resize around.** |
| **Nodal (variable)** | $\lambda^Q(\text{bus}_g)\times Q_g$ | This work's own OPF dual, §3.2 |
| **Uniform** | one system-average price × $Q_g$ | Average of the nodal duals across the fleet — an approximation of a real bid-clearing uniform price, stated as such since there is no bid layer here |
| **Area-wise-uniform (2-zone)** | one price per feeder × $Q_g$ | Average nodal price within each of CIGRE MV's two real, independently-transformed feeders |
| **Area-wise-uniform (3-zone)** | one price per zone × $Q_g$, feeder 1 split by real topological hop-distance from its head | Zones defined by BFS over the real line/transformer graph, not an arbitrary redraw |
| Performance-adjusted capacity *(tested, not a headline scheme)* | $\pi_{cap}\times|Q_g|$ | Mathematically a utilisation payment at the *administered* Statnett rate rather than the *marginal-cost* nodal rate — kept as a robustness check, not part of the core comparison below |
| Hybrid *(tested, found redundant)* | Capacity + nodal, stacked | Confirmed **exactly** equal to capacity+nodal summed (max deviation $4.4\times10^{-16}$ across 8,675 hours) — carries no new information over the two component schemes and is not reported separately below |

**The real Statnett variable-payment formula**, for completeness (verified directly from
the primary PDF, not summarized secondhand): when Statnett has issued a specific prior
order requiring high reactive delivery from a ≥10 MVA plant, systematically beyond **+40%
(capacitive) or −20% (inductive) of actual active production**, it pays
$B = k \times S_p \times L$, where $k=0.012$ for capacitive delivery, $k=0.007$ for
inductive absorption, $S_p$ is the previous year's average day-ahead system price, and $L$
is the measured MVArh delivered beyond the threshold. Cited here for completeness of the
real regulatory baseline; not implemented as a scheme in this study since it is
case-by-case and order-triggered, not a standing rate.

### 4.3 The two recovery metrics — precisely defined, not to be conflated

Two genuinely different questions, both computed correctly, and easy to conflate if not
named separately:

- **Service-cost recovery** = $\dfrac{\sum_h \text{payment}_g}{\sum_h C_g^Q}$ — *"is the
  generator paid enough to cover what this actually cost them?"* This is the headline
  metric in the results below.
- **Load-charge recovery** = $\dfrac{\sum_h \text{payment}_g}{\sum_h \lambda^Q(\text{bus})\cdot Q_{demand}(\text{bus})}$
  — *"if the DSO tried to fund generator payments purely by billing loads their own
  reactive consumption at the same nodal price, would it balance?"* Answered directly in
  §7.3: no, not under any scheme tested (1–11% across every scheme this session) — a real,
  separate finding about how the mechanism would need to be funded, not a restatement of
  the service-cost number.

---

## Part 5 — Solver and optimality methodology

### 5.1 Why IPOPT

The AC-OPF above is a **non-convex nonlinear program** (the AC power-flow equations are
non-convex in $(V,\theta)$; the field-limit constraint is a non-convex circle in $(P,Q)$).
IPOPT (Wächter & Biegler) is a primal-dual interior-point solver for general smooth NLPs,
called through Pyomo's `SolverFactory("ipopt")`. It finds a **locally** optimal,
KKT-satisfying point — for a non-convex problem, this carries **no global-optimality
guarantee**, the same limitation essentially every full-AC-OPF solver in this literature
has (the guarantee only survives under a convex relaxation — SOCP/SDP — which this project
does not use, opting for the full, more physically faithful AC formulation instead).

**Parameters/settings used**: default IPOPT tolerances, with `Suffix(direction=IMPORT)` to
extract duals for pricing, and the fallback described in §3.4
(`nlp_scaling_method=none` retried only on a first-attempt failure). Roughly 25 decision
variables per generator-bus-hour (P, Q, V, θ per bus plus per-generator P/Q), solved
independently per real hour — no inter-hour coupling (each hour is a separate, independent
AC-OPF).

### 5.2 Multi-start — what it means here, and the result

**Multi-start**: the same AC-OPF, for the same real hour, solved repeatedly from different
randomized *initial guesses* for the decision variables (voltages, angles, generator
dispatch) — not different problem data. If IPOPT's local search is sensitive to where it
starts, different starts converge to different objective values; if the problem is
"effectively convex" in the region that matters (or the non-convexity doesn't create
competing local optima at these operating points), different starts converge to the same
value. **Result**: 5 randomized starts × 12 real hours, spanning all 4 study months and the
full demand range — all 12 hours agree to a relative objective spread ≤ $2.5\times10^{-12}$,
i.e. effectively identical regardless of starting point.

### 5.3 Differential evolution — an independent, unrelated cross-check

A second, algorithmically unrelated method (gradient-free `scipy.optimize.differential_evolution`,
a population-based metaheuristic with no relation to IPOPT's interior-point algorithm) was
run on the base case. **Result**: agrees with IPOPT to 0.00075%. Neither this nor the
multi-start result is a formal proof of global optimality — but together they are real
evidence against the specific failure mode (a silently-reported, bad local optimum) that
would undermine every other number in this document, checked by two structurally
independent methods, not one method run twice.

---

## Part 6 — Results (full year, 8,675 real hours, 2021, production placement)

**Coverage**: 8,675 of 8,760 possible hours solved (99.0%); 85 hours skipped (solver
non-convergence, tracked and reported, never silently dropped). Every month has near-full
representation — no month thin enough to bias the annual picture.

### 6.1 System-level impact of coordination — figure Panel A

| | Baseline (today, no incentive) | Coordinated (physical-cost dispatch) |
|---|---|---|
| Mean network loss | 0.0426 MW | 0.0449 MW |
| Total network loss, full year | 369.7 MWh | 389.4 MWh |
| Mean max line loading | 30.3% | 28.3% |
| **Worst-case max line loading (any hour, all year)** | **99.75%** | **47.1%** |
| Mean voltage minimum | 1.0173 pu | 1.0244 pu |

**Key finding, stated precisely**: coordination does **not** reliably reduce network
losses — it uses marginally *more* total energy in losses over the year (389 vs. 370 MWh)
— but it dramatically reduces **peak congestion risk**: baseline gets to 99.75% of a line's
thermal limit in at least one real hour of the year (a near-violation of the real network
under today's uncoordinated practice); coordinated dispatch never exceeds 47.1%, all year.
**The honest "coordination helps" claim is congestion management, not efficiency** — this
is the correct framing for the slide, not "coordination reduces losses."

### 6.1a Reactive power procurement — what the system operator actually pays, full year

The sharpest version of "does incentivizing reactive power actually save real money" is not
the whole-system objective (which mixes in active-power cost and dilutes the effect) but
the cost line-item the operator can point to directly: **what it pays to procure reactive
power from the upstream interface**, $\pi_Q \times Q_{slack}$, summed over every real hour
of the year. No figure needed — this is a text finding.

| | Baseline (today, no incentive) | Coordinated (physical-cost dispatch) |
|---|---|---|
| **Total reactive power procurement cost, full year** | **71,041.93 EUR** | **11,244.93 EUR** |
| **Savings** | | **59,796.99 EUR — an 84.17% reduction** |
| **Total reactive power imported from upstream, full year** | **36,384.0 MVArh** | **12,796.2 MVArh** |
| **Avoided import** | | **23,587.8 MVArh — a 64.83% reduction** |

**Coordinating this fleet's reactive power cuts what the system operator pays to procure
reactive power from the grid by 84%, and cuts the physical volume imported by 65%, over a
full real year.** This isolates the reactive-power-specific effect cleanly — it's the
direct, uncontaminated answer to "how much does incentivizing local reactive generation
actually save the system operator," stated in full-year totals, not an hourly average.

For completeness, the broader **total system cost** (including active power, all costs, the
full OPF objective) also favours coordination, but by a much smaller margin once diluted by
everything else in the objective — figure `results/figures/fig_system_cost.png`:

| | Baseline | Coordinated |
|---|---|---|
| Total system cost, full year | 9,081,945.83 EUR | 9,027,698.26 EUR |

**Coordination saves 54,247.57 EUR over the year — 0.5973% of total system cost.** Small in
relative terms because it's diluted by active-power cost, which dwarfs the reactive-power
line item — the procurement-cost framing above is the cleaner, more legible number for the
slide. Mechanistically both numbers trace to the same thing: coordination avoids the
interface price ($\pi_Q$, §6.5) at a rate ~14.5× the local marginal cost.

**Full honesty on the exceptions**: in 360 of 8,675 hours (4.15%), coordinated system cost
was nominally *higher* than baseline's. Checked in detail before reporting the headline
number: the mean excess in those hours is 0.0606 EUR/h (max 0.19 EUR/h across the whole
year), totalling **21.82 EUR** — 0.0052% of that hour's own baseline cost, on average.
This is noise-level, not a real reversal of the finding — most likely near-tied optimal
points where baseline's passively-determined dispatch happens to sit close to the
coordinated optimum for that specific hour (concentrated in April, a shoulder-season month
outside the original 4-month study window, 297 of the 360 hours). Reported here rather than
smoothed over, precisely because it doesn't change the conclusion and shouldn't be hidden.

### 6.1b Active power's locational price barely moves; reactive power's moves a lot

A direct, quantified answer to "does the same locational-pricing argument apply to active
power" — computed from the same OPF solves, since every hour already produces both
$\lambda^P$ and $\lambda^Q$ duals at every bus with no extra computation needed. Figures:
`results/figures/fig_price_variability_p_vs_q.png` (locational variability) and
`results/figures/fig_pricing_basis_sensitivity.png` (the resulting revenue/recovery swing).

| | Active power ($\lambda^P$) | Reactive power ($\lambda^Q$) |
|---|---|---|
| Locational price variability (coefficient of variation across the 4 generator buses) | **0.53%** | **26.62%** |
| Ratio | — | **~50× more locationally variable than P** |
| Fleet revenue/recovery under nodal | 100.0% (reference) | 95.7% |
| Fleet revenue/recovery under uniform pricing | 99.9% (−0.11%) | 64.6% (**−31.1 points**) |
| Fleet revenue/recovery under AWU (zonal) pricing | 99.9% (−0.05%) | 65.6% (**−30.1 points**) |

**Switching active power from nodal to uniform or zonal pricing changes fleet revenue by a
fraction of a percent; the identical switch for reactive power changes recovery by ~30
percentage points.** This is the direct economic consequence of the price-variability
row above — because $\lambda^P$ barely differs bus to bus, *how* you average it away costs
almost nothing; because $\lambda^Q$ genuinely differs bus to bus, averaging it away throws
away real, collectable value.

**Sourcing, precisely**: the underlying mechanism (reactive power/voltage is locally
determined; active power/angle propagates more globally) is established, textbook power-systems
theory — the P-θ/Q-V decoupling behind the classical Fast Decoupled Load Flow (Stott &
Alsac, 1974) — and is the standard justification, in every reactive-power-market paper
consulted for this project (including Potter et al. 2023 and Wolgast et al. 2022), for why
reactive power needs locational treatment at all. It is also indirectly consistent with
real Nordic market design: Norway prices active power **zonally** (5 bidding zones), not
nodally, which is only a reasonable simplification because within-zone active-power price
differences are small — exactly what the 0.53% CV above shows for this network too. **The
specific quantified comparison above (CV of $\lambda^P$ vs. $\lambda^Q$, and the resulting
revenue/recovery sensitivity) was not found replicated this way in any single source
checked this session** — it is original analysis for this project, fully explained by and
consistent with established theory, not a restated literature result. State it that way if
asked, not as "as also shown by Potter et al."

### 6.2 Settlement scheme comparison — figure Panel B

Service-cost recovery, full year, excluding hybrid (redundant, §4.2) and
performance-adjusted-capacity (secondary robustness check):

| Scheme | Mean payment (EUR/h) | Service-cost recovery | Load-charge recovery |
|---|---|---|---|
| Baseline | 0.000 | 0.0% | — |
| Capacity (fixed) | 0.055 | 11.4% | 1.1% |
| **Nodal (variable)** | **0.460** | **95.7%** | 9.2% |
| Uniform | 0.311 | 64.6% | 6.2% |
| AWU 2-zone | 0.315 | 65.6% | 6.3% |
| AWU 3-zone | 0.348 | 72.4% | 7.0% |

**Findings:**
- The **real** Statnett capacity mechanism, applied to this fleet, recovers only 11.4% of
  what it actually costs them to provide reactive service — a direct, quantified
  illustration of the compensation gap this project studies.
- **Nodal pricing gets closest to full cost recovery** (95.7%) — because it is the only
  scheme that pays each generator at *its own* location's marginal value, rather than an
  averaged or flat rate.
- **Finer zoning captures real locational value without full nodal complexity**: AWU
  3-zone (72.4%) outperforms 2-zone (65.6%) — splitting feeder 1 by real hop-distance from
  its head separates two generators (G1, G2) whose real nodal prices differ by ~24% but
  which a coarser 2-zone split averages together. A genuine, quantified argument for zonal
  granularity as a practical middle ground between flat and full-nodal pricing.
- **Load-charge recovery is low everywhere** (1–9%) — even nodal pricing, applied
  symmetrically to loads' own reactive consumption at the same price, would recover only
  ~9% of what's paid to generators. **Reactive-service payment cannot realistically be
  funded from load-side reactive billing alone, under any scheme tested** — a real,
  separate finding about mechanism funding, distinct from the service-cost question above.

### 6.3 The ownership-fairness finding — figure Panels C and D

**The single most important nuance in these results.** Every number in §6.2 is a
**fleet aggregate** — it implicitly assumes one operator pools all four generators'
revenue. If the four generators instead belong to **independent asset owners** (the more
realistic framing for CoordQ — separate hydropower producers, not one utility), the
aggregate number hides a large, real disparity:

| Generator | Type | Rated | Mean \|Q\| delivered | Nodal service-cost recovery |
|---|---|---|---|---|
| G1 | A (real) | 8 MVA | 0.970 MVAr | 93.9% |
| **G2** | B (illustrative) | 5 MVA | 0.084 MVAr | **0.3%** |
| G3 | A (real) | 6 MVA | 1.233 MVAr | 120.6% |
| G4 | B (illustrative) | 3 MVA | 0.122 MVAr | 27.3% |

**Mechanism, not noise**: the cheaper-reactive-cost machines (G1, G3 — Type A, lower $X_d$)
are dispatched for almost all the reactive duty; a price-per-delivered-MVAr scheme
naturally concentrates payment exactly there. G2's owner, under nodal pricing, would
recover essentially **nothing** (0.3%) of their own real reactive-service cost, across a
full real year, while G3's owner is paid **20% more** than their own cost. **This is a
genuine, quantified mechanism-design finding: nodal pricing, exactly as specified, is fair
in aggregate but not fair per owner** — directly relevant to whether a real CoordQ
mechanism needs an equalization/pooling layer if the participating hydro units are
independently owned, which they generally are in the real Norwegian hydro sector.

### 6.4 Capability constraints — do the physical limits ever bind?

- **Field (rotor-current) limit: 0.00% binding, all 4 generators, all 8,675 solved hours.**
  This fleet's installed capacity exceeds what real CINELDI-shaped demand ever asks of it —
  confirmed at full annual resolution, not a sample. Reported honestly as "not reached at
  these parameters," not glossed over.
- **Stator limit: also 0.00%, all year.**
- **Underexcitation limit: G4 binds 21.58% of the year** (G2 essentially never, 0.03%) —
  the one capability constraint that is genuinely live, consistently, across the annual
  cycle. G4 is small (3 MVA) and Type B (higher $X_d$), making its stability floor easier
  to reach.
- **Loss-of-opportunity-cost (the P-for-Q tradeoff)**: implemented as a diagnostic
  (`settlement.loss_of_opportunity_cost`, deliberately excluded from `profit` to avoid
  double-counting, since a reduced $P_g$ is already reflected in energy revenue) — but,
  because the field limit never binds, this is **exactly zero throughout the real data**.
  The tradeoff exists in the model; nothing in this fleet's real operating conditions ever
  triggers it.

### 6.5 Locality has a real, quantified price

$$\pi_Q\text{ (interface, TSO slack)} = 3.478\text{ EUR/MVArh (winter)}\;/\;0.435\text{ (summer)}$$
$$\bar\lambda^Q\text{ (local generator buses, mean of G1–G4)} = 0.134\text{ EUR/MVArh}$$

**Importing reactive power from the upstream interface costs roughly 14.5× more, on
average over the year, than sourcing it locally from the hydro fleet** (roughly 26× in
winter specifically). This is the quantified reason local coordination has economic value
at all — without this price gap, there would be no incentive to use local generation for
reactive support rather than simply drawing everything from the grid.

### 6.6 Generator placement — acknowledged as a real, secondary finding

A 4-month sensitivity (7 layouts, 2/3/4-generator fleets, current vs. head-of-feeder vs.
remote bus placement — full detail in `PLACEMENT_ANALYSIS.md`) found that **placement
affects operational feasibility and locational fairness, not primarily average losses**:

- The current production layout (bus 3/10/13/14) solves 98–100% of real hours at every
  fleet size; a "remote" layout (generators 4–5 hops from the feeder head) solves as few as
  41.8% of hours at 4-gen scale — a real, structural feasibility degradation, not just a
  worse economic outcome.
- Placement changes which generator carries the reactive burden, and therefore how nodal
  payment is distributed — directly compounding the ownership-fairness finding in §6.3:
  where a generator sits and what it costs to run jointly determine how much reactive duty
  it is dispatched for, and therefore how much it is paid.

This project's primary scope is the pricing-scheme comparison, not a placement/siting
study — placement is reported here as a real, acknowledged secondary finding that
reinforces the fairness discussion, not pursued to the same depth as Part 6's core results.

---

## Part 7 — Discussion: what a post-hoc, centralized approach cannot answer, and what would be needed

### 7.1 The honest limit of everything above

Every result in Part 6 answers *"given the cost-minimal dispatch, how should the DSO pay
for it."* It does **not** answer *"would generators actually behave this way if they set
their own prices."* The dispatch in this study assumes each generator's true cost is known
(derived from its own physics, Part 2) and that generators are **cost-takers**, not
strategic bidders. A real market has **independent asset owners who may misreport their
own cost** to increase payment — this is not addressed by a fixed, centrally-computed
dispatch, no matter how the settlement layer is designed on top of it.

**Tested directly, not just argued**: a withholding experiment (`withholding_experiment.py`)
found that misreporting cost was **profitable in 84 of 84 trials** under nodal settlement —
direct, quantified evidence that the current architecture, exactly as specified, is
gameable. This is expected, not a flaw specific to this implementation — it follows
directly from settlement being computed *after* dispatch is fixed, so a generator has no
way to influence the price it faces through its declared cost within this framework, but
would in any real system where declared cost *feeds into* the clearing dispatch itself.

### 7.2 What the next step actually requires: a bilevel / bidding market

To move from *"how do we pay for an already-optimal outcome"* to *"how do we get
independent, self-interested generators to reveal their true cost and participate
willingly,"* the problem needs to become a **bilevel** (or Stackelberg) formulation:

- **Upper level**: each independent generator owner chooses a bid (price-quantity pair, or
  a bid curve) to maximize their own profit, anticipating how the market clears.
- **Lower level**: a market operator clears the submitted bids — e.g. pay-as-bid or
  uniform-price clearing — subject to the same physical AC-OPF feasibility constraints used
  here.

This is substantially harder than the centralized problem in Parts 3–4: the market
operator's clearing problem becomes an optimization *constrained by* the KKT conditions of
each generator's own best-response problem (an MPEC — mathematical program with
equilibrium constraints), which is itself non-convex and generally requires convex
relaxation (e.g. McCormick envelopes on the bilinear terms that appear) to become
tractable at all.

**Preliminary exploration exists in this repository** (`game_theory_approach/`) — a
convexified CI-OPF/McCormick reformulation and a strategic-market simulation, built as a
first step toward this harder problem. It is **explicitly self-gated**: its own dispatch-error
validation check marks itself `REJECT_FOR_KKT_MPEC` when the convex relaxation's dispatch
diverges too far from the true AC-OPF solution, rather than silently reporting a result —
an honest signal that convexification has a real fidelity cost. Its qualitative finding
(strategic bidders can profit from misreporting under the tested mechanisms) is consistent
with, and independently arrived at from, the withholding-experiment result above. **This
module has not yet had a dedicated adversarial review and should not be presented as
validated** — flagged as exploratory future work, not a result.

### 7.3 Why this is genuinely difficult, and why it matters for design

- **Bid-based clearing is possible, but reactive power markets are structurally thin.**
  With only 2–4 generators on a given feeder (this study's own fleet size), a "market" is a
  small-numbers game, not a competitive auction — classical mechanism-design results
  (Myerson–Satterthwaite: efficiency, incentive compatibility, individual rationality, and
  budget balance cannot all be simultaneously guaranteed) directly constrain what any
  bidding mechanism here can promise. This is a known, structural feature of reactive-power
  markets specifically (few local providers, monopsonistic buyer, §0.1), not a solvable
  engineering problem.
- **The many-small-provider case (distribution-connected DERs/inverters) is a distinct,
  harder version of the same problem.** Coordinating a handful of hydro generators (this
  study) is tractable because their costs are physically computable (Part 2) and they are
  few enough to solve for directly. Coordinating hundreds or thousands of small,
  independently-owned inverters requires **privacy-preserving, distributed** optimization —
  no central operator can or should see every individual owner's cost/state — a genuinely
  different computational and institutional problem (this is the TSO–DSO / aggregation
  architecture referenced in §0.2's CoordQ framing: DSO clears locally, reports an
  aggregated flexibility range upward, individual data stays local).
- **Game-theoretic fairness** (whether an equilibrium outcome is fair across asset owners,
  not just efficient in aggregate) is a further, separate question from the individual-owner
  recovery disparity already found in §6.3 under the *centralized* mechanism — a bidding
  market would need its own fairness analysis (e.g., via cooperative-game solution concepts
  such as the Shapley value, or explicit incentive-compatibility and individual-rationality
  proofs for the specific mechanism chosen), not an assumption that competitive bidding
  resolves fairness automatically.

### 7.4 The honest overall framing

> The centralized, physically-costed approach in this document is the correct **first**
> step: it establishes what reactive power actually costs a real synchronous hydro
> generator to provide, shows that this differs by an order of magnitude from the
> assumed coefficient the literature typically uses, and shows precisely how the choice of
> payment mechanism redistributes that already-known cost. It deliberately does not attempt
> to solve the harder, adjacent problem of eliciting true costs from strategic, independent
> participants — that problem is real, it is where the withholding experiment and the
> exploratory bilevel work point, and it is future work, not a gap in the current results.

---

## Part 8 — Assumptions and sourcing summary (quick citation reference)

| Element | Status | Source |
|---|---|---|
| CIGRE MV topology | **Sourced** | CIGRE TB575, via pandapower's verified implementation |
| CINELDI demand data | **Sourced** | Engan et al. (2025), Zenodo 14528192 |
| Bus-to-household grouping (sizes) | **Reasoned** (group *size* justified by CIGRE's own load skew; specific pairing arbitrary, stated as such) | This project |
| G1/G3 machine parameters ($\cos\varphi$, $X_d$, $R_a$, rotor-loss fraction) | **Sourced** | Karekezi, Melfald, Øyvang & Nøland (2023), IEEE TEC 38(2), Tables I–II |
| G2/G4 machine parameters | **Assumed** (illustrative variation on cited Type A values) | This project, stated as such |
| Loss/EMF equations ($E_f^2$, stator/rotor loss shape) | **Sourced**, cross-checked term-for-term | syngenlib (Melfald, Øyvang & Mishra), `archive/pyomo_generator_loss_model.py` |
| Underexcitation grid-code limit ($\varphi_{lead,max}=0.86$) | **Sourced** | de Brito, Baltensperger & Uhlen (2025) |
| Energy price (70 EUR/MWh) | **Assumed**, inherited convention | SysOpt WP4 (predecessor project) |
| Interface reactive price $\pi_Q$ | **Assumed proxy** from a real tariff | Lnett tariffhefte, 1 Jan 2026 (withdrawal tariff, repurposed) |
| Capacity settlement rate (250 NOK/MVA/yr) | **Sourced**, verified against primary PDF this session | Statnett, *Vedtak om levering og betaling for systemtjenester 2024*, fos §15 |
| Statnett variable-payment formula ($k=0.012/0.007$, ±40%/−20% threshold) | **Sourced**, verified against primary PDF this session | Same Statnett 2024 decision document |
| Nordic locational pricing precedent (5 bidding zones) | **Sourced**, standard public knowledge | Statnett / NordPool |
| Norway hydro share (89.9%, 2025) | **Sourced**, verified this session | Statistics Norway (SSB) |
| Reactive pricing mechanism taxonomy (capacity/utilisation/hybrid × nodal/uniform/AWU) | **Sourced** | Wolgast et al. (2022), IEEE Access |
| d-LMP / distribution-level nodal pricing precedent | **Sourced** | Potter et al. (2023) |
| Solver (IPOPT), non-convex AC-OPF, no global guarantee | Standard, well-known limitation | Wächter & Biegler; stated as a limitation throughout Part 5 |

---

## Appendix — figures in this document

- `results/figures/network_diagram.png` — CIGRE MV topology, generator placement, tie
  switches, built directly from the loaded network's own bus/line/switch tables.
- `results/figures/fig_dispatch_by_machine.png` — standalone: which machines actually get
  dispatched for reactive duty (Type A/B), no price axis — slide 3 material.
- `results/figures/fig_recovery_by_scheme.png` — standalone: fleet-aggregate service-cost
  recovery by settlement scheme, including baseline at 0%.
- `results/figures/fig_recovery_per_generator.png` — standalone: per-generator service-cost
  recovery, nodal alone vs. hybrid (capacity+nodal), the ownership-fairness finding (§6.3).
- `results/figures/fig_system_cost.png` — standalone: full-year total system cost, baseline
  vs. coordinated, plus the upstream-reactive-import mechanism (§6.1a, secondary framing).
- `results/figures/fig_price_variability_p_vs_q.png` — standalone: locational price
  variability, active vs. reactive power (§6.1b).
- `results/figures/fig_pricing_basis_sensitivity.png` — standalone: revenue/recovery
  sensitivity to pricing basis, active vs. reactive power (§6.1b).
