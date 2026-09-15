"""The 0.4 Python integrator against the compiled engine, same models, same grids.

What is measured, per model:

``0.4 integrate_phs``
    the hand-written ``PortHamiltonianSystem`` through the Python implicit
    midpoint solver, the fastest applicable path (``method="auto"``).
``numpy backend``
    the compiled model on the NumPy reference backend, implicit midpoint.
``rust engine``
    the compiled model on ``otwin_engine``, implicit midpoint, and RK4 for the
    fixed-step comparison.
``rust batch``
    one hundred simulations from different initial states, in parallel.

Compilation time is reported separately: it is paid once per model, not per
simulation, and it is the price of never calling Python inside the loop.

Run:  python benchmarks/bench_engine.py
Writes: benchmarks/results/engine.json
"""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import otwin  # noqa: E402
from otwin.components import catalogue  # noqa: E402
from otwin.model import (  # noqa: E402
    dc_motor,
    integrate_phs,
    mass_spring_damper,
    water_tank,
)
from otwin.runtime import engine_available  # noqa: E402

N_REPEAT = 5
CASES = {
    "mass_spring_damper": (
        lambda: mass_spring_damper(1.0, 20.0, 0.3),
        lambda: catalogue.mass_spring_damper(1.0, 20.0, 0.3, position=1.0),
        np.array([1.0, 0.0]),
        np.linspace(0, 20, 20_001),
        None,
    ),
    "water_tank": (
        water_tank,
        lambda: catalogue.water_tank(level=2.0),
        np.array([2.0]),
        np.linspace(0, 600, 60_001),
        None,
    ),
    "dc_motor": (
        dc_motor,
        catalogue.dc_motor,
        np.array([0.0, 0.0]),
        np.linspace(0, 5, 50_001),
        12.0,
    ),
}


def best_of(fn, n=N_REPEAT):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times)


def main() -> None:
    results = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "otwin": otwin.__version__,
        "engine_available": engine_available(),
        "cases": {},
    }
    print(
        f"otwin {otwin.__version__}  engine={'yes' if engine_available() else 'no'}  {platform.platform()}"
    )
    print(
        f"{'model':<20} {'steps':>7} {'0.4 python':>12} {'numpy':>10} {'rust mid':>10} {'rust rk4':>10} {'compile':>9} {'batch/run':>10}"
    )
    for name, (old_fn, new_fn, x0, t, u_const) in CASES.items():
        old = old_fn()
        u = None if u_const is None else np.full((t.size, 1), u_const)
        t_old = best_of(
            lambda: integrate_phs(
                old, x0, t, u if u is not None else np.zeros((t.size, 1))
            )
        )
        t0 = time.perf_counter()
        model_np = otwin.compile(new_fn(), backend="numpy")
        t_compile = time.perf_counter() - t0
        inputs = None if u_const is None else {model_np.input_names[0]: u_const}
        t_np = best_of(
            lambda: model_np.simulate(t=t, x0=x0, inputs=inputs, record=False), n=1
        )
        row = {
            "steps": int(t.size - 1),
            "python_0_4_s": t_old,
            "numpy_s": t_np,
            "compile_s": t_compile,
        }
        t_rs = t_rk4 = t_batch = float("nan")
        if engine_available():
            model_rs = otwin.compile(new_fn(), backend="rust")
            t_rs = best_of(
                lambda: model_rs.simulate(t=t, x0=x0, inputs=inputs, record=False)
            )
            t_rk4 = best_of(
                lambda: model_rs.simulate(
                    t=t, x0=x0, inputs=inputs, solver="rk4", record=False
                )
            )
            x0s = np.tile(x0, (100, 1)) * np.linspace(0.5, 1.5, 100)[:, None]
            tb = t[:: max(1, t.size // 2001)]
            ub = None if u_const is None else np.full((tb.size, 1), u_const)
            t_batch = (
                best_of(lambda: model_rs.simulate_batch(x0s, tb, inputs=ub), n=2) / 100
            )
            row.update(
                {
                    "rust_midpoint_s": t_rs,
                    "rust_rk4_s": t_rk4,
                    "rust_batch_per_run_s": t_batch,
                    "batch_steps": int(tb.size - 1),
                }
            )
        results["cases"][name] = row
        print(
            f"{name:<20} {t.size - 1:>7} {t_old:>11.3f}s {t_np:>9.3f}s {t_rs:>9.4f}s {t_rk4:>9.4f}s {t_compile:>8.3f}s {t_batch:>9.5f}s"
        )
    out = Path(__file__).resolve().parent / "results" / "engine.json"
    out.write_text(json.dumps(results, indent=2))
    print(
        f"\nwritten {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}"
    )


if __name__ == "__main__":
    main()
