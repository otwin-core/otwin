"""High-level evaluation protocol (rigorous by default).

The one invariant this module exists to hold: **the model never sees the test
targets.** It is given the training history and a horizon, and it returns that
many steps. Anything else is not forecasting, it is interpolation with extra
steps, and it will report a skill score that cannot be reproduced in service.

That invariant was violated here until 2026-08-12. ``evaluate`` called
``model.predict(test)`` -- handing the model the very values it was about to be
scored against -- which meant a ``predict`` that returned its own argument
scored a perfect skill. The interface below makes that call impossible to write:
the second argument is an integer horizon, so there is nothing to leak.
``tests/test_forecast_no_leakage.py`` pins it.
"""

import hashlib
from typing import Any

import numpy as np
import numpy.typing as npt

from .baselines import get_best_baseline
from .metrics import crps, mae, mase, mpiw, nrmse, picp, rmse, theil_u
from .report import EvalReport
from .splitters import rolling_origin, temporal_holdout


class ForecastInterfaceError(TypeError):
    """The model does not expose an interface that can forecast without leakage."""


_INTERFACE_HELP = """
otwin.forecast.evaluate requires a model that can forecast forward from history
without being shown the future. Implement one of:

    def forecast(self, history, horizon) -> array of length `horizon`
    def predict(self, horizon) -> array of length `horizon`   # after .fit(history)

If your model currently takes the test array (`predict(X_test)`), that is the
leak this interface removes: the array it received *was* the answer. Change it
to take an integer number of steps.
"""


def _forecast(
    model: Any,
    train: npt.NDArray[np.floating],
    horizon: int,
    method: str = "forecast",
    **kwargs: Any,
) -> npt.NDArray[np.floating]:
    """Ask ``model`` for ``horizon`` steps beyond the end of ``train``.

    The test targets are not an argument to this function and cannot be passed
    to the model through it. That is the entire design.

    Args:
        model: The model under evaluation.
        train: History the model may use.
        horizon: Number of steps to forecast. An integer, never an array.
        method: ``"forecast"``, ``"quantiles"`` or ``"ensemble"``.
        **kwargs: Forwarded (e.g. ``q=0.05`` for quantiles).

    Returns:
        Array whose leading axis has length ``horizon``.

    Raises:
        ForecastInterfaceError: The model exposes no leakage-free interface, or
            returned the wrong number of steps.
    """
    names = {
        "forecast": ("forecast", "predict"),
        "quantiles": ("forecast_quantiles", "predict_quantiles"),
        "ensemble": ("forecast_ensemble", "predict_ensemble"),
    }[method]

    fn = None
    takes_history = False
    for name in names:
        candidate = getattr(model, name, None)
        if callable(candidate):
            fn = candidate
            takes_history = name.startswith("forecast")
            break
    if fn is None:
        raise ForecastInterfaceError(
            f"model {type(model).__name__!r} has none of {names}.\n{_INTERFACE_HELP}"
        )

    try:
        raw = fn(train, horizon, **kwargs) if takes_history else fn(horizon, **kwargs)
    except (TypeError, ValueError, IndexError) as exc:
        raise ForecastInterfaceError(
            f"calling {type(model).__name__}.{fn.__name__} with a horizon of "
            f"{horizon} failed: {exc}\n{_INTERFACE_HELP}"
        ) from exc

    try:
        y = np.asarray(raw, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ForecastInterfaceError(
            f"{type(model).__name__}.{fn.__name__} returned {raw!r}, which is not "
            f"an array of forecasts.\n{_INTERFACE_HELP}"
        ) from exc

    if y.ndim == 0:
        # A model that echoes its argument gets the horizon back as a scalar.
        # That is the old leaking interface being handed an integer, which is
        # exactly what this design intends.
        raise ForecastInterfaceError(
            f"{type(model).__name__}.{fn.__name__} returned the scalar {float(y)} "
            f"rather than {horizon} forecast steps.\n{_INTERFACE_HELP}"
        )
    if y.shape[0] != horizon:
        raise ForecastInterfaceError(
            f"{type(model).__name__}.{fn.__name__} returned {y.shape[0]} steps for a "
            f"horizon of {horizon}. A forecaster must return exactly the number of "
            f"steps it was asked for."
        )
    return y


def evaluate(
    model: Any,
    data: npt.NDArray[np.floating],
    protocol: str = "temporal_holdout",
    test_frac: float = 0.2,
    n_folds: int = 5,
    horizon: int = 10,
    return_uncertainty: bool = False,
    seasonal_period: int | None = None,
    seed: int = 42,
) -> EvalReport:
    """
    Evaluate forecasting model rigorously (baselines + temporal split).

    This is the ONE ENTRY POINT for evaluation. It enforces:
    - Temporal split (default) or rolling-origin
    - Mandatory baseline comparison
    - Skill scores as headline metric

    Args:
        model: A forecaster exposing ``forecast(history, horizon)`` or
            ``predict(horizon)``. It is never shown the test targets.
        data: Time series data (n_samples, n_features)
        protocol: 'temporal_holdout' or 'rolling_origin'
        test_frac: Fraction for test (temporal_holdout)
        n_folds: Number of folds (rolling_origin)
        horizon: Forecast horizon (rolling_origin)
        return_uncertainty: Whether to compute probabilistic metrics
        seasonal_period: Period for seasonal baselines (optional)
        seed: Random seed

    Returns:
        EvalReport with skill scores, baselines, and all metrics

    Example:
        >>> import numpy as np
        >>> class Drift:
        ...     '''Continues the average slope of the history.'''
        ...     def forecast(self, history, horizon):
        ...         h = np.asarray(history, dtype=float).reshape(len(history), -1)
        ...         slope = (h[-1] - h[0]) / max(len(h) - 1, 1)
        ...         return np.array([h[-1] + slope * (k + 1) for k in range(horizon)])
        >>> data = np.arange(100.0).reshape(-1, 1)
        >>> report = evaluate(Drift(), data, protocol='temporal_holdout')
        >>> report.split_protocol
        'temporal_holdout'
        >>> bool(np.isfinite(report.point_metrics['rmse']))
        True
    """
    if protocol == "temporal_holdout":
        train, test = temporal_holdout(data, test_frac=test_frac)
        folds = [(train, test)]
        n_folds_actual = 1

    elif protocol == "rolling_origin":
        min_train = max(50, len(data) // 4)  # At least 50 or 25% of data
        folds = list(
            rolling_origin(data, n_folds=n_folds, min_train=min_train, horizon=horizon)
        )
        n_folds_actual = len(folds)

    else:
        raise ValueError(
            f"Unknown protocol: {protocol}. Use 'temporal_holdout' or 'rolling_origin'."
        )

    # Accumulate metrics across folds
    model_rmse_vals = []
    model_mae_vals = []
    baseline_rmse_vals = []
    baseline_mae_vals = []
    baseline_names = []

    nrmse_vals = []
    mase_vals = []
    theil_u_vals = []
    crps_vals = []
    picp_vals = []
    mpiw_vals = []

    for train, test in folds:
        # Train model (if it has a .fit method)
        if hasattr(model, "fit"):
            model.fit(train)

        # Model forecast. `train` and a horizon go in; `test` is not passed and
        # is used only for scoring, below. See module docstring.
        y_pred = _forecast(model, train, len(test))

        # Ensure shapes match
        if y_pred.shape != test.shape:
            y_pred = y_pred.reshape(test.shape)

        # Point metrics
        model_rmse_vals.append(rmse(test, y_pred))
        model_mae_vals.append(mae(test, y_pred))
        nrmse_vals.append(nrmse(test, y_pred))

        # Baseline
        baseline_name, baseline_pred, baseline_rmse = get_best_baseline(
            train, test, period=seasonal_period
        )
        baseline_names.append(baseline_name)
        baseline_rmse_vals.append(baseline_rmse)
        baseline_mae_vals.append(mae(test, baseline_pred))

        # Scale-free metrics
        mase_vals.append(mase(test, y_pred, train, seasonal_period=seasonal_period or 1))
        theil_u_vals.append(theil_u(test, y_pred, train))

        # Probabilistic metrics (if requested)
        if return_uncertainty:
            if hasattr(model, "predict_quantiles") or hasattr(
                model, "forecast_quantiles"
            ):
                # 5th and 95th percentiles (90% interval), forecast forward.
                lower = _forecast(model, train, len(test), "quantiles", q=0.05)
                upper = _forecast(model, train, len(test), "quantiles", q=0.95)

                picp_vals.append(picp(test.flatten(), lower.flatten(), upper.flatten()))
                mpiw_vals.append(mpiw(lower.flatten(), upper.flatten()))

            if hasattr(model, "predict_ensemble") or hasattr(model, "forecast_ensemble"):
                # (horizon, n_members), forecast forward.
                ensemble = _forecast(model, train, len(test), "ensemble")
                crps_vals.append(crps(test.flatten(), ensemble))

    # Aggregate across folds
    model_rmse_mean = float(np.mean(model_rmse_vals))
    model_mae_mean = float(np.mean(model_mae_vals))
    baseline_rmse_mean = float(np.mean(baseline_rmse_vals))
    baseline_mae_mean = float(np.mean(baseline_mae_vals))

    # Most common baseline
    baseline_name = max(set(baseline_names), key=baseline_names.count)

    # Create report
    report = EvalReport(
        split_protocol=protocol,
        n_folds=n_folds_actual,
        baseline_name=baseline_name,
        baseline_metrics={
            "rmse": baseline_rmse_mean,
            "mae": baseline_mae_mean,
        },
    )

    # Add model metrics
    report.add_point_metrics(
        rmse=model_rmse_mean,
        mae=model_mae_mean,
        # Computed inside the fold loop from the same leakage-free forecast that
        # produced rmse. Re-running the model here on the test fold -- which is
        # what this line used to do -- was the same leak a second time.
        nrmse=float(np.mean(nrmse_vals)) if nrmse_vals else None,
        mase=float(np.mean(mase_vals)) if mase_vals else None,
        theil_u=float(np.mean(theil_u_vals)) if theil_u_vals else None,
    )

    # Add probabilistic metrics if available
    if crps_vals or picp_vals or mpiw_vals:
        report.add_probabilistic_metrics(
            crps=float(np.mean(crps_vals)) if crps_vals else None,
            picp=float(np.mean(picp_vals)) if picp_vals else None,
            mpiw=float(np.mean(mpiw_vals)) if mpiw_vals else None,
            nominal_level=0.90,
        )

    # Metadata
    report.seed = seed
    report.data_hash = hashlib.sha256(data.tobytes()).hexdigest()[:16]
    report.model_name = (
        model.__class__.__name__ if hasattr(model, "__class__") else "Unknown"
    )

    return report
