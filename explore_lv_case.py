"""Diagnostic, not part of the main study: does reactive power have anything
to price on the CINELDI 50-bus rural grid itself -- real topology, real load,
same DSO (Lede), fully self-consistent, no borrowed shape from anywhere?

This tests the R/X and scarcity argument from earlier in the session
empirically instead of leaving it as a theoretical claim. Four small hydro
units, same cited machine parameters as the main study (SynGenLib reference:
cos_phi 0.9, R_a 0.003), scaled down to LV size and spread across four
different radial branches of the feeder (buses 10, 25, 40, 49 -- confirmed
each carries its own real load column).
"""

from __future__ import annotations

import pandas as pd

from src.case_data import build_rural_case
from src.cost_models import PhysicalCost
from src.machine import Machine
from src.opf import solve
from src.settlement import capacity, hybrid, loss_of_opportunity_cost, variable

ENERGY_PRICE = 70.0  # EUR/MWh, same convention as the main study
# 0.95-1.05 pu (CIGRE MV's band, and solve()'s default) is the WRONG voltage
# limit for this network: a plain power flow with zero local generation
# already sits at Vmin=0.9213 here, and the dataset's own mpc_bus.csv states
# Vmax=1.2/Vmin=0.75 for every bus (a rural LV feeder "close to its limits",
# per the paper's own description). 0.75-1.2 looks like a MATPOWER solver
# safety margin, not a real operating tolerance, so used 0.90-1.05 instead --
# the convention Zhang et al. (2024) cite for LV/distribution voltage limits
# (see Brain note energy-storage-reactive-power-joint-market.md).
V_MIN, V_MAX = 0.90, 1.05
S_BASE_MVA = 0.0344  # this grid's own base -- read directly from
# mpc_base_mva.csv, not from Table 4 of the paper. Table 4 states 0.0334 MVA
# for this grid; the shipped data file says 0.0344. Using the file, since
# that is what the OPF actually solves against (`net.sn_mva`) -- a mismatch
# here would silently scale every machine's per-unit reactance and capability
# limit against the wrong base.
V_SETPOINT = 1.02  # re-tested after resizing -- see main() output

# Lnett LOW VOLTAGE rate (this network genuinely is 230 V, unlike the CIGRE MV
# case, so the LV rate applies here, not the HV rate used elsewhere):
# 85 kr/kVAr winter, verified against tariffhefte 1 Jan 2026.
_NOK_PER_EUR = 11.5
Q_IMPORT_PRICE = 85.0 / _NOK_PER_EUR
PI_CAP = Q_IMPORT_PRICE

HYDRO_BUSES = {"G1": 10, "G2": 25, "G3": 40, "G4": 49}


def machines() -> dict[int, Machine]:
    """Four micro-hydro units, sized against each bus's OWN local peak load
    (checked directly: bus 10 1.66 kW, bus 25 2.52 kW, bus 40 1.36 kW, bus 49
    0.91 kW) -- not against the whole feeder, the same principle that placed
    G1/G2 on CIGRE MV and the one the first pass at this diagnostic skipped
    (35 kVA units against ~1-2 kW local loads, which produced the
    infeasible/edge-of-solver-precision results earlier). Ratings are set to
    roughly 2-3x local peak load, small enough to stay in the micro-hydro
    class this session's own MV-vs-LV argument said belongs at LV in the
    first place -- consistent with that argument, not an exception to it.
    """
    specs = {  # (s_rated_MVA, X_d, rotor_loss_frac)
        "G1": (0.005, 1.1, 0.004),  # bus 10, local peak 1.66 kW
        "G2": (0.006, 1.3, 0.005),  # bus 25, local peak 2.52 kW
        "G3": (0.004, 1.1, 0.004),  # bus 40, local peak 1.36 kW
        "G4": (0.003, 1.3, 0.005),  # bus 49, local peak 0.91 kW
    }
    return {
        HYDRO_BUSES[name]: Machine.from_nameplate(
            name, s_mva, S_BASE_MVA, cos_phi=0.9, x_d_pu=x_d, r_a_pu=0.003,
            rotor_loss_frac=rlf, p_max_pu=0.85, p_min_pu=0.15,
        )
        for name, (s_mva, x_d, rlf) in specs.items()
    }


def main() -> None:
    mach = machines()
    net = build_rural_case(1.0, 1.0)
    print(f"Peak-hour demand: {net.load.p_mw.sum()*1000:.2f} kW / "
          f"{net.load.q_mvar.sum()*1000:.2f} kVAr")
    total_kva = sum(m.s_rated for m in mach.values()) * S_BASE_MVA * 1000
    print(f"Total hydro nameplate: {total_kva:.1f} kVA across {len(mach)} units")

    baseline = solve(net, mach, PhysicalCost(ENERGY_PRICE), ENERGY_PRICE,
                      q_import_price=Q_IMPORT_PRICE, v_min=V_MIN, v_max=V_MAX,
                      unity_pf_buses=set(mach))
    coordinated = solve(build_rural_case(1.0, 1.0), mach, PhysicalCost(ENERGY_PRICE),
                         ENERGY_PRICE, q_import_price=Q_IMPORT_PRICE, v_min=V_MIN, v_max=V_MAX)

    print(f"\nbaseline:     status={baseline.status:10s} loss={baseline.losses_mw*1e3:.4f} kW "
          f"Vmin={min(baseline.v.values()):.4f}")
    print(f"coordinated:  status={coordinated.status:10s} loss={coordinated.losses_mw*1e3:.4f} kW "
          f"Vmin={min(coordinated.v.values()):.4f}")
    print(f"loss saving from coordination: "
          f"{(baseline.losses_mw - coordinated.losses_mw)*1e3:.4f} kW "
          f"({100*(baseline.losses_mw-coordinated.losses_mw)/baseline.losses_mw:.1f}%)")

    print(f"\n{'bus':>4s} {'Q_g (kVAr)':>11s} {'lambda_Q (EUR/MVArh)':>20s} {'binding':>25s}")
    for b, m in mach.items():
        binding = [k for k, v in coordinated.binding[b].items() if v]
        print(f"{b:4d} {coordinated.q_gen[b]*1e3:11.3f} {coordinated.q_price[b]:20.4f} "
              f"{','.join(binding) or '-':>25s}")

    loc = loss_of_opportunity_cost(mach, coordinated, ENERGY_PRICE)
    rows = []
    for settle_fn, name in (
        (lambda: capacity(mach, coordinated, ENERGY_PRICE, PI_CAP), "capacity"),
        (lambda: variable(mach, coordinated, ENERGY_PRICE), "variable"),
        (lambda: hybrid(mach, coordinated, ENERGY_PRICE, PI_CAP), "hybrid"),
    ):
        s = settle_fn()
        rows.append({
            "scheme": name,
            "total_payment_eur_h": sum(s.payment.values()),
            "total_service_cost_eur_h": sum(s.service_cost.values()),
            "total_loc_eur_h": sum(loc.values()),
            "total_profit_eur_h": sum(s.profit.values()),
        })
    df = pd.DataFrame(rows)
    print("\n" + df.round(5).to_string(index=False))


if __name__ == "__main__":
    main()
