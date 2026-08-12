"""Generator placement experiment: hold fleet size and machine identity
fixed per count (2/3/4 generators), move WHERE they sit, and see how
losses/prices/recovery change.

Bus choices are grounded in real topological hop-distance from the nearest
feeder head (bus 1 or 12), not guessed:
    head buses:    1, 12                     (0 hops)
    current G1-G4: 3, 10, 13, 14              (2, 5, 3, 2 hops)
    remote buses:  6, 9, 7, 5                 (5, 4, 4, 4 hops)

Same machine (size, type) at a different bus, per count:
    2-gen: G1(8MVA,A) + G2(5MVA,B)
    3-gen: + G3(6MVA,A)
    4-gen: + G4(3MVA,B)

    python placement_experiment.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from run_experiments import machines as _prod_machines, GEN_BUSES
from run_monthly_analysis import run_all_configs_parallel, STUDY_MONTHS

RESULTS = Path(__file__).parent / "results"


def _placement_configs() -> dict[str, dict[int, "Machine"]]:
    full = _prod_machines()
    g1, g2, g3, g4 = (full[GEN_BUSES[n]] for n in ("G1", "G2", "G3", "G4"))

    return {
        # 2-generator: current vs. both-at-heads vs. both-remote
        "2gen_current_b3_b10": {3: g1, 10: g2},
        "2gen_heads_b1_b12": {1: g1, 12: g2},
        "2gen_remote_b6_b9": {6: g1, 9: g2},
        # 3-generator: current vs. remote
        "3gen_current_b3_b10_b13": {3: g1, 10: g2, 13: g3},
        "3gen_remote_b6_b9_b7": {6: g1, 9: g2, 7: g3},
        # 4-generator: current (already the main study's config) vs. remote
        "4gen_current_b3_b10_b13_b14": {3: g1, 10: g2, 13: g3, 14: g4},
        "4gen_remote_b6_b9_b7_b5": {6: g1, 9: g2, 7: g3, 5: g4},
    }


def main():
    RESULTS.mkdir(exist_ok=True)
    configs = _placement_configs()
    df, skipped = run_all_configs_parallel(
        months=STUDY_MONTHS, p_cost_gen=70.0, n_workers=6,
        configs=configs,
        checkpoint_path=str(RESULTS / "placement_experiment.csv"),
        checkpoint_every=300,
    )
    df.to_csv(RESULTS / "placement_experiment.csv", index=False)
    (RESULTS / "placement_experiment_skipped.txt").write_text("\n".join(skipped))
    print(f"DONE: {len(df)} solved, {len(skipped)} skipped")

    print("\n=== summary: mean coordinated network loss (MW) and max line loading (%) per placement ===")
    g = df.groupby("config").agg(
        mean_loss_mw=("coordinated_loss_mw", "mean"),
        mean_max_line_loading_pct=("coordinated_max_line_loading_pct", "mean"),
        mean_nodal_payment=("2a_variable_nodal_total_payment_eur_h", "mean"),
    )
    print(g)


if __name__ == "__main__":
    main()
