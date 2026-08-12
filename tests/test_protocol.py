"""Tests for the evaluation protocol (the core differentiator).

The mock in this file used to be ``predict(X) -> X + noise``: handed the test
targets, it returned them with a little noise on top, and scored "near-perfect".
That was not a model. It was the leak in ``protocol.py`` wearing a costume, and
because the mock and the harness shared the same mistake, the whole suite passed.

The mock below forecasts forward from history and cannot see the future. It is
worse at the job, which is the point -- a test double that cheats will certify
a harness that lets it.
"""

import numpy as np
import pytest

from otwin.forecast import EvalReport, evaluate


class _MockModel:
    """A linear-trend forecaster. Sees history and a horizon, never the answer."""

    def __init__(self, noise: float = 0.0) -> None:
        self.noise = noise
        self.fitted = False
        self._history: np.ndarray | None = None

    def fit(self, train: np.ndarray) -> None:
        self.fitted = True
        self._history = np.asarray(train, dtype=float)

    def _trend(self, history: np.ndarray, horizon: int) -> np.ndarray:
        h = np.asarray(history, dtype=float).reshape(len(history), -1)
        window = min(len(h), 20)
        recent = h[-window:]
        slope = (
            (recent[-1] - recent[0]) / (window - 1) if window > 1 else np.zeros_like(h[0])
        )
        steps = np.arange(1, horizon + 1)[:, None]
        return h[-1][None, :] + slope[None, :] * steps

    def forecast(self, history: np.ndarray, horizon: int) -> np.ndarray:
        out = self._trend(history, horizon)
        if self.noise:
            rng = np.random.default_rng(0)
            out = out + rng.normal(0, self.noise, size=out.shape)
        return out

    def forecast_quantiles(
        self, history: np.ndarray, horizon: int, q: float = 0.5
    ) -> np.ndarray:
        # A band that widens with the horizon, as any honest one must.
        centre = self._trend(history, horizon)
        width = 1.0 + 0.02 * np.arange(1, horizon + 1)[:, None]
        return centre + (-width if q < 0.5 else width)

    def forecast_ensemble(self, history: np.ndarray, horizon: int) -> np.ndarray:
        rng = np.random.default_rng(1)
        centre = self._trend(history, horizon).ravel()
        return centre[:, None] + rng.normal(0, 0.5, size=(centre.size, 20))


def _series(n: int = 120) -> np.ndarray:
    t = np.linspace(0, 12, n)
    return (np.sin(t) + 0.05 * t).reshape(-1, 1)


def test_temporal_holdout_protocol_runs_and_reports() -> None:
    report = evaluate(_MockModel(noise=0.01), _series(), protocol="temporal_holdout")
    assert isinstance(report, EvalReport)
    assert report.split_protocol == "temporal_holdout"
    assert report.n_folds == 1
    assert "rmse" in report.point_metrics
    assert report.baseline_name  # a baseline was chosen
    assert report.data_hash and report.seed == 42


def test_rolling_origin_protocol_multiple_folds() -> None:
    report = evaluate(
        _MockModel(noise=0.01),
        _series(200),
        protocol="rolling_origin",
        n_folds=3,
        horizon=10,
    )
    assert report.split_protocol == "rolling_origin"
    assert report.n_folds == 3


def test_unknown_protocol_raises() -> None:
    with pytest.raises(ValueError):
        evaluate(_MockModel(), _series(), protocol="kfold_shuffle")


def test_probabilistic_metrics_are_computed_when_requested() -> None:
    report = evaluate(
        _MockModel(noise=0.01),
        _series(),
        protocol="temporal_holdout",
        return_uncertainty=True,
    )
    pm = report.probabilistic_metrics
    assert "picp" in pm and "mpiw" in pm and "crps" in pm
    assert 0.0 <= float(pm["picp"]) <= 1.0


def test_skill_score_positive_for_good_model() -> None:
    # A near-perfect model should beat the naive baseline -> positive skill.
    report = evaluate(_MockModel(noise=0.001), _series(), protocol="temporal_holdout")
    assert report.skill_score("rmse") > 0.0


def test_report_render_and_json_roundtrip(tmp_path) -> None:
    report = evaluate(
        _MockModel(noise=0.01),
        _series(),
        protocol="temporal_holdout",
        return_uncertainty=True,
    )
    text = str(report)
    assert "Skill Score" in text or "Baseline" in text
    md = report.to_markdown()
    assert "Baseline" in md

    path = tmp_path / "report.json"
    report.to_json(str(path))
    loaded = EvalReport.from_json(str(path))
    assert loaded.split_protocol == report.split_protocol
    assert loaded.baseline_name == report.baseline_name
