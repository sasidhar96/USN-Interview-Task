"""Case data: CIGRE MV topology driven by Norwegian CINELDI demand shapes.

Two datasets, each used for what it is good for.

**Topology — CIGRE MV benchmark** (via pandapower). A 20 kV distribution feeder,
R/X ~ 0.70, 44.7 MW / 11.0 MVAr nominal. This is the standard benchmark the
distribution reactive-power literature uses, and it is a voltage level at which
synchronous hydro actually connects.

**Demand shape — CINELDI 50-bus rural reference grid** (Engan et al. 2025,
Zenodo 14528192), 8760 measured hourly P and Q observations from a Norwegian
rural network. Used as a normalised temporal profile, not as a topology.

Why not run the study on the CINELDI network itself: all four CINELDI grids are
230 V with a 114 kW peak and a 15.6 kVAr peak reactive demand. The smallest unit
that is still a synchronous machine (100 kVA) has ~120 kVAr of field-limited
reactive capability -- eight times the whole feeder's peak reactive demand. There
is no scarcity to price. The topology is also wrong for the question: R/X ~ 7.5
in LV cable, against ~0.70 in MV.

Both networks are loadable from here; `build_case` is the one used for results.
"""

from __future__ import annotations

from pathlib import Path

import pandapower as pp
import pandas as pd

DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "raw" / "cineldi_lv" / "dataset"
DEFAULT_GRID = "50_bus_rural_reference_grid"


def load_profiles(grid: str = DEFAULT_GRID) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hourly active (MW) and reactive (MVAr) demand per load bus, 8760 hours."""
    d = DATA_ROOT / grid
    p = pd.read_csv(d / "p_load.csv", parse_dates=["Date"], index_col="Date")
    q = pd.read_csv(d / "q_load.csv", parse_dates=["Date"], index_col="Date")
    if not p.index.equals(q.index):
        raise ValueError("Active and reactive load timestamps do not match")
    if len(p) != 8760:
        raise ValueError(f"Expected 8760 hourly observations, found {len(p)}")
    return p, q


def representative_hours(p: pd.DataFrame, q: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """Deterministic operating hours spanning the year's stress range."""
    pt, qt = p.sum(axis=1), q.sum(axis=1)
    st = (pt**2 + qt**2) ** 0.5
    return {
        "minimum_load": st.idxmin(),
        "median_load": (st - st.median()).abs().idxmin(),
        "peak_active": pt.idxmax(),
        "peak_reactive": qt.idxmax(),
        "peak_apparent": st.idxmax(),
    }


def build_network(timestamp: pd.Timestamp, grid: str = DEFAULT_GRID) -> pp.pandapowerNet:
    """Full published network at one hour. No aggregation, no equivalencing."""
    d = DATA_ROOT / grid
    base = float(pd.read_csv(d / "mpc_base_mva.csv").iloc[0, 0])
    bus_df = pd.read_csv(d / "mpc_bus.csv")
    branch_df = pd.read_csv(d / "mpc_branch.csv", index_col=0)
    p, q = load_profiles(grid)

    net = pp.create_empty_network(sn_mva=base)
    idx = {
        int(row.bus_i): pp.create_bus(net, vn_kv=float(row.basekV), name=str(int(row.bus_i)))
        for row in bus_df.itertuples()
    }
    slack = int(bus_df.loc[bus_df.type == 3, "bus_i"].iloc[0])
    pp.create_ext_grid(net, idx[slack], vm_pu=1.0, name="upstream_grid")

    for row in branch_df.itertuples():
        pp.create_impedance(
            net, idx[int(row.fbus)], idx[int(row.tbus)],
            rft_pu=float(row.r), xft_pu=float(row.x), sn_mva=base,
        )

    for col in p.columns:
        pp.create_load(
            net, idx[int(col)],
            p_mw=float(p.at[timestamp, col]), q_mvar=float(q.at[timestamp, col]),
            name=f"load_{col}",
        )
    return net


def build_rural_case(
    p_scale: float = 1.0, q_scale: float = 1.0,
    timestamp: pd.Timestamp | None = None, grid: str = DEFAULT_GRID,
) -> pp.pandapowerNet:
    """The 50-bus rural grid, fully self-consistent: real topology, real load
    shape, both from the same Lede dataset -- no CIGRE, no borrowed shape.

    Diagnostic case for testing whether reactive power has anything to price
    at LV scale, not the main study network. Loads only -- as with `build_case`
    for CIGRE MV, hydro machines are added separately as a `machines` dict at
    solve time, not as pandapower sgens (an sgen here would double-count: the
    OPF reads net demand straight from pandapower's ppc, which already nets
    out any sgen, then adds machine injection again as its own variable).
    """
    p, q = load_profiles(grid)
    if timestamp is None:
        timestamp = (p.sum(axis=1)**2 + q.sum(axis=1)**2).idxmax()
    net = build_network(timestamp, grid)
    net.load.p_mw *= p_scale
    net.load.q_mvar *= q_scale
    return net


# --- CIGRE MV case, driven by Norwegian demand shapes ---------------------

# Four hydro units, deliberately diverse on two axes: capacity size and
# feeder location. G1/G2 sit on feeder 1 (fed via its own 110/20 kV
# transformer, head at bus 1); G3/G4 sit on feeder 2 (a SEPARATE transformer,
# head at bus 12) -- CIGRE MV's own topology, not an invented partition (see
# net.trafo: two independent transformers). Machine "type" (electrical
# parameters) is reused across sizes rather than invented per unit -- G1's
# type is the Karekezi-sourced reference machine, G2's type is the
# illustrative deviation; G3 reuses G1's type at a smaller rating, G4 reuses
# G2's type smaller still. The story is capacity size and location, not
# invented condition-management differences between otherwise-similar units.
GEN_BUSES = {"G1": 3, "G2": 10, "G3": 13, "G4": 14}


def demand_shapes(grid: str = DEFAULT_GRID) -> pd.DataFrame:
    """Normalised hourly SYSTEM-WIDE P and Q multipliers (all 21 CINELDI load
    buses summed, then scaled by the annual peak).

    For the load SWEEP only (`run_load_sweep`) -- a deliberate, uniform,
    system-wide stress multiplier, e.g. "what if demand were 130% of nominal
    everywhere". Do not use this for a single-hour case that is meant to look
    like a real operating point: applying one national shape to every bus
    forces every load to move in perfect lockstep (correlation 1.0), which is
    not real -- actual CINELDI bus-to-bus correlation is 0.24-0.47, checked
    directly. Use `build_case_from_hour` for that.

    P and Q are each normalised by their OWN max (as before -- that part is
    harmless), but q_scale carries an extra rescaling factor so its MEAN
    matches p_scale's mean. Without it, P and Q peak at different hours (28
    Jan 21:00 vs 25 Jan 22:00 here), so dividing each series by its own,
    independently-timed max multiplies every hour's Q/P ratio by a constant
    bias with no physical meaning -- a review caught this distorting
    modelled tan(phi) network-wide (CIGRE's own nominal tan(phi) was being
    scaled by an arbitrary factor, not the real data's actual variation).
    The rescaling forces E[q_scale] == E[p_scale], so CIGRE's nominal tan(phi)
    is preserved ON AVERAGE across the year, while real hour-to-hour
    departures from that average -- genuine physics -- still come through
    via q_scale's own shape, just without the constant offset. A shared
    single reference HOUR (rather than a mean) was tried first and rejected:
    several buses have near-zero reactive demand at their own active-power
    peak (see `bus_demand_shapes`), which turns a single-hour reference into
    a division-by-zero for exactly the buses that most need a robust fix.
    """
    p, q = load_profiles(grid)
    total_p, total_q = p.sum(axis=1), q.sum(axis=1)
    p_scale = total_p / total_p.max()
    q_scale_raw = total_q / total_q.max()
    q_scale = q_scale_raw * (p_scale.mean() / q_scale_raw.mean())
    return pd.DataFrame({"p_scale": p_scale, "q_scale": q_scale})


def build_case(p_scale: float = 1.0, q_scale: float = 1.0) -> pp.pandapowerNet:
    """CIGRE MV benchmark with every load scaled by the same multiplier.

    System-wide stress sweep only -- see `demand_shapes`. For a single real
    hour, use `build_case_from_hour`.
    """
    import pandapower.networks as nw

    net = nw.create_cigre_network_mv(with_der=False)
    net.load.p_mw *= p_scale
    net.load.q_mvar *= q_scale
    return net


# 13 CIGRE MV load buses, each mapped to a GROUP of real CINELDI households
# (not one each -- see additional_files/documentation/CASE_STUDY_AND_METHODOLOGY.md).
# CIGRE MV is extremely
# skewed: buses 1 and 12 alone are 89% of total demand (19.84 and 20.01 MW);
# the other 11 buses are all under 1 MW. A single real household's shape is a
# reasonable granularity match for the small buses, but far too spiky to
# stand in for buses 1/12 -- those represent many aggregated customers, and a
# real aggregate is smoother than any one customer (the diversity/coincidence
# factor effect). So the two dominant buses get 4 real households EACH,
# summed (not averaged -- summing raw kW is what physical aggregation
# actually is, and it's what produces the smoothing); the next two largest get
# 2; the remaining 9 (all under 0.6 MW, already close to single-household
# scale) get 1 each. 4+4+2+2+9x1 = 21, using every one of the 21 real
# households available exactly once, none reused, none left over. The
# specific column-to-bus pairing beyond the group sizes is arbitrary and
# stated as such.
CIGRE_TO_CINELDI_GROUPS: dict[int, list[str]] = {
    12: ["6", "10", "11", "12"],
    1: ["15", "16", "18", "20"],
    5: ["25", "29"],
    8: ["30", "31"],
    9: ["33"], 6: ["36"], 10: ["39"], 14: ["40"],
    3: ["42"], 4: ["43"], 11: ["48"], 7: ["49"], 13: ["50"],
}


def bus_demand_shapes(grid: str = DEFAULT_GRID) -> dict[int, pd.DataFrame]:
    """Per-CIGRE-bus (p_scale, q_scale) series, each built by SUMMING the raw
    P/Q of that bus's assigned real households, then normalising the summed
    series against that GROUP's own peak-apparent-power hour (shared by P and
    Q), not each series' own independent peak. Summing before normalising is
    what makes larger groups genuinely smoother -- it's physical aggregation,
    not an average.

    Normalising P and Q independently (each by its own max, which occurs at a
    different hour) multiplies every hour's real Q/P ratio by a constant,
    physically-meaningless bias -- caught by review, see `demand_shapes`'s
    docstring for the full explanation and why the fix is a mean-rescale of
    q_scale rather than a shared reference hour (several groups have
    near-zero Q at their own P peak, which breaks a single-hour reference).

    Separate issue, also from review: buses 4 and 6's underlying CINELDI
    households have degenerate reactive-power meters -- Q is exactly zero
    for the large majority of the year, so `q_sum.max()` is set by one rare,
    almost certainly noisy spike (one bus's max is a single ~56 VAr sample).
    The mean-rescale above corrects the AVERAGE bias but, for a series this
    lopsided, the correction factor itself is dominated by that one spike --
    every other hour then gets amplified to match it, reproducing the same
    distortion in a different shape. Guarded by winsorizing q_scale at each
    group's own 99th percentile after rescaling: cheap, standard, and it
    only touches the top ~1% of hours, which is exactly where the spikes
    live -- verified it leaves well-behaved buses (e.g. bus 12, 1, 5)
    numerically unchanged.
    """
    p, q = load_profiles(grid)
    shapes = {}
    for bus, cols in CIGRE_TO_CINELDI_GROUPS.items():
        p_sum, q_sum = p[cols].sum(axis=1), q[cols].sum(axis=1)
        p_scale = p_sum / p_sum.max()
        q_scale_raw = q_sum / q_sum.max()
        q_scale = q_scale_raw * (p_scale.mean() / q_scale_raw.mean()) if q_scale_raw.mean() > 0 else q_scale_raw
        q_scale = q_scale.clip(upper=q_scale.quantile(0.99))
        shapes[bus] = pd.DataFrame({"p_scale": p_scale, "q_scale": q_scale})
    return shapes


def build_case_from_hour(timestamp: pd.Timestamp, grid: str = DEFAULT_GRID) -> pp.pandapowerNet:
    """CIGRE MV at one real hour, each load bus scaled by its OWN group's real
    shape at that hour (see `bus_demand_shapes`) -- not one system-wide shape
    applied everywhere. Use this for any single-hour case meant to represent a
    real, locationally-varied operating point (base case, seasonal runs,
    scheme settlement); `build_case` with a scalar is for the uniform stress
    sweep only.
    """
    import pandapower.networks as nw

    shapes = bus_demand_shapes(grid)
    net = nw.create_cigre_network_mv(with_der=False)
    for bus, shape in shapes.items():
        rows = net.load.bus == bus
        net.load.loc[rows, "p_mw"] *= shape.at[timestamp, "p_scale"]
        net.load.loc[rows, "q_mvar"] *= shape.at[timestamp, "q_scale"]
    return net
