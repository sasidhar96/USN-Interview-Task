# Reactive-power incentives for dispatchable hydro

This repository contains the reproducible AC optimal-power-flow study used for
the USN / CoordQ interview task. It evaluates how alternative settlement rules
compensate four dispatchable hydrogenerators for local reactive-power support in
a Norwegian medium-voltage setting.

The repository is intentionally limited to the final study. Superseded pilot
runs, placement and withholding experiments, the abandoned game-theory
prototype, presentation build files, and duplicate analysis notes are excluded.

## Study boundary

- **Network:** CIGRE 15-bus MV benchmark, loaded through pandapower.
- **Demand:** hourly 2021 active and reactive profiles from the CINELDI
  50-bus rural Norwegian reference grid. The measured temporal shapes are
  mapped to the CIGRE load buses; CIGRE's published MV demand magnitudes and
  network parameters are retained.
- **Resources:** four synchronous hydrogenerators at buses 3, 10, 13 and 14.
- **Dispatch:** smooth, non-convex AC-OPF formulated in Pyomo and solved with
  IPOPT.
- **Reactive cost benchmark:** incremental stator and field loss relative to
  each machine's feasible minimum-loss reactive operating point.
- **Settlement:** capacity, nodal utilisation, uniform utilisation, two- and
  three-zone AWU, performance-capacity and hybrid comparisons, applied post
  hoc to the coordinated dispatch.

The detailed equations, parameter provenance, assumptions and limitations are
in [`CASE_STUDY_AND_METHODOLOGY.md`](CASE_STUDY_AND_METHODOLOGY.md). A compact
inventory of the final findings is in [`KEY_FINDINGS.md`](KEY_FINDINGS.md).

## Repository contents

```text
data/raw/cineldi_lv/.../50_bus_rural_reference_grid/
    Source P/Q profiles and network metadata used by the study
src/
    Network data, machine physics, cost models, AC-OPF and settlements
src/study.py
    Canonical fleet definition, prices and production solver settings
run_monthly_analysis.py
    Parallel hourly AC-OPF runner used by the full-year study
run_fullyear_pricing.py
    Reproduces the authoritative full-year settlement dataset
scripts/
    Reproduces the retained network and result figures
tests/test_machine.py
    Machine, capability, loss-minimum and settlement validation
results/pricing_mechanisms_fullyear.csv
    Authoritative 2021 result: 8,675 solved real hours
results/figures/
    Final figures generated from the authoritative result
```

## Installation

Python 3.11 or newer is recommended. IPOPT must also be available on the
system path.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Validation

```bash
pytest -q
```

## Reproduce the final study

The full-year solve is computationally expensive and checkpoints its output.

```bash
python run_fullyear_pricing.py
python scripts/make_network_diagram.py
python scripts/make_slide_figures.py
python scripts/make_p_vs_q_figure.py
python scripts/make_system_cost_figure.py
```

The figure scripts read `results/pricing_mechanisms_fullyear.csv`; rerunning the
AC-OPF is not required merely to recreate the plots.

## Interpretation limit

The settlement comparison is a post-hoc revenue-adequacy study, not a bid-based
market equilibrium. “Recovery” means annual generator payment divided by the
modeled incremental machine-loss cost of reactive provision. It does not include
fixed availability, wear, telemetry, compliance, risk or strategic behaviour,
and fleet-average recovery does not prove fair recovery for every owner.

## Primary references

- CIGRE Technical Brochure 575 (2014), *Benchmark Systems for Network
  Integration of Renewable and Distributed Energy Resources*.
- Engan et al. (2025), *Reference dataset for semi-urban and rural Norwegian
  low voltage distribution grids*, Data in Brief 59, 111453.
  DOI: 10.1016/j.dib.2025.111453.
- Karekezi, Melfald, Oyvang & Noland (2023), *Loss Modeling of Large
  Hydrogenerators for Cost Estimation of Reactive Power Services and
  Identification of Optimal Operation*, IEEE Transactions on Energy
  Conversion 38(2), 1350-1360. DOI: 10.1109/TEC.2022.3230763.
