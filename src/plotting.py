"""The three figures for the deck. matplotlib only, 150 dpi, white background."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# One colour per case, held across all figures.
COLOUR = {"free": "#8c8c8c", "assumed": "#c1440e", "deadband": "#9b59b6", "physical": "#1f5c8b"}
LABEL = {
    "free": "Case 0 — reactive power free",
    "assumed": r"Case A — assumed $b^Q=0.1\,b^P$ (Potter)",
    "deadband": "Case D — Norwegian deadband (30% free, then Case A rate)",
    "physical": "Case B — derived from machine losses",
}
SYSOPT_PRICE = 0.28  # EUR/MVArh, SysOpt WP4 Nordic-44 equitable point


def figure0_demand(p, q, path):
    """The source data itself: total active and reactive demand across the
    measured year, and the implied power factor this session confirmed is
    NOT constant (Engan et al. 2025, 50-bus rural grid) -- unlike the
    semi-urban CINELDI grids, which assume a fixed PF of 0.98 by construction.
    """
    pt, qt = p.sum(axis=1), q.sum(axis=1)
    pf = pt / (pt**2 + qt**2) ** 0.5

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True,
                              gridspec_kw={"height_ratios": [2, 1]})
    ax = axes[0]
    ax.plot(pt.index, pt.values * 1000, lw=0.6, color="#1f5c8b", label="Active demand P (kW)")
    ax2 = ax.twinx()
    ax2.plot(qt.index, qt.values * 1000, lw=0.6, color="#c1440e", alpha=0.75,
              label="Reactive demand Q (kVAr)")
    ax.set_ylabel("P (kW)", color="#1f5c8b")
    ax2.set_ylabel("Q (kVAr)", color="#c1440e")
    ax.set_title("CINELDI 50-bus rural reference grid — measured hourly demand, 2021",
                  fontsize=11)
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [l.get_label() for l in lines], fontsize=8, frameon=False, loc="upper right")
    _style(ax)

    ax = axes[1]
    ax.plot(pf.index, pf.values, lw=0.5, color="#2e8b57")
    ax.axhline(0.958, color="k", ls="--", lw=1,
               label=r"Lnett deadband, $\tan\varphi=0.30$ ($\cos\varphi\approx0.958$)")
    ax.set_ylabel("Implied power factor")
    ax.set_ylim(0.3, 1.02)
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def figure_bus_profiles(path, buses=(12, 1, 5, 9, 6, 11)):
    """Annual P profile for a sample of CIGRE buses under the per-bus grouped
    real-shape mapping -- the two dominant buses (12, 1; 4 households each),
    two mid-size (5, 9), and two flagged outliers (6: near-zero Q always,
    genuine; 11: very spiky, CoV 1.53). Visual honesty check, not a headline
    figure: are these annual shapes plausible Norwegian residential/rural
    demand, including the outliers.
    """
    from .case_data import bus_demand_shapes, CIGRE_TO_CINELDI_GROUPS
    import pandapower.networks as nw

    net = nw.create_cigre_network_mv(with_der=False)
    peak_p = net.load.groupby("bus").p_mw.sum()
    shapes = bus_demand_shapes()

    fig, axes = plt.subplots(len(buses), 1, figsize=(10, 1.6 * len(buses)), sharex=True)
    for ax, bus in zip(axes, buses):
        series = shapes[bus].p_scale * peak_p[bus] * 1000  # kW
        ax.plot(series.index, series.values, lw=0.4, color="#1f5c8b")
        n = len(CIGRE_TO_CINELDI_GROUPS[bus])
        ax.set_ylabel(f"bus {bus}\n({n} hh)\nkW", fontsize=8)
        ax.tick_params(labelsize=7)
        _style(ax)
    axes[0].set_title("Annual active-demand profile, sample CIGRE MV buses "
                       "(real per-bus CINELDI household mapping)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def _style(ax):
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.set_axisbelow(True)


def figure1(machines, base, path):
    """Capability diagrams with the dispatched operating points."""
    fig, axes = plt.subplots(1, len(machines), figsize=(5.5 * len(machines), 5), sharey=False)
    for ax, (bus, m) in zip(np.atleast_1d(axes), sorted(machines.items())):
        tag = m.name.lower()
        p = np.linspace(0, m.p_max * 1.15, 400)

        stator = np.sqrt(np.maximum(m.s_rated**2 - p**2, 0))
        v = 1.0
        radius2 = (v * m.e_f_max / m.x_s) ** 2 - p**2
        field = np.where(radius2 > 0, np.sqrt(np.maximum(radius2, 0)) - v**2 / m.x_s, np.nan)

        ax.plot(stator, p, color="k", lw=1.4, label="Stator current limit")
        ax.plot(field, p, color="k", ls="--", lw=1.4, label="Field current limit")
        ax.axvline(-0.75 * v**2 / m.x_s, color="k", ls=":", lw=1.2,
                   label="Underexcitation limit")
        ax.axhline(m.p_max, color="0.5", lw=1.0)
        ax.axhline(m.p_min, color="0.5", lw=1.0)
        ax.axvline(m.q_star(v), color="#2e8b57", ls="-.", lw=1.6,
                   label=r"Minimum-loss locus $Q^\star$")

        for _, row in base.iterrows():
            ax.plot(row[f"q_{tag}_mvar"], row[f"p_{tag}_mw"], "o",
                    ms=9, color=COLOUR[row["case"]], mec="k", mew=0.6,
                    label=LABEL[row["case"]], zorder=5)

        ax.set_title(f"{m.name} — {m.s_rated:.0f} MVA at bus {bus}")
        ax.set_xlabel("Reactive power Q (MVAr)")
        ax.set_ylabel("Active power P (MW)")
        ax.set_ylim(0, m.p_max * 1.2)
        ax.set_xlim(-m.s_rated * 0.9, m.s_rated * 1.05)
        _style(ax)

    handles, labels = np.atleast_1d(axes)[0].get_legend_handles_labels()
    seen = dict(zip(labels, handles))
    fig.legend(seen.values(), seen.keys(), loc="lower center", ncol=4, fontsize=8,
               frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Capability diagrams and dispatched operating points "
                 "(nominal load)", fontsize=12)
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def figure2(machines, energy_price, path):
    """Marginal cost of reactive power, every machine, against Case A."""
    fig, ax = plt.subplots(figsize=(8, 5))
    palette = ["#1f5c8b", "#c1440e", "#2e8b57", "#9b59b6", "#e0a800"]
    for i, (bus, m) in enumerate(sorted(machines.items())):
        q = np.linspace(-m.s_rated * 0.6, m.s_rated * 0.8, 400)
        mc = energy_price * m.marginal_loss(q, 1.0)
        ax.plot(q, mc, lw=2, color=palette[i % len(palette)],
                label=f"{m.name} — derived (Case B)")
        ax.plot(m.q_star(1.0), 0, "o", ms=8, color="#2e8b57", mec="k", mew=0.6,
                zorder=5, label=r"$Q^\star$ — zero marginal cost" if i == 0 else None)

    ax.axhline(0.1 * energy_price, color=COLOUR["assumed"], lw=2, ls="--",
               label=r"Case A — $0.1\,\lambda_E$, flat")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("Reactive power Q (MVAr)")
    ax.set_ylabel(r"Marginal cost $\partial C^Q/\partial Q$ (EUR/MVArh)")
    ax.set_title("Marginal cost of reactive power\n"
                 "field loss dominates below $Q^\\star$, stator loss above",
                 fontsize=11)
    ax.legend(fontsize=8, frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def figure3(sweep, path):
    """Reactive price at the load bus against loading, both cases.

    Non-optimal solves are dropped before plotting. `run_load_sweep` keeps
    them in the CSV on purpose (CLAUDE.md SS4.3: record failures, don't
    silently skip), but a failed IPOPT solve's returned duals/binding flags
    are not physically meaningful -- plotting them produced a fake
    field-limit-binding event at the top of a past sweep (review caught
    this: every "field binding" row was also an infeasible row, and
    re-solving those points gave different numbers). Filter first, plot
    second.
    """
    sweep = sweep[sweep.status == "optimal"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for case, grp in sweep.groupby("case"):
        grp = grp.sort_values("load_scale")
        ax.plot(grp.p_demand_mw, grp.lambda_q_g1, lw=2,
                color=COLOUR[case], label=LABEL[case])

    physical = sweep[sweep.case == "physical"].sort_values("load_scale")
    field_bound = physical[physical.g1_field_binding | physical.g2_field_binding]
    congested = physical[physical.max_line_loading_pct >= 99.9]
    if not congested.empty:
        ax.axvspan(congested.p_demand_mw.min(), congested.p_demand_mw.max(),
                   color="#c1440e", alpha=0.08)
        ax.text(congested.p_demand_mw.min(), ax.get_ylim()[1] * 0.92,
                "  feeder trunk at thermal limit", fontsize=8, color="#7a2a08")
    if not field_bound.empty:
        ax.axvspan(field_bound.p_demand_mw.min(), physical.p_demand_mw.max(),
                   color="#1f5c8b", alpha=0.06)
        ax.text(field_bound.p_demand_mw.min(), ax.get_ylim()[1] * 0.85,
                "  G1/G2 field limit binding", fontsize=8, color="#0d2d42")

    ax.axhline(SYSOPT_PRICE, color="#2e8b57", ls=":", lw=1.6)
    ax.text(sweep.p_demand_mw.min(), SYSOPT_PRICE,
            " SysOpt (Nordic-44) equitable price, 0.28 EUR/MVArh",
            fontsize=8, color="#2e8b57", va="bottom")

    ax.set_xlabel("Feeder active demand (MW)")
    ax.set_ylabel(r"Reactive price $\lambda^Q$ at G1 bus (EUR/MVArh)")
    ax.set_title("Nodal reactive price against loading\n"
                 "CIGRE MV benchmark, Norwegian CINELDI demand shapes",
                 fontsize=11)
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def figure4_dispatch_split(machines, sweep, path):
    """Backup figure (CLAUDE.md SS7, generalised from 2 to N generators):
    each machine's own Q dispatch across the load sweep, physical-cost case
    only. Shows the allocation shifting between machines as load rises --
    the point of having more than one machine to compare in the first place.

    Non-optimal solves filtered first -- see `figure3`'s docstring.
    """
    sweep = sweep[sweep.status == "optimal"]
    physical = sweep[sweep.case == "physical"].sort_values("load_scale")
    fig, ax = plt.subplots(figsize=(8, 5))
    palette = ["#1f5c8b", "#c1440e", "#2e8b57", "#9b59b6", "#e0a800"]
    for i, (bus, m) in enumerate(sorted(machines.items())):
        tag = m.name.lower()
        ax.plot(physical.p_demand_mw, physical[f"q_{tag}_mvar"], lw=2,
                color=palette[i % len(palette)],
                label=f"{m.name} ({m.s_rated:.0f} MVA, bus {bus})")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("Feeder active demand (MW)")
    ax.set_ylabel("Dispatched reactive power Q (MVAr)")
    ax.set_title("Reactive dispatch split across generators\n"
                 "physical cost model, load sweep", fontsize=11)
    ax.legend(fontsize=8, frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
