"""Non-convex AC optimal power flow in Pyomo, solved with IPOPT.

Network-agnostic: takes any pandapower net, pulls its admittance matrix, and
attaches synchronous machines at named buses. The reactive cost model is
injected, so Case A and Case B differ by one argument and nothing else.

The nodal reactive price is the dual of the reactive balance constraint.

Note on bus indexing: pandapower expands its network into an internal "ppc"
that can contain auxiliary buses (transformer star points, fused switch nodes),
so the ppc bus set is a superset of `net.bus`. The OPF is built over the ppc bus
set -- taking a submatrix of Ybus over only the pandapower buses silently breaks
power balance. Results are mapped back to pandapower bus indices for reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandapower as pp
import pyomo.environ as pyo
from pandapower.pypower.idx_bus import BASE_KV, BUS_TYPE, PD, QD, REF, VA, VM
from pandapower.pypower.idx_brch import F_BUS, T_BUS
from pandapower.pypower.makeYbus import makeYbus

from .machine import Machine


@dataclass
class Grid:
    """Flat, solver-ready view of a pandapower net."""

    y: np.ndarray
    pd: np.ndarray  # pu, on s_base
    qd: np.ndarray
    slack: int
    s_base: float
    pp_to_ppc: dict  # pandapower bus index -> ppc row
    v_init: np.ndarray
    theta_init: np.ndarray
    v_slack: float
    yf: np.ndarray  # (n_line, n_bus) branch "from"-end current rows, from makeYbus
    yt: np.ndarray  # (n_line, n_bus) branch "to"-end current rows
    i_max: np.ndarray  # per-unit thermal current rating, one row per net.line

    @property
    def n(self) -> int:
        return len(self.pd)


def load_grid(net: pp.pandapowerNet) -> Grid:
    """Run one power flow, then read off the admittance matrix and injections.

    The power flow doubles as the initial point for IPOPT, which is what keeps
    the non-convex problem converging.
    """
    pp.runpp(net, calculate_voltage_angles=True)
    ppc = net._ppc
    base = ppc["baseMVA"]
    ybus, yf, yt = makeYbus(base, ppc["bus"], ppc["branch"])
    y = np.asarray(ybus.todense())
    slack = int(np.flatnonzero(ppc["bus"][:, BUS_TYPE] == REF)[0])
    lut = net._pd2ppc_lookups["bus"]

    # Branch thermal limits, "line" elements only (transformers carry their own
    # sn_mva rating and are out of scope here). Yf/Yt from makeYbus give exact
    # complex branch current as a linear function of the bus voltage vector --
    # If = Yf @ V, It = Yt @ V -- the same construction pypower's own OPF uses
    # for line-flow limits, rather than hand-deriving a pi-model line current.
    # net._pd2ppc_lookups["branch"]["line"] is the contiguous ppc branch row
    # range built from net.line, in net.line's own row order (a pandapower
    # internal invariant, confirmed directly: (0, 15) for CIGRE MV, exactly
    # matching net.line's 15 rows in order).
    lo, hi = net._pd2ppc_lookups.get("branch", {}).get("line", (0, 0))
    branch_from = ppc["branch"][lo:hi, F_BUS].real.astype(int)
    i_base_ka = base / (np.sqrt(3) * ppc["bus"][branch_from, BASE_KV])
    i_max = net.line.max_i_ka.to_numpy() / i_base_ka if hi > lo else np.array([])

    return Grid(
        y=y,
        pd=ppc["bus"][:, PD] / base,
        qd=ppc["bus"][:, QD] / base,
        slack=slack,
        s_base=base,
        pp_to_ppc={int(b): int(lut[b]) for b in net.bus.index},
        v_init=ppc["bus"][:, VM].copy(),
        theta_init=np.radians(ppc["bus"][:, VA]),
        v_slack=float(ppc["bus"][slack, VM]),
        yf=np.asarray(yf[lo:hi].todense()),
        yt=np.asarray(yt[lo:hi].todense()),
        i_max=i_max,
    )


@dataclass
class OPFResult:
    status: str
    objective: float
    v: dict
    p_gen: dict
    q_gen: dict
    q_price: dict  # EUR/MVArh, keyed by pandapower bus
    p_price: dict  # EUR/MWh
    slack_p: float
    slack_q: float
    losses_mw: float
    binding: dict = field(default_factory=dict)
    line_loading: dict = field(default_factory=dict)  # net.line row -> % of max_i_ka


def build_model(
    grid: Grid,
    machines: dict[int, Machine],
    cost_model,
    energy_price: float,
    v_min: float = 0.95,
    v_max: float = 1.05,
    p_cost_gen: float = 0.0,
    q_import_price: float = 0.0,
    fixed_voltage_buses: dict[int, float] | None = None,
    unity_pf_buses: set[int] | None = None,
    s_interface_max: float | None = None,
    warm_start: dict[int, tuple[float, float]] | None = None,
):
    """Assemble the OPF.

    machines: {pandapower bus index -> Machine}. The slack is priced at
    `energy_price`, so network losses are paid for implicitly and need no
    separate objective term -- adding one would double-count.

    `q_import_price` (EUR/MVArh) charges reactive exchange at the TSO-DSO
    interface. Leaving it at zero makes the upstream grid an infinite free
    source of reactive power, so no machine capability limit can ever bind and
    local reactive power has no value. Madureira & Pecas Lopes (2012) let the HV
    network bid into the var market; Ntakou & Caramanis (2015) carry substation
    reactive power as an objective term. Both directions are charged: reactive
    export is as unwelcome at the interface as import. Note this is a
    *price*, not a *limit* -- before `s_interface_max` (below) existed,
    p_slack/q_slack had no upper bound at all, so a cheap-enough local
    generator could export without physical limit. Real generators do get
    paid the same market price whether they are net importing or exporting
    at an instant -- that symmetry is standard, efficient market design, not
    a shortcut -- the missing piece was capacity, not price symmetry.

    `warm_start` ({pandapower bus -> (P_g, Q_g)}), if given, overrides the
    generic pg/qg initial guess (0.6*p_max, Q*) with a specific starting
    point -- e.g. an adjacent hour's own solved dispatch. Tested directly:
    on hours known to hit IPOPT's iteration cap at c_g^P == energy_price
    (a genuinely flat-objective regime, not a bug -- see run_monthly_analysis.py),
    a plain p_min-based guess alone cut failures roughly in half (25 -> 17 of
    25 known-hard hours); a real adjacent-hour warm start is expected to do
    better still, since it starts from an actual nearby solution rather than
    a generic heuristic.

    `s_interface_max` (MVA) bounds the *apparent* power exchanged at the
    interface, `p_slack^2 + q_slack^2 <= s_interface_max^2`, both directions
    -- the real thermal limit of whatever transformer(s) connect this
    network to the upstream grid. None (default) leaves the interface
    unconstrained, matching every result before this parameter existed.

    `fixed_voltage_buses` ({pandapower bus -> V setpoint}) turns a machine into
    a PV bus: voltage is fixed, Q is whatever the power flow requires to hold
    it, and that Q is excluded from the cost sum. This is Scheme 0 -- the
    Statnett fos regulated-obligation baseline, where a plant "holds an agreed
    voltage setpoint and has no delivery of reactive power" and is paid
    nothing. Capability limits still apply, so a setpoint the machine cannot
    physically hold shows up as solver infeasibility rather than being masked.

    `unity_pf_buses` is a second, alternative no-incentive baseline: Q fixed at
    0 rather than V fixed at a setpoint. Better justified than a voltage
    setpoint for small/household-scale plants that don't actively regulate
    voltage at all -- matches the default DG behaviour described in Wolgast et
    al. (2022): "without payment, operators set inverters to unity PF." Fixing
    V at several buses simultaneously can be jointly infeasible on a small,
    tightly-coupled network (confirmed directly on the CINELDI rural grid this
    session); fixing Q=0 is a much weaker constraint and does not have that
    failure mode.
    """
    g_mat, b_mat = grid.y.real, grid.y.imag
    gen_at = {grid.pp_to_ppc[b]: mach for b, mach in machines.items()}
    fixed_voltage_buses = fixed_voltage_buses or {}
    unity_pf_buses = unity_pf_buses or set()
    fixed_gens = {grid.pp_to_ppc[b] for b in fixed_voltage_buses} | \
        {grid.pp_to_ppc[b] for b in unity_pf_buses}

    m = pyo.ConcreteModel()
    m.B = pyo.Set(initialize=range(grid.n))
    m.G = pyo.Set(initialize=sorted(gen_at))

    v_start = np.clip(grid.v_init, v_min, v_max)
    m.v = pyo.Var(m.B, bounds=(v_min, v_max), initialize=lambda _m, i: v_start[i])
    m.theta = pyo.Var(m.B, bounds=(-np.pi / 2, np.pi / 2),
                      initialize=lambda _m, i: grid.theta_init[i])
    m.pg = pyo.Var(m.G, initialize=lambda _m, g: gen_at[g].p_max * 0.6)
    m.qg = pyo.Var(m.G, initialize=lambda _m, g: gen_at[g].q_star(1.0))
    if warm_start:
        for b, (p0, q0) in warm_start.items():
            g = grid.pp_to_ppc[b]
            if g in gen_at:
                m.pg[g].set_value(p0)
                m.qg[g].set_value(q0)
    m.p_slack = pyo.Var(initialize=0.0)
    m.q_slack = pyo.Var(initialize=0.0)
    m.theta[grid.slack].fix(0.0)
    # The upstream grid holds its voltage, as it does in the power flow. Leaving
    # it free would let the OPF buy voltage support for nothing.
    m.v[grid.slack].fix(grid.v_slack)
    for b, v_setpoint in fixed_voltage_buses.items():
        m.v[grid.pp_to_ppc[b]].fix(v_setpoint)
    for b in unity_pf_buses:
        m.qg[grid.pp_to_ppc[b]].fix(0.0)

    def injection(mm, i, reactive):
        return sum(
            mm.v[i] * mm.v[k] * (
                g_mat[i, k] * (pyo.sin if reactive else pyo.cos)(mm.theta[i] - mm.theta[k])
                + (-1 if reactive else 1) * b_mat[i, k]
                * (pyo.cos if reactive else pyo.sin)(mm.theta[i] - mm.theta[k])
            )
            for k in mm.B
        )

    def supply(mm, i, var):
        s = var[i] if i in gen_at else 0.0
        return s + ((mm.p_slack if var is mm.pg else mm.q_slack) if i == grid.slack else 0.0)

    # Written as (injection - supply + load == 0) at every bus, always in this
    # orientation. If the generation side is left as a bare constant -- which it
    # is at any bus without a machine -- Pyomo canonicalises `const == expr`
    # differently from `expr == expr` and the returned multiplier changes sign,
    # so prices come out negated at generator buses only.
    m.p_balance = pyo.Constraint(
        m.B, rule=lambda mm, i: injection(mm, i, False) - supply(mm, i, mm.pg) + grid.pd[i] == 0
    )
    m.q_balance = pyo.Constraint(
        m.B, rule=lambda mm, i: injection(mm, i, True) - supply(mm, i, mm.qg) + grid.qd[i] == 0
    )

    m.p_limit = pyo.Constraint(
        m.G, rule=lambda mm, g: (gen_at[g].p_min, mm.pg[g], gen_at[g].p_max)
    )
    m.stator = pyo.Constraint(
        m.G, rule=lambda mm, g: gen_at[g].stator_limit(mm.pg[g], mm.qg[g], mm.v[g]) <= 0
    )
    m.field = pyo.Constraint(
        m.G, rule=lambda mm, g: gen_at[g].field_limit(mm.pg[g], mm.qg[g], mm.v[g]) <= 0
    )
    m.underexcitation = pyo.Constraint(
        m.G, rule=lambda mm, g: gen_at[g].underexcitation_limit(mm.pg[g], mm.qg[g], mm.v[g]) <= 0
    )
    if s_interface_max is not None:
        # p_slack/q_slack are per-unit on grid.s_base; s_interface_max is
        # documented and passed in as MVA. Divide before comparing -- this
        # only happened to be a no-op while grid.s_base == 1.0 (true for
        # CIGRE MV's default pandapower sn_mva), but silently broke the
        # limit at any other base (review caught it: an intended 20 MVA cap
        # at a 100 MVA base was violated by 89% while still reporting
        # "optimal", since the raw per-unit values were being compared
        # against 20 instead of 0.2).
        s_interface_max_pu = s_interface_max / grid.s_base
        m.interface_capacity = pyo.Constraint(
            expr=m.p_slack**2 + m.q_slack**2 <= s_interface_max_pu**2
        )

    # Branch thermal limits. |I|^2 <= i_max^2 at both ends of each line -- a
    # pi-model line's from- and to-end currents can differ slightly (line
    # charging), so both are checked, matching what pandapower's own
    # loading_percent does (max of both ends).
    m.LN = pyo.Set(initialize=range(len(grid.i_max)))

    def current_sq(mm, g_row, b_row):
        real = sum(g_row[k] * mm.v[k] * pyo.cos(mm.theta[k])
                   - b_row[k] * mm.v[k] * pyo.sin(mm.theta[k]) for k in mm.B)
        imag = sum(g_row[k] * mm.v[k] * pyo.sin(mm.theta[k])
                   + b_row[k] * mm.v[k] * pyo.cos(mm.theta[k]) for k in mm.B)
        return real**2 + imag**2

    yf_g, yf_b = grid.yf.real, grid.yf.imag
    yt_g, yt_b = grid.yt.real, grid.yt.imag
    m.thermal_f = pyo.Constraint(
        m.LN, rule=lambda mm, ln: current_sq(mm, yf_g[ln], yf_b[ln]) <= grid.i_max[ln] ** 2
    )
    m.thermal_t = pyo.Constraint(
        m.LN, rule=lambda mm, ln: current_sq(mm, yt_g[ln], yt_b[ln]) <= grid.i_max[ln] ** 2
    )

    m.cost = pyo.Objective(
        expr=grid.s_base * (
            energy_price * m.p_slack
            + q_import_price * (m.q_slack**2 + 1e-10) ** 0.5
            + sum(
                p_cost_gen * m.pg[g]
                + (0.0 if g in fixed_gens else cost_model(gen_at[g], m.pg[g], m.qg[g], m.v[g]))
                for g in m.G
            )
        ),
        sense=pyo.minimize,
    )
    m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    return m, gen_at


def solve(net, machines, cost_model, energy_price, init_seed: int | None = None, **kwargs) -> OPFResult:
    """Solve the OPF. `init_seed`, if given, jitters the IPOPT starting point
    (bus voltages and angles) with a fixed random seed -- used to check
    whether the solver lands on the same local optimum from different starts,
    since nothing about a non-convex NLP guarantees that on its own.
    """
    grid = load_grid(net)
    if init_seed is not None:
        rng = np.random.default_rng(init_seed)
        grid.v_init = np.clip(grid.v_init + rng.uniform(-0.03, 0.03, grid.n), 0.90, 1.10)
        grid.theta_init = grid.theta_init + rng.uniform(-0.1, 0.1, grid.n)
    m, gen_at = build_model(grid, machines, cost_model, energy_price, **kwargs)
    # max_iter above IPOPT's default (3000): near c_g^P == energy_price the
    # objective is flat in P to first order (see run_monthly_analysis.py),
    # which slows convergence without making the problem infeasible --
    # confirmed directly, several hours that hit maxIterations at the
    # default converge cleanly to "optimal" with more room.
    res = pyo.SolverFactory("ipopt").solve(m, tee=False, options={"max_iter": 20000})
    status = str(res.solver.termination_condition)
    if status != "optimal":
        # Fallback, not the default: analytically, when c_g^P == energy_price
        # the objective's linear term in P_g vanishes exactly, leaving only
        # network losses and C_g^Q's secondary P-dependence -- confirmed
        # directly, the gradient in the P direction is an order of magnitude
        # smaller there than in the Q/V directions. That is real
        # ill-conditioning (IPOPT's default gradient-based scaling doesn't
        # suit it), not a centrality problem (mu_strategy=monotone made no
        # difference in testing). nlp_scaling_method=none cut failures on a
        # sample of confirmed-hard hours from 25/25 to 11/25 -- but it also
        # introduced 2 new failures on a sample of 16 already-easy hours, so
        # it is not a safe global default. Retrying only on failure gets
        # (most of) the benefit without ever regressing an easy case, since
        # the default attempt above always runs first.
        m, gen_at = build_model(grid, machines, cost_model, energy_price, **kwargs)
        res = pyo.SolverFactory("ipopt").solve(
            m, tee=False, options={"max_iter": 20000, "nlp_scaling_method": "none"}
        )
        status = str(res.solver.termination_condition)

    def price(constraint, ppc_bus):
        # The dual is EUR/h per per-unit injection. One pu = s_base MVAr, so
        # EUR/MVArh = dual / s_base. With the balance written as
        # (injection - supply + load == 0), IPOPT returns the multiplier with
        # the opposite sign to the marginal cost of load, so negate. Verified
        # against a finite-difference load perturbation at every bus by
        # `test_unit_conversion`.
        return -m.dual[constraint[ppc_bus]] / grid.s_base

    ppc_to_pp = {v: k for k, v in grid.pp_to_ppc.items()}
    total_gen = pyo.value(m.p_slack) + sum(pyo.value(m.pg[g]) for g in m.G)
    losses = (total_gen - grid.pd.sum()) * grid.s_base

    line_loading = {}
    if len(grid.i_max):
        v_sol = np.array([pyo.value(m.v[i]) for i in m.B])
        theta_sol = np.array([pyo.value(m.theta[i]) for i in m.B])
        v_complex = v_sol * np.exp(1j * theta_sol)
        i_f = np.abs(grid.yf @ v_complex)
        i_t = np.abs(grid.yt @ v_complex)
        loading_pct = np.maximum(i_f, i_t) / grid.i_max * 100
        line_loading = {ln: float(loading_pct[ln]) for ln in range(len(grid.i_max))}

    binding = {}
    for b, mach in machines.items():
        g = grid.pp_to_ppc[b]
        p, q, v = pyo.value(m.pg[g]), pyo.value(m.qg[g]), pyo.value(m.v[g])
        binding[b] = {
            "field": mach.field_limit(p, q, v) > -1e-6,
            "stator": mach.stator_limit(p, q, v) > -1e-6,
            "underexcited": mach.underexcitation_limit(p, q, v) > -1e-6,
            "p_max": abs(p - mach.p_max) < 1e-6,
        }

    return OPFResult(
        status=status,
        objective=pyo.value(m.cost),
        v={ppc_to_pp[i]: pyo.value(m.v[i]) for i in m.B if i in ppc_to_pp},
        p_gen={b: pyo.value(m.pg[grid.pp_to_ppc[b]]) * grid.s_base for b in machines},
        q_gen={b: pyo.value(m.qg[grid.pp_to_ppc[b]]) * grid.s_base for b in machines},
        q_price={ppc_to_pp[i]: price(m.q_balance, i) for i in m.B if i in ppc_to_pp},
        p_price={ppc_to_pp[i]: price(m.p_balance, i) for i in m.B if i in ppc_to_pp},
        slack_p=pyo.value(m.p_slack) * grid.s_base,
        slack_q=pyo.value(m.q_slack) * grid.s_base,
        losses_mw=losses,
        binding=binding,
        line_loading=line_loading,
    )
