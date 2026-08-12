"""Energy-consistent state correction for port-Hamiltonian twins.

The problem, in one paragraph
----------------------------

A port-Hamiltonian model is passive by construction: with no input, the stored
energy ``H(x)`` can only go down, because ``dH/dt = -∇Hᵀ R ∇H + yᵀu ≤ yᵀu``.
That guarantee is the reason the model is trustworthy outside its training data
— it cannot invent energy no matter how far you extrapolate. Then a Kalman
filter is bolted on, and every measurement update applies
``x⁺ = x⁻ + K·ν``, a jump chosen purely to reduce measurement error. Nothing in
the Kalman derivation knows about ``H``. On a noisy sample the jump routinely
lands uphill: the estimated flywheel spins faster, the estimated capacitor holds
more charge, the estimated tank holds more heat — with no input to have supplied
it. The model is passive; the estimator is not; and the combined twin, which is
what the user actually runs, is not passive either. The failure is silent,
because the state trajectory still looks plausible and the innovations still
look white.

The fix, in one paragraph
-------------------------

Put an energy meter on the correction. Over one sampling interval the ports
supply at most ``∫yᵀu dt``, approximated as ``yᵀu·dt``. Any correction whose
energy increase exceeds that budget has created energy out of nothing. When
that happens, scale the correction back — the correction *direction* is what
the innovation tells you and is worth keeping; the *magnitude* is what
overshoots. Apply ``x⁺ = x⁻ + α·K·ν`` with the largest ``α ∈ [0, 1]`` that
keeps the step inside the energy budget. If ``α = 1`` is already fine, nothing
happens, and the observer is exactly the EKF.

Reading the diagnostics
-----------------------

``alpha`` per step is the honest signal. Occasional dips below 1 are the
filter being caught doing something unphysical, which is the point. A clamp
that fires on most steps is *not* a success: it means the tuning is wrong,
almost always ``R_meas`` too small (the filter trusts a noisy sensor and takes
large jumps) or ``Q`` too large (the filter distrusts a model it should be
leaning on). Fix the covariances; do not let the clamp paper over them.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from .kalman import Array, ExtendedKalmanFilter, FilterResult, Jacobian, _symmetrise

__all__ = ["EnergyConsistentObserver", "EnergyFilterResult"]

EnergyFn = Callable[[npt.NDArray[np.floating]], float]


@dataclass
class EnergyFilterResult(FilterResult):
    """A :class:`~otwin.estimate.kalman.FilterResult` plus the energy audit.

    Args:
        alpha: Correction scale actually applied at each step, shape
            ``(n_steps,)``. ``1.0`` means the EKF correction was accepted whole.
        energy: ``H(x)`` after each update, shape ``(n_steps,)``.
        energy_created: Per step, the energy the *unclamped* EKF correction
            would have manufactured beyond what the ports supplied, shape
            ``(n_steps,)``. Zero on steps where the correction was benign, and
            zero at step 0, which is not energy-constrained.
        energy_injected: ``energy_created.sum()`` — the total the plain EKF
            would have added to a system that had no source for it.
    """

    alpha: Array = field(default_factory=lambda: np.empty(0, dtype=float))
    energy: Array = field(default_factory=lambda: np.empty(0, dtype=float))
    energy_created: Array = field(default_factory=lambda: np.empty(0, dtype=float))
    energy_injected: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        self.alpha = np.asarray(self.alpha, dtype=float)
        self.energy = np.asarray(self.energy, dtype=float)
        self.energy_created = np.asarray(self.energy_created, dtype=float)
        self.energy_injected = float(self.energy_injected)

    @property
    def clamp_rate(self) -> float:
        """Fraction of steps where the correction had to be scaled back.

        Above roughly 0.2 the covariances are misspecified — see the module
        docstring.
        """
        if self.alpha.size == 0:
            return 0.0
        return float(np.mean(self.alpha < 1.0))


class EnergyConsistentObserver(ExtendedKalmanFilter):
    """EKF whose measurement correction cannot manufacture energy.

    Each step runs the ordinary EKF prediction and computes the ordinary EKF
    correction ``δ = K·ν``. Before accepting it, the observer checks the energy
    balance over the interval:

    .. math::

        H(x^- + \\delta) - H(x^-) \\;\\le\\; y^{\\top}u \\, \\Delta t + \\varepsilon

    The right-hand side is the energy the environment actually delivered through
    the ports during the step. If the inequality holds, ``α = 1`` and this is an
    EKF, bit for bit. If it fails, ``α`` is reduced until it holds, and the
    scaled correction ``α·δ`` is applied instead.

    The correction is scaled, never rotated. The innovation still decides which
    way to move; only how far is negotiable. In the limit ``α → 0`` the observer
    falls back to open-loop simulation of a passive model, which is the correct
    conservative behaviour: trust the physics when the data asks for something
    the physics forbids.

    The covariance uses the *applied* gain ``αK``, not ``K``:
    ``P⁺ = (I − αKH)P⁻(I − αKH)ᵀ + α²K R_meas Kᵀ``. A clamped step really did
    absorb less information than an unclamped one, and reporting the unclamped
    covariance would leave the filter overconfident precisely when it has just
    been overruled.

    How ``α`` is found, and the one caveat:
        The feasible set ``{α ∈ [0, 1] : φ(α) ≤ 0}`` with
        ``φ(α) = H(x⁻ + αδ) − H(x⁻) − budget`` is found by scanning ``n_scan``
        equally spaced values of ``α``, taking the largest feasible grid point,
        and bisecting between it and the next (infeasible) grid point.

        **The caveat, stated plainly:** ``H`` is not required to be monotone or
        convex along ``δ``, so the feasible set need not be an interval. If a
        violating region is narrower than the grid spacing ``1/n_scan``, or if a
        feasible island sits entirely between two grid points, the scan can miss
        a larger feasible ``α`` and return a smaller one. The returned ``α`` is
        therefore always **safe** — the energy constraint is verified at the
        value that is actually applied — but it may be **conservative**. It is
        never unsafe, which is the direction that matters: the failure mode is a
        correction that is smaller than it could have been, not one that creates
        energy.

        For the common case of a quadratic energy, ``H(x) = ½xᵀMx`` with
        ``M ⪰ 0`` — every linear-storage electrical, mechanical and thermal
        element in :mod:`otwin.model.library` — ``φ`` is a convex parabola in
        ``α``, the feasible set is a genuine interval containing ``0``, and the
        returned ``α`` is exact to bisection tolerance. Raise ``n_scan`` if your
        ``H`` is strongly non-convex.

    What this costs you on an autonomous system:
        With ``u = 0`` the budget collapses to ``tol``, so **no upward
        correction is permitted at all**, however small. That is the literal
        and correct reading of passivity — with nothing connected to the ports
        there is no source for an energy increase — but it has a consequence
        worth stating before you meet it in production. If the estimate's energy
        starts *below* the plant's, the measurements can never lift it; only the
        dynamics can, and for a dissipative system the dynamics only push
        energy down. The estimator will track the shape of the trajectory and
        systematically under-report its amplitude.

        Three ways out, in order of preference. Initialise from a state whose
        energy is not below the plant's — an over-energetic prior is corrected
        freely, since every downward correction is inside budget. Model the
        disturbance you are actually seeing as an input and give it a port,
        which is the honest fix and restores a real budget. Or set ``tol`` to a
        small fraction of the system's energy scale, accepting a bounded leak of
        at most ``tol`` per step in exchange for a filter that can climb —
        quantify it as ``tol × n_steps`` and check that against the energy you
        care about resolving.

        The first sample is exempt (see :meth:`filter`), because conditioning a
        prior on its first measurement is initialisation, not evolution, and
        there is no elapsed interval over which a balance could have been
        broken.

        If even ``α = 0`` violates the budget, the budget itself was negative:
        the ports were *drawing* energy out during the step and the state should
        have fallen on its own. No correction can fix that, so ``α = 0`` is
        applied and the step is recorded as clamped. Persistent ``α = 0`` means
        the model and the plant disagree about the direction of power flow —
        check the sign convention on ``g``.

    Args:
        model: Port-Hamiltonian model exposing ``rhs``, ``observe`` and an
            energy function (``energy(x)`` as on
            :class:`~otwin.model.phs.PortHamiltonianSystem`, or ``H(x)``).
        Q: Process-noise covariance per step, shape ``(n, n)``.
        R_meas: Measurement-noise covariance, shape ``(m, m)``. Named
            ``R_meas`` because ``R`` is the dissipation matrix here.
        P0: Initial covariance, shape ``(n, n)``.
        x0: Initial state, shape ``(n,)``.
        jac_f: Optional analytic ``∂rhs/∂x``.
        jac_h: Optional analytic ``∂observe/∂x``.
        energy: Optional explicit energy function, overriding lookup on
            ``model``.
        port_output: Optional map ``(x, u, t) -> y_port`` giving the
            *collocated port* output used for the power term. Defaults to
            ``model.observe``, which is correct for a port-Hamiltonian system
            because its output ``y = gᵀ∇H`` is power-conjugate to ``u``. Supply
            this explicitly whenever your sensors measure something other than
            the port variable, otherwise ``yᵀu`` is not a power and the budget
            is meaningless.
        tol: Slack ``ε`` added to the budget, in energy units. Absorbs
            round-off in ``H``; keep it small relative to the energy scale of
            the system.
        n_scan: Grid resolution for the feasibility scan.
        n_bisect: Bisection iterations, giving ``2^-n_bisect`` resolution in
            ``α``.

    Attributes:
        energy_injected: Running total of energy the unclamped EKF would have
            created since the last :meth:`reset`.

    Example:
        >>> import numpy as np
        >>> from otwin.model.phs import PortHamiltonianSystem
        >>> H = lambda x: 0.5 * (x[0] ** 2 + x[1] ** 2)
        >>> phs = PortHamiltonianSystem(
        ...     H=H, J=lambda x: np.array([[0.0, 1.0], [-1.0, 0.0]]),
        ...     R=lambda x: np.diag([0.0, 0.2]), g=lambda x: np.array([[0.0], [1.0]]),
        ...     n_states=2, n_inputs=1, grad_H=lambda x: x.copy())
        >>> obs = EnergyConsistentObserver(
        ...     phs, Q=1e-6 * np.eye(2), R_meas=np.array([[0.25]]),
        ...     P0=np.eye(2), x0=np.array([1.0, 0.0]))
        >>> ts = np.linspace(0.0, 2.0, 41)
        >>> ys = np.full((41, 1), 3.0)        # sensor screaming "faster!"
        >>> res = obs.filter(ys, np.zeros((41, 1)), ts)
        >>> bool(np.all(np.diff(res.energy) <= 1e-9))   # never gains energy
        True
        >>> bool(res.alpha.min() < 1.0)                 # the clamp did fire
        True
    """

    def __init__(
        self,
        model: object,
        Q: Array,
        R_meas: Array,
        P0: Array,
        x0: Array | None = None,
        jac_f: Jacobian | None = None,
        jac_h: Jacobian | None = None,
        energy: EnergyFn | None = None,
        port_output: Callable[[Array, Array, float], Array] | None = None,
        tol: float = 1e-12,
        n_scan: int = 32,
        n_bisect: int = 60,
    ) -> None:
        if n_scan < 1:
            raise ValueError(f"n_scan must be >= 1, got {n_scan}")
        if n_bisect < 1:
            raise ValueError(f"n_bisect must be >= 1, got {n_bisect}")
        self._energy_fn = self._resolve_energy(model, energy)
        self._port_fn = port_output
        self.tol = float(tol)
        self.n_scan = int(n_scan)
        self.n_bisect = int(n_bisect)
        self.energy_injected = 0.0
        super().__init__(model, Q, R_meas, P0, x0=x0, jac_f=jac_f, jac_h=jac_h)

    @staticmethod
    def _resolve_energy(model: object, energy: EnergyFn | None) -> EnergyFn:
        """Find the energy function: explicit argument, then ``energy``, then ``H``."""
        if energy is not None:
            return energy
        for name in ("energy", "H"):
            fn = getattr(model, name, None)
            if callable(fn):
                return fn  # type: ignore[return-value]
        raise TypeError(
            "model exposes neither energy(x) nor H(x); an energy-consistent "
            "observer needs a stored-energy function. Pass energy=... "
            "explicitly, or use ExtendedKalmanFilter if the model has no energy."
        )

    def reset(self, x0: Array | None = None, P0: Array | None = None) -> None:
        """Restore state, covariance and the injected-energy counter."""
        super().reset(x0, P0)
        self.energy_injected = 0.0

    def energy_of(self, x: Array) -> float:
        """Stored energy ``H(x)``.

        Args:
            x: State, shape ``(n_states,)``.

        Returns:
            Energy as a float.
        """
        return float(self._energy_fn(np.asarray(x, dtype=float)))

    def _port_power(self, x: Array, u: Array, t: float) -> float:
        """Instantaneous port power ``yᵀu`` at ``x``."""
        if u.size == 0:
            return 0.0
        y_port = np.atleast_1d(
            np.asarray(
                self._port_fn(x, u, t)
                if self._port_fn is not None
                else self.model.observe(x, u, t),
                dtype=float,
            )
        )
        if y_port.size != u.size:
            raise ValueError(
                f"port output has size {y_port.size} but input has size {u.size}; "
                "yᵀu is not a power. Pass port_output=... to give the collocated "
                "port variable explicitly."
            )
        return float(y_port @ u)

    def _largest_feasible_alpha(
        self, x_prior: Array, delta: Array, h_prior: float, budget: float
    ) -> float:
        """Largest ``α ∈ [0, 1]`` with ``H(x⁻ + αδ) − H(x⁻) ≤ budget``.

        See the class docstring for the non-monotonicity caveat. The returned
        value always satisfies the constraint; it may be conservative.
        """

        def phi(a: float) -> float:
            return self.energy_of(x_prior + a * delta) - h_prior - budget

        if phi(1.0) <= 0.0:
            return 1.0

        grid = np.linspace(0.0, 1.0, self.n_scan + 1)
        lo = 0.0
        hi = float(grid[1])
        found = False
        for j in range(self.n_scan - 1, -1, -1):
            if phi(float(grid[j])) <= 0.0:
                lo = float(grid[j])
                hi = float(grid[j + 1])
                found = True
                break
        if not found:
            # Even a zero correction breaks the balance: the budget is negative
            # because the ports were extracting power. Nothing to scale.
            return 0.0
        if hi <= lo:
            return lo

        for _ in range(self.n_bisect):
            mid = 0.5 * (lo + hi)
            if phi(mid) <= 0.0:
                lo = mid
            else:
                hi = mid
        return lo

    def update(  # type: ignore[override]
        self, y: Array, u: Array, t: float = 0.0, dt: float = 0.0, enforce: bool = True
    ) -> Array:
        """Correct with one measurement, scaled to respect the energy budget.

        Args:
            y: Measurement, shape ``(n_obs,)``.
            u: Input held over the interval that just elapsed, shape
                ``(n_inputs,)``.
            t: Measurement time.
            dt: Length of the interval the ports were supplying over. With
                ``dt = 0`` the budget is ``tol`` alone, i.e. the correction may
                not increase energy at all.
            enforce: Apply the energy constraint. Set ``False`` to take the
                unclamped EKF correction while still recording the diagnostics —
                :meth:`filter` uses this for the very first sample, where no
                interval has elapsed and so no energy balance can have been
                violated. Conditioning a prior on its first measurement is
                initialisation, not evolution.

        Returns:
            The corrected state, shape ``(n_states,)``.
        """
        y = np.atleast_1d(np.asarray(y, dtype=float))
        u = np.atleast_1d(np.asarray(u, dtype=float))
        x_prior = self.x.copy()
        h_prior = self.energy_of(x_prior)

        H_jac, S, K = self._gain(u, t)
        innovation = y - self._h(x_prior, u, t)
        delta = K @ innovation

        supplied = self._port_power(x_prior, u, t) * float(dt)
        budget = supplied + self.tol

        dh_unclamped = self.energy_of(x_prior + delta) - h_prior
        # On an unenforced step there is no budget to exceed, so nothing is
        # recorded as created: the diagnostic counts energy the clamp actually
        # withheld, and counting an initialisation jump here would make it look
        # as though the filter had misbehaved when it was merely starting up.
        created = max(0.0, dh_unclamped - supplied) if enforce else 0.0
        self.energy_injected += created

        alpha = (
            1.0
            if (not enforce or dh_unclamped <= budget)
            else self._largest_feasible_alpha(x_prior, delta, h_prior, budget)
        )

        self.x = x_prior + alpha * delta
        eye = np.eye(self.n_states)
        A_cl = eye - alpha * (K @ H_jac)
        self.P = _symmetrise(
            A_cl @ self.P @ A_cl.T + (alpha**2) * (K @ self.R_meas @ K.T)
        )
        self._last_innovation = innovation
        self._last_nis = float(innovation @ np.linalg.solve(S, innovation))
        self._last_alpha = float(alpha)
        self._last_created = float(created)
        return self.x.copy()

    def step(  # type: ignore[override]
        self, y: Array, u: Array, dt: float, t: float = 0.0
    ) -> Array:
        """Predict across ``dt``, then apply an energy-consistent correction."""
        self.predict(u, dt, t)
        return self.update(y, u, t + dt, dt)

    def filter(  # type: ignore[override]
        self, ys: Array, us: Array | None, ts: Array, reset: bool = True
    ) -> EnergyFilterResult:
        """Run the observer over a full measurement record.

        Same timing convention as
        :meth:`~otwin.estimate.kalman.ExtendedKalmanFilter.filter`: sample 0 is
        an update with no prediction, sample ``k > 0`` predicts across
        ``ts[k] − ts[k-1]`` holding ``us[k-1]`` and then corrects with that same
        interval as the energy budget window.

        Sample 0 is **not** energy-constrained, and ``alpha[0]`` is always
        ``1.0``. No time has elapsed at the first sample, so there is no energy
        balance to violate — the first update conditions the prior, it does not
        evolve a trajectory. Constraining it would instead mean that a prior
        chosen slightly too low could never be corrected upward at all, which
        would make the observer's behaviour depend on the accuracy of the guess
        it was handed.

        Args:
            ys: Measurements, shape ``(n_steps, n_obs)``.
            us: Inputs, shape ``(n_steps, n_inputs)``, or ``None``.
            ts: Time stamps, shape ``(n_steps,)``.
            reset: Restart from ``x0``/``P0`` first.

        Returns:
            An :class:`EnergyFilterResult`.
        """
        ys = np.atleast_2d(np.asarray(ys, dtype=float))
        ts = np.asarray(ts, dtype=float).ravel()
        n_steps = ys.shape[0]
        if ts.size != n_steps:
            raise ValueError(f"ts has {ts.size} entries but ys has {n_steps} rows")
        us_arr = self._empty_inputs(n_steps, us)
        if reset:
            self.reset()

        xs = np.zeros((n_steps, self.n_states))
        Ps = np.zeros((n_steps, self.n_states, self.n_states))
        nus = np.zeros((n_steps, self.n_obs))
        nis = np.zeros(n_steps)
        alphas = np.zeros(n_steps)
        energies = np.zeros(n_steps)
        created = np.zeros(n_steps)

        for k in range(n_steps):
            dt = 0.0
            if k > 0:
                dt = float(ts[k] - ts[k - 1])
                self.predict(us_arr[k - 1], dt, float(ts[k - 1]))
            self.update(ys[k], us_arr[k], float(ts[k]), dt, enforce=k > 0)
            xs[k] = self.x
            Ps[k] = self.P
            nus[k] = self._last_innovation
            nis[k] = self._last_nis
            alphas[k] = self._last_alpha
            created[k] = self._last_created
            energies[k] = self.energy_of(self.x)

        return EnergyFilterResult(
            x=xs,
            P=Ps,
            innovation=nus,
            nis=nis,
            t=ts,
            alpha=alphas,
            energy=energies,
            energy_created=created,
            energy_injected=float(created.sum()),
        )
