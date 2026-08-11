"""Single-generator strategic-misreporting illustration.

Tier-3 "withholding experiment" from the blind review (review/00_synthesis.md),
scoped small deliberately: this is NOT a full game-theoretic/bilevel model
(see MECHANISM_DESIGN_DISCUSSION.md SS4 for why that's out of scope). It answers
one narrow, cheap question -- if ONE generator reports an inflated reactive
cost to the OPF (the only lever it has, since dispatch is centrally cleared
against reported cost, not chosen by the generator), does its TRUE profit
under the nodal settlement scheme (2a) go up or down relative to truthful
reporting?

Method: solve the coordinated OPF twice at the same real hour. Run 1: every
generator's true PhysicalCost. Run 2: the target generator's cost is
inflated by `factor` inside the OBJECTIVE only (this is what "misreporting"
means here -- the OPF believes the inflated number and dispatches
accordingly); every other generator stays truthful. In both runs, profit is
computed using the generator's TRUE cost (misreporting doesn't change
physical reality, only what the optimizer believes), so this is an honest
apples-to-apples profit comparison, not a comparison of self-reported numbers.

    python withholding_experiment.py
"""

from __future__ import annotations

import pandas as pd

from src.case_data import build_case_from_hour
from src.cost_models import PhysicalCost
from src.settlement import variable
from run_experiments import ENERGY_PRICE, PI_CAP, Q_IMPORT_PRICE, machines, solve


class MisreportedCost:
    """Wraps a true cost model; one named machine's reported cost to the
    OPF is scaled by `factor`. Everyone else sees/uses the true cost.
    """

    def __init__(self, true_cost, target_name: str, factor: float):
        self.true_cost = true_cost
        self.target_name = target_name
        self.factor = factor
        self.label = f"{true_cost.label}_misreport_{target_name}_x{factor}"

    def __call__(self, machine, p, q, v):
        base = self.true_cost(machine, p, q, v)
        return self.factor * base if machine.name == self.target_name else base


def run_one_hour(timestamp, target_name: str, factor: float, p_cost_gen: float = ENERGY_PRICE):
    mach = machines()
    true_cost = PhysicalCost(ENERGY_PRICE)

    net_true = build_case_from_hour(timestamp)
    truthful = solve(net_true, mach, true_cost, ENERGY_PRICE,
                      q_import_price=Q_IMPORT_PRICE, p_cost_gen=p_cost_gen)

    misreport_cost = MisreportedCost(true_cost, target_name, factor)
    net_lie = build_case_from_hour(timestamp)
    misreported = solve(net_lie, mach, misreport_cost, ENERGY_PRICE,
                         q_import_price=Q_IMPORT_PRICE, p_cost_gen=p_cost_gen)

    if truthful.status != "optimal" or misreported.status != "optimal":
        return None

    target_bus = next(b for b, m in mach.items() if m.name == target_name)
    m = mach[target_bus]

    def true_profit(result):
        s = variable(mach, result, ENERGY_PRICE, pricing="nodal", p_cost_gen=p_cost_gen)
        # profit computed from TRUE cost regardless of what was reported to the OPF
        true_service_cost = true_cost(m, result.p_gen[target_bus], result.q_gen[target_bus], result.v[target_bus])
        revenue_p = ENERGY_PRICE * result.p_gen[target_bus]
        gen_cost = p_cost_gen * result.p_gen[target_bus]
        return revenue_p + s.payment[target_bus] - true_service_cost - gen_cost

    return {
        "timestamp": timestamp, "target": target_name, "factor": factor,
        "truthful_p": truthful.p_gen[target_bus], "truthful_q": truthful.q_gen[target_bus],
        "truthful_lambda_q": truthful.q_price[target_bus],
        "truthful_true_profit": true_profit(truthful),
        "misreport_p": misreported.p_gen[target_bus], "misreport_q": misreported.q_gen[target_bus],
        "misreport_lambda_q": misreported.q_price[target_bus],
        "misreport_true_profit": true_profit(misreported),
    }


def main():
    hours = pd.date_range("2021-01-10", "2021-01-17", freq="6h")[:-1]
    factors = [1.5, 2.0, 3.0]
    rows = []
    for ts in hours:
        for factor in factors:
            r = run_one_hour(ts, "G1", factor)
            if r is not None:
                r["profit_gain_from_lying"] = r["misreport_true_profit"] - r["truthful_true_profit"]
                rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv("results/withholding_experiment.csv", index=False)
    print(df[["timestamp", "factor", "truthful_true_profit", "misreport_true_profit",
              "profit_gain_from_lying"]].to_string())
    print()
    print(f"{len(df)} (hour, factor) combinations tested")
    print(f"lying was profitable in {(df.profit_gain_from_lying > 1e-6).sum()}/{len(df)} cases")
    print(f"mean profit gain from lying: {df.profit_gain_from_lying.mean():.5f} EUR/h "
          f"(vs truthful mean profit {df.truthful_true_profit.mean():.5f} EUR/h)")


if __name__ == "__main__":
    main()
