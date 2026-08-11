"""4-month hourly analysis: December+January (winter) + June+July (summer),
real per-bus CINELDI-shaped demand, one full AC OPF solve per real hour.

Scheme 0 (baseline, fixed-voltage) needs its own OPF solve; Schemes 1/2a/3
(capacity / utilisation-nodal / hybrid) are all different payment formulas
applied to the SAME coordinated (physical-cost) solve -- see src/settlement.py
-- so each hour costs exactly two OPF solves, not four.

    python run_monthly_analysis.py            # full 4-month, 4-generator run
    python run_monthly_analysis.py --pilot 48  # first 48 hours only, for timing

Writes results/monthly_hourly.csv (main run) and, separately,
results/generator_count_comparison.csv (2/3/4-generator fleets, compared at
representative hours only -- full hourly resolution for every fleet size
would be tens of thousands of solves for a question that doesn't need that
resolution to answer).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from src.case_data import GEN_BUSES, build_case_from_hour, load_profiles
from src.cost_models import PhysicalCost
from src.settlement import capacity, cost_recovery, hybrid, load_side_charge, variable
from run_experiments import (
    BASELINE_FIXED_VOLTAGE_BUSES, BASELINE_UNITY_PF_BUSES,
    ENERGY_PRICE, PI_CAP, Q_IMPORT_PRICE, Q_IMPORT_PRICE_SUMMER, V_SETPOINT, machines, solve,
)

RESULTS = Path(__file__).parent / "results"
WINTER_MONTHS = {10, 11, 12, 1, 2, 3}
STUDY_MONTHS = {12, 1, 6, 7}  # Dec+Jan (winter), Jun+Jul (summer)


def _q_price_for(ts) -> float:
    return Q_IMPORT_PRICE if ts.month in WINTER_MONTHS else Q_IMPORT_PRICE_SUMMER


def _baseline_convention(mach: dict) -> tuple[dict, set]:
    """Only the single LARGEST machine in this fleet holds a fixed voltage
    setpoint; everyone else runs at unity PF. Root-caused for the 4-generator
    fleet (see BASELINE_FIXED_VOLTAGE_BUSES's own comment in run_experiments.py)
    and generalised here for any fleet size, the same rule
    generator_count_comparison() already uses.
    """
    largest = max(mach, key=lambda b: mach[b].s_rated)
    return {largest: V_SETPOINT}, set(mach) - {largest}


def solve_hour(mach: dict, timestamp, p_cost_gen: float = 0.0,
                fixed_voltage_buses: dict | None = None, unity_pf_buses: set | None = None) -> dict | None:
    """One real hour, two OPF solves (baseline + coordinated), four schemes
    settled. Returns None -- never a partially-wrong row -- if either solve
    is not optimal.

    `p_cost_gen` (water value, EUR/MWh) defaults to 0 for backward
    compatibility, but the water-value-corrected run passes ENERGY_PRICE --
    see module docstring / README for why that specific value, not an
    arbitrary positive number, is what actually isolates the reactive-power
    story from the active-power dispatch confound.

    `fixed_voltage_buses`/`unity_pf_buses` default to the 4-generator
    convention (module-level constants) for backward compatibility; pass
    `_baseline_convention(mach)` explicitly for any other fleet size.
    """
    if fixed_voltage_buses is None:
        fixed_voltage_buses = BASELINE_FIXED_VOLTAGE_BUSES
    if unity_pf_buses is None:
        unity_pf_buses = BASELINE_UNITY_PF_BUSES
    q_price = _q_price_for(timestamp)

    net_c = build_case_from_hour(timestamp)
    coordinated = solve(net_c, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE, q_import_price=q_price,
                         p_cost_gen=p_cost_gen)
    net_b = build_case_from_hour(timestamp)
    baseline = solve(net_b, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE, q_import_price=q_price,
                      p_cost_gen=p_cost_gen,
                      fixed_voltage_buses=fixed_voltage_buses,
                      unity_pf_buses=unity_pf_buses)
    if coordinated.status != "optimal" or baseline.status != "optimal":
        return None

    # PI_CAP, not q_price: capacity payment must use the real Statnett fos SS15
    # generator-facing rate (see run_experiments.py's PI_CAP definition and
    # caveat), not the Lnett withdrawal tariff used for the utilisation price.
    # These are two structurally different instruments -- conflating them here
    # was a ~1400x bug (q_price=3.478 vs PI_CAP=0.00248 EUR/MVArh), not a
    # deliberate choice (contrast run_seasonal()'s use of q_price for pi_cap,
    # which IS deliberate and documented there for that specific pre-PI_CAP run).
    settlements = {
        "1_capacity": capacity(mach, coordinated, ENERGY_PRICE, PI_CAP, p_cost_gen=p_cost_gen),
        "2a_variable_nodal": variable(mach, coordinated, ENERGY_PRICE, pricing="nodal", p_cost_gen=p_cost_gen),
        "3_hybrid": hybrid(mach, coordinated, ENERGY_PRICE, PI_CAP, pricing="nodal", p_cost_gen=p_cost_gen),
    }
    # Counterparty check (added after review found a ~30x mismatch in the
    # base case): are LOADS charged enough, at the same nodal prices, to
    # cover what each scheme pays generators? Charge is scheme-independent
    # (same coordinated dispatch/prices throughout), so computed once.
    charge = load_side_charge(net_c, coordinated)
    recovery = {label: cost_recovery(s.payment, charge) for label, s in settlements.items()}
    baseline_cost = {b: PhysicalCost(ENERGY_PRICE)(m, baseline.p_gen[b], baseline.q_gen[b], baseline.v[b])
                      for b, m in mach.items()}
    baseline_gen_cost = {b: p_cost_gen * baseline.p_gen[b] for b in mach}
    baseline_revenue_p = {b: ENERGY_PRICE * baseline.p_gen[b] for b in mach}

    row = {
        "timestamp": timestamp, "month": timestamp.month, "q_import_price": q_price,
        "p_demand_mw": net_c.load.p_mw.sum(), "q_demand_mvar": net_c.load.q_mvar.sum(),
        "0_baseline_loss_mw": baseline.losses_mw,
        "coordinated_loss_mw": coordinated.losses_mw,
        "0_baseline_vmin": min(baseline.v.values()), "0_baseline_vmax": max(baseline.v.values()),
        "coordinated_vmin": min(coordinated.v.values()), "coordinated_vmax": max(coordinated.v.values()),
        "0_baseline_max_line_loading_pct":
            max(baseline.line_loading.values()) if baseline.line_loading else float("nan"),
        "coordinated_max_line_loading_pct":
            max(coordinated.line_loading.values()) if coordinated.line_loading else float("nan"),
        "0_baseline_total_payment_eur_h": 0.0,
        "0_baseline_total_revenue_p_eur_h": sum(baseline_revenue_p.values()),
        "0_baseline_total_profit_eur_h": sum(
            baseline_revenue_p[b] - baseline_cost[b] - baseline_gen_cost[b] for b in mach
        ),
    }
    for label, s in settlements.items():
        row[f"{label}_total_payment_eur_h"] = sum(s.payment.values())
        row[f"{label}_total_revenue_p_eur_h"] = sum(s.revenue_p.values())
        row[f"{label}_total_profit_eur_h"] = sum(s.profit.values())
        row[f"{label}_load_charge_eur_h"] = recovery[label]["load_charge_eur_h"]
        row[f"{label}_net_surplus_eur_h"] = recovery[label]["net_surplus_eur_h"]
        row[f"{label}_recovery_ratio"] = recovery[label]["recovery_ratio"]
    for b, m in mach.items():
        tag = m.name.lower()
        row[f"p_{tag}_mw"] = coordinated.p_gen[b]
        row[f"q_{tag}_mvar"] = coordinated.q_gen[b]
        row[f"v_{tag}"] = coordinated.v[b]
        row[f"lambda_q_{tag}"] = coordinated.q_price[b]
        row[f"{tag}_field_binding"] = coordinated.binding[b]["field"]
        row[f"{tag}_stator_binding"] = coordinated.binding[b]["stator"]
        row[f"{tag}_underexcited_binding"] = coordinated.binding[b]["underexcited"]
    return row


def _fleet_configs() -> dict[str, dict[int, "Machine"]]:
    """2-gen, 3-gen (x2), 4-gen -- the same four configurations already used
    for the representative-hour comparison, now run at full hourly
    resolution. Isolates G3's own effect from G4's own effect from their
    combined interaction (the representative-hour study found the combined
    4-gen effect is more than 3x the sum of either alone -- this is the full
    check of that finding, not a new hypothesis).
    """
    full = machines()
    return {
        "2gen_G1G2": {GEN_BUSES[n]: full[GEN_BUSES[n]] for n in ("G1", "G2")},
        "3gen_G1G2G3": {GEN_BUSES[n]: full[GEN_BUSES[n]] for n in ("G1", "G2", "G3")},
        "3gen_G1G2G4": {GEN_BUSES[n]: full[GEN_BUSES[n]] for n in ("G1", "G2", "G4")},
        "4gen_all": full,
    }


def _solve_one(args) -> dict | None:
    """Top-level, picklable worker for multiprocessing -- must NOT be a
    closure (that's exactly what broke the differential-evolution script
    earlier this session; spawn-based multiprocessing needs a module-level
    function it can re-import in each worker process).
    """
    config_label, mach, timestamp, p_cost_gen = args
    fixed, unity = _baseline_convention(mach)
    row = solve_hour(mach, timestamp, p_cost_gen=p_cost_gen,
                      fixed_voltage_buses=fixed, unity_pf_buses=unity)
    if row is None:
        return {"config": config_label, "timestamp": timestamp, "_skipped": True}
    row["config"] = config_label
    row["_skipped"] = False
    return row


def run_all_configs_parallel(months: set[int] = STUDY_MONTHS, p_cost_gen: float = ENERGY_PRICE,
                              n_workers: int = 7, limit: int | None = None,
                              shards: tuple[int, ...] | None = None, n_shards: int = 1) -> tuple[pd.DataFrame, list]:
    """All 4 fleet configurations x the full study period, solved as one flat
    pool of independent (config, hour) tasks across n_workers processes.
    Independent tasks pooled together (not one config at a time) keeps every
    worker busy throughout, rather than idling between configs of different
    sizes/solve times.

    `shards`/`n_shards` split the SAME deterministic task list across two
    machines with no overlap: task index i is assigned to shard `i % n_shards`,
    so each machine's slice is an interleaved, representative mix across all
    4 configs and all months -- not "this machine gets config X" (which would
    make the two machines' results non-comparable in solve difficulty) and
    not a naive contiguous slice (which would put every 4gen_all task on one
    side, since configs are the outer loop). Pass e.g. shards=(0,) n_shards=3
    for the 1/3 share, shards=(1,2) n_shards=3 for the 2/3 share.
    """
    import multiprocessing as mp

    configs = _fleet_configs()
    p, _ = load_profiles()
    hours = p.index[p.index.month.isin(months)]
    if limit is not None:
        hours = hours[:limit]

    tasks = [(label, mach, ts, p_cost_gen) for label, mach in configs.items() for ts in hours]
    if shards is not None:
        tasks = [t for i, t in enumerate(tasks) if i % n_shards in shards]
    print(f"{len(tasks)} total tasks ({len(configs)} configs x {len(hours)} hours"
          f"{f', shard {shards} of {n_shards}' if shards is not None else ''}), "
          f"{n_workers} worker processes", flush=True)

    rows, skipped = [], []
    t0 = time.time()
    with mp.Pool(n_workers) as pool:
        for i, result in enumerate(pool.imap_unordered(_solve_one, tasks, chunksize=4)):
            if result["_skipped"]:
                skipped.append(f"{result['config']} {result['timestamp']}")
            else:
                rows.append(result)
            if (i + 1) % 200 == 0 or (i + 1) == len(tasks):
                elapsed = time.time() - t0
                print(f"  {i+1}/{len(tasks)} tasks, {elapsed:.0f}s elapsed, "
                      f"{len(skipped)} skipped", flush=True)
    return pd.DataFrame(rows), skipped


def run_period(mach: dict, months: set[int], label: str, limit: int | None = None,
               p_cost_gen: float = 0.0) -> tuple[pd.DataFrame, list]:
    p, _ = load_profiles()
    hours = p.index[p.index.month.isin(months)]
    if limit is not None:
        hours = hours[:limit]
    rows, skipped = [], []
    t0 = time.time()
    for i, ts in enumerate(hours):
        row = solve_hour(mach, ts, p_cost_gen=p_cost_gen)
        (rows if row is not None else skipped).append(row if row is not None else str(ts))
        if (i + 1) % 100 == 0 or (i + 1) == len(hours):
            elapsed = time.time() - t0
            rate = elapsed / (i + 1)
            print(f"  [{label}] {i+1}/{len(hours)} hours, {elapsed:.0f}s elapsed "
                  f"({rate:.2f}s/hour), {len(skipped)} skipped", flush=True)
    return pd.DataFrame(rows), skipped


def main():
    limit = None
    if "--pilot" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--pilot") + 1])
    p_cost_gen = ENERGY_PRICE if "--water-value" in sys.argv else 0.0
    tag = "_waterval" if p_cost_gen else ""

    mach = machines()
    label = f"4-gen, Dec+Jan+Jun+Jul, c_g^P={p_cost_gen:.0f}"
    df, skipped = run_period(mach, STUDY_MONTHS, label, limit=limit, p_cost_gen=p_cost_gen)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"monthly_hourly{tag}{'_pilot' if limit else ''}.csv"
    df.to_csv(out, index=False)
    print(f"\n{len(df)} hours solved, {len(skipped)} skipped, written to {out}")
    if skipped:
        skip_path = RESULTS / f"monthly_hourly{tag}{'_pilot' if limit else ''}_skipped.txt"
        skip_path.write_text("\n".join(skipped))
        print(f"skipped timestamps written to {skip_path}")


def generator_count_comparison() -> pd.DataFrame:
    """2-gen, 3-gen (x2), 4-gen fleets, compared at the same 4 representative
    hours run_experiments.run_seasonal() already uses -- not full hourly
    resolution, since this question (does count/placement matter) doesn't
    need it to answer, and a full cross of 4 configs x 2920 hours would be
    tens of thousands of solves for a question already partly answered.

    Baseline convention scales with the fleet: the single LARGEST machine in
    each configuration holds the fixed voltage setpoint, everyone else runs
    at unity PF -- the same rule the 4-generator convention above reduces to,
    not a special case invented just for this comparison.
    """
    from src.case_data import GEN_BUSES, demand_shapes
    full = machines()

    configs = {
        "2-gen (G1,G2)": ("G1", "G2"),
        "3-gen (G1,G2,G3)": ("G1", "G2", "G3"),
        "3-gen (G1,G2,G4)": ("G1", "G2", "G4"),
        "4-gen (all)": ("G1", "G2", "G3", "G4"),
    }

    shapes = demand_shapes()
    total = shapes.p_scale
    winter_mask = shapes.index.month.isin(WINTER_MONTHS)
    summer_mask = ~winter_mask
    points = {
        "winter_peak": shapes[winter_mask].p_scale.idxmax(),
        "winter_median": (total[winter_mask] - total[winter_mask].median()).abs().idxmin(),
        "summer_peak": shapes[summer_mask].p_scale.idxmax(),
        "summer_median": (total[summer_mask] - total[summer_mask].median()).abs().idxmin(),
    }

    rows = []
    for config_label, names in configs.items():
        mach = {GEN_BUSES[n]: full[GEN_BUSES[n]] for n in names}
        largest = max(mach, key=lambda b: mach[b].s_rated)
        fixed = {largest: V_SETPOINT}
        unity = set(mach) - {largest}
        for point_label, ts in points.items():
            q_price = _q_price_for(ts)
            net_c = build_case_from_hour(ts)
            coord = solve(net_c, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE, q_import_price=q_price)
            net_b = build_case_from_hour(ts)
            base = solve(net_b, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE, q_import_price=q_price,
                         fixed_voltage_buses=fixed, unity_pf_buses=unity)
            rows.append({
                "config": config_label, "point": point_label, "timestamp": ts,
                "n_generators": len(mach),
                "coord_status": coord.status, "base_status": base.status,
                "coord_loss_mw": coord.losses_mw if coord.status == "optimal" else float("nan"),
                "base_loss_mw": base.losses_mw if base.status == "optimal" else float("nan"),
                "coord_vmin": min(coord.v.values()) if coord.status == "optimal" else float("nan"),
                "coord_vmax": max(coord.v.values()) if coord.status == "optimal" else float("nan"),
                "coord_max_line_loading_pct":
                    max(coord.line_loading.values()) if coord.status == "optimal" and coord.line_loading else float("nan"),
            })
    return pd.DataFrame(rows)


if __name__ == "__main__" and "--gen-count" in sys.argv:
    df = generator_count_comparison()
    df.to_csv(RESULTS / "generator_count_comparison.csv", index=False)
    print(df.to_string(index=False))
elif __name__ == "__main__":
    main()
