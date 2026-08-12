"""Irreversible Port-Hamiltonian Systems (IPHS) with entropy production."""

from collections.abc import Callable

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
    ) -> None:
        # Use PHS for reversible part
        self.phs = PortHamiltonianSystem(H, J, R, g, n_states, n_inputs)

        self.S = S
        self.L = L
        self.n_states = n_states
        self.n_inputs = n_inputs
        # The second-law guarantee σ = ∇Sᵀ L ∇S ≥ 0 holds only if L is PSD.
        # Enforced rather than documented: when `validate`, the irreversible
        # coupling is checked on EVERY dynamics/entropy call, not just the first.
        self.validate = validate

    def entropy(self, x: npt.NDArray[np.floating]) -> float:
        """Evaluate entropy S(x)."""
        return float(self.S(x))

    def grad_S(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Compute gradient of entropy ∇S(x)."""
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
    # otwin-base protocol surface
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
