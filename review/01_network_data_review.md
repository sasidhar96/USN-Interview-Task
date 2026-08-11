# Review 01 — Network data, demand data, and case integration

Independent first-look review. Scope: `src/case_data.py`, `data/raw/`, `data/processed/`,
the integration path from network + demand + generator capacity into a per-hour OPF case,
and the divergence between the code and `CLAUDE.md` / `DESIGN.md`.

Explicitly **out of scope** and not read for review purposes: `src/machine.py` (loss model),
`src/cost_models.py`, `src/opf.py` (formulation/objective/solver), `src/settlement.py`.
I did read the *interface* lines of `opf.py` (how it ingests the pandapower net) and the
generator sizing constants in `run_experiments.py`, because question 3 cannot be answered
without them. I have not formed or recorded any opinion on the loss model, objective,
solver behaviour or settlement logic.

---

## 1. What I looked at, and how

- Read `src/case_data.py` in full (222 lines).
- Listed and opened `data/raw/` and `data/processed/`; read the four CINELDI grid folders'
  `mpc_bus.csv`, `mpc_branch.csv`, `mpc_base_mva.csv`, `branch_extra.csv`, `load_bus_extra.csv`,
  and the `p_load.csv` / `q_load.csv` time series.
- Reconstructed the CIGRE MV benchmark from `pandapower.networks.create_cigre_network_mv`
  and inspected its bus/load/line/trafo/switch tables directly rather than trusting the docstring.
- Ran independent numerical checks (statistics below are all computed, not quoted):
  per-column load statistics, timestamp continuity, per-unit base consistency, implied
  cable Ω/km against catalogue values, graph connectivity of every CINELDI grid, realised
  power factor after the shape mapping, realised annual demand under `build_case_from_hour`
  vs installed generation, and a plain power flow on the LV diagnostic case.
- Cross-checked the dataset against its own data paper (Engan, Ekrheim, Bjarghov, Klemets,
  Schytte & Kjølle, *Data in Brief* 59 (2025) 111453), text available in `tmp/pdfs/norwegian_dataset.txt`.
- Read `CLAUDE.md`, `DESIGN.md`, `IMPLEMENTATION_PLAN.md`, and the relevant sections of `README.md`.

---

## 2. Question 1 — What network does `case_data.py` define, and is it internally consistent?

`case_data.py` defines **two** networks, not one.

### 2.1 The study network: CIGRE MV benchmark (`build_case`, `build_case_from_hour`)

Loaded from `pandapower.networks.create_cigre_network_mv(with_der=False)`. Verified directly:

| Quantity | Value (verified) |
|---|---|
| Buses | 15 (bus 0 = 110 kV; buses 1–14 = 20 kV) |
| Loads | 18 load records across 13 buses (1, 3–14 except 2) |
| Lines | 15, R/X = 0.501/0.716 = **0.70** on feeder 1, 0.510/0.366 = 1.39 on feeder 2 |
| Transformers | 2 × 25 MVA, 110/20 kV, vk 12.0 %, Dyn (30° shift) |
| Ext grid | bus 0, vm_pu 1.03 |
| Nominal demand | 44.742 MW / 11.040 MVAr |
| Switches | S1 (14–8), S2 (6–7), S3 (11–4) all **open** → radial |

The docstring's headline numbers ("R/X ~ 0.70, 44.7 MW / 11.0 MVAr nominal", 20 kV) are
correct. This is a published benchmark used as-is, so per-unit / unit consistency is
inherited and I found nothing wrong with it.

Two structural facts the docstring gets right and that matter downstream:
- With S1/S2/S3 open the network is genuinely radial and splits into **two independent
  feeders behind two separate transformers** — feeder 1 = buses 1–11, feeder 2 = buses 12–14.
  `GEN_BUSES = {G1: 3, G2: 10, G3: 13, G4: 14}` therefore does put G1/G2 on feeder 1 and
  G3/G4 on feeder 2, as claimed. Path 1→2→3→8→9→10 confirms G2 is 5 hops out. The
  area-wise-uniform (AWU) zone definition in `DESIGN.md` §5 rests on a real topological
  split, not an invented one.
- CIGRE MV is extremely skewed: buses 1 and 12 carry 19.839 and 20.010 MW respectively
  = **89.1 %** of total demand, all 11 other buses < 1 MW. The docstring's numbers here
  are exactly right.

**One physical inconsistency in the study network that is created by the code, not by
CIGRE**, discussed under §5.3: feeder-1 lines are rated `max_i_ka = 0.145` at 20 kV, i.e.
√3·20·0.145 = **5.02 MVA per circuit**, while 13 MVA of generation (G1 8 MVA + G2 5 MVA)
is placed behind them. Every base-case solve in `results/base_case.csv` reports
`max_line_loading_pct = 100.0` in all four cost cases — the network is thermally saturated
at the base operating point in every case.

### 2.2 The diagnostic network: CINELDI 50-bus rural LV (`build_network`, `build_rural_case`)

Built by hand from the MATPOWER-style CSVs. Per-unit consistency checked from first
principles and it **passes**:

- `mpc_base_mva.csv` = 0.0344 MVA, `basekV` = 0.23 kV → Z_base = 0.23²/0.0344 = **1.5378 Ω**.
- Converting the published pu impedances back to Ω/km using `branch_extra.csv` lengths gives
  median **1.200 Ω/km for "EX 3x25 Al"** and **0.320 Ω/km for "EX 3x95 Al"** — exactly the
  catalogue resistances for those cables. Reactances come out at ~0.082 Ω/km, also correct.
  This is strong independent confirmation that the base quantities and the pu convention are right.
- `pp.create_impedance(..., rft_pu=r, xft_pu=x, sn_mva=base)` on a net created with
  `sn_mva=base` is the correct way to inject MATPOWER pu impedances — the two bases agree,
  so no rescaling error. Confirmed by running `pp.runpp`: 3.2 % losses and Vmin = 0.921 pu at
  the annual peak-apparent hour, against the data paper's own reported 0.901 pu minimum.
  The ~2 pp gap is unexplained (see issue M6) but the model is clearly in the right regime.
- Median branch R/X = **7.45**, length-weighted 7.02 — the docstring's "R/X ~ 7.5 in LV cable"
  is correct.

---

## 3. Question 2 — What is the demand data?

### 3.1 Source and nature

`data/raw/cineldi_lv/dataset/` holds the four reference grids from **Engan et al. (2025),
*Data in Brief* 59:111453, Zenodo 10.5281/zenodo.14528192** — anonymised real Norwegian LV
distribution grids from Lede AS. `data/raw/dataset.zip` is the untouched 8.5 MB download.
`data/processed/` is **empty** — nothing is checkpointed; every derived series is recomputed
from raw on each call.

The code uses only `50_bus_rural_reference_grid`: 50 buses, 49 branches, 21 consumers
("Private building" per `load_bus_extra.csv`; the paper says houses, small farms and one
office building), price area NO2, calendar year 2021.

**Real or synthetic?** This distinction is handled correctly by the code's grid choice, and
it is worth recording explicitly because it is not obvious:

- For the two **semi-urban** grids the paper states the profiles are matched from a separate
  residential dataset and *"the reactive power of each load is calculated by assuming a
  constant power factor of 0.98"* — i.e. Q is **synthetic** there.
- For the two **rural** grids the paper states *"the rural grids have their original load
  profiles"*. The 50-bus grid used here is rural, so both P and Q are **measured**.

So the README's claim that the reactive series is measured rather than PF-derived is correct.
But see H2 — "measured" is not the same as "usable" for several of these channels.

### 3.2 Verified properties of the series

| Check | Result |
|---|---|
| Rows | 8760 in both `p_load.csv` and `q_load.csv` |
| Index | 2021-01-01 00:00 → 2021-12-31 23:00, strictly hourly, zero gaps |
| P/Q index equality | identical (the code asserts this — good) |
| Columns | 21, headers are the CINELDI bus numbers |
| NaNs / negatives | none |
| System P peak | 114.0 kW; system Q peak 15.6 kVAr |
| Timezone | fixed **UTC+1**, no DST (per paper §3.11); code parses naive timestamps |

`load_profiles` correctly raises if the P and Q indices differ or if the row count is not
8760. Both guards are appropriate. No resampling is performed anywhere — the data is
already hourly and is consumed hourly.

### 3.3 Units — the code is right, the source paper is wrong, and nothing says so

The data paper §3.11 states the CSVs contain *"hourly load data in the units kWh/h and
kVArh/h"* — i.e. kW and kVAr. The code's `load_profiles` docstring says **MW and MVAr**, and
`build_network` passes the raw numbers straight into `p_mw=` / `q_mvar=`.

I resolved this against three independently published statistics in the same paper:

| Paper statement (§3.5) | Computed from the CSVs treating the numbers as MW |
|---|---|
| "highest peak load … at node 42 with a peak of 27 kWh/h" | 27.1 kW ✓ |
| "the average of all peak loads in the grid is 8.11 kWh/h" | 8.11 kW ✓ |
| "The average yearly load is 20.73 MWh" | 20.73 MWh ✓ |

All three match exactly. **The file numbers are MW/MVAr and the code is correct**; §3.11 of
the paper is an error. This is a 1000× trap that the repo currently documents nowhere —
see issue M5.

### 3.4 Association with buses and time steps

Column header → CINELDI bus number → `pp.create_load` at the mapped pandapower bus, one
load per column, at the single timestamp requested. Row index → hour. Straightforward and
correct for the diagnostic case. For the study case the association is indirect and is where
the substance is; see §4.

---

## 4. Question 3 — Integration: how the per-hour OPF case is actually formed

There are two independent paths, and it is important which results come from which.

### Path A — uniform stress sweep (`demand_shapes` → `build_case(p_scale, q_scale)`)

```
p_scale(t) = Σ_buses P(t) / max_t Σ_buses P(t)          # ONE national scalar
q_scale(t) = Σ_buses Q(t) / max_t Σ_buses Q(t)          # normalised INDEPENDENTLY
net.load.p_mw *= p_scale ;  net.load.q_mvar *= q_scale  # applied to every CIGRE bus
```

### Path B — per-bus real hour (`bus_demand_shapes` → `build_case_from_hour(timestamp)`)

Each of the 13 CIGRE load buses is assigned a group of real CINELDI households via
`CIGRE_TO_CINELDI_GROUPS`; the group's raw P and Q are **summed** (correct — that is what
physical aggregation is), then each channel is normalised by **its own annual peak** and
used as a multiplier on CIGRE's published nominal values.

I verified the mapping arithmetic and it is exactly as the comment claims: group sizes
4/4/2/2/1×9 = 21, every one of the 21 households used exactly once, none reused, none left
over; the two 4-household groups go to buses 12 and 1 (the two ~20 MW buses); the two
2-household groups go to buses 5 (0.7275 MW) and 8 (0.5869 MW), which are indeed the next two
largest. All 13 CIGRE load buses are covered — no bus is silently left unscaled.

### What consumes what — a divergence worth knowing

| Runner | Case builder | Demand actually used |
|---|---|---|
| `run_experiments.py` runs 1, 3, 4, 5, 7 | `build_case(1.0, 1.0)` | **CIGRE nominal, 44.74 MW — no CINELDI data at all** |
| `run_experiments.py` run 2 (load sweep) | `build_case(scale, scale)` | linear 0.40→1.50, **no CINELDI data** |
| `run_experiments.py` run 6 (seasonal) | `build_case(p_s, q_s)` | Path A |
| `run_monthly_analysis.py` | `build_case_from_hour(ts)` | Path B |
| `explore_lv_case.py` | `build_rural_case` | CINELDI topology + load, LV |

So the module docstring's framing — "CIGRE MV topology **driven by** Norwegian CINELDI
demand shapes" — overstates the role of the demand data in the headline results. The base
case, the load sweep, the price sensitivity, the water-value sweep, the six-scheme
settlement comparison and the local-optimum check are all solved at the **CIGRE nominal
point**, untouched by any Norwegian measurement. The CINELDI data drives only the seasonal
run and the monthly analysis. That is a defensible design, but it is not what the docstring says.

### Generator capacity vs demand

`run_experiments.machines()` fixes G1 = 8, G2 = 5, G3 = 6, G4 = 3 MVA (22 MVA nameplate,
`p_max_pu = 0.85` → 18.7 MW of active capability), justified in-code as *"22 MVA vs. 44.74 MW
nominal feeder demand (49 %)"*. That ratio is correct **for `build_case(1.0,1.0)`**.

It is not correct for Path B. Realised CIGRE demand across all 8760 hours under
`build_case_from_hour`:

| | P (MW) | Q (MVAr) |
|---|---|---|
| min | 4.19 | 0.65 |
| median | 13.76 | 2.90 |
| mean | 14.81 | 2.95 |
| max | 37.09 | 7.29 |
| nominal | 44.74 | 11.04 |

Installed active capability (18.7 MW) therefore **exceeds total feeder demand in 6679 of
8760 hours (76 % of the year)**, and is 136 % of demand at the median hour. Combined with
`c^P = 0` this makes the feeder export-dominated for most of the year. The repo has already
felt this — the `S_INTERFACE_MAX = 50.0` comment in `run_experiments.py` records the symptom
("12.6 MW of generation against 4.3 MW of local demand, all 'exported' through an interface
with no capacity limit") and patches it with a cap rather than revisiting the sizing.

### Unit conversions across the boundary — checked, and clean

- `build_case*` returns a pandapower net with `sn_mva = 1.0` (CIGRE MV default).
- `opf.load_grid` runs `pp.runpp` then reads `net._ppc`, taking `base = ppc["baseMVA"]`,
  and builds Ybus with `makeYbus`. This means the **open switches S1/S2/S3, both 25 MVA
  transformers, the transformer phase shift and line charging are all correctly represented** —
  there is no hand-built Y-bus and no opportunity for a topology transcription error.
- `run_experiments.S_BASE = 1.0` MVA matches `net.sn_mva = 1.0`, so machine per-unit
  quantities and network per-unit quantities share a base. Consistent.
- `explore_lv_case.py` hardcodes `S_BASE_MVA = 0.0344` to match `build_rural_case`'s
  `sn_mva`, which is currently right but is a duplicated constant (issue L4).

I found **no MW/kW/pu mismatch** on this path. The dangerous conversion (§3.3) is upstream
of it and the code handles it correctly.

---

## 5. Concrete issues, ranked by severity

### HIGH

**H1 — Independent P/Q normalisation systematically distorts the power factor, which is the
one quantity the whole study exists to price.**

`p_scale` and `q_scale` are each divided by their **own** annual maximum. Because the P peak
and the Q peak occur at different hours, this multiplies the modelled tan φ by a constant:

```
tan φ_applied = tan φ_CIGRE · (q_scale/p_scale)
              = tan φ_CIGRE · (P_peak/Q_peak)_real · tan φ_real
```

For the system-wide shape (Path A) that constant is 0.2467 × (0.1140/0.0156) = **1.803**.
Every hour of the sweep and every seasonal point carries a power factor 1.8× more inductive
in tan φ than the real Norwegian data it is derived from:

| | real CINELDI | applied after `build_case(p_s, q_s)` |
|---|---|---|
| median tan φ | 0.150 | 0.271 |
| max tan φ | 0.422 | 0.761 (pf 0.796) |

Path B is better but still biased: median applied tan φ 0.210 vs 0.150 real (1.4×), worst
hour pf **0.760** against a real worst of 0.92. A worst-hour 0.76 power factor on a
Norwegian MV feeder is not a realistic operating point — Lnett's own deadband sits at
tan φ 0.30 (pf 0.96), per `DESIGN.md` §2.1.

This biases the study **toward** finding reactive scarcity, i.e. in the direction that
flatters its own conclusion. It is not a small effect and it is not documented anywhere.

*Fix:* normalise Q by the **same** reference as P (e.g. `q_sum / p_sum.max() × (P_nom/Q_nom)`),
or better, drop `q_scale` entirely and reconstruct bus reactive demand as
`Q(t) = P_scaled(t) × tan φ_real(t)` so the measured hour-by-hour power factor is preserved
exactly. Either fix is a few lines and removes the bias.

---

**H2 — Several CIGRE buses inherit a degenerate reactive profile from meters that do not
record reactive power.**

The per-column reactive series are of very uneven quality. `q_scale == 0` counts after mapping:

| CIGRE bus | CINELDI household | hours with Q = 0 exactly | unique Q values in the year |
|---|---|---|---|
| 6 | "36" | **8758 / 8760** | **3** |
| 4 | "43" | 5889 / 8760 | 307 |
| 10 | "39" | 4321 / 8760 | 138 |
| 5 | "25", "29" | — | 28 for "25" |

CIGRE bus 6 therefore carries **exactly zero reactive demand for the entire year except two
hours**, in which it jumps to its full nominal 0.1374 MVAr. Worse, the peak it is normalised
against is a single 56 VAr sample — the code amplifies one probably-spurious meter reading
by a factor of ~2450 into a full-nominal MV reactive load.

A consequence: the cross-bus correlation of the reactive shapes has **median 0.01** — the
13 buses' reactive demands are essentially statistically independent of one another. That is
physically implausible for a distribution network, where reactive demand is driven by the
same load population as active demand. The reactive input signal is the weakest part of the
data, and it is precisely the signal that defines the scarcity being priced.

*Fix:* screen the reactive channels (e.g. reject any column whose unique-value count or
non-zero fraction falls below a threshold) and either exclude those households from the
mapping or derive their Q from the group's own measured tan φ. Whatever is chosen, the
screening should be explicit and reported.

---

**H3 — The fleet is sized against a demand level that never occurs in the time series used
for the monthly results.**

Detail in §4. 18.7 MW of active capability against a realised median of 13.76 MW means the
feeder is a net exporter in 76 % of hours under Path B. The "49 % of nominal" justification
in `run_experiments.machines()` is measured against `build_case(1.0,1.0)`, which is the right
comparator for `run_experiments.py` but the wrong one for `run_monthly_analysis.py`.

*Fix:* either resize the fleet against the realised demand distribution (e.g. target ~50 %
of the *median* or *P90* realised hour rather than of the nominal point), or state plainly
that the monthly results describe a heavy-export regime and are a study of export-driven
reactive coordination, not of a demand-constrained feeder. The second is cheaper and honest;
the first is more defensible.

---

### MEDIUM

**M1 — Single-household shapes stand in for MV buses, with an unquantified load-factor penalty.**

The README acknowledges this qualitatively. The magnitude is worth stating: household "48"
(→ CIGRE bus 11) has a load factor of 0.061, so CIGRE bus 11's 0.33 MW nominal becomes ~4 kW
at the median hour. Realised network-wide load factor under Path B is **0.399**, against
0.5–0.7 typical for a real MV feeder. Nine of thirteen buses are driven by a single house.
The two 4-household buses (which are 89 % of demand) largely rescue the aggregate, but the
small buses are effectively switched off most of the year, which changes where reactive
demand sits on the feeder and therefore where the nodal reactive prices land.

**M2 — The `grid=` parameter is a trap: only 2 of the 4 shipped grids will load.**

`load_profiles(grid=...)` and `build_network(grid=...)` accept any of the four folders, but:

| Grid | `mpc_base_mva.csv` | type-3 slack rows | profile header problem |
|---|---|---|---|
| 39_bus_semi_urban | **0** | **0** | duplicate bus id → pandas mangles to `"30.1"` |
| 56_bus_semi_urban | **0** | **0** | 9 mangled columns (`"54.1"`…`"52.1"`) |
| 50_bus_rural | 0.0344 | 1 | none |
| 80_bus_rural | 0.015967 | 1 | none |

On the two semi-urban grids `build_network` would call `create_empty_network(sn_mva=0)`,
then raise `IndexError` on `bus_df.loc[bus_df.type == 3, "bus_i"].iloc[0]`, and if it got
past that, `int(col)` would raise `ValueError: invalid literal for int() with base 10: '30.1'`.
There is no guard and no docstring warning. (Also note the duplicate headers mean those grids
have multiple loads per bus, which the current one-column-one-load logic does not model.)

**M3 — `build_network` silently drops five columns of the source data.**

`status`, `ratio`, `angle`, `rateA` from `mpc_branch.csv`, and `Vmax`/`Vmin`/`Gs`/`Bs`/`Pd`/`Qd`
from `mpc_bus.csv` are all ignored. For the 50-bus grid today this is harmless (all
`status == 1`, all `ratio == 0`, all `Gs == Bs == 0`, and ignoring `Pd`/`Qd` correctly avoids
double-counting against the time series). But there is no assertion, so a different grid or an
updated Zenodo release would silently produce a wrong network. Dropping `rateA` in particular
means the LV diagnostic case has **no thermal limits at all** — worth knowing given M4.

**M4 — The stated justification for abandoning the CINELDI topology is partly wrong.**

The docstring argues *"There is no scarcity to price"* at LV. A plain power flow on
`build_rural_case()` at its own annual peak-apparent hour gives **Vmin = 0.921 pu** (the data
paper reports 0.901 pu over the full year). That is a real voltage problem, below the usual
0.95 statutory band. The honest argument is the *other* one the docstring makes — at
R/X ≈ 7.5, reactive power is an ineffective lever for voltage, so pricing it there is not
where the value is. That claim is stronger and survives scrutiny; "no scarcity" does not.

Related and smaller: *"The smallest unit that is still a synchronous machine (100 kVA) has
~120 kVAr of field-limited reactive capability"*. The field circle does allow 1.2 pu at P = 0,
but the **stator circle caps it at 1.0 pu = 100 kVAr**, so the deliverable headroom is 100 kVAr,
not 120. The multiple over the 15.6 kVAr feeder peak is 6.4×, not the ~8× the README quotes.
The conclusion is unchanged; the number should be corrected.

**M5 — Two upstream data contradictions are resolved correctly in code but recorded nowhere.**

1. **Units.** Data paper §3.11 says the CSVs are in kWh/h and kVArh/h. The code treats them
   as MW/MVAr. I verified the code is right against three of the paper's own published
   statistics (§3.3 above). A reviewer who checks §3.11 will conclude the model is 1000× off.
2. **Base MVA.** Paper Table 4 gives the 50-bus rural grid as **0.0334 MVA**; the shipped
   `mpc_base_mva.csv` says **0.0344 MVA**. The file is correct — with 0.0344 the implied cable
   resistances reproduce catalogue values exactly (1.200 and 0.320 Ω/km); with 0.0334 they
   would be 3 % off. This 3 % propagates into every impedance and hence every LV voltage result.

Neither resolution is documented. Both should be, with the evidence, since both are exactly
the kind of thing a panel will probe.

**M6 — Unexplained ~2 pp gap against the dataset's own published validation number.**

`build_rural_case()` + `runpp` gives Vmin = 0.921 pu; Engan et al. §3.5 report 0.901 pu for
the same grid at 230 V feeder voltage. The reconstruction is clearly in the right regime, but
this is a free, published validation point that the repo does not use. Reproducing it (or
explaining the difference — likely single-phase vs three-phase treatment, or the slack voltage
convention) would be a cheap credibility win.

---

### LOW

**L1 — `representative_hours()` is dead code.** Defined at line 47, never called anywhere in
the repo (`run_experiments.py`, `run_monthly_analysis.py` and `explore_lv_case.py` all compute
their own representative hours inline). Either use it or delete it — right now there are two
uncoordinated definitions of "representative hour" in the codebase.

**L2 — No caching; `build_case_from_hour` re-reads 3.7 MB of CSV on every call.**
Measured: 0.91 s per call, of which ~0.12 s is the raw CSV read and the rest is the group
sum/normalise. `run_monthly_analysis.py` calls it twice per hour; `results/monthly_hourly.csv`
has 2947 rows, so that is roughly **45 minutes of pure case reconstruction** per monthly run.
A single `@functools.lru_cache` on `load_profiles` and `bus_demand_shapes` removes essentially
all of it.

**L3 — `data/processed/` is empty.** The mapped per-bus shapes are recomputed from raw on
every run and never written out, so there is no diffable artefact and no way to see that the
mapping changed between two result sets.

**L4 — Duplicated base constant.** `explore_lv_case.py` hardcodes `S_BASE_MVA = 0.0344`
rather than reading `mpc_base_mva.csv`. Currently correct; would silently desync if the grid
or dataset version changed. One-line fix.

**L5 — The "0.24–0.47 bus-to-bus correlation" figure does not reproduce.**
Quoted in the `demand_shapes` docstring and in README as "checked directly". Computed:
raw household pairwise P correlation runs **−0.28 to 0.83** (median 0.44); at the mapped
group level, **−0.28 to 0.83** (median 0.47). The underlying point (correlation is well below
1.0, so the uniform shape is unrealistic) is sound and the argument survives; the specific
range quoted does not.

**L6 — Timezone convention undocumented.** The paper specifies fixed **UTC+1** with no DST.
The code parses naive timestamps, which is fine today, but the winter/summer seasonal split
in `run_seasonal` and any future coupling to a day-ahead price series both depend on this
and it is stated nowhere in the repo.

**L7 — `S_INTERFACE_MAX = 50 MVA` pools two independent transformers.** The 2 × 25 MVA
transformers feed two electrically separate feeders, and the AWU-zone argument in
`DESIGN.md` §5 depends on exactly that separation. A single 50 MVA pooled cap lets feeder 1
borrow feeder 2's transformer capacity, which is not physical. Two 25 MVA constraints would
be more faithful. (Flagged as network-data modelling; the constraint itself lives in the OPF,
which is another reviewer's scope.)

---

## 6. Question 4 — Divergence between the code and `CLAUDE.md` / `DESIGN.md`

### 6.1 `CLAUDE.md` describes a different study entirely, and has not been superseded in writing

`CLAUDE.md` is loaded as project instructions ("IMPORTANT: These instructions OVERRIDE any
default behavior"). It is comprehensively out of date:

| `CLAUDE.md` spec | Actually implemented |
|---|---|
| 3 buses, 2 generators | 15-bus CIGRE MV, 4 generators |
| 132 kV, S_base 100 MVA | 20 kV, S_base 1 MVA |
| Line 1–3: R 0.020, X 0.100; line 2–3: R 0.050, X 0.250 | CIGRE MV lines; none of these values appear anywhere |
| Load 1.20 pu, pf 0.95 lagging | 44.742 MW / 11.040 MVAr, pf 0.971 |
| Sweep P_D ∈ [0.60, 1.60] pu, 40 steps | scale ∈ [0.40, 1.50], 40 steps, of CIGRE nominal |
| Machine params: X_s 1.00/1.20, k_f 0.0012/0.0015, E_f,max 2.20/2.00 | Karekezi-sourced type A / illustrative type B, `E_f,max` derived from nameplate pf |
| Underexcitation limit `Q ≥ −0.75 V²/X_s` | 0.86 leading-pf grid-code limit (`DESIGN.md` §2.3) |
| Repo has `src/network.py` | No such file (a stale `src/__pycache__/network.cpython-313.pyc` shows it once existed) |
| Cases: A "assumed" vs B "physical" | Four cost models plus six settlement schemes |
| No demand data at all | An entire CINELDI ingestion and mapping layer |

`DESIGN.md` line 4 says it "Supersedes `IMPLEMENTATION_PLAN.md` (five-bus reduction, deleted)" —
but `IMPLEMENTATION_PLAN.md` is still present in the repo, so that statement is itself wrong,
and nothing anywhere says `CLAUDE.md` is superseded. As it stands, the file that claims
override authority describes a system that does not exist. This is a real hazard for any
future session or collaborator.

*Fix:* add an explicit "SUPERSEDED — see DESIGN.md and README.md" banner at the top of
`CLAUDE.md` and `IMPLEMENTATION_PLAN.md`, or reduce `CLAUDE.md` to the parts that still hold
(the honesty/limitations discipline in §11, which is still exactly right and is genuinely
well-followed elsewhere in this repo).

### 6.2 `DESIGN.md` does not mention the demand data at all

`DESIGN.md` is the current working design document. It contains **no** section on the demand
data: no mention of CINELDI, Engan et al., the 50-bus rural grid, the units, the
peak-normalisation, or `CIGRE_TO_CINELDI_GROUPS`. Its §7 "Open assumptions — must stay on the
limitations slide" lists machine parameters, the round-rotor approximation, the Lnett
withdrawal-tariff proxy, and the single-snapshot convention — all of which are real — but
omits every assumption in the demand pipeline, which is where the largest unforced choices
actually live (H1, H2, M1).

`README.md` §"Demand" does document the mapping well and honestly, including the
single-household-shape limitation. So the information exists; it is the design document
that is out of step with it. Given that §7 is explicitly the "limitations slide" list, the
demand assumptions belong there.

### 6.3 Where the code is *better* than the docs

Worth recording so this does not read as one-sided: the per-bus mapping (`build_case_from_hour`),
the deliberate separation between the uniform sweep and the locationally-varied hour, the
group-size-matched-to-bus-scale reasoning, and the decision to sum-then-normalise rather than
average are all sound, well-reasoned extensions beyond anything either document specifies.
The in-code comments explaining them are unusually good.

---

## 7. What checked out clean

Stated explicitly so the issue list above is read in proportion:

- Per-unit convention end to end: MATPOWER pu → `create_impedance(sn_mva=base)` → `net.sn_mva`
  → `ppc["baseMVA"]` → `S_BASE`. Consistent at every hop. No unit bug found on this path.
- The CINELDI impedances are physically correct — implied cable resistances reproduce
  catalogue values for EX 3x25 Al and EX 3x95 Al exactly.
- Time series integrity: 8760 hourly rows, no gaps, no NaNs, no negatives, P and Q indices
  identical, and the code asserts both of these.
- The CIGRE→CINELDI group arithmetic is exactly as claimed (4+4+2+2+9×1 = 21, each household
  used once), and the group-size ordering matches the true bus-demand ranking.
- All 13 CIGRE load buses are covered by the mapping — none silently left unscaled.
- The two-feeder / two-transformer split underpinning the AWU zone definition is real and
  correctly identified from the switch states.
- The winter:summer active-demand ratio of **1.647** quoted in the README reproduces exactly.
- The rural grid's reactive series really is measured, not the constant-pf-0.98 synthesis the
  paper applies to the semi-urban grids — the README's claim is right, and the grid choice
  that makes it right was the correct one.
- The OPF ingests topology through pandapower's own `_ppc`, so open switches, transformers
  and line charging are all faithfully represented. No hand-rolled Y-bus to get wrong.

---

## 8. Suggestions, in the order I would do them

1. **Fix the power-factor normalisation (H1).** Reconstruct Q from the measured per-hour
   tan φ instead of normalising Q independently. Few lines, removes a bias that runs in the
   study's own favour, and makes "we use real Norwegian reactive demand" a claim that fully
   survives inspection.
2. **Screen the reactive channels and report the screening (H2).** State how many households
   have usable reactive metering and which CIGRE buses depend on the ones that do not. A
   sentence naming this as a data limitation is worth more than a clean-looking figure.
3. **Reconcile fleet size with realised demand, or relabel the monthly results (H3).**
   Whichever is chosen, put the realised-demand distribution (min/median/max) in the README
   next to the 22 MVA nameplate, so the ratio a reader computes is the right one.
4. **Add a short "Data provenance and corrections" section to `README.md`** recording:
   the units contradiction with the paper's §3.11 and the three statistics that resolve it;
   the 0.0334 vs 0.0344 base-MVA discrepancy and the cable-resistance check that resolves it;
   the UTC+1 convention. All three are already-done work that is currently invisible.
5. **Add a `DESIGN.md` §demand-data section** and extend §7's limitations list to cover the
   mapping, the normalisation and the single-household load factors.
6. **Mark `CLAUDE.md` and `IMPLEMENTATION_PLAN.md` superseded.**
7. **Reproduce the paper's Vmin = 0.901 pu** for the 50-bus grid, or document why it differs.
   Cheap, and it validates the hand-built network against its own publication.
8. **Guard `load_profiles`/`build_network` against the two unusable grids (M2)**, or restrict
   the `grid` parameter to the two that work.
9. **Add `functools.lru_cache` to `load_profiles` / `bus_demand_shapes` (L2)** and delete or
   use `representative_hours` (L1). Ten minutes, ~45 minutes saved per monthly run.
10. **Write the mapped per-bus shapes to `data/processed/`** so the demand input to every
    result set is a diffable artefact rather than a recomputation.

---

*Reviewer note: everything numeric in this document was computed directly from the repo's
own data and dependencies during the review, not taken from the code's comments or README.
Where a claim in the repo reproduced, I have said so.*
