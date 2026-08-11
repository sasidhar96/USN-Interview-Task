# Design notes — incentivising reactive power from dispatchable hydro

Working document. Records what the study is, what is verified, and what is still
an assumption. Supersedes `IMPLEMENTATION_PLAN.md` (five-bus reduction, deleted).

---

## 1. The question

> How can reactive power from dispatchable hydro be incentivised in an
> Arctic/Nordic system?

This is **mechanism design**, not "build a market". A bid-based market is one
option, and per Wolgast et al. (2022) it is the option that is *"essentially
absent from real-world deployment"*. The deliverable is a baseline plus five
incentive schemes (six total, see SS5), compared on one network of four hydro
units, each answering: what does the generator do, what does the system pay,
and would the generator participate.

## 2. What Norway actually does — verified 2026-08-10

### 2.1 DSO level (Lnett)

Reactive power is **charged on withdrawal**, never paid on supply.

- Basis: **highest reactive withdrawal in the month** (a capacity charge, kr/kVAr,
  not an energy charge).
- Deadband: *"Det betales bare for den del av reaktiv effekt som overstiger 30 %
  av den aktive effekten"* — only the portion above **30 % of active power** is
  charged. tan φ = 0.30 → **cos φ ≈ 0.96**.
- Seasons: winter Oct–Mar, summer Apr–Sep.

Rates, kr/kVAr (winter / summer), tariffhefte 1 Jan 2026:

| Level | Rate |
|---|---|
| High voltage | **40 / 5**, and 30 / 4 |
| Low voltage | **85 / 25**, and 80 / 20 |
| Regionalnett (withdrawal) | 40, charged only in the hours Lnett is itself charged against sentralnettet |

Seasonal ratio is 8:1 at HV but ~3.4:1 at LV — do not quote 8:1 as general.

Source worked example: 500 kW active → 150 kVAr free; measured 250 kVAr → pay
100 kVAr × 40 kr = 4000 kr that month.

### 2.2 Transmission level (Statnett)

- Reactive power is a paid **system service** under the system operation
  regulation, fos §15.
- **In normal operation a plant holds an agreed voltage setpoint and delivers no
  reactive power**, keeping capability in reserve for disturbances. This defines
  the no-incentive counterfactual.
- Charging side: 90th percentile of the quarter's hourly reactive exchange,
  highest quarterly value. Capacity basis.

### 2.3 Grid code

Maximum leading (underexcited) power factor **φ_lead^max = 0.86**, per de Brito
et al. (2025). Replaces the invented 0.75·V²/X_s underexcitation margin.

### 2.4 The gap this study addresses

Norway charges reactive **withdrawal** and pays for reactive **capability at
transmission level**, but has no mechanism that pays a distribution-connected
hydro unit for reactive **supply**. NC RfG explicitly leaves reactive capability
for type-B units (≤ 50 MW) to national discretion — so this is a live policy
choice, not a settled one.

## 3. Nearest published work

**de Brito, Baltensperger & Uhlen (NTNU), CIGRE Trondheim 2025, paper 1120** —
hierarchical voltage control on a 21-bus 132 kV Norwegian subsystem.

Their TVR layer is an interior-point OPF:

```
min_{Q_G, V}  Σ_(i,j)∈M ( P_ij + P_ji )        (total active power loss)
s.t.          g(u,x) ≤ 0,   h(u,x) = 0
```

with P_G,k = P⁰_G,k + K_p,k·Δf (active power set by governor droop, not
optimised), Q limits, and an apparent-power limit √(P² + Q²) ≤ S_max.

**No cost function, no price, no settlement, no market.** Purely technical loss
minimisation. That is precisely the gap: they show reactive power *can* be
coordinated in the Norwegian grid; nobody has shown how to *pay* for it.

Their own remark: an SVR prototype ran in the Southern Norway control centre in
the 2000s and *"around 20 years later, no innovation nor concrete expansion upon
this idea has been put into practice in the country."*

## 4. Formulation

### 4.1 Decision variables

| Symbol | Role |
|---|---|
| `P_g`, `Q_g` | **controls** — what the operator chooses |
| `V_i`, `θ_i` | **state** — determined by the balance equations |
| `P_import`, `Q_import` | grid interface |

`V, θ` are not extra freedoms. A power flow solves for them given fixed `P_g, Q_g`;
an OPF hands both to the solver and enforces the balance as equality constraints.
Their presence is what yields a separate active and reactive price **per bus** —
2·n_bus balance equations, 2·n_bus duals. A copper-plate model has one balance,
one dual, and therefore cannot price reactive power at all.

### 4.2 Objective

```
min  λ_E · P_import  +  Σ_g C_g^Q(P_g, Q_g, V_g)  +  π_Q · f(Q_import)
```

Losses are inside `P_import` — no separate loss term, which would double-count.
Generator profit is **not** in the objective; it is computed after clearing.

### 4.3 Constraints

AC power balance at every bus; `0.95 ≤ V ≤ 1.05`; stator circle; field circle
(centre `(0, −V²/X_s)`, radius `V·E_f,max/X_s`, with `E_f,max` derived from the
nameplate power factor); underexcitation at the 0.86 leading grid-code limit;
`P_min ≤ P_g ≤ P_max`; slack angle fixed.

### 4.4 Why an exact non-convex AC OPF

Potter convexifies (current-injection + McCormick) to get a global guarantee and a
distributed algorithm, at the cost of an unquantified relaxation gap (his
limitation #3). Our cost function is a machine loss curve that the McCormick route
could not carry. We keep exact physics and give up the global guarantee,
mitigated by warm-starting from a power flow and replaying every solution in
pandapower. Stated as a limitation, not hidden.

## 5. Schemes to compare

Six, final (`src/settlement.py`): 0 baseline, 1 capacity, 2a/2b/2c utilisation
at nodal/uniform/area-wise-uniform pricing, 3 hybrid (full stack of 1+2a).
Profit is computed post-clearing as `revenue_p + payment − service_cost −
gen_cost` (LOC reported as a diagnostic, not subtracted — see README §6 for
why subtracting it too would double-count against `revenue_p`). A
bid-clearing market was considered and rejected for this scope: Wolgast et
al.'s own review calls bid-based reactive markets *"essentially absent from
real-world deployment,"* and modelling an autonomous profit-maximising
bidder is itself one of their named open research gaps, not an incremental
extension.

| # | Scheme | Norwegian basis | Model |
|---|---|---|---|
| **0** | Regulated obligation | Statnett fos: fixed agreed voltage setpoint; Lnett: free below tan φ 0.30 | `Q_g` not optimised — machine holds a voltage setpoint |
| **1** | Capacity / availability payment | Lnett kr/kVAr on monthly peak | pay on peak Q capability provided |
| **2a/b/c** | Utilisation, nodal / uniform / area-wise-uniform | none — the proposal; AWU zones are CIGRE MV's two independent feeders | pay `price × Q`, cost derived from machine physics |
| **3** | Hybrid | — | 1 + 2a, stacked not blended |

## 6. Evaluation metrics

Technical: total active loss; min/max bus voltage; voltage deviation from
nominal; reactive import at the interface; capability headroom used.
Economic: system cost; payment per machine; service cost; **profit** (the
participation test); cost of no coordination (0 → 1, 0 → 2).

## 7. Open assumptions — must stay on the limitations slide

- `k_f` (field loss coefficient) is not published; chosen to give the two machines
  different loss slopes. Representative, not measured.
- Machine ratings scaled to the CIGRE MV feeder; cos φ and `X_d` follow SynGenLib's
  own test machine (30 MVA, cos φ 0.9, X_d 1.1).
- Round-rotor approximation, `X_d = X_q`.
- Lnett rates are *withdrawal* tariffs used here as a proxy for the value of
  supply. Defensible as an opportunity cost to the DSO; not the same thing.
- Capacity (kr/kVAr on peak) and utilisation (EUR/MVArh) are different units.
  Both conventions are reported; see §8.
- Single snapshot per scenario, no water value.

## 8. Unit convention

Reported **both** ways, deliberately:
1. **Peak-hour snapshot** — in a single period the marginal cost of one more kVAr
   of peak *is* the capacity charge, so kr/kVAr and EUR/MVArh coincide.
2. **Annualised** — utilisation payments accumulated over representative hours,
   compared against kr/kVAr-year.

They will not agree, and the size of the disagreement is itself a result: it
measures how much a capacity-based tariff misprices a service whose cost is
driven by utilisation.
