"""Custom CIGRE MV one-line diagram (schematic, not geographic) -- built from
the actual pandapower network topology (buses/lines/switches read directly,
see the coordinates below), not from a template. Highlights the four
generator buses (real study placement, bus 3/10/13/14), the two normally-
open tie switches, and the two feeder-head transformers.

    python scripts/make_network_diagram.py   (run from repo root)
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

GEN_BUSES = {3: "G1\n8 MVA (A)", 10: "G2\n5 MVA (B)", 13: "G3\n6 MVA (A)", 14: "G4\n3 MVA (B)"}

# Schematic (topologically accurate, not geographic) positions, x=horizontal, y=vertical
pos = {
    0: (4.0, 6.6),   # 110 kV slack / ext grid
    1: (2.0, 5.2),   # feeder 1 head
    2: (1.0, 4.2),
    3: (2.0, 4.2),
    4: (3.2, 5.0),
    5: (4.2, 5.0),
    6: (5.2, 5.0),
    7: (5.2, 3.6),
    8: (3.2, 3.6),
    9: (3.0, 2.6),
    10: (2.6, 1.7),
    11: (2.1, 2.6),
    12: (6.5, 5.2),  # feeder 2 head
    13: (7.5, 4.2),
    14: (8.5, 3.2),
}

# closed (always-connected) lines
closed_lines = [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (7, 8), (8, 9), (9, 10),
                 (10, 11), (3, 8), (12, 13), (13, 14)]
# normally-open tie switches (real CIGRE MV reconfiguration ties)
open_lines = [(6, 7), (11, 4), (14, 8)]
trafos = [(0, 1), (0, 12)]

fig, ax = plt.subplots(figsize=(11, 7.5))

# transformers
for a, b in trafos:
    x1, y1 = pos[a]; x2, y2 = pos[b]
    ax.plot([x1, x2], [y1, y2], color="#555555", lw=1.6, zorder=1)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    circ = plt.Circle((mx, my - 0.15), 0.14, fill=False, color="#555555", lw=1.6, zorder=2)
    circ2 = plt.Circle((mx, my + 0.15), 0.14, fill=False, color="#555555", lw=1.6, zorder=2)
    ax.add_patch(circ); ax.add_patch(circ2)

# closed lines
for a, b in closed_lines:
    x1, y1 = pos[a]; x2, y2 = pos[b]
    ax.plot([x1, x2], [y1, y2], color="#8a8a8a", lw=1.4, zorder=1)

# open tie lines (dashed, with an open-switch mark)
for a, b in open_lines:
    x1, y1 = pos[a]; x2, y2 = pos[b]
    ax.plot([x1, x2], [y1, y2], color="#c9c9c9", lw=1.2, ls=(0, (4, 3)), zorder=1)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    ax.plot(mx, my, marker="x", color="#b03a2e", markersize=7, mew=1.8, zorder=3)

# ext grid (slack)
x0, y0 = pos[0]
ax.add_patch(mpatches.Rectangle((x0 - 0.35, y0 - 0.12), 0.7, 0.24, facecolor="#2c3e50", zorder=3))
ax.text(x0, y0 + 0.32, "110 kV\nupstream grid", ha="center", va="bottom", fontsize=9, color="#2c3e50")

# buses
for b, (x, y) in pos.items():
    if b == 0:
        continue
    is_gen = b in GEN_BUSES
    color = "#c0392b" if is_gen else "#2e86ab"
    ax.plot(x, y, marker="s", markersize=9 if is_gen else 6, color=color, zorder=4,
            markeredgecolor="white", markeredgewidth=0.6)
    label_y_off = -0.32 if b not in (4, 11) else 0.30
    ax.text(x, y + 0.22, f"Bus {b}", ha="center", va="bottom", fontsize=7.5, color="#333333")

# generator markers
for b, label in GEN_BUSES.items():
    x, y = pos[b]
    ax.text(x, y - 0.30, label, ha="center", va="top", fontsize=8.5, color="#c0392b", fontweight="bold")

ax.text(pos[1][0], pos[1][1] + 0.55, "Feeder 1", ha="center", fontsize=10.5, color="#333333", fontweight="bold")
ax.text(pos[12][0], pos[12][1] + 0.55, "Feeder 2", ha="center", fontsize=10.5, color="#333333", fontweight="bold")

legend_elems = [
    Line2D([0], [0], marker="s", color="w", markerfacecolor="#2e86ab", markersize=9, label="Load bus"),
    Line2D([0], [0], marker="s", color="w", markerfacecolor="#c0392b", markersize=11, label="Generator bus (this study)"),
    Line2D([0], [0], color="#8a8a8a", lw=1.4, label="Line (closed)"),
    Line2D([0], [0], color="#c9c9c9", lw=1.2, ls=(0, (4, 3)), label="Tie line (normally open)"),
    Line2D([0], [0], marker="x", color="#b03a2e", lw=0, markeredgewidth=1.8, markersize=7, label="Open switch"),
]
ax.legend(handles=legend_elems, loc="lower left", fontsize=8.5, frameon=False)

ax.set_title("CIGRE MV benchmark network -- 15 buses, radial after 3 normally-open ties\n"
              "Generator placement used throughout this study: bus 3 / 10 / 13 / 14",
              fontsize=12, pad=14)
ax.set_xlim(-0.2, 9.5)
ax.set_ylim(1.2, 7.2)
ax.axis("off")
plt.tight_layout()
plt.savefig("results/figures/network_diagram.png", dpi=200, bbox_inches="tight")
print("saved results/figures/network_diagram.png")
