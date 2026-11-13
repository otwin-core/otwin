"""Leave-one-unit-out validation: does a twin calibrated on a fleet transfer?

A twin built for one kind of equipment is usually calibrated on some units and
then used on another that it has never seen. Validating it on the units it was
calibrated on measures how well it remembers them. It says nothing about the
next unit.

:func:`transfer_validation` holds out each unit in turn. It calls ``fit`` on
the remaining units only, then forecasts the held-out unit from rolling
origins along its own series. Each contrast (an observation against its
forecast) is recorded with its unit, origin, horizon, signed error and whether
the range covered it. The resulting table is what
:func:`otwin.audit.coverage_audit` reads, so the same numbers can be split by
horizon tranche.

What the held-out unit contributes and what it does not
-------------------------------------------------------
**Calibration.** The held-out unit contributes nothing. ``fit`` receives a
mapping that does not contain it, and this is checked on every fold, with a
check that survives ``python -O``. Units given twice, as the same array or as
equal data, are rejected up front. Otherwise a unit could be calibrated on its
own copy.

**Conditioning.** The forecaster sees the held-out unit's own past, up to the
origin. That is how the twin will run on a new unit. It never sees the values
it is scored against.

Neither check can stop ``fit`` from reading the full set of units through a
closure. Pass it only what it is given.

The loop runs one unit after another, with no parallelism. A unit's fit is
called once. Its forecaster is called once per origin.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from otwin.audit import CoverageAudit, coverage_audit

__all__ = ["TransferContrasts", "TransferValidation", "transfer_validation"]

Array = npt.NDArray[np.floating]
#: Named aliases rather than ``npt.NDArray[np.bool_]`` inline: a trailing
#: underscore reads as a reStructuredText hyperlink when autodoc renders the
#: annotation (the same reason :mod:`otwin.forecast.conformal` names its own).
IdArray = npt.NDArray[np.object_]
IntArray = npt.NDArray[np.int_]
BoolArray = npt.NDArray[np.bool_]
Forecaster = Callable[[Array, int], tuple[Any, Any, Any]]


def _frozen(a: Array) -> Array:
    """A read-only copy, so neither ``fit`` nor a forecaster can edit the caller's data."""
    out = np.array(a, dtype=float, copy=True)
    out.setflags(write=False)
    return out


def _assert_not_self_calibrated(
    held_out: Hashable,
    calibration: Mapping[Hashable, Array],
    all_ids: Sequence[Hashable],
    held_out_series: Array,
) -> None:
    """Fail loudly if the held-out unit could reach its own calibration.

    This raises :class:`AssertionError` explicitly, not with an ``assert``
    statement, so it still runs under ``python -O``.
    """
    if held_out in calibration:
        raise AssertionError(f"unit {held_out!r} is in its own calibration set")
    expected = [u for u in all_ids if u != held_out]
    if list(calibration) != expected:
        raise AssertionError(
            f"calibration set for unit {held_out!r} is {list(calibration)}, "
            f"expected exactly the other units {expected}"
        )
    for other, series in calibration.items():
        if np.shares_memory(series, held_out_series):
            raise AssertionError(
                f"calibration unit {other!r} shares memory with held-out unit {held_out!r}"
            )


@dataclass(frozen=True)
class TransferContrasts:
    """One row per contrast: a held-out observation against its forecast.

    Every column has one entry per contrast. The columns ``observed``,
    ``prediction``, ``lower``, ``upper`` and ``horizon`` are what
    :func:`otwin.audit.coverage_audit` takes. :meth:`audit` passes them on.

    Attributes:
        unit: The held-out unit each contrast belongs to.
        origin: Index in that unit's series where the forecast started. The
            forecaster saw ``series[:origin]``.
        horizon: Steps ahead, starting at 1.
        observed: ``series[origin + horizon - 1]``.
        prediction: The point forecast.
        lower: Lower end of the range.
        upper: Upper end of the range.
        error: ``observed - prediction``, the signed error.
        covered: ``lower <= observed <= upper``.
    """

    unit: IdArray
    origin: IntArray
    horizon: IntArray
    observed: Array
    prediction: Array
    lower: Array
    upper: Array
    error: Array
    covered: BoolArray

    def __len__(self) -> int:
        return int(self.observed.size)

    def audit(
        self,
        *,
        level: float,
        tranches: Sequence[float] | None = None,
        min_contrasts: int | None = None,
        confidence: float = 0.95,
    ) -> CoverageAudit:
        """The tranche report on these contrasts, by :func:`otwin.audit.coverage_audit`."""
        return coverage_audit(
            self.observed,
            self.prediction,
            self.lower,
            self.upper,
            level=level,
            horizons=self.horizon.astype(float),
            tranches=tranches,
            min_contrasts=min_contrasts,
            confidence=confidence,
        )

    def to_dict(self) -> dict[str, list[Any]]:
        """Column-oriented, JSON-serialisable form: one list per column."""
        return {
            "unit": [_json_id(u) for u in self.unit],
            "origin": [int(v) for v in self.origin],
            "horizon": [int(v) for v in self.horizon],
            "observed": [float(v) for v in self.observed],
            "prediction": [float(v) for v in self.prediction],
            "lower": [float(v) for v in self.lower],
            "upper": [float(v) for v in self.upper],
            "error": [float(v) for v in self.error],
            "covered": [bool(v) for v in self.covered],
        }


def _json_id(u: Any) -> Any:
    """A unit id as JSON can hold it: kept if ``str`` or ``int``, else its ``str``."""
    if isinstance(u, (str, int)) and not isinstance(u, bool):
        return u
    if isinstance(u, np.integer):
        return int(u)
    return str(u)


@dataclass(frozen=True)
class TransferValidation:
    """Leave-one-unit-out contrasts and their summary.

    Attributes:
        contrasts: Every contrast, ready for the tranche report.
        audit: The tranche report on all contrasts at ``level``, with
            ``horizon_levels`` as the tranches.
        calibration_units: For each held-out unit, the units ``fit`` was
            called with. This records that no unit was in its own set.
        n_contrasts_per_unit: How many contrasts each held-out unit gave. A
            unit too short for any origin gives zero.
    """

    contrasts: TransferContrasts
    audit: CoverageAudit
    calibration_units: dict[Hashable, tuple[Hashable, ...]] = field(default_factory=dict)
    n_contrasts_per_unit: dict[Hashable, int] = field(default_factory=dict)

    @property
    def overall_coverage(self) -> float | None:
        """Coverage over every contrast, or ``None`` if the row was refused."""
        return self.audit.overall.coverage

    @property
    def tranche_coverage(self) -> dict[str, float | None]:
        """Coverage per horizon tranche, ``None`` where a tranche was refused."""
        return {t.label: t.coverage for t in self.audit.tranches or ()}

    @property
    def median_bias(self) -> float | None:
        """Median of ``observed - prediction`` over every contrast."""
        return self.audit.overall.median_error

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable summary, with the tranche report and the calibration record.

        The contrasts table is left out because it can be large. Use
        ``self.contrasts.to_dict()`` to include it.
        """
        return {
            "section": "transfer_validation",
            "overall_coverage": self.overall_coverage,
            "tranche_coverage": self.tranche_coverage,
            "median_bias": self.median_bias,
            "n_contrasts": len(self.contrasts),
            "n_contrasts_per_unit": {
                str(_json_id(k)): v for k, v in self.n_contrasts_per_unit.items()
            },
            "calibration_units": {
                str(_json_id(k)): [_json_id(u) for u in v]
                for k, v in self.calibration_units.items()
            },
            "coverage": self.audit.to_dict(),
        }


def transfer_validation(
    units: Mapping[Hashable, Array | Sequence[float]] | Sequence[Array | Sequence[float]],
    fit: Callable[[Mapping[Hashable, Array]], Forecaster],
    horizon_levels: Sequence[float],
    *,
    level: float,
    min_history: int = 1,
    step: int = 1,
    min_contrasts: int | None = None,
    confidence: float = 0.95,
) -> TransferValidation:
    """Hold out each unit, calibrate on the rest, forecast it, and record every contrast.

    Args:
        units: One series per unit. A mapping from unit id to series, or a
            sequence, in which case the ids are ``0, 1, ...``. At least two.
        fit: ``fit(calibration_units) -> forecaster``. It receives a mapping
            from id to read-only series, with every unit except the held-out
            one. It returns ``forecaster(history, horizon) -> (prediction,
            lower, upper)``, three arrays of ``horizon`` values. The range
            should be stated at ``level``. ``fit`` is where the model is
            fitted and the range calibrated, so both see only the other units.
        horizon_levels: Horizon tranche boundaries ``[b0, b1, ..., bk]``,
            strictly increasing, as in :func:`otwin.audit.coverage_audit`. The
            forecast runs to ``floor(bk)`` steps.
        level: The coverage the forecaster's range states.
        min_history: The first origin in each held-out series. The forecaster
            always gets at least this many points of history.
        step: Spacing between origins.
        min_contrasts: Passed to :func:`otwin.audit.coverage_audit`. A tranche
            with fewer contrasts is refused, and the refusal names the count.
        confidence: Confidence of the interval on observed coverage.

    Returns:
        A :class:`TransferValidation`.

    Raises:
        ValueError: If there are fewer than two units, a series is not 1-D or
            not finite, two units are the same data, ``horizon_levels`` does
            not give at least one step, ``min_history`` or ``step`` is below 1,
            a forecaster returns the wrong shape, NaN or ``lower > upper``,
            or no unit is long enough to give a single contrast.
        AssertionError: If a held-out unit ever reaches its own calibration
            set. This cannot happen through this function. It is checked
            anyway on every fold, because the guarantee is the point.

    Example:
        >>> import numpy as np
        >>> rng = np.random.default_rng(0)
        >>> fleet = {f"pump{i}": 5.0 + rng.normal(0, 0.5, 60) for i in range(4)}
        >>> def fit(cal):                                 # mean level, 90 % range
        ...     pooled = np.concatenate(list(cal.values()))
        ...     mu, (lo, hi) = pooled.mean(), np.quantile(pooled - pooled.mean(), [0.05, 0.95])
        ...     def forecaster(history, horizon):
        ...         p = np.full(horizon, mu)
        ...         return p, p + lo, p + hi
        ...     return forecaster
        >>> tv = transfer_validation(fleet, fit, [0, 3, 6], level=0.9, min_history=10, step=5)
        >>> tv.calibration_units["pump0"]
        ('pump1', 'pump2', 'pump3')
        >>> len(tv.contrasts), sorted(tv.tranche_coverage)
        (236, ['(0, 3]', '(3, 6]'])
        >>> 0.8 < tv.overall_coverage <= 1.0
        True
    """
    items = list(units.items()) if isinstance(units, Mapping) else list(enumerate(units))
    if len(items) < 2:
        raise ValueError(
            f"transfer validation needs at least two units, got {len(items)}: "
            "with one, there is nothing left to calibrate on"
        )
    ids = [u for u, _ in items]
    series: dict[Hashable, Array] = {}
    originals: dict[Hashable, Any] = {}
    for u, s in items:
        arr = np.asarray(s, dtype=float)
        if arr.ndim != 1:
            raise ValueError(f"unit {u!r} must be a 1-D series, got shape {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"unit {u!r} contains NaN or Inf")
        originals[u] = s
        series[u] = _frozen(arr)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            oa, ob = originals[a], originals[b]
            aliased = (
                isinstance(oa, np.ndarray)
                and isinstance(ob, np.ndarray)
                and np.shares_memory(oa, ob)
            )
            if aliased or np.array_equal(series[a], series[b]):
                raise ValueError(
                    f"units {a!r} and {b!r} are the same data; holding one out would "
                    "leave its copy in the calibration set"
                )

    edges = np.asarray(horizon_levels, dtype=float).ravel()
    if edges.size < 2 or not np.all(np.isfinite(edges)) or np.any(np.diff(edges) <= 0):
        raise ValueError(
            "horizon_levels must be at least two finite, strictly increasing "
            f"boundaries, got {list(edges)}"
        )
    max_horizon = int(np.floor(edges[-1]))
    if max_horizon < 1:
        raise ValueError(
            f"the last horizon boundary must be at least 1 step, got {edges[-1]:g}"
        )
    if int(min_history) < 1 or int(step) < 1:
        raise ValueError(
            f"min_history and step must be at least 1, got {min_history} and {step}"
        )

    cols: dict[str, list[Any]] = {
        k: [] for k in ("unit", "origin", "horizon", "observed", "pred", "lo", "up")
    }
    calibration_record: dict[Hashable, tuple[Hashable, ...]] = {}
    per_unit: dict[Hashable, int] = {}

    for held_out in ids:  # one unit at a time, by design
        calibration = {u: series[u] for u in ids if u != held_out}
        y = series[held_out]
        _assert_not_self_calibrated(held_out, calibration, ids, y)
        calibration_record[held_out] = tuple(calibration)

        forecaster = fit(calibration)

        count = 0
        for origin in range(int(min_history), y.size, int(step)):
            horizon = min(max_horizon, y.size - origin)
            history = _frozen(y[:origin])
            out = forecaster(history, horizon)
            try:
                pred, lo, up = (np.asarray(v, dtype=float).ravel() for v in out)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"the forecaster for unit {held_out!r} must return "
                    "(prediction, lower, upper)"
                ) from exc
            where = f"unit {held_out!r}, origin {origin}"
            if not pred.size == lo.size == up.size == horizon:
                raise ValueError(
                    f"{where}: the forecaster returned {pred.size}, {lo.size} and "
                    f"{up.size} steps for a horizon of {horizon}"
                )
            if not (
                np.all(np.isfinite(pred))
                and np.all(np.isfinite(lo))
                and np.all(np.isfinite(up))
            ):
                raise ValueError(f"{where}: the forecaster returned NaN or Inf")
            if np.any(lo > up):
                raise ValueError(f"{where}: the forecaster returned lower > upper")
            cols["unit"].extend([held_out] * horizon)
            cols["origin"].extend([origin] * horizon)
            cols["horizon"].extend(range(1, horizon + 1))
            cols["observed"].extend(y[origin : origin + horizon])
            cols["pred"].extend(pred)
            cols["lo"].extend(lo)
            cols["up"].extend(up)
            count += horizon
        per_unit[held_out] = count

    if not cols["observed"]:
        raise ValueError(
            f"no unit is longer than min_history={min_history}, so there is no "
            "origin to forecast from"
        )

    unit_col = np.empty(len(cols["unit"]), dtype=object)
    unit_col[:] = cols["unit"]
    obs = np.asarray(cols["observed"], dtype=float)
    pred_a = np.asarray(cols["pred"], dtype=float)
    lo_a = np.asarray(cols["lo"], dtype=float)
    up_a = np.asarray(cols["up"], dtype=float)
    contrasts = TransferContrasts(
        unit=unit_col,
        origin=np.asarray(cols["origin"], dtype=int),
        horizon=np.asarray(cols["horizon"], dtype=int),
        observed=obs,
        prediction=pred_a,
        lower=lo_a,
        upper=up_a,
        error=obs - pred_a,
        covered=(lo_a <= obs) & (obs <= up_a),
    )
    audit = contrasts.audit(
        level=level,
        tranches=list(edges),
        min_contrasts=min_contrasts,
        confidence=confidence,
    )
    return TransferValidation(
        contrasts=contrasts,
        audit=audit,
        calibration_units=calibration_record,
        n_contrasts_per_unit=per_unit,
    )
