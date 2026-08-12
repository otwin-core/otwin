"""Result types — what Otwin tools return.

These are frozen dataclasses that defensively copy and write-lock the arrays
they are given, so an invariant checked at construction stays true afterwards.
They are deliberately dumb: they carry numbers and provenance, and they know
how to serialise themselves. Logic that *interprets* them belongs in a tool
package, not here.

Keeping them here rather than in each tool is what lets an ``otwin-uq``
calibrator consume an ``otwin-phs`` forecast without either package importing
the other. The ``to_dict`` / ``from_dict`` pair on each type is what lets a
``Report`` produced in Python be read by the Julia binding — and what stops
each tool from inventing its own key names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .protocols import Array

__all__ = ["Forecast", "Interval", "MetricSet", "Report"]


def _frozen_array(a: Any, name: str) -> Array:
    """Copy an array-like and mark it read-only.

    Without this, a caller keeps a live reference to the array a result was
    validated against, and can invalidate the invariant one line later.
    """
    arr = np.array(a, dtype=float, copy=True)
    arr.flags.writeable = False
    if not np.all(np.isfinite(arr)) and name in ("lower", "upper"):
        raise ValueError(f"{name} contains non-finite values (NaN or Inf)")
    return arr


@dataclass(frozen=True)
class Interval:
    """A calibrated prediction interval.

    Attributes:
        lower: Lower bound, same shape as the mean it accompanies.
        upper: Upper bound.
        level: Nominal coverage, e.g. ``0.9`` for a 90% interval.
        method: How it was produced (``"conformal"``, ``"ensemble"``, ``"gp"``).
        empirical_coverage: Measured coverage on held-out data, if known.
            ``None`` means *not yet validated* — which is not the same as
            *valid*, and tools should present it that way.
    """

    lower: Array
    upper: Array
    level: float
    method: str
    empirical_coverage: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lower", _frozen_array(self.lower, "lower"))
        object.__setattr__(self, "upper", _frozen_array(self.upper, "upper"))
        if self.lower.shape != self.upper.shape:
            raise ValueError(
                f"lower and upper must have the same shape, "
                f"got {self.lower.shape} and {self.upper.shape}"
            )
        if not np.isfinite(self.level) or not 0.0 < self.level < 1.0:
            raise ValueError(f"level must be a finite number in (0, 1), got {self.level}")
        if np.any(~(self.upper >= self.lower)):
            raise ValueError("upper bound is below lower bound somewhere")
        if not self.method:
            raise ValueError("method must be a non-empty string")
        ec = self.empirical_coverage
        if ec is not None and (not np.isfinite(ec) or not 0.0 <= ec <= 1.0):
            raise ValueError(f"empirical_coverage must be in [0, 1], got {ec}")

    @property
    def width(self) -> Array:
        """Interval width, elementwise."""
        return self.upper - self.lower

    @property
    def is_validated(self) -> bool:
        """True only if empirical coverage has actually been measured."""
        return self.empirical_coverage is not None

    def coverage_error(self) -> float | None:
        """Signed difference between empirical and nominal coverage.

        Negative means the interval is over-confident — it covers less often
        than it claims, which is the dangerous direction.
        """
        if self.empirical_coverage is None:
            return None
        return self.empirical_coverage - self.level

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain JSON-compatible types."""
        return {
            "lower": self.lower.tolist(),
            "upper": self.upper.tolist(),
            "level": self.level,
            "method": self.method,
            "empirical_coverage": self.empirical_coverage,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Interval:
        """Reconstruct from :meth:`to_dict` output."""
        return cls(
            lower=np.asarray(d["lower"], dtype=float),
            upper=np.asarray(d["upper"], dtype=float),
            level=float(d["level"]),
            method=str(d["method"]),
            empirical_coverage=(
                None
                if d.get("empirical_coverage") is None
                else float(d["empirical_coverage"])
            ),
        )


@dataclass(frozen=True)
class Forecast:
    """The output of a forecasting tool.

    Attributes:
        t: Time grid, shape ``(n_steps,)``.
        x: State trajectory, shape ``(n_steps, n_states)``.
        y: Observation trajectory, shape ``(n_steps, n_outputs)``, if computed.
        energy: ``H(x)`` along the trajectory, for models that have it. This is
            what makes a structural violation visible: for a passive system
            with ``u = 0`` it must be non-increasing.
        interval: Calibrated uncertainty, if attached.
        meta: Free-form provenance (integrator used, step size, seed).
    """

    t: Array
    x: Array
    y: Array | None = None
    energy: Array | None = None
    interval: Interval | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "t", _frozen_array(self.t, "t"))
        object.__setattr__(self, "x", _frozen_array(self.x, "x"))
        if self.x.ndim != 2:
            raise ValueError(
                f"x must be 2-D (n_steps, n_states), got shape {self.x.shape}"
            )
        if self.t.ndim != 1:
            raise ValueError(f"t must be 1-D (n_steps,), got shape {self.t.shape}")
        n = self.x.shape[0]
        if self.t.shape[0] != n:
            raise ValueError(
                f"t and x disagree on the number of steps: {self.t.shape[0]} vs {n}"
            )
        for name in ("y", "energy"):
            v = getattr(self, name)
            if v is not None:
                arr = _frozen_array(v, name)
                object.__setattr__(self, name, arr)
                if arr.shape[0] != n:
                    raise ValueError(
                        f"{name} has {arr.shape[0]} steps but the trajectory has {n}"
                    )
        if self.interval is not None and self.interval.lower.shape[0] != n:
            raise ValueError(
                f"interval has {self.interval.lower.shape[0]} steps "
                f"but the trajectory has {n}"
            )

    @property
    def n_steps(self) -> int:
        """Number of time steps in this trajectory."""
        return int(self.x.shape[0])

    @property
    def n_states(self) -> int:
        """State dimension of this trajectory."""
        return int(self.x.shape[1])

    def energy_is_non_increasing(self, tol: float = 1e-9) -> bool:
        """Check the passivity signature on this trajectory.

        Returns ``True`` when no step increases the stored energy by more than
        ``tol``. Meaningful only for an unforced (``u = 0``) run of a passive
        model; a forced trajectory may legitimately gain energy through the
        port.

        Raises:
            ValueError: If the forecast carries no energy trace, if that trace
                is too short to have a trend, or if it contains non-finite
                values. This check refuses to answer on data it cannot trust —
                a diverged run must not read as "passive".
        """
        if self.energy is None:
            raise ValueError(
                "This forecast has no energy trace. Only models satisfying "
                "PortHamiltonianModel produce one."
            )
        if self.energy.shape[0] < 2:
            raise ValueError(
                f"Need at least 2 energy samples to check a trend, "
                f"got {self.energy.shape[0]}."
            )
        if not np.all(np.isfinite(self.energy)):
            raise ValueError(
                "Energy trace contains non-finite values; the integration "
                "diverged. This is a failure, not a passive trajectory."
            )
        return bool(np.all(np.diff(self.energy) <= tol))


@dataclass(frozen=True)
class MetricSet:
    """Forecast accuracy metrics.

    ``skill`` is the headline number, not ``r2``. Skill is the model's error
    divided by a baseline's error, so it answers the only question that
    matters: is this better than the obvious thing? A model with an excellent
    R-squared and a skill score above 1 is worse than persistence, and R² will
    never tell you.

    Attributes:
        extra: Domain-specific metrics that do not belong in the closed set
            above. Present so that adding one metric does not require a release
            of this package and a version bump across the ecosystem.
    """

    rmse: float
    mae: float
    skill: float
    baseline_name: str
    mase: float | None = None
    theil_u: float | None = None
    crps: float | None = None
    picp: float | None = None
    mpiw: float | None = None
    r2: float | None = None
    extra: dict[str, float] = field(default_factory=dict)

    @property
    def beats_baseline(self) -> bool:
        """True when the model has lower error than its baseline."""
        return self.skill < 1.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise, dropping metrics that were not computed."""
        d = {
            k: v
            for k, v in {
                "rmse": self.rmse,
                "mae": self.mae,
                "skill": self.skill,
                "baseline_name": self.baseline_name,
                "mase": self.mase,
                "theil_u": self.theil_u,
                "crps": self.crps,
                "picp": self.picp,
                "mpiw": self.mpiw,
                "r2": self.r2,
            }.items()
            if v is not None
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetricSet:
        """Reconstruct from :meth:`to_dict` output, ignoring unknown keys."""
        known = {
            "rmse",
            "mae",
            "skill",
            "baseline_name",
            "mase",
            "theil_u",
            "crps",
            "picp",
            "mpiw",
            "r2",
            "extra",
        }
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass(frozen=True)
class Report:
    """The output of an evaluation protocol.

    Attributes:
        metrics: Per-fold metric sets.
        protocol_name: Which evaluation protocol produced this.
        leakage_free: Whether the split protocol was leakage-free. A report
            with ``False`` here measures interpolation, not forecasting, and
            says so on the first line of every summary.
        n_folds: Number of folds evaluated. Must equal ``len(metrics)``.
        calibration: Coverage diagnostics, if uncertainty was evaluated.
        meta: Free-form provenance.
    """

    metrics: tuple[MetricSet, ...]
    protocol_name: str
    leakage_free: bool
    n_folds: int
    calibration: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", tuple(self.metrics))
        if self.n_folds != len(self.metrics):
            raise ValueError(
                f"n_folds is {self.n_folds} but {len(self.metrics)} metric "
                f"sets were supplied"
            )

    @property
    def mean_skill(self) -> float:
        """Mean skill score across folds, or NaN when there are no folds."""
        if not self.metrics:
            return float("nan")
        return float(np.mean([m.skill for m in self.metrics]))

    def summary(self) -> str:
        """A short human-readable summary, leading with the caveat if any."""
        lines = []
        if not self.leakage_free:
            lines.append(
                "WARNING: this protocol is not leakage-free. These numbers "
                "measure interpolation, not forecasting."
            )
        lines.append(f"protocol: {self.protocol_name}  ({self.n_folds} folds)")
        if not self.metrics:
            lines.append("skill:    n/a (no folds evaluated)")
        else:
            skill = self.mean_skill
            verdict = "beats" if skill < 1.0 else "LOSES TO"
            lines.append(
                f"skill:    {skill:.3f} vs {self.metrics[0].baseline_name} "
                f"({verdict} baseline)"
            )
        if self.calibration:
            nominal = self.calibration.get("level")
            empirical = self.calibration.get("empirical_coverage")
            try:
                if nominal is not None and empirical is not None:
                    lines.append(
                        f"coverage: {float(empirical):.3f} empirical "
                        f"vs {float(nominal):.3f} nominal"
                    )
            except (TypeError, ValueError):
                lines.append(f"coverage: {empirical!r} empirical vs {nominal!r} nominal")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain JSON-compatible types.

        This is the canonical shape for
        :attr:`~otwin.interfaces.TwinManifest.validation`. Use it rather than
        hand-rolling keys, so that Python, Julia and MATLAB agree.
        """
        return {
            "protocol": self.protocol_name,
            "leakage_free": self.leakage_free,
            "n_folds": self.n_folds,
            "mean_skill": None if not self.metrics else self.mean_skill,
            "metrics": [m.to_dict() for m in self.metrics],
            "calibration": self.calibration,
            "meta": self.meta or None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Report:
        """Reconstruct from :meth:`to_dict` output."""
        metrics = tuple(MetricSet.from_dict(m) for m in d.get("metrics", []))
        return cls(
            metrics=metrics,
            protocol_name=str(d["protocol"]),
            leakage_free=d["leakage_free"] is True,
            n_folds=int(d.get("n_folds", len(metrics))),
            calibration=d.get("calibration"),
            meta=d.get("meta") or {},
        )
