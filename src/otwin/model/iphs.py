"""Irreversible Port-Hamiltonian Systems (IPHS) with entropy production.

Two structures are in use in the literature and both are here, because a model
written in one does not fit the other without a derivation:

:class:`IrreversiblePHS`
    The additive coupling ``ẋ = (J − R)∇H + g u + L(x)∇S(x)``, with entropy
    production ``σ = ∇Sᵀ L ∇S`` guaranteed non-negative by ``L ⪰ 0``.

:class:`ModulatedIPHS`
    The Ramírez–Maschke–Sbarbaro form ``ẋ = γ(x)·J ∇H + g u``, where a scalar
    *modulating function* multiplies a skew interconnection. Energy conservation
    is structural for the same reason it is in a plain PHS — ``γJ`` is still
    skew — and the second law is a condition on ``γ``, checked rather than
    assumed. This is the form a non-isothermal reactor is naturally written in:
    ``γ = r/T`` and ``σ = A·r/T`` with ``A`` the chemical affinity.

Reach for the second through :meth:`IrreversiblePHS.from_modulated`, which is
where someone arriving from the RMS papers will look.
"""

from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt

from .phs import PortHamiltonianSystem


class IrreversiblePHS:
    """
    Irreversible Port-Hamiltonian System with entropy production.

    Extension of PHS to include thermodynamic irreversibility:
        ẋ = (J(x) − R(x)) ∇H(x) + g(x) u + L(x) ∇S(x)
        y = g(x)^T ∇H(x)
        σ(x) ≥ 0  (entropy production, second law)

    where:
        - S(x): Entropy/availability function
        - L(x): Irreversible coupling matrix (must be PSD)
        - σ(x) = ∇S^T L ∇S ≥ 0 (entropy production; holds iff L is PSD)

    The second-law guarantee σ ≥ 0 requires L(x) ⪰ 0. This is *enforced*, not
    just assumed: with ``validate=True`` (default) L is checked on first use and a
    ValueError is raised if it is not PSD. Use ``check_structure`` /
    ``check_entropy_production`` to inspect the guarantees explicitly.

    Args:
        H: Energy (internal energy or Hamiltonian)
        S: Entropy/availability function
        J: Interconnection (skew-symmetric)
        R: Dissipation (PSD)
        L: Irreversible coupling (must ensure σ ≥ 0)
        g: Input map
        n_states: Number of states
        n_inputs: Number of inputs
        grad_H: Optional analytic ``∇H``. Without it the gradient is finite-
            differenced, which on a stiff Hamiltonian is the difference between
            an energy drift at 1e-13 and one at 1e-6 — the check this class
            exists to make, quietly weakened.
        grad_S: Optional analytic ``∇S``. Same argument.
        validate: Check ``L(x) ⪰ 0`` on every dynamics and entropy call.

    Example:
        >>> # Simple 1D irreversible system
        >>> H = lambda x: 0.5 * x[0]**2
        >>> S = lambda x: -x[0]  # Entropy increases as energy decreases
        >>> J = lambda x: np.zeros((1, 1))
        >>> R = lambda x: np.array([[0.1]])
        >>> L = lambda x: np.array([[0.05]])
        >>> g = lambda x: np.array([[1.0]])
        >>> iphs = IrreversiblePHS(H, S, J, R, L, g, 1, 1)
    """

    def __init__(
        self,
        H: Callable[[npt.NDArray[np.floating]], float],
        S: Callable[[npt.NDArray[np.floating]], float],
        J: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        R: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        L: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        g: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        n_states: int,
        n_inputs: int,
        validate: bool = True,
        grad_H: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]]
        | None = None,
        grad_S: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]]
        | None = None,
    ) -> None:
        # Use PHS for reversible part
        self.phs = PortHamiltonianSystem(H, J, R, g, n_states, n_inputs, grad_H=grad_H)

        self.S = S
        self.L = L
        self._grad_S = grad_S
        self.n_states = n_states
        self.n_inputs = n_inputs
        # The second-law guarantee σ = ∇Sᵀ L ∇S ≥ 0 holds only if L is PSD.
        # Enforced rather than documented: when `validate`, the irreversible
        # coupling is checked on EVERY dynamics/entropy call, not just the first.
        self.validate = validate

    @staticmethod
    def from_modulated(
        H: Callable[[npt.NDArray[np.floating]], float],
        S: Callable[[npt.NDArray[np.floating]], float],
        J: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        gamma: Callable[[npt.NDArray[np.floating]], float],
        g: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        n_states: int,
        n_inputs: int,
        **kwargs: Any,
    ) -> "ModulatedIPHS":
        """Build the Ramírez–Maschke–Sbarbaro form ``ẋ = γ(x)·J∇H + g u``.

        Most of the irreversible-PHS literature — including the paper this
        package cites — writes the structure with a scalar modulating function
        rather than the additive ``L∇S`` coupling this class implements. The two
        describe the same physics for a given system, but converting between them
        is a derivation, not a change of notation, and doing it by hand is where
        the time goes.

        Returns a :class:`ModulatedIPHS`; see that class for the guarantees.

        Example:
            >>> import numpy as np
            >>> react = IrreversiblePHS.from_modulated(
            ...     H=lambda x: float(x[0] + x[1]),
            ...     S=lambda x: float(x[1]),
            ...     J=lambda x: np.array([[0.0, -1.0], [1.0, 0.0]]),
            ...     gamma=lambda x: 1.0,
            ...     g=lambda x: np.zeros((2, 1)),
            ...     n_states=2, n_inputs=1,
            ...     grad_H=lambda x: np.ones(2), grad_S=lambda x: np.array([0.0, 1.0]),
            ... )
            >>> type(react).__name__
            'ModulatedIPHS'
            >>> bool(abs(react.check_energy_conservation(np.array([1.0, 2.0]))[1]) < 1e-12)
            True
        """
        return ModulatedIPHS(
            H=H,
            S=S,
            J=J,
            gamma=gamma,
            g=g,
            n_states=n_states,
            n_inputs=n_inputs,
            **kwargs,
        )

    def entropy(self, x: npt.NDArray[np.floating]) -> float:
        """Evaluate entropy S(x)."""
        return float(self.S(x))

    def grad_S(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Compute gradient of entropy ∇S(x)."""
        if self._grad_S is not None:
            return self._grad_S(x)
        from otwin.model.linalg import numerical_gradient

        return numerical_gradient(self.S, x)

    def _ensure_valid_L(self, x: npt.NDArray[np.floating], tol: float = 1e-8) -> None:
        """Validate that L(x) is PSD (the second-law prerequisite); raise if not.

        Checked on **every** call, not cached. An earlier version set a
        ``_validated`` flag on first success and returned early forever after,
        which meant a state-modulated ``L`` was verified at exactly one point in
        state space. A model that is PSD at its initial condition and indefinite
        later then produced σ < 0 and raised nothing — while the README claimed
        the second law was enforced rather than documented. The eigenvalue
        computation is cheap next to the gradient work already happening here.
        """
        if not self.validate:
            return
        from otwin.model.linalg import check_psd

        is_psd, min_eig = check_psd(self.L(x), tol)
        if not is_psd:
            raise ValueError(
                "Irreversible coupling L(x) must be positive semidefinite to "
                f"guarantee entropy production σ ≥ 0 (min eigenvalue {min_eig:.3e}). "
                "Fix L or construct with validate=False to bypass (not recommended)."
            )

    def check_structure(
        self, x: npt.NDArray[np.floating], tol: float = 1e-10
    ) -> dict[str, tuple[bool, float]]:
        """Check all structural properties at ``x``.

        Returns J skew-symmetry, R PSD, L PSD, and σ ≥ 0 — the latter two are the
        irreversible (second-law) guarantees that the base PHS does not cover.
        """
        from otwin.model.linalg import check_psd

        base = self.phs.check_structure(x, tol)
        l_psd = check_psd(self.L(x), tol)
        is_nonneg, sigma = self.check_entropy_production(x, tol)
        du_dt = self.check_energy_conservation(x)
        return {
            "J_skew": base["J_skew"],
            "R_psd": base["R_psd"],
            "L_psd": l_psd,
            "sigma_nonneg": (is_nonneg, sigma),
            "energy_conserved": du_dt,
        }

    def check_energy_conservation(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating] | None = None,
        tol: float = 1e-8,
    ) -> tuple[bool, float]:
        """Return ``(is_conserved, dU_dt)`` — the **first law**, with u = 0.

        A true irreversible port-Hamiltonian system moves energy between stores
        without creating or destroying it: heat conduction between two bodies
        conserves total energy and produces entropy. Putting that process in
        ``R`` instead destroys the energy, which is a first-law violation that
        nevertheless produces a smooth and plausible curve.

        This check existed nowhere until now, while both the README and the
        package docstring asserted ``dU/dt = 0``. It is reported rather than
        raised, because a model with a genuine external power port legitimately
        has ``dU/dt = yᵀu ≠ 0``; pass ``u = 0`` to test the closed system.
        """
        if u is None:
            u = np.zeros(self.phs.n_inputs)
        du_dt = float(np.dot(self.grad_H(x), self.dynamics(x, u, 0.0)))
        return abs(du_dt) <= tol, du_dt

    def check_entropy_production(
        self, x: npt.NDArray[np.floating], tol: float = 1e-10
    ) -> tuple[bool, float]:
        """Return ``(is_nonneg, sigma)`` for the entropy production at ``x``.

        Validates ``L`` first. Previously only ``dynamics()`` did, so a caller who
        checked σ and nothing else could read a clean result from a model whose
        coupling was indefinite.
        """
        self._ensure_valid_L(x)
        sigma = self.entropy_production(x)
        return sigma >= -tol, sigma

    def dynamics(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating],
        t: float = 0.0,
    ) -> npt.NDArray[np.floating]:
        """
        Compute state derivative: ẋ = (J - R) ∇H + g u + L ∇S.

        The irreversible term L ∇S captures entropy production.
        """
        self._ensure_valid_L(x)

        # Reversible + dissipative part
        dx_phs = self.phs.dynamics(x, u, t)

        # Irreversible part
        grad_S = self.grad_S(x)
        L_mat = self.L(x)
        dx_irreversible = L_mat @ grad_S

        return dx_phs + dx_irreversible

    # ----------------------------------------------------------------------
    # Contract surface
    #
    # The contract (otwin.interfaces.IrreversibleModel) extends PortHamiltonianModel,
    # so an irreversible system must also expose H, J, R and g. Those live on
    # the reversible sub-system, so they are forwarded here rather than
    # duplicated: there must be exactly one definition of the energy structure.
    # ----------------------------------------------------------------------

    def H(self, x: npt.NDArray[np.floating]) -> float:
        """Energy stored at ``x``. Forwarded to the reversible part."""
        return float(self.phs.H(x))

    def J(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Interconnection matrix. Forwarded to the reversible part."""
        return self.phs.J(x)

    def R(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Dissipation matrix. Forwarded to the reversible part."""
        return self.phs.R(x)

    def g(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Port map. Forwarded to the reversible part."""
        return self.phs.g(x)

    def grad_H(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Energy gradient. Forwarded to the reversible part."""
        return self.phs.grad_H(x)

    def rhs(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating],
        t: float = 0.0,
    ) -> npt.NDArray[np.floating]:
        """Right-hand side of the dynamics. The contract name for :meth:`dynamics`."""
        return self.dynamics(x, u, t)

    def observe(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating] | None = None,
        t: float = 0.0,
    ) -> npt.NDArray[np.floating]:
        """Observation map ``y = gᵀ ∇H``. The contract name for the port output."""
        return self.phs.output(x)

    def entropy_production(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating] | None = None,
        t: float = 0.0,
    ) -> float:
        """
        Compute entropy production: σ = ∇S^T L ∇S.

        Must be non-negative (second law).

        Returns:
            Entropy production rate (should be ≥ 0)
        """
        grad_S = self.grad_S(x)
        L_mat = self.L(x)

        sigma = float(grad_S @ L_mat @ grad_S)
        return sigma


class ModulatedIPHS:
    """Irreversible PHS in the modulated (Ramírez–Maschke–Sbarbaro) form.

        ẋ = γ(x)·J(x) ∇H(x) − R(x) ∇H(x) + g(x) u
        y = g(x)ᵀ ∇H(x)
        σ(x) = ∇S(x)ᵀ · γ(x)·J(x)∇H(x) ≥ 0

    A scalar *modulating function* ``γ`` multiplies a skew interconnection. This
    is not a special case of :class:`IrreversiblePHS`'s ``L(x)∇S(x)`` coupling
    and it is not a different notation for it: getting from one to the other is
    a derivation, which is why both are here.

    **What the structure buys, and what it does not.** ``γJ`` is skew for any
    scalar ``γ``, so with ``R = 0`` and the ports closed ``dH/dt = ∇Hᵀ γJ ∇H = 0``
    identically — the first law is structural, exactly as in a plain PHS. The
    second law is *not*: nothing about a skew matrix forces ``∇Sᵀ ẋ ≥ 0``. In the
    reactor case it holds because ``γ = r/T`` is built from the affinity so that
    ``sign(r) = sign(A)``, and that is a property of the model, not of the form.
    With ``validate=True`` (default) ``σ`` is therefore evaluated and checked on
    every dynamics call, which is the same bargain :class:`IrreversiblePHS`
    strikes with ``L ⪰ 0``.

    Args:
        H: Energy (internal energy or Hamiltonian).
        S: Entropy function. May be a coordinate, e.g. ``lambda x: x[2]``.
        J: Skew interconnection, *before* modulation.
        gamma: Modulating function ``γ(x) -> float``.
        g: Input map.
        n_states: Number of states.
        n_inputs: Number of inputs.
        R: Optional dissipation, PSD. Defaults to zero.
        grad_H: Optional analytic ``∇H``.
        grad_S: Optional analytic ``∇S``.
        validate: Check ``σ(x) ≥ 0`` on every dynamics and entropy call.

    Example:
        Heat conduction between two bodies, the textbook irreversible system.
        States are the two entropies, ``∇H = (T₁, T₂)``, and
        ``γ = λ(T₁ − T₂)/(T₁T₂)`` gives Fourier's law:

        >>> import numpy as np
        >>> C, lam, Tref = 100.0, 2.0, 300.0
        >>> temps = lambda x: np.array([Tref * np.exp(x[0] / C),
        ...                             Tref * np.exp(x[1] / C)])
        >>> J = np.array([[0.0, -1.0], [1.0, 0.0]])
        >>> def gamma(x):
        ...     T1, T2 = temps(x)
        ...     return lam * (T1 - T2) / (T1 * T2)
        >>> cond = ModulatedIPHS(
        ...     H=lambda x: C * (temps(x)[0] + temps(x)[1] - 2 * Tref),
        ...     S=lambda x: float(x[0] + x[1]),
        ...     J=lambda x: J, gamma=gamma,
        ...     g=lambda x: np.zeros((2, 1)),
        ...     n_states=2, n_inputs=1,
        ...     grad_H=temps, grad_S=lambda x: np.ones(2),
        ... )
        >>> x = np.array([20.0, -20.0])          # body 1 hotter than body 2
        >>> bool(cond.entropy_production(x) > 0)  # heat flows, entropy is made
        True
        >>> bool(abs(cond.check_energy_conservation(x)[1]) < 1e-9)  # first law
        True
    """

    def __init__(
        self,
        H: Callable[[npt.NDArray[np.floating]], float],
        S: Callable[[npt.NDArray[np.floating]], float],
        J: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        gamma: Callable[[npt.NDArray[np.floating]], float],
        g: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]],
        n_states: int,
        n_inputs: int,
        R: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]] | None = None,
        grad_H: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]]
        | None = None,
        grad_S: Callable[[npt.NDArray[np.floating]], npt.NDArray[np.floating]]
        | None = None,
        validate: bool = True,
    ) -> None:
        zero_R = R if R is not None else (lambda x: np.zeros((n_states, n_states)))
        # The modulated interconnection is what the reversible sub-system sees,
        # so `phs` carries γJ and every structural check on it -- skew-symmetry
        # above all -- is a check on the matrix actually being integrated.
        self.phs = PortHamiltonianSystem(
            H,
            lambda x: float(gamma(x)) * np.asarray(J(x), dtype=float),
            zero_R,
            g,
            n_states,
            n_inputs,
            grad_H=grad_H,
        )
        self.S = S
        self.J_unmodulated = J
        self.gamma = gamma
        self._grad_S = grad_S
        self.n_states = n_states
        self.n_inputs = n_inputs
        self.validate = validate

    def entropy(self, x: npt.NDArray[np.floating]) -> float:
        """Evaluate entropy S(x)."""
        return float(self.S(x))

    def grad_S(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Compute gradient of entropy ∇S(x)."""
        if self._grad_S is not None:
            return self._grad_S(x)
        from otwin.model.linalg import numerical_gradient

        return numerical_gradient(self.S, x)

    def _irreversible_flow(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """The modulated term ``γ J ∇H`` alone, without ports or dissipation."""
        grad_h = self.phs.grad_H(x)
        return float(self.gamma(x)) * (
            np.asarray(self.J_unmodulated(x), dtype=float) @ grad_h
        )

    def entropy_production(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating] | None = None,
        t: float = 0.0,
    ) -> float:
        """Entropy production ``σ = ∇Sᵀ γ J ∇H``.

        The port contribution is excluded on purpose: entropy carried in through
        a port is not produced by the system, and adding it would let an open
        system report a non-negative σ while its internal process ran backwards.
        """
        return float(self.grad_S(x) @ self._irreversible_flow(x))

    def _ensure_second_law(self, x: npt.NDArray[np.floating], tol: float = 1e-8) -> None:
        """Check ``σ(x) ≥ 0``; raise if not.

        Checked on every call rather than cached, for the reason the additive
        form checks ``L`` on every call: ``γ`` is state-dependent, so a model
        that satisfies the second law at its initial condition can violate it
        later — which for a reaction is exactly what happens once the affinity
        changes sign.
        """
        if not self.validate:
            return
        sigma = self.entropy_production(x)
        if sigma < -tol:
            raise ValueError(
                "modulating function gamma(x) violates the second law at this state: "
                f"entropy production sigma = {sigma:.3e} < 0. In the RMS form sigma >= 0 "
                "is a property of gamma, not of the structure -- build the rate from the "
                "affinity so that sign(r) = sign(A), or construct with validate=False "
                "to bypass (not recommended)."
            )

    def dynamics(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating],
        t: float = 0.0,
    ) -> npt.NDArray[np.floating]:
        """State derivative ``ẋ = γ J ∇H − R ∇H + g u``."""
        self._ensure_second_law(x)
        return self.phs.dynamics(x, u, t)

    def check_structure(
        self, x: npt.NDArray[np.floating], tol: float = 1e-10
    ) -> dict[str, tuple[bool, float]]:
        """Check all structural properties at ``x``.

        Reports the same four keys as :meth:`IrreversiblePHS.check_structure` so
        the two forms can be checked by the same code, with ``L_psd`` replaced by
        ``gamma_finite``: there is no ``L`` here, and the second-law guarantee
        rests on ``σ`` instead.
        """
        base = self.phs.check_structure(x, tol)
        gam = float(self.gamma(x))
        sigma = self.entropy_production(x)
        return {
            "J_skew": base["J_skew"],
            "R_psd": base["R_psd"],
            "gamma_finite": (bool(np.isfinite(gam)), gam),
            "sigma_nonneg": (sigma >= -tol, sigma),
            "energy_conserved": self.check_energy_conservation(x),
        }

    def check_energy_conservation(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating] | None = None,
        tol: float = 1e-8,
    ) -> tuple[bool, float]:
        """Return ``(is_conserved, dU_dt)`` — the first law, with ``u = 0``."""
        if u is None:
            u = np.zeros(self.phs.n_inputs)
        du_dt = float(np.dot(self.grad_H(x), self.phs.dynamics(x, u, 0.0)))
        return abs(du_dt) <= tol, du_dt

    def check_entropy_production(
        self, x: npt.NDArray[np.floating], tol: float = 1e-10
    ) -> tuple[bool, float]:
        """Return ``(is_nonneg, sigma)`` for the entropy production at ``x``."""
        sigma = self.entropy_production(x)
        return sigma >= -tol, sigma

    # ------------------------------------------------------------------
    # Contract surface, forwarded to the reversible sub-system.
    # ------------------------------------------------------------------

    def H(self, x: npt.NDArray[np.floating]) -> float:
        """Energy stored at ``x``."""
        return float(self.phs.H(x))

    def J(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """The **modulated** interconnection ``γ(x)·J(x)``, which is what is integrated."""
        return self.phs.J(x)

    def R(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Dissipation matrix."""
        return self.phs.R(x)

    def g(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Port map."""
        return self.phs.g(x)

    def grad_H(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Energy gradient."""
        return self.phs.grad_H(x)

    def rhs(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating],
        t: float = 0.0,
    ) -> npt.NDArray[np.floating]:
        """Right-hand side of the dynamics. The contract name for :meth:`dynamics`."""
        return self.dynamics(x, u, t)

    def observe(
        self,
        x: npt.NDArray[np.floating],
        u: npt.NDArray[np.floating] | None = None,
        t: float = 0.0,
    ) -> npt.NDArray[np.floating]:
        """Observation map ``y = gᵀ ∇H``."""
        return self.phs.output(x)
