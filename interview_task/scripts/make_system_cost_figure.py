"""System-cost figure: full-year (8,675 real hours) total system cost,
baseline vs coordinated, and the mechanism (upstream reactive import).
Source: results/pricing_mechanisms_fullyear.csv, `.objective`/`.slack_q`
columns captured directly from the OPF's own true objective value (not
reconstructed/approximated).

    python scripts/make_system_cost_figure.py   (run from repo root)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import matplotlib.pyplot as plt
import pandas as pd

df = pd.read_csv("results/pricing_mechanisms_fullyear.csv", low_memory=False)

COL_BASE = "#9a9a9a"
COL_COORD = "#2e86ab"
COL_GOOD = "#2e8b57"

base_total = df["0_baseline_objective_eur_h"].sum()
coord_total = df["coordinated_objective_eur_h"].sum()
savings = base_total - coord_total
savings_pct = 100 * savings / base_total

base_q = df["0_baseline_slack_q_mvar"].mean()
coord_q = df["coordinated_slack_q_mvar"].mean()

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5.5))

# Panel 1: total annual system cost
bars = ax1.bar(["Baseline\n(today, no incentive)", "Coordinated\n(physical-cost dispatch)"],
                [base_total / 1000, coord_total / 1000], color=[COL_BASE, COL_COORD], width=0.55)
for b, v in zip(bars, [base_total / 1000, coord_total / 1000]):
    ax1.text(b.get_x() + b.get_width() / 2, v + 15, f"{v:,.0f}k EUR", ha="center", fontsize=11, fontweight="bold")
ax1.annotate(f"-{savings:,.0f} EUR\n(-{savings_pct:.2f}%)", xy=(1, coord_total / 1000), xytext=(0.5, coord_total / 1000 - 700),
             fontsize=10.5, color=COL_GOOD, fontweight="bold", ha="center",
             arrowprops=dict(arrowstyle="->", color=COL_GOOD, lw=1.4))
ax1.set_ylabel("Total system cost, full year 2021\n(thousand EUR)", fontsize=10)
ax1.set_title("A. Coordinating reactive power lowers\ntotal system cost", fontsize=12, pad=10)
ax1.spines[["top", "right"]].set_visible(False)

# Panel 2: mechanism -- upstream reactive import
bars2 = ax2.bar(["Baseline", "Coordinated"], [base_q, coord_q], color=[COL_BASE, COL_COORD], width=0.55)
for b, v in zip(bars2, [base_q, coord_q]):
    ax2.text(b.get_x() + b.get_width() / 2, v + 0.08, f"{v:.2f} MVAr", ha="center", fontsize=11, fontweight="bold")
ax2.set_ylabel("Mean reactive power imported\nfrom the upstream interface (MVAr)", fontsize=10)
ax2.set_title("B. Mechanism: coordination cuts expensive\nupstream reactive import by 65%", fontsize=12, pad=10)
ax2.spines[["top", "right"]].set_visible(False)

fig.text(0.5, -0.02, "Full year 2021, 8,675 real hours solved (99.0% coverage), production placement (bus 3/10/13/14)",
          ha="center", fontsize=8.5, color="#666666")
plt.tight_layout()
plt.savefig("results/figures/fig_system_cost.png", dpi=200, bbox_inches="tight")
plt.close(fig)

print(f"Baseline total system cost:    {base_total:>14,.2f} EUR")
print(f"Coordinated total system cost: {coord_total:>14,.2f} EUR")
print(f"Savings:                       {savings:>14,.2f} EUR  ({savings_pct:.4f}%)")
print(f"Mean upstream Q import: baseline {base_q:.3f} MVAr -> coordinated {coord_q:.3f} MVAr")
print("saved results/figures/fig_system_cost.png")
