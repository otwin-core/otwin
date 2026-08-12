"""Tests for the Otwin contract.

These tests are the executable definition of what it means to satisfy an
Otwin protocol. They are intentionally written against *minimal* conforming
implementations rather than against real models, because the point is to pin
the contract, not to test physics.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from otwin.interfaces import (
    Baseline,
    EmpiricalLawModel,
    Forecast,
    Integrator,
    Interval,
    IrreversibleModel,
    MetricSet,
    PortHamiltonianModel,
    Provenance,
    Report,
    Splitter,
    TwinManifest,
    TwinModel,
    UncertaintyModel,
)

# --------------------------------------------------------------------------
# Minimal conforming implementations
# --------------------------------------------------------------------------


class MinimalTwin:
    n_states = 1
    n_inputs = 0

    def rhs(self, x, u, t):
        return -0.5 * x

    def observe(self, x, u, t):
        return x


class MinimalPHS:
    """dH/dt = -R (∇H)^2 <= 0 with u = 0. The simplest passive system."""

    n_states = 1
    n_inputs = 1

    def H(self, x):
        return 0.5 * float(x[0] ** 2)

    def J(self, x):
        return np.zeros((1, 1))

    def R(self, x):
        return np.array([[0.1]])

    def g(self, x):
        return np.array([[1.0]])

    def rhs(self, x, u, t):
        return (self.J(x) - self.R(x)) @ x + self.g(x) @ np.atleast_1d(u)

    def observe(self, x, u, t):
        return self.g(x).T @ x


class MinimalIPHS(MinimalPHS):
    def entropy_production(self, x, u, t):
        return float(x[0] ** 2) * 0.1


class MinimalLaw:
    """A pure trend law: no state derivative, and none required."""

    def law(self, t, params):
        return 1.0 - params["c"] * t ** params["z"]

    @property
    def param_names(self):
        return ("c", "z")


class MinimalIntegrator:
    preserves_structure = False

    def step(self, model, x, u, t, dt):
        return x + dt * model.rhs(x, u, t)


class MinimalUQ:
    def calibrate(self, residuals, horizons):
        self._s = float(np.std(residuals))

    def interval(self, mean, horizons, level=0.9):
        z = 1.645
        return mean - z * self._s, mean + z * self._s


class MinimalBaseline:
    name = "persistence"

    def forecast(self, history, horizon):
        return np.repeat(history[-1:], horizon, axis=0)


class MinimalSplitter:
    leakage_free = True

    def split(self, n_samples):
        cut = n_samples // 2
        return [(np.arange(cut), np.arange(cut, n_samples))]


# --------------------------------------------------------------------------
# Protocol satisfaction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "impl,proto",
    [
        (MinimalTwin(), TwinModel),
        (MinimalPHS(), TwinModel),
        (MinimalPHS(), PortHamiltonianModel),
        (MinimalIPHS(), PortHamiltonianModel),
        (MinimalIPHS(), IrreversibleModel),
        (MinimalLaw(), EmpiricalLawModel),
        (MinimalIntegrator(), Integrator),
        (MinimalUQ(), UncertaintyModel),
        (MinimalBaseline(), Baseline),
        (MinimalSplitter(), Splitter),
    ],
)
def test_minimal_implementations_satisfy_their_protocol(impl, proto):
    assert isinstance(impl, proto)


def test_plain_twin_is_not_a_phs():
    """A model without energy structure must not claim the PHS protocol."""
    assert not isinstance(MinimalTwin(), PortHamiltonianModel)


def test_phs_is_not_irreversible_without_entropy():
    assert not isinstance(MinimalPHS(), IrreversibleModel)


def test_base_exports_no_algorithms():
    """otwin-base must never grow a solver.

    This test exists to fail loudly if someone adds an algorithm here. The
    whole value of the package is that it has none.
    """
    import otwin.interfaces as otwin_base

    banned = {"solve", "integrate", "fit", "forecast", "evaluate", "calibrate"}
    exported = {n for n in otwin_base.__all__}
    assert not (banned & exported), (
        f"otwin-base exported an algorithm: {sorted(banned & exported)}. "
        "Algorithms belong in a tool package."
    )


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------


def test_forecast_rejects_shape_mismatch():
    with pytest.raises(ValueError, match="disagree on the number of steps"):
        Forecast(t=np.linspace(0, 1, 10), x=np.zeros((5, 1)))


def test_forecast_rejects_1d_state():
    with pytest.raises(ValueError, match="must be 2-D"):
        Forecast(t=np.linspace(0, 1, 10), x=np.zeros(10))


def test_energy_non_increasing_detects_a_violation():
    t = np.linspace(0, 1, 5)
    x = np.zeros((5, 1))
    good = Forecast(t=t, x=x, energy=np.array([1.0, 0.9, 0.8, 0.7, 0.6]))
    bad = Forecast(t=t, x=x, energy=np.array([1.0, 0.9, 0.8, 0.95, 0.6]))
    assert good.energy_is_non_increasing()
    assert not bad.energy_is_non_increasing()


def test_energy_check_requires_an_energy_trace():
    f = Forecast(t=np.linspace(0, 1, 3), x=np.zeros((3, 1)))
    with pytest.raises(ValueError, match="no energy trace"):
        f.energy_is_non_increasing()


def test_interval_rejects_inverted_bounds():
    with pytest.raises(ValueError, match="below lower bound"):
        Interval(
            lower=np.array([1.0, 2.0]),
            upper=np.array([0.0, 3.0]),
            level=0.9,
            method="conformal",
        )


def test_interval_rejects_impossible_level():
    with pytest.raises(ValueError, match="level must be a finite number"):
        Interval(lower=np.zeros(2), upper=np.ones(2), level=1.5, method="conformal")


def test_uncalibrated_interval_is_not_validated():
    i = Interval(np.zeros(3), np.ones(3), 0.9, "ensemble")
    assert not i.is_validated
    assert i.coverage_error() is None


def test_coverage_error_signs_the_dangerous_direction():
    """Negative coverage error means over-confidence."""
    over = Interval(np.zeros(3), np.ones(3), 0.9, "conformal", empirical_coverage=0.72)
    under = Interval(np.zeros(3), np.ones(3), 0.9, "conformal", empirical_coverage=0.97)
    assert over.coverage_error() < 0
    assert under.coverage_error() > 0


def test_metricset_beats_baseline_uses_skill_not_r2():
    m = MetricSet(rmse=1.0, mae=0.8, skill=1.4, baseline_name="persistence", r2=0.99)
    assert not m.beats_baseline, "high R² must not disguise a model losing to baseline"


def test_metricset_to_dict_drops_uncomputed():
    m = MetricSet(rmse=1.0, mae=0.8, skill=0.5, baseline_name="drift")
    d = m.to_dict()
    assert "crps" not in d
    assert d["skill"] == 0.5


def test_report_leads_with_the_leakage_warning():
    r = Report(
        metrics=(MetricSet(1.0, 0.8, 0.5, "persistence"),),
        protocol_name="random_split",
        leakage_free=False,
        n_folds=1,
    )
    assert r.summary().startswith("WARNING")


def test_report_summary_names_a_loss_loudly():
    r = Report(
        metrics=(MetricSet(1.0, 0.8, 1.05, "persistence"),),
        protocol_name="rolling_origin",
        leakage_free=True,
        n_folds=1,
    )
    assert "LOSES TO" in r.summary()


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def _manifest(**kw):
    base = dict(
        name="tank-A",
        model_class="port_hamiltonian",
        model_kind="water_tank",
        n_states=1,
        n_inputs=1,
        parameters={"area": 1.0, "outlet": 0.1},
        provenance=Provenance.now("0.1.0"),
    )
    base.update(kw)
    return TwinManifest(**base)


def test_manifest_white_box_when_nothing_estimated():
    assert _manifest().is_white_box


def test_manifest_grey_box_when_something_estimated():
    assert not _manifest(estimated=["outlet"]).is_white_box


def test_manifest_rejects_estimated_name_not_in_parameters():
    with pytest.raises(ValueError, match="not present in parameters"):
        _manifest(estimated=["nonexistent"])


def test_manifest_rejects_unknown_model_class():
    with pytest.raises(ValueError, match="model_class must be one of"):
        _manifest(model_class="neural_vibes")


def test_manifest_not_validated_without_leakage_free_flag():
    assert not _manifest().is_validated
    assert not _manifest(validation={"leakage_free": False}).is_validated
    assert _manifest(validation={"leakage_free": True}).is_validated


def test_manifest_roundtrips_through_json(tmp_path):
    m = _manifest(estimated=["outlet"], validation={"leakage_free": True, "skill": 0.31})
    p = m.save(tmp_path / "twin.json")
    back = TwinManifest.load(p)
    assert back.name == m.name
    assert back.estimated == ("outlet",)
    assert back.validation["skill"] == 0.31
    assert back.provenance.otwin_version == "0.1.0"
    assert back.is_validated


def test_manifest_json_is_plain_and_language_neutral():
    """No Python-specific constructs may leak into the serialised form."""
    import json

    d = json.loads(_manifest().to_json())
    assert isinstance(d, dict)
    assert d["manifest_version"] == "1.0"
    assert isinstance(d["provenance"], dict)


# ==========================================================================
# Regression tests for defects found in independent review (2026-08-03)
# Each test names the defect it pins. Do not delete one without understanding
# what it was protecting against.
# ==========================================================================


class MinimalEstimator:
    @property
    def estimated_names(self):
        return ("level",)

    def fit(self, model, data, t=None, u=None):
        return {"level": float(np.mean(data))}


class WithGradient(MinimalPHS):
    def grad_H(self, x):
        return x


def test_estimator_protocol_exists_and_is_satisfiable():
    """The contract must cover 'estimate', not only 'validate'.

    Without this protocol every fitting tool invents its own interface, and
    fixing that later is a breaking change across the ecosystem.
    """
    from otwin.interfaces import Estimator

    assert isinstance(MinimalEstimator(), Estimator)


def test_energy_gradient_is_a_separate_declarable_protocol():
    """Tools must be able to branch on an analytic ∇H rather than guess a name."""
    from otwin.interfaces import HasEnergyGradient

    assert isinstance(WithGradient(), HasEnergyGradient)
    assert not isinstance(MinimalPHS(), HasEnergyGradient)


def test_empirical_law_does_not_require_a_state_derivative():
    """A fade law has no rhs. Requiring a zero stub was the conceptual error."""
    assert isinstance(MinimalLaw(), EmpiricalLawModel)
    assert not hasattr(MinimalLaw(), "rhs")


def test_accidental_subclass_raises_instead_of_returning_none():
    """Subclassing a protocol is a trap; it must fail loudly, not return None."""

    class Inherits(PortHamiltonianModel):
        n_states = 1
        n_inputs = 1

    with pytest.raises(
        NotImplementedError, match="not for\ninheritance|not for inheritance"
    ):
        Inherits().H(np.ones(1))


def test_manifest_refuses_to_write_nan():
    """NaN and Infinity are not valid JSON and are unreadable from Julia/MATLAB.

    This is the defect that would have broken the first binding silently.
    """
    m = _manifest(parameters={"c": float("nan")})
    with pytest.raises(ValueError, match="not representable in JSON"):
        m.to_json()


def test_manifest_refuses_to_write_infinity():
    m = _manifest(parameters={"c": float("inf")})
    with pytest.raises(ValueError, match="not representable in JSON"):
        m.to_json()


def test_manifest_save_leaves_no_file_when_json_is_invalid(tmp_path):
    target = tmp_path / "bad.json"
    with pytest.raises(ValueError):
        _manifest(parameters={"c": float("nan")}).save(target)
    assert not target.exists(), "a corrupt manifest must not reach disk"


def test_manifest_json_is_parseable_by_a_strict_reader():
    """Emulates Julia JSON3 / MATLAB jsondecode: no bare NaN/Infinity tokens."""
    import json

    text = _manifest(parameters={"a": 1.0, "b": 1e30}).to_json()
    assert "NaN" not in text and "Infinity" not in text
    json.loads(
        text,
        parse_constant=lambda c: (_ for _ in ()).throw(
            ValueError(f"non-JSON constant {c}")
        ),
    )


def test_is_validated_rejects_a_truthy_non_boolean():
    """MATLAB and Julia can round-trip a boolean as 1 or as the string 'false'."""
    assert not _manifest(validation={"leakage_free": "false"}).is_validated
    assert not _manifest(validation={"leakage_free": "no"}).is_validated
    assert not _manifest(validation={"leakage_free": 1}).is_validated
    assert _manifest(validation={"leakage_free": True}).is_validated


def test_manifest_rejects_bare_string_for_estimated():
    """'a' would pass the set-difference check and serialise as a JSON string."""
    with pytest.raises(TypeError, match="not a single string"):
        _manifest(parameters={"a": 1.0}, estimated="a")


def test_manifest_rejects_duplicate_estimated_names():
    with pytest.raises(ValueError, match="duplicates"):
        _manifest(parameters={"a": 1.0}, estimated=["a", "a"])


def test_manifest_rejects_empty_name():
    with pytest.raises(TypeError, match="non-empty string"):
        _manifest(name="")


def test_manifest_is_frozen():
    m = _manifest()
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.model_class = "neural_vibes"


def test_manifest_preserves_unknown_fields_from_a_newer_version():
    """A manifest from a newer Otwin must round-trip losslessly through this one."""
    import json

    d = json.loads(_manifest().to_json())
    d["some_future_field"] = {"nested": [1, 2, 3]}
    back = TwinManifest.from_dict(d)
    assert back.extra["some_future_field"] == {"nested": [1, 2, 3]}
    assert json.loads(back.to_json())["some_future_field"] == {"nested": [1, 2, 3]}


def test_manifest_warns_on_incompatible_major_version():
    import json

    d = json.loads(_manifest().to_json())
    d["manifest_version"] = "99.0"
    with pytest.warns(UserWarning, match="version 99.0"):
        TwinManifest.from_dict(d)


def test_timestamp_is_parseable_without_a_timezone_library():
    """Julia's Dates and MATLAB's datetime both choke on a +00:00 offset."""
    from datetime import datetime

    created = Provenance.now("0.1.0").created
    assert created.endswith("Z")
    assert "+" not in created and "." not in created
    datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")


def test_interval_rejects_nan_bounds():
    """np.any(upper < lower) is False for NaN — the old check let this through."""
    with pytest.raises(ValueError, match="non-finite"):
        Interval(np.array([1e9]), np.array([np.nan]), 0.9, "gp")


def test_interval_rejects_empty_method():
    with pytest.raises(ValueError, match="non-empty string"):
        Interval(np.zeros(2), np.ones(2), 0.9, "")


def test_interval_rejects_impossible_empirical_coverage():
    with pytest.raises(ValueError, match="empirical_coverage must be in"):
        Interval(np.zeros(2), np.ones(2), 0.9, "gp", empirical_coverage=5.0)


def test_result_arrays_cannot_be_mutated_after_validation():
    """Invariants checked at construction must stay true afterwards."""
    lo, up = np.zeros(2), np.ones(2)
    i = Interval(lo, up, 0.9, "gp")
    up[0] = -5.0  # caller mutates their own copy
    assert np.all(i.upper == 1.0), "Interval must not alias caller arrays"
    with pytest.raises(ValueError):
        i.upper[0] = -5.0  # and the stored array is read-only


def test_forecast_rejects_energy_of_the_wrong_length():
    with pytest.raises(ValueError, match="energy has 2 steps"):
        Forecast(t=np.zeros(5), x=np.zeros((5, 1)), energy=np.zeros(2))


def test_forecast_rejects_interval_of_the_wrong_length():
    bad = Interval(np.zeros(9), np.ones(9), 0.9, "gp")
    with pytest.raises(ValueError, match="interval has 9 steps"):
        Forecast(t=np.zeros(3), x=np.zeros((3, 1)), interval=bad)


def test_energy_check_refuses_a_trace_too_short_to_have_a_trend():
    f = Forecast(t=np.zeros(1), x=np.zeros((1, 1)), energy=np.zeros(1))
    with pytest.raises(ValueError, match="at least 2 energy samples"):
        f.energy_is_non_increasing()


def test_energy_check_refuses_a_diverged_run():
    """A diverged integration must not read as a passive trajectory."""
    f = Forecast(t=np.zeros(3), x=np.zeros((3, 1)), energy=np.array([1.0, np.nan, 0.5]))
    with pytest.raises(ValueError, match="diverged"):
        f.energy_is_non_increasing()


def test_report_with_no_folds_is_quiet_and_honest():
    r = Report(metrics=(), protocol_name="p", leakage_free=True, n_folds=0)
    with np.errstate(all="raise"):
        s = r.summary()
    assert "n/a (no folds evaluated)" in s
    assert "LOSES TO" not in s
    assert np.isnan(r.mean_skill)


def test_report_rejects_n_folds_that_disagrees_with_metrics():
    with pytest.raises(ValueError, match="n_folds is 999"):
        Report((MetricSet(1.0, 1.0, 0.5, "b"),), "p", True, 999)


def test_report_summary_survives_string_calibration_values():
    """calibration arrives from JSON that another language may have written."""
    r = Report(
        (MetricSet(1.0, 1.0, 0.5, "b"),),
        "p",
        True,
        1,
        calibration={"level": "0.9", "empirical_coverage": "0.8"},
    )
    assert "coverage" in r.summary()


def test_report_roundtrips_through_dict():
    """One agreed key set for manifest.validation, not one per tool."""
    r = Report(
        metrics=(
            MetricSet(
                1.0, 0.8, 0.31, "persistence", theil_u=0.4, extra={"energy_drift": 1e-9}
            ),
        ),
        protocol_name="rolling_origin",
        leakage_free=True,
        n_folds=1,
        calibration={"level": 0.9, "empirical_coverage": 0.91},
    )
    back = Report.from_dict(r.to_dict())
    assert back.protocol_name == "rolling_origin"
    assert back.leakage_free is True
    assert back.metrics[0].theil_u == 0.4
    assert back.metrics[0].extra["energy_drift"] == 1e-9
    assert back.mean_skill == pytest.approx(0.31)


def test_report_from_dict_rejects_truthy_leakage_free():
    back = Report.from_dict(
        {"protocol": "p", "leakage_free": 1, "n_folds": 0, "metrics": []}
    )
    assert back.leakage_free is False


def test_interval_roundtrips_through_dict():
    i = Interval(
        np.array([0.0, 1.0]),
        np.array([2.0, 3.0]),
        0.9,
        "conformal",
        empirical_coverage=0.91,
    )
    back = Interval.from_dict(i.to_dict())
    assert np.allclose(back.lower, i.lower)
    assert back.method == "conformal"
    assert back.coverage_error() == pytest.approx(0.01)


def test_metricset_extra_allows_a_new_metric_without_a_release():
    m = MetricSet(1.0, 0.8, 0.5, "b", extra={"pinball_0.9": 0.02})
    assert MetricSet.from_dict(m.to_dict()).extra["pinball_0.9"] == 0.02


def test_metricset_from_dict_ignores_unknown_keys():
    m = MetricSet.from_dict(
        {
            "rmse": 1.0,
            "mae": 1.0,
            "skill": 0.5,
            "baseline_name": "b",
            "invented_by_julia": 7,
        }
    )
    assert m.skill == 0.5


def test_evaluation_protocol_has_a_sane_name():
    """Protocol_ was a wart; the error messages and Sphinx pages showed it."""
    from otwin.interfaces import EvaluationProtocol

    assert EvaluationProtocol.__name__ == "EvaluationProtocol"


def test_index_arrays_are_typed_separately_from_float_arrays():
    """Splitters return integer indices; typing them as float forced bad casts."""
    from otwin.interfaces import IndexArray

    assert IndexArray is not None
    idx = np.arange(5)
    assert np.issubdtype(idx.dtype, np.integer)
