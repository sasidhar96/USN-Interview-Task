# Mechanism Design Discussion — LOC, Bid Markets, and Post-Hoc vs. Game-Theoretic Settlement

Written before running any further scenarios, per the request to "dig deep" first.
Grounded in the Brain's wiki (`reactive-power-markets`, `market-pricing-mechanisms`,
`market-design-approaches`, `bi-level-optimization`, `vcg-mechanism`,
`nash-equilibrium-game-theory` — all cited inline) plus data already in hand
from the 2,915-hour water-value run.

## 1. Is a generator absorbing reactive power ("lagging/leading") normal?

Yes — and it's already happening in this study, not a hypothetical. A
synchronous generator delivering positive Q is **overexcited** (lagging
power factor, supplying reactive power to the grid); delivering negative Q
is **underexcited** (leading power factor, *absorbing* reactive power from
the grid). Both are completely normal, designed-for operating modes — it's
literally what the field current knob does. Real generators, including
large hydro units, routinely run underexcited during light-load periods
specifically to help hold voltage down and reduce system losses.

**In the actual data**: G2 is negative (absorbing) in 36.9% of the 2,915
hours, G4 in 25.7%. G1 and G3 are never negative — they're the two
"anchor" units the optimizer leans on for genuine reactive *supply*.
This is not a fault or a modeling artifact; it's the direct, expected
consequence of the loss-minimizing point Q\* itself being negative for
every machine (§3.2 of `CLAUDE.md`) — a well-run generator sits *near* its
own Q\*, and Q\* is inherently on the underexcited side. A fleet where every
machine were always overexcited would actually be the surprising result.

## 2. Loss-of-opportunity-cost (LOC) — already modeled, currently always zero, here's why

**It is modeled.** `src/settlement.py`'s `loss_of_opportunity_cost()`
computes exactly the standard formulation the Brain's wiki confirms is the
literature-standard treatment (`wiki/concepts/reactive-power-markets.md`,
`market-pricing-mechanisms.md` — "Opportunity cost (LOC): Active power
revenue foregone to provide Q, paid when providing Q restricts P output" —
one of the four canonical settlement components alongside availability,
utilisation, and fixed-price payments):

$$LOC_g = \lambda_E \cdot \max(0,\, P_{max,g} - P_g) \quad\text{when the field-current limit binds, else } 0$$

It is deliberately **not** added to the OPF objective (that would
double-count — CLAUDE.md §3.4, independently verified by the earlier blind
review as correctly avoided) and **not** subtracted again in `profit`
(`revenue_p` already reflects the reduced `P_g`, so subtracting LOC on top
would double-count a second time). It's reported purely as a diagnostic.

**Why it reads as ~0 everywhere in the current data, checked directly**:
across all 2,915 hours and all 4 generators, the field-current limit binds
**zero times**. This isn't a guess — pulled straight from the
`{gen}_field_binding` flags added this session. Consistent with
§9/§12 of `CLAUDE.md`: this fleet's installed capacity exceeds real feeder
demand most hours, so no machine is ever pushed to the P/Q corner where the
field limit would force a P cutback. **Nothing needs to change in the LOC
model itself** — it's correctly implemented and correctly reporting zero
because the event it measures genuinely isn't happening at these demand
levels. If you want a non-zero LOC to show on a slide, the lever is the
*scenario* (push the load sweep further, or shrink the fleet), not the LOC
formula.

**One interesting, related, non-zero finding**: G4's *underexcitation*
limit (the Norwegian 0.86-leading-PF grid code floor, a different
constraint from the field limit) binds in **19.2%** of hours (559/2,915).
G4 is regularly pushed to the edge of how much it's allowed to absorb.
There's no "LOC" concept on this side in the standard literature (LOC is
specifically about *P* foregone for *Q*, not Q itself being capped) — but
it's worth a sentence on the slide as a second, real, currently-binding
constraint, distinct from the field limit that never binds.

## 3. Bid/market mechanism for a small (2-4 generator) reactive power pool

Per the Brain (`reactive-power-markets.md`, `market-design-approaches.md`,
`nash-equilibrium-game-theory.md`), this is a genuinely harder, actively
unsolved problem in the literature — not just an engineering add-on to what
exists:

- **Reactive power markets essentially don't exist in practice.** Potter
  et al. 2023 (cited in the Brain): "Reactive power markets do not
  currently exist in the US." Most real systems use mandatory obligation
  or administered/fixed pricing instead (exactly what Statnett fos §15 and
  Lnett's tariff are — administered, not market-cleared). Proposing an
  actual bid mechanism would be a research contribution in its own right,
  which is presumably exactly why it's a good *follow-up question* for the
  panel rather than something expected in this deliverable.
- **Small-N market power is a named, flagged, understudied problem**,
  not a hypothetical: "Market power: monopsonistic buyer + few local
  providers = gaming risk (understudied)" and specifically for reactive
  power: *"standard market power indices (HHI, must-run index) developed
  for active power markets don't translate directly to reactive power
  markets because of the monopsony structure and geographic locality"*
  (Wolgast et al. 2022, via `nash-equilibrium-game-theory.md`). **This
  fleet is a textbook case of the problem, not just an example of it**:
  feeder 1 has exactly 2 potential Q providers (G1, G2), feeder 2 has
  exactly 2 (G3, G4). If reactive power is genuinely local (it is — see
  `reactive-power-fundamentals`), each feeder is effectively a 2-provider
  local market, or worse, a single "must-run" provider once the other's
  headroom is used up. A 2-participant market has essentially no
  competitive discipline; standard mechanism-design tools (VCG, double
  auctions) assume enough participants for competition to matter.
- **The grid operator is a monopsony (sole buyer)** — a second, independent
  reason standard competitive-market theory doesn't transfer cleanly, per
  `reactive-power-markets.md`.
- **The 7-property mechanism-design checklist** (efficiency, incentive
  compatibility, individual rationality, budget balance, tractability,
  privacy, explainability) has a proven impossibility result baked in:
  **no mechanism achieves all 7 simultaneously**, and specifically
  **incentive compatibility and budget balance are largely mutually
  exclusive** (Myerson-Satterthwaite theorem, `market-design-approaches.md`,
  `vcg-mechanism.md`). VCG gets IC but not budget balance (may need
  external subsidy — politically awkward for a DSO); pay-as-bid gets
  budget balance but not IC (bidders shade their true cost). **Any bid
  mechanism proposal for the follow-up slide needs to state which property
  it's sacrificing, not claim it gets everything.**
- **What a workable design would plausibly need**, synthesized from the
  taxonomy: bids as (price, quantity) pairs per generator against their own
  capability curve (not a single number — Q value depends on P and V), an
  Availability+Utilisation two-part structure (the EPF framework, Zhong &
  Bhattacharya, cited in the Brain, is the standard way to let generators
  bid once across both components), area-wise-uniform pricing per feeder
  zone (already implemented in `src/settlement.py`'s `_awu_price` — this
  turns out to be the literature's most common practical compromise, not
  an arbitrary choice), and — given the small-N problem above — some
  explicit market-power mitigation (e.g. an offer cap, or defaulting to the
  administered PhysicalCost price as a "reference" that bids are checked
  against, similar to how real ISOs cap bids relative to estimated
  marginal cost).

**Bottom line for the follow-up question**: yes, worth raising as a
research direction — but the honest framing is "this fleet's own topology
(2 providers per feeder) is close to a worst case for competitive bidding,
which is exactly why administered pricing, not a market, is what's proposed
here — and that's a defensible, literature-grounded position, not a
shortcut."

## 4. Post-hoc settlement vs. game-theoretic (bilevel) reformulation

Directly addresses "is the post-hoc approach going in the right direction."

**What exists now**: one coordinated OPF solve, minimizing true system cost
(`PhysicalCost`), then N different payment formulas applied to that single
fixed outcome. This answers "how should the DSO **split payment** for an
already-efficient outcome" — a real, legitimate question (§6 of
`CLAUDE.md`), matching how Wolgast et al.'s own taxonomy treats
capacity/utilisation/hybrid (a payment-structure axis, not a
dispatch-objective axis).

**What it can't answer**: whether a generator would behave *differently*
under a different payment rule — i.e., whether the rule is **incentive
compatible**. Right now, by construction, it can't be gamed *in this model*,
because the model doesn't let generators act in their own interest at all —
they're dispatched centrally against true cost, full stop.

**What a genuine behavioral/game-theoretic version requires**, per the
Brain's `bi-level-optimization.md`:

- **Structure**: a Stackelberg game / bilevel program. Upper level: each
  generator (or the DSO) chooses a bid/strategy to maximize its own profit.
  Lower level: the OPF clears the market/dispatch given those bids, not
  given true cost.
- **Solvability**: the lower level (the OPF) has to be **convex** for the
  standard KKT-reformulation route to work at all — our AC-OPF is
  **non-convex** (that's exactly why IPOPT, not a convex solver, is used
  throughout this project). This is the real blocker, not just "more code."
  The honest options are: (a) convexify the lower level (e.g. DC
  approximation, or a convex relaxation of the AC equations) and accept the
  fidelity loss, (b) an iterative best-response simulation instead of an
  exact MPEC (each generator re-solves its own profit-max problem holding
  others fixed, repeat until it settles — no formal convergence/uniqueness
  guarantee, but tractable with the exact non-convex AC-OPF already built),
  or (c) a much smaller, illustrative single-generator "what if it
  misreported its cost" experiment rather than a full multi-agent
  equilibrium.
- **What it would let us answer, that we can't today**: is a scheme
  gameable (would a generator profit from misreporting cost or
  withholding capacity)? Does the fleet's small-N structure (§3 above)
  produce real market power? Does profit-maximizing behavior converge to
  the same dispatch as the coordinated optimum, or leave welfare on the
  table (Price of Anarchy, per `nash-equilibrium-game-theory.md`)?
- **Complexity, plainly**: bilevel programs are NP-hard in general even
  when both levels are individually easy (`bi-level-optimization.md`).
  This is not a same-day addition on top of the existing single-level AC-OPF
  codebase — it's a different, harder modeling paradigm requiring either a
  convexified network model or an iterative heuristic with no optimality
  guarantee.

**Recommendation given the deadline**: keep the post-hoc architecture as
the primary result — it's honest, literature-grounded, and already produces
the strongest single number in the study (9.7% capacity-payment cost
recovery). Do **not** attempt a full bilevel/MPEC reformulation before
submission; the non-convexity of the underlying AC-OPF makes that a
multi-day undertaking with real convergence risk, not a quick add. If time
allows one small, self-contained addition: a **single best-response
illustration** — e.g. take G1 at one representative hour, let it report a
cost 2× its true value under the nodal scheme, re-solve, and show whether
its profit goes up (answers "is this scheme gameable, at least for one
generator, in one direction" cheaply) — flagged explicitly as an
illustration, not a full equilibrium analysis. This is the Tier-3
"withholding experiment" the blind review already recommended
(`review/00_synthesis.md`), and it's the only piece of this whole
discussion that's actually cheap to build.

## 5. Where does the incentive actually live? (Follow-up, resolving a real point of confusion)

Sharpened after a direct back-and-forth: "the optimizer doesn't care about
anything not in the objective function — so if the goal is to *incentivize*
generators, shouldn't the incentive be *in* the objective?" This is correct,
and the answer is: **it already is — just not the part you'd expect.**
"Incentivize" bundles two genuinely different questions, and this project
answers them with two different mechanisms, deliberately:

### 5a. "What should each generator do?" — answered *inside* the objective, not post-hoc

`C_g^Q(P_g,Q_g,V_g)` (`PhysicalCost`) is a term in the OPF's objective
(§4.1 of `CLAUDE.md`) — solving the OPF **is** the act of incentivizing the
right dispatch, in exactly the same architectural sense as Potter et al.'s
`b^Q Q` term in their own objective (§ below). Comparing `AssumedCost` vs
`PhysicalCost` vs `DeadbandCost` (Cases A/B/D) is comparing three different
answers to "what should the objective reward," and each one **does** change
the actual dispatch — verified directly by `test_cost_models_actually_swap`.
None of this is post-hoc.

### 5b. "How should the DSO pay for what already happened?" — this is the post-hoc part

Given the dispatch that (5a) already produced, `src/settlement.py`'s four
payment rules (capacity/nodal/uniform/AWU/hybrid) answer a *different*
question: how to split the resulting cash. This is what stays post-hoc, and
it's a legitimately separate question from (5a) — real DSOs and ISOs also
split "what's the efficient dispatch" (an engineering/optimization question)
from "who gets paid what for it" (a distributive/revenue-adequacy question).

### The nodal scheme (2a) is not an arbitrary post-hoc formula — it's constructed to match (5a)

This is the resolving point. Scheme 2a pays `λ^Q_bus × Q_delivered`, where
`λ^Q_bus` is the **dual** of the same reactive-balance constraint that the
`C_g^Q` objective term already shaped. `test_price_at_unconstrained_generator_equals_its_marginal_cost`
proves directly that at any unconstrained generator, `λ^Q_bus` **equals that
generator's own marginal cost** `∂C_g^Q/∂Q` at the solution. That equality —
price equals marginal cost — is precisely the condition under which a
*self-interested, price-taking* generator would voluntarily choose to
produce exactly the `Q` the centralized OPF already gave it (standard
LMP-market theory: this is why real energy markets use marginal-cost
pricing at all). **So scheme 2a's payment isn't just "a" post-hoc rule — of
the four schemes, it's the one specifically incentive-consistent with the
dispatch that (5a) already computed.** If the generators actually got to
choose for themselves facing that price, nothing would change.

What this does *not* resolve: whether generators would behave this way in a
real, decentralized, strategic setting rather than the fully centralized
setting modelled here (§3's small-N market-power concern) — that gap is
exactly the bilevel/game-theory question from §4, still open.

**Scheme 1 (capacity), by contrast, has zero Q-dependence in its formula** —
it pays the same whether a generator delivers its full reactive capability
or none at all. It incentivizes *installing* capability, not *delivering*
it. That's not a flaw in the scheme (capacity/availability payments are a
real, standard ancillary-service instrument for exactly this purpose — long-
run investment signal, not short-run dispatch signal), but it's worth being
precise that scheme 1 alone does not incentivize supply in the delivery
sense the word usually implies; scheme 3 (hybrid) exists specifically to
combine both signals.

### Every price in the objective, enumerated — inputs vs. the one output

| Symbol | What it prices | Value / source | Input or output? |
|---|---|---|---|
| `λ_E` | energy (`P_slack`, and implicitly all network losses) | 70 EUR/MWh, SysOpt WP4 | **Input** — chosen before solving |
| `π_Q` | reactive exchange at the TSO-DSO interface | Lnett HV tariff: 3.478 EUR/MVArh winter, 0.435 summer | **Input** |
| `c_g^P` | each generator's own active energy | `= λ_E` by the water-value convention | **Input** — a modeling choice, not an independently sourced number |
| `C_g^Q(P,Q,V)` | each generator's own reactive service | a *function*, not a number — built from `R_a, X_s, k_f` (Karekezi-cited for G1/G3, illustrative for G2/G4) and `λ_E` | **Input** — no separate "price coefficient" needed; this is the whole contribution (cf. Case A's `0.1·λ_E`, which *is* an assumed input coefficient) |
| `λ^Q_bus` | the nodal reactive price everyone actually calls "the price" | — | **Output** — the dual of the reactive-balance constraint, extracted *after* solving; used only by the settlement layer (5b), never fed back as an objective input |

### Is our direction right?

Yes, with the two-part framing above made explicit on the slide: "we
incentivize efficient reactive dispatch by pricing it correctly *inside* the
objective (physically derived, not assumed — §6a), and we incentivize fair
compensation for that dispatch via settlement rules structured to match the
resulting shadow price where possible (nodal, §6b)." That is a complete,
honest, defensible answer to "how do you incentivize hydro generators to
supply reactive power" — it just uses two different mechanisms for two
different sub-questions, deliberately, not by oversight.

### Potter, precisely, on the same two questions

Their `b^Q Q` term lives in the same place as our `C_g^Q` — inside the
objective, answering (5a). Their d-LMP payment (their eq. 12, a **daily
Q-weighted average** of the real-time dual, used specifically to reduce
settlement volatility while dispatch still follows the real-time clearing)
is architecturally the same instrument as our nodal scheme 2a, answering
(5b) the same way. **They do not offer a capacity/availability scheme at
all** — a real, substantive difference from this project, not just a
detail. Their own paper argues explicitly against capacity payments,
because their target resource (DER smart inverters) has heterogeneous,
largely unobservable costs, so an administered capacity rate can't be set
credibly. **The case for including a capacity scheme here is exactly the
mirror image of their argument, not a contradiction of it**: dispatchable
synchronous hydro has a small number of large, well-characterized,
cost-analyzable units — precisely the population the literature says
capacity/cost-based administered pricing is suited to (per the Brain: "This
cost-based compensation is commonly used today... generally limited to
large traditional generators who can afford the cost analyses... most DGs
[are] not [as] applicable"). Potter is right to reject capacity payment for
their DER context; it's right to include it for this project's hydro
context — same literature, opposite resource, opposite conclusion, both
correct.

## 6. Recommendation: what to do before running further scenarios

1. State the post-hoc architecture's scope limit explicitly on the slide
   (§4) — this is a documentation task, zero new compute.
2. State the small-N market-power finding as the honest answer to "could
   this be a bid market" (§3) — also zero new compute, strengthens the
   deliverable rather than weakening it.
3. If time allows: the one single-generator withholding illustration (§4) —
   small, bounded scope, ~1 hour of work, not a new architecture.
4. Everything else already validated (`TECHNICAL_VALIDATION.md`,
   `RESULTS_ANALYSIS.md`) stands — no changes needed there before scaling
   up to more scenarios.
