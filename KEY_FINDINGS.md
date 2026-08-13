# Key Findings — Complete Inventory

Every distinct, concrete finding produced by this project, grouped by theme. Each line is a
standalone claim you can drop onto a slide or into discussion; source section in
`CASE_STUDY_AND_METHODOLOGY.md` given where applicable.

---

## A. Machine physics

1. **Type A machine parameters (G1, G3) are real and cited**; Type B (G2, G4) are
   illustrative variations on the same cited base values, not independently sourced —
   stated distinction, not hidden. (§2.1)
2. **The loss-minimizing reactive power point is not zero** — it's slightly negative
   (underexcited), $Q^\star \approx -0.191$ pu for G1, matching the source paper's own
   reported range. (§2.3)
3. **Found and fixed a real infeasibility bug**: bare $Q^\star$ is infeasible (below the
   underexcitation floor) at every one of the fleet's four machines' own minimum active
   power — affected cost *levels* fleet-wide since 3 of 4 generators sit at their floor most
   hours. Fixed via a smooth $Q_{ref}=\max(\text{floor},Q^\star)$. (§2.3)
4. **Found and fixed a cited-parameter error**: an earlier version used the source paper's
   bare Table II armature resistance (0.002 pu) instead of its Table I combined
   armature+stray-load figure (0.0026862 pu) — understated cost and pushed $Q^\star$ outside
   the paper's own reported range. (§2.1)
5. **syngenlib cross-check**: this project's loss/EMF equations verified term-for-term
   identical to syngenlib's own archived Pyomo-native model, read directly from source.
   (§2.2)
6. **Found a likely bug in syngenlib's own archived code** (unsquared $P$ term in its field-
   limit constraint, dimensionally inconsistent) and deliberately did not carry it over —
   verification that caught an error in the reference implementation itself. (§2.2)
7. **The field (rotor-current) limit never binds** — 0.00%, all 4 generators, all 8,675 real
   hours, the entire year. This fleet's installed capacity exceeds what real demand ever
   asks of it. (§6.4)
8. **The stator (armature) limit also never binds** — 0.00%, all year. (§6.4)
9. **The underexcitation limit is the one genuinely live constraint** — binds for G4 21.58%
   of the year (small, higher-$X_d$ machine); essentially never for the others. (§6.4)
10. **Loss-of-opportunity-cost (the active-power-for-reactive-power tradeoff) is implemented
    correctly but is exactly zero throughout the real data**, because the field limit that
    would trigger it never binds. The mechanism exists in the model; nothing in this fleet's
    real operating conditions ever activates it. (§6.4)

## B. Network and demand data

11. **CIGRE MV topology verified directly from the loaded network object** (not redrawn from
    a template) — 15 buses, two independently-transformed feeders, three real normally-open
    reconfiguration ties. (§1.1)
12. **Found and fixed a demand-normalization bug**: independently normalizing active and
    reactive demand by each series' own peak introduced a physically meaningless constant
    bias in every hour's real tan(φ). Fixed via mean-rescaling plus 99th-percentile
    winsorization. (§1.2)
13. **Two real CINELDI households (feeding CIGRE buses 4 and 6) have degenerate reactive-
    power meters** — near-zero for most of the year, with rare, likely-noisy spikes — a
    genuine source-data limitation, not a code bug. (§1.2)
14. **CIGRE MV's own nominal load is extremely skewed** — buses 1 and 12 alone are 89% of
    total nominal demand — which drove the bus-to-household group-size reasoning (not an
    equal split). (§1.2)

## C. Optimization / solver

15. **Total system cost is mathematically identical across every settlement scheme** —
    proven numerically to $5.7\times10^{-14}$ EUR precision, not just architecturally
    argued. Settlement is a pure payment-redistribution layer; it cannot and does not touch
    dispatch. (§4.1)
16. **The water-value convention ($c_g^P=\lambda_E$) causes real IPOPT ill-conditioning** —
    the linear P-direction gradient term vanishes exactly at this value, diagnosed as a
    scaling problem (not centrality) via targeted option sweeps, fixed with a one-shot
    fallback retry (`nlp_scaling_method=none`) that never regresses an easy hour. (§3.4)
17. **AC-OPF is non-convex; IPOPT provides no global-optimality guarantee** — stated
    plainly, then addressed two independent ways: 5-start multi-start across 12 real hours
    (relative spread ≤$2.5\times10^{-12}$) and an algorithmically unrelated
    differential-evolution cross-check (agrees to 0.00075%). Neither is a proof; together
    they're real evidence against the one failure mode that would undermine every other
    number in the study. (§5.2, §5.3)
18. **Unit conversion (per-unit ↔ EUR/MVArh) independently verified** by re-basing the whole
    problem to 100 MVA — bit-identical prices to 5 decimal places. (§3.2)
19. **Found and fixed a unit bug in the interface thermal-limit constraint** — comparing a
    per-unit quantity against an MVA-documented value, silently correct only because
    $s_{base}=1$; would have silently broken the limit at any other base.
20. **Found and fixed a ~1,400× settlement-rate bug** — one of two call sites for the real
    Statnett capacity rate used the wrong number, which had been flipping which settlement
    scheme looked dominant before it was caught.

## D. Settlement schemes and pricing

21. **Nodal pricing is genuinely locational, not a relabeled flat rate** — verified directly
    on real data that per-bus prices differ meaningfully hour to hour. (§3.2)
22. **The real Statnett capacity mechanism recovers only 11.4%** of this fleet's actual
    modeled incremental machine-loss cost — an order-of-magnitude illustration of the compensation
    gap this project studies. (§6.2)
23. **Nodal pricing gets closest to full aggregate service-cost recovery** — 95.7%, because
    it's the only tested scheme that pays each generator at its own location's true
    marginal value. (§6.2)
24. **Finer zoning captures real locational value a coarser split throws away**: AWU 3-zone
    (72.4%) beats AWU 2-zone (65.6%) — driven by separating two generators (G1, G2) whose
    real prices differ ~24% but which the 2-zone split blends into one number. (§6.2)
25. **Hybrid is exactly capacity+nodal** — proven to $4.4\times10^{-16}$ precision, not a
    third independent mechanism. (§4.2)
26. **The hybrid capacity floor materially helps the chronically underpaid units** — G2
    30.9% (up from 0.3% nodal-alone), G4 57.4% (up from 27.3%) — but **does not fully fix
    the problem**: G2 still falls well short of break-even even with the floor. (§6.3,
    `fig_recovery_per_generator.png`)
27. **Load-charge recovery is low everywhere** — 1–11% across every scheme tested,
    including nodal — meaning reactive-service payment cannot realistically be funded from
    billing loads their own reactive consumption alone, under any mechanism tested. (§4.3)
28. **Two genuinely different "recovery" metrics existed under one ambiguous name** in an
    earlier version of the project documentation (service-cost vs. load-charge) — found
    conflated, separated, and both now precisely defined. (§4.3)
29. **Performance-adjusted capacity is a real, counterintuitive trade-off, not a bug**: it
    fixes flat-capacity's zero-marginal-incentive flaw but, at the real administered
    Statnett rate, recovers *less* (1.2%) than plain flat capacity (11.4%) — the rate, not
    the formula, is the binding constraint.

## E. Ownership and fairness

30. **The fleet-aggregate 95.7% nodal recovery number hides a 0.3%–120.6% spread across
    individual generators** — G1 93.9%, G2 0.3%, G3 120.6%, G4 27.3%. (§6.3)
31. **This disparity is mechanistic, not random**: cheaper (Type A, lower $X_d$) machines
    are dispatched for nearly all the reactive duty (G1 0.97 MVAr, G3 1.23 MVAr) while the
    costlier Type B units are barely used (G2 0.08 MVAr, G4 0.12 MVAr) — a price-per-
    delivered-unit scheme necessarily concentrates payment where the delivery already is.
    (§6.3, `fig_dispatch_by_machine.png`)
32. **G2 fails individual rationality under nodal pricing, the best-performing scheme
    tested** — a rational, independent owner would have no economic reason to participate
    voluntarily. This is the sharp, quantified version of "is this proper incentivization."
    (§6.3, §7.1)
33. **Placement and pricing are not independent levers — they compound**: where a generator
    sits determines how much reactive duty it's dispatched for, which directly determines
    how much it gets paid under any delivery-based scheme.

## F. System cost and procurement cost

34. **Coordinating reactive power lowers total system cost over the full year** — savings of
    54,247.57 EUR, 0.60% of total system cost, computed from the OPF's own true objective
    value across all 8,675 real hours, not extrapolated from a sample. (§6.1a)
35. **In 4.15% of hours coordination was nominally more expensive — checked in detail and
    found to be noise-level** (21.82 EUR total across all 360 such hours, ~0.005% of that
    hour's own cost) — reported honestly rather than hidden, and doesn't change the
    conclusion. (§6.1a)
36. **The sharper, uncontaminated number**: reactive power *procurement cost* specifically
    (what the operator pays the upstream interface) drops 84% under coordination — from
    71,041.93 EUR/year to 11,244.93 EUR/year, a savings of 59,796.99 EUR. (§6.1a)
37. **Total reactive power physically imported from upstream drops 65%** over the year —
    36,384.0 MVArh (baseline) to 12,796.2 MVArh (coordinated), 23,587.8 MVArh avoided.
    (§6.1a)
38. **The interface reactive price is ~14.5× the local generator-bus price on average**
    (up to ~26× in winter specifically) — the quantified economic reason local coordination
    has value at all; without this gap there would be no incentive to source reactive power
    locally rather than importing it. (§3.1, §6.1a)

## G. Active vs. reactive power — the "gold mine" comparison

39. **Active power's locational price is nearly flat across the network** — coefficient of
    variation 0.53% across generator buses; **reactive power's varies ~50× more** — CV
    26.62%. (§6.1b, `fig_price_variability_p_vs_q.png`)
40. **Changing the pricing basis (nodal→uniform/zonal) barely moves active-power revenue**
    (≤0.15% swing) **but swings reactive-power recovery by ~30 percentage points** — the
    direct economic consequence of finding 39. (§6.1b, `fig_pricing_basis_sensitivity.png`)
41. **This is consistent with, but goes beyond, established theory**: the underlying
    mechanism (P-θ/Q-V decoupling, Stott & Alsac 1974) is textbook and well-known; the
    specific quantified comparison for this real network was not found replicated in any
    source checked and is original analysis for this project. (§6.1b)
42. **Indirectly validated by real Nordic market design**: Norway prices active power
    zonally (5 bidding zones), not nodally — only a reasonable simplification because
    within-zone active-power price differences are genuinely small, exactly what finding 39
    shows computationally for this network too. (§6.1b)

## H. Incentive-design boundary and the honest limits of this work

43. **Post-hoc settlement does not change dispatch** — by construction, every scheme uses
    finding 15. Every settlement scheme answers "how to pay for an already-fixed optimal
    outcome," never "does the payment scheme change behavior." (§4.1, §7.1)
44. **Individual rationality fails for at least one generator (G2) even under the best-
    performing centralized mechanism tested** — the sharp, quantified argument for why a
    real bidding/negotiated market is the necessary next step, not an optional refinement.
    (§7.1, finding 32)

## I. Literature and citation verification

45. **Potter et al.'s assumed reactive cost coefficient — the entire premise this project's
    thesis contrasts against — verified word-for-word**: $b^Q_j = 0.1\,b^P_j$, explicitly
    motivated by citing a 2014 FERC report finding reactive prices are often one-tenth of
    real power prices. Checked directly against the paper, not a summary.
46. **Statnett's real capacity (250 NOK/MVA/yr) and variable ($k=0.012/0.007$, ±40%/−20%
    threshold) settlement formulas verified word-for-word** against the primary 2024
    decision PDF.
47. **Norway's 89.9% hydro share (2025) verified directly against Statistics Norway (SSB)**,
    not asserted from memory.
48. **Karekezi et al.'s cited machine parameters verified exactly** against the paper's own
    Tables I and II — with one honest nuance surfaced: the paper's *later* section (Table
    VII) uses a slightly different parameterization for what it also calls "the 103 MVA
    machine" — an inconsistency inside the source paper itself, not in this project's
    citation of it.
54. **Found something genuinely useful while verifying Potter et al.**: their d-LMP is a
    volatility-weighted average over the settlement period, specifically designed to contain
    price volatility — a design choice this project's own nodal scheme does not implement,
    surfaced as a real, citable limitation rather than missed.
55. **Two citations flagged as the least independently re-verified in this session**: the
    0.86 leading-power-factor grid-code figure (de Brito et al. 2025) and the Lnett tariff
    numbers (checked in an earlier session per project memory, not re-checked this session)
    — flagged honestly rather than presented with false confidence.
