"""Tests for ensemble forecasting.

Deliberately self-contained. ``Ensemble`` requires only that its members expose
``forecast(x0, t, u, method=...) -> {"x": ...}`` — a duck-typed contract, not a
particular class. The original version of this file imported ``DigitalTwin``
from the umbrella package, which made a leaf package depend on the thing that
depends on it. The minimal member below proves the decoupling is real, which is
what lets ``otwin-uq`` be installed and used on its own.
"""

from __future__ import annotations

import numpy as np
import pytest

from otwin.forecast import Ensemble, crps
from otwin.model import integrate_with_inputs, water_tank


class SimpleForecaster:
    """The minimum an ensemble member must be. No Otwin base class involved."""

    def __init__(self, model):
        self.model = model

    def forecast(self, x0, t, u, method: str = "RK45") -> dict:
        sol = integrate_with_inputs(
            lambda tt, xx, uu: self.model.rhs(xx, uu, tt), x0, t, u, method=method
        )
        return {"x": sol["x"]}


def _ensemble(spread=(0.08, 0.10, 0.12)) -> Ensemble:
    return Ensemble([SimpleForecaster(water_tank(a=a)) for a in spread])


def test_a_member_needs_no_otwin_base_class():
    """The point of the duck-typed contract, stated as a test."""
    ens = _ensemble()
    assert not any(hasattr(m, "__otwin__") for m in ens.members)
    assert ens.n_members == 3


def test_requires_at_least_two_members():
    with pytest.raises(ValueError, match="at least two"):
        Ensemble([SimpleForecaster(water_tank())])


def test_trajectories_shape():
    ens = _ensemble()
    t = np.linspace(0, 5, 40)
    trajs = ens.forecast_trajectories(np.array([2.0]), t, np.zeros((40, 1)))
    assert trajs.shape == (3, 40, 1)


def test_interval_bounds_are_ordered_and_contain_the_mean():
    ens = _ensemble()
    t = np.linspace(0, 5, 40)
    band = ens.forecast_interval(np.array([2.0]), t, np.zeros((40, 1)), level=0.9)
    assert band["lower"].shape == (40, 1)
    assert np.all(band["lower"] <= band["upper"] + 1e-12)
    assert np.all(band["mean"] >= band["lower"] - 1e-9)
    assert np.all(band["mean"] <= band["upper"] + 1e-9)
    assert band["std"].max() > 0.0, "members differ, so the spread must be real"


def test_spread_reflects_real_disagreement_not_a_constant():
    """An ensemble whose members agree must not manufacture uncertainty.

    A constant band is the classic placeholder that looks like uncertainty
    quantification and is not.
    """
    identical = Ensemble([SimpleForecaster(water_tank(a=0.1)) for _ in range(3)])
    t = np.linspace(0, 5, 40)
    band = identical.forecast_interval(np.array([2.0]), t, np.zeros((40, 1)))
    assert band["std"].max() < 1e-9, "identical members must produce ~zero spread"

    spread = _ensemble().forecast_interval(np.array([2.0]), t, np.zeros((40, 1)))
    assert spread["std"].max() > 1e-3


def test_band_widens_with_the_horizon():
    """Uncertainty about a trajectory should grow as you forecast further."""
    ens = _ensemble()
    t = np.linspace(0, 8, 80)
    band = ens.forecast_interval(np.array([2.0]), t, np.zeros((80, 1)))
    width = (band["upper"] - band["lower"])[:, 0]
    assert width[20] > width[2], "the band should widen away from the initial condition"


def test_ensemble_matrix_is_crps_compatible():
    ens = _ensemble()
    t = np.linspace(0, 5, 40)
    mat = ens.ensemble_matrix(np.array([2.0]), t, np.zeros((40, 1)), state=0)
    assert mat.shape == (40, 3)
    score = crps(mat.mean(axis=1), mat)
    assert np.isfinite(score) and score >= 0.0


def test_level_must_be_in_the_unit_interval():
    ens = _ensemble()
    t = np.linspace(0, 1, 10)
    with pytest.raises(ValueError):
        ens.forecast_interval(np.array([2.0]), t, np.zeros((10, 1)), level=1.5)
