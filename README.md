# Reactive-power incentives for dispatchable hydro

Implementation of a full AC optimal-power-flow study for incentivising
reactive-power provision from dispatchable hydrogenerators in a Nordic
distribution-network context.

## What the implementation does

- loads the CIGRE 15-bus medium-voltage benchmark;
- applies measured 2021 Norwegian active and reactive demand profiles;
- models four synchronous hydrogenerators with machine-derived reactive-loss
  costs and feasible P–Q capability limits;
- solves baseline and coordinated AC-OPF dispatch with Pyomo and IPOPT;
- calculates nodal reactive prices from Q-balance duals; and
- compares capacity, nodal, uniform, zonal/AWU, performance-capacity and
  hybrid settlements over **8,675 solved hours**.

## Repository structure

```text
run_study.py              Run the complete annual study
src/                      Network, machine, AC-OPF and settlement code
data/                     Only the network and demand inputs used
results/
  pricing_mechanisms_fullyear.csv
                          Authoritative annual result
  figures/                Final plots used to communicate the findings
scripts/                  Recreate the retained figures
additional_files/
  documentation/          Detailed methodology and findings
  validation/             Tests and diagnostic result tables
  references/             Local papers; excluded from GitHub
```

## Run

Python 3.11 or newer and IPOPT are required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_study.py
```

The annual solve is computationally expensive. Existing figures can be
recreated directly from the retained annual CSV:

```bash
python scripts/make_network_diagram.py
python scripts/make_slide_figures.py
python scripts/make_p_vs_q_figure.py
python scripts/make_system_cost_figure.py
```

## Validate

```bash
pytest -q
```

The validation suite covers the machine-loss minimum, capability limits,
power-flow residuals, settlement accounting, thermal limits and cost-model
switching. Additional diagnostic outputs are retained under
`additional_files/validation/results/`.

## Main outputs

- `results/pricing_mechanisms_fullyear.csv` — 8,675 unique solved hours,
  all 12 months and every settlement outcome.
- `results/figures/network_diagram.png` — study network and hydro placement.
- `results/figures/fig_system_cost.png` — baseline versus coordinated cost
  and upstream reactive import.
- `results/figures/fig_recovery_by_scheme.png` — settlement payment relative
  to modeled incremental machine-loss cost.
- `results/figures/fig_recovery_per_generator.png` — owner-level recovery.
- `results/figures/fig_price_variability_p_vs_q.png` and
  `fig_pricing_basis_sensitivity.png` — locational pricing evidence.

## Interpretation boundary

This is a centralized AC-OPF followed by post-hoc settlement, not a bidding
market equilibrium. “Cost recovery” means payment divided by modeled
incremental machine-loss cost. It does not include fixed availability, wear,
telemetry, compliance, risk or strategic behaviour.

For equations, parameter provenance, assumptions and limitations, see
[`additional_files/documentation/CASE_STUDY_AND_METHODOLOGY.md`](additional_files/documentation/CASE_STUDY_AND_METHODOLOGY.md).
The final result inventory is in
[`additional_files/documentation/KEY_FINDINGS.md`](additional_files/documentation/KEY_FINDINGS.md).
