"""Library of reference port-Hamiltonian systems."""

import numpy as np
import numpy.typing as npt

from .iphs import ModulatedIPHS
from .phs import PortHamiltonianSystem


def water_tank(
    A: float = 1.0,
    a: float = 0.1,
    g: float = 9.81,
    c_d: float = 0.6,
    rho: float = 1000.0,
) -> PortHamiltonianSystem:
    """
    Water tank with drain (passive dissipative PHS).

    State: x = [h] (water height, m)
    Input: u = [q_in] (inflow rate, m³/s)
    Energy: H(h) = (1/2) ρ g A h² (potential energy)

    Dynamics:
        ẋ = -c_d a √(2gh) / A + u / A
          = (J - R) ∇H + g u

    where:
        J = 0 (no internal interconnection for 1D)
        R = c_d a / (ρ g A²) (dissipation from drain)
        g = 1/A (input map)
        ∇H = ρ g A h

    With u=0, energy strictly decreases (passive system).

    Args:
        A: Tank cross-sectional area (m²)
        a: Drain orifice area (m²)
        g: Gravitational acceleration (m/s²)
        c_d: Discharge coefficient (dimensionless, typically ~0.6)
        rho: Water density (kg/m³)

    Returns:
        PortHamiltonianSystem for water tank

    Example:
        >>> tank = water_tank()
        >>> x = np.array([1.0])  # 1m height
        >>> u = np.array([0.0])   # no inflow
        >>> dx = tank.dynamics(x, u)
        >>> dx[0] < 0  # Height decreases
        True
        >>> tank.energy(x) > 0
        True
    """

    def H(x: npt.NDArray[np.floating]) -> float:
        """Potential energy: (1/2) rho g A h^2, with the head clamped at empty.

        The clamp matters: H is even in h, so without it a step that overshoots
        below empty reads back as an energy *increase* and passivity appears to
        fail for a purely numerical reason.
        """
        h = max(float(x[0]), 0.0)
        return float(0.5 * rho * g * A * h**2)

    def grad_H(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Gradient: grad_H = rho g A h, with the head clamped at empty."""
        h = max(float(x[0]), 0.0)
        return np.array([rho * g * A * h])

    def J(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Interconnection: J = 0 (1D system, no internal coupling)."""
        return np.zeros((1, 1))

    def R(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """
        Dissipation from drain: R = c_d a / (ρ g A²).

        The drain flow is: q_out = c_d a √(2gh) = R ∇H
        where R is chosen so that the PHS structure is exact.
        """
        # Torricelli's law gives the outflow VOLUME rate q = c_d a sqrt(2 g h),
        # so the rate of change of HEAD is dh/dt = -c_d a sqrt(2 g h) / A.
        #
        # In port-Hamiltonian form with J = 0 we need  R grad_H = c_d a sqrt(2gh)/A,
        # and grad_H = rho g A h, hence
        #
        #     R = c_d a sqrt(2 g h) / (rho g A^2 h)
        #       = c_d a sqrt(2 g / h) / (rho g A^2)
        #
        # Both the `g` under the radical and the SECOND factor of `A` are
        # load-bearing. An earlier version of this function had
        #     R = c_d a sqrt(2/h) / (rho g A)
        # which is dimensionally inconsistent -- it yields dh/dt in units of
        # m^2.5 -- and drains the tank 3.13x too slowly (a factor sqrt(g)/A).
        # It produced a perfectly smooth, plausible decay curve, and no
        # accuracy test caught it; it was found by dimensional analysis.
        # See otwin-spec fixture `water_tank_drain_law`, which now catches it
        # by 157%.
        #
        # R is regularised to zero below h = 1e-9 because the exact form is
        # singular at an empty tank, and the head is clamped at zero because
        # H = (1/2) rho g A h^2 is EVEN in h -- an overshoot below empty would
        # otherwise read back as an energy *increase*.
        h = max(float(x[0]), 0.0)
        R_val = 0.0 if h < 1e-9 else c_d * a * np.sqrt(2.0 * g / h) / (rho * g * A * A)
        return np.array([[R_val]])

    def g_mat(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Input map: g = [1/A] (inflow increases volume at rate u/A)."""
        return np.array([[1.0 / A]])

    return PortHamiltonianSystem(
        H=H,
        J=J,
        R=R,
        g=g_mat,
        n_states=1,
        n_inputs=1,
        grad_H=grad_H,
    )


def mass_spring_damper(
    m: float = 1.0,
    k: float = 1.0,
    c: float = 0.1,
) -> PortHamiltonianSystem:
    """
    Mass-spring-damper system (canonical mechanical PHS).

    State: x = [q, p] (position, momentum)
    Input: u = [F] (external force)
    Energy: H(q, p) = (1/2) k q² + (1/2) p²/m (potential + kinetic)

    Dynamics:
        ẋ = [J - R] ∇H + g u

    where:
        J = [[0, 1], [-1, 0]] (canonical symplectic form)
        R = [[0, 0], [0, c]] (damping on momentum)
        g = [[0], [1]] (force acts on momentum)
        ∇H = [k q, p/m]

    Args:
        m: Mass (kg)
        k: Spring constant (N/m)
        c: Damping coefficient (N·s/m)

    Returns:
        PortHamiltonianSystem for mass-spring-damper

    Example:
        >>> sys = mass_spring_damper()
        >>> x = np.array([1.0, 0.0])  # Displaced, at rest
        >>> u = np.array([0.0])
        >>> dx = sys.dynamics(x, u)
        >>> # Position unchanged (p=0), momentum decreases (restoring force)
    """

    def H(x: npt.NDArray[np.floating]) -> float:
        """Total energy: (1/2) k q² + (1/2) p²/m."""
        q, p = x[0], x[1]
        return float(0.5 * k * q**2 + 0.5 * p**2 / m)

    def grad_H(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Gradient: [k q, p/m]."""
        q, p = x[0], x[1]
        return np.array([k * q, p / m])

    def J(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Canonical symplectic form."""
        return np.array([[0.0, 1.0], [-1.0, 0.0]])

    def R(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Damping on momentum."""
        return np.array([[0.0, 0.0], [0.0, c]])

    def g_mat(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Force acts on momentum."""
        return np.array([[0.0], [1.0]])

    return PortHamiltonianSystem(
        H=H,
        J=J,
        R=R,
        g=g_mat,
        n_states=2,
        n_inputs=1,
        grad_H=grad_H,
    )


def dc_motor(
    L: float = 0.5,
    inertia: float = 0.01,
    Re: float = 1.0,
    b: float = 0.1,
    K: float = 0.5,
) -> PortHamiltonianSystem:
    """
    DC motor as a multi-domain (electrical + mechanical) port-Hamiltonian system.

    Reference: van der Schaft & Jeltsema (2014), "Port-Hamiltonian Systems
    Theory: An Introductory Overview", Example 2.5, Eq. (2.30).

    State, ports and energy::

        x = [phi, p]
            phi - inductor flux-linkage (Wb), electrical energy store
            p   - rotor angular momentum (kg·m²/s), mechanical energy store
        u = [V]     applied voltage
        y = I       armature current
        H(phi, p) = phi² / (2 L) + p² / (2 inertia)

    Dynamics (Eq. 2.30)::

        [phi_dot]   ([ 0  -K ]   [Re  0 ]) [phi/L]   [1]
        [ p_dot ] = ([ K   0 ] - [ 0  b ]) [ p/J ] + [0] V
        y = [1 0] grad_H = phi / L

    Structure::

        J = [[0, -K], [K, 0]]   skew-symmetric (the gyrator couples the
                                electrical and mechanical domains)
        R = diag(Re, b)         PSD: armature resistance and viscous friction
        g = [[1], [0]]          voltage drives the electrical state

    With V = 0 the stored energy is non-increasing (passivity by construction).

    Args:
        L: Armature inductance (H)
        inertia: Rotor moment of inertia (kg·m²)
        Re: Armature resistance (ohm)
        b: Viscous friction coefficient (N·m·s)
        K: Motor/gyrator constant (N·m/A = V·s)

    Returns:
        PortHamiltonianSystem for the DC motor.

    Example:
        >>> motor = dc_motor()
        >>> x = np.array([1.0, 0.0])   # some flux, rotor at rest
        >>> u = np.array([0.0])        # no applied voltage
        >>> dx = motor.dynamics(x, u)
        >>> motor.energy(x) > 0
        True
    """

    def H(x: npt.NDArray[np.floating]) -> float:
        """Total energy: magnetic phi²/(2L) + kinetic p²/(2 inertia)."""
        phi, p = x[0], x[1]
        return float(0.5 * phi**2 / L + 0.5 * p**2 / inertia)

    def grad_H(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Gradient: [phi/L, p/inertia] = [current I, angular velocity omega]."""
        phi, p = x[0], x[1]
        return np.array([phi / L, p / inertia])

    def J(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Gyrator coupling (skew-symmetric)."""
        return np.array([[0.0, -K], [K, 0.0]])

    def R(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Dissipation: armature resistance Re and viscous friction b."""
        return np.array([[Re, 0.0], [0.0, b]])

    def g_mat(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Voltage acts on the electrical (flux) state."""
        return np.array([[1.0], [0.0]])

    return PortHamiltonianSystem(
        H=H,
        J=J,
        R=R,
        g=g_mat,
        n_states=2,
        n_inputs=1,
        grad_H=grad_H,
    )


def pumped_hydro(
    A_u: float = 5.0e4,
    A_l: float = 5.0e6,
    z_u: float = 300.0,
    R_penstock: float = 5.0e8,
    g: float = 9.81,
    rho: float = 1000.0,
) -> PortHamiltonianSystem:
    """Pumped-hydro energy storage as a two-reservoir port-Hamiltonian system.

    Pumped hydro is the dominant grid-scale storage technology (~95% of the
    world's installed long-duration storage). Two reservoirs exchange water
    through a reversible pump-turbine; energy is stored as gravitational
    potential energy. Unlike the water tank — whose open drain *dissipates*
    energy — the connection here is a *controlled, reversible* power port, so the
    store is conservative: this is the white-box guarantee a degradation
    (grey-box) model cannot offer.

    State and ports::

        x = [V_u, V_l]   reservoir volumes (m^3), upper and lower
        u = [q]          commanded pump-turbine flow (m^3/s); q > 0 pumps
                         water up (charging), q < 0 generates (discharging)

    Energy, taken as gravitational potential about the lower datum, and its
    gradient, which is the pressure head at each free surface::

        H       = rho g [ z_u V_u + V_u^2 / (2 A_u) + V_l^2 / (2 A_l) ]
        grad_H  = rho g [ z_u + V_u/A_u , V_l/A_l ]

    Structure::

        J = 0                         no lossless internal circulation
        R = (1/R_penstock) [[1, -1], [-1, 1]]
                                      penstock conductance (graph-Laplacian, PSD):
                                      with the valve open and the pump off, water
                                      runs downhill and the head difference is
                                      dissipated -- passivity. Default R_penstock is
                                      large, i.e. a near-lossless store.
        g = [[1], [-1]]               the pump-turbine moves water between reservoirs.

    With the pump off the stored energy can only decrease (dH/dt <= 0); as
    R_penstock -> inf it is exactly conserved (a perfect store). Round-trip losses
    in a real plant come from the pump/turbine conversion efficiency, applied at the
    power port (see the worked example), not from the stored energy decaying.

    Args:
        A_u: Upper reservoir surface area (m^2).
        A_l: Lower reservoir surface area (m^2); large => near-constant tailwater.
        z_u: Elevation of the upper reservoir base above the lower datum (m).
        R_penstock: Hydraulic resistance of the (open) penstock (Pa*s/m^3).
        g: Gravitational acceleration (m/s^2).
        rho: Water density (kg/m^3).

    Returns:
        PortHamiltonianSystem for the pumped-hydro store.

    Example:
        >>> plant = pumped_hydro()
        >>> x = np.array([1.0e6, 1.0e7])   # some water up top
        >>> plant.energy(x) > 0
        True
        >>> float(plant.power_balance(x, np.array([0.0]))["dH_dt"]) <= 1e-6
        True
    """

    def H(x: npt.NDArray[np.floating]) -> float:
        """Gravitational potential energy of both reservoirs (J)."""
        v_u, v_l = x[0], x[1]
        return float(rho * g * (z_u * v_u + v_u**2 / (2.0 * A_u) + v_l**2 / (2.0 * A_l)))

    def grad_H(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Pressure head at each free surface: rho g x surface elevation."""
        v_u, v_l = x[0], x[1]
        return np.array([rho * g * (z_u + v_u / A_u), rho * g * (v_l / A_l)])

    def J(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """No lossless circulation."""
        return np.zeros((2, 2))

    def R(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Penstock conductance (graph-Laplacian, positive semidefinite)."""
        c = 1.0 / R_penstock
        return np.array([[c, -c], [-c, c]])

    def g_mat(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Pump-turbine: +flow into the upper reservoir, -flow out of the lower."""
        return np.array([[1.0], [-1.0]])

    return PortHamiltonianSystem(
        H=H,
        J=J,
        R=R,
        g=g_mat,
        n_states=2,
        n_inputs=1,
        grad_H=grad_H,
    )


def heat_exchanger(
    UA: float = 4.0e4,
    C_hot: float = 5.0e5,
    C_cold: float = 8.0e5,
    T_ref: float = 300.0,
) -> ModulatedIPHS:
    """Counter-flow heat exchanger as an irreversible port-Hamiltonian system.

    Heat exchangers are named in this package's own scope statement and were not
    in the catalogue. They are also the cleanest small example of why the
    irreversible structure exists: conduction between two bodies **conserves
    energy and produces entropy**, and a model that puts it in ``R`` instead
    destroys the energy — a first-law violation that produces a perfectly smooth,
    perfectly plausible temperature curve.

    State: ``x = [S_h, S_c]`` — the entropies of the hot-side and cold-side
    hold-ups (J/K), measured from the state at ``T_ref``.
    Input: ``u = [σ_h, σ_c]`` — entropy flows carried in by the two streams
    (W/K); ``u_i = Q̇_i / T_i`` for a stream delivering ``Q̇_i`` watts.
    Output: ``y = [T_h, T_c]`` — the two temperatures, so ``yᵀu`` is the heat
    power crossing the boundary.

    Energy and its gradient:

        T_i(x) = T_ref · exp(S_i / C_i)
        H(x)   = C_h (T_h − T_ref) + C_c (T_c − T_ref)
        ∇H     = (T_h, T_c)

    Structure — the modulated form, because that is what conduction is:

        J = [[0, −1], [1, 0]]                       skew: heat leaves one, enters the other
        γ(x) = UA (T_h − T_c) / (T_h T_c)           Fourier's law, as a modulation
        ẋ = γ J ∇H = (−Q̇/T_h, +Q̇/T_c),  Q̇ = UA (T_h − T_c)

    so with the ports closed ``dH/dt = ∇Hᵀ γJ ∇H = 0`` exactly — energy moves and
    is not lost — while the entropy production

        σ = Q̇ (1/T_c − 1/T_h) ≥ 0

    is non-negative whichever body is hotter, and zero only at equality. Both are
    checked by :meth:`~otwin.model.ModulatedIPHS.check_structure`.

    **Scope.** This is a lumped two-node model: it captures the approach to
    thermal equilibrium and the entropy cost of getting there. It is not a
    distributed model and will not reproduce a temperature profile along the
    tube; for the steady-state duty of a real exchanger use
    :func:`effectiveness_ntu`. Fouling is not here either — it has no energy
    function and no port, so it belongs in an empirical law; see
    :func:`otwin.model.kern_seaton_fouling`.

    Args:
        UA: Overall heat-transfer coefficient times area (W/K).
        C_hot: Thermal capacity of the hot-side hold-up (J/K).
        C_cold: Thermal capacity of the cold-side hold-up (J/K).
        T_ref: Reference temperature for the entropy datum (K).

    Returns:
        A :class:`~otwin.model.ModulatedIPHS` for the exchanger.

    Example:
        >>> hx = heat_exchanger()
        >>> x = np.array([1.0e5, -1.0e5])          # hot side hot, cold side cold
        >>> report = hx.check_structure(x)
        >>> report["energy_conserved"][0]           # first law, exactly
        True
        >>> report["sigma_nonneg"][0]               # second law, structurally
        True
        >>> bool(hx.entropy_production(x) > 0)      # and strictly positive here
        True
        >>> bool(hx.entropy_production(np.zeros(2)) == 0.0)   # at equilibrium, zero
        True
    """
    if UA <= 0 or C_hot <= 0 or C_cold <= 0 or T_ref <= 0:
        raise ValueError("UA, C_hot, C_cold and T_ref must all be positive")

    caps = np.array([C_hot, C_cold], dtype=float)
    J_hx = np.array([[0.0, -1.0], [1.0, 0.0]])

    def temperatures(x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        return T_ref * np.exp(np.asarray(x, dtype=float) / caps)

    def gamma(x: npt.NDArray[np.floating]) -> float:
        t_h, t_c = temperatures(x)
        return float(UA * (t_h - t_c) / (t_h * t_c))

    return ModulatedIPHS(
        H=lambda x: float(np.dot(caps, temperatures(x) - T_ref)),
        S=lambda x: float(x[0] + x[1]),
        J=lambda x: J_hx,
        gamma=gamma,
        g=lambda x: np.eye(2),
        n_states=2,
        n_inputs=2,
        grad_H=temperatures,
        grad_S=lambda x: np.ones(2),
    )


def effectiveness_ntu(
    UA: float,
    C_hot: float,
    C_cold: float,
    flow: str = "counter",
) -> float:
    """Heat-exchanger effectiveness ε by the ε-NTU method.

    The steady-state companion to :func:`heat_exchanger`: the fraction of the
    thermodynamically maximum duty that an exchanger of a given size actually
    delivers, ``Q̇ = ε · C_min · (T_h,in − T_c,in)``. This is the quantity that
    degrades as a unit fouls, and the one a cleaning decision is made on.

    Args:
        UA: Overall heat-transfer coefficient times area (W/K). For a fouled
            unit this is ``1 / (1/U_clean + R_f) · A``; see
            :func:`kern_seaton_fouling`.
        C_hot: Hot-stream capacity rate ``ṁ·c_p`` (W/K).
        C_cold: Cold-stream capacity rate (W/K).
        flow: ``"counter"``, ``"parallel"`` or ``"evaporator"`` (one stream
            changing phase, i.e. ``C_max → ∞``).

    Returns:
        Effectiveness in (0, 1]. It saturates to exactly 1.0 in floating point
        at large NTU, which is the correct asymptote: an infinitely large
        exchanger brings the outlet to the other stream's inlet temperature.

    Raises:
        ValueError: On a non-positive capacity rate or an unknown ``flow``.

    Example:
        >>> round(effectiveness_ntu(4.0e4, 1.44e4, 5.0e4), 4)
        0.8974
        >>> # Counter-flow beats parallel flow at the same size, always.
        >>> counter = effectiveness_ntu(4.0e4, 1.44e4, 5.0e4)
        >>> parallel = effectiveness_ntu(4.0e4, 1.44e4, 5.0e4, flow="parallel")
        >>> bool(counter > parallel)
        True
    """
    if UA <= 0 or C_hot <= 0 or C_cold <= 0:
        raise ValueError("UA and both capacity rates must be positive")
    c_min, c_max = (C_hot, C_cold) if C_hot <= C_cold else (C_cold, C_hot)
    ntu = UA / c_min
    ratio = c_min / c_max

    if flow == "evaporator" or ratio < 1e-12:
        return float(1.0 - np.exp(-ntu))
    if flow == "parallel":
        return float((1.0 - np.exp(-ntu * (1.0 + ratio))) / (1.0 + ratio))
    if flow != "counter":
        raise ValueError(
            f"flow must be 'counter', 'parallel' or 'evaporator', got {flow!r}"
        )
    if abs(ratio - 1.0) < 1e-12:
        return float(ntu / (1.0 + ntu))
    num = 1.0 - np.exp(-ntu * (1.0 - ratio))
    return float(num / (1.0 - ratio * np.exp(-ntu * (1.0 - ratio))))


def kern_seaton_fouling(
    R_inf: float = 8.0e-4,
    tau_days: float = 260.0,
    U_clean: float = 800.0,
) -> "FoulingLaw":
    """Asymptotic fouling resistance over time (Kern–Seaton).

    Deposition and removal reach a balance, so the fouling resistance approaches
    a plateau rather than growing without bound:

        R_f(t) = R_∞ (1 − exp(−t/τ))

    Returned as an :class:`~otwin.interfaces.EmpiricalLawModel`, not a
    port-Hamiltonian system, and the distinction is not bookkeeping. Fouling has
    no conserved energy and no port through which power flows; writing it as an
    energy balance is the modelling error this package's scope note warns about.
    What it has instead is a trend law with two estimated parameters and a
    residual — and from there the workflow is identical.

    **The identifiability trap, stated because it bites.** ``τ`` is only
    identifiable from a record longer than ``τ``. Fitted to 180 days of a
    260-day process, ``R_∞`` comes out low — the fit cannot see the plateau it
    is extrapolating to — and the cleaning date it implies is late. Check the
    span of your data against the fitted ``τ`` before believing either.

    Args:
        R_inf: Asymptotic fouling resistance (m²K/W).
        tau_days: Time constant (days).
        U_clean: Clean overall heat-transfer coefficient (W/m²K), used to turn
            the resistance into a cleanliness factor.

    Returns:
        A :class:`FoulingLaw`.

    Example:
        >>> law = kern_seaton_fouling()
        >>> law.param_names
        ('R_inf', 'tau_days')
        >>> import numpy as np
        >>> cf = law.cleanliness(np.array([0.0, 260.0, 1e4]))
        >>> bool(cf[0] == 1.0 and cf[1] < 1.0 and cf[2] < cf[1])
        True
        >>> round(float(law.law(np.array([260.0]))[0]), 6)   # 1 - 1/e of R_inf
        0.000506
    """
    return FoulingLaw(R_inf=R_inf, tau_days=tau_days, U_clean=U_clean)


class FoulingLaw:
    """Kern–Seaton fouling as an empirical trend law.

    Satisfies :class:`otwin.interfaces.EmpiricalLawModel`: it has ``law`` and
    ``param_names`` and deliberately no ``rhs``, because a fade law has no state
    derivative and a stub returning zeros would be exactly the conceptual error
    the protocol exists to prevent.

    Attributes:
        R_inf: Asymptotic fouling resistance (m²K/W).
        tau_days: Time constant (days).
        U_clean: Clean overall heat-transfer coefficient (W/m²K).
    """

    def __init__(self, R_inf: float, tau_days: float, U_clean: float) -> None:
        if R_inf < 0 or tau_days <= 0 or U_clean <= 0:
            raise ValueError("R_inf must be >= 0, tau_days and U_clean must be > 0")
        self.R_inf = float(R_inf)
        self.tau_days = float(tau_days)
        self.U_clean = float(U_clean)

    @property
    def param_names(self) -> tuple[str, ...]:
        """Names of the estimated parameters, in a stable order."""
        return ("R_inf", "tau_days")

    def law(
        self,
        t: npt.NDArray[np.floating],
        params: dict[str, float] | None = None,
    ) -> npt.NDArray[np.floating]:
        """Fouling resistance ``R_f(t)`` in m²K/W, with ``t`` in days."""
        p = params or {}
        r_inf = float(p.get("R_inf", self.R_inf))
        tau = float(p.get("tau_days", self.tau_days))
        return r_inf * (1.0 - np.exp(-np.asarray(t, dtype=float) / tau))

    def cleanliness(
        self,
        t: npt.NDArray[np.floating],
        params: dict[str, float] | None = None,
    ) -> npt.NDArray[np.floating]:
        """Cleanliness factor ``U(t) / U_clean`` — 1 when clean, falling as it fouls.

        This is the quantity worth forecasting: it is bounded, dimensionless, and
        a cleaning threshold is stated on it directly.
        """
        return 1.0 / (1.0 + self.U_clean * self.law(t, params))

    def U(
        self,
        t: npt.NDArray[np.floating],
        params: dict[str, float] | None = None,
    ) -> npt.NDArray[np.floating]:
        """Overall heat-transfer coefficient at time ``t`` (W/m²K)."""
        return self.U_clean * self.cleanliness(t, params)
