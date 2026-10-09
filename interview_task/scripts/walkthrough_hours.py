"""Three real hours of the full-year study, opened up term by term.

Re-solves the same two AC-OPFs the annual run does (baseline + coordinated) for
a winter, a shoulder and a summer hour, then prints the complete per-generator
ledger: dispatch, capability, physical cost, nodal price, payment under every
scheme, and the operator's own side of the trade.

This is the "who actually gains, and how" walkthrough. The annual CSV stores
fleet totals; this recomputes the per-generator detail behind them.

Run:  python scripts/walkthrough_hours.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.case_data import GEN_BUSES, build_case_from_hour
from src.cost_models import PhysicalCost
from src.hourly_runner import _baseline_convention, _q_price_for
from src.settlement import (
    THREE_ZONES, capacity, hybrid, load_side_charge, performance_adjusted_capacity, variable,
)
from src.study import ENERGY_PRICE, PI_CAP, machines, solve

logging.getLogger("pyomo.core").setLevel(logging.ERROR)

BUS_TO_NAME = {b: n for n, b in GEN_BUSES.items()}

HOURS = [
    ("2021-01-25 12:00:00", "WINTER  -- high demand, pi_Q at the winter rate"),
    ("2021-04-15 18:00:00", "SHOULDER -- mid demand, summer rate (April is outside Oct-Mar)"),
    ("2021-07-15 12:00:00", "SUMMER  -- low demand, pi_Q at the summer rate"),
]


def ledger(ts_text: str, note: str) -> dict | None:
    ts = pd.Timestamp(ts_text)
    mach = machines()
    pi_q = _q_price_for(ts)
    fixed, unity = _baseline_convention(mach)
    cost_model = PhysicalCost(ENERGY_PRICE)

    net_c = build_case_from_hour(ts)
    coord = solve(net_c, mach, cost_model, ENERGY_PRICE,
                  q_import_price=pi_q, p_cost_gen=ENERGY_PRICE)
    net_b = build_case_from_hour(ts)
    base = solve(net_b, mach, cost_model, ENERGY_PRICE,
                 q_import_price=pi_q, p_cost_gen=ENERGY_PRICE,
                 fixed_voltage_buses=fixed, unity_pf_buses=unity)
    if coord.status != "optimal" or base.status != "optimal":
        print(f"\n[skipped {ts} -- baseline {base.status}, coordinated {coord.status}]")
        return None

    print(f"\n{'=' * 96}")
    print(f"{ts}   {note}")
    print(f"{'=' * 96}")
    print(f"  demand {net_c.load.p_mw.sum():.3f} MW + j{net_c.load.q_mvar.sum():.3f} MVAr"
          f"    pi_Q = {pi_q:.4f} EUR/MVArh    lambda_E = {ENERGY_PRICE:.0f} EUR/MWh")

    # ---------------------------------------------------------------- system
    q_imp_b, q_imp_c = base.slack_q, coord.slack_q
    print(f"\n  {'SYSTEM':<44s} {'baseline':>14s} {'coordinated':>14s} {'change':>14s}")
    rows = [
        ("reactive power imported, MVAr", q_imp_b, q_imp_c),
        ("cost of that import, EUR/h", pi_q * abs(q_imp_b), pi_q * abs(q_imp_c)),
        ("active power imported, MW", base.slack_p, coord.slack_p),
        ("network losses, MW", base.losses_mw, coord.losses_mw),
        ("worst line loading, %", max(base.line_loading.values()),
         max(coord.line_loading.values())),
        ("lowest bus voltage, pu", min(base.v.values()), min(coord.v.values())),
        ("OPF objective, EUR/h", base.objective, coord.objective),
    ]
    for label, bv, cv in rows:
        print(f"  {label:<44s} {bv:>14.4f} {cv:>14.4f} {cv - bv:>+14.4f}")

    # ------------------------------------------------------------ generators
    print(f"\n  {'PER GENERATOR':<10s} {'BASELINE (today: obligation, no payment)':>60s}")
    print(f"  {'unit':<5s} {'bus':>4s} {'MVA':>5s} {'mode':>14s} {'P_g':>8s} {'Q_g':>8s} "
          f"{'V':>8s} {'C^Q':>9s} {'payment':>9s} {'profit':>9s}")
    base_cost, coord_cost = {}, {}
    for b, m in mach.items():
        c = cost_model(m, base.p_gen[b], base.q_gen[b], base.v[b])
        base_cost[b] = c
        mode = "V setpoint" if b in fixed else "unity PF"
        print(f"  {BUS_TO_NAME[b]:<5s} {b:>4d} {m.s_rated:>5.0f} {mode:>14s} "
              f"{base.p_gen[b]:>8.4f} {base.q_gen[b]:>8.4f} {base.v[b]:>8.5f} "
              f"{c:>9.5f} {0.0:>9.5f} {-c:>+9.5f}")
    print(f"  {'':<5s} {'':>4s} {'':>5s} {'TOTAL':>14s} {'':>8s} "
          f"{sum(base.q_gen.values()):>8.4f} {'':>8s} {sum(base_cost.values()):>9.5f} "
          f"{0.0:>9.5f} {-sum(base_cost.values()):>+9.5f}")

    print(f"\n  {'':<10s} {'COORDINATED (cost-based AC-OPF dispatch)':>60s}")
    print(f"  {'unit':<5s} {'bus':>4s} {'MVA':>5s} {'binding':>14s} {'P_g':>8s} {'Q_g':>8s} "
          f"{'V':>8s} {'C^Q':>9s} {'lambda^Q':>9s} {'MC':>9s}")
    for b, m in mach.items():
        c = cost_model(m, coord.p_gen[b], coord.q_gen[b], coord.v[b])
        coord_cost[b] = c
        bind = [k for k, v in coord.binding[b].items() if v] or ["-"]
        mc = ENERGY_PRICE * m.marginal_loss(coord.q_gen[b], coord.v[b])
        print(f"  {BUS_TO_NAME[b]:<5s} {b:>4d} {m.s_rated:>5.0f} {','.join(bind):>14s} "
              f"{coord.p_gen[b]:>8.4f} {coord.q_gen[b]:>8.4f} {coord.v[b]:>8.5f} "
              f"{c:>9.5f} {coord.q_price[b]:>9.5f} {mc:>9.5f}")
    print(f"  {'':<5s} {'':>4s} {'':>5s} {'TOTAL':>14s} {'':>8s} "
          f"{sum(coord.q_gen.values()):>8.4f} {'':>8s} {sum(coord_cost.values()):>9.5f}")

    # ------------------------------------------------------------ settlement
    schemes = {
        "0 baseline (no payment)": {b: 0.0 for b in mach},
        "1 capacity (Statnett rate)": capacity(mach, coord, ENERGY_PRICE, PI_CAP,
                                               p_cost_gen=ENERGY_PRICE).payment,
        "2a nodal": variable(mach, coord, ENERGY_PRICE, pricing="nodal",
                             p_cost_gen=ENERGY_PRICE).payment,
        "2b uniform": variable(mach, coord, ENERGY_PRICE, pricing="uniform",
                               p_cost_gen=ENERGY_PRICE).payment,
        "2c AWU 2-zone": variable(mach, coord, ENERGY_PRICE, pricing="awu",
                                  p_cost_gen=ENERGY_PRICE).payment,
        "2d AWU 3-zone": variable(mach, coord, ENERGY_PRICE, pricing="awu", zones=THREE_ZONES,
                                  p_cost_gen=ENERGY_PRICE).payment,
        "4 performance capacity": performance_adjusted_capacity(
            mach, coord, ENERGY_PRICE, PI_CAP, p_cost_gen=ENERGY_PRICE).payment,
        "3 hybrid (capacity+nodal)": hybrid(mach, coord, ENERGY_PRICE, PI_CAP, pricing="nodal",
                                            p_cost_gen=ENERGY_PRICE).payment,
    }
    names = [BUS_TO_NAME[b] for b in mach]
    print(f"\n  SETTLEMENT on the coordinated dispatch -- payment, EUR/h")
    print(f"  {'scheme':<28s} " + " ".join(f"{n:>9s}" for n in names)
          + f" {'total':>9s} {'recovery':>9s}")
    total_cost = sum(coord_cost.values())
    for label, pay in schemes.items():
        tot = sum(pay.values())
        print(f"  {label:<28s} " + " ".join(f"{pay[b]:>9.5f}" for b in mach)
              + f" {tot:>9.5f} {tot / total_cost * 100:>8.1f}%")
    print(f"  {'physical cost C^Q':<28s} " + " ".join(f"{coord_cost[b]:>9.5f}" for b in mach)
          + f" {total_cost:>9.5f}")
    # A generator sitting exactly on its own Q_ref has C^Q = 0 by construction
    # (that is what Q_ref means), so recovery is undefined, not infinite. This
    # happens whenever the underexcitation floor binds: Q_ref clamps up to the
    # floor, the machine is pinned to the floor, so the two coincide.
    def pct(pay: float, cost: float) -> str:
        return "     n/a" if abs(cost) < 1e-9 else f"{pay / cost * 100:>8.1f}"

    print(f"\n  per-generator recovery under nodal, %   (n/a = C^Q is exactly zero,")
    print(f"                                           the machine sits on its own Q_ref)")
    print(f"  {'':<28s} " + " ".join(
        f"{pct(schemes['2a nodal'][b], coord_cost[b])}%" for b in mach))

    # ------------------------------------------------------------- operator
    charge = load_side_charge(net_c, coord)
    q_avoided = abs(q_imp_b) - abs(q_imp_c)
    nodal_total = sum(schemes["2a nodal"].values())
    print(f"\n  THE OPERATOR'S TRADE")
    print(f"    reactive import avoided vs baseline   {q_avoided:>10.4f} MVAr")
    print(f"    value of that at pi_Q                 {q_avoided * pi_q:>10.5f} EUR/h")
    print(f"    paid to generators under nodal        {nodal_total:>10.5f} EUR/h")
    print(f"    operator's net gain                   {q_avoided * pi_q - nodal_total:>+10.5f} EUR/h")
    print(f"    (cross-check) objective saving        {base.objective - coord.objective:>+10.5f} EUR/h")
    print(f"    load-side charge at the same prices   {sum(charge.values()):>10.5f} EUR/h")

    print(f"\n  THE GENERATORS' TRADE   (profit = payment - C^Q; active energy cancels)")
    print(f"  {'unit':<5s} {'baseline profit':>17s} {'nodal profit':>14s} "
          f"{'hybrid profit':>15s} {'better off?':>13s}")
    for b in mach:
        pb = -base_cost[b]
        pn = schemes["2a nodal"][b] - coord_cost[b]
        ph = schemes["3 hybrid (capacity+nodal)"][b] - coord_cost[b]
        print(f"  {BUS_TO_NAME[b]:<5s} {pb:>+17.5f} {pn:>+14.5f} {ph:>+15.5f} "
              f"{('yes' if pn > pb else 'NO'):>13s}")

    # ------------------------------------------------- how the gain is split
    gen_base = -sum(base_cost.values())
    print(f"\n  HOW THE GAIN FROM COORDINATING IS SPLIT")
    print(f"  {'':<28s} {'operator':>12s} {'generators':>12s} {'total':>12s} {'operator %':>12s}")
    for label in ("2a nodal", "2d AWU 3-zone", "1 capacity (Statnett rate)",
                  "3 hybrid (capacity+nodal)"):
        paid = sum(schemes[label].values())
        op_gain = q_avoided * pi_q - paid
        gen_gain = (paid - total_cost) - gen_base
        tot = op_gain + gen_gain
        share = op_gain / tot * 100 if abs(tot) > 1e-12 else float("nan")
        print(f"  {label:<28s} {op_gain:>+12.5f} {gen_gain:>+12.5f} {tot:>+12.5f} "
              f"{share:>11.1f}%")
    print("    operator gain   = value of avoided reactive import - what it pays out")
    print("    generator gain  = (payment - C^Q) under the scheme, minus their")
    print("                      baseline profit, which is negative today")
    return {"ts": ts, "base": base, "coord": coord, "schemes": schemes,
            "coord_cost": coord_cost, "base_cost": base_cost}


def main() -> None:
    print("=" * 96)
    print("THREE REAL HOURS, OPENED UP")
    print("=" * 96)
    print("\n  Baseline convention (today's practice): the largest unit, G1, holds a fixed")
    print("  voltage setpoint of 1.02 pu -- Statnett fos 15's description of a plant that")
    print("  'holds an agreed voltage setpoint and has no delivery of reactive power'.")
    print("  G2, G3 and G4 run at unity power factor, which is what an unpaid operator")
    print("  does (Wolgast et al. 2022). Neither is paid anything.")
    print()
    print("  Read the baseline C^Q column carefully: it is NOT zero. Cost is measured")
    print("  against the machine's own feasible loss minimum Q_ref, which is slightly")
    print("  underexcited -- so sitting at Q = 0 already costs the generator real money")
    print("  today, uncompensated. That is the incentive gap, before any market exists.")

    for ts, note in HOURS:
        ledger(ts, note)


if __name__ == "__main__":
    main()
