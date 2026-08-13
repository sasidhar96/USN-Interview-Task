"""Canonical fleet, prices and solver wrapper for the full-year study."""

from __future__ import annotations

from .case_data import GEN_BUSES
from .machine import Machine
from .opf import solve as _solve_raw

ENERGY_PRICE = 70.0  # EUR/MWh, assumed water-value convention
S_BASE = 1.0  # CIGRE MV base, MVA
V_SETPOINT = 1.02  # pu, regulated-obligation baseline

# Baseline: the largest unit controls voltage; the smaller units operate at
# unity power factor. This avoids infeasible simultaneous voltage setpoints at
# light load while representing the present obligation-based convention.
BASELINE_FIXED_VOLTAGE_BUSES = {GEN_BUSES["G1"]: V_SETPOINT}
BASELINE_UNITY_PF_BUSES = {
    GEN_BUSES["G2"], GEN_BUSES["G3"], GEN_BUSES["G4"],
}

# Assumed hourly utilisation prices with the order of magnitude of Lnett's
# 2026 high-voltage winter/summer withdrawal tariffs. The source tariff is a
# monthly peak charge, so these are proxies—not literal tariff conversions.
NOK_PER_EUR = 11.5
Q_IMPORT_PRICE = 40.0 / NOK_PER_EUR
Q_IMPORT_PRICE_SUMMER = 5.0 / NOK_PER_EUR

# Statnett fos §15 reference fixed payment for 2024. The source mechanism
# applies to >=10 MVA regional/transmission-connected units; it is retained as
# a benchmark and does not literally apply to this 3–8 MVA distribution fleet.
PI_CAP = 250.0 / NOK_PER_EUR / 8760

# Two 25 MVA CIGRE transformers connect the MV system to the upstream grid.
S_INTERFACE_MAX = 50.0


def solve(net, machines, cost_model, energy_price, **kwargs):
    """Solve with the production interface limit and water-value convention."""
    kwargs.setdefault("s_interface_max", S_INTERFACE_MAX)
    kwargs.setdefault("p_cost_gen", energy_price)
    return _solve_raw(net, machines, cost_model, energy_price, **kwargs)


def machines() -> dict[int, Machine]:
    """Return the four hydrogenerators used in the final study.

    Type A (G1/G3) follows Karekezi et al. (2023), IEEE Transactions on
    Energy Conversion 38(2), Tables I–II. The effective stator coefficient
    includes the paper's armature and stray-load losses:
    ``(P_a* + P_s*) / S_rated = 276.62 / 103000``. Its rotor-loss fraction is
    ``(P_ex* + P_f* + P_br*) / S_rated = (15.88 + 175.78) / 103000``.

    Type B (G2/G4) is an explicitly illustrative higher-reactance,
    higher-rotor-loss variation. Ratings and bus placements are assumed to
    create a heterogeneous but feasible two-feeder case.
    """
    type_a = dict(
        cos_phi=0.90,
        x_d_pu=1.087,
        r_a_pu=276.62 / 103_000,
        rotor_loss_frac=(15.88 + 175.78) / 103_000,
        p_max_pu=0.85,
        p_min_pu=0.15,
    )
    type_b = dict(
        cos_phi=0.90,
        x_d_pu=1.3,
        r_a_pu=276.62 / 103_000,
        rotor_loss_frac=0.0024,
        p_max_pu=0.85,
        p_min_pu=0.15,
    )
    return {
        GEN_BUSES["G1"]: Machine.from_nameplate("G1", 8.0, S_BASE, **type_a),
        GEN_BUSES["G2"]: Machine.from_nameplate("G2", 5.0, S_BASE, **type_b),
        GEN_BUSES["G3"]: Machine.from_nameplate("G3", 6.0, S_BASE, **type_a),
        GEN_BUSES["G4"]: Machine.from_nameplate("G4", 3.0, S_BASE, **type_b),
    }
