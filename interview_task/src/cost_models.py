"""The two reactive cost models under comparison.

Both return a Pyomo-compatible expression in (P, Q, V) for one machine, in
EUR/h, given the energy price. Swapping them is the whole experiment.
"""

from __future__ import annotations

from .machine import Machine


class AssumedCost:
    """Case A — Potter et al. (2023).

    C^Q = b^Q |Q| with b^Q = 0.1 b^P, motivated by the FERC observation that
    reactive prices are often one tenth of real power prices. Potter's own
    IEEE-123 results measure reactive d-LMP at ~10% of real d-LMP, so the
    coefficient is empirically supported for smart inverters.

    |Q| is not differentiable at zero, so it is smoothed to sqrt(Q^2 + eps).
    eps is deliberately not tiny: at 1e-8 the kink is sharp enough that IPOPT
    stalls, and the smoothing is invisible beyond ~0.01 MVAr either way.
    """

    label = "assumed"

    def __init__(self, energy_price: float, ratio: float = 0.1, eps: float = 1e-4):
        self.energy_price = energy_price
        self.ratio = ratio
        self.eps = eps

    def __call__(self, machine: Machine, p, q, v):
        return self.ratio * self.energy_price * (q**2 + self.eps) ** 0.5


class PhysicalCost:
    """Case B — derived from the machine.

    C^Q = lambda_E [ P_loss(P, Q) - P_loss(P, Q_ref(P,V)) ]

    Cost is measured against Q_ref(P,V) -- the machine's own loss-minimising
    reactive point Q*(V), clamped up to the underexcitation floor at this P
    when Q*(V) alone isn't actually reachable there (see `Machine.q_ref`'s
    docstring; caught by external review -- Q* ignored that its own
    reachability depends on P, which overstated cost at low P, exactly where
    G2-G4 spend most of their time in this study). Q_ref is never Q=0.

    This follows the accumulated-average-efficiency method: deviation from
    the minimum-loss path through the (feasible) capability diagram is the
    cost of the service. Non-negative by construction, and zero at a
    physically meaningful, reachable, — usually slightly underexcited —
    operating point.

    Note this contradicts the 0.95-0.95 pricing deadband: cost inside the band
    is non-zero and asymmetric about Q = 0.
    """

    label = "physical"

    def __init__(self, energy_price: float):
        self.energy_price = energy_price

    def __call__(self, machine: Machine, p, q, v):
        # P does NOT cancel between the two loss terms here (unlike the old
        # Q*(V)-only reference) -- Q_ref depends on P too, so both terms are
        # kept explicit rather than assumed to simplify.
        return self.energy_price * (
            machine.loss(p, q, v) - machine.loss(p, machine.q_ref(p, v), v)
        )


class DeadbandCost:
    """Case D — Norway's real consumer-side reactive withdrawal tariff,
    applied symmetrically to generation (which today it is not: Norway
    charges withdrawal but never pays generators for supply -- see
    norwegian-reactive-power-practice memory).

    Free within a PF-based deadband; Case A's flat 0.1 lambda_E rate applies
    only to the excess beyond it. Default threshold 0.30 is Lnett's own
    figure ("betales bare for den del av reaktiv effekt som overstiger 30 %
    av den aktive effekten", cos phi ~= 0.958); Elvia's 2026 tariff uses 0.33
    instead -- both real, different DSOs.

    Deliberately reuses Case A's rate rather than inventing a new one, so any
    divergence from Case B is attributable to the deadband *structure* (free
    zone, then flat) and not to a different price level. This is the direct
    demonstration of the claim in PhysicalCost's docstring: a deadband
    assumes zero cost inside the band, and the physical model shows that's
    false.
    """

    label = "deadband"

    def __init__(self, energy_price: float, threshold: float = 0.30, ratio: float = 0.1, eps: float = 1e-4):
        self.energy_price = energy_price
        self.threshold = threshold
        self.ratio = ratio
        self.eps = eps

    def __call__(self, machine: Machine, p, q, v):
        q_mag = (q**2 + self.eps) ** 0.5
        excess = q_mag - self.threshold * p
        excess_pos = 0.5 * (excess + (excess**2 + self.eps) ** 0.5)  # smooth max(0, .)
        return self.ratio * self.energy_price * excess_pos


class NoCost:
    """Case 0 — reactive power is free. Today's practice inside the deadband."""

    label = "free"

    def __call__(self, machine: Machine, p, q, v):
        return 0.0
