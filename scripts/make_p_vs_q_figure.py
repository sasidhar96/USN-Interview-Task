"""Active vs reactive power pricing: TWO standalone single-panel PNGs (not one
grouped figure), matching the treatment given to the other slide-4 figures.

  fig_price_variability_p_vs_q.png    -- how much the locational price itself
      varies across generator buses, P vs Q.
  fig_pricing_basis_sensitivity.png   -- the resulting swing in what
      generators actually get paid when you change the pricing basis
      (nodal/uniform/AWU), P vs Q.

Source: results/pricing_mechanisms_fullyear.csv (8,675 real hours, 2021),
lambda_p_gX / lambda_q_gX columns (both duals from the same single OPF
solve, no separate active-power settlement layer needed).

    python scripts/make_p_vs_q_figure.py   (run from repo root)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.case_data import GEN_BUSES
from src.settlement import FEEDER_ZONES

df = pd.read_csv("results/pricing_mechanisms_fullyear.csv", low_memory=False)
gens = {"g1": GEN_BUSES["G1"], "g2": GEN_BUSES["G2"], "g3": GEN_BUSES["G3"], "g4": GEN_BUSES["G4"]}

COL_P = "#e08214"
COL_Q = "#2e86ab"

# --- locational price variability (CV across the 4 generator buses) --------
p_vals = np.array([df[f"lambda_p_{t}"] for t in gens])
q_vals = np.array([df[f"lambda_q_{t}"] for t in gens])
p_cv = np.nanmean(p_vals.std(axis=0) / np.abs(p_vals.mean(axis=0)))
q_cv = np.nanmean(q_vals.std(axis=0) / np.abs(q_vals.mean(axis=0)))

# --- revenue/recovery sensitivity to pricing basis --------------------------
lam_p = {t: df[f"lambda_p_{t}"] for t in gens}
p_g = {t: df[f"p_{t}_mw"] for t in gens}
uniform_p_price = sum(lam_p.values()) / 4
zone_of = {t: FEEDER_ZONES[b] for t, b in gens.items()}
zone_avg = {z: sum(lam_p[t] for t in gens if zone_of[t] == z) / sum(1 for t in gens if zone_of[t] == z)
            for z in set(zone_of.values())}
awu_p_price = {t: zone_avg[zone_of[t]] for t in gens}
nodal_p_rev = sum((lam_p[t] * p_g[t]).sum() for t in gens)
uniform_p_rev = sum((uniform_p_price * p_g[t]).sum() for t in gens)
awu_p_rev = sum((awu_p_price[t] * p_g[t]).sum() for t in gens)

service_cost_total = (df["1_capacity_total_payment_eur_h"] - df["1_capacity_total_profit_eur_h"]
                       + df["1_capacity_total_revenue_p_eur_h"]).sum() - df["1_capacity_total_revenue_p_eur_h"].sum()
q_recovery = {}
for s, label in [("2a_variable_nodal", "Nodal"), ("2b_variable_uniform", "Uniform"), ("2c_variable_awu", "AWU")]:
    q_recovery[label] = 100 * df[f"{s}_total_payment_eur_h"].sum() / service_cost_total

p_pct_of_nodal = {"Nodal": 100.0,
                   "Uniform": 100 * uniform_p_rev / nodal_p_rev,
                   "AWU": 100 * awu_p_rev / nodal_p_rev}

CAPTION = "Full year 2021, 8,675 real hours; same OPF solve produces both lambda-P and lambda-Q duals"

# ---------------------------------------------------------------------------
# Figure 1: locational price variability, P vs Q (standalone)
# ---------------------------------------------------------------------------
fig, ax1 = plt.subplots(figsize=(8, 6))
bars = ax1.bar(["Active power\n(lambda-P)", "Reactive power\n(lambda-Q)"], [p_cv * 100, q_cv * 100],
                color=[COL_P, COL_Q], width=0.5)
ax1.set_yscale("log")
for b, v in zip(bars, [p_cv * 100, q_cv * 100]):
    ax1.text(b.get_x() + b.get_width() / 2, v * 1.15, f"{v:.2f}%", ha="center", fontsize=14, fontweight="bold")
ax1.set_ylabel("Locational price variability\n(coefficient of variation across generator buses, %)", fontsize=10.5)
ax1.set_title("Reactive power's price varies ~50x more\nacross the network than active power's",
               fontsize=13.5, pad=14)
ax1.spines[["top", "right"]].set_visible(False)
ax1.tick_params(axis="x", labelsize=11)
fig.text(0.5, -0.01, CAPTION, ha="center", fontsize=8.5, color="#666666")
plt.tight_layout()
plt.savefig("results/figures/fig_price_variability_p_vs_q.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print("saved results/figures/fig_price_variability_p_vs_q.png")

# ---------------------------------------------------------------------------
# Figure 2: what generators are actually paid, by pricing basis, P vs Q (standalone)
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
fig, ax2 = plt.subplots(figsize=(10.5, 6.8))
x = np.arange(3)
w = 0.35
bars_p = ax2.bar(x - w / 2, [p_pct_of_nodal[k] for k in ["Nodal", "Uniform", "AWU"]], width=w,
                  color=COL_P, label="Active power (P)")
bars_q = ax2.bar(x + w / 2, [q_recovery[k] for k in ["Nodal", "Uniform", "AWU"]], width=w,
                  color=COL_Q, label="Reactive power (Q)")
for b in bars_p:
    ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 2.2, f"{b.get_height():.1f}%",
             ha="center", fontsize=17, fontweight="bold")
for b in bars_q:
    ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 2.2, f"{b.get_height():.1f}%",
             ha="center", fontsize=17, fontweight="bold")
ax2.set_xticks(x)
ax2.set_xticklabels(["Nodal", "Uniform", "AWU (zonal)"], fontsize=16, fontweight="bold")
ax2.set_ylabel("Relative revenue / cost recovery (%)", fontsize=16, fontweight="bold", labelpad=12)
ax2.set_title("Pricing basis barely changes P revenue—\nbut shifts Q cost recovery by ~30 points",
               fontsize=22, fontweight="bold", pad=18)
ax2.set_ylim(0, 128)
ax2.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.95), ncol=2,
           columnspacing=2.0, prop={"weight": "bold", "size": 15})
ax2.spines[["top", "right"]].set_visible(False)
ax2.tick_params(axis="y", labelsize=14)
for label in ax2.get_yticklabels():
    label.set_fontweight("bold")
fig.text(0.5, 0.018, "Full-year 2021 · 8,675 solved hours · same AC-OPF dispatch",
         ha="center", fontsize=12.5, fontweight="bold", color="#555555")
plt.tight_layout(rect=[0, 0.06, 1, 1])
plt.savefig("results/figures/fig_pricing_basis_sensitivity.png", dpi=300, bbox_inches="tight", facecolor="white")
plt.close(fig)
plt.rcParams.update(default_style)
print("saved results/figures/fig_pricing_basis_sensitivity.png")

print()
print(f"lambda_P CV: {p_cv*100:.3f}%   lambda_Q CV: {q_cv*100:.3f}%   ratio: {q_cv/p_cv:.1f}x")
print("P revenue relative to nodal:", {k: round(v, 3) for k, v in p_pct_of_nodal.items()})
print("Q recovery:", {k: round(v, 1) for k, v in q_recovery.items()})
