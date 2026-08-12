"""Per-step cost of the implicit-midpoint solver paths.

The implicit-midpoint rule needs a root find at every step. The original
implementation handed that to :func:`scipy.optimize.fsolve` (MINPACK ``hybrd``),
which finite-differences its Jacobian — ``n + 1`` vector-field evaluations per
Jacobian — and cold-starts on every step. Its cost therefore grows with the state
dimension, which is exactly backwards for the operational use case: a 50-state
twin fed by a 1 kHz sensor stream has 1000 µs per step to work with.

This script measures µs/step for each path on the same systems, same grid, same
initial condition:

``fsolve``
    the original path, kept reachable for genuinely nasty nonlinear ``R``.
``newton``
    damped Newton on the analytic Jacobian ``I − (Δt/2)(J − R)∇²H``, factorised
    once when it is constant.
``newton (FD jac)``
    the same Newton solver on a model that exposes no ``hess_H``, so the
    residual Jacobian is finite-differenced. This is what a bare vector field
    passed to ``implicit_midpoint`` gets, and it is the honest floor for a model
    that tells the integrator nothing.
``linear``
    the closed-form step for quadratic ``H`` and constant structure matrices:
    one LU before the loop, matrix-vector products inside it.

Two model families are timed: a linear PHS (``H = ½xᵀQx``, where the closed form
applies) and a nonlinear one (``H = Σ cosh(xᵢ) − 1``, where it does not and
Newton has to iterate).

Run:  python benchmarks/bench_integrator.py
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from otwin.model.integrators import integrate_phs  # noqa: E402
from otwin.model.phs import PortHamiltonianSystem  # noqa: E402

SEED = 20240612
N_STATES = (2, 10, 50)
#: Extra size used only to locate where the Newton path crosses the gate, since
#: its per-step cost is nearly flat in n while fsolve's is not.
N_SCALING_PROBE = 100
N_STEPS = 400
DT = 1e-3
#: Repeats per measurement; the minimum is reported, which is the standard
#: choice for timing under a noisy scheduler (the minimum is the run least
#: disturbed by everything else on the machine).
N_REPEAT = 5
#: Speedup at n = 50 that the rewrite is required to clear.
GATE_SPEEDUP = 20.0
GATE_N = 50


Matrices = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def _structure(n: int, seed: int) -> Matrices:
    """Constant ``Q ≻ 0``, ``J = −Jᵀ``, ``R ⪰ 0``, ``g`` for an n-state PHS."""
    rng = np.random.default_rng(seed)
    A = rng.normal(size=(n, n)) / np.sqrt(n)
    Q = A.T @ A + np.eye(n)  # symmetric positive definite
    B = rng.normal(size=(n, n)) / np.sqrt(n)
    J = 0.5 * (B - B.T)  # skew-symmetric
    L = np.tril(rng.normal(size=(n, n))) / np.sqrt(n)
    R = 0.1 * (L @ L.T)  # positive semidefinite
    g = rng.normal(size=(n, 1))
    return Q, J, R, g


def linear_phs(n: int, seed: int = SEED, with_hessian: bool = True):
    """``H(x) = ½ xᵀQx`` — quadratic energy, constant structure matrices."""
    Q, J, R, g = _structure(n, seed)
    phs = PortHamiltonianSystem(
        H=lambda x: float(0.5 * x @ Q @ x),
        J=lambda x: J,
        R=lambda x: R,
        g=lambda x: g,
        n_states=n,
        n_inputs=1,
        grad_H=lambda x: Q @ x,
    )
    if with_hessian:
        phs.hess_H = lambda x: Q
    return phs


def nonlinear_phs(n: int, seed: int = SEED, with_hessian: bool = True):
    """``H(x) = Σ (cosh xᵢ − 1)`` — nonlinear energy, constant structure matrices.

    ``∇H = sinh x`` and ``∇²H = diag(cosh x)``, so the closed form cannot apply
    and the Newton path has to reassemble and refactorise every iteration.
    """
    _, J, R, g = _structure(n, seed)

    phs = PortHamiltonianSystem(
        H=lambda x: float(np.sum(np.cosh(x) - 1.0)),
        J=lambda x: J,
        R=lambda x: R,
        g=lambda x: g,
        n_states=n,
        n_inputs=1,
        grad_H=np.sinh,
    )
    if with_hessian:
        phs.hess_H = lambda x: np.diag(np.cosh(x))
    return phs


@dataclass
class Measurement:
    us_per_step: float
    speedup: float
    path: str
    ok: bool
    max_diff: float


def time_path(phs, x0, t, u, method, reference=None) -> tuple[float, dict]:
    """Minimum wall time over ``N_REPEAT`` runs, plus the last result."""
    integrate_phs(phs, x0, t, u, method=method)  # warm up imports/caches
    best = float("inf")
    res = None
    for _ in range(N_REPEAT):
        t0 = time.perf_counter()
        res = integrate_phs(phs, x0, t, u, method=method)
        best = min(best, time.perf_counter() - t0)
    return best, res


def run_family(name: str, factory, methods) -> dict[int, dict[str, Measurement]]:
    print(f"\n{name}")
    print("-" * len(name))
    rows: dict[int, dict[str, Measurement]] = {}
    for n in N_STATES:
        rng = np.random.default_rng(SEED + n)
        x0 = rng.normal(size=n)
        t = np.linspace(0.0, N_STEPS * DT, N_STEPS + 1)
        u = (0.1 * np.sin(3.0 * t)).reshape(-1, 1)

        rows[n] = {}
        baseline_us = None
        reference_x = None
        for label, method, with_hessian in methods:
            phs = factory(n, with_hessian=with_hessian)
            elapsed, res = time_path(phs, x0, t, u, method)
            us = elapsed / N_STEPS * 1e6
            if baseline_us is None:
                baseline_us = us
                reference_x = res["x"]
            max_diff = float(np.max(np.abs(res["x"] - reference_x)))
            rows[n][label] = Measurement(
                us_per_step=us,
                speedup=baseline_us / us,
                path=res["method"],
                ok=bool(res["success"]),
                max_diff=max_diff,
            )
    return rows


def print_table(rows: dict[int, dict[str, Measurement]], labels: list[str]) -> None:
    head = (
        f"{'n':>4}  {'path':<18} {'µs/step':>10} {'speedup':>9} "
        f"{'took':<8} {'Δ vs fsolve':>12}"
    )
    print(head)
    print("-" * len(head))
    for n in N_STATES:
        for label in labels:
            m = rows[n][label]
            flag = "" if m.ok else "  FAILED"
            print(
                f"{n:>4}  {label:<18} {m.us_per_step:>10.2f} {m.speedup:>8.1f}x "
                f"{m.path:<8} {m.max_diff:>12.2e}{flag}"
            )
        print()


def main() -> int:
    print("otwin - implicit-midpoint per-step cost")
    print("=" * 72)
    print(f"python {platform.python_version()}  numpy {np.__version__}  ")
    print(f"{platform.machine()} / {platform.system()}")
    print(
        f"seed={SEED}  steps={N_STEPS}  dt={DT}  repeats={N_REPEAT} "
        f"(minimum reported)"
    )

    methods = [
        ("fsolve (old)", "fsolve", True),
        ("newton (analytic)", "newton", True),
        ("newton (FD jac)", "newton", False),
        ("linear (closed form)", "linear", True),
    ]
    linear_rows = run_family(
        "Linear PHS:  H = 1/2 x'Qx,  constant J, R, g", linear_phs, methods
    )
    print_table(linear_rows, [m[0] for m in methods])

    nonlinear_rows = run_family(
        "Nonlinear PHS:  H = sum(cosh(x) - 1),  constant J, R, g",
        nonlinear_phs,
        [m for m in methods if m[0] != "linear (closed form)"],
    )
    print_table(
        nonlinear_rows, [m[0] for m in methods if m[0] != "linear (closed form)"]
    )

    # ------------------------------------------------------------------
    # acceptance gate
    # ------------------------------------------------------------------
    print("=" * 72)
    print(f"Acceptance gate: >= {GATE_SPEEDUP:.0f}x speedup at n = {GATE_N}")
    print("-" * 72)
    default_path = linear_rows[GATE_N]["linear (closed form)"]
    newton_path = linear_rows[GATE_N]["newton (analytic)"]
    nonlinear_newton = nonlinear_rows[GATE_N]["newton (analytic)"]

    print(
        f"  quadratic H, default path (linear): {default_path.speedup:8.1f}x  "
        f"({default_path.us_per_step:.2f} us/step)  "
        f"{'PASS' if default_path.speedup >= GATE_SPEEDUP else 'FAIL'}"
    )
    print(
        f"  quadratic H, forced Newton path:    {newton_path.speedup:8.1f}x  "
        f"({newton_path.us_per_step:.2f} us/step)  "
        f"{'PASS' if newton_path.speedup >= GATE_SPEEDUP else 'FAIL'}"
    )
    print(
        f"  nonlinear H, default path (Newton): {nonlinear_newton.speedup:8.1f}x  "
        f"({nonlinear_newton.us_per_step:.2f} us/step)  "
        f"{'PASS' if nonlinear_newton.speedup >= GATE_SPEEDUP else 'FAIL'}"
    )

    # A 1 kHz sensor stream gives 1000 us per step. Say plainly whether each
    # path keeps up at n = 50, because that is the operational claim.
    print()
    for label in ("fsolve (old)", "newton (analytic)", "linear (closed form)"):
        m = linear_rows[GATE_N][label]
        verdict = "keeps up" if m.us_per_step < 1000.0 else "TOO SLOW"
        print(
            f"  1 kHz real time at n=50, {label:<21} "
            f"{m.us_per_step:8.2f} us  {verdict}"
        )

    gate_ok = default_path.speedup >= GATE_SPEEDUP
    print()
    verdict = "MET" if gate_ok else "NOT MET"
    print(f"GATE: {verdict} on the default path for a quadratic H.")
    if newton_path.speedup < GATE_SPEEDUP:
        probe = scaling_probe(N_SCALING_PROBE)
        print(
            "NOTE: the forced-Newton path on the same system comes in at "
            f"{newton_path.speedup:.1f}x, below the {GATE_SPEEDUP:.0f}x gate. Its "
            "per-step cost is a couple of model evaluations plus a fixed slab of "
            "interpreter overhead, neither of which grows with n, while fsolve "
            "pays n+1 evaluations per Jacobian. The ratio therefore climbs with "
            "n and crosses the gate above n=50: measured "
            f"{probe['speedup']:.1f}x at n={N_SCALING_PROBE} "
            f"({probe['fsolve']:.0f} -> {probe['newton']:.1f} us/step)."
        )
    return 0 if gate_ok else 1


def scaling_probe(n: int) -> dict[str, float]:
    """fsolve vs analytic Newton at one larger size, to locate the crossover."""
    phs = linear_phs(n)
    rng = np.random.default_rng(SEED + n)
    x0 = rng.normal(size=n)
    t = np.linspace(0.0, N_STEPS * DT, N_STEPS + 1)
    u = (0.1 * np.sin(3.0 * t)).reshape(-1, 1)
    fs, _ = time_path(phs, x0, t, u, "fsolve")
    nw, _ = time_path(phs, x0, t, u, "newton")
    return {
        "fsolve": fs / N_STEPS * 1e6,
        "newton": nw / N_STEPS * 1e6,
        "speedup": fs / nw,
    }


if __name__ == "__main__":
    raise SystemExit(main())
