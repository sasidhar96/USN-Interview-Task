"""Settlement -- turn one cleared OPF result into payments under six schemes.

Dispatch (P_g, Q_g, nodal prices) comes from a single coordinated AC OPF,
cleared against the true physical reactive cost (PhysicalCost). Every scheme
below differs only in how the DSO *pays* for that same physical outcome --
this mirrors the standard split in ancillary-service literature between a
capability/availability market and a utilisation/dispatch market (Dandachi et
al., via Wolgast et al.'s taxonomy), not six different dispatch objectives.

Two axes, per Wolgast et al. (2022)'s own taxonomy:
  service component -- capacity / utilisation / hybrid (what is paid for)
  pricing basis      -- nodal / uniform / area-wise-uniform (how the price
                         that multiplies delivered Q is computed)
Only utilisation (and hybrid, which contains a utilisation leg) has a pricing
basis to vary -- a flat capacity payment has no "price" in the nodal sense.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cost_models import PhysicalCost
from .machine import Machine
from .opf import OPFResult

# CIGRE MV's two feeders run off two SEPARATE 110/20 kV transformers (see
# net.trafo) -- a real topological boundary, not an invented partition. Used
# as the zone definition for area-wise-uniform pricing.
FEEDER_ZONES: dict[int, str] = {b: ("feeder1" if b <= 11 else "feeder2") for b in range(1, 15)}

# Three zones instead of two: split feeder 1 by real topological hop-distance
# from its own head (bus 1) -- buses <=3 hops away are "near", the rest are
# "far" -- keeping feeder 2 as its own zone (it's short enough, 3 buses, that
# splitting it further would leave a 1-bus zone). Hop distance computed via
# BFS over net.line/net.trafo, the same graph used for the placement
# experiment's remote-bus selection -- not an arbitrary redraw, the same
# topological logic already shown to correlate with nodal price.
THREE_ZONES: dict[int, str] = {
    1: "feeder1_near", 3: "feeder1_near", 4: "feeder1_near", 8: "feeder1_near",
    5: "feeder1_far", 6: "feeder1_far", 7: "feeder1_far", 9: "feeder1_far",
    10: "feeder1_far", 11: "feeder1_far",
    12: "feeder2", 13: "feeder2", 14: "feeder2",
}


@dataclass
class Settlement:
    scheme: str
    payment: dict  # {bus: EUR/h} -- reactive-power revenue only
    revenue_p: dict  # {bus: EUR/h} -- active-power revenue, energy_price * P_g
    service_cost: dict  # {bus: EUR/h} -- C_g^Q at the actual dispatch
    gen_cost: dict  # {bus: EUR/h} -- c_g^P * P_g (water value; usually 0)
    loc: dict  # {bus: EUR/h} -- informational only, see loss_of_opportunity_cost
    profit: dict  # {bus: EUR/h} -- revenue_p + payment - service_cost - gen_cost


def _service_cost(machines: dict[int, Machine], r: OPFResult, energy_price: float) -> dict:
    cost_model = PhysicalCost(energy_price)
    return {b: cost_model(m, r.p_gen[b], r.q_gen[b], r.v[b]) for b, m in machines.items()}


def loss_of_opportunity_cost(machines: dict[int, Machine], r: OPFResult, energy_price: float) -> dict:
    """Energy revenue foregone because the field limit forced P below P_max.

    LOC_g = lambda_E * max(0, P_max,g - P_g)   when the field constraint binds
          = 0                                   otherwise

    Not added to the OPF objective (see CASE_STUDY_AND_METHODOLOGY.md) and NOT subtracted in
    `profit` either: `revenue_p` already uses the generator's actual
    (possibly reduced) P_g, so the foregone revenue is already reflected
    there. Subtracting LOC again on top would double-count it -- the same
    principle the methodology applies to the OPF objective, one layer up in
    settlement. LOC is reported purely as a diagnostic: how much MORE this
    generator could have earned running flat-out at its own P_max.
    """
    loc = {}
    for b, m in machines.items():
        if r.binding[b]["field"]:
            loc[b] = energy_price * max(0.0, m.p_max - r.p_gen[b])
        else:
            loc[b] = 0.0
    return loc


def _settle(scheme: str, machines, r, energy_price, payment: dict, p_cost_gen: float = 0.0) -> Settlement:
    cost = _service_cost(machines, r, energy_price)
    loc = loss_of_opportunity_cost(machines, r, energy_price)
    revenue_p = {b: energy_price * r.p_gen[b] for b in machines}
    gen_cost = {b: p_cost_gen * r.p_gen[b] for b in machines}
    profit = {
        b: revenue_p[b] + payment[b] - cost[b] - gen_cost[b]
        for b in machines
    }
    return Settlement(scheme, payment, revenue_p, cost, gen_cost, loc, profit)


def capacity(
    machines: dict[int, Machine], r: OPFResult, energy_price: float, pi_cap: float,
    p_cost_gen: float = 0.0,
) -> Settlement:
    """Scheme 1 -- flat payment for standing reactive capability (nameplate
    MVA), independent of dispatch. Matches how real capacity/availability
    payments are structured (e.g. New England ISO's ~$587M/year VAR capacity
    payments): paid for being available, not for what is delivered this hour.
    Delivered Q never enters this formula -- that is the point of a capacity
    payment, not an omission.
    """
    payment = {b: pi_cap * m.s_rated for b, m in machines.items()}
    return _settle("1_capacity", machines, r, energy_price, payment, p_cost_gen)


def _uniform_price(machines: dict[int, Machine], r: OPFResult) -> float:
    """Simple average of the nodal price across the machines being settled.

    A real uniform-price scheme sets one system-wide price via bid-clearing
    (the highest accepted bid); we have no bid layer (dispatch is cost-based,
    not bid-cleared -- see the bid-market discussion in the accompanying
    write-up), so the closest honest stand-in is the average of the nodal
    values the OPF actually produced for the providers being paid. Stated as
    an approximation, not a bid-clearing price.
    """
    return sum(r.q_price[b] for b in machines) / len(machines)


def _awu_price(machines: dict[int, Machine], r: OPFResult, zones=FEEDER_ZONES) -> dict:
    """Area-wise-uniform: average nodal price within each feeder zone,
    applied to every machine in that zone. Zones are CIGRE MV's own two
    independently-transformed feeders, not an arbitrary split."""
    by_zone: dict[str, list[float]] = {}
    for b in machines:
        by_zone.setdefault(zones[b], []).append(r.q_price[b])
    zone_avg = {z: sum(v) / len(v) for z, v in by_zone.items()}
    return {b: zone_avg[zones[b]] for b in machines}


def variable(
    machines: dict[int, Machine], r: OPFResult, energy_price: float,
    pricing: str = "nodal", p_cost_gen: float = 0.0, zones: dict | None = None,
) -> Settlement:
    """Scheme 2 -- utilisation payment: price * delivered Q. Same settlement
    rule Potter et al. use (payment = d-LMP * Q). `pricing` selects which of
    Wolgast et al.'s three pricing bases sets that price:
      "nodal"   -- this work's proposal, r.q_price[bus] directly (default)
      "uniform" -- one averaged price for every machine (see _uniform_price)
      "awu"     -- one averaged price per zone (see _awu_price); `zones`
                   defaults to the 2-zone FEEDER_ZONES split, pass
                   THREE_ZONES for the finer-grained variant
    """
    if pricing == "nodal":
        price = {b: r.q_price[b] for b in machines}
        label = "2a_variable_nodal"
    elif pricing == "uniform":
        p = _uniform_price(machines, r)
        price = {b: p for b in machines}
        label = "2b_variable_uniform"
    elif pricing == "awu":
        price = _awu_price(machines, r, zones=zones if zones is not None else FEEDER_ZONES)
        label = "2c_variable_awu" if zones is None else "2d_variable_awu3"
    else:
        raise ValueError(f"unknown pricing basis: {pricing!r}")
    payment = {b: price[b] * r.q_gen[b] for b in machines}
    return _settle(label, machines, r, energy_price, payment, p_cost_gen)


def performance_adjusted_capacity(
    machines: dict[int, Machine], r: OPFResult, energy_price: float, pi_cap: float,
    p_cost_gen: float = 0.0,
) -> Settlement:
    """Scheme 4 -- capacity payment scaled by how much of that capacity was
    actually used this hour, fixing the sharpest critique of plain `capacity()`:
    a flat rate has ZERO marginal incentive to deliver, since it pays the
    same whether a generator delivers its full reactive capability or none.

    payment_g = pi_cap * S_rated_g * utilisation_g,  utilisation_g = |Q_g| / S_rated_g

    Which simplifies to payment_g = pi_cap * |Q_g| -- stated plainly, not
    hidden: this reduces to a utilisation payment, just priced at the real
    Statnett-sourced capacity rate (an ADMINISTERED price) rather than the
    OPF's own nodal dual (a MARGINAL-COST-derived price). That is the actual
    distinction from `variable(pricing="nodal")` -- a different, independently
    sourced price level, not a different formula shape. Genuinely different
    from plain `capacity()` in the one way that matters: a generator that
    delivers nothing gets paid nothing, same as any real
    availability-plus-performance instrument would require.
    """
    payment = {b: pi_cap * abs(r.q_gen[b]) for b, m in machines.items()}
    return _settle("4_performance_capacity", machines, r, energy_price, payment, p_cost_gen)


def load_side_charge(net, r: OPFResult) -> dict:
    """Reactive charge to each LOAD bus at that bus's own nodal price -- the
    counterparty side of every generator-side payment above.

    Nothing else in this module checks whether generator payments are
    actually covered by anyone; a review of the base case found nodal
    payments of 0.83 EUR/h to generators against 25.61 EUR/h charged to
    loads at the SAME nodal prices -- a ~31x mismatch never computed here.
    Reported alongside `capacity`/`variable`/`hybrid`'s generator-side
    payment, not merged into it: the two are deliberately different
    quantities (a capacity payment, in particular, has no reason to equal
    a utilisation-based load charge -- that gap is itself the finding).
    """
    charge: dict[int, float] = {}
    for _, row in net.load.iterrows():
        b = int(row.bus)
        charge[b] = charge.get(b, 0.0) + r.q_price[b] * row.q_mvar
    return charge


def cost_recovery(payment: dict, charge: dict) -> dict:
    """Reconcile total generator-side payment against total load-side
    charge for one scheme: is this settlement scheme budget-balanced,
    running a surplus, or under-recovering?
    """
    total_payment = sum(payment.values())
    total_charge = sum(charge.values())
    return {
        "generator_payment_eur_h": total_payment,
        "load_charge_eur_h": total_charge,
        "net_surplus_eur_h": total_charge - total_payment,
        "recovery_ratio": total_payment / total_charge if total_charge else float("nan"),
    }


def hybrid(
    machines: dict[int, Machine], r: OPFResult, energy_price: float,
    pi_cap: float, capacity_weight: float = 1.0, pricing: str = "nodal",
    p_cost_gen: float = 0.0,
) -> Settlement:
    """Scheme 3 -- the full capacity payment PLUS the full utilisation payment,
    stacked, not blended. This mirrors how real capacity+energy ancillary
    markets work (e.g. PJM): the capacity market and the delivery market are
    separate, additive revenue streams, not a fixed budget split between them.

    capacity_weight scales only the capacity leg (default 1.0 = full stack);
    it exists so a DSO that wants to phase in a partial capacity payment can
    be modelled, but 1.0 is the economically standard case, not 0.5.
    """
    if pricing == "nodal":
        price = {b: r.q_price[b] for b in machines}
    elif pricing == "uniform":
        p = _uniform_price(machines, r)
        price = {b: p for b in machines}
    elif pricing == "awu":
        price = _awu_price(machines, r)
    else:
        raise ValueError(f"unknown pricing basis: {pricing!r}")
    payment = {
        b: capacity_weight * pi_cap * m.s_rated + price[b] * r.q_gen[b]
        for b, m in machines.items()
    }
    return _settle("3_hybrid", machines, r, energy_price, payment, p_cost_gen)
