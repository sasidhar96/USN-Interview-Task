"""Full-year production study for the bus 3/10/13/14 hydro fleet.

    python run_study.py
"""
from __future__ import annotations

from pathlib import Path

from src.study import ENERGY_PRICE, machines as _prod_machines
from src.hourly_runner import run_all_configs_parallel

RESULTS = Path(__file__).parent / "results"


def main():
    RESULTS.mkdir(exist_ok=True)
    configs = {"4gen_current": _prod_machines()}
    df, skipped = run_all_configs_parallel(
        months=set(range(1, 13)), p_cost_gen=ENERGY_PRICE, n_workers=12,
        configs=configs,
        checkpoint_path=str(RESULTS / "pricing_mechanisms_fullyear.csv"),
        checkpoint_every=500,
    )
    df.to_csv(RESULTS / "pricing_mechanisms_fullyear.csv", index=False)
    skipped_path = RESULTS / "pricing_mechanisms_fullyear_skipped.txt"
    if skipped:
        skipped_path.write_text("\n".join(skipped))
    elif skipped_path.exists():
        skipped_path.unlink()
    print(f"DONE: {len(df)} solved, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
