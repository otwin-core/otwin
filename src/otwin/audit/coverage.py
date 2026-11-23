"""Does a forecast range hold what it states, overall and by horizon?

Given observations, point forecasts and the stated range around them, from
Otwin or from any other tool, :func:`coverage_audit` reports four things. The
coverage actually observed, with its own confidence interval. The median signed
error, which is the bias. The mean width of the range. The number of contrasts
(observation against forecast) behind those numbers.

By default it reports one row over every contrast. Horizon tranches are off
unless you ask for them. A range calibrated on the average horizon is often
too wide at the start and too narrow at the end, and the overall number hides
that. ``tranches=[0, 6, 12, 24]`` reports horizons ``(0, 6]``, ``(6, 12]`` and
``(12, 24]`` separately.

Three choices are deliberate.

**The interval on coverage is Clopper-Pearson.** It is exact for a binomial
count and never narrower than it should be, at any sample size. A row with 12
contrasts and 12 hits gets an interval that reaches well below 90 %, which is
what 12 contrasts can show.

**A range that covers more than it states is not a success.** The verdict
reads ``wider than stated`` when the whole confidence interval lies above the
stated level, in the same way as ``narrower than stated`` when it lies below.

**Too few contrasts give a refusal that names the count.** A row with fewer
than the minimum carries the count, the minimum and nothing else. It has no
coverage, no interval, no bias and no width. The default minimum is the fewest
contrasts at which a range that holds its level exactly is expected to miss at
least once: ``ceil(1 / (1 - level))``, which is 10 at 90 %. Below it, 100 %
coverage is the likeliest outcome for a range that is exactly right.

One caveat sits with the interval and is printed in the report. Clopper-Pearson
treats the contrasts as independent. Contrasts from overlapping rolling-origin
forecasts are not independent, so the real uncertainty is wider than the
interval shown.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.stats import beta

__all__ = ["CoverageAudit", "CoverageRow", "coverage_audit", "default_min_contrasts"]

Array = npt.NDArray[np.floating]

_INDEPENDENCE_NOTE = (
    "The confidence interval treats contrasts as independent. Contrasts from "
    "overlapping forecasts are not, so the true uncertainty is wider."
)

#: Same guard as :mod:`otwin.forecast.conformal`. ``1 / (1 - 0.9)`` is
#: ``9.999999999999998``, and a bare ceil of a slightly larger burr asks for one
#: contrast too many.
_DECIMALS = 12


def _pct(x: float, decimals: int = 1) -> str:
    """``0.9`` as ``"90.0 %"``, with the space the rest of Otwin's text uses."""
    return f"{round(100.0 * x, decimals):.{decimals}f} %"


def _check_unit(name: str, x: float) -> None:
    """Raise unless ``x`` is a finite number strictly between 0 and 1."""
    if not np.isfinite(x) or not 0.0 < x < 1.0:
        raise ValueError(f"{name} must be a finite number in (0, 1), got {x!r}")


def default_min_contrasts(level: float) -> int:
    """The fewest contrasts at which a range at ``level`` is expected to miss once.

    That is ``ceil(1 / (1 - level))``. With fewer contrasts, a range that holds
    its level exactly most likely shows no miss at all. Its observed coverage
    is then 100 % whether the range is right or far too wide.

    Example:
        >>> default_min_contrasts(0.9), default_min_contrasts(0.95), default_min_contrasts(0.8)
        (10, 20, 5)
    """
    _check_unit("level", level)
    return int(np.ceil(round(1.0 / (1.0 - level), _DECIMALS)))


def _clopper_pearson(k: int, n: int, confidence: float) -> tuple[float, float]:
    """Exact two-sided binomial interval for ``k`` successes in ``n`` trials."""
    a = 1.0 - confidence
    low = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    high = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return low, high


@dataclass(frozen=True)
class CoverageRow:
    """One row of the audit: every contrast, or one horizon tranche.

    The numeric fields are ``None`` when the row is a refusal. They are never
    filled with zeros.

    Attributes:
        label: ``"all"`` for the overall row, ``"(lo, hi]"`` for a tranche.
        lo: Lower horizon boundary, exclusive. ``None`` for the overall row.
        hi: Upper horizon boundary, inclusive. ``None`` for the overall row.
        n_contrasts: How many observation-forecast pairs fall in the row.
        n_required: The minimum it was held to.
        n_covered: How many observations fell inside the range, ends included.
        coverage: ``n_covered / n_contrasts``.
        ci_low: Lower end of the Clopper-Pearson interval on coverage.
        ci_high: Upper end of it.
        median_error: Median of ``observed - prediction``. A positive value
            means the forecast runs low.
        mean_width: Mean of ``upper - lower``.
        verdict: ``"consistent with stated"``, ``"narrower than stated"`` (the
            whole interval is below the level) or ``"wider than stated"`` (the
            whole interval is above it).
        refusal: Why the row has no numbers, or ``None``.
    """

    label: str
    lo: float | None
    hi: float | None
    n_contrasts: int
    n_required: int
    n_covered: int | None = None
    coverage: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    median_error: float | None = None
    mean_width: float | None = None
    verdict: str | None = None
    refusal: str | None = None

    @property
    def answered(self) -> bool:
        """``True`` when the row has enough contrasts to give numbers."""
        return self.refusal is None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form of the row."""
        return {
            "label": self.label,
            "lo": self.lo,
            "hi": self.hi,
            "answered": self.answered,
            "refusal": self.refusal,
            "n_contrasts": self.n_contrasts,
            "n_required": self.n_required,
            "n_covered": self.n_covered,
            "coverage": self.coverage,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "median_error": self.median_error,
            "mean_width": self.mean_width,
            "verdict": self.verdict,
        }


def _row(
    label: str,
    lo: float | None,
    hi: float | None,
    obs: Array,
    pred: Array,
    low: Array,
    up: Array,
    level: float,
    confidence: float,
    required: int,
) -> CoverageRow:
    """One row from the contrasts already selected for it."""
    n = int(obs.size)
    if n < required:
        noun = "contrast" if n == 1 else "contrasts"
        return CoverageRow(
            label=label,
            lo=lo,
            hi=hi,
            n_contrasts=n,
            n_required=required,
            refusal=f"{n} {noun}; the minimum is {required}",
        )
    k = int(np.count_nonzero((low <= obs) & (obs <= up)))
    ci_low, ci_high = _clopper_pearson(k, n, confidence)
    if ci_high < level:
        verdict = "narrower than stated"
    elif ci_low > level:
        verdict = "wider than stated"
    else:
        verdict = "consistent with stated"
    return CoverageRow(
        label=label,
        lo=lo,
        hi=hi,
        n_contrasts=n,
        n_required=required,
        n_covered=k,
        coverage=k / n,
        ci_low=ci_low,
        ci_high=ci_high,
        median_error=float(np.median(obs - pred)),
        mean_width=float(np.mean(up - low)),
        verdict=verdict,
    )


@dataclass(frozen=True)
class CoverageAudit:
    """The coverage audit: one overall row, and per-tranche rows if asked for.

    Attributes:
        level: The coverage the range states.
        confidence: Confidence of the interval on observed coverage.
        min_contrasts: The minimum every row was held to.
        overall: The row over every contrast. This is the default report.
        tranches: One row per horizon tranche, or ``None`` when tranches were
            not asked for.
        boundaries: The tranche boundaries, or ``None``.
        n_outside: Contrasts whose horizon falls outside every tranche. They
            count in :attr:`overall` and in no tranche. ``None`` without
            tranches.
    """

    level: float
    confidence: float
    min_contrasts: int
    overall: CoverageRow
    tranches: tuple[CoverageRow, ...] | None = None
    boundaries: tuple[float, ...] | None = None
    n_outside: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form, as a section of an audit report.

        ``tranches`` is ``None`` when tranches are off, so the single-number
        report keeps the same keys it would have with them on.

        Example:
            >>> import json, numpy as np
            >>> y = np.zeros(40); d = coverage_audit(y, y, y - 1, y + 1, level=0.9).to_dict()
            >>> d["overall"]["coverage"], d["tranches"]
            (1.0, None)
            >>> _ = json.dumps(d, allow_nan=False)
        """
        return {
            "section": "coverage",
            "level": self.level,
            "confidence": self.confidence,
            "min_contrasts": self.min_contrasts,
            "convention": (
                "error = observed - prediction; covered when lower <= observed "
                "<= upper; tranche (lo, hi] holds horizons lo < h <= hi"
            ),
            "note": _INDEPENDENCE_NOTE,
            "overall": self.overall.to_dict(),
            "boundaries": None if self.boundaries is None else list(self.boundaries),
            "n_outside": self.n_outside,
            "tranches": (
                None if self.tranches is None else [t.to_dict() for t in self.tranches]
            ),
        }

    def to_html(self, heading_level: int = 2) -> str:
        """A self-contained ``<section>`` for an HTML audit report.

        One table. It has a single row by default, plus one row per tranche
        when tranches were asked for. A refused row shows its reason in place
        of numbers.

        Example:
            >>> import numpy as np
            >>> y = np.zeros(40)
            >>> out = coverage_audit(y, y, y - 1, y + 1, level=0.9).to_html()
            >>> out.count("<tr>")                 # header and the overall row
            2
        """
        lvl = min(max(int(heading_level), 1), 6)
        out = [
            '<section class="otwin-coverage">',
            f"<h{lvl}>Coverage of the stated {_pct(self.level, 0)} range</h{lvl}>",
            f"<p>Interval on coverage: Clopper-Pearson at {_pct(self.confidence, 0)}. "
            f"{html.escape(_INDEPENDENCE_NOTE)}</p>",
        ]
        if self.n_outside:
            verb = "contrast falls" if self.n_outside == 1 else "contrasts fall"
            out.append(
                f"<p>{self.n_outside} {verb} outside every tranche; "
                "they count only in the overall row.</p>"
            )
        out.append("<table>")
        out.append(
            "<thead><tr><th>Horizon</th><th>Contrasts</th><th>Coverage</th>"
            "<th>Interval</th><th>Median error</th><th>Mean width</th>"
            "<th>Verdict</th></tr></thead>"
        )
        out.append("<tbody>")
        rows = [self.overall, *(self.tranches or ())]
        for r in rows:
            label = html.escape(r.label)
            if not r.answered:
                out.append(
                    f'<tr class="refusal"><td>{label}</td><td>{r.n_contrasts}</td>'
                    f'<td colspan="5">Not computed: {html.escape(str(r.refusal))}.</td></tr>'
                )
                continue
            assert r.coverage is not None and r.ci_low is not None
            assert r.ci_high is not None
            out.append(
                f"<tr><td>{label}</td><td>{r.n_contrasts}</td>"
                f"<td>{_pct(r.coverage)}</td>"
                f"<td>{_pct(r.ci_low)} to {_pct(r.ci_high)}</td>"
                f"<td>{r.median_error:.6g}</td><td>{r.mean_width:.6g}</td>"
                f"<td>{html.escape(str(r.verdict))}</td></tr>"
            )
        out.append("</tbody>")
        out.append("</table>")
        out.append("</section>")
        return "\n".join(out)


def _fmt_edge(x: float) -> str:
    """A tranche boundary as written in a label: ``6.0`` as ``6``."""
    return f"{x:g}"


def coverage_audit(
    observed: Array | Sequence[float],
    prediction: Array | Sequence[float],
    lower: Array | Sequence[float],
    upper: Array | Sequence[float],
    *,
    level: float,
    horizons: Array | Sequence[float] | None = None,
    tranches: Sequence[float] | None = None,
    min_contrasts: int | None = None,
    confidence: float = 0.95,
) -> CoverageAudit:
    """Observed coverage, bias and width of a forecast range, overall or by horizon.

    Args:
        observed: What the asset did.
        prediction: The point forecast for each observation.
        lower: Lower end of the stated range, one per observation.
        upper: Upper end of the stated range.
        level: The coverage the range states, for example ``0.9``.
        horizons: The forecast horizon of each contrast, in steps or in time.
            Needed only with ``tranches``.
        tranches: Horizon boundaries ``[b0, b1, ..., bk]``, strictly
            increasing, giving the tranches ``(b0, b1], ..., (b_{k-1}, bk]``.
            ``None``, the default, reports the single overall row only.
        min_contrasts: The fewest contrasts a row is answered from. Rows with
            fewer are refused, and the refusal names the count. This includes
            the overall row. The default is :func:`default_min_contrasts`,
            which is 10 at 90 %. A value you give is used as given.
        confidence: Confidence of the interval on observed coverage.

    Returns:
        A :class:`CoverageAudit`.

    Raises:
        ValueError: If the arrays differ in length or contain NaN or Inf, if
            any ``lower`` exceeds its ``upper``, if ``tranches`` is given
            without ``horizons`` or is not strictly increasing with at least
            two boundaries, if ``min_contrasts`` is below 1, or if ``level``
            or ``confidence`` is outside (0, 1). These are errors in the call.
            Too few contrasts is a refusal, not an error.

    Example:
        >>> import numpy as np
        >>> h = np.tile(np.arange(1, 13), 20)            # 20 forecasts, 12 steps each
        >>> y = np.zeros(h.size)
        >>> half = np.where(h <= 6, 1.0, 0.0)            # the range collapses after step 6
        >>> pred = np.where(h <= 6, 0.0, 0.5)
        >>> a = coverage_audit(y, pred, pred - half, pred + half, level=0.9)
        >>> a.overall.coverage, a.tranches                # the default: one number
        (0.5, None)
        >>> a = coverage_audit(y, pred, pred - half, pred + half, level=0.9,
        ...                    horizons=h, tranches=[0, 6, 12, 24])
        >>> [(t.label, t.n_contrasts, t.coverage) for t in a.tranches]
        [('(0, 6]', 120, 1.0), ('(6, 12]', 120, 0.0), ('(12, 24]', 0, None)]
        >>> a.tranches[0].verdict, a.tranches[1].median_error
        ('wider than stated', -0.5)
        >>> a.tranches[2].refusal
        '0 contrasts; the minimum is 10'
    """
    obs = np.asarray(observed, dtype=float).ravel()
    pred = np.asarray(prediction, dtype=float).ravel()
    low = np.asarray(lower, dtype=float).ravel()
    up = np.asarray(upper, dtype=float).ravel()

    _check_unit("level", level)
    _check_unit("confidence", confidence)
    sizes = {obs.size, pred.size, low.size, up.size}
    if len(sizes) != 1:
        raise ValueError(
            "observed, prediction, lower and upper must be the same length, got "
            f"{obs.size}, {pred.size}, {low.size} and {up.size}"
        )
    for name, arr in (
        ("observed", obs),
        ("prediction", pred),
        ("lower", low),
        ("upper", up),
    ):
        if not np.all(np.isfinite(arr)):
            raise ValueError(
                f"{name} contains NaN or Inf; drop missing contrasts before the "
                "audit so the count behind each row is the count actually used"
            )
    if np.any(low > up):
        bad = int(np.count_nonzero(low > up))
        raise ValueError(f"lower exceeds upper at {bad} contrasts")

    if min_contrasts is None:
        required = default_min_contrasts(level)
    else:
        required = int(min_contrasts)
        if required < 1:
            raise ValueError(f"min_contrasts must be at least 1, got {min_contrasts!r}")

    def row(label: str, lo: float | None, hi: float | None, mask: Any) -> CoverageRow:
        return _row(
            label,
            lo,
            hi,
            obs[mask],
            pred[mask],
            low[mask],
            up[mask],
            level,
            confidence,
            required,
        )

    overall = row("all", None, None, slice(None))
    if tranches is None:
        return CoverageAudit(
            level=float(level),
            confidence=float(confidence),
            min_contrasts=required,
            overall=overall,
        )

    if horizons is None:
        raise ValueError("tranches need horizons: the horizon of every contrast")
    hor = np.asarray(horizons, dtype=float).ravel()
    if hor.size != obs.size:
        raise ValueError(
            f"horizons must be the same length as observed, got {hor.size} and {obs.size}"
        )
    if not np.all(np.isfinite(hor)):
        raise ValueError("horizons contain NaN or Inf")
    edges = np.asarray(tranches, dtype=float).ravel()
    if edges.size < 2:
        raise ValueError(
            f"tranches needs at least two boundaries to make one tranche, got {edges.size}"
        )
    if not np.all(np.isfinite(edges)) or np.any(np.diff(edges) <= 0):
        raise ValueError(
            f"tranche boundaries must be finite and strictly increasing, got {list(edges)}"
        )

    rows = []
    inside = np.zeros(hor.size, dtype=bool)
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (hor > lo) & (hor <= hi)
        inside |= mask
        rows.append(
            row(f"({_fmt_edge(lo)}, {_fmt_edge(hi)}]", float(lo), float(hi), mask)
        )
    return CoverageAudit(
        level=float(level),
        confidence=float(confidence),
        min_contrasts=required,
        overall=overall,
        tranches=tuple(rows),
        boundaries=tuple(float(e) for e in edges),
        n_outside=int(np.count_nonzero(~inside)),
    )
