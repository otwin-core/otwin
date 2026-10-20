"""A ModelingToolkit model checked with Otwin: the level of a town's storage tank.

The model is written in Julia (tank.jl, next to this file) and called from
Python. Run it from this folder after:

    pip install "otwin[engine]" juliacall
    python -c 'from juliacall import Main as jl; jl.seval("import Pkg; Pkg.add([\"ModelingToolkit\", \"OrdinaryDiffEq\"])")'

The first run downloads Julia and compiles the packages (about twenty minutes).
"""

import numpy as np
from juliacall import Main as jl
from otwin.forecast import evaluate

jl.include("tank.jl")  # the ModelingToolkit model of the storage tank


class JuliaTank:
    """Forecast the level from the last reading with the ModelingToolkit model."""

    def forecast(self, history, horizon):
        t0 = float(len(history) - 1)
        last = float(np.ravel(history)[-1])
        return np.asarray(jl.forecast(last, t0, horizon)).reshape(-1, 1)


# the real tank: deeper morning and evening peaks than the design profile,
# level sensor noise 1 cm
rng = np.random.default_rng(0)
hours = np.arange(30 * 24, dtype=float)
draw = 60.0 * (1 + 0.8 * np.sin(2 * np.pi * hours / 24 - np.pi / 2))
level = 3.0 + np.concatenate([[0.0], np.cumsum((60.0 - draw[:-1]) / 400.0)])
reading = level + rng.normal(0, 0.01, hours.size)

report = evaluate(
    JuliaTank(),
    reading.reshape(-1, 1),
    protocol="rolling_origin",
    n_folds=5,
    horizon=24,
    seasonal_period=24,
)
print(report)
