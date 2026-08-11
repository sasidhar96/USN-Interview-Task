# Five-bus reactive-power market case

## Purpose

Demonstrate how two dispatchable small-hydro generators can be compensated for
local reactive-power support in a Norwegian rural distribution network. The
case is a mechanism demonstration, not a calibrated model of a particular DSO.

## Data provenance

- Network and hourly load source: Engan et al. (2025), Zenodo record 14528192.
- Selected source grid: `50_bus_rural_reference_grid`, 230 V, radial, NO2.
- Source data retained under `data/raw/cineldi_lv` without modification.
- The five-bus equivalent preserves all 21 hourly P and Q load series by
  aggregating them into four load zones.
- Equivalent branch impedances are load-weighted reductions of original
  per-unit paths. They are approximations and must be checked against the full
  50-bus power flow at representative hours.
- Hydro electrical parameters and loss functions: SynGenLib. Ratings are
  scaled for this feeder and are illustrative rather than manufacturer data.

## Five-bus topology

```text
                    upstream grid (bus 0)
                       /             \
              hydro G1/bus 1    hydro G2/bus 3
                    |                  |
                load bus 2         load bus 4
```

Loads also exist at buses 1 and 3. G1 is rated 80 kVA and G2 60 kVA. The
combined 140 kVA rating is compared with a measured coincident peak of about
114.6 kVA. The upstream grid remains present so all scenarios are feasible and
can import or export P and Q.

## Why pandapower and Pyomo are both needed

Pandapower stores buses, impedances, loads and generators and solves AC power
flow. Its built-in AC-OPF can be used as a baseline with simple polynomial P/Q
costs. It does not directly express the full SynGenLib coupled loss function,
curved P-Q-V capability limits, availability products and settlement rules.

The final market clearing is therefore a custom nonlinear AC-OPF in Pyomo,
solved with IPOPT. Every clearing result is replayed in pandapower as an
independent network feasibility check.

## Market-clearing formulation

Decision variables are generator active/reactive output `(P_g, Q_g)`, voltage
magnitude `V_i`, and voltage angle `theta_i`. The objective minimizes:

```text
upstream energy cost
+ hydro water/opportunity cost
+ incremental hydro machine-loss cost
+ optional reactive-capacity reservation cost
+ high penalty for involuntary load shedding
```

Constraints include AC active and reactive nodal balance, bus-voltage limits,
branch limits, generator active limits, and SynGenLib stator, rotor,
underexcitation and terminal-voltage limits.

The local marginal reactive price is the dual multiplier of each bus's
reactive-power balance. A positive price means one additional MVAr of local
demand increases minimized system cost.

## Scenarios

1. **No incentive / local Q disabled:** `Q_G1 = Q_G2 = 0`; the upstream grid
   supplies reactive demand. This quantifies unused hydro flexibility.
2. **Coordinated technical dispatch:** local Q is optimized to minimize total
   physical losses. No market settlement is applied.
3. **Market clearing:** generators submit loss- and opportunity-cost-based
   offers; AC-OPF clears Q and produces nodal prices.
4. **Stress sensitivity:** repeat scenario 3 at the minimum, median, peak-P,
   peak-Q and peak-apparent-power hours, then vary load and generator
   availability.

## Settlement and participation

For each generator and hour, report:

```text
activation payment = nodal Q price * cleared Q
capacity payment   = reserved Q capacity * capacity price (optional)
service cost       = incremental machine loss + opportunity cost
service profit     = activation + capacity payment - service cost
```

For the network operator, report avoided upstream reactive import, avoided
active losses, voltage improvement, procurement payment and net system benefit.
The base implementation should clear activation first; capacity reservation is
an extension if time permits.

## Validation gates

- Sum of reduced hourly loads must equal the full dataset at every hour.
- Five-bus voltages and losses must be compared with the full 50-bus case; the
  reduction is accepted only if its qualitative stress ranking is preserved.
- SynGenLib scaled-machine loss and capability curves must be plotted and
  checked before embedding them in Pyomo.
- Pyomo power-balance residual must be below `1e-6` per unit.
- Replaying optimized injections in pandapower must converge and reproduce bus
  voltages within a documented tolerance.
- Reactive dual units must be hand-checked before reporting EUR/MVArh.

## Deliberate scope choices

- No transformer is required in the first five-bus demonstration because all
  buses and small generators are represented on one 230 V equivalent. This is
  an explicit simplification.
- A generator transformer and the CINELDI MV reference grid are the preferred
  extension for a more realistic plant connection.
- The first model is single-period. Reservoir dynamics and unit commitment are
  outside the core reactive-pricing mechanism; water value enters as an active
  opportunity-cost coefficient.
- A full exchange or auction engine is unnecessary. Market clearing, nodal
  prices, payments, service costs and profits are sufficient to demonstrate
  incentive compatibility.

## Implementation order

1. Validate the five-bus pandapower model at representative hours.
2. Reconstruct scaled SynGenLib machine curves for G1 and G2.
3. Implement the Pyomo AC-OPF with no-incentive and coordinated cases.
4. Add physical reactive offers, dual extraction and settlement accounting.
5. Compare reduced and full-network results and run sensitivities.
6. Produce the presentation figures and five-slide narrative.
