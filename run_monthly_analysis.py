"""Hourly AC-OPF and settlement engine used by the full-year study.

Scheme 0 (baseline, fixed-voltage) needs its own OPF solve; Schemes 1/2a/3
(capacity / utilisation-nodal / hybrid) are all different payment formulas
applied to the SAME coordinated (physical-cost) solve -- see src/settlement.py
-- so each hour costs exactly two OPF solves, not four.

The public entry point is ``run_fullyear_pricing.py``. This module retains the
single-hour solve and parallel checkpointed runner used by that script.
"""

from __future__ import annotations

import time

import pandas as pd

from src.case_data import build_case_from_hour, load_profiles
from src.cost_models import PhysicalCost
from src.settlement import (
    THREE_ZONES, capacity, cost_recovery, hybrid, load_side_charge,
    performance_adjusted_capacity, variable,
)
from src.study import (
    BASELINE_FIXED_VOLTAGE_BUSES, BASELINE_UNITY_PF_BUSES,
    ENERGY_PRICE, PI_CAP, Q_IMPORT_PRICE, Q_IMPORT_PRICE_SUMMER, V_SETPOINT, machines, solve,
)

WINTER_MONTHS = {10, 11, 12, 1, 2, 3}
STUDY_MONTHS = set(range(1, 13))


def _q_price_for(ts) -> float:
    return Q_IMPORT_PRICE if ts.month in WINTER_MONTHS else Q_IMPORT_PRICE_SUMMER


def _baseline_convention(mach: dict) -> tuple[dict, set]:
    """Only the single LARGEST machine in this fleet holds a fixed voltage
    setpoint; everyone else runs at unity PF. Root-caused for the 4-generator
    fleet and generalized here for any fleet size.
    """
    largest = max(mach, key=lambda b: mach[b].s_rated)
    return {largest: V_SETPOINT}, set(mach) - {largest}


def solve_hour(mach: dict, timestamp, p_cost_gen: float = 0.0,
                fixed_voltage_buses: dict | None = None, unity_pf_buses: set | None = None) -> dict | None:
    """One real hour, two OPF solves (baseline + coordinated), seven settlements
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
    # generator-facing rate (see src/study.py's PI_CAP definition and
    # caveat), not the Lnett withdrawal tariff used for the utilisation price.
    # These are two structurally different instruments -- conflating them here
    # would be a ~1400x error (q_price=3.478 vs PI_CAP=0.00248 EUR/MVArh).
    settlements = {
        "1_capacity": capacity(mach, coordinated, ENERGY_PRICE, PI_CAP, p_cost_gen=p_cost_gen),
        "2a_variable_nodal": variable(mach, coordinated, ENERGY_PRICE, pricing="nodal", p_cost_gen=p_cost_gen),
        "2b_variable_uniform": variable(mach, coordinated, ENERGY_PRICE, pricing="uniform", p_cost_gen=p_cost_gen),
        "2c_variable_awu": variable(mach, coordinated, ENERGY_PRICE, pricing="awu", p_cost_gen=p_cost_gen),
        "2d_variable_awu3": variable(mach, coordinated, ENERGY_PRICE, pricing="awu", zones=THREE_ZONES, p_cost_gen=p_cost_gen),
        "4_performance_capacity": performance_adjusted_capacity(mach, coordinated, ENERGY_PRICE, PI_CAP, p_cost_gen=p_cost_gen),
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
        "0_baseline_objective_eur_h": baseline.objective,
        "coordinated_objective_eur_h": coordinated.objective,
        "0_baseline_slack_q_mvar": baseline.slack_q,
        "coordinated_slack_q_mvar": coordinated.slack_q,
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
        row[f"lambda_p_{tag}"] = coordinated.p_price[b]
        row[f"{tag}_field_binding"] = coordinated.binding[b]["field"]
        row[f"{tag}_stator_binding"] = coordinated.binding[b]["stator"]
        row[f"{tag}_underexcited_binding"] = coordinated.binding[b]["underexcited"]
    # Every bus, not just generator buses -- for the spatial (distance-to-
    # generator vs. price/voltage) analysis. Cheap: coordinated.v/p_price/
    # q_price already cover the full network (src/opf.py loops over all ppc
    # buses), this was previously just not being extracted into the row.
    for b in coordinated.v:
        row[f"v_bus{b}"] = coordinated.v[b]
        row[f"lambda_q_bus{b}"] = coordinated.q_price[b]
        row[f"lambda_p_bus{b}"] = coordinated.p_price[b]
    return row


def _solve_one(args) -> dict | None:
    """Top-level, picklable worker for multiprocessing -- must NOT be a
    closure (that's exactly what broke the differential-evolution script
    earlier this session; spawn-based multiprocessing needs a module-level
    function it can re-import in each worker process).

    Wrapped in try/except: a full-year run is ~8760 hours and must not die
    because one hour raised something unexpected (a data lookup edge case,
    a transient solver crash) -- that hour is recorded as skipped, with the
    exception text, and the run continues. Never let one bad hour take down
    the other 8759.
    """
    config_label, mach, timestamp, p_cost_gen = args
    try:
        fixed, unity = _baseline_convention(mach)
        row = solve_hour(mach, timestamp, p_cost_gen=p_cost_gen,
                          fixed_voltage_buses=fixed, unity_pf_buses=unity)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
        return {"config": config_label, "timestamp": timestamp, "_skipped": True,
                "_error": f"{type(exc).__name__}: {exc}"}
    if row is None:
        return {"config": config_label, "timestamp": timestamp, "_skipped": True, "_error": None}
    row["config"] = config_label
    row["_skipped"] = False
    return row


def run_all_configs_parallel(months: set[int] = STUDY_MONTHS, p_cost_gen: float = ENERGY_PRICE,
                              n_workers: int = 7, limit: int | None = None,
                              shards: tuple[int, ...] | None = None, n_shards: int = 1,
                              configs: dict | None = None,
                              checkpoint_path: str | None = None,
                              checkpoint_every: int = 500) -> tuple[pd.DataFrame, list]:
    """The configured fleet cases x the study period, solved as one flat
    pool of independent (config, hour) tasks across n_workers processes.
    Independent tasks are pooled together to keep every worker busy.

    `shards`/`n_shards` split the SAME deterministic task list across two
    machines with no overlap: task index i is assigned to shard `i % n_shards`,
    so each machine's slice is an interleaved, representative mix across all
    4 configs and all months -- not "this machine gets config X" (which would
    make the two machines' results non-comparable in solve difficulty) and
    not a naive contiguous slice (which would put every 4gen_all task on one
    side, since configs are the outer loop). Pass e.g. shards=(0,) n_shards=3
    for the 1/3 share, shards=(1,2) n_shards=3 for the 2/3 share.

    `configs` may override the default production fleet.

    `checkpoint_path`, if given, writes the accumulated results to that CSV
    every `checkpoint_every` completed tasks -- for a run long enough that
    losing it all to a mid-run crash (or an accidental process kill) would
    actually hurt. Each checkpoint is a full overwrite with everything
    solved so far, not an append -- always resumable by reading the latest
    checkpoint, at the cost of only ever losing at most `checkpoint_every`
    tasks' worth of work, not the whole run.
    """
    import multiprocessing as mp

    if configs is None:
        configs = {"4gen_current": machines()}
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

    rows, skipped, errors = [], [], []
    t0 = time.time()
    with mp.Pool(n_workers) as pool:
        for i, result in enumerate(pool.imap_unordered(_solve_one, tasks, chunksize=4)):
            if result["_skipped"]:
                skipped.append(f"{result['config']} {result['timestamp']}")
                if result.get("_error"):
                    errors.append(f"{result['config']} {result['timestamp']}: {result['_error']}")
            else:
                rows.append(result)
            if (i + 1) % 200 == 0 or (i + 1) == len(tasks):
                elapsed = time.time() - t0
                print(f"  {i+1}/{len(tasks)} tasks, {elapsed:.0f}s elapsed, "
                      f"{len(skipped)} skipped ({len(errors)} errors)", flush=True)
            if checkpoint_path and (i + 1) % checkpoint_every == 0:
                pd.DataFrame(rows).to_csv(checkpoint_path, index=False)
                if errors:
                    from pathlib import Path as _Path
                    _Path(checkpoint_path).with_suffix(".errors.txt").write_text("\n".join(errors))
    if checkpoint_path:
        pd.DataFrame(rows).to_csv(checkpoint_path, index=False)
    return pd.DataFrame(rows), skipped
