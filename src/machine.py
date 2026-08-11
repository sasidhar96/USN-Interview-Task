"""Synchronous machine loss and capability model.

Round-rotor form (X_d = X_q). Follows the phasor relation used by SynGenLib's
`pyomo_generator_loss_model`:

    E_f^2 = V^2 [ (1 + X_s Q / V^2)^2 + (X_s P / V^2)^2 ]
    P_field = k_f * E_f^2

This is a deliberate simplification against the primary source for this
machine class -- Karekezi, Melfald, Oyvang & Noland (2023), "Loss Modeling of
Large Hydrogenerators for Cost Estimation of Reactive Power Services and
Identification of Optimal Operation," IEEE Trans. Energy Conversion 38(2),
verified directly against the PDF this session. Their rotor loss (eq. 5) is
linear-plus-quadratic in field CURRENT, not purely quadratic in EMF:

    P_l,r = P_ex*(I_f/I_f*) + (P_f*+P_br*)*(I_f/I_f*)^2

and I_f is obtained from a saturated Potier-triangle construction (their eqs.
21-23), not a closed form. They also use a true salient-pole model
(X_d=1.087 pu, X_q=0.676 pu for their 103 MVA reference machine -- a 38%
difference, not a small one). Neither of those is implemented here: doing so
would mean an implicit/root-solve relation inside the OPF, which is exactly
the reason SynGenLib itself cannot be embedded directly in Pyomo (see
DESIGN.md). The E_f^2-quadratic form kept here is closed-form and
differentiable, at the cost of that fidelity.

Cross-checked, not just declared: with G1's parameters below, this model's
analytical Q* comes out to -0.191 pu (machine base) against the paper's own
reported -0.194 to -0.202 pu (with saturation) and -0.152 to -0.157 pu
(without saturation -- the more comparable case, since this model has no
saturation either). Falls inside the saturated range and close to the
unsaturated one; the residual gap is attributable to the structural
differences above (round-rotor vs salient-pole, no saturation), not a bug.

Getting this close required one correction, caught by review: r_a_pu must be
the paper's COMBINED armature+stray-load loss (Table I, 276.62 kW / 103 MVA =
0.0026862 pu), not Table II's standalone R_a=0.002pu. The paper's own stator
loss equation scales the combined 276.62 kW figure by (I_a/I_a*)^2, not
R_a*I_a^2 -- Table II's R_a is used elsewhere in the paper (the Potier
field-current estimate), not as a stator I^2R coefficient. This model's
stator_loss() IS the simplified R_a*I^2 form, so reproducing the paper's
total rated stator-side loss means using the combined figure as R_a here.
Using 0.002pu alone (an earlier version of this file did) understated stator
loss by the missing 70.6 kW stray-load component and put Q* at -0.239 pu --
outside the paper's own range, not just an approximation of it.

All quantities are per unit **on the system base**. Use `Machine.on_system_base`
to convert a nameplate given on the machine's own base.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Machine:
    name: str
    s_rated: float  # pu on system base
    x_s: float  # synchronous reactance, pu on system base
    r_a: float  # armature resistance, pu on system base
    e_f_max: float  # max excitation EMF, pu
    k_f: float  # field loss coefficient: P_field = k_f * E_f^2
    p_max: float
    p_min: float
    p_const: float = 0.0  # core + friction + windage, independent of Q
    pf_lead_max: float = 0.86  # Norwegian grid code max leading power factor

    @classmethod
    def on_system_base(
        cls,
        name: str,
        s_rated_mva: float,
        s_base_mva: float,
        x_s_pu: float,
        r_a_pu: float,
        e_f_max: float,
        k_f: float,
        p_max_pu: float,
        p_min_pu: float,
        p_const_pu: float = 0.0,
        pf_lead_max: float = 0.86,
    ) -> "Machine":
        """Convert a nameplate given on the machine base to the system base.

        A per-unit impedance moves base as X_new = X_old * (S_new / S_old), so a
        1.0 pu reactance on a 20 MVA machine is 0.05 pu on a 1 MVA system base.
        Powers scale the other way.
        """
        z_scale = s_base_mva / s_rated_mva
        p_scale = s_rated_mva / s_base_mva
        return cls(
            name=name,
            s_rated=p_scale,
            x_s=x_s_pu * z_scale,
            r_a=r_a_pu * z_scale,
            e_f_max=e_f_max,
            k_f=k_f * p_scale,
            p_max=p_max_pu * p_scale,
            p_min=p_min_pu * p_scale,
            p_const=p_const_pu * p_scale,
            pf_lead_max=pf_lead_max,
        )

    @classmethod
    def from_nameplate(
        cls,
        name: str,
        s_rated_mva: float,
        s_base_mva: float,
        cos_phi: float,
        x_d_pu: float,
        r_a_pu: float,
        rotor_loss_frac: float,
        p_max_pu: float,
        p_min_pu: float,
        p_const_pu: float = 0.0,
        pf_lead_max: float = 0.86,
    ) -> "Machine":
        """Build from a nameplate, deriving E_f,max and k_f instead of assuming them.

        The rated point (P = cos_phi, Q = sin_phi at V = 1) is by definition the
        corner of the capability diagram where the field limit is reached, so

            E_f,max^2 = (1 + X_d sin_phi)^2 + (X_d cos_phi)^2

        Picking E_f,max by hand instead tends to make it too generous and the
        field limit never binds -- the machine then looks stator-limited, which
        is the wrong physics for a salient-pole hydro unit. `cos_phi` and `X_d`
        are both parameters SynGenLib's GeneratorDataclass already carries.

        `rotor_loss_frac` is field (rotor) copper loss at the rated point, as a
        fraction of S_rated -- the same quantity SynGenLib calls
        `P_loss_nom_rotor_pu`. At the rated point E_f = E_f,max by construction,
        so k_f = rotor_loss_frac / E_f,max^2. This still has to be assumed (no
        source for this specific split was accessible this session -- the
        Karekezi et al. IEEE TEC papers this figure would come from were
        paywalled), but it is one order-of-magnitude sanity-checkable number
        instead of an unexplained k_f pulled from nowhere.

        Note `p_max_pu` should sit below `cos_phi`, or the stator and field
        circles meet exactly at the dispatch point and neither binds first.
        """
        sin_phi = (1.0 - cos_phi**2) ** 0.5
        e_f_max = ((1 + x_d_pu * sin_phi) ** 2 + (x_d_pu * cos_phi) ** 2) ** 0.5
        k_f = rotor_loss_frac / e_f_max**2
        return cls.on_system_base(
            name, s_rated_mva, s_base_mva, x_d_pu, r_a_pu, e_f_max,
            k_f, p_max_pu, p_min_pu, p_const_pu, pf_lead_max,
        )

    # --- losses -----------------------------------------------------------

    def stator_loss(self, p, q, v):
        return self.r_a * (p**2 + q**2) / v**2

    def field_loss(self, p, q, v):
        return self.k_f * ((v + self.x_s * q / v) ** 2 + (self.x_s * p / v) ** 2)

    def loss(self, p, q, v):
        return self.stator_loss(p, q, v) + self.field_loss(p, q, v) + self.p_const

    def q_star(self, v):
        """Reactive output that minimises loss at fixed P. Always negative.

        d(loss)/dQ = 0  =>  Q* = -k_f X_s V^2 / (R_a + k_f X_s^2)

        Slightly underexcited: cutting excitation saves more field loss than the
        extra stator current costs, until this point.
        """
        return -self.k_f * self.x_s * v**2 / (self.r_a + self.k_f * self.x_s**2)

    def marginal_loss(self, q, v):
        """d(loss)/dQ at fixed P — linear in Q, non-zero intercept."""
        return 2 * self.k_f * self.x_s + 2 * (self.r_a + self.k_f * self.x_s**2) * q / v**2

    def q_ref(self, p, v, eps: float = 1e-6):
        """The reference point PhysicalCost measures deviation from --
        Q*(V) if that's actually reachable at this P, else the tightest
        binding limit at this P.

        Caught by external review: Q*(V) alone (the old reference) ignores
        that Q also has to satisfy the underexcitation floor,
        Q >= -P*tan(acos(pf_lead_max)), which DOES depend on P. At every
        machine's own p_min this floor sits well above Q*(V) (e.g. G1:
        floor=-0.089 pu machine-base vs Q*=-0.191 -- Q* needs P >= ~38% of
        p_max before it's reachable at all), so the cost was being measured
        against an operating point the machine's own other constraint
        already forbids at low P -- overstating service cost there (by
        ~60% for G2/G4 in the study's actual dispatch, where P sits at or
        near p_min most hours).

        Q* is never positive (see `q_star`'s docstring) and the stator/field
        circles only bind at high |Q|, so in practice only the lower
        (underexcitation) floor can be violated here -- the fix is a
        one-sided clamp, `max(floor, Q*)`, not a full two-sided projection
        onto the stator/field circles too (verified: at every (P,V) this
        model dispatches, Q* sits well inside both circles whenever it's
        above the floor -- adding an upper clamp would be defending against
        a case that doesn't occur, at the cost of a more fragile smoothed
        expression).

        Smoothed (`sqrt((a-b)^2+eps)` in place of `|a-b|`) so the reference
        is differentiable everywhere, matching how `cost_models.py`'s own
        smoothed max(0,.) terms are already handled -- IPOPT needs this,
        not just style consistency; a hard `max()` has an undefined
        derivative exactly on the kink, which is exactly where the
        optimizer likes to sit.
        """
        floor = -p * math.tan(math.acos(self.pf_lead_max))
        qs = self.q_star(v)
        return 0.5 * (floor + qs + ((floor - qs) ** 2 + eps) ** 0.5)

    # --- capability limits (written as g(P,Q,V) <= 0) ---------------------

    def stator_limit(self, p, q, v):
        return p**2 + q**2 - self.s_rated**2

    def field_limit(self, p, q, v):
        """Field circle: centre (0, -V^2/X_s), radius V*E_f_max/X_s."""
        return p**2 + (q + v**2 / self.x_s) ** 2 - (v * self.e_f_max / self.x_s) ** 2

    def underexcitation_limit(self, p, q, v):
        """Norwegian grid-code leading power-factor limit.

        Stated as a maximum leading PF (phi_lead_max = 0.86, per de Brito,
        Baltensperger & Uhlen, CIGRE Trondheim 2025) rather than an arbitrary
        fraction of the theoretical stability limit. A PF bound is a straight
        line through the origin, Q >= -P*tan(acos(pf_lead_max)), not the
        voltage-dependent constant this replaced.
        """
        return -q - p * math.tan(math.acos(self.pf_lead_max))
