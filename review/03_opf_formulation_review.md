# Review 03 — OPF formulation, cost models, experiment driver

**Scope reviewed:** `src/opf.py`, `src/cost_models.py`, and the OPF-relevant parts of
`run_experiments.py`. `src/machine.py`, `src/case_data.py` and `src/settlement.py` were
read only far enough to know the signatures and units they hand to the OPF; they are
reviewed by others and I do not offer verdicts on them.

**Method.** I re-derived the power-flow equations, the objective, the capability
constraints and the per-unit-to-EUR/MVArh conversion from scratch, then checked each
derivation against the code *and* against the solver by running it. Every numerical claim
below is something I executed, not something I inferred from a comment. Several comments
in this code assert that a thing was "verified directly"; I treated all of those as
unverified until I reproduced them myself.

**Headline.** The formulation itself is sound. The power balance, the slack reference, the
pandapower-ppc bus mapping, the dual sign convention and the EUR/MVArh conversion are all
correct, and I confirmed the last two to machine precision. The problems are not in the
maths — they are in what happens to **failed solves** and to **constraint-activity
detection**, and together those two defects manufacture the study's headline result. There
is also one genuine unit bug in the interface constraint that is currently masked by an
accident of the chosen base.

---

## 1. Power flow formulation

### 1.1 My derivation

Standard polar-form AC injection at bus $i$, with $Y = G + jB$ and $\theta_{ik} = \theta_i - \theta_k$:

$$P_i^{inj} = V_i \sum_k V_k \left( G_{ik}\cos\theta_{ik} + B_{ik}\sin\theta_{ik} \right)$$

$$Q_i^{inj} = V_i \sum_k V_k \left( G_{ik}\sin\theta_{ik} - B_{ik}\cos\theta_{ik} \right)$$

and the nodal balance $P_i^{inj} = P_{g,i} - P_{D,i}$, i.e.

$$P_i^{inj} - P_{g,i} + P_{D,i} = 0, \qquad Q_i^{inj} - Q_{g,i} + Q_{D,i} = 0.$$

### 1.2 What the code does

`injection(mm, i, reactive)` (opf.py:214–222) is one function generating both, switching
`sin`/`cos` and the sign on $B$. Unrolling it:

- `reactive=False` → `v_i*v_k*(G_ik*cos(θi-θk) + 1*B_ik*sin(θi-θk))` ✔ matches $P_i^{inj}$
- `reactive=True` → `v_i*v_k*(G_ik*sin(θi-θk) - B_ik*cos(θi-θk))` ✔ matches $Q_i^{inj}$

Diagonal check: at $k=i$, $\theta_{ii}=0$, so $P$ picks up $V_i^2 G_{ii}$ and $Q$ picks up
$-V_i^2 B_{ii}$ — both standard. The constraints (opf.py:233–238) are written exactly in
the `injection − supply + load == 0` orientation I derived. **Correct.**

**Dimensional consistency.** `grid.y` comes from `makeYbus(baseMVA, ...)` so it is pu on
`baseMVA`; `grid.pd/qd` are `ppc["bus"][:,PD]/base`, also pu; `v` is pu; `theta` is
radians (`np.radians(VA)` at init). All four consistent. ✔

**Slack reference.** `m.theta[grid.slack].fix(0.0)` (opf.py:205) ✔, with the slack index
taken from `BUS_TYPE == REF` in the ppc, not assumed to be bus 0. `m.v[slack]` is also
fixed at the power-flow value, which is a modelling choice (infinite upstream voltage
support) and is documented as such at opf.py:206–208. Reasonable.

### 1.3 Bus indexing

This is the part I most expected to find a bug in, and it is **right**, non-trivially so.
pandapower expands 15 CIGRE MV buses into 18 ppc rows (I confirmed: `n pp buses: 15,
n ppc buses: 18`) because of the six line switches. The model is built over the full ppc
bus set and results are mapped back through `ppc_to_pp`, exactly as the module docstring
claims. Taking a 15×15 submatrix of Ybus would indeed have broken the balance silently.
Branch-limit indexing via `net._pd2ppc_lookups["branch"]["line"]` returns `(0, 15)` and
`net.line` has 15 rows, so the claimed ordering invariant holds here.

Two **latent** indexing hazards, neither triggered by the networks actually used:

- `ppc_to_pp = {v: k for k, v in grid.pp_to_ppc.items()}` (opf.py:343) inverts a mapping
  that is not guaranteed injective. Closed bus–bus switches fuse several pandapower buses
  onto one ppc row; the inversion would then silently drop all but one, and
  `baseline.v[b]` in `run_schemes` would `KeyError` for a lost bus. CIGRE MV has zero
  closed bus–bus switches, so this never fires today.
- Out-of-service buses are not excluded. I set bus 11 out of service and pandapower mapped
  it to an *isolated* ppc row (17) with an all-zero Ybus row. The OPF would then carry a
  balance constraint that reduces to `0 == 0` with two free, unbounded variables
  ($V_{11}, \theta_{11}$) — a rank-deficient KKT system and undefined duals at that bus.
  Worth one guard.

- `i_max` ignores `net.line.parallel` and `net.line.df`. Both are 1 on CIGRE MV, so the
  thermal limit matches pandapower's own `loading_percent` today, but it would silently
  under-rate parallel circuits on another network.

**Verdict on Q1: standard, dimensionally consistent, slack correctly referenced, no active
indexing bug.**

---

## 2. Objective function

### 2.1 Written out

From opf.py:279–290, with everything inside the bracket in per unit and $S_{base}$ in MVA:

$$
\min \; S_{base}\Bigg[\;
\underbrace{\lambda_E \, P_{slack}}_{\text{(i)}}
\;+\;
\underbrace{\pi_Q \sqrt{Q_{slack}^2 + 10^{-10}}}_{\text{(ii)}}
\;+\;
\sum_{g\in\mathcal G}\Big(
\underbrace{c^P P_g}_{\text{(iii)}}
+
\underbrace{\mathbb{1}[g \notin \mathcal F]\; C^Q_g(P_g,Q_g,V_g)}_{\text{(iv)}}
\Big)\Bigg]
$$

where $\mathcal F$ = buses with a fixed voltage setpoint or fixed unity PF, and
$C^Q_g$ is the injected strategy object:

$$
C^Q_{\text{assumed}} = 0.1\,\lambda_E \sqrt{Q^2 + 10^{-4}}
$$
$$
C^Q_{\text{deadband}} = 0.1\,\lambda_E \cdot \tfrac12\!\left[e + \sqrt{e^2 + 10^{-4}}\right],
\quad e = \sqrt{Q^2+10^{-4}} - 0.30\,P
$$
$$
C^Q_{\text{physical}} = \lambda_E\left[P_{loss}(P,Q,V) - P_{loss}(P,Q^\star(V),V)\right]
$$
$$
C^Q_{\text{free}} = 0
$$

Units: $S_{base}\cdot$pu → MW or MVAr, times EUR/MWh or EUR/MVArh → **EUR/h** throughout. ✔

### 2.2 The physical cost, in closed form

The code and its tests never write this out, and it is worth writing out because it makes
two properties obvious. With
$P_{loss} = R_a\frac{P^2+Q^2}{V^2} + k_f\!\left[(V + \tfrac{X_sQ}{V})^2 + (\tfrac{X_sP}{V})^2\right] + P_{const}$:

$$\frac{\partial^2 P_{loss}}{\partial Q^2} = \frac{2(R_a + k_f X_s^2)}{V^2} > 0$$

so $P_{loss}$ is a strictly convex parabola in $Q$ with vertex at
$Q^\star = -\,k_f X_s V^2/(R_a + k_f X_s^2)$, and therefore

$$\boxed{\;C^Q_{\text{physical}} = \lambda_E\,\frac{R_a + k_f X_s^2}{V^2}\,\bigl(Q - Q^\star(V)\bigr)^2\;}$$

Two consequences the code does not state:

1. **It is non-negative for every $V$, not just $V=1$.** `test_cost_is_nonnegative` only
   checks $V = 1.0$; the closed form proves the general case. Good news, but it is proved
   here, not there.
2. **It is exactly independent of $P$.** Both $R_a P^2/V^2$ and $k_f X_s^2 P^2/V^2$ cancel
   identically between the two loss evaluations. The code comment at cost_models.py:57
   notes this ("P cancels between the two loss terms") but does not draw the consequence:
   *the generator's active copper loss never enters the objective at all*, only the
   $Q$-deviation part of it.

I also confirmed the marginal-cost identity the pricing test relies on:
$\partial C^Q/\partial Q = \lambda_E\left[2k_fX_s + 2(R_a+k_fX_s^2)Q/V^2\right] = \lambda_E \cdot$ `machine.marginal_loss(q,v)` ✔.

### 2.3 Double-counting audit

I checked every pairing that could double-count:

| Candidate | Verdict |
|---|---|
| Network losses charged twice (explicit $\lambda_E P_{loss}^{net}$ term *and* slack import) | **No.** There is no explicit network-loss term. Losses are paid implicitly through (i), which is the correct treatment. The docstring at opf.py:128–130 says so and it is true. |
| Opportunity cost of backing off $P$ added explicitly on top of the constrained optimisation | **No.** No explicit LOC term in the objective. It can only emerge through the field-limit constraint coupling $P$ and $Q$, which is the correct mechanism. (`loss_of_opportunity_cost` in settlement.py is post-hoc reporting, outside the objective — I did not audit it.) |
| Generator active output paid for twice (once as `c^P P_g`, once as reduced slack import) | **No, but note the sign.** With $c^P=0$ the generator's MW have zero direct cost and reduce (i) at $\lambda_E$/MW, so their *system* value is $\lambda_E$ at the margin. That is internally consistent. |
| Machine internal loss both deducted from the network balance and charged in the objective | **No — the opposite problem.** `m.pg[g]` is the *terminal* injection; machine loss is not withdrawn anywhere in the balance. Combined with the $P$-cancellation above, the machine's own losses are almost entirely **unmodelled**. See issue S2-c. |
| Reactive exchange charged at the interface *and* priced through the machine costs | **No double count**, but term (ii) is not the "symmetric price" its docstring claims. See issue S3-a. |

**Verdict on Q2: no double-counting. One material omission (machine active loss) and one
mis-described term (ii).**

---

## 3. Constraints

All five spec'd constraint families are present and, as far as I can check without
straying into `machine.py`, each does what it claims:

| Constraint | Where | Form | Check |
|---|---|---|---|
| Voltage limits | opf.py:192 | **variable bounds** $0.95 \le V \le 1.05$ | Present. As bounds, not constraints — their multipliers land in `ipopt_zL/zU`, not in `m.dual`. Nodal prices are still correct (bound multipliers enter stationarity), but you cannot report *which* voltage bound binds from the duals you import. |
| Prime mover | opf.py:240 | ranged `(p_min, pg, p_max)` | Present, and a ranged Constraint rather than a bound, so its dual *is* importable. Note it makes every machine must-run at $\ge 0.15 S_{rated}$. |
| Stator | opf.py:243 | $P^2+Q^2 \le S_{rated}^2$ | Present. **Not voltage-scaled**, while the field circle *is* (radius $VE_{f,max}/X_s$). A constant-armature-current limit is $P^2+Q^2 \le (V S_{rated})^2$. Within $V\in[0.95,1.05]$ this is a ≤10% inconsistency between two limits that are supposed to describe the same capability diagram. The formula lives in machine.py; flagging only the inconsistency of the assembled set. |
| Field | opf.py:246 | $P^2 + (Q + V^2/X_s)^2 \le (VE_{f,max}/X_s)^2$ | Present, standard round-rotor field circle. |
| Underexcitation | opf.py:249 | $Q \ge -P\tan(\arccos 0.86)$ | Present. |
| Interface MVA | opf.py:252 | $P_{slack}^2 + Q_{slack}^2 \le S_{max}^2$ | Present, **and dimensionally wrong** — see S1-b. |
| Branch thermal | opf.py:272 | $|I_f|^2, |I_t|^2 \le I_{max}^2$ via $Y_f, Y_t$ | Present and correct in construction; $I_{base} = S_{base}/(\sqrt3 V_{base})$ from the from-bus kV ✔. |
| Angle | opf.py:193 | $-\pi/2 \le \theta \le \pi/2$ | An artificial box that is not part of the physics. Harmless on this feeder (angles are a few degrees) but it can convert a genuinely infeasible case into a spuriously bounded one. |

### 3.1 Redundancy / contradiction for the actual parameters

I evaluated all limits for G1 (8 MVA on the 1 MVA base) and G2 (5 MVA):

```
G1: s_rated=8.00  p_min=1.20  p_max=6.80  Q*=-1.9134 pu (-0.239 machine base)
    underexcitation floor: -0.712 at p_min, -4.035 at p_max
G2: s_rated=5.00  p_min=0.75  p_max=4.25  Q*=-1.3330 pu (-0.267 machine base)
    underexcitation floor: -0.445 at p_min, -2.522 at p_max
```

**The loss-minimising point $Q^\star$ is outside the feasible set below ~40% of rating.**
$Q^\star$ is a constant (at fixed $V$) while the PF floor is a ray through the origin, so
they cross at $P = |Q^\star|/\tan(\arccos 0.86)$ — 40% of rating for G1, 45% for G2. Below
that, `PhysicalCost`'s zero-cost point is unreachable, $C^Q > 0$ everywhere feasible, and
$\partial C^Q/\partial Q < 0$ at the boundary. This is not a bug — it is a real
interaction between two correctly-implemented constraints — but it undercuts the
docstring's claim that the model is "zero at a physically meaningful operating point", and
it should be stated, because it is doing visible work in the results (I observed G4 sitting
exactly on the underexcitation limit at 40% loading, residual 9.5e-9).

Stator vs field: at $P = p_{max} = 0.85$ pu machine base, the field circle allows
$Q \le 0.468$ and the stator circle $Q \le 0.527$ — field binds first, as intended, and
neither is redundant. I confirmed no constraint violations anywhere in the stored
160-row load sweep (checked the underexcitation ray explicitly across all four machines
and all rows: zero violations).

**Verdict on Q3: all present and doing what they claim; two consistency issues
(voltage-scaling of the stator circle; $Q^\star$ infeasible at light $P$) and one unit bug.**

---

## 4. Solver setup and duals

`pyo.SolverFactory("ipopt").solve(m, tee=False, options={"max_iter": 20000})` at
opf.py:312. `m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)` is set at opf.py:291, i.e.
**inside `build_model`, before every solve** — including before the retry, which rebuilds
the model. ✔ Duals are retrievable; I retrieved them.

**Termination checking.** `status = str(res.solver.termination_condition)` is compared to
`"optimal"`, once to trigger the retry and then stored on `OPFResult`. Callers do check it:
`run_load_sweep` prints a warning, `run_schemes` and `run_seasonal` print, and
`run_seasonal` actually `continue`s past a failure. So failures are *recorded*.

**But they are not handled.** On a failed solve `solve()` still returns a fully populated
`OPFResult`: objective, dispatch, voltages, and — critically — `q_price` and `p_price`
read out of `m.dual`. I verified this: with `s_interface_max=20`, IPOPT reports
"Converged to a locally infeasible point" and the function returns `slack_p=16.9,
slack_q=10.7` and a full price vector. A multiplier taken at a locally infeasible point is
a multiplier of IPOPT's restoration subproblem, not a price. Nothing downstream
distinguishes it. See S1-a — this is not hypothetical, it is what produced the study's
headline number.

Also not checked: `res.solver.status` (as distinct from termination condition), and the
fact that IPOPT's "Solved To Acceptable Level" can surface as `optimal` at a looser
tolerance than requested, which degrades dual accuracy silently.

---

## 5. Unit conversion for the reactive price — independent verification

### 5.1 Derivation from scratch

The objective is $S_{base}\cdot[\ldots]$ with the bracket in pu, so $f$ has units EUR/h.
The balance constraints $c_i(x) = 0$ are in per unit. The Lagrangian is
$L = f + \sum_i \mu_i c_i$, so

$$[\mu_i] = \frac{\text{EUR/h}}{\text{pu}} .$$

One pu of reactive injection is $S_{base}$ MVAr, hence

$$\lambda^Q_i \;[\text{EUR/MVArh}] \;=\; \frac{\mu_i}{S_{base}\,[\text{MVA}]}.$$

Sign: the constraint is written $c_i = Q^{inj}_i - Q_{g,i} + Q_{D,i} = 0$. Raising the load
$Q_{D,i}$ by $\delta$ is equivalent to shifting the constraint's right-hand side by
$-\delta$, so $\partial f/\partial Q_{D,i} = -\,\partial f/\partial \text{rhs} = -\mu_i$.
**Negation is required.** Code: `return -m.dual[constraint[ppc_bus]] / grid.s_base`
(opf.py:341). ✔ Both factor and sign agree with my derivation.

### 5.2 Empirical verification — and why their own test cannot see it

`test_unit_conversion` finite-differences the objective against a load bump. That is the
right test, but **it is blind to the $S_{base}$ factor**, because
`ppc["baseMVA"] = net.sn_mva = 1.0` for CIGRE MV (I checked: `baseMVA: 1`). At a 1 MVA
base, dividing by `s_base` is numerically a no-op. Removing the division entirely would
leave every existing test green.

So I verified it the way the test cannot — by **re-basing the whole problem to 100 MVA**
(`net.sn_mva = 100`, machines rebuilt on a 100 MVA base) and checking base invariance:

```
s_base=1.0    obj 2687.7974  q_price@3 0.16266  q_price@10 0.09199  q_price@14 17.64096
s_base=100.0  obj 2687.7967  q_price@3 0.16266  q_price@10 0.09199  q_price@14 17.64096
```

Identical to five decimals. The conversion is **correct**.

Two further independent confirmations, which are cleaner than a finite difference because
they are exact:

- $\lambda^P$ at the slack bus comes out **70.0000** EUR/MWh against `energy_price = 70.0`.
- $\lambda^Q$ at the slack bus comes out **16.0000** EUR/MVArh against `q_import_price = 16.0`.

Both are analytically forced (the slack's marginal source is priced at exactly those
rates), and both landing on the nose confirms sign *and* scale simultaneously.

**Verdict on Q5: the conversion is right. The test that is supposed to protect it cannot
detect a missing or wrong $S_{base}$ factor, and should be re-based.**

---

## 6. Convergence robustness — the retry path

`solve()` (opf.py:312–332) does: solve with `max_iter=20000`; if `termination_condition !=
"optimal"`, **rebuild the model from scratch** and re-solve with
`nlp_scaling_method="none"`. The reasoning is documented at unusual length (opf.py:314–327)
with the specific counts that motivated it (25/25 → 11/25 recovered on hard hours, but
2 new failures on 16 easy hours, hence retry-only-on-failure).

**Assessment: legitimate, not a hack.** The default attempt always runs first, so an easy
case can never be regressed; the retry is deterministic (same starting point, only the
solver's internal scaling changes); and turning off gradient-based NLP scaling is a
standard response to a badly-scaled NLP, not a tolerance relaxation. Nobody is loosening
`tol` or accepting `acceptable` status to make numbers appear.

Three caveats:

- **Nothing records which configuration produced the answer.** Add a `retried: bool` (and
  ideally the iteration count) to `OPFResult`, so a reader can see whether a headline point
  came from the default path.
- **Selection bias in the surviving sample is real but under-stated.** The hours that only
  solve with scaling off are precisely the ill-conditioned, near-flat-objective ones; when
  results are aggregated over many hours, the recovered set is systematically not a random
  subsample. The docstring frames the retry purely as an upside.
- **The underlying cause is probably self-inflicted.** The system base is
  `net.sn_mva = 1 MVA` for a 45 MW feeder. That puts Ybus entries at 104–2321 pu against
  bus injections of 0–20 pu and an objective gradient of order 70 — I measured
  $|Y|_{max}=2321$, $\mathrm{cond}(\Re Y)\approx 7.6\times10^3$. Constraint functions three
  orders of magnitude larger than the variables is exactly the condition IPOPT's default
  scaling handles badly. Since I have already shown the model is base-invariant, moving to
  a conventional 100 MVA base is free and is a much better fix than turning scaling off.
  Worth testing before the retry is presented as the answer.

---

## 7. Other findings

### 7.1 The interface constraint is dimensionally wrong (masked by the base)

`m.p_slack**2 + m.q_slack**2 <= s_interface_max**2` compares **per-unit** slack power
against a quantity documented in the docstring as "(MVA)" and set in `run_experiments.py`
as `S_INTERFACE_MAX = 50.0  # MVA`. It works today only because 1 pu = 1 MVA. Demonstrated:

```
s_interface_max=20 MVA, s_base=1    -> infeasible, |S| driven to exactly 20.000 MVA
s_interface_max=20 MVA, s_base=100  -> "optimal", |S| = 37.727 MVA   <-- limit ignored
```

At a 100 MVA base the constraint is 10 000× too loose and reports `optimal` while violating
its own limit by 89%. Fix: `<= (s_interface_max / grid.s_base)**2`.

### 7.2 The reactive interface term is a magnitude charge, not a symmetric price

Term (ii) is $\pi_Q|Q_{slack}|$. The docstring (opf.py:136–144) defends it with "Real
generators do get paid the same market price whether they are net importing or exporting
— that symmetry is standard, efficient market design". That argument describes a **signed**
price $\pi_Q Q_{slack}$, which is what term (i) does for active power ($\lambda_E P_{slack}$,
correctly crediting export). Term (ii) instead *penalises both directions equally*: the
feeder is charged for helping the upstream grid exactly as much as for burdening it. That
may be a defensible model of a tariff on exchange, but the stated justification does not
support the implemented form, and the two are conflated in one paragraph.

Consequence: $\lambda^Q$ at the slack is $+\pi_Q$ or $-\pi_Q$ depending on the sign of
$Q_{slack}$, with a discontinuity at zero. In these runs $Q_{slack}\in[6.6, 20.8]$ MVAr so
it never bites, but it is a latent source of a price jump unrelated to any machine limit.

### 7.3 Inconsistent smoothing of the $|\cdot|$ kinks

`cost_models.py` uses `eps = 1e-4` and explains why: "at 1e-8 the kink is sharp enough that
IPOPT stalls". `opf.py:282` then smooths the *same kind of kink* with `1e-10` — six orders
of magnitude tighter than the value their own testing established. Latent only (see above),
but it directly contradicts a documented finding in the sibling module.

### 7.4 Machine active losses are ~10% of network losses and almost entirely unmodelled

Because $C^Q_{\text{physical}}$ is exactly $P$-independent (§2.2) and machine loss is not
withdrawn in the power balance, only the $Q$-deviation slice of machine loss reaches the
objective. Measured at the base case:

```
G1 22.5 kW (min-loss at same P: 18.1)   G2  7.4 kW (6.6)
G3 18.9 kW (13.6)                        G4  7.7 kW (7.4)
total machine loss 56.5 kW  vs network loss 574.6 kW  = 9.8%
value at 70 EUR/MWh: 3.95 EUR/h, of which only 0.76 EUR/h appears in the objective
```

Defensible as a "cost of the service relative to the best point at the same $P$"
definition, but it means (a) `losses_mw` is *network* losses only and the "cost of no
coordination" percentage should say so, and (b) `run_schemes`' description of the
coordinated solve as "the true least-cost operating point" is least-cost with respect to
network losses plus $Q$-service cost only.

### 7.5 The active dispatch is degenerate under the default configuration

With $c^P = 0$ and export credited at $\lambda_E$, the objective is strictly decreasing in
every $P_g$, so machines sit at $p_{max}$ or at a network bound in essentially every run
(I confirmed `p_max: True` for all four machines at 135% loading, and `p_g3 = 5.10 = p_max`
across the whole sweep). One visible consequence: the feeder trunk is at
`max_line_loading_pct = 100.0` at **every** sweep point including the lightest (40%
loading) — the congestion is created by forced maximum export, not by demand. Every nodal
price reported is therefore a congestion price shaped by the zero-water-value assumption,
which is why $\lambda^P$ collapses to ~0 behind the constraint and $\lambda^Q$ at the
generator buses (0.09–0.25) sits ~40× below $\lambda^Q$ at the load buses (3.5).

The water-value sensitivity does not probe this well: $c^P = 0$ and $c^P = 35$ give
**bit-identical** dispatch (both still below $\lambda_E$, so export is still profitable and
$P$ still hits the bound), and $c^P = 70$ is exactly the degenerate flat-objective point
they had to add solver workarounds for. Two of the three points are uninformative. Sweep
above $\lambda_E$ (e.g. 0, 85, 120) instead.

### 7.6 Negative nodal reactive prices are being produced and not flagged

At the base case with the default $\pi_Q = 3.478$, $\lambda^Q$ spans **−0.101 to +3.498**
EUR/MVArh across the 15 buses, and bus 14 (generator G4) is **negative**. That is a correct
model outcome — G4 sits below $Q^\star$, where marginal service cost is negative — but a
negative nodal price means a supplier would be *charged* for injecting. It has real
settlement consequences and it is not surfaced anywhere in the outputs.

### 7.7 Which node's price gets headlined

`figure3` plots `lambda_q_g1` and compares it against a horizontal "SysOpt equitable price"
reference at 0.28 EUR/MVArh. Given the 0.09–3.5 EUR/MVArh spread across buses in the same
solve, the agreement between $\lambda^Q_{G1}\approx0.24$ and 0.28 is substantially a choice
of which bus to plot. The axis label is honest ("at G1 bus"), but a system-wide "equitable
price" is not the natural comparator for a single congested node's price. Worth either
plotting the spread as a band, or saying explicitly why G1's bus is the right comparator.

### 7.8 `run_seasonal` uses the load builder its own module docstring warns against

`case_data.demand_shapes` says, verbatim, "Do not use this for a single-hour case that is
meant to look like a real operating point ... Use `build_case_from_hour` for that", because
one system-wide shape forces correlation 1.0 across buses against a real 0.24–0.47.
`run_seasonal` (run_experiments.py:335) then does exactly that:
`build_case(p_s, q_s)` at a specific timestamp, to represent winter/summer peak and median
*hours*. Either switch it to `build_case_from_hour` or state why the uniform shape is
acceptable there.

### 7.9 Minor

- `run_local_optimum_check` jitters only $V$ and $\theta$; $P_g$ and $Q_g$ start at the
  same generic guess for all 8 seeds, and the $V$ jitter is then re-clipped to
  $[0.95,1.05]$. All 8 seeds return objectives identical to 12 significant figures. That is
  reassuring but weaker evidence than "8 random starts" suggests — jitter `pg`/`qg` too.
- A new `SolverFactory("ipopt")` object is constructed per solve; `injection` and
  `current_sq` build dense $O(n^2)$ expression trees over all buses including zero-admittance
  pairs. Irrelevant at $n=18$; both matter if this is ever pointed at a larger network.
- `warm_start` does `grid.pp_to_ppc[b]` before checking membership, so a stray key raises
  `KeyError` rather than being ignored.
- `OPFResult.binding` records `underexcited`, but `_row` in `run_experiments.py` only
  writes `field` and `stator` to the CSV — so the constraint I found actually binding most
  often (§3.1) is the one not recorded.

---

## 8. Issues ranked by severity

### S1 — Critical: the headline "field limit binds → price jumps" result comes from failed solves

This is the most important finding in the review, and it is the product of three defects
compounding.

`results/load_sweep.csv` contains 160 rows, of which **8 have `status == "infeasible"`** —
the top two load scales (1.4718 and 1.5000) in each of the four cases. Those rows are
written to CSV and `figure3` plots the whole dataframe with **no status filter**.

Worse: those two points are the *only* rows in the entire sweep where
`g1_field_binding | g2_field_binding` is `True`. So:

- The blue "G1/G2 field limit binding" shaded region on Figure 3 is drawn entirely from
  non-converged solves.
- The price jump that region is meant to explain — $\lambda^Q_{G1}$ going 0.245 → 2.15 →
  2.25 EUR/MVArh over the last three points — is a jump *into* two failed solves.

And the failed points are not reproducible. Re-solving the same two scales gives:

| load scale | CSV `lambda_q_g1` | my re-solve |
|---|---|---|
| 1.4718 | 2.1518 | 0.0000 |
| 1.5000 | 2.2453 | 60.6311 |

Same code, same inputs — different numbers, because what is being reported is IPOPT's last
iterate from a restoration failure, not a solution.

Root cause of the infeasibility is physical and benign: at 150% loading the feeder needs
$\sqrt{49.0^2 + 17.1^2} = 51.9$ MVA at the interface against `S_INTERFACE_MAX = 50`. I
confirmed by bisection — the same case solves cleanly with the interface at 200 MVA or
unset. **The sweep range simply overshoots the network's feasible envelope.**

At every genuinely feasible point the field limit is nowhere near active. Residuals at 135%
loading (against the constraint's own scale):

```
G1 field residual -29.96 (scale 186.9)    G3 -11.44 (104.4)
G2 field residual -38.01 (scale  62.4)    G4 -15.48 ( 22.4)
```

**So on the current evidence the field limit never binds anywhere in the feasible operating
range, and the study's central claimed mechanism is not demonstrated by these results.**

Fixes, in order:
1. In `solve()`, return `q_price`/`p_price`/`objective` as `NaN` (or raise) when
   `status != "optimal"`. Duals from a non-converged point should never leave the function
   as numbers.
2. Filter `status == "optimal"` in every plotting and aggregation path.
3. Truncate the sweep at the feasible envelope (~1.44 here) or raise `S_INTERFACE_MAX` if
   50 MVA is not the intended limit, and report the truncation.
4. Re-examine whether the field limit binds anywhere at all with these machines; if not,
   say so plainly rather than shading a region on the strength of two failures.

### S1 — Critical: `s_interface_max` compared against per-unit power (§7.1)

Currently correct only because `baseMVA == 1`. At any other base it silently permits
arbitrary violation and still reports `optimal`. One-line fix.

### S2 — Constraint-activity flags use an absolute tolerance ~5e-9 relative

`binding` (opf.py:357–366) tests `mach.field_limit(p,q,v) > -1e-6`. The field-limit residual
has scale 22–187 pu² depending on machine, so `1e-6` is a relative tolerance of
$5\times10^{-9}$ — far below IPOPT's own constraint tolerance. The flag is therefore
unreliable in both directions, and it is the input to Figure 3's shading and to the
"which constraints are active" deliverable. Use the constraint's dual
(`m.dual[m.field[g]] > tol`, which is scale-free and is the correct test for activity), or
at minimum normalise by the constraint scale.

### S2 — Failed solves return full, plausible-looking numbers

See S1. Listed separately because it is a distinct code change from the plotting filter and
because it also affects `run_schemes`, `run_seasonal` and the monthly runs.

### S2 — Machine active losses ~10% of network losses, essentially unmodelled (§7.4)

Not a bug; an accounting gap that should be stated wherever a loss reduction percentage is
quoted.

### S3 — Interface reactive term is a magnitude penalty described as a symmetric price (§7.2)

### S3 — Stator circle not voltage-scaled while field circle is (§3)

### S3 — $Q^\star$ infeasible below ~40% of rating, so the "zero-cost point" claim is
conditional (§3.1)

### S3 — Degenerate $P$ dispatch and an uninformative water-value sweep (§7.5)

### S3 — `1e-10` smoothing contradicts the sibling module's own documented `1e-4` finding (§7.3)

### S4 — Poor per-unit base (1 MVA for a 45 MW feeder) is a likely root cause of the
ill-conditioning the retry works around (§6)

### S4 — Unit-conversion test cannot detect an $S_{base}$ error at the base actually used (§5.2)

### S4 — Retry does not record which solver configuration produced the result (§6)

### S4 — `run_seasonal` uses `build_case` where `case_data` says not to (§7.8)

### S4 — Negative nodal reactive prices produced and unflagged (§7.6)

### S5 — Latent: non-injective `ppc_to_pp` inversion, out-of-service buses, `parallel`/`df`
on lines, `warm_start` KeyError, artificial $\pm\pi/2$ angle box, `res.solver.status`
unchecked (§1.3, §3, §4)

---

## 9. Concrete suggestions

**Must do before any of these numbers go on a slide**

1. `solve()`: `if status != "optimal": q_price = p_price = {b: float("nan") ...}`. Then
   filter on status in `figure3`, `figure4_dispatch_split` and every aggregation.
2. Truncate the load sweep to the feasible envelope, and print the binding reason for the
   truncation (here: interface MVA).
3. Fix the interface constraint units: `<= (s_interface_max / grid.s_base)**2`.
4. Replace residual-threshold activity detection with dual-based detection.
5. Re-run and re-check whether the field limit binds anywhere feasible. Report the answer
   either way — "the field limit does not bind on this feeder at any feasible load" is a
   perfectly good finding and is far better than the current figure.

**Should do**

6. Re-base the system to 100 MVA. It is free (I verified base invariance), it makes the
   `s_base` division actually exercised by the tests, and it plausibly removes the need for
   the `nlp_scaling_method=none` fallback — test that hypothesis explicitly, because
   "we fixed the scaling properly" is a much stronger slide than "we retry with scaling off".
7. Parametrise `test_unit_conversion` over `s_base ∈ {1, 100}` and add the two exact
   assertions I used: $\lambda^P(\text{slack}) = \lambda_E$ and
   $\lambda^Q(\text{slack}) = \pi_Q$. They are analytically forced and catch sign, scale and
   base in one line each.
8. Add `retried: bool` and `iterations: int` to `OPFResult`; write both to every CSV.
9. Add a `test_infeasible_solve_does_not_return_prices` regression test — the S1 defect is
   exactly the kind that comes back.
10. State the closed form $C^Q = \lambda_E (R_a + k_fX_s^2)(Q-Q^\star)^2/V^2$ in
    `cost_models.py`. It proves non-negativity for all $V$, makes the $P$-independence
    explicit, and is a better slide than the difference-of-losses form.
11. Either scale the stator circle by $V$, or document why the two capability limits are
    treated differently with respect to voltage.
12. Rewrite the term-(ii) docstring to describe what it implements (a two-sided magnitude
    charge on interface reactive exchange) rather than price symmetry, and raise its `eps`
    to `1e-4` for consistency with `cost_models.py`.
13. Record `underexcited` binding in `_row`; it is the limit that actually binds.
14. Widen the water-value sweep above $\lambda_E$.

**Nice to have**

15. Jitter `pg`/`qg` as well as `V`/`θ` in `run_local_optimum_check`.
16. Guard against out-of-service buses and non-injective bus mappings in `load_grid`.
17. Report the full $\lambda^Q$ spread on Figure 3 (band or second series), so the
    comparison to the SysOpt reference is not resting on the choice of node.

---

## 10. What I checked and found nothing wrong with

Stated explicitly, because it matters as much as the defect list:

- The polar power-balance equations, term by term against my own derivation, including the
  diagonal terms and the $B$-sign convention. Correct.
- Per-unit consistency of Ybus, injections, voltages and angles. Correct.
- Slack angle reference. Correct, and correctly located from `BUS_TYPE == REF`.
- pandapower→ppc bus handling, which is the subtlest thing in the file and which the
  author got right for a documented and real reason (18 ppc rows vs 15 buses on this net).
- Branch-limit construction from `Yf`/`Yt` and the current base $S_{base}/(\sqrt3 V_{base})$.
- Dual sign convention. Verified analytically *and* by two exact numerical identities.
- The pu→EUR/MVArh conversion factor. Verified by re-basing the entire problem to 100 MVA
  and confirming invariance to five decimals.
- Absence of double-counting in the objective — including the specific trap of adding an
  explicit opportunity-cost term on top of a constrained formulation. That trap was
  correctly avoided.
- `Suffix(direction=IMPORT)` placement, including on the retry path.
- Non-negativity of `PhysicalCost` (proved in closed form for all $V$, stronger than the
  existing test).
- Consistency between `PhysicalCost`'s gradient and `machine.marginal_loss`, which is what
  `test_price_at_unconstrained_generator_equals_its_marginal_cost` rests on.
- Constraint satisfaction across all 160 stored sweep rows (underexcitation ray checked
  explicitly for all four machines: zero violations).
- The retry logic, which I expected to be a results-biasing hack and which is not one.
