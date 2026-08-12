"""Prognostic Assessment (ISO 13374 block PA): what happens next, and how sure.

Three opinions are built into the interface rather than written in a document
and hoped for:

**Out-of-sample partitions by default.** A random partition trains on Tuesday
and Thursday and predicts Wednesday. That measures interpolation, and
interpolation is not the task. ``random_split`` exists, warns, and marks every
report derived from it on the first line.

**A reference forecaster is mandatory.** The headline number is skill --
model error over reference error -- because the only question that matters is
whether this beats the obvious thing. R-squared will read 0.99 on a model that
loses to repeating yesterday's value, which is why it is not shown first.

**The model never sees the test targets.** ``evaluate`` hands a model its
history and an integer horizon. There is no argument through which the answer
could reach it. See ``protocol.py`` for the defect that made this explicit.
"""

from .baselines import (
    drift,
    get_best_baseline,
    mean_forecast,
    persistence,
    seasonal_naive,
)
from .calibration import (
    coverage_curve,
    expected_calibration_error,
    interval_score,
    pit_values,
    recalibrate,
    sharpness,
)
from .ensemble import Ensemble
from .metrics import crps, mae, mase, mpiw, nrmse, picp, rmse, skill_score, theil_u
from .protocol import ForecastInterfaceError, evaluate
from .report import EvalReport
from .splitters import random_split, rolling_origin, temporal_holdout

__all__ = [
    "evaluate",
    "EvalReport",
    "ForecastInterfaceError",
    "temporal_holdout",
    "rolling_origin",
    "random_split",
    "persistence",
    "drift",
    "mean_forecast",
    "seasonal_naive",
    "get_best_baseline",
    "rmse",
    "mae",
    "nrmse",
    "mase",
    "theil_u",
    "crps",
    "picp",
    "mpiw",
    "skill_score",
    "Ensemble",
    "pit_values",
    "coverage_curve",
    "expected_calibration_error",
    "interval_score",
    "recalibrate",
    "sharpness",
]


def __getattr__(name):
    if name == "GPPHS":
        try:
            from .gp_phs import GPPHS
        except ImportError as exc:
            raise ImportError(
                "GPPHS needs scikit-learn. Install it with: pip install 'otwin[gp]'"
            ) from exc
        return GPPHS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
