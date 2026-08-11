# Review 02 — Generator loss, capability and cost model

**Scope:** `src/machine.py`, `tests/test_machine.py`.
`src/cost_models.py::PhysicalCost` is read only as far as question 3 requires (the cost is
defined there, not in `machine.py`). Network, OPF/solver and settlement layers deliberately
untouched.

**Reviewer stance:** no prior context on this project. Every equation re-derived from
first-principles synchronous machine theory before comparing to the code. Where the code
cites a source, I opened the source. Where the code claims agreement with a number, I
recomputed the number.

---

## 0. What I actually did

1. Re-derived the field EMF, the total loss, `Q*`, the marginal loss and both capability
   circles by hand (§1–§4 below).
2. Numerically verified `Q*` against a `scipy.optimize.minimize_scalar` argmin of the code's
   own loss, over V ∈ {0.90, 0.95, 1.00, 1.05, 1.10} × P ∈ {0.2, 0.5, 0.85}. Agreement to
   ≤7e-8 everywhere.
3. Opened the cited source PDF
   (`Loss_Modeling_of_Large_Hydrogenerators_...pdf`, Karekezi, Melfald, Øyvang & Nøland,
   IEEE TEC 38(2), 2023), rendered Tables I/II and Fig. 2 (they are images, not text) and
   read equations (4)–(7) directly.
4. **Re-implemented the paper's own loss model (eqs. 4–7) independently** and compared its
   `Q_opt` against the code's `Q*`, peeling the approximations off one at a time to see which
   one actually causes the discrepancy the code's docstring apologises for.
5. Discovered that **`syngenlib` is installed in the project venv** (pinned in
   `requirements.txt` at commit `e19de79`) and read
   `syngenlib/archive/pyomo_generator_loss_model.py`,
   `syngenlib/models/generator_calculation_model.py` and
   `syngenlib/data/components.py` — i.e. the exact reference the module docstring claims to
   follow. This turns several "declared but unverifiable" claims into verified ones.
6. Ran the test suite (result in §6).
7. **Mutation-tested the model against its own tests** — seven single-token edits to the
   voltage exponents, each run against the full 21-test file, file restored afterwards
   (verified byte-identical with `cmp`).

---

## 1. Loss model

### 1.1 Terms present

`Machine.loss(p, q, v)` = `stator_loss` + `field_loss` + `p_const`:

| Term | Code | Form |
|---|---|---|
| Stator/armature copper | `r_a * (p**2 + q**2) / v**2` | `R_a · I_a²`, `I_a² = S²/V²` |
| Field/rotor copper | `k_f * ((v + x_s*q/v)**2 + (x_s*p/v)**2)` | `k_f · E_f²` |
| Constant | `p_const` (defaults 0.0, **never set non-zero anywhere in the repo**) | additive constant |
| Core loss | **absent** | — |

### 1.2 My derivation of the field term

Round rotor, terminal voltage taken as the real reference `V_t = V∠0`, generator convention
`S = V I*`, so `I = (P − jQ)/V`. Neglecting `R_a` in the phasor relation:

```
E_f = V_t + j X_s I
    = V + j X_s (P − jQ)/V
    = V + X_s Q / V   +   j · X_s P / V
```

Hence

```
E_f² = (V + X_s Q / V)² + (X_s P / V)²
```

**The code matches this exactly.** The docstring's factored form
`E_f² = V²[(1 + X_s Q/V²)² + (X_s P/V²)²]` is algebraically identical (factor `V²` in).

Independent confirmation: `syngenlib/archive/pyomo_generator_loss_model.py:50` writes

```python
E_q_2_calc = m.V_g_pu**2*((1 + m.x_d*m.Q_g_pu/m.V_g_pu**2)**2 + (m.x_d*m.P_g_pu/m.V_g_pu**2)**2)
```

— structurally identical, and `syngenlib/models/generator_calculation_model.py:72` repeats
it. So the docstring's provenance claim is **true and now verified against the library
itself**, not merely asserted.

`P_field = k_f E_f²` assumes `I_f ∝ E_f` (air-gap line, no saturation) and rotor loss
`∝ I_f²`. SynGenLib's Pyomo model does the same
(`P_loss_rotor = P_r_star · E_q²/E_q_nom² · S_n`, line 72); its *non*-Pyomo path instead uses
`P_loss_nom_rotor_pu · |I_f|²` with a real saturation model. The code's simplification is
therefore exactly the one SynGenLib itself makes when it needs a Pyomo-embeddable form.

### 1.3 Is the round-rotor approximation declared?

**Yes, prominently and honestly.** The module docstring's first line is "Round-rotor form
(X_d = X_q)", and lines 9–32 spell out three separate departures from the primary source
(round rotor vs. `X_d`=1.087/`X_q`=0.676; `E_f²`-quadratic vs. the paper's
linear-plus-quadratic-in-`I_f` eq. 5; no saturated Potier construction), gives the reason
(closed form and differentiable inside Pyomo), and states the numerical consequence. This is
better disclosure than I usually see. Everything it asserts, I checked and it holds:

- Table II of the paper does read `R_a = 0.002 pu, X_d = 1.087 pu, X_q = 0.676 pu,
  X_p = 0.144 pu, X_t = 0.129 pu` (rendered from p.3 of the PDF).
- Table I does read `P_a*+P_s* = 276.62 kW, P_ex* = 15.88 kW, P_f*+P_br* = 175.78 kW,
  P_c* = 211.92 kW, P_be*+P_wf* = 413.82 kW`.
- Eq. (5) does read `P_l,r = P_ex*(I_f/I_f*) + (P_f*+P_br*)(I_f/I_f*)²`.
- Fig. 2(a) does show `Q_opt` spanning ≈ −0.194…−0.203 pu with saturation and
  ≈ −0.152…−0.156 pu without — exactly the ranges the docstring quotes.
- `cos φ = 0.9` is sourced: it appears in the Table V caption ("NOMINAL OPERATING POINT OF
  S = 1.0, cos ϕ = 0.9 (INDUCTIVE)"). I initially suspected this was an unsourced assumption
  smuggled into a "verified against the PDF" list; it is not.

One small thing that is **not** declared: `E_f` neglects `R_a` in the phasor relation
(`E_f = V + jX_s I`, not `V + (R_a + jX_s)I`) while `R_a` *is* retained in the stator loss.
Negligible at `R_a = 0.002` and universal practice, but it belongs in the same list.

---

## 2. `Q*` — the minimum-loss reactive point

### 2.1 My derivation

```
P_loss(P,Q,V) = R_a (P² + Q²)/V²  +  k_f [(V + X_s Q/V)² + (X_s P/V)²]  +  P_const

∂P_loss/∂Q = 2 R_a Q / V²  +  2 k_f (V + X_s Q/V)(X_s/V)
           = 2 R_a Q / V²  +  2 k_f X_s  +  2 k_f X_s² Q / V²

Set to zero:   Q (2R_a + 2k_f X_s²)/V² = −2 k_f X_s

         ┌────────────────────────────────────┐
         │  Q* = − k_f X_s V² / (R_a + k_f X_s²)  │
         └────────────────────────────────────┘

∂²P_loss/∂Q² = 2(R_a + k_f X_s²)/V² > 0   ⇒ genuine minimum, unique, global.
```

**The code matches exactly** (`machine.py:159`), including the `V²`.

**Sign: it must be negative (underexcited), and it is.** The reason is structural, not
numerical: the stator term is *even* in Q (`R_a Q²/V²`, minimum at Q = 0), whereas the field
term expands to `k_f X_s² Q²/V² + 2 k_f X_s Q + k_f V² + …` and carries a **linear** term
`+2 k_f X_s Q`. A quadratic with a positive linear coefficient has its vertex at negative
argument. Physically: backing excitation off below the no-load value cuts field copper loss
at first order while raising stator copper loss only at second order, so the machine's own
cheapest place to sit is slightly absorbing.

`Q*` is **independent of P** — correct for this loss form, because P and Q separate (no cross
term survives). The signature `q_star(self, v)` is therefore honest, even though the project
spec writes it as `Q*(P)`. Worth noting in the docstring that this is *supported*, not merely
convenient: the paper's own Fig. 2(a) shows `Q_opt` drifting only from −0.194 to −0.203 pu
across the entire P range (≈5%), and the paper's text says the minimum "is around −0.2 pu
reactive power, regardless of the active power level."

### 2.2 Numerical verification (mine, independent of their test)

| V | numeric argmin | analytic `q_star(v)` | diff |
|---|---|---|---|
| 0.90 | −1.549820 | −1.549820 | −2.3e-08 |
| 0.95 | −1.726806 | −1.726806 | −2.6e-08 |
| 1.00 | −1.913358 | −1.913358 | +2.8e-08 |
| 1.05 | −2.109477 | −2.109477 | +6.3e-08 |
| 1.10 | −2.315163 | −2.315163 | +3.4e-08 |

(identical at P = 0.2, 0.5, 0.85 — confirming P-independence numerically). Values are on the
system base with `S_BASE = 1 MVA` for the 8 MVA `g1()`; dividing by 8 gives −0.23917 pu on the
machine base, matching the docstring's stated −0.239.

I also verified base-change invariance analytically: under `on_system_base`,
`x_s → x_s·z`, `r_a → r_a·z`, `k_f → k_f/z` with `z = S_base/S_rated`, so

```
Q*_new = −(k_f/z)(x_s z)V² / (r_a z + (k_f/z)(x_s z)²) = (1/z)·Q*_old = p_scale · Q*_old
```

Confirmed numerically (ratio exactly 8.0). The base conversion is self-consistent — a real
correctness win, and one that is only half-tested (see §6).

---

## 3. Cost function

`PhysicalCost.__call__` (`cost_models.py`):

```python
return self.energy_price * (machine.loss(p, q, v) - machine.loss(p, machine.q_star(v), v))
```

### 3.1 Closed form (mine)

Write `a = (R_a + k_f X_s²)/V²` and `b = 2 k_f X_s`, so
`P_loss(Q) = aQ² + bQ + const(P,V)` and `Q* = −b/(2a)`. Then

```
C^Q = λ_E [P_loss(Q) − P_loss(Q*)] = λ_E · a · (Q − Q*)²
```

i.e.

```
C^Q(P,Q,V) = λ_E · (R_a + k_f X_s²)/V² · (Q − Q*(V))²
```

**Verified to 1e-12 relative** against the code for V ∈ {0.95, 1.0, 1.05} × P ∈ {0.2, 0.9, 5.0}
× Q ∈ {−3, 0, 2, 7}.

### 3.2 Answers

- **Non-negative by construction?** Yes, unconditionally — it is `λ_E · a · (ΔQ)²` with
  `a > 0` for any positive `R_a`, `k_f`, `X_s`. Exactly zero at `Q = Q*`. There is **no input
  (P, Q, V, or parameter set with positive physical values) that makes it negative.**
- **Discontinuous anywhere?** No. It is a polynomial in Q and a smooth rational function of V,
  `C^∞` on `V ≠ 0`. No `abs`, no `max`, no branch — unlike `AssumedCost`/`DeadbandCost`, which
  need ε-smoothing. This is a genuine advantage of Case B worth putting on a slide.
- **Numerically fragile?** I specifically looked for catastrophic cancellation, since the
  code computes an `O(ΔQ²)` quantity as the difference of two `O(P²)` losses. It is
  **clean**: the P-dependent terms are computed by identical expressions in both calls and
  cancel bit-exactly in IEEE arithmetic. `C^Q(Q*)` returns exactly `+0.0` at P = 0.5, 2.0 and
  7.2 pu. No issue.
- **Structural note:** `p_const` (and any purely V-dependent loss term) cancels *identically*
  out of `C^Q`. So setting `p_const` is a no-op for the price. That is correct behaviour —
  constant losses are not a reactive service cost — but it means `p_const` cannot be used to
  make the loss figures right either (see Issue M3).
- The definition matches the primary source's own eq. (2),
  `ΔP_l = P_l(Q,P) − P_l(Q_opt,P)`, which I read in the PDF. Faithful.
- Consistency: `dC^Q/dQ = λ_E · 2a(Q−Q*) = λ_E · [2k_f X_s + 2(R_a + k_f X_s²)Q/V²]`
  = `λ_E · marginal_loss(q, v)`. The code's `marginal_loss` is exactly this. ✔

---

## 4. Capability limits

### 4.1 Field limit — correct

From `E_f² ≤ E_f,max²`, multiply through by `V²/X_s²`:

```
(V + X_s Q/V)² + (X_s P/V)² ≤ E_f,max²
⇔  (V²/X_s + Q)² + P² ≤ (V E_f,max / X_s)²
```

Circle, centre `(P=0, Q=−V²/X_s)`, radius `V·E_f,max/X_s`. **`field_limit` matches exactly**
(`machine.py:172`), in `g(P,Q,V) ≤ 0` form, with the sign the right way round (increasing Q
moves away from the centre and binds). It is also *internally consistent with the loss model*:
`field_limit ≤ 0 ⟺ field_loss ≤ k_f E_f,max²`, same `E_f` expression. That consistency is
worth more than it looks.

Cross-check against SynGenLib `_get_rotor_limits_pu`: `r_f_max = E_q_max·V/x`,
`q_f = −V²/x`. Identical geometry. ✔

Two remarks:

- SynGenLib also carries an `E_q_min` **minimum-excitation** circle (`r_f_min = E_q_min·V/x`).
  The code has no equivalent. Not necessarily wrong (the PF ray substitutes), but it is a
  limit the reference model has and this one does not.
- `E_f,max` is derived in `from_nameplate` from the rated point,
  `E_f,max² = (1 + X_d sin φ)² + (X_d cos φ)²`. I initially flagged this as conflating
  SynGenLib's `E_q_nom` (rotor-loss normaliser) with `E_q_max` (field limit) — the archived
  Pyomo model does keep them as separate parameters. But
  `syngenlib/data/components.py::CapabilityModelDataclass.default_limits` derives `E_q_max`
  from the rated point by **exactly the same formula**. So the code is faithful to the
  library's own default. **Not an issue.** Good call by whoever wrote it — deriving `E_f,max`
  rather than picking it is the right instinct and the docstring's reasoning for it is sound.
- Two bugs in SynGenLib's archived Pyomo model were **not** copied: its `exciter_constraint`
  writes `+ m.P_g_pu` where it should be `+ m.P_g_pu**2` (line 66), and its
  `stator_constraint` (line 63) is a tautology `0 ≤ 0` given the `I_a_2` defining constraint.
  The code under review has both right. Worth saying out loud.

### 4.2 Field circle vs. a true salient-pole boundary (quantifying the declared approximation)

I built the classical salient-pole construction (`E_q = V + jX_q I` → δ, `I_d = I sin(δ−φ)`,
`E_f = |E_q| + (X_d − X_q) I_d`) with `X_d = 1.087`, `X_q = 0.676`, calibrated `E_f,max` at the
same rated point, and compared the maximum permissible Q at V = 1:

| P (pu) | Q_max, code's circle | Q_max, salient-pole | error |
|---|---|---|---|
| 0.00 | 0.7074 | 0.6899 | +2.5% |
| 0.40 | 0.6575 | 0.6429 | +2.3% |
| 0.80 | 0.4972 | 0.4928 | +0.9% |
| 0.85 | 0.4678 | 0.4655 | +0.5% |

So the round-rotor circle is **optimistic by 0.5–2.5% in Q** over the usable P range. The
docstring warns that `X_d` vs `X_q` is "a 38% difference, not a small one" — true of the
reactances, but the *consequence* for the capability boundary is 1–2%, and for `Q_opt` it is
≈8% (§5.1). Quantifying this converts a caveat into a defence. I'd rather see the number than
the worry.

### 4.3 Stator limit — the one geometric term that is *not* right

```python
def stator_limit(self, p, q, v):
    return p**2 + q**2 - self.s_rated**2      # v accepted, never used
```

This is an **apparent-power** limit, not a **current** limit. The physical constraint is
`I_a ≤ I_a,rated`, i.e. `S ≤ V · S_rated`, so the circle radius scales with terminal voltage.
SynGenLib does exactly that (`_get_stator_limits_pu`:
`Q_max = sqrt((V·I_a_max/tap)² − P²)`), and so does every standard capability diagram
treatment once V leaves 1.0 pu.

Magnitude, with V bounded to [0.95, 1.05] in this study:

| V | code permits | current limit | error |
|---|---|---|---|
| 0.95 | S = 1.000 pu | 0.950 pu | code permits **+5.3% overcurrent** |
| 1.05 | S = 1.000 pu | 1.050 pu | code is 4.8% conservative |

The unused `v` parameter is a tell that the V-scaling was considered and dropped, or was never
finished. Either way it is undocumented.

### 4.4 Underexcitation limit — a substantive modelling choice, under-declared

```python
return -q - p * math.tan(math.acos(self.pf_lead_max))     # ⇔  Q ≥ −P·tan(acos 0.86)
```

The algebra is right: `tan(acos 0.86) = 0.5934`, and `P/√(P²+Q²) = cos φ = 0.86` on that ray. ✔

But a **ray through the origin** is not the shape of an underexcitation limit. Both classical
theory and SynGenLib put an offset on it — `_get_stability_limit_pu` returns
`Q_min = m·P − V²/x`. Consequences at V = 1, `X_d`=1.087:

- At **P = 0**, the code forbids *any* reactive absorption (`Q ≥ 0`). SynGenLib's limit would
  allow `Q ≥ −0.92 pu`. A hydro unit at zero output that cannot absorb a single MVAr is not
  physical.
- More importantly: `Q* = −0.2392 pu` (machine base) is only reachable when
  `0.5934·P ≥ 0.2392`, i.e. **P ≥ 0.403 pu**. With `p_min = 0.15`, the whole band
  P ∈ [0.15, 0.40] pu has the machine's own zero-cost point **outside its feasible set**:

  | P (pu) | Q floor | Q* | Q* feasible? |
  |---|---|---|---|
  | 0.150 | −0.0890 | −0.2392 | **no** |
  | 0.300 | −0.1780 | −0.2392 | **no** |
  | 0.403 | −0.2391 | −0.2392 | **no** (boundary) |
  | 0.600 | −0.3560 | −0.2392 | yes |
  | 0.850 | −0.5044 | −0.2392 | yes |

  In that band `C^Q > 0` at *every* feasible operating point, so the model's headline
  property — "a physically meaningful zero-cost point" — quietly fails, and the reported
  reactive cost acquires a floor that is an artefact of the constraint shape rather than the
  machine. Nothing in the code, the tests, or the docstring says so.

Separately, a grid-code leading-PF figure is a **capability requirement** ("the unit shall be
able to operate down to 0.86 leading"), and it is being used here as an **operating
prohibition** ("the unit may not go below 0.86 leading"). Those are different statements. The
docstring argues the ray is preferable to "an arbitrary fraction of the theoretical stability
limit", and the criticism of the thing it replaced is fair — but the replacement introduces
the artefact above. The honest framing is: this is a *policy* constraint standing in for a
*physical* one, and it binds before the physics does at low P.

---

## 5. Parameters — sourced, or illustrative?

`machine.py` itself contains **no numeric machine parameters at all** — only structure and
conversions. That is good design and the right answer to "where do I look for the
assumptions". The numbers live in `tests/test_machine.py::g1()/g2()` and
`run_experiments.py::machines()`.

**Verdict: mostly and unusually well sourced, with two presentation risks and one substantive
parameter error.**

- ✅ `x_d_pu = 1.087`, `r_a_pu = 0.002`, `cos_phi = 0.90`, `rotor_loss_frac =
  (15.88 + 175.78)/103_000` — **all four verified by me against the PDF** (Tables I, II and the
  Table V caption). The claim "verified directly against the PDF (not a summary)" in
  `run_experiments.py` is accurate. This is materially better than the "representative,
  not measured" fallback the project spec anticipated.
- ✅ `run_experiments.py` explicitly labels Type B (`x_d = 1.3`, `rotor_loss_frac = 0.0024`) as
  illustrative, with a stated reason for keeping `R_a` and `cos φ` at the cited values, and
  labels the sizes and bus placements `[ASSUMED]`. Good practice.
- ⚠️ **Presentation risk 1:** `tests/test_machine.py:15-20` puts the comment "Karekezi …
  103 MVA reference machine, verified directly against the PDF" directly above
  `Machine.from_nameplate("G1", 8.0, ...)` — an **8 MVA** machine. The *per-unit* parameters
  transfer; the machine does not. A reader (or a panel member skimming the repo) will read
  that as "we modelled the 103 MVA unit". One added clause fixes it.
- ⚠️ **Presentation risk 2:** `g2()` in the test file carries **no comment at all** and sits
  immediately under the cited `g1()`. The illustrative-vs-cited distinction that
  `run_experiments.py` makes carefully is lost in the file a reviewer is most likely to open.
- ❌ **Substantive:** `r_a_pu = 0.002` is the wrong coefficient for this loss term — see H1
  below.

---

## 6. Test coverage — I ran them, and then I attacked them

### 6.1 Actual run

```
$ .venv/bin/python -m pytest tests/test_machine.py -v
...
============================= 21 passed in 33.74s ==============================
```

All 21 pass. (Note: bare `python` is not on PATH; `python3` has no pytest. The venv
interpreter at `.venv/bin/python` is the one that works — worth a README line.)

### 6.2 Are they as strong as they look? Mutation test.

Every loss/`Q*`/capability unit test evaluates at **`v = 1.0` only** — the one voltage at
which `V` and `V²` are indistinguishable. Since V is a *decision variable* in the OPF and is
bounded to [0.95, 1.05], that is precisely the exponent that matters and precisely the one the
tests cannot see.

I made seven single-token edits and ran the full file against each (file restored and verified
byte-identical afterwards):

| Mutation | 8 machine-unit tests | Full 21-test file |
|---|---|---|
| `q_star`: `V²` → `V` | **8 passed** | **21 passed** ❌ not caught |
| field circle centre `V²` → `V` | **8 passed** | **21 passed** ❌ not caught |
| field circle radius `V` → `V²` | **8 passed** | **21 passed** ❌ not caught |
| stator loss `/V²` → `/V` | **8 passed** | **21 passed** ❌ not caught |
| `stator_limit` → `(V·S_rated)²` | **8 passed** | **21 passed** ❌ not caught |
| field loss `X_s·q/v` → `X_s·q` | 8 passed | 1 failed ✔ caught |
| `marginal_loss` `q/V²` → `q/V` | 8 passed | 1 failed ✔ caught |

**5 of 7 survive the entire suite.** The two that are caught are both caught by the *same*
test — `test_price_at_unconstrained_generator_equals_its_marginal_cost` — which is the only
test in the file that evaluates the machine model at an off-nominal voltage, and it only
catches *inconsistency* between `loss` and `marginal_loss`. A voltage-exponent error made
*consistently* in both (which is what a real typo looks like) sails straight through.

The most alarming survivor is `q_star: V² → V`, because `Q*` is the zero of the cost function
and therefore sets the intercept of every price the study reports.

### 6.3 Test-by-test assessment

| Test | Verdict |
|---|---|
| `test_q_star_is_negative` | Weak but fine as a sign-flip guard. Only `v=1.0`; sign is algebraically inevitable for positive parameters, so it can only catch a literal `-` deletion. |
| `test_loss_minimum_at_q_star` | **Genuinely good.** 200,001-point argmin, grid spacing 5.7e-5 vs. tolerance 1.9e-3 — comfortably resolved. Independent of the analytic formula. Only weakness: one machine, one P, `v=1.0`. |
| `test_cost_is_nonnegative` | Passes but is mathematically guaranteed (§3.1) — it can never fail. Not wasted (guards against a future refactor breaking the identity), but it verifies less than its name suggests. Only `v=1.0`, one P. |
| `test_capability_limits_consistent` | Restates the code's own algebra at `P=0, v=1.0`. At `v=1.0` it cannot distinguish the `V²` centre from the `V` radius — see the mutation table. |
| `test_ef_max_derived_from_rated_point` | Good and meaningful (the rated point must lie on the field circle), but again `v=1.0`. |
| `test_base_change_is_self_consistent` | Checks only `s_rated` and `x_s`. Does **not** check `k_f`'s inverse scaling, nor that `loss` and `q_star` scale as powers — which is where a base-conversion bug would actually bite. |
| `test_underexcitation_is_a_pf_ray_through_origin` | Good — checks linearity and the ray, both branches. |
| `test_rotor_loss_frac_recovered_at_rated_point` | Good, and correctly accounts for the base (`× m.s_rated`). This is the test that pins `k_f`'s calibration. |
| `test_price_at_unconstrained_generator_...` | **The strongest test in the file.** Cross-checks a hand-written derivative against Pyomo's autodiff via the dual — genuinely independent implementations. Carries the entire V-sensitivity of the suite on its own. |
| **missing** | No test of `stator_limit` — at all. |
| **missing** | No test that `Q*` is P-independent. |
| **missing** | No direct finite-difference check of `marginal_loss` vs `loss` (currently only via the solver, so it needs IPOPT to run at all). |
| **missing** | No test at `v ≠ 1.0` of anything in `machine.py`. |

### 6.4 File scope

Only **8 of 21** tests in `tests/test_machine.py` test `machine.py`. The other 13 exercise the
OPF, power-flow residual, dual/unit conversion, thermal limits, settlement and a
four-generator fleet — all requiring IPOPT. That is why the "machine unit tests" take 34 s
instead of 0.5 s. The machine-only subset runs in ~7 s, and most of that is imports.

---

## 7. Issues, ranked

### H1 — Stator loss coefficient omits stray load loss; `Q*` is ~25% too negative as a result **(highest impact, one-line fix)**

The paper's eq. (4) is `P_l,s = (P_a* + P_s*)(I_a/I_a*)²` — armature copper **and stray load
loss**, both `I²`-dependent, both in the same term, `276.62 kW` total for the 103 MVA machine
(`= 0.0026862 pu`). The code uses `r_a_pu = 0.002` — the Table II *armature resistance*, which
accounts for `0.002 × 103 MVA = 206 kW`. **The remaining 70.6 kW of `I²`-dependent stray loss
is silently dropped.**

I reproduced the paper's model and peeled the approximations off one at a time (P = 0.3, 0.6,
0.9 — all identical, confirming P-independence):

| Model | `Q_opt` (pu, machine base) |
|---|---|
| code as written (round rotor, all-quadratic rotor, `R_a`=0.002) | **−0.2392** |
| + paper's stator coefficient `(P_a*+P_s*)` | **−0.1908** |
| + paper's eq. (5) rotor split (linear + quadratic in `I_f`) | −0.1870 |
| + salient-pole `E_f` (`X_d ≠ X_q`) | −0.2018 |
| paper's own answer, text and Fig. 2 | **"about −0.2 pu"** |

So: **the single largest contributor to the model's disagreement with its own source is not
any of the three structural approximations the docstring apologises for — it is the stator
coefficient.** Fixing that one number moves `Q*` from −0.2392 to −0.1908 and into agreement
with the paper's headline. The salient-pole correction is worth ~8%; the rotor-split
correction ~2%.

Impact on the results, not just on `Q*`: the marginal cost is `λ_E · 2a(Q − Q*)` with
`a = R_a + k_f X_s²` (machine base: 2.703e-3 as coded, 3.389e-3 corrected). So the code
**understates the marginal-cost slope by ~20%** *and* misplaces its zero by ~25%. Both the
intercept and the gradient of the Case B price curve move. Against a headline anchor like
0.28 €/MVArh that is not a rounding error.

The docstring's line — "attributable to the structural differences above, not a bug" — is,
on my analysis, **not correct**. It is mostly attributable to a parameter choice, and it is
fixable without any structural change.

*Fix:* `r_a_pu = (276.62)/103_000  # = 0.0026862 pu; Table I, P_a*+P_s*, eq. (4)` and rename
the field to something like `stator_loss_coeff` so it is not mistaken for the Table II
resistance. Then re-run everything and update the docstring's cross-check paragraph — it will
read much better at −0.191 vs "about −0.2".

### H2 — The tests cannot see any voltage-exponent error

Demonstrated in §6.2: 5 of 7 mutations survive all 21 tests, including `q_star: V² → V`.
Every machine-model assertion is made at `v = 1.0`. This is the single cheapest thing to fix
and the one most likely to be silently protecting a real bug in future edits.

*Fix:* `@pytest.mark.parametrize("v", [0.95, 1.0, 1.05])` on every machine test, plus one
explicit scaling test:
`assert m.q_star(1.05) / m.q_star(1.0) == pytest.approx(1.05**2)`.
That alone kills 4 of the 5 survivors.

### M1 — Underexcitation limit shape makes `Q*` infeasible below P = 0.403 pu

See §4.4. A PF ray through the origin has no offset term; SynGenLib and classical theory both
use `Q_min = m·P − V²/X_s`. Consequences: no reactive absorption permitted at P = 0, and the
zero-cost point unreachable across P ∈ [0.15, 0.40] pu, which silently puts a floor under the
reported reactive cost in that band. Undocumented and untested.

*Fix (cheapest honest version):* keep the PF ray if that is the intended policy statement, but
(a) say in the docstring that it is a policy constraint standing in for a physical one, (b) add
the `−V²/X_s` offset or take the max of the two limits, and (c) add a test/diagnostic that
flags the P range where `Q*` is infeasible, and report it.

### M2 — Stator limit is an MVA circle, not a current limit

See §4.3. Permits up to +5.3% overcurrent at V = 0.95. `stator_limit` accepts `v` and ignores
it. Untested (the mutation to the correct form passes everything).

*Fix:* `return p**2 + q**2 - (v * self.s_rated)**2`, or delete the unused `v` and document
that a rated-voltage circle is intended. Do not leave it ambiguous.

### M3 — Core loss omitted entirely; no total-loss or efficiency number from this model is safe to quote

The paper's eq. (6) is `P_l,c = P_c*(U_a/U_a*)² + P_be* + P_wf*`; SynGenLib's Pyomo model
carries `P_loss_core = P_c* · V_g² · S_n` as one of its four loss terms. The code has
neither — `p_const` is the only placeholder, and it is `0.0` everywhere in the repo.

For the reference machine, `P_c* = 211.92 kW` — **larger than the entire rotor loss the model
does include** (191.66 kW) — and `P_be*+P_wf* = 413.82 kW`. Together 625.74 kW = 0.00607 pu,
against `ΔP_l` values of 0–0.005 pu (the paper's own Fig. 3(a) range). So the omitted constant
and core losses are **larger than the entire quantity being priced**.

This does **not** affect prices: a term in V only (or a constant) cancels exactly out of
`C^Q = λ[P_loss(Q) − P_loss(Q*)]` at the same V. But any figure, table or slide reporting
"generator losses" or machine efficiency from this model is understated by ~0.6% of rating.

Note the stated reason for the other omissions (implicit/root-solve, not Pyomo-embeddable)
does **not** apply here — `P_c·V²` is closed-form, differentiable, and already in SynGenLib's
Pyomo model.

*Fix:* add `p_core` and `p_const` from Table I and use them, **or** state explicitly in the
docstring and README that `loss()` returns only the Q-dependent loss components and must not
be used for efficiency reporting.

### M4 — Citation placement in `tests/test_machine.py` reads as stronger than it is

`g1()`'s comment says "103 MVA reference machine" above an 8 MVA construction; `g2()` carries
no illustrative label even though `run_experiments.py` correctly labels the same numbers as
illustrative. Cheap to fix, and it is exactly the kind of thing a panel will pick up on.

*Fix:* change the `g1()` comment to "*per-unit* parameters from the 103 MVA reference machine,
applied here to an 8 MVA unit", and copy `run_experiments.py`'s Type B disclaimer onto `g2()`.

### L1 — No input validation

`Machine` is a frozen dataclass with no `__post_init__`. Observed:
- `from_nameplate(..., p_max_pu=0.85, p_min_pu=0.9)` is accepted silently (`p_min > p_max`).
- The docstring's "`p_max_pu` should sit below `cos_phi`" is advice, not a check.
- `q_star(0.0)` returns `-0.0` without complaint, while `loss(p, q, 0.0)` raises — inconsistent.
- `r_a = 0` with `rotor_loss_frac = 0` gives `ZeroDivisionError` inside `q_star` (0/0).

### L2 — `E_f` neglects `R_a` in the phasor relation while `R_a` is kept in the stator loss

Standard and negligible here, but it belongs in the docstring's otherwise-complete list of
declared approximations.

### L3 — Naming

`marginal_loss(q, v)` is `∂P_loss/∂Q` specifically; `dloss_dq` would say so. `q_star(v)`
implements what the spec calls `Q*(P)` — the P-independence deserves a one-line docstring
note (with the Fig. 2(a) evidence from §2.1) rather than being inferable only from the
signature.

### L4 — `tests/test_machine.py` is a whole-system test file wearing a unit-test name

13 of 21 tests need IPOPT. Split into `test_machine.py` (fast, pure, no solver) and
`test_opf.py` / `test_settlement.py`. The machine model should be testable in under a second,
which is what makes parameterising over V (H2) free.

---

## 8. Concrete suggestions, in the order I'd do them

1. **Fix `r_a_pu` → 0.0026862** (H1), rename the field, re-run, and rewrite the docstring's
   cross-check paragraph. The model then agrees with its source's headline number, and the
   disclosure gets *stronger*, not weaker. This is the highest-value change in the file.
2. **Parameterise every machine test over `v ∈ {0.95, 1.0, 1.05}`** and add an explicit
   `Q* ∝ V²` test (H2). Cheap; kills most of the mutation survivors.
3. **Add a `syngenlib` cross-validation test.** The library is already installed and pinned at
   a specific commit in `requirements.txt`. A test asserting that this model's `E_f²`,
   field-circle `(centre, radius)` and `E_f,max`-from-rated-point agree with
   `syngenlib`'s `GeneratorCalculationModel` / `CapabilityModelDataclass.default_limits` to
   1e-12 would convert the docstring's provenance narrative into a machine-checked fact. Based
   on what I read, **it will pass** — the formulas are identical. This is the strongest single
   slide available from this part of the codebase, and the project's own notes assumed the
   library was unavailable when it is sitting in the venv.
4. **Document the `Q*`-infeasibility band** (M1) and either add the `−V²/X_s` offset or state
   the policy-vs-physics substitution explicitly. Report the P range where the zero-cost point
   is unreachable — it is an interesting result, not just a caveat.
5. **Decide the stator limit** (M2): V-scale it or drop the unused argument and say why.
6. **Add core/constant losses or forbid efficiency reporting** (M3). Either is fine; silence
   is not.
7. **Fix the two citation comments** in the test file (M4).
8. **Add `__post_init__` validation** (L1) and split the test file (L4).
9. Add the two cheap missing tests: `stator_limit` geometry, and `marginal_loss` vs a central
   finite difference of `loss` (so the derivative check no longer depends on IPOPT).
10. Put the two numbers I computed in §4.2 and §2.1 into the docstring — round-rotor costs
    ~1–2% on the capability boundary and ~8% on `Q_opt`; `Q_opt`'s P-independence is supported
    by the source's own Fig. 2(a) (−0.194…−0.203 over the full P range). Quantified caveats
    read as confidence; unquantified ones read as worry.

---

## 9. Summary judgement

The physics in this file is, with one exception, **correct**. I re-derived the field EMF, the
total loss, `Q*`, the marginal loss and both capability circles independently, and the code
matches my derivations term for term and sign for sign. `Q*` is correctly negative for the
right structural reason, correctly independent of P, correctly proportional to `V²`, and
correctly base-invariant. The cost function is non-negative by construction — provably, as
`λ_E·a·(Q−Q*)²` — smooth, and faithful to the source's own eq. (2). The field circle is exactly
right and internally consistent with the loss model. The disclosure of approximations is
unusually honest, and the parameters are genuinely sourced — I opened the PDF and every cited
number checked out.

The three things I would not let go to a slide as they stand:

1. **`r_a_pu = 0.002` is the wrong coefficient** (it should be `0.0026862`, armature + stray,
   per the source's own eq. 4). This is the dominant cause of the model's ~25% disagreement
   with its source on `Q*`, and it moves the Case B price curve's slope and intercept by
   ~20–25%. The docstring currently attributes that disagreement to structural
   approximations; my reproduction of the paper's model shows otherwise.
2. **The tests cannot detect a voltage-exponent error anywhere in the model** — demonstrated,
   not suspected: 5 of 7 single-token mutations pass all 21 tests.
3. **The 0.86-leading-PF ray makes the model's own zero-cost point infeasible below
   P = 0.403 pu**, which silently floors the reported reactive cost across a realistic
   operating band, and is nowhere documented.

None of these is a formulation error in the sense of "the equation is wrong". All three are
the kind of thing that quietly changes a headline number, which — given the audience — is the
category that matters most.
