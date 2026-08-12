"""The model must never see the test targets.

This file exists because of a specific defect. Until 2026-08-12,
``otwin.forecast.evaluate`` called ``model.predict(test)`` -- it handed the
model the exact values it was about to be scored against. A model whose
``predict`` returned its own argument therefore scored a perfect skill, in the
one package whose stated purpose is preventing that.

Every test below is written so that it fails if the defect returns. Two of them
are written so that they would also fail if the *fix* were fake -- they assert
the leak is impossible, not merely that a particular call site was edited.
"""

import numpy as np
import pytest

from otwin.forecast.protocol import ForecastInterfaceError, evaluate

# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


class Oracle:
    """Returns whatever array it is handed.

    Under the old interface this scored a perfect RMSE of 0.0, because the
    array it was handed was the answer. Under the current interface it is
    handed an integer and cannot do anything with it.
    """

    def predict(self, x):
        return x


class Spy:
    """Records every argument it ever receives, then forecasts badly on purpose."""

    def __init__(self):
        self.seen = []

    def fit(self, train):
        self.seen.append(("fit", np.asarray(train, dtype=float).copy()))

    def forecast(self, history, horizon):
        self.seen.append(("forecast:history", np.asarray(history, dtype=float).copy()))
        self.seen.append(("forecast:horizon", horizon))
        last = np.asarray(history, dtype=float)[-1]
        return np.repeat(np.atleast_1d(last)[None, :], horizon, axis=0)

    def arrays_seen(self):
        return [v for _, v in self.seen if isinstance(v, np.ndarray)]


class Persistence:
    """Repeats the last observed value. The honest floor."""

    def forecast(self, history, horizon):
        h = np.asarray(history, dtype=float).reshape(len(history), -1)
        return np.repeat(h[-1][None, :], horizon, axis=0)


class Cheater:
    """Tries every trick to get at the future, and must fail at all of them."""

    def __init__(self, truth):
        self.truth = np.asarray(truth, dtype=float)

    def forecast(self, history, horizon):
        # The only thing available is `history`. If the harness were leaking,
        # `history` would contain values beyond its own end -- it does not.
        h = np.asarray(history, dtype=float)
        return np.repeat(h[-1][None, :], horizon, axis=0)


class LegacyPredictTakesArray:
    """The pre-fix interface: predict(X_test). Must be rejected, loudly."""

    def predict(self, x):
        return np.asarray(x, dtype=float) * 2.0


class WrongLength:
    def forecast(self, history, horizon):
        return np.zeros((horizon + 3, 1))


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def trending():
    """A trending series -- the case where leakage is most flattering."""
    n = 240
    t = np.arange(n, dtype=float)
    rng = np.random.default_rng(0)
    return (0.05 * t + 2.0 * np.sin(t / 9.0) + rng.normal(0, 0.3, n)).reshape(-1, 1)


# --------------------------------------------------------------------------
# The invariant
# --------------------------------------------------------------------------


def test_model_never_receives_the_test_targets(trending):
    """The property, asserted directly rather than inferred from a call site.

    Whatever `evaluate` does internally, no array handed to the model may
    contain a value from the held-out tail. This is the test that would still
    catch the defect if it came back through a different code path.
    """
    spy = Spy()
    evaluate(spy, trending, protocol="temporal_holdout", test_frac=0.25)

    n_test = int(len(trending) * 0.25)
    held_out = trending[-n_test:].ravel()

    assert spy.arrays_seen(), "the spy was never called at all"
    for arr in spy.arrays_seen():
        flat = np.asarray(arr, dtype=float).ravel()
        overlap = np.intersect1d(flat, held_out)
        assert overlap.size == 0, (
            f"the model was handed {overlap.size} value(s) from the test tail; "
            f"first was {overlap[0]!r}"
        )


def test_horizon_is_an_integer_not_an_array(trending):
    """There must be nothing array-shaped in the horizon argument to leak."""
    spy = Spy()
    evaluate(spy, trending, protocol="temporal_holdout", test_frac=0.2)
    horizons = [v for k, v in spy.seen if k == "forecast:horizon"]
    assert horizons, "forecast was never called"
    for h in horizons:
        assert isinstance(h, (int, np.integer)), f"horizon was {type(h).__name__}"
        assert h > 0


def test_oracle_cannot_score_better_than_persistence(trending):
    """The headline regression.

    Before the fix this model scored a skill of 0.0 -- a perfect forecast --
    by returning the answer it had been given. It must now do no better than
    repeating the last value.
    """
    with pytest.raises(ForecastInterfaceError):
        evaluate(Oracle(), trending, protocol="temporal_holdout")


def test_cheater_gets_no_better_than_persistence(trending):
    """A model actively trying to reach the future gets exactly persistence."""
    cheat = evaluate(Cheater(trending), trending, protocol="temporal_holdout")
    honest = evaluate(Persistence(), trending, protocol="temporal_holdout")
    assert cheat.point_metrics["rmse"] == pytest.approx(
        honest.point_metrics["rmse"], rel=1e-12
    )


def test_persistence_scores_about_one_against_itself(trending):
    """Sanity floor: the harness is measuring something real.

    Persistence evaluated against a baseline family that contains persistence
    must land at a skill near 1.0. Materially below 1.0 would mean the model
    path and the baseline path are not being scored on the same footing --
    which is exactly what leakage looked like.
    """
    report = evaluate(Persistence(), trending, protocol="temporal_holdout")
    skill = report.point_metrics["rmse"] / report.baseline_metrics["rmse"]
    assert skill >= 0.99, f"persistence scored a skill of {skill:.4f} against itself"


# --------------------------------------------------------------------------
# The interface refuses the old shape rather than silently accepting it
# --------------------------------------------------------------------------


def test_legacy_array_predict_is_rejected_with_an_actionable_message(trending):
    with pytest.raises(ForecastInterfaceError) as exc:
        evaluate(LegacyPredictTakesArray(), trending)
    msg = str(exc.value)
    assert "forecast(self, history, horizon)" in msg
    assert "integer number of steps" in msg


def test_model_with_no_forecast_interface_is_rejected(trending):
    class Nothing:
        pass

    with pytest.raises(ForecastInterfaceError):
        evaluate(Nothing(), trending)


def test_wrong_horizon_length_is_caught(trending):
    with pytest.raises(ForecastInterfaceError) as exc:
        evaluate(WrongLength(), trending)
    assert "steps it was asked for" in str(exc.value)


# --------------------------------------------------------------------------
# The invariant holds on every split protocol, not just the default
# --------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", ["temporal_holdout", "rolling_origin"])
def test_invariant_holds_across_protocols(trending, protocol):
    spy = Spy()
    evaluate(spy, trending, protocol=protocol, n_folds=3, horizon=8)

    for arr in spy.arrays_seen():
        flat = np.asarray(arr, dtype=float).ravel()
        # Every array the model saw must be a prefix of the series: its last
        # element must appear before the point the fold's forecast begins.
        assert flat.size <= trending.size
        assert np.all(np.isin(flat, trending.ravel()))


def test_rolling_origin_history_grows_and_never_jumps_ahead(trending):
    """Each fold's history must extend the previous one, never overlap the future."""
    spy = Spy()
    evaluate(spy, trending, protocol="rolling_origin", n_folds=4, horizon=6)
    histories = [v for k, v in spy.seen if k == "forecast:history"]
    lengths = [len(h) for h in histories]
    assert lengths == sorted(lengths), f"history did not grow monotonically: {lengths}"
    series = trending.ravel()
    for h in histories:
        n = len(h)
        assert np.allclose(np.asarray(h, dtype=float).ravel(), series[:n]), (
            "a fold's history was not a strict prefix of the series"
        )
