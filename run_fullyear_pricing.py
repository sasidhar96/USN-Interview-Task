"""Full-year (12 months), single production-config (bus 3/10/13/14) pricing-
scheme comparison, all 8 settlement schemes, with the Q_ref fix baked into
the dispatch itself (not a post-hoc approximation like the earlier
full_year_hourly.csv). Supersedes that file for any scheme-recovery number.

    python _fullyear_pricing_run.py
"""
from __future__ import annotations

from pathlib import Path

from run_experiments import machines as _prod_machines
from run_monthly_analysis import run_all_configs_parallel

RESULTS = Path(__file__).parent / "results"


def main():
    RESULTS.mkdir(exist_ok=True)
    configs = {"4gen_current": _prod_machines()}
    df, skipped = run_all_configs_parallel(
        months=set(range(1, 13)), p_cost_gen=70.0, n_workers=12,
        configs=configs,
        checkpoint_path=str(RESULTS / "pricing_mechanisms_fullyear.csv"),
        checkpoint_every=500,
    )
    df.to_csv(RESULTS / "pricing_mechanisms_fullyear.csv", index=False)
    (RESULTS / "pricing_mechanisms_fullyear_skipped.txt").write_text("\n".join(skipped))
    print(f"DONE: {len(df)} solved, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
