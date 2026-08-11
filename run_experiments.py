"""Reproduce every result end to end.

    python run_experiments.py

Writes results/base_case.csv, results/load_sweep.csv, results/sensitivity.csv,
results/schemes.csv and results/figures/fig{1,2,3}.png.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.case_data import GEN_BUSES, build_case, demand_shapes, load_profiles
from src.cost_models import AssumedCost, DeadbandCost, NoCost, PhysicalCost
from src.machine import Machine
from src.opf import solve as _solve_raw
from src.settlement import (
    capacity, cost_recovery, hybrid, load_side_charge, loss_of_opportunity_cost, variable,
)

RESULTS = Path(__file__).parent / "results"
FIGURES = RESULTS / "figures"

ENERGY_PRICE = 70.0  # EUR/MWh -- SysOpt WP4 used this for Nordic-44
S_BASE = 1.0  # CIGRE MV benchmark base, MVA
V_SETPOINT = 1.02  # pu -- Scheme 0 (regulated obligation) AVR setpoint

# Scheme 0's baseline convention: only G1 (8 MVA, the largest unit) holds a
# fixed voltage setpoint; G2/G3/G4 run at unity PF instead. Root-caused, not
# guessed -- diagnosed against real hours across all four study months:
#   all four fixed simultaneously: frequently infeasible even in January
#     (100 sampled hours: as few as 60% solved)
#   G1/G2 fixed, G3/G4 unity PF: fixes Dec/Jan/Jun cleanly, but still fails
#     8/10 sampled light-load July hours -- G2 itself violates its own
#     underexcitation floor (Q >= -P*tan(acos(0.86)), which shrinks with P)
#     at very light system-wide load
#   only G1 fixed: 199/200 sampled July hours solve (the single remaining
#     failure is G1 itself violating the same floor at an even lighter point)
# The mechanism is real and general -- the fixed-voltage-setpoint convention
# is intrinsically fragile at light system-wide load, for whichever generator
# is asked to hold it, not a property of any one machine. Only G1 is large
# enough to make this rare (0.5%) rather than routine. The tiny residual is
# accepted and logged (never silently included), not chased further -- also
# matches Wolgast et al. (2022)'s description of default DG behaviour:
# "without payment, operators set inverters to unity PF", most plausible for
# the smaller, less centrally-managed units.
BASELINE_FIXED_VOLTAGE_BUSES = {GEN_BUSES["G1"]: V_SETPOINT}
BASELINE_UNITY_PF_BUSES = {GEN_BUSES["G2"], GEN_BUSES["G3"], GEN_BUSES["G4"]}

# Reactive tariff, RELABELLED after external review -- read this before
# trusting the number. Source: Lnett HV winter rate, tariffhefte 1 Jan 2026,
# 40 NOK/kVAr/MONTH -- a peak-setting capacity charge, not a per-hour
# marginal price. The single-period convention this study runs under (one
# independent OPF per hour, no monthly peak-tracking state) cannot represent
# a true monthly-peak tariff at all -- there is no "this hour's contribution
# to the eventual monthly max" state to charge. What's actually implemented
# is an ASSUMED FLAT HOURLY UTILISATION PRICE, chosen to be the same order of
# magnitude as a naive energy-spread of the real tariff (40,000 EUR/MVAr/
# month / 730 h/month = 4.76 EUR/MVArh, vs the 3.478 EUR/MVArh used below --
# both defensible-magnitude, neither a precise derivation of an hourly
# marginal cost from a monthly peak charge). Two honest options if this
# needs to be tighter: (a) state it plainly as an assumed utilisation price
# with this order-of-magnitude justification, not as "the Lnett rate,"
# or (b) implement the real peak-charge structure properly at a MONTHLY
# settlement layer (`pi_cap_monthly * max_t[|Q_interface,t| - Q_free]`,
# using the monthly max of already-solved hourly Q_interface, not inside
# the hourly OPF objective itself). This file keeps (a) for the OPF -- the
# number below is an assumed price, carried at the same order of magnitude
# as the real tariff, not the real tariff correctly integrated.
_NOK_PER_EUR = 11.5
Q_IMPORT_PRICE = 40.0 / _NOK_PER_EUR  # EUR/MVArh, ASSUMED utilisation price (see caveat above) -- HV winter magnitude
Q_IMPORT_PRICE_SUMMER = 5.0 / _NOK_PER_EUR  # EUR/MVArh, ASSUMED utilisation price -- HV summer magnitude
# Statnett's fos SS15 generator-facing capacity rate for 2024, read directly
# from "Vedtak om levering og betaling for systemtjenester 2024" (18.12.2023,
# ref. 2023/3485), SS3 "Reaktiv effekt": fixed payment model B = Y(MVA) x
# S(kr/MVA), S = kr 250 per installed MVA per year for 2024 -- a real,
# generator-facing rate, not a withdrawal tariff reused as a proxy.
#
# RELABELLED after external review: this is the 2024 rate, not verified as
# the current 2026 rate -- Statnett's 2026 consultation material discusses
# changes to the fixed-payment model, not checked here. Report this as "the
# 2024 Statnett reference payment, the closest real Norwegian benchmark,"
# NOT as "the current rate underpays this fleet by ~10x" -- the honest claim
# is narrower: "the 2024 reference benchmark would cover ~9-11% of this
# fleet's modeled cost" (see Q_ref fix above for why the number moved from
# 9.7%), not a claim about what today's regime actually pays anyone.
# Converted to an EUR/MVArh-equivalent hourly rate under this study's single-
# period convention (divide the annual retainer by 8760 h/year):
#   250 NOK/MVA/yr / 11.5 NOK-per-EUR / 8760 h/yr = 0.00248 EUR/MVArh
# ~1400x smaller than the previous Lnett-withdrawal-reuse (3.478 EUR/MVArh) --
# expected, not a bug: an annual flat retainer and a monthly-peak withdrawal
# charge are structurally different instruments, not directly comparable.
#
# CAVEAT, stated not hidden: fos SS15's fixed payment applies to plants >= 10
# MVA connected to the regional or transmission grid. G1-G4 (3-8 MVA, all
# distribution-connected at 20 kV) are below that threshold and outside that
# grid level -- this is the REAL Norwegian rate for the closest REAL
# mechanism, not a rate that literally applies to this fleet today. That gap
# is not a flaw to engineer around (e.g. by resizing a machine past 10 MVA):
# it is precisely the population Statnett's own mechanism does not cover, and
# covering exactly that gap is this study's actual research question. Kept as
# the primary capacity-payment number because it is the best real number
# available, with this caveat carried alongside it, not silently dropped.
PI_CAP = 250.0 / _NOK_PER_EUR / 8760  # EUR/MVArh-equivalent, from Statnett fos SS15

# Statnett's fos SS15 VARIABLE payment (only triggered by a specific order
# requiring delivery beyond +40%/-20% of active production) is worth noting
# even though it is not wired in as a scheme here: B = k(MW/MVAr) x Sp(kr/MWh)
# x L(MVArh), where k is a loss coefficient (0.012 capacitive, 0.007
# inductive) and Sp is last year's average day-ahead price. That is
# structurally the SAME idea as this study's own PhysicalCost model -- price
# excess reactive power by the extra active-power loss it causes, at the
# system energy price -- an independent real-world confirmation of the
# approach, not something engineered to match.

# CIGRE MV connects to the 110 kV grid through two 25 MVA transformers (see
# net.trafo -- verified directly, not assumed): 2 x 25 = 50 MVA combined
# thermal capacity at the interface, both directions. Before this existed,
# p_slack/q_slack had NO bound at all -- a cheap-enough local generator could
# export without physical limit, which is exactly what happened with
# c_g^P = 0 (see the monthly analysis: 12.6 MW of generation against 4.3 MW
# of local demand, all "exported" through an interface with no capacity
# limit). This bounds apparent power at the interface, both import and
# export, at the real transformer rating -- not a new, separate export price,
# since the same market price applying to both directions is standard,
# efficient market design; the missing piece was capacity, not price.
S_INTERFACE_MAX = 50.0  # MVA


def solve(net, machines, cost_model, energy_price, **kwargs):
    kwargs.setdefault("s_interface_max", S_INTERFACE_MAX)
    # Water-value convention: c_g^P = energy_price by default (matches
    # run_monthly_analysis.py's water-value-corrected runs). At exactly this
    # value the linear term in P_g vanishes from the objective, isolating the
    # reactive-power story from the active-power dispatch confound -- see
    # src/opf.py's solve() fallback comment for why c_g^P=0 also caused most
    # of this session's IPOPT convergence failures. Explicit p_cost_gen=...
    # (e.g. run_monthly_analysis.solve_hour's own default of 0.0 for
    # backward-compat callers) still overrides this.
    kwargs.setdefault("p_cost_gen", energy_price)
    return _solve_raw(net, machines, cost_model, energy_price, **kwargs)


def machines() -> dict[int, Machine]:
    """Four hydro units, two machine "types" reused at two sizes each.

    Type A (G1, G3) -- fully cited to Karekezi, Melfald, Oyvang & Noland
    (2023), IEEE Trans. Energy Conversion 38(2), Tables I-II -- their 103
    MVA, 11 kV, 500 rpm hydrogenerator case study, verified directly against
    the PDF (not a summary):
        cos_phi = 0.90, X_d = 1.087 pu
        rotor_loss_frac = (P_ex* + P_f* + P_br*) / S_rated
                        = (15.88 + 175.78) kW / 103000 kW = 0.001861 pu
        r_a_pu = (P_a* + P_s*) / S_rated = 276.62 kW / 103000 kW = 0.0026862 pu
                -- the COMBINED armature + stray-load loss from Table I, not
                Table II's standalone R_a=0.002pu. The paper's own stator
                loss equation (4) scales P_a*+P_s*=276.62 kW by (I_a/I_a*)^2
                -- it does not use R_a*I_a^2 directly (Table II's R_a is used
                elsewhere, e.g. the Potier field-current estimate). Our loss
                model IS the simplified R_a*I_a^2 form (CLAUDE.md SS3.1), so
                matching the paper's total rated stator-side loss means using
                the combined figure as the effective R_a here, not the bare
                Table II value -- using 0.002pu alone silently drops the
                70.6 kW stray-load-loss component (review caught this: it
                moves Q* by ~25% and the marginal-cost slope by ~20%,
                verified against the paper's own "~-0.2pu" Q* result, which
                the corrected value reproduces and the original did not).

    Type B (G2, G4) -- no second real reference machine exists, so it keeps
    the same illustrative deviation from Type A that CLAUDE.md's original
    two-machine spec called for (X_d bumped up, rotor_loss_frac ~30% higher),
    stated as illustrative rather than invented per unit. R_a, cos_phi kept
    equal to Type A -- no reason to vary a cited number without cause.

    Sizes and bus placement (all [ASSUMED], chosen to fit this feeder):
        G1  8 MVA, bus 3  (feeder 1, 2 hops from the feeder-1 head)
        G2  5 MVA, bus 10 (feeder 1, 5 hops -- distant, same feeder as G1)
        G3  6 MVA, bus 13 (feeder 2 -- a separate transformer from feeder 1)
        G4  3 MVA, bus 14 (feeder 2, far end of that feeder's loop)
    Combined nameplate 22 MVA vs. 44.74 MW nominal feeder demand (49%, up
    from 29% with just G1/G2) -- enough local capacity to materially relieve
    feeder-1's trunk congestion (see README SS OPF formulation), while G3/G4
    sit behind an entirely different transformer and are not exposed to that
    same congestion at all -- a genuinely distinct location, not just a
    third/fourth copy of G1/G2's story.
    """
    type_a = dict(cos_phi=0.90, x_d_pu=1.087, r_a_pu=276.62 / 103_000,
                  rotor_loss_frac=(15.88 + 175.78) / 103_000, p_max_pu=0.85, p_min_pu=0.15)
    type_b = dict(cos_phi=0.90, x_d_pu=1.3, r_a_pu=276.62 / 103_000,
                  rotor_loss_frac=0.0024, p_max_pu=0.85, p_min_pu=0.15)
    return {
        GEN_BUSES["G1"]: Machine.from_nameplate("G1", 8.0, S_BASE, **type_a),
        GEN_BUSES["G2"]: Machine.from_nameplate("G2", 5.0, S_BASE, **type_b),
        GEN_BUSES["G3"]: Machine.from_nameplate("G3", 6.0, S_BASE, **type_a),
        GEN_BUSES["G4"]: Machine.from_nameplate("G4", 3.0, S_BASE, **type_b),
    }


def cases(energy_price: float = ENERGY_PRICE):
    return [
        NoCost(), AssumedCost(energy_price), DeadbandCost(energy_price), PhysicalCost(energy_price),
    ]


def _row(case_label, scale, net, r, mach, energy_price):
    """One row per solve, one set of {p,q,price,binding,loc} columns per
    generator -- generalised over however many machines `mach` holds, keyed
    by each Machine's own .name (lowercased), rather than hardcoding G1/G2.
    """
    loc = loss_of_opportunity_cost(mach, r, energy_price)
    row = {
        "case": case_label,
        "load_scale": scale,
        "p_demand_mw": net.load.p_mw.sum(),
        "q_demand_mvar": net.load.q_mvar.sum(),
        "status": r.status,
        "objective_eur_h": r.objective,
        "q_slack_mvar": r.slack_q, "p_slack_mw": r.slack_p,
        "losses_mw": r.losses_mw,
        "v_min": min(r.v.values()), "v_max": max(r.v.values()),
        "max_line_loading_pct": max(r.line_loading.values()) if r.line_loading else float("nan"),
    }
    for bus, m in mach.items():
        tag = m.name.lower()
        row[f"p_{tag}_mw"] = r.p_gen[bus]
        row[f"q_{tag}_mvar"] = r.q_gen[bus]
        row[f"lambda_q_{tag}"] = r.q_price[bus]
        row[f"{tag}_field_binding"] = r.binding[bus]["field"]
        row[f"{tag}_stator_binding"] = r.binding[bus]["stator"]
        row[f"loc_{tag}_eur_h"] = loc[bus]
    return row


def run_base_case() -> pd.DataFrame:
    rows = []
    for cost in cases():
        net = build_case(1.0, 1.0)
        r = solve(net, machines(), cost, ENERGY_PRICE, q_import_price=Q_IMPORT_PRICE)
        rows.append(_row(cost.label, 1.0, net, r, machines(), ENERGY_PRICE))
    return pd.DataFrame(rows)


def run_load_sweep(steps: int = 40) -> pd.DataFrame:
    """Sweep loading from 40% to 150% of the CIGRE MV nominal point."""
    rows = []
    for cost in cases():
        for i in range(steps):
            scale = 0.40 + (1.50 - 0.40) * i / (steps - 1)
            net = build_case(scale, scale)
            r = solve(net, machines(), cost, ENERGY_PRICE, q_import_price=Q_IMPORT_PRICE)
            if r.status != "optimal":
                print(f"  !! {cost.label} at scale {scale:.3f}: {r.status}")
            rows.append(_row(cost.label, scale, net, r, machines(), ENERGY_PRICE))
    return pd.DataFrame(rows)


def run_sensitivity() -> pd.DataFrame:
    """Reactive price should scale roughly linearly with the energy price."""
    rows = []
    for lam in (40.0, 70.0, 100.0):
        for cost in cases(lam):
            net = build_case(1.0, 1.0)
            r = solve(net, machines(), cost, lam, q_import_price=Q_IMPORT_PRICE)
            row = _row(cost.label, 1.0, net, r, machines(), lam)
            row["energy_price"] = lam
            rows.append(row)
    return pd.DataFrame(rows)


def run_water_value_sensitivity() -> pd.DataFrame:
    """Water value drives whether P dispatch is loss/constraint-limited (c^P=0,
    must-run) or genuinely traded off against reactive service (c^P>0). Swept
    at 0, half and full energy price -- the single-period equilibrium bound.
    """
    rows = []
    for c_p in (0.0, 0.5 * ENERGY_PRICE, ENERGY_PRICE):
        net = build_case(1.0, 1.0)
        r = solve(net, machines(), PhysicalCost(ENERGY_PRICE), ENERGY_PRICE,
                  q_import_price=Q_IMPORT_PRICE, p_cost_gen=c_p)
        row = _row("physical", 1.0, net, r, machines(), ENERGY_PRICE)
        row["water_value"] = c_p
        rows.append(row)
    return pd.DataFrame(rows)


def run_schemes() -> pd.DataFrame:
    """Baseline (Scheme 0, regulated obligation) vs coordinated dispatch
    (physical cost, the true least-cost operating point), settled six ways:
    the four generators' own G1/G2/G3/G4 fleet, crossed with the six final
    schemes -- one service-component axis (capacity / utilisation / hybrid,
    per Wolgast et al. 2022) and, for utilisation, one pricing-basis axis
    (nodal / uniform / area-wise-uniform, same taxonomy) folded in as three
    variants of scheme 2. 1 (baseline) + 1 (capacity) + 3 (utilisation
    pricing bases) + 1 (hybrid) = 6.
    """
    mach = machines()
    net_base = build_case(1.0, 1.0)
    baseline = solve(
        net_base, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE,
        q_import_price=Q_IMPORT_PRICE,
        fixed_voltage_buses=BASELINE_FIXED_VOLTAGE_BUSES,
        unity_pf_buses=BASELINE_UNITY_PF_BUSES,
    )
    net_coord = build_case(1.0, 1.0)
    coordinated = solve(
        net_coord, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE,
        q_import_price=Q_IMPORT_PRICE,
    )
    if baseline.status != "optimal" or coordinated.status != "optimal":
        print(f"  !! run_schemes: baseline={baseline.status} coordinated={coordinated.status}")

    rows = []
    baseline_loc = loss_of_opportunity_cost(mach, baseline, ENERGY_PRICE)
    for b, m in mach.items():
        cost = PhysicalCost(ENERGY_PRICE)(m, baseline.p_gen[b], baseline.q_gen[b], baseline.v[b])
        revenue_p = ENERGY_PRICE * baseline.p_gen[b]
        gen_cost = ENERGY_PRICE * baseline.p_gen[b]  # water-value convention: c_g^P = ENERGY_PRICE
        rows.append({
            "scheme": "0_baseline", "bus": b, "generator": m.name,
            "p_mw": baseline.p_gen[b], "q_mvar": baseline.q_gen[b],
            "payment": 0.0, "revenue_p": revenue_p, "service_cost": cost,
            "loc": baseline_loc[b], "profit": revenue_p - cost - gen_cost,
        })
    # p_cost_gen=ENERGY_PRICE here matches solve()'s new default above --
    # settlement's own gen_cost/profit accounting must use the SAME water
    # value the OPF actually dispatched against, or profit silently ignores
    # a real cost the dispatch already paid.
    settlements = [
        capacity(mach, coordinated, ENERGY_PRICE, PI_CAP, p_cost_gen=ENERGY_PRICE),
        variable(mach, coordinated, ENERGY_PRICE, pricing="nodal", p_cost_gen=ENERGY_PRICE),
        variable(mach, coordinated, ENERGY_PRICE, pricing="uniform", p_cost_gen=ENERGY_PRICE),
        variable(mach, coordinated, ENERGY_PRICE, pricing="awu", p_cost_gen=ENERGY_PRICE),
        hybrid(mach, coordinated, ENERGY_PRICE, PI_CAP, pricing="nodal", p_cost_gen=ENERGY_PRICE),
    ]
    # Counterparty check: nothing above asks who pays for a generator-side
    # payment. Review found a ~31x mismatch in the base case (nodal payment
    # 0.83 EUR/h to generators vs 25.61 EUR/h charged to loads at the SAME
    # nodal prices) -- reported per scheme, not silently absent.
    charge = load_side_charge(net_coord, coordinated)
    for s in settlements:
        recovery = cost_recovery(s.payment, charge)
        for b, m in mach.items():
            rows.append({
                "scheme": s.scheme, "bus": b, "generator": m.name,
                "p_mw": coordinated.p_gen[b], "q_mvar": coordinated.q_gen[b],
                "payment": s.payment[b], "revenue_p": s.revenue_p[b],
                "service_cost": s.service_cost[b], "loc": s.loc[b], "profit": s.profit[b],
                "load_charge_total_eur_h": recovery["load_charge_eur_h"],
                "net_surplus_eur_h": recovery["net_surplus_eur_h"],
                "recovery_ratio": recovery["recovery_ratio"],
            })

    df = pd.DataFrame(rows)
    print(f"\n  baseline: status={baseline.status} loss={baseline.losses_mw:.4f} MW "
          f"Vmin={min(baseline.v.values()):.4f}")
    print(f"  coordinated: status={coordinated.status} loss={coordinated.losses_mw:.4f} MW "
          f"Vmin={min(coordinated.v.values()):.4f}")
    loss_reduction_pct = 100 * (baseline.losses_mw - coordinated.losses_mw) / baseline.losses_mw
    print(f"  cost of no coordination (loss delta): "
          f"{(baseline.losses_mw - coordinated.losses_mw):.4f} MW "
          f"({loss_reduction_pct:.1f}% reduction)")
    return df


def run_seasonal() -> pd.DataFrame:
    """Winter vs summer, at each season's peak and median hour, using the
    season-appropriate Lnett tariff (40 vs 5 NOK/kVAr at HV -- an 8:1 ratio).
    Settled all four ways at each point.

    This extrapolates an annual EUR figure as (representative-hour EUR/h) *
    (hours in that season), NOT a full 8760-hour integration -- solving the
    OPF at every hour was out of scope for this pass. Treat the annualised
    column as order-of-magnitude, not a rigorous total.
    """
    shapes = demand_shapes()
    total = shapes.p_scale
    winter_mask = shapes.index.month.isin([10, 11, 12, 1, 2, 3])
    summer_mask = ~winter_mask
    points = {
        "winter_peak": (shapes[winter_mask].p_scale.idxmax(), Q_IMPORT_PRICE, 6 * 30 * 24),
        "winter_median": ((total[winter_mask] - total[winter_mask].median()).abs().idxmin(),
                           Q_IMPORT_PRICE, 6 * 30 * 24),
        "summer_peak": (shapes[summer_mask].p_scale.idxmax(), Q_IMPORT_PRICE_SUMMER, 6 * 30 * 24),
        "summer_median": ((total[summer_mask] - total[summer_mask].median()).abs().idxmin(),
                           Q_IMPORT_PRICE_SUMMER, 6 * 30 * 24),
    }

    mach = machines()
    rows = []
    for label, (ts, q_price, hours_in_season) in points.items():
        p_s, q_s = shapes.loc[ts, "p_scale"], shapes.loc[ts, "q_scale"]
        net = build_case(p_s, q_s)
        coordinated = solve(net, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE,
                             q_import_price=q_price)
        baseline = solve(build_case(p_s, q_s), mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE,
                          q_import_price=q_price,
                          fixed_voltage_buses=BASELINE_FIXED_VOLTAGE_BUSES,
                          unity_pf_buses=BASELINE_UNITY_PF_BUSES)
        if coordinated.status != "optimal" or baseline.status != "optimal":
            print(f"  !! {label}: coordinated={coordinated.status} baseline={baseline.status} "
                  f"-- skipped (fixed-voltage baseline can be jointly infeasible when several "
                  f"machines on the same feeder are all pinned to a setpoint at very light load; "
                  f"see G3/G4 on feeder 2)")
            continue
        # pi_cap uses the SAME season-appropriate Lnett rate as q_price -- both
        # are the withdrawal tariff used as the capacity-value proxy (see
        # PI_CAP's definition above). Using the fixed winter PI_CAP constant
        # here would silently erase the summer/winter difference this run
        # exists to show.
        settlements = {
            "1_capacity": capacity(mach, coordinated, ENERGY_PRICE, q_price),
            "2_variable": variable(mach, coordinated, ENERGY_PRICE),
            "3_hybrid": hybrid(mach, coordinated, ENERGY_PRICE, q_price),
        }
        for scheme, s in settlements.items():
            total_payment = sum(s.payment.values())
            rows.append({
                "season": label, "timestamp": ts, "scheme": scheme,
                "p_demand_mw": net.load.p_mw.sum(), "q_demand_mvar": net.load.q_mvar.sum(),
                "q_import_price": q_price,
                "total_payment_eur_h": total_payment,
                "total_payment_eur_annualised": total_payment * hours_in_season,
                "loss_mw": coordinated.losses_mw,
                "baseline_loss_mw": baseline.losses_mw,
            })
    return pd.DataFrame(rows)


def run_local_optimum_check(n_starts: int = 8) -> pd.DataFrame:
    """Re-solve the base case from n_starts randomly perturbed initial points.

    IPOPT gives no global-optimality guarantee on this non-convex problem.
    This does not prove global optimality either -- it is a sanity check: if
    different starts land on different objective values, the result is
    start-dependent and must be reported as such. Matching objectives across
    all starts is evidence (not proof) that the KKT point found is robust.
    """
    mach = machines()
    rows = []
    for seed in range(n_starts):
        net = build_case(1.0, 1.0)
        r = solve(net, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE,
                  q_import_price=Q_IMPORT_PRICE, init_seed=seed)
        rows.append({
            "seed": seed, "status": r.status, "objective": r.objective,
            **{f"q_{name.lower()}": r.q_gen[bus] for name, bus in GEN_BUSES.items()},
        })
    df = pd.DataFrame(rows)
    spread = (df.objective.max() - df.objective.min()) / df.objective.mean()
    print(f"  {n_starts} starts, objective range {df.objective.min():.4f}-{df.objective.max():.4f}, "
          f"relative spread {spread:.2e}")
    return df


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    shapes = demand_shapes()
    print(f"CINELDI demand shapes: {len(shapes)} hours, "
          f"p_scale {shapes.p_scale.min():.3f}-{shapes.p_scale.max():.3f}")

    print("Run 1 - base case")
    base = run_base_case()
    base.to_csv(RESULTS / "base_case.csv", index=False)
    q_cols = [f"q_{n.lower()}_mvar" for n in GEN_BUSES]
    print(base[["case", *q_cols, "max_line_loading_pct", "losses_mw"]]
          .round(4).to_string(index=False))

    print("\nRun 2 - load sweep")
    sweep = run_load_sweep()
    sweep.to_csv(RESULTS / "load_sweep.csv", index=False)
    print(f"  {len(sweep)} solves, "
          f"{(sweep.status != 'optimal').sum()} non-optimal")

    print("\nRun 3 - energy price sensitivity")
    sens = run_sensitivity()
    sens.to_csv(RESULTS / "sensitivity.csv", index=False)
    print(sens[["energy_price", "case", "lambda_q_g1", "lambda_q_g2"]]
          .round(4).to_string(index=False))

    print("\nRun 4 - water value sensitivity")
    water = run_water_value_sensitivity()
    water.to_csv(RESULTS / "water_value_sensitivity.csv", index=False)
    print(water[["water_value", "p_g1_mw", "p_g2_mw", "lambda_q_g1",
                 "g1_field_binding"]].round(4).to_string(index=False))

    print("\nRun 5 - incentive schemes")
    schemes = run_schemes()
    schemes.to_csv(RESULTS / "schemes.csv", index=False)
    print(schemes.round(4).to_string(index=False))

    print("\nRun 6 - seasonal (winter vs summer, real Lnett tariff ratio)")
    seasonal = run_seasonal()
    seasonal.to_csv(RESULTS / "seasonal.csv", index=False)
    print(seasonal[["season", "scheme", "p_demand_mw", "total_payment_eur_h",
                    "total_payment_eur_annualised"]].round(2).to_string(index=False))

    print("\nRun 7 - local optimum check (8 random starts)")
    local_opt = run_local_optimum_check()
    local_opt.to_csv(RESULTS / "local_optimum_check.csv", index=False)

    print("\nFigures")
    from src.plotting import (
        figure0_demand, figure1, figure2, figure3, figure4_dispatch_split, figure_bus_profiles,
    )
    p_raw, q_raw = load_profiles()
    figure0_demand(p_raw, q_raw, FIGURES / "fig0_demand_data.png")
    figure_bus_profiles(FIGURES / "fig_bus_profiles.png")
    figure1(machines(), base, FIGURES / "fig1_capability.png")
    figure2(machines(), ENERGY_PRICE, FIGURES / "fig2_marginal_cost.png")
    figure3(sweep, FIGURES / "fig3_price_vs_load.png")
    figure4_dispatch_split(machines(), sweep, FIGURES / "fig4_dispatch_split.png")
    print(f"  written to {FIGURES}")


if __name__ == "__main__":
    main()
