"""Exogenous drivers through the one entry point.

`evaluate` handed a model a history and an integer horizon, which is the right
shape for a self-driven series and the wrong one for a twin whose future depends
on something the target does not determine: a duty cycle, an ambient
temperature, a commanded current. Such a twin had to be scored by wiring the
splitters and the metrics up by hand, which is exactly the path where the
leakage discipline gets left out.

The interesting risk in adding drivers is that `exog_future` is future
information. For a genuine driver that is legitimate and necessary. For the
target wearing a different column name it is the leak the whole module exists to
prevent, so it is checked before anything else happens.
"""

import numpy as np
import pytest

from otwin.forecast import ForecastInterfaceError, evaluate


class DriverAwareTwin:
    """Forecasts the target as a response to a driver it is told about."""

    def forecast(self, history, horizon, exog_past=None, exog_future=None):
        h = np.asarray(history, dtype=float).reshape(len(history), -1)
        if exog_past is None or exog_future is None:
            # Without the driver, all it can do is hold the last value.
            return np.repeat(h[-1:], horizon, axis=0)
        past = np.asarray(exog_past, dtype=float).reshape(len(exog_past), -1)[:, 0]
        future = np.asarray(exog_future, dtype=float).reshape(len(exog_future), -1)[:, 0]
        # Fade proportional to cumulative duty: fit the rate on the history,
        # then roll it forward over the duty that is actually scheduled.
        used = np.cumsum(past)
        rate = (h[0, 0] - h[-1, 0]) / max(used[-1], 1e-12)
        return (h[-1, 0] - rate * np.cumsum(future)).reshape(-1, 1)


class HistoryOnlyTwin:
    def forecast(self, history, horizon):
        h = np.asarray(history, dtype=float).reshape(len(history), -1)
        return np.repeat(h[-1:], horizon, axis=0)


def _series(n=200, seed=0):
    """A target that only makes sense given its driver: fade per unit of duty."""
    rng = np.random.default_rng(seed)
    duty = 1.0 + 0.5 * np.sin(np.arange(n) / 7.0) + rng.normal(0, 0.05, n)
    target = 1.0 - 0.0008 * np.cumsum(duty)
    return target.reshape(-1, 1), duty.reshape(-1, 1)


def test_drivers_reach_the_forecaster_and_improve_the_score():
    """If exog changed nothing measurable, it would not be worth an argument."""
    data, duty = _series()
    with_exog = evaluate(DriverAwareTwin(), data, protocol="temporal_holdout", exog=duty)
    without = evaluate(HistoryOnlyTwin(), data, protocol="temporal_holdout")

    assert with_exog.n_exog == 1
    assert without.n_exog is None
    assert with_exog.point_metrics["rmse"] < without.point_metrics["rmse"]


def test_the_report_says_drivers_were_used():
    """A skill score with the drivers in hand is not the same claim as one without."""
    data, duty = _series()
    report = evaluate(DriverAwareTwin(), data, protocol="temporal_holdout", exog=duty)
    text = str(report)
    assert "Exogenous drivers: 1" in text
    assert "the baselines did not" in text


def test_exog_is_split_on_exactly_the_same_boundaries_as_the_data():
    """Off-by-one here would hand the model the driver for the wrong window."""
    data, duty = _series(n=240)
    seen: dict[str, list[tuple[int, int, int, int]]] = {}

    class Recorder:
        def forecast(self, history, horizon, exog_past=None, exog_future=None):
            seen.setdefault("pairs", []).append(
                (len(history), len(exog_past), horizon, len(exog_future))
            )
            return np.repeat(
                np.asarray(history, dtype=float).reshape(len(history), -1)[-1:],
                horizon,
                axis=0,
            )

    evaluate(
        Recorder(), data, protocol="rolling_origin", n_folds=3, horizon=10, exog=duty
    )
    assert seen["pairs"]
    for n_hist, n_past, horizon, n_future in seen["pairs"]:
        assert n_hist == n_past
        assert horizon == n_future


def test_a_covariate_that_is_the_target_is_refused():
    """The leak that does not look like one: a column joined in a month ago."""
    data, _ = _series()
    with pytest.raises(ForecastInterfaceError, match="is the target series"):
        evaluate(DriverAwareTwin(), data, protocol="temporal_holdout", exog=data)


def test_a_shifted_target_is_refused_too():
    """`capacity_next` is the classic. It is the answer with a lag."""
    data, duty = _series()
    lead = np.roll(data[:, 0], -1)
    with pytest.raises(ForecastInterfaceError, match="shifted by"):
        evaluate(
            DriverAwareTwin(),
            data,
            protocol="temporal_holdout",
            exog=np.column_stack([duty[:, 0], lead]),
        )


def test_an_informative_covariate_is_not_refused():
    """The guard must not catch the thing exogenous inputs exist for."""
    data, duty = _series()
    correlated = data[:, 0] * 0.9 + 0.05  # highly informative, not identical
    report = evaluate(
        DriverAwareTwin(),
        data,
        protocol="temporal_holdout",
        exog=np.column_stack([duty[:, 0], correlated]),
    )
    assert report.n_exog == 2


def test_misaligned_exog_is_refused():
    data, duty = _series()
    with pytest.raises(ValueError, match="aligned sample for sample"):
        evaluate(DriverAwareTwin(), data, protocol="temporal_holdout", exog=duty[:-5])


def test_a_forecaster_that_cannot_take_drivers_gets_a_useful_error():
    data, duty = _series()
    with pytest.raises(ForecastInterfaceError, match="exog_past"):
        evaluate(HistoryOnlyTwin(), data, protocol="temporal_holdout", exog=duty)


def test_omitting_exog_leaves_the_old_path_untouched():
    """Every existing forecaster keeps working, with no keyword it never asked for."""
    data, _ = _series()
    report = evaluate(HistoryOnlyTwin(), data, protocol="rolling_origin", n_folds=3)
    assert report.n_exog is None
    assert "Exogenous drivers" not in str(report)
    assert np.isfinite(report.point_metrics["rmse"])
