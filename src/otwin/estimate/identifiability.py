"""Was the parameter determined by the data, or chosen by the noise?

A coefficient is *identified* when two different values of it would have
produced observably different predictions. If they would not — because two
basis columns are nearly proportional, because the record is shorter than the
time constant it is asked to reveal, or because refitting on a resampled fleet
returns a different number every time — then whatever value the fit returned
was selected by the noise, and everything that extrapolates through it is
extrapolating the noise.

This is the fourth ground for refusal, alongside operating range, horizon and
calibration, and it is the one that decided every result in the replication
series: a free exponent fitted on 100 cycles, a two-term law whose columns are
proportional early in life, a second mechanism fitted to three tests per
system. None of those laws was wrong. None was identified.

The check has three parts, each answering a different way a parameter can fail
to be identified:

1. **Collinearity.** Can this column of the design matrix be reproduced from
   the others? If ``R²`` of that regression is near one, the data fix the sum
   of the coefficients but not the split. This is the early-life two-term law.
2. **Span.** For a parameter that is a time constant, is the record longer
   than it? A plateau cannot be seen from before the knee, and a knee cannot be
   seen from before it starts. This is the Kern–Seaton trap.
3. **Stability.** Refit on bootstrap resamples of the *units* (cells, systems)
   and look at the spread of each coefficient. A coefficient of variation near
   one, or a sign that flips, is a parameter the fleet does not determine.

None of these is a proof. All of them are what a careful engineer does by hand
before believing a fit, and the point of writing them down is that a
:class:`~otwin.interfaces.TwinManifest` can then record the verdict and an
:class:`~otwin.advise.Envelope` can refuse on it.

Example:
    Two columns that are nearly the same power of ``n`` cannot be told apart on
    a short window; on a long one they can.

    >>> import numpy as np
    >>> n = np.arange(1.0, 101.0)
    >>> X = np.column_stack([n**0.5, n**0.6])
    >>> y = 0.01 * n**0.5 + 0.002 * n**0.6
    >>> rep = identifiability(X, y, names=("c1", "c2"), n_boot=50, seed=0)
    >>> rep.identified
    False
    >>> [p.name for p in rep.parameters if not p.identified]
    ['c1', 'c2']
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

__all__ = ["ParameterVerdict", "IdentifiabilityReport", "identifiability"]

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ParameterVerdict:
    """The identifiability verdict for one parameter.

    Attributes:
        name: Parameter name.
        identified: ``True`` only if every check that applied passed.
        collinearity: ``R²`` of this design column regressed on the others.
            Near one means the column is redundant.
        span_ratio: Record span divided by this parameter's time constant, if
            one was supplied; ``None`` otherwise.
        cv: Bootstrap coefficient of variation, ``std / |mean|``; ``None`` if
            the bootstrap could not run.
        sign_stable: Whether the bootstrap coefficient kept one sign.
        reasons: Human-readable reasons for a failure, empty on success.
    """

    name: str
    identified: bool
    collinearity: float
    span_ratio: float | None
    cv: float | None
    sign_stable: bool
    reasons: tuple[str, ...] = ()

    def __str__(self) -> str:
        status = "identified" if self.identified else "NOT identified"
        parts = [f"collinearity R²={self.collinearity:.3f}"]
        if self.span_ratio is not None:
            parts.append(f"span/τ={self.span_ratio:.2f}")
        if self.cv is not None:
            parts.append(f"bootstrap CV={self.cv:.2f}")
        head = f"{self.name}: {status} ({', '.join(parts)})"
        if self.reasons:
            head += "\n    " + "\n    ".join(self.reasons)
        return head


@dataclass(frozen=True)
class IdentifiabilityReport:
    """What the data could and could not determine about a fit.

    Attributes:
        parameters: One verdict per parameter, in design-matrix column order.
        condition_number: Of the column-standardised design matrix.
        n_rows: Number of observations used.
        n_units: Number of units resampled in the bootstrap (rows if no groups).
        thresholds: The limits the verdicts were judged against.
    """

    parameters: tuple[ParameterVerdict, ...]
    condition_number: float
    n_rows: int
    n_units: int
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def identified(self) -> bool:
        """``True`` only if every parameter is identified."""
        return all(p.identified for p in self.parameters)

    @property
    def verdicts(self) -> dict[str, bool]:
        """``{name: identified}`` — the shape :meth:`TwinManifest.identified_by` takes."""
        return {p.name: p.identified for p in self.parameters}

    def to_dict(self) -> dict[str, Any]:
        return {
            "identified": self.identified,
            "condition_number": float(self.condition_number),
            "n_rows": int(self.n_rows),
            "n_units": int(self.n_units),
            "thresholds": dict(self.thresholds),
            "parameters": [
                {
                    "name": p.name,
                    "identified": p.identified,
                    "collinearity": float(p.collinearity),
                    "span_ratio": None if p.span_ratio is None else float(p.span_ratio),
                    "cv": None if p.cv is None else float(p.cv),
                    "sign_stable": p.sign_stable,
                    "reasons": list(p.reasons),
                }
                for p in self.parameters
            ],
        }

    def __str__(self) -> str:
        head = (
            f"identifiability: {'all identified' if self.identified else 'NOT all identified'} "
            f"({self.n_rows} rows, {self.n_units} units, condition number {self.condition_number:.3g})"
        )
        return head + "\n" + "\n".join("  " + str(p) for p in self.parameters)


def _solve(X: Array, y: Array, nonneg: bool) -> Array:
    if nonneg:
        from scipy.optimize import nnls

        coef, _ = nnls(X, y)
        return np.asarray(coef, dtype=float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return np.asarray(coef, dtype=float)


def _collinearity(X: Array) -> Array:
    """R² of each column regressed on the others (1.0 means fully redundant)."""
    n, k = X.shape
    out = np.zeros(k)
    if k == 1:
        return out
    for j in range(k):
        others = np.delete(X, j, axis=1)
        A = np.column_stack([others, np.ones(n)])
        target = X[:, j]
        coef, *_ = np.linalg.lstsq(A, target, rcond=None)
        resid = target - A @ coef
        ss_tot = float(np.sum((target - target.mean()) ** 2))
        out[j] = 1.0 - float(np.sum(resid**2)) / ss_tot if ss_tot > 0 else 1.0
    return np.clip(out, 0.0, 1.0)


def identifiability(
    X: npt.ArrayLike,
    y: npt.ArrayLike,
    *,
    names: Sequence[str] | None = None,
    groups: npt.ArrayLike | None = None,
    span: float | None = None,
    time_constants: dict[str, float] | None = None,
    nonneg: bool = False,
    max_collinearity: float = 0.95,
    min_span_ratio: float = 1.0,
    max_cv: float = 0.5,
    n_boot: int = 200,
    seed: int | None = 0,
) -> IdentifiabilityReport:
    """Decide, per parameter, whether the data determined it.

    Args:
        X: Design matrix, one column per parameter. For a fade law that is the
            basis evaluated at the observations — ``n**z1`` and ``n**z2``, or
            ``t**z`` and ``ΔEFC``.
        y: Observations, same length as ``X`` has rows.
        names: Parameter names, one per column. Defaults to ``p0, p1, …``.
        groups: Unit label per row (cell id, system id). The bootstrap
            resamples *units*, because rows from one unit are not independent
            draws. Without groups it resamples rows, which overstates stability.
        span: Length of the record in the units of ``time_constants``.
        time_constants: ``{name: τ}`` for parameters that are time constants or
            imply one. The span check applies only to these.
        nonneg: Fit with non-negative least squares (``scipy.optimize.nnls``)
            rather than plain least squares. Use it if that is how the twin is
            fitted; the stability check must use the same solver.
        max_collinearity: ``R²`` above which a column is called redundant.
        min_span_ratio: ``span / τ`` below which a time constant is called
            unseen.
        max_cv: Bootstrap coefficient of variation above which a coefficient
            is called unstable.
        n_boot: Bootstrap resamples. ``0`` skips the stability check.
        seed: Random seed for the bootstrap.

    Returns:
        An :class:`IdentifiabilityReport`. It never raises on a failed check;
        the verdict is the result.

    Raises:
        ValueError: On shape mismatches, which are programming errors.
    """
    X_ = np.atleast_2d(np.asarray(X, dtype=float))
    if X_.shape[0] == 1 and X_.shape[1] > 1 and np.asarray(y).size == X_.shape[1]:
        X_ = X_.T
    y_ = np.asarray(y, dtype=float).reshape(-1)
    n, k = X_.shape
    if y_.size != n:
        raise ValueError(f"X has {n} rows but y has {y_.size} values")
    if names is None:
        names = tuple(f"p{j}" for j in range(k))
    if len(names) != k:
        raise ValueError(f"{len(names)} names for {k} columns")
    thresholds = {
        "max_collinearity": float(max_collinearity),
        "min_span_ratio": float(min_span_ratio),
        "max_cv": float(max_cv),
    }

    # 1. collinearity on column-standardised X
    scale = np.linalg.norm(X_, axis=0)
    scale[scale == 0] = 1.0
    Xs = X_ / scale
    coll = _collinearity(Xs)
    sv = np.linalg.svd(Xs, compute_uv=False)
    cond = float(sv[0] / sv[-1]) if sv[-1] > 0 else float("inf")

    # 3. stability by bootstrap over units
    rng = np.random.default_rng(seed)
    unit_of = np.arange(n) if groups is None else np.asarray(groups)
    units = np.unique(unit_of)
    cvs: list[float | None] = [None] * k
    signs_ok = [True] * k
    if n_boot > 0 and len(units) >= 2:
        draws = np.empty((n_boot, k))
        for b in range(n_boot):
            pick = rng.choice(units, size=len(units), replace=True)
            idx = np.concatenate([np.flatnonzero(unit_of == u) for u in pick])
            if idx.size < k:
                draws[b] = np.nan
                continue
            try:
                draws[b] = _solve(X_[idx], y_[idx], nonneg)
            except (np.linalg.LinAlgError, ValueError):
                draws[b] = np.nan
        good = np.isfinite(draws).all(axis=1)
        if good.sum() >= 10:
            d = draws[good]
            mean = d.mean(axis=0)
            std = d.std(axis=0, ddof=1)
            for j in range(k):
                denom = abs(mean[j])
                cvs[j] = float(std[j] / denom) if denom > 0 else float("inf")
                # a coefficient that is zero on more than 10 % of resamples (NNLS
                # switching the term off) or that changes sign is not stable
                nonzero = d[:, j][d[:, j] != 0]
                if nonneg:
                    signs_ok[j] = bool((d[:, j] == 0).mean() <= 0.10)
                else:
                    signs_ok[j] = bool(
                        nonzero.size == 0
                        or (np.sign(nonzero) == np.sign(nonzero[0])).all()
                    )

    verdicts = []
    for j, name in enumerate(names):
        reasons: list[str] = []
        if coll[j] > max_collinearity:
            reasons.append(
                f"design column can be reproduced from the others (R²={coll[j]:.3f} > "
                f"{max_collinearity}); the data fix a combination of coefficients, not this one"
            )
        span_ratio = None
        if time_constants and name in time_constants and span is not None:
            tau = float(time_constants[name])
            span_ratio = float(span / tau) if tau > 0 else float("inf")
            if span_ratio < min_span_ratio:
                reasons.append(
                    f"record spans {span:g} but the fitted time constant is {tau:g} "
                    f"(ratio {span_ratio:.2f} < {min_span_ratio}); the process the parameter "
                    "describes has not been observed"
                )
        cv_j = cvs[j]
        if cv_j is not None and cv_j > max_cv:
            reasons.append(
                f"bootstrap over {len(units)} units gives CV={cv_j:.2f} > {max_cv}; "
                "refitting on a resampled fleet returns a different value"
            )
        if not signs_ok[j]:
            reasons.append(
                "coefficient switches off or changes sign across bootstrap resamples"
            )
        verdicts.append(
            ParameterVerdict(
                name=str(name),
                identified=not reasons,
                collinearity=float(coll[j]),
                span_ratio=span_ratio,
                cv=cvs[j],
                sign_stable=signs_ok[j],
                reasons=tuple(reasons),
            )
        )
    return IdentifiabilityReport(
        parameters=tuple(verdicts),
        condition_number=cond,
        n_rows=int(n),
        n_units=int(len(units)),
        thresholds=thresholds,
    )
