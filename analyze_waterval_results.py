"""Diagnostic figures for the water-value 4-month study (results/monthly_hourly_waterval.csv).

Supplementary analysis figures, not the final 3-slide deck figures (those are
src/plotting.py's figure1-4). Answers: does the dispatch make sense, where do
losses come from, how do settlement schemes compare, how far off is the
assumed-cost convention from the physically-derived one.

    python analyze_waterval_results.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from run_experiments import machines

RESULTS = Path(__file__).parent / "results"
FIGURES = RESULTS / "figures"
GEN_COLOUR = {"g1": "#1f5c8b", "g2": "#c1440e", "g3": "#2e8b57", "g4": "#9b59b6"}
SCHEME_COLOUR = {
    "0_baseline": "#8c8c8c", "1_capacity": "#c1440e",
    "2a_variable_nodal": "#1f5c8b", "3_hybrid": "#2e8b57",
}


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25, lw=0.6)


def fig_dispatch(df, mach, path):
    """P and Q dispatch per generator, monthly box plots -- sense check."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    months = sorted(df.month.unique())
    for ax, var, ylabel in zip(axes, ["p", "q"], ["Active power P (MW)", "Reactive power Q (MVAr)"]):
        width = 0.18
        for i, (b, m) in enumerate(sorted(mach.items())):
            tag = m.name.lower()
            data = [df.loc[df.month == mo, f"{var}_{tag}_mw" if var == "p" else f"{var}_{tag}_mvar"]
                    for mo in months]
            positions = [j + (i - 1.5) * width for j in range(len(months))]
            bp = ax.boxplot(data, positions=positions, widths=width, patch_artist=True,
                             showfliers=False, medianprops=dict(color="black", lw=1.2))
            for patch in bp["boxes"]:
                patch.set_facecolor(GEN_COLOUR[tag])
                patch.set_alpha(0.75)
            if var == "p":
                ax.axhline(m.p_min, color=GEN_COLOUR[tag], ls=":", lw=0.8, alpha=0.6)
        ax.set_xticks(range(len(months)))
        ax.set_xticklabels([{12: "Dec", 1: "Jan", 6: "Jun", 7: "Jul"}[mo] for mo in months])
        ax.set_ylabel(ylabel)
        _style(ax)
    handles = [plt.Rectangle((0, 0), 1, 1, fc=GEN_COLOUR[m.name.lower()], alpha=0.75) for m in mach.values()]
    fig.suptitle("Generator dispatch by month, coordinated (physical-cost) case\n"
                  "dotted lines = each machine's own P floor (p_min)", fontsize=11, y=1.0)
    fig.legend(handles, [m.name for m in mach.values()], loc="lower center", ncol=4, frameon=False,
               fontsize=9, bbox_to_anchor=(0.5, -0.05))
    fig.tight_layout(rect=(0, 0.03, 1, 0.90))
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def fig_line_loading(df, path):
    """Max line loading distribution, baseline vs coordinated."""
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.hist(df["0_baseline_max_line_loading_pct"], bins=40, alpha=0.55, color="#8c8c8c", label="Baseline")
    ax.hist(df["coordinated_max_line_loading_pct"], bins=40, alpha=0.55, color="#1f5c8b", label="Coordinated")
    ax.set_xlabel("Max line loading across the feeder (%)")
    ax.set_ylabel("Hours")
    ax.set_title("Line loading distribution, 2,915 real hours\nDec+Jan+Jun+Jul, water-value convention")
    ax.legend(frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def fig_loss_composition(df, mach, path):
    """Stacked bar: network loss vs each machine's stator/field loss, mean MW."""
    fig, ax = plt.subplots(figsize=(7, 5))
    labels = ["Network\n(line I²R)"] + [m.name for m in sorted(mach.values(), key=lambda m: m.name)]
    network = df["coordinated_loss_mw"].mean()
    stator = [0.0] + [df[f"{m.name.lower()}_stator_loss_mw"].mean() for m in sorted(mach.values(), key=lambda m: m.name)]
    field = [0.0] + [df[f"{m.name.lower()}_field_loss_mw"].mean() for m in sorted(mach.values(), key=lambda m: m.name)]
    network_bar = [network] + [0.0] * len(mach)
    x = range(len(labels))
    ax.bar(x, network_bar, color="#8c8c8c", label="Network (line)")
    ax.bar(x, stator, bottom=network_bar, color="#c1440e", label="Stator (armature) copper")
    bottom2 = [n + s for n, s in zip(network_bar, stator)]
    ax.bar(x, field, bottom=bottom2, color="#1f5c8b", label="Field (rotor) copper")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean loss (MW)")
    ax.set_title("Where the losses come from\nmean over 2,915 hours, coordinated dispatch")
    ax.legend(frameon=False, fontsize=9)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def fig_avoidable_loss(df, mach, path):
    """Each machine's loss at actual Q vs at its own Q* (same P,V) -- how much is 'the price of service'."""
    fig, ax = plt.subplots(figsize=(7, 5))
    names = [m.name for m in sorted(mach.values(), key=lambda m: m.name)]
    actual = [df[f"{n.lower()}_machine_loss_mw"].mean() for n in names]
    at_qstar = [df[f"{n.lower()}_loss_at_qstar_mw"].mean() for n in names]
    x = range(len(names))
    w = 0.35
    ax.bar([i - w / 2 for i in x], at_qstar, width=w, color="#2e8b57", label="Loss at own Q* (loss-minimising)")
    ax.bar([i + w / 2 for i in x], actual, width=w, color="#c1440e", label="Loss at actual dispatched Q")
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel("Mean machine loss (MW)")
    ax.set_title("Machine loss: actual dispatch vs loss-minimising Q*\n"
                  "the gap is the physical cost of providing reactive power away from Q*")
    ax.legend(frameon=False, fontsize=9)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def fig_scheme_comparison(df, path):
    """Total payment and cost-recovery ratio per settlement scheme."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    schemes = ["0_baseline", "1_capacity", "2a_variable_nodal", "3_hybrid"]
    labels = ["0 Baseline", "1 Capacity\n(Statnett rate)", "2a Nodal\nutilisation", "3 Hybrid"]
    totals = [df[f"{s}_total_payment_eur_h"].sum() for s in schemes]
    axes[0].bar(labels, totals, color=[SCHEME_COLOUR[s] for s in schemes])
    axes[0].set_ylabel("Total payment, 2,915 hours (EUR)")
    axes[0].set_title("Total generator payment by scheme")
    _style(axes[0])

    # service cost is scheme-independent (same coordinated dispatch); recover it once
    service_cost_total = (df["1_capacity_total_payment_eur_h"] - df["1_capacity_total_profit_eur_h"]).sum()
    recovery = [0.0] + [100 * df[f"{s}_total_payment_eur_h"].sum() / service_cost_total for s in schemes[1:]]
    axes[1].bar(labels, recovery, color=[SCHEME_COLOUR[s] for s in schemes])
    axes[1].set_ylabel("Payment / generators' own service cost (%)")
    axes[1].set_title("Cost recovery: does the payment\ncover what it cost to provide?")
    axes[1].axhline(100, color="black", ls=":", lw=1)
    _style(axes[1])
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def fig_case_a_vs_b_price(sweep_path, path):
    """Assumed (Case A, flat 0.1x) vs physical (Case B) reactive price -- the core thesis, quantified."""
    df = pd.read_csv(sweep_path)
    opt = df[df.status == "optimal"]
    fig, ax = plt.subplots(figsize=(7, 5))
    assumed = opt[opt.case == "assumed"].sort_values("load_scale")
    physical = opt[opt.case == "physical"].sort_values("load_scale")
    ax.plot(assumed.p_demand_mw, assumed.lambda_q_g1, color="#c1440e", lw=2, label="Case A: assumed (0.1x energy price)")
    ax.plot(physical.p_demand_mw, physical.lambda_q_g1, color="#1f5c8b", lw=2, label="Case B: physically derived")
    ax.set_yscale("log")
    ax.set_xlabel("Feeder active demand (MW)")
    ax.set_ylabel(r"Reactive price $\lambda^Q$ at G1 (EUR/MVArh), log scale")
    ax.set_title("Assumed vs physically-derived reactive price\n"
                  "~28x apart at typical load -- not just a different shape")
    ax.legend(frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(RESULTS / "monthly_hourly_waterval_with_losses.csv", parse_dates=["timestamp"])
    mach = machines()

    fig_dispatch(df, mach, FIGURES / "waterval_dispatch_by_month.png")
    fig_line_loading(df, FIGURES / "waterval_line_loading.png")
    fig_loss_composition(df, mach, FIGURES / "waterval_loss_composition.png")
    fig_avoidable_loss(df, mach, FIGURES / "waterval_avoidable_loss.png")
    fig_scheme_comparison(df, FIGURES / "waterval_scheme_comparison.png")
    fig_case_a_vs_b_price(RESULTS / "load_sweep.csv", FIGURES / "waterval_case_a_vs_b_price.png")
    print("wrote 6 figures to", FIGURES)


if __name__ == "__main__":
    main()
