"""Independent cross-check of IPOPT's base-case result using a genuinely
different solution paradigm: differential evolution (Storn & Price 1997), a
population-based, gradient-free global metaheuristic -- no KKT conditions, no
Jacobian, no relation to IPOPT's interior-point machinery at all.

No second exact NLP solver is installed in this environment (checked IPOPT,
BONMIN, COUENNE, CONOPT, KNITRO, SCIP, CBC, BARON directly -- only IPOPT and
GLPK are available, and GLPK is LP-only, cannot represent the nonlinear AC
power flow at all). DE is the most meaningful available alternative: it
explores broadly rather than following a gradient, so if the two land on the
same answer, that's real, independent evidence of (near-)global optimality,
complementing the existing 8-random-restart IPOPT check (which only tests
sensitivity to the *starting point* of the *same* algorithm).

Search space reduced to just (P_g, Q_g) per generator -- 8 dimensions for 4
machines, not the full 36-dimensional (V, theta) state space IPOPT solves
over. Feasibility of the power-flow equations is enforced exactly (not
approximated) by calling pandapower's own AC power flow inside the fitness
function for each candidate dispatch; only the *inequality* constraints
(capability limits, voltage band) are enforced via penalty, since DE has no
native constraint-handling for those.

    python verify_with_metaheuristic.py
"""

from __future__ import annotations

import time

import numpy as np
import pandapower as pp
from scipy.optimize import differential_evolution

from src.case_data import build_case
from src.cost_models import PhysicalCost
from run_experiments import ENERGY_PRICE, Q_IMPORT_PRICE, machines, solve

PENALTY = 1e5


def make_fitness(mach, cost_model, energy_price, q_import_price):
    bus_list = sorted(mach)

    def fitness(x):
        net = build_case(1.0, 1.0)
        for i, b in enumerate(bus_list):
            p, q = x[2 * i], x[2 * i + 1]
            pp.create_sgen(net, b, p_mw=p, q_mvar=q)
        try:
            pp.runpp(net, calculate_voltage_angles=True)
        except Exception:
            return 1e9  # power flow itself didn't converge for this candidate

        vmin, vmax = net.res_bus.vm_pu.min(), net.res_bus.vm_pu.max()
        p_slack = net.res_ext_grid.p_mw.iloc[0]
        q_slack = net.res_ext_grid.q_mvar.iloc[0]

        obj = energy_price * p_slack + q_import_price * abs(q_slack)
        penalty = PENALTY * (max(0.0, 0.95 - vmin) + max(0.0, vmax - 1.05))
        # Branch thermal limit -- the real OPF enforces this (src/opf.py's
        # i_max constraint); the first version of this script omitted it,
        # which let DE "beat" IPOPT by 3.85% at 130.8% line loading. Not a
        # sign IPOPT missed the optimum -- a sign this fitness function was
        # missing a constraint IPOPT actually has.
        if len(net.res_line):
            penalty += PENALTY * max(0.0, net.res_line.loading_percent.max() - 100.0) / 100.0
        for i, b in enumerate(bus_list):
            p, q = x[2 * i], x[2 * i + 1]
            m = mach[b]
            v = net.res_bus.vm_pu[b]
            obj += cost_model(m, p, q, v)
            penalty += PENALTY * max(0.0, m.stator_limit(p, q, v))
            penalty += PENALTY * max(0.0, m.field_limit(p, q, v))
            penalty += PENALTY * max(0.0, m.underexcitation_limit(p, q, v))
        return obj + penalty

    return fitness, bus_list


def main():
    mach = machines()
    cost_model = PhysicalCost(ENERGY_PRICE)
    fitness, bus_list = make_fitness(mach, cost_model, ENERGY_PRICE, Q_IMPORT_PRICE)
    bounds = [(mach[b].p_min, mach[b].p_max) if j % 2 == 0 else (-mach[b].s_rated, mach[b].s_rated)
              for b in bus_list for j in (0, 1)]

    print("IPOPT reference solve (nominal load, physical cost):")
    net = build_case(1.0, 1.0)
    ref = solve(net, mach, cost_model, ENERGY_PRICE, q_import_price=Q_IMPORT_PRICE)
    print(f"  status={ref.status}  objective={ref.objective:.4f} EUR/h")
    for b in bus_list:
        print(f"  {mach[b].name}: P={ref.p_gen[b]:.4f} MW  Q={ref.q_gen[b]:.4f} MVAr")

    print("\nDifferential evolution (independent, gradient-free, 8-D search):")
    t0 = time.time()
    result = differential_evolution(
        fitness, bounds, seed=42, maxiter=40, popsize=10, tol=1e-8,
        mutation=(0.4, 1.0), recombination=0.7, polish=True,
    )
    dt = time.time() - t0
    print(f"  converged={result.success}  objective={result.fun:.4f} EUR/h  ({dt:.0f}s, {result.nfev} evals)")
    for i, b in enumerate(bus_list):
        print(f"  {mach[b].name}: P={result.x[2*i]:.4f} MW  Q={result.x[2*i+1]:.4f} MVAr")

    print(f"\nObjective gap: {abs(result.fun - ref.objective):.4f} EUR/h "
          f"({100*abs(result.fun - ref.objective)/abs(ref.objective):.3f}%)")
    for b in bus_list:
        i = bus_list.index(b)
        dp = abs(result.x[2*i] - ref.p_gen[b])
        dq = abs(result.x[2*i+1] - ref.q_gen[b])
        print(f"  {mach[b].name}: |dP|={dp:.4f} MW  |dQ|={dq:.4f} MVAr")


if __name__ == "__main__":
    main()
