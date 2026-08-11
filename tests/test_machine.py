import numpy as np
import pandapower as pp
import pandapower.networks as nw
import pytest

from src.cost_models import AssumedCost, DeadbandCost, PhysicalCost
from src.machine import Machine
from src.case_data import build_case
from src.opf import solve

S_BASE = 1.0


def g1() -> Machine:
    # Karekezi, Melfald, Oyvang & Noland (2023), IEEE TEC 38(2), Tables I-II --
    # 103 MVA reference machine, verified directly against the PDF.
    return Machine.from_nameplate(
        "G1", 8.0, S_BASE, cos_phi=0.90, x_d_pu=1.087, r_a_pu=0.002,
        rotor_loss_frac=(15.88 + 175.78) / 103_000, p_max_pu=0.85, p_min_pu=0.15,
    )


def g2() -> Machine:
    return Machine.from_nameplate(
        "G2", 5.0, S_BASE, cos_phi=0.90, x_d_pu=1.3, r_a_pu=0.002,
        rotor_loss_frac=0.0024, p_max_pu=0.85, p_min_pu=0.15,
    )


def test_q_star_is_negative():
    """Minimum-loss reactive point is slightly underexcited."""
    for m in (g1(), g2()):
        assert m.q_star(1.0) < 0


def test_q_star_scales_with_v_squared():
    """Q* = -k_f*X_s*V^2/(R_a+k_f*X_s^2) is quadratic in V, not linear.

    Every other test in this file runs at V=1.0, where V and V^2 are
    numerically indistinguishable -- a mutation-testing pass (review) found
    5 of 7 single-token mutations, including V^2 -> V in q_star, survived
    the entire suite because of exactly this gap. Checked at two voltages
    away from 1.0 so a linear-in-V bug (or any other exponent) is caught.
    """
    m = g1()
    q_star_1 = m.q_star(0.95)
    q_star_2 = m.q_star(1.05)
    assert q_star_2 / q_star_1 == pytest.approx((1.05 / 0.95) ** 2, rel=1e-9)
    assert m.loss(0.5 * m.p_max, m.q_star(0.95), 0.95) == pytest.approx(
        min(m.loss(0.5 * m.p_max, q, 0.95) for q in np.linspace(-2, 2, 20_001)), rel=1e-3
    )


def test_loss_minimum_at_q_star():
    """Numerical argmin over Q matches the analytical Q*."""
    m = g1()
    q = np.linspace(-3 * abs(m.q_star(1.0)), 3 * abs(m.q_star(1.0)), 200_001)
    numeric = q[np.argmin(m.loss(0.5 * m.p_max, q, 1.0))]
    assert numeric == pytest.approx(m.q_star(1.0), rel=1e-3)


def test_cost_is_nonnegative():
    """C^Q >= 0 everywhere, and exactly zero at Q*."""
    cost = PhysicalCost(70.0)
    for m in (g1(), g2()):
        for q in np.linspace(-m.s_rated, m.s_rated, 501):
            assert cost(m, 0.5 * m.p_max, q, 1.0) >= -1e-12
        assert cost(m, 0.5 * m.p_max, m.q_star(1.0), 1.0) == pytest.approx(0.0, abs=1e-12)


def test_capability_limits_consistent():
    """Field circle centred at (0, -V^2/Xs) with radius V*Ef_max/Xs.

    So at P = 0 the field limit permits Q up to V*Ef_max/Xs - V^2/Xs.
    """
    m, v = g1(), 1.0
    q_max = v * m.e_f_max / m.x_s - v**2 / m.x_s
    assert m.field_limit(0.0, q_max, v) == pytest.approx(0.0, abs=1e-9)
    assert m.field_limit(0.0, q_max * 1.01, v) > 0


def test_ef_max_derived_from_rated_point():
    """The nameplate rated point sits exactly on the field limit."""
    m = g1()
    p_rated, q_rated = 0.9 * m.s_rated, (1 - 0.9**2) ** 0.5 * m.s_rated
    assert m.field_limit(p_rated, q_rated, 1.0) == pytest.approx(0.0, abs=1e-9)


def test_base_change_is_self_consistent():
    """Machine-base pu quantities recover their nameplate values."""
    m = g1()
    assert m.s_rated == pytest.approx(8.0)  # 8 MVA on a 1 MVA base
    assert m.x_s * m.s_rated == pytest.approx(1.087)  # back to 1.087 pu machine base


def test_underexcitation_is_a_pf_ray_through_origin():
    """Norwegian grid-code leading-PF limit: Q >= -P*tan(acos(pf_lead_max)).

    A straight ray through the origin, not a voltage-dependent constant --
    doubling P must double the allowed underexcitation at fixed V.
    """
    m, v = g1(), 1.0
    lim_1 = -m.underexcitation_limit(1.0, 0.0, v)  # magnitude of the Q floor at P=1
    lim_2 = -m.underexcitation_limit(2.0, 0.0, v)
    assert lim_2 == pytest.approx(2 * lim_1)
    assert m.underexcitation_limit(1.0, -lim_1, v) == pytest.approx(0.0, abs=1e-9)


def test_rotor_loss_frac_recovered_at_rated_point():
    """k_f is derived so that field loss at the rated point equals the
    cited rotor_loss_frac -- since E_f = E_f_max exactly at rated P,Q,V=1.
    """
    m = g1()
    rotor_loss_frac = (15.88 + 175.78) / 103_000
    assert m.field_loss(0.9 * m.s_rated, (1 - 0.9**2) ** 0.5 * m.s_rated, 1.0) \
        == pytest.approx(rotor_loss_frac * m.s_rated, rel=1e-9)


def _cigre():
    """CIGRE MV benchmark with the two hydro units at their study positions."""
    net = nw.create_cigre_network_mv(with_der=False)
    return net, {3: g1(), 10: g2()}


def test_power_flow_residual():
    """The solved OPF satisfies AC power balance to 1e-6 pu.

    Checked independently of Pyomo by rebuilding S = V .* conj(Y V) from the
    reported voltages and comparing against the dispatched injections.
    """
    net, machines = _cigre()
    r = solve(net, machines, PhysicalCost(70.0), 70.0)
    assert r.status == "optimal"

    replay = nw.create_cigre_network_mv(with_der=False)
    for b in machines:
        pp.create_sgen(replay, b, p_mw=r.p_gen[b], q_mvar=r.q_gen[b])
    pp.runpp(replay, calculate_voltage_angles=True)

    for b, v in r.v.items():
        assert v == pytest.approx(replay.res_bus.vm_pu[b], abs=1e-6)
    assert r.slack_p == pytest.approx(replay.res_ext_grid.p_mw[0], abs=1e-4)
    assert r.slack_q == pytest.approx(replay.res_ext_grid.q_mvar[0], abs=1e-4)


@pytest.mark.parametrize("bus", [3, 5, 9, 10, 12, 14])
def test_unit_conversion(bus):
    """Hand-checked conversion from a per-unit dual to EUR/MVArh.

    The dual of the reactive balance is EUR/h per pu of injection. One pu is
    s_base MVAr, so EUR/MVArh = dual / s_base. Verified independently by
    perturbing the reactive load at one bus and confirming the objective moves
    by price * delta.

    Checked at both generator and non-generator buses on purpose: writing the
    balance with a bare constant on the generation side made Pyomo return the
    multiplier negated at generator buses only, which a single-bus test misses.

    Several CIGRE MV buses carry two load rows, so only the first is bumped --
    a mask assignment would perturb by 2 * delta and appear as a factor-2 error
    in the price.
    """
    net, machines = _cigre()
    delta = 0.01  # small enough to keep finite-difference truncation error << 5%
    base = solve(net, machines, PhysicalCost(70.0), 70.0, q_import_price=16.0)

    bumped, _ = _cigre()
    row = bumped.load[bumped.load.bus == bus].index[0]
    bumped.load.loc[row, "q_mvar"] += delta
    perturbed = solve(bumped, machines, PhysicalCost(70.0), 70.0, q_import_price=16.0)

    measured = (perturbed.objective - base.objective) / delta
    assert measured == pytest.approx(base.q_price[bus], rel=0.05)


def test_price_at_unconstrained_generator_equals_its_marginal_cost():
    """With nothing binding, the nodal price is the machine's own dC/dQ.

    This is the economic consistency check the whole result rests on: if it
    fails, the duals are not prices.
    """
    net, machines = _cigre()
    r = solve(net, machines, PhysicalCost(70.0), 70.0, q_import_price=16.0)
    for bus, mach in machines.items():
        if any(r.binding[bus][k] for k in ("field", "stator", "underexcited")):
            continue
        analytic = 70.0 * mach.marginal_loss(r.q_gen[bus], r.v[bus])
        assert r.q_price[bus] == pytest.approx(analytic, rel=0.02)


def test_deadband_cost_zero_inside_free_zone_positive_outside():
    """Case D: free within the deadband, Case A's rate applies only beyond it."""
    m = g1()
    cost = DeadbandCost(70.0, threshold=0.30)
    p = 0.5 * m.p_max
    assert cost(m, p, 0.25 * p, 1.0) == pytest.approx(0.0, abs=1e-2)  # inside 30%, eps-smoothed
    assert cost(m, p, 0.60 * p, 1.0) > 0.0  # outside 30%


def test_four_generator_fleet_solves():
    """The full G1-G4 fleet (run_experiments.machines(), two feeders, two
    machine types) solves cleanly -- not just the original 2-generator pair.
    """
    from run_experiments import ENERGY_PRICE, machines as fleet_machines

    net = build_case(1.0, 1.0)
    r = solve(net, fleet_machines(), PhysicalCost(ENERGY_PRICE), ENERGY_PRICE)
    assert r.status == "optimal"
    assert len(r.p_gen) == 4


def test_settlement_profit_does_not_double_count_loc():
    """Total profit = revenue_p + payment - service_cost - gen_cost, with LOC
    reported but NOT subtracted -- revenue_p already reflects the generator's
    actual (possibly LOC-reduced) dispatch, so subtracting LOC again would
    double-count the same foregone revenue.
    """
    from src.settlement import capacity

    net, mach = _cigre()
    r = solve(net, mach, PhysicalCost(70.0), 70.0)
    s = capacity(mach, r, 70.0, pi_cap=16.0)
    for b in mach:
        expected = s.revenue_p[b] + s.payment[b] - s.service_cost[b] - s.gen_cost[b]
        assert s.profit[b] == pytest.approx(expected)


def test_thermal_limit_respected():
    """Branch current constraints keep every CIGRE MV line under 100% loading
    (small numeric tolerance) at nominal load. Before this constraint existed,
    the unconstrained physical-cost dispatch pushed line 1-2 to 128% loading
    -- checked directly against pandapower's own res_line.loading_percent.
    """
    net, machines = _cigre()
    r = solve(net, machines, PhysicalCost(70.0), 70.0)
    assert r.status == "optimal"
    assert r.line_loading  # constraint actually built (non-empty on CIGRE MV)
    assert max(r.line_loading.values()) <= 100.0 + 1e-3


def test_cost_models_actually_swap():
    """Case A and Case B must produce different reactive dispatch.

    Tested at 60% loading, deliberately. Once the field limit binds, capability
    decides the dispatch and both cost models return the same answer -- the
    models can only differ while the machines are unconstrained.
    """
    machines = {3: g1(), 10: g2()}
    kw = dict(q_import_price=16.0)
    a = solve(build_case(0.6, 0.6), machines, AssumedCost(70.0), 70.0, **kw)
    b = solve(build_case(0.6, 0.6), machines, PhysicalCost(70.0), 70.0, **kw)
    assert a.status == b.status == "optimal"
    assert any(abs(a.q_gen[k] - b.q_gen[k]) > 1e-3 for k in machines)
