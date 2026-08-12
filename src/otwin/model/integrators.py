"""Structure-preserving time integration for port-Hamiltonian systems.

Standard explicit solvers (RK45, etc.) do not respect the energy balance of a
port-Hamiltonian system: over long horizons they can *inject* energy and push the
state into unphysical regions (e.g. negative water height), which shows up as the
Hamiltonian ticking back up near equilibrium.

The implicit-midpoint rule is a symmetric, symplectic-class integrator. For a PHS
with a **quadratic** energy ``H(x) = 1/2 xᵀ Q x`` it satisfies the *discrete*
power balance exactly:

    H(x_{n+1}) − H(x_n) = ∇H(x_mid)·(x_{n+1} − x_n)
                        = Δt · ∇H(x_mid)·[(J − R)∇H(x_mid) + g u_mid]
                        = −Δt · ∇H(x_mid)ᵀ R(x_mid) ∇H(x_mid) + Δt · yᵀ u_mid
                        ≤ Δt · yᵀ u_mid

so with ``u = 0`` energy is non-increasing **to machine precision**, regardless of
how nonlinear ``R(x)`` is, as long as ``R(x_mid) ⪰ 0``. That is the structural
guarantee RK45 cannot give.

For non-quadratic ``H`` the equality above holds only to second order; use a
discrete-gradient method if exact decay is required there.

How the implicit step is solved
-------------------------------
The rule is implicit, so every step needs a root find on

    F(x₁) = x₁ − x₀ − Δt · f(x_m, u_m, t_m),      x_m = (x₀ + x₁)/2

Three solver paths are available, in increasing order of what they assume about
the model and decreasing order of cost per step:

``"fsolve"``
    MINPACK ``hybrd`` via :func:`scipy.optimize.fsolve`. Assumes nothing, builds
    its Jacobian by finite differences (n+1 vector-field evaluations *per*
    Jacobian) and cold-starts on every step. Robust, and slow: ~1.0 ms/step at
    n = 50, which is on the edge of real time against a 1 kHz sensor stream, and
    it gets worse from there — 3.6 ms/step at n = 100.

``"newton"``
    Damped Newton on ``F`` with the analytic Jacobian

        ∂F/∂x₁ = I − (Δt/2) · ∂f/∂x |_{x_m}

    which a port-Hamiltonian model hands you almost for free: for
    ``f = (J − R)∇H + g u`` with state-independent ``J``, ``R``, ``g`` it is
    ``∂f/∂x = (J − R)·∇²H``. When ``∂F/∂x₁`` is the same matrix at every step
    (constant structure matrices, constant ``∇²H``, fixed step size) it is LU
    factorised **once** before the loop. When it is not, it is still reused
    across steps as a modified-Newton iteration matrix and rebuilt only when
    convergence shows it has drifted — including when it has to be
    finite-differenced, which is what a bare vector field with no analytic
    Jacobian gets.

``"linear"``
    When ``H`` is quadratic (``∇H = Qx``, possibly with a constant offset) and
    the structure matrices are constant, the whole system is affine and the
    implicit-midpoint step has a closed form

        (I − Δt/2·M) x₁ = (I + Δt/2·M) x₀ + Δt·(c + g u_m),    M = (J − R)Q

    One LU factorisation before the loop, matrix-vector products inside it, zero
    Newton iterations, zero vector-field evaluations.

:func:`integrate_phs` picks the cheapest applicable path automatically
(``method="auto"``); see its docstring for how the model is inspected, and for
the limits of that inspection. ``benchmarks/bench_integrator.py`` measures all
of them; at n = 50 the closed form runs ~135x faster per step than ``fsolve``
and the Newton path ~15x (~37x at n = 100).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import numpy.typing as npt
from numpy.linalg import LinAlgError
from scipy.linalg import lu_factor, lu_solve
from scipy.optimize import fsolve

__all__ = [
    "IntegratorConvergenceError",
    "LinearMidpointSystem",
    "NewtonResult",
    "implicit_midpoint",
    "integrate_phs",
    "newton_step",
]

Vector = npt.NDArray[np.floating]
Matrix = npt.NDArray[np.floating]

#: Armijo sufficient-decrease constant for the Newton line search.
_ARMIJO = 1e-4
#: Maximum number of step halvings per Newton iteration.
_MAX_LINE_SEARCH = 12
#: A step needing more than this many chord iterations invalidates the cached
#: finite-difference Jacobian.
_JAC_REFRESH_ITERS = 3
#: Residual norm below which a step is accepted even when the solver flagged it.
_RESIDUAL_ACCEPT = 1e-8

_VALID_METHODS = ("auto", "newton", "linear", "fsolve")

# The pre-0.2 name for the default path. Kept working rather than renamed out
# from under callers: `Ensemble` and the published tutorial both pass it.
_METHOD_ALIASES = {"implicit_midpoint": "auto"}


def _resolve_method(method: str) -> str:
    method = _METHOD_ALIASES.get(method, method)
    if method not in _VALID_METHODS:
        raise ValueError(f"method must be one of {_VALID_METHODS}, got {method!r}")
    return method


class IntegratorConvergenceError(RuntimeError):
    """A per-step implicit solve failed to converge.

    Raised only when ``raise_on_failure=True``; otherwise non-convergence is
    reported through the ``'success'`` / ``'message'`` keys of the result dict.
    Either way it is never swallowed: the integrator does not return a state it
    could not solve for as though it were converged.
    """


@dataclass(frozen=True)
class NewtonResult:
    """Outcome of a single damped-Newton solve.

    Attributes:
        x: Best iterate found. Meaningful only if ``converged`` is True.
        converged: Whether the tolerance was met.
        iterations: Newton iterations actually taken.
        residual_norm: ``‖F(x)‖_∞`` at the returned iterate.
        n_feval: Residual evaluations used (including the line search).
        message: Human-readable reason for stopping.
    """

    x: Vector
    converged: bool
    iterations: int
    residual_norm: float
    n_feval: int
    message: str


@dataclass(frozen=True)
class LinearMidpointSystem:
    """An affine vector field ``f(x, u, t) = M x + c + G u``.

    Declaring one of these turns :func:`implicit_midpoint` into a single LU
    factorisation plus one triangular solve per step. Only pass it if the field
    really is affine — the integrator takes it at its word and never evaluates
    ``dynamics``, so a wrong ``M`` here is a wrong *answer*, not merely a slow
    one. :func:`integrate_phs` builds and verifies this object for you.

    Attributes:
        M: State matrix ``(n, n)``; for a PHS, ``(J − R) Q``.
        c: Constant drift ``(n,)``; non-zero when ``∇H`` has an affine offset.
        G: Input matrix ``(n, m)``; for a PHS, ``g``.
    """

    M: Matrix
    c: Vector
    G: Matrix


# ----------------------------------------------------------------------
# Newton
# ----------------------------------------------------------------------


def _inf_norm(v: Vector) -> float:
    # ndarray.max() rather than np.max(): the free function goes through
    # numpy's dispatch machinery and costs about twice as much, which is
    # measurable when it runs five times per integration step.
    return float(np.abs(v).max()) if v.size else 0.0


def _safe_residual(
    residual: Callable[[Vector], Vector], x: Vector
) -> tuple[Vector | None, float]:
    """Evaluate ``residual`` at ``x``, returning ``(F, ‖F‖_∞)``.

    Returns ``(None, inf)`` if the model is undefined there. The line search
    probes points the model may not accept (negative water height, the square
    root of a negative number); such a point must shrink the step, not abort the
    integration. Non-finite entries are caught by the norm itself — ``nan`` and
    ``inf`` both fail ``math.isfinite`` — which saves a separate scan.
    """
    try:
        F = np.asarray(residual(x), dtype=float)
    except (ArithmeticError, ValueError):
        return None, float("inf")
    fnorm = _inf_norm(F)
    if not isfinite(fnorm):
        return None, float("inf")
    return F, fnorm


def _fd_jacobian(
    residual: Callable[[Vector], Vector], x: Vector, F0: Vector
) -> tuple[Matrix, int]:
    """Forward-difference Jacobian of ``residual`` at ``x`` (n extra evaluations)."""
    n = x.size
    jac = np.empty((F0.size, n), dtype=float)
    eps = np.sqrt(np.finfo(float).eps)
    n_feval = 0
    for i in range(n):
        h = eps * max(abs(float(x[i])), 1.0)
        x_pert = x.copy()
        x_pert[i] += h
        # Recover the exact perturbation actually representable at x[i].
        h = float(x_pert[i] - x[i])
        F_pert, _ = _safe_residual(residual, x_pert)
        n_feval += 1
        if F_pert is None:
            # Step backwards instead; the model is undefined on this side.
            x_pert = x.copy()
            x_pert[i] -= abs(h)
            h = float(x_pert[i] - x[i])
            F_pert, _ = _safe_residual(residual, x_pert)
            n_feval += 1
            if F_pert is None:
                raise LinAlgError(
                    f"residual is undefined in both directions along axis {i}"
                )
        jac[:, i] = (F_pert - F0) / h
    return jac, n_feval


def newton_step(
    residual: Callable[[Vector], Vector],
    x_guess: Vector,
    jac: Callable[[Vector], Matrix] | None = None,
    *,
    tol: float = 1e-12,
    max_iter: int = 100,
    linear_solve: Callable[[Vector], Vector] | None = None,
    max_line_search: int = _MAX_LINE_SEARCH,
) -> NewtonResult:
    """Solve ``residual(x) = 0`` by damped Newton iteration.

    Uses the analytic Jacobian when one is supplied, a forward-difference
    Jacobian otherwise, and a caller-supplied pre-factorised solve when the
    Jacobian is constant. Each iteration is backtracked (step halving, Armijo
    condition on ``‖F‖_∞``) so that a bad linear model — a stiff step, an
    inexact Jacobian, a model that is undefined at the full Newton point — damps
    the step instead of diverging.

    Convergence is declared when either

    * ``‖F(x)‖_∞ ≤ tol·(1 + ‖x‖_∞)`` — the residual test, or
    * ``‖Δx‖_∞ ≤ tol·(1 + ‖x‖_∞)`` — Newton's own estimate of the remaining
      error is below tolerance (this is what ``fsolve``'s ``xtol`` measures, and
      it is what stops the iteration once the residual hits its round-off floor).

    Non-convergence is **reported, never swallowed**: the caller gets
    ``converged=False`` plus the reason, and must decide what to do with it.

    Args:
        residual: ``F(x) -> (n,)``. May raise or return non-finite values at
            points outside the model's domain; such points are rejected by the
            line search rather than propagated.
        x_guess: Starting iterate ``(n,)``.
        jac: Optional ``x -> ∂F/∂x`` ``(n, n)``. If None, finite differences are
            used (n extra residual evaluations per iteration).
        tol: Mixed absolute/relative tolerance (see above).
        max_iter: Maximum Newton iterations.
        linear_solve: Optional ``F -> Δx`` solving ``(∂F/∂x)·Δx = −F`` from a
            factorisation the caller has already computed. This is how a
            constant Jacobian is factorised once and reused across every step of
            an integration. It takes precedence over ``jac``. Note that the
            accuracy of this map is *not* an accuracy requirement on the answer:
            Newton drives the residual to ``tol`` however the direction was
            obtained, so an approximate application (a slightly stale
            factorisation, an explicitly formed inverse) costs at most an extra
            iteration.
        max_line_search: Maximum step halvings per iteration.

    Returns:
        :class:`NewtonResult`.

    Example:
        >>> import numpy as np
        >>> res = newton_step(
        ...     lambda x: x**2 - 2.0, np.array([1.0]), lambda x: np.diag(2 * x)
        ... )
        >>> res.converged and bool(abs(res.x[0] - np.sqrt(2)) < 1e-12)
        True
    """
    x = np.array(x_guess, dtype=float, copy=True).ravel()
    n_feval = 1
    F, fnorm = _safe_residual(residual, x)
    if F is None:
        return NewtonResult(
            x,
            False,
            0,
            float("inf"),
            n_feval,
            "residual undefined at the initial guess",
        )
    xnorm = _inf_norm(x)

    for k in range(max_iter):
        xtol = tol * (1.0 + xnorm)
        if fnorm <= xtol:
            return NewtonResult(x, True, k, fnorm, n_feval, "residual below tolerance")

        # --- Newton direction ------------------------------------------------
        try:
            if linear_solve is not None:
                dx = linear_solve(F)
            elif jac is not None:
                dx = np.linalg.solve(np.asarray(jac(x), dtype=float), -F)
            else:
                jac_fd, extra = _fd_jacobian(residual, x, F)
                n_feval += extra
                dx = np.linalg.solve(jac_fd, -F)
        except LinAlgError as exc:
            return NewtonResult(
                x, False, k, fnorm, n_feval, f"Jacobian solve failed: {exc}"
            )
        dxnorm = _inf_norm(dx)
        if not isfinite(dxnorm):
            return NewtonResult(
                x, False, k, fnorm, n_feval, "Newton direction is not finite"
            )

        # Newton's own error estimate is already below tolerance: take the step
        # and stop. This is the criterion that terminates cleanly once the
        # residual has reached its round-off floor.
        if dxnorm <= xtol:
            x_final = x + dx
            F_final, f_final = _safe_residual(residual, x_final)
            n_feval += 1
            if F_final is None:
                return NewtonResult(
                    x, True, k + 1, fnorm, n_feval, "step below tolerance"
                )
            return NewtonResult(
                x_final, True, k + 1, f_final, n_feval, "step below tolerance"
            )

        # --- backtracking line search ---------------------------------------
        alpha = 1.0
        accepted = False
        x_try = x
        F_try = F
        f_try = fnorm
        for _ in range(max_line_search):
            x_cand = x + alpha * dx if alpha != 1.0 else x + dx
            F_cand, f_cand = _safe_residual(residual, x_cand)
            n_feval += 1
            if F_cand is not None and f_cand <= (1.0 - _ARMIJO * alpha) * fnorm:
                x_try, F_try, f_try, accepted = x_cand, F_cand, f_cand, True
                break
            alpha *= 0.5

        if not accepted:
            return NewtonResult(
                x,
                False,
                k + 1,
                fnorm,
                n_feval,
                f"line search failed to reduce the residual (‖F‖={fnorm:.3e})",
            )
        x, F, fnorm = x_try, F_try, f_try
        xnorm = _inf_norm(x)

    converged = fnorm <= tol * (1.0 + xnorm)
    return NewtonResult(
        x,
        converged,
        max_iter,
        fnorm,
        n_feval,
        "residual below tolerance"
        if converged
        else f"no convergence in {max_iter} iterations (‖F‖={fnorm:.3e})",
    )


def _reusable_solve(A: Matrix) -> Callable[[Vector], Vector]:
    """Factorise ``A`` once and return ``F -> Δx`` solving ``A Δx = −F``.

    The factorisation is applied by matrix-vector product against an explicitly
    formed ``−A⁻¹``: at these sizes a :func:`scipy.linalg.lu_solve` call costs
    ~12 µs of dispatch overhead against ~2 µs for the matmul, and this map is
    applied once per Newton iteration per step — tens of thousands of times in a
    single integration. Forming an inverse is normally the wrong instinct, so it
    is checked against the factorisation before being trusted, and falls back to
    ``lu_solve`` if it does not reproduce it. It is safe here regardless: the map
    only supplies Newton's *direction*, and Newton's answer is fixed by the
    residual tolerance, not by how the direction was computed.

    Raises:
        numpy.linalg.LinAlgError: If ``A`` is singular.
    """
    lu = lu_factor(A, check_finite=False)
    eye = np.eye(A.shape[0])
    neg_inv = -lu_solve(lu, eye, check_finite=False)
    if _inf_norm(A @ neg_inv + eye) <= 1e-8 * max(_inf_norm(A), 1.0):
        return neg_inv.__matmul__

    def solve(F: Vector, _lu: Any = lu) -> Vector:
        return lu_solve(_lu, -F, check_finite=False)

    return solve


def _cached_newton(
    residual: Callable[[Vector], Vector],
    x_guess: Vector,
    tol: float,
    max_iter: int,
    cache: Callable[[Vector], Vector] | None,
    build: Callable[[Vector], tuple[Callable[[Vector], Vector], int]],
) -> tuple[NewtonResult, Callable[[Vector], Vector] | None, int]:
    """Newton with an iteration matrix reused between steps.

    Rebuilding and refactorising ``∂F/∂x₁ = I − (Δt/2)·∂f/∂x`` at every step —
    and, for a finite-difference Jacobian, paying ``n+1`` extra vector-field
    evaluations to do it — is precisely the waste that made the ``fsolve`` path
    scale so badly with ``n``. On a fixed grid that matrix changes slowly from
    step to step, so it is built once, factorised, and reused as a
    modified-Newton (chord) iteration matrix. A step that converges only after
    several chord iterations invalidates it for the next step; a step that fails
    outright rebuilds it at the current iterate and retries once.

    Reuse costs convergence *rate*, never the answer: a step is still accepted
    only on a residual below ``tol``.

    Args:
        build: ``x -> (solve, n_feval)`` building the reusable iteration matrix
            at ``x``, and reporting any residual evaluations it needed.

    Returns:
        ``(result, cache_for_the_next_step, extra_residual_evaluations)``.
    """
    n_feval = 0
    res: NewtonResult | None = None
    for _attempt in (0, 1):
        if cache is None:
            try:
                cache, extra = build(x_guess)
                n_feval += extra
            except (LinAlgError, ValueError) as exc:
                return (
                    NewtonResult(
                        x_guess,
                        False,
                        0,
                        float("inf"),
                        n_feval,
                        f"iteration matrix unusable: {exc}",
                    ),
                    None,
                    n_feval,
                )
        res = newton_step(
            residual, x_guess, tol=tol, max_iter=max_iter, linear_solve=cache
        )
        n_feval += res.n_feval
        if res.converged:
            # A step that needed many chord iterations is a sign the cached
            # matrix has drifted; rebuild it before the next one.
            drifted = res.iterations > _JAC_REFRESH_ITERS
            return res, (None if drifted else cache), n_feval
        cache = None  # stale iteration matrix suspected: rebuild and retry once

    assert res is not None
    return res, None, n_feval


def _fd_solve_builder(
    residual: Callable[[Vector], Vector],
) -> Callable[[Vector], tuple[Callable[[Vector], Vector], int]]:
    """Build a reusable solve from a finite-difference residual Jacobian."""

    def build(x: Vector) -> tuple[Callable[[Vector], Vector], int]:
        F0, _ = _safe_residual(residual, x)
        if F0 is None:
            raise ValueError("residual is undefined at the Jacobian point")
        jac_fd, extra = _fd_jacobian(residual, x, F0)
        return _reusable_solve(jac_fd), extra + 1

    return build


# ----------------------------------------------------------------------
# implicit midpoint
# ----------------------------------------------------------------------


def _prepare_inputs(
    x0: Vector, t_eval: Vector, u: Vector
) -> tuple[Vector, Vector, Vector]:
    t_eval = np.asarray(t_eval, dtype=float)
    x0 = np.asarray(x0, dtype=float).ravel()
    u = np.asarray(u, dtype=float)
    if u.ndim == 1:
        u = u.reshape(-1, 1)
    if t_eval.ndim != 1 or t_eval.size < 2:
        raise ValueError("t_eval must be a 1-D array with at least two points")
    if np.any(np.diff(t_eval) <= 0):
        raise ValueError("t_eval must be strictly increasing")
    return x0, t_eval, u


def _fail(message: str, raise_on_failure: bool) -> str:
    if raise_on_failure:
        raise IntegratorConvergenceError(message)
    return message


def _step_sizes(t_eval: Vector) -> tuple[Vector, bool]:
    """Step sizes, with a round-off-uniform grid snapped to a single value.

    ``np.diff(np.linspace(0, 50, 2001))`` takes twelve distinct values: the grid
    points themselves carry an absolute round-off of order ``eps·|t|``, so the
    differences wobble by up to ``n_steps·eps`` *relative*. Taken literally that
    is twelve different step sizes, which would refactorise the step matrix
    twelve times and defeat the point of caching it.

    A grid whose steps vary by no more than the round-off in ``t_eval`` itself is
    therefore treated as exactly uniform, with ``Δt = (t_N − t_0)/N`` — a better
    estimate of the intended step than any individual noisy difference.
    Genuinely non-uniform grids fail the test and are integrated with their own
    per-step ``Δt``. The snap is applied identically on every solver path, so
    the paths stay directly comparable.
    """
    dts = np.diff(t_eval)
    n_steps = dts.size
    span_scale = max(abs(float(t_eval[0])), abs(float(t_eval[-1])))
    uniform = bool(np.ptp(dts) <= 16.0 * np.finfo(float).eps * span_scale)
    if uniform:
        dts = np.full(dts.shape, (float(t_eval[-1]) - float(t_eval[0])) / n_steps)
    return dts, uniform


def _integrate_linear(
    linear: LinearMidpointSystem,
    x0: Vector,
    t_eval: Vector,
    u: Vector,
) -> dict[str, Any]:
    """Closed-form implicit midpoint for an affine field ``f = Mx + c + Gu``.

    On a uniform grid the step operator is assembled once, by solving the single
    LU factorisation of ``A = I − Δt/2·M`` against ``I + Δt/2·M``, ``Δt·G`` and
    ``Δt·c``; every step is then two matrix-vector products and no vector-field
    evaluation at all. On a non-uniform grid it falls back to one triangular
    solve per step, refactorising only when ``Δt`` actually changes.
    """
    n_points = t_eval.size
    n_states = x0.size
    M = np.asarray(linear.M, dtype=float)
    c = np.asarray(linear.c, dtype=float).ravel()
    G = np.asarray(linear.G, dtype=float)
    eye = np.eye(n_states)
    dts, uniform = _step_sizes(t_eval)
    u_mid = 0.5 * (u[:-1] + u[1:])

    xs = np.empty((n_points, n_states), dtype=float)
    xs[0] = x0

    if uniform:
        dt = float(dts[0])
        lu = lu_factor(eye - 0.5 * dt * M, check_finite=False)
        step_op = lu_solve(lu, eye + 0.5 * dt * M, check_finite=False)
        drift = lu_solve(lu, dt * c, check_finite=False)
        input_op = lu_solve(lu, dt * G, check_finite=False)
        # Whole-trajectory input contribution in one matmul.
        forcing = u_mid @ input_op.T + drift
        for k in range(n_points - 1):
            xs[k + 1] = step_op @ xs[k] + forcing[k]
    else:
        lu = None
        rhs_mat = eye
        dt_cached = np.nan
        for k in range(n_points - 1):
            dt = float(dts[k])
            if lu is None or dt != dt_cached:
                lu = lu_factor(eye - 0.5 * dt * M, check_finite=False)
                rhs_mat = eye + 0.5 * dt * M
                dt_cached = dt
            rhs = rhs_mat @ xs[k] + dt * (c + G @ u_mid[k])
            xs[k + 1] = lu_solve(lu, rhs, check_finite=False)

    return {
        "t": t_eval,
        "x": xs,
        "success": True,
        "message": "Integration successful",
        "method": "linear",
        "n_newton_iter": 0,
        "n_feval": 0,
    }


def implicit_midpoint(
    dynamics: Callable[[float, Vector, Vector], Vector],
    x0: Vector,
    t_eval: Vector,
    u: Vector,
    newton_tol: float = 1e-12,
    max_iter: int = 100,
    *,
    method: str = "auto",
    jac: Callable[[float, Vector, Vector], Matrix] | None = None,
    constant_jacobian: bool | None = None,
    linear: LinearMidpointSystem | None = None,
    raise_on_failure: bool = False,
) -> dict[str, Any]:
    """Integrate ``dx/dt = dynamics(t, x, u(t))`` with the implicit-midpoint rule.

    Each step solves the implicit equation

        x_{n+1} = x_n + Δt · dynamics(t_mid, (x_n + x_{n+1}) / 2, u_mid)

    for ``x_{n+1}`` (``t_mid`` and ``u_mid`` are the step midpoints). Inputs are
    interpolated linearly between the rows of ``u``.

    The default solver is damped Newton (:func:`newton_step`) rather than
    ``fsolve``: it uses the analytic Jacobian when one is available, factorises
    it once when it is constant, and warm-starts each step from the previous
    step's increment. The converged answer is the same either way — the residual
    is driven to ``newton_tol`` regardless of how the Jacobian was obtained — so
    the choice of path buys speed, not accuracy.

    Args:
        dynamics: Vector field with signature ``(t, x, u) -> dx``.
        x0: Initial state ``(n_states,)``.
        t_eval: Strictly increasing time points ``(n_points,)``.
        u: Input trajectory ``(n_points, n_inputs)`` (1-D is reshaped to a column).
        newton_tol: Residual tolerance for the per-step implicit solve.
        max_iter: Maximum iterations for the per-step solve.
        method: ``"auto"`` (default) uses the cheapest path the supplied
            information allows — closed form if ``linear`` is given, otherwise
            Newton, falling back to ``fsolve`` for any individual step Newton
            cannot solve. ``"newton"``, ``"linear"`` and ``"fsolve"`` force one
            path and report failure rather than falling back.
        jac: Optional Jacobian of the *vector field*, ``(t, x, u) -> ∂f/∂x``
            ``(n, n)``. The residual Jacobian ``I − (Δt/2)·∂f/∂x`` is assembled
            from it. If None, Newton finite-differences the residual.
        constant_jacobian: Declare that ``jac`` returns the same matrix
            everywhere. With a fixed step size this lets the integrator LU
            factorise ``I − (Δt/2)·∂f/∂x`` once before the loop and reuse it for
            every step and every Newton iteration.
        linear: Optional :class:`LinearMidpointSystem`; enables the closed-form
            path, which never calls ``dynamics``.
        raise_on_failure: Raise :class:`IntegratorConvergenceError` on a failed
            step instead of returning ``success=False``.

    Returns:
        Dict with ``'t'``, ``'x'`` ``(n_points, n_states)``, ``'success'`` and
        ``'message'``, plus ``'method'`` (the path actually taken),
        ``'n_newton_iter'`` and ``'n_feval'``.

    Raises:
        ValueError: On a malformed ``t_eval`` / unknown ``method``, or if
            ``method="linear"`` is requested without a ``linear`` model.
        IntegratorConvergenceError: If a step fails and ``raise_on_failure``.

    Example:
        >>> import numpy as np
        >>> from otwin.model import water_tank
        >>> tank = water_tank()
        >>> t = np.linspace(0, 10, 100)
        >>> u = np.zeros((100, 1))
        >>> res = implicit_midpoint(
        ...     lambda tv, x, uv: tank.dynamics(x, uv), np.array([2.0]), t, u
        ... )
        >>> res["success"]
        True
    """
    method = _resolve_method(method)
    x0, t_eval, u = _prepare_inputs(x0, t_eval, u)

    if method == "linear":
        if linear is None:
            raise ValueError(
                "method='linear' requires a LinearMidpointSystem; use integrate_phs "
                "to derive one from a model, or pass linear=... explicitly"
            )
        return _integrate_linear(linear, x0, t_eval, u)
    if method == "auto" and linear is not None:
        return _integrate_linear(linear, x0, t_eval, u)

    n_points = t_eval.size
    n_states = x0.size
    xs = np.empty((n_points, n_states), dtype=float)
    xs[0] = x0
    eye = np.eye(n_states)

    use_newton = method in ("auto", "newton")
    allow_fsolve_fallback = method == "auto"
    dts, uniform_grid = _step_sizes(t_eval)

    # Factor once, reuse: with a constant vector-field Jacobian and a fixed step
    # size, ∂F/∂x₁ = I − (Δt/2)·∂f/∂x is the same matrix at every step, so it is
    # factorised once here and applied thousands of times below.
    const_solve: Callable[[Vector], Vector] | None = None
    if use_newton and jac is not None and constant_jacobian and uniform_grid:
        t_mid0 = 0.5 * (t_eval[0] + t_eval[1])
        u_mid0 = 0.5 * (u[0] + u[1])
        jac_f = np.asarray(jac(t_mid0, x0, u_mid0), dtype=float)
        try:
            const_solve = _reusable_solve(eye - 0.5 * float(dts[0]) * jac_f)
        except (LinAlgError, ValueError):
            const_solve = None

    success = True
    message = "Integration successful"
    total_iter = 0
    total_feval = 0
    dx_prev: Vector | None = None
    dt_prev = 1.0
    step_solve: Callable[[Vector], Vector] | None = None
    cache_dt = np.nan

    for n in range(n_points - 1):
        dt = float(dts[n])
        t_mid = 0.5 * (t_eval[n] + t_eval[n + 1])
        u_mid = 0.5 * (u[n] + u[n + 1])
        x_n = xs[n]

        def residual(
            x_next: Vector,
            x_n: Vector = x_n,
            dt: float = dt,
            t_mid: float = t_mid,
            u_mid: Vector = u_mid,
        ) -> Vector:
            x_mid = 0.5 * (x_n + x_next)
            return x_next - x_n - dt * np.asarray(dynamics(t_mid, x_mid, u_mid))

        # Warm start: reuse the previous step's increment (rescaled if the grid
        # is non-uniform); fall back to an explicit-Euler predictor on step 0.
        if dx_prev is not None:
            x_guess = x_n + (dt / dt_prev) * dx_prev
        else:
            x_guess = x_n + dt * np.asarray(dynamics(t_eval[n], x_n, u[n]), dtype=float)
            total_feval += 1

        step_failed_msg: str | None = None
        x_next: Vector | None = None

        if use_newton:
            if const_solve is not None:
                # Constant Jacobian, fixed step: one factorisation for the whole
                # integration, applied here.
                res = newton_step(
                    residual,
                    x_guess,
                    tol=newton_tol,
                    max_iter=max_iter,
                    linear_solve=const_solve,
                )
                total_feval += res.n_feval
            else:
                # State-dependent (or unavailable) Jacobian: build the iteration
                # matrix from whatever the model offers and reuse it across
                # steps, refreshing when convergence says it has drifted.
                if dt != cache_dt:
                    step_solve = None
                    cache_dt = dt
                if jac is not None:

                    def build(
                        x: Vector,
                        x_n: Vector = x_n,
                        dt: float = dt,
                        t_mid: float = t_mid,
                        u_mid: Vector = u_mid,
                    ) -> tuple[Callable[[Vector], Vector], int]:
                        x_mid = 0.5 * (x_n + x)
                        jac_f = np.asarray(jac(t_mid, x_mid, u_mid), dtype=float)
                        return _reusable_solve(eye - 0.5 * dt * jac_f), 0

                else:
                    build = _fd_solve_builder(residual)

                res, step_solve, extra = _cached_newton(
                    residual, x_guess, newton_tol, max_iter, step_solve, build
                )
                total_feval += extra
            total_iter += res.iterations
            if res.converged:
                x_next = res.x
            else:
                step_failed_msg = res.message
                if not allow_fsolve_fallback:
                    x_next = res.x

        if x_next is None:
            # fsolve path: either requested outright, or Newton could not solve
            # this step and method="auto" permits the robust fallback.
            x_fs, _info, ier, msg = fsolve(
                residual,
                x_guess,
                full_output=True,
                xtol=newton_tol,
                maxfev=max_iter * (n_states + 1),
            )
            x_fs = np.asarray(x_fs, dtype=float).ravel()
            # fsolve may flag non-convergence near non-smooth points (e.g. sqrt(h)
            # at h->0) even when the residual is effectively zero. Accept on a small
            # residual norm; only fail if the step is genuinely unsolved.
            resid_norm = float(np.linalg.norm(residual(x_fs)))
            if ier != 1 and resid_norm > _RESIDUAL_ACCEPT:
                prefix = (
                    f"Newton did not converge ({step_failed_msg}) and the fsolve "
                    "fallback also failed"
                    if step_failed_msg
                    else "Implicit solve failed"
                )
                message = _fail(
                    f"{prefix} at step {n} (t={t_eval[n]:.4g}, "
                    f"residual={resid_norm:.2e}): {msg}",
                    raise_on_failure,
                )
                success = False
                xs[n + 1] = x_fs
                xs[n + 2 :] = x_fs
                break
            x_next = x_fs
            step_failed_msg = None

        if step_failed_msg is not None:
            message = _fail(
                f"Implicit solve failed at step {n} (t={t_eval[n]:.4g}): "
                f"{step_failed_msg}",
                raise_on_failure,
            )
            success = False
            xs[n + 1] = x_next
            xs[n + 2 :] = x_next
            break

        xs[n + 1] = x_next
        dx_prev = x_next - x_n
        dt_prev = dt

    return {
        "t": t_eval,
        "x": xs,
        "success": success,
        "message": message,
        "method": "newton" if use_newton else "fsolve",
        "n_newton_iter": total_iter,
        "n_feval": total_feval,
    }


# ----------------------------------------------------------------------
# PHS structure inspection
# ----------------------------------------------------------------------


def _probe_points(x0: Vector, n_states: int) -> list[Vector]:
    """Well-separated probe states used to test structure matrices for constancy.

    Deterministic (fixed seed) so that a run is reproducible: the same model and
    the same ``x0`` always take the same solver path.
    """
    scale = np.maximum(np.abs(x0), 1.0)
    rng = np.random.default_rng(20240612)
    alt = np.where(np.arange(n_states) % 2 == 0, 1.0, -1.0)
    return [
        np.asarray(x0, dtype=float),
        x0 + 0.7 * scale * alt,
        x0 - 2.3 * scale,
        x0 + rng.uniform(-3.0, 3.0, size=n_states) * scale,
    ]


def _same(mats: list[Matrix], rtol: float = 1e-10) -> bool:
    """True if every matrix in ``mats`` matches the first, relatively."""
    ref = np.asarray(mats[0], dtype=float)
    scale = max(float(np.max(np.abs(ref))) if ref.size else 0.0, 1.0)
    return all(
        np.allclose(np.asarray(m, dtype=float), ref, rtol=rtol, atol=rtol * scale)
        for m in mats[1:]
    )


def _hessian_jacobian(
    phs: Any, hess_H: Callable[[Vector], Matrix]
) -> Callable[[float, Vector, Vector], Matrix]:
    """``∂f/∂x ≈ (J(x) − R(x))·∇²H(x)``, evaluated wherever Newton needs it.

    Exact when ``J``, ``R`` and ``g`` do not depend on the state. When they do it
    drops the ``∂(J − R)/∂x·∇H`` terms and is an approximation — which costs
    Newton its quadratic convergence rate and nothing else, since the step is
    still accepted only on a residual below tolerance.
    """

    def jac(t: float, x: Vector, u_val: Vector) -> Matrix:
        A = np.asarray(phs.J(x), dtype=float) - np.asarray(phs.R(x), dtype=float)
        return A @ np.asarray(hess_H(x), dtype=float)

    return jac


def _analyse_phs(
    phs: Any,
    x0: Vector,
    u_sample: Vector,
    constant_structure: bool | None,
) -> tuple[
    Callable[[float, Vector, Vector], Matrix] | None, bool, LinearMidpointSystem | None
]:
    """Work out what analytic structure ``phs`` exposes.

    Returns ``(jac, constant_jacobian, linear)``. Any of them may be None/False;
    the integrator degrades to a finite-difference Newton solve, which is still
    correct, only slower.
    """
    n_states = int(getattr(phs, "n_states", x0.size))
    hess_H = getattr(phs, "hess_H", None)
    jac_rhs = getattr(phs, "jac_rhs", None)

    # --- an explicit ∂f/∂x wins outright ---------------------------------
    if callable(jac_rhs):

        def jac(t: float, x: Vector, u_val: Vector) -> Matrix:
            return np.asarray(jac_rhs(x, u_val, t), dtype=float)

        constant = False
        if constant_structure is not False:
            try:
                probes = _probe_points(x0, n_states)
                mats = [jac(0.0, p, u_sample) for p in probes]
                constant = bool(constant_structure) or _same(mats)
            except (ArithmeticError, ValueError):
                constant = bool(constant_structure)
        return jac, constant, None

    if not callable(hess_H):
        return None, False, None

    # --- assemble ∂f/∂x = (J − R)·∇²H ------------------------------------
    try:
        probes = _probe_points(x0, n_states)
        J_mats = [np.asarray(phs.J(p), dtype=float) for p in probes]
        R_mats = [np.asarray(phs.R(p), dtype=float) for p in probes]
        g_mats = [np.asarray(phs.g(p), dtype=float) for p in probes]
        Q_mats = [np.asarray(hess_H(p), dtype=float) for p in probes]
        zero_u = u_sample * 0.0
        f_vals = [np.asarray(phs.dynamics(p, zero_u, 0.0), dtype=float) for p in probes]
    except (ArithmeticError, ValueError, AttributeError):
        # A probe left the model's domain, so nothing can be concluded about
        # constancy; fall back to a Jacobian evaluated where it is needed.
        return _hessian_jacobian(phs, hess_H), False, None

    if any(not np.all(np.isfinite(m)) for m in J_mats + R_mats + Q_mats + g_mats):
        return _hessian_jacobian(phs, hess_H), False, None

    if constant_structure is None:
        struct_const = _same(J_mats) and _same(R_mats) and _same(g_mats)
    else:
        struct_const = bool(constant_structure)
    hess_const = _same(Q_mats)

    if struct_const and hess_const:
        A = J_mats[0] - R_mats[0]
        M = A @ Q_mats[0]

        def jac_const(t: float, x: Vector, u_val: Vector, M: Matrix = M) -> Matrix:
            return M

        # Is the field genuinely affine, f(x, 0) = M x + c? Check the drift term
        # at every probe: a state dependence that survives (J − R)·∇²H being
        # constant would show up here.
        cs = [f - M @ p for f, p in zip(f_vals, probes, strict=True)]
        f_scale = max(
            *(_inf_norm(f) for f in f_vals),
            *(_inf_norm(M @ p) for p in probes),
            1.0,
        )
        affine = all(
            np.allclose(c, cs[0], rtol=0.0, atol=1e-10 * f_scale) for c in cs[1:]
        )
        if affine:
            c = np.mean(np.asarray(cs), axis=0)
            if _inf_norm(c) <= 1e-12 * f_scale:
                c = np.zeros(n_states)
            linear = LinearMidpointSystem(M=M, c=c, G=g_mats[0])
            return jac_const, True, linear
        return jac_const, True, None

    # Structure and/or ∇²H vary with the state: use the state-dependent
    # (and, if J/R/g vary, approximate) Jacobian. See `_hessian_jacobian`.
    return _hessian_jacobian(phs, hess_H), False, None


def integrate_phs(
    phs: Any,
    x0: Vector,
    t_eval: Vector,
    u: Vector | None = None,
    *,
    constant_structure: bool | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Structure-preserving integration of a PHS / IPHS object.

    Convenience wrapper around :func:`implicit_midpoint` that uses
    ``phs.dynamics(x, u, t)`` and, where the model provides enough information,
    a much cheaper solver path than a generic root find.

    **What the model can supply.** Both are optional attributes, looked up with
    ``getattr``; a plain :class:`~otwin.model.phs.PortHamiltonianSystem` has
    neither and simply gets the finite-difference path.

    * ``hess_H(x) -> (n, n)`` — the Hessian ``∇²H``. With state-independent
      ``J``, ``R``, ``g`` this gives the exact vector-field Jacobian
      ``∂f/∂x = (J − R)·∇²H``.
    * ``jac_rhs(x, u, t) -> (n, n)`` — ``∂f/∂x`` directly, for models that know
      it. Takes precedence over ``hess_H``.

    **How constancy is decided, and why that is safe.** ``J``, ``R``, ``g`` and
    ``∇²H`` are evaluated at four well-separated, deterministic probe states
    around ``x0`` and compared. This is a *heuristic*: a model whose structure
    varies but happens to agree at all four probes will be misclassified. The
    consequence differs by path, and the difference matters:

    * For the **Newton** path a wrong Jacobian costs convergence *rate* only.
      The residual is still driven to ``newton_tol``, so the trajectory is
      unchanged. This is safe by construction.
    * For the **closed-form linear** path a wrong ``M`` is a wrong *answer*.
      That path therefore requires ``∇²H`` to be constant *and* the drift
      ``f(x, 0) − M x`` to be identical at every probe — an independent check
      that a merely-coincidental match at the probes is unlikely to pass. Pass
      ``constant_structure=False`` to switch it off outright if your ``J``,
      ``R``, ``g`` or ``∇²H`` vary in a way the probes cannot see; pass
      ``constant_structure=True`` to assert constancy without probing.

    Args:
        phs: Object exposing ``dynamics(x, u, t)`` and ``n_inputs``; optionally
            ``J``, ``R``, ``g``, ``hess_H``, ``jac_rhs``.
        x0: Initial state.
        t_eval: Time points.
        u: Input trajectory ``(n_points, n_inputs)``; defaults to zeros.
        constant_structure: Override for the constancy heuristic described
            above. ``None`` (default) probes the model.
        **kwargs: Forwarded to :func:`implicit_midpoint` (``method``,
            ``newton_tol``, ``max_iter``, ``raise_on_failure``, ...).

    Returns:
        Same dict as :func:`implicit_midpoint`.

    Raises:
        ValueError: If ``method="linear"`` is requested but the model cannot be
            shown to be affine. The request is refused, never silently
            downgraded to a different answer.
    """
    t_eval = np.asarray(t_eval, dtype=float)
    x0_arr = np.asarray(x0, dtype=float).ravel()
    n_inputs = int(getattr(phs, "n_inputs", 1))
    if u is None:
        u = np.zeros((t_eval.size, n_inputs))

    def dynamics(t: float, x: Vector, u_val: Vector) -> Vector:
        return np.asarray(phs.dynamics(x, u_val, t), dtype=float)

    method = kwargs.get("method", "auto")
    method = _resolve_method(method)

    jac = kwargs.pop("jac", None)
    constant_jacobian = kwargs.pop("constant_jacobian", None)
    linear = kwargs.pop("linear", None)

    if method != "fsolve" and (jac is None and linear is None):
        u_arr = np.asarray(u, dtype=float)
        u_sample = u_arr[0] if u_arr.ndim > 1 else np.atleast_1d(u_arr[0])
        try:
            jac, detected_const, linear = _analyse_phs(
                phs, x0_arr, np.asarray(u_sample, dtype=float), constant_structure
            )
        except Exception:  # noqa: BLE001 - inspection must never break integration
            jac, detected_const, linear = None, False, None
        if constant_jacobian is None:
            constant_jacobian = detected_const

    if method == "linear" and linear is None:
        raise ValueError(
            "method='linear' was requested but this model could not be shown to be "
            "affine: it needs constant J, R, g and a constant hess_H(x) (∇²H), and "
            "f(x, 0) − M x must be state-independent. Use method='newton' (same "
            "answer, one LU per Newton iteration) or supply hess_H."
        )

    return implicit_midpoint(
        dynamics,
        x0_arr,
        t_eval,
        u,
        jac=jac,
        constant_jacobian=constant_jacobian,
        linear=linear,
        **kwargs,
    )
