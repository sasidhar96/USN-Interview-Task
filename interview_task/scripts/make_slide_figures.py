"""Three standalone, single-panel PNGs for the slide deck (not grouped
multi-panel figures):

  fig_recovery_by_scheme.png  -- slide 4: does the payment cover the
      modeled incremental machine-loss cost, fleet aggregate,
      one bar per scheme including baseline.
  fig_recovery_per_generator.png -- slide 4: same question, per generator,
      under nodal pricing only.
  fig_dispatch_by_machine.png -- slide 3: which machines actually get
      dispatched for reactive duty, and why (Type A/B, no price axis --
      price comparison is slide 4's territory).

Source: results/pricing_mechanisms_fullyear.csv (8,675 real hours, 2021,
production generator placement).

    python scripts/make_slide_figures.py   (run from repo root)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import matplotlib.pyplot as plt
import pandas as pd

from src.case_data import GEN_BUSES
from src.study import PI_CAP, machines
from src.cost_models import PhysicalCost

df = pd.read_csv("results/pricing_mechanisms_fullyear.csv", low_memory=False)

COL_BASE = "#9a9a9a"
COL_SCHEME = "#2e86ab"
COL_GOOD = "#2e8b57"
COL_BAD = "#c0392b"
COL_TYPE_A = "#2e86ab"
COL_TYPE_B = "#e08214"

service_cost_total = (df["1_capacity_total_payment_eur_h"] - df["1_capacity_total_profit_eur_h"]
                       + df["1_capacity_total_revenue_p_eur_h"]).sum() - df["1_capacity_total_revenue_p_eur_h"].sum()

# ---------------------------------------------------------------------------
# Figure 1: recovery by scheme, fleet aggregate (single panel)
# ---------------------------------------------------------------------------
default_style = plt.rcParams.copy()
plt.rcParams.update({
    "font.family": "Arial",
    "font.size": 16,
    "font.weight": "bold",
    "axes.labelweight": "bold",
    "axes.titleweight": "bold",
    "axes.linewidth": 1.8,
    "xtick.major.width": 1.6,
    "ytick.major.width": 1.6,
})
fig, ax = plt.subplots(figsize=(11.8, 6.8))
schemes = [("0_baseline", "Baseline"), ("1_capacity", "Capacity\nfixed"),
           ("2a_variable_nodal", "Nodal\nvariable"), ("2b_variable_uniform", "Uniform"),
           ("2c_variable_awu", "AWU\n2-zone"), ("2d_variable_awu3", "AWU\n3-zone"),
           ("3_hybrid", "Hybrid\ncapacity + nodal")]
recoveries = []
for s, _ in schemes:
    recoveries.append(0.0 if s == "0_baseline" else 100 * df[f"{s}_total_payment_eur_h"].sum() / service_cost_total)
colors = [COL_BASE] + [COL_SCHEME] * (len(schemes) - 2) + ["#6a3d9a"]
bars = ax.bar([l for _, l in schemes], recoveries, color=colors, width=0.62)
ax.axhline(100, color=COL_GOOD, lw=2.2, ls="--", alpha=0.9)
ax.text(0.25, 102.8, "100% = payment equals modeled incremental loss cost", fontsize=13,
        fontweight="bold", color=COL_GOOD, ha="left")
for b, v in zip(bars, recoveries):
    ax.text(b.get_x() + b.get_width() / 2, v + 2.4, f"{v:.1f}%", ha="center",
            fontsize=16, fontweight="bold")
ax.set_ylabel("Modeled incremental Q cost recovered (%)", fontsize=16,
              fontweight="bold", labelpad=12)
ax.set_title("How much of the modeled incremental Q cost\ndoes each settlement scheme recover?",
              fontsize=22, fontweight="bold", pad=18)
ax.set_ylim(0, 122)
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(axis="x", labelsize=14)
ax.tick_params(axis="y", labelsize=14)
for label in ax.get_xticklabels():
    label.set_fontweight("bold")
fig.text(0.5, 0.018, "Full-year 2021 · 8,675 solved hours · fleet aggregate",
          ha="center", fontsize=12.5, fontweight="bold", color="#555555")
plt.tight_layout(rect=[0, 0.06, 1, 1])
plt.savefig("results/figures/fig_recovery_by_scheme.png", dpi=300, bbox_inches="tight", facecolor="white")
plt.close(fig)
plt.rcParams.update(default_style)
print("saved results/figures/fig_recovery_by_scheme.png")

# ---------------------------------------------------------------------------
# Figure 2: per-generator recovery under nodal pricing (single panel)
# ---------------------------------------------------------------------------
mach = machines()
cost_model = PhysicalCost(70.0)
gens = {"G1": GEN_BUSES["G1"], "G2": GEN_BUSES["G2"], "G3": GEN_BUSES["G3"], "G4": GEN_BUSES["G4"]}
gen_recovery_nodal, gen_recovery_hybrid = [], []
n_hours = len(df)
for tag_full, bus in gens.items():
    tag = tag_full.lower()
    m = mach[bus]
    p = df[f"p_{tag}_mw"]; q = df[f"q_{tag}_mvar"]; v = df[f"v_{tag}"]; lam = df[f"lambda_q_{tag}"]
    cost_g = pd.Series([cost_model(m, pp, qq, vv) for pp, qq, vv in zip(p, q, v)])
    nodal_pay = (lam * q).sum()
    capacity_pay = PI_CAP * m.s_rated * n_hours
    gen_recovery_nodal.append(100 * nodal_pay / cost_g.sum())
    gen_recovery_hybrid.append(100 * (nodal_pay + capacity_pay) / cost_g.sum())

fig, ax = plt.subplots(figsize=(9, 5.5))
gen_labels = [f"{g}\nbus {b}, {mach[b].s_rated:.0f} MVA\n({'Type A' if g in ('G1', 'G3') else 'Type B'})"
              for g, b in gens.items()]
import numpy as np
x = np.arange(4)
w = 0.35
bars_n = ax.bar(x - w / 2, gen_recovery_nodal, width=w, color=COL_SCHEME, label="Nodal alone")
bars_h = ax.bar(x + w / 2, gen_recovery_hybrid, width=w, color="#6a3d9a", label="Hybrid (capacity + nodal)")
ax.axhline(100, color="#555555", lw=1.2, ls="--", alpha=0.7)
ax.text(3.5, 103, "100% = break-even", fontsize=8.5, color="#555555", ha="right")
for b, v in zip(bars_n, gen_recovery_nodal):
    ax.text(b.get_x() + b.get_width() / 2, v + 2.5, f"{v:.1f}%", ha="center", fontsize=9.5, fontweight="bold")
for b, v in zip(bars_h, gen_recovery_hybrid):
    ax.text(b.get_x() + b.get_width() / 2, v + 2.5, f"{v:.1f}%", ha="center", fontsize=9.5, fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(gen_labels, fontsize=9)
ax.set_ylabel("% of own reactive-service cost recovered", fontsize=10)
ax.set_title("The capacity floor helps the chronically underpaid units --\nbut G2 still falls well short of break-even",
              fontsize=12.5, pad=12)
ax.set_ylim(0, 140)
ax.legend(fontsize=9, frameon=False, loc="upper left")
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.5, -0.01, "Full year 2021, 8,675 real hours, nodal vs. hybrid (capacity+nodal) settlement",
          ha="center", fontsize=8, color="#666666")
plt.tight_layout()
plt.savefig("results/figures/fig_recovery_per_generator.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print("saved results/figures/fig_recovery_per_generator.png")

# ---------------------------------------------------------------------------
# Figure 3 (slide 3): dispatch by machine -- who actually provides the
# reactive service, and why -- no price axis, that's slide 4's question.
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5.5))
gen_q = [df[f"q_{g.lower()}_mvar"].abs().mean() for g in gens]
gen_srated = [mach[b].s_rated for b in gens.values()]
gen_util = [100 * q / s for q, s in zip(gen_q, gen_srated)]
bar_colors2 = [COL_TYPE_A if g in ("G1", "G3") else COL_TYPE_B for g in gens]
bars3 = ax.bar(gen_labels, gen_q, color=bar_colors2, width=0.55)
for b, v, u in zip(bars3, gen_q, gen_util):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.03, f"{v:.2f} MVAr\n({u:.1f}% of rating)",
            ha="center", fontsize=9.5)
ax.set_ylabel("Mean |Q| delivered (MVAr)", fontsize=10)
ax.set_title("Reactive duty concentrates on the cheaper (Type A)\nmachines -- G1 and G3 do nearly all of it",
              fontsize=12.5, pad=12)
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(axis="x", labelsize=9)
from matplotlib.patches import Patch
ax.set_ylim(0, 1.55)
ax.legend(handles=[Patch(color=COL_TYPE_A, label="Type A -- real, cited (Karekezi et al. 2023)"),
                    Patch(color=COL_TYPE_B, label="Type B -- illustrative variation")],
          fontsize=8.5, frameon=False, loc="upper left")
fig.text(0.5, -0.01, "Full year 2021, 8,675 real hours, coordinated (physical-cost) dispatch",
          ha="center", fontsize=8, color="#666666")
plt.tight_layout()
plt.savefig("results/figures/fig_dispatch_by_machine.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print("saved results/figures/fig_dispatch_by_machine.png")
