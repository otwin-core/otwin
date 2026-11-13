"""How much margin above a reference curve can be promised, and at what risk.

A reference curve is what the asset is expected to deliver: a pump curve, a
rated capacity, a contracted power, or the model's own forecast. A promise of
*margin* ``m`` above it is a promise that the asset will deliver at least
``reference + m``. The question an engineer signs off on is how often that
promise is broken.

The answer here comes from the residuals alone, ``residual = delivered -
reference``, as the asset actually behaved. There is no normal fit, no standard
deviation and no tail model. A margin is broken exactly when the residual
falls short of it, so the probability of not delivering ``m`` is the share of
residuals below ``m``. The margin at a stated risk is an order statistic of the
same residuals.

Two choices are deliberate.

**The margin at a risk keeps its promise on the next residual, not only on the
past ones.** The plug-in answer, the ``risk``-quantile of the sample, is
optimistic by about one residual in ``n + 1``. The margin returned here is the
``j``-th smallest residual with ``j = floor(risk * (n + 1))``. For exchangeable
residuals, the probability that the next one falls below it is ``j / (n + 1)``,
which is at most ``risk``. Its share of past residuals below it is also at most
``risk``, so the margin agrees with the probability table next to it.

**Too few residuals give a refusal, not a number.** Below
``ceil(1 / risk) - 1`` residuals (19 at 5 %), no order statistic carries that
guarantee. The sample minimum is still a number, and it is the one a
hand-rolled implementation returns. Here the result says how many residuals
there are and how many are needed, and carries no probability and no margin.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

__all__ = ["DEFAULT_RISK_LEVELS", "MarginRisk", "margin_risk", "min_residuals_for"]

Array = npt.NDArray[np.floating]
IntArray = npt.NDArray[np.integer]

#: The risk levels reported when none are given: 5, 10 and 20 %.
DEFAULT_RISK_LEVELS: tuple[float, ...] = (0.05, 0.10, 0.20)

#: Round ``risk * (n + 1)`` to this many decimals before the floor.
#: ``0.05 * 20`` is ``1.0000000000000002``, which is harmless, but ``0.1 * 30``
#: is ``3.0000000000000004`` and ``0.7 * 10`` is ``6.999999999999999``. In the
#: second case a bare floor gives one rank too few. This uses the same guard
#: as :mod:`otwin.forecast.conformal`.
_RANK_DECIMALS = 12


def _rank(risk: float, n: int) -> int:
    """``floor(risk * (n + 1))``, without the floating-point burr."""
    return int(np.floor(round(risk * (n + 1), _RANK_DECIMALS)))


def min_residuals_for(risk: float) -> int:
    """The fewest residuals at which a margin at ``risk`` exists.

    This is the smallest ``n`` with ``floor(risk * (n + 1)) >= 1``, found from
    that definition and not from ``ceil(1 / risk) - 1``. The two agree in exact
    arithmetic but can differ by one in floating point.

    Example:
        >>> min_residuals_for(0.05), min_residuals_for(0.10), min_residuals_for(0.20)
        (19, 9, 4)
    """
    _check_risk(risk)
    n = 1
    while _rank(risk, n) < 1:
        n += 1
    return n


def _pct(x: float, decimals: int = 0) -> str:
    """``0.05`` as ``"5 %"``, with the space the rest of Otwin's text uses."""
    return f"{round(100.0 * x, decimals):.{decimals}f} %"


def _check_risk(risk: float) -> None:
    """Raise unless ``risk`` is a finite number strictly between 0 and 1."""
    if not np.isfinite(risk) or not 0.0 < risk < 1.0:
        raise ValueError(f"risk levels must be finite numbers in (0, 1), got {risk!r}")


@dataclass(frozen=True)
class MarginRisk:
    """The risk of not delivering each margin, or a refusal saying why not.

    The numeric fields are ``None`` when the result is a refusal, so code that
    ignores the refusal fails instead of reading a number nobody can stand
    behind.

    Attributes:
        reference: The reference curve the margins are measured from.
        margins: The margins asked about, in the order they were given.
        risk_levels: The stated risk levels.
        n_available: How many residuals were given.
        n_required: How many are needed: the stated minimum, or the fewest at
            which the smallest risk level exists, whichever is larger.
        probabilities: For each margin, the share of residuals below it, which
            is the empirical probability of not delivering it.
        n_residuals: For each margin, how many residuals that probability was
            computed from.
        n_short: For each margin, how many residuals fell below it. Equal to
            ``probabilities * n_residuals``. It is kept as a count so the
            fraction can be checked by hand.
        margin_at_risk: For each risk level, the largest margin whose risk of
            not being delivered on the next residual is at most that level.
            A negative value means even the reference curve cannot be promised
            at that risk.
        refusal: Why there is no answer, or ``None`` when there is one.
    """

    reference: Array
    margins: Array
    risk_levels: tuple[float, ...]
    n_available: int
    n_required: int
    probabilities: Array | None = None
    n_residuals: IntArray | None = None
    n_short: IntArray | None = None
    margin_at_risk: Array | None = None
    refusal: str | None = None

    @property
    def answered(self) -> bool:
        """``True`` when there are enough residuals to give numbers."""
        return self.refusal is None

    def __bool__(self) -> bool:
        return self.answered

    def promised(self, risk: float) -> Array:
        """The curve that can be promised at ``risk``: ``reference + margin``.

        Raises:
            ValueError: If the result is a refusal, or ``risk`` is not one of
                :attr:`risk_levels`.

        Example:
            >>> import numpy as np
            >>> res = np.arange(1.0, 101.0)               # delivered - reference
            >>> r = margin_risk(res, reference=[10.0, 12.0], margins=[0.0])
            >>> r.promised(0.05).tolist()                 # 5th smallest of 100
            [15.0, 17.0]
        """
        if self.margin_at_risk is None:
            raise ValueError(f"no promised curve: {self.refusal}")
        for level, margin in zip(self.risk_levels, self.margin_at_risk, strict=True):
            if np.isclose(level, risk, rtol=0.0, atol=1e-12):
                return self.reference + margin
        raise ValueError(
            f"risk {risk!r} was not one of the stated levels {list(self.risk_levels)}"
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form, as a section of an audit report.

        A refusal keeps ``refusal``, the counts and the inputs, and sets every
        computed field to ``None``. It is never filled with zeros.

        Example:
            >>> import json
            >>> d = margin_risk([0.1] * 5, reference=1.0, margins=[0.0]).to_dict()
            >>> d["refusal"]
            '5 residuals; at least 19 are needed for a margin at 5 % risk'
            >>> d["probabilities"] is None and d["margin_at_risk"] is None
            True
            >>> _ = json.dumps(d, allow_nan=False)
        """

        def floats(a: Array | None) -> list[float] | None:
            return None if a is None else [float(v) for v in a]

        def ints(a: IntArray | None) -> list[int] | None:
            return None if a is None else [int(v) for v in a]

        at_risk = None
        if self.margin_at_risk is not None:
            at_risk = [
                {"risk": float(level), "margin": float(margin)}
                for level, margin in zip(
                    self.risk_levels, self.margin_at_risk, strict=True
                )
            ]
        return {
            "section": "margin_risk",
            "convention": (
                "residual = delivered - reference; a margin m is not delivered "
                "when the residual is below m"
            ),
            "answered": self.answered,
            "refusal": self.refusal,
            "n_available": int(self.n_available),
            "n_required": int(self.n_required),
            "reference": floats(self.reference),
            "margins": floats(self.margins),
            "risk_levels": [float(r) for r in self.risk_levels],
            "probabilities": floats(self.probabilities),
            "n_residuals": ints(self.n_residuals),
            "n_short": ints(self.n_short),
            "margin_at_risk": at_risk,
        }

    def to_html(self, heading_level: int = 2) -> str:
        """A self-contained ``<section>`` for an HTML audit report.

        It contains no styles and no scripts. Classes on the elements
        (``otwin-margin-risk``, ``refusal``) let the report style it. A refusal
        renders as a sentence with the counts and no table.

        Example:
            >>> print(margin_risk([0.1] * 5, 1.0, [0.0]).to_html())  # doctest: +ELLIPSIS
            <section class="otwin-margin-risk">
            <h2>Margin above the reference curve</h2>
            <p class="refusal">Not computed: 5 residuals; at least 19 are needed...</p>
            </section>
        """
        level = min(max(int(heading_level), 1), 6)
        h = f"h{level}"
        out = [
            '<section class="otwin-margin-risk">',
            f"<{h}>Margin above the reference curve</{h}>",
        ]
        if not self.answered:
            out.append(
                f'<p class="refusal">Not computed: {html.escape(str(self.refusal))}.</p>'
            )
            out.append("</section>")
            return "\n".join(out)

        assert self.probabilities is not None
        assert self.n_residuals is not None
        assert self.n_short is not None
        assert self.margin_at_risk is not None
        out.append(
            "<p>A margin is not delivered when the asset falls short of the "
            "reference curve plus that margin. Probabilities are shares of "
            f"{self.n_available} residuals (delivered &minus; reference), with "
            "no distribution assumed.</p>"
        )
        out.append("<table>")
        out.append(
            "<thead><tr><th>Margin</th><th>Probability of not delivering</th>"
            "<th>Residuals below margin</th><th>Residuals</th></tr></thead>"
        )
        out.append("<tbody>")
        for m, p, k, n in zip(
            self.margins, self.probabilities, self.n_short, self.n_residuals, strict=True
        ):
            out.append(
                f"<tr><td>{m:.6g}</td><td>{_pct(p, 1)}</td><td>{int(k)}</td><td>{int(n)}</td></tr>"
            )
        out.append("</tbody>")
        out.append("</table>")
        out.append("<table>")
        out.append("<thead><tr><th>Stated risk</th><th>Margin</th></tr></thead>")
        out.append("<tbody>")
        for r, m in zip(self.risk_levels, self.margin_at_risk, strict=True):
            out.append(f"<tr><td>{_pct(r)}</td><td>{m:.6g}</td></tr>")
        out.append("</tbody>")
        out.append("</table>")
        out.append("</section>")
        return "\n".join(out)


def margin_risk(
    residuals: Array | Sequence[float],
    reference: Array | Sequence[float] | float,
    margins: Array | Sequence[float],
    *,
    risk_levels: Sequence[float] = DEFAULT_RISK_LEVELS,
    min_residuals: int | None = None,
) -> MarginRisk:
    """The probability of not delivering each margin above a reference curve.

    For each margin ``m`` this returns the share of residuals below ``m``. A
    residual equal to ``m`` counts as delivered. For each stated risk it
    returns the largest margin that can be promised with at most that risk of
    falling short. Both come from the empirical distribution of the residuals
    and nothing else. See the module docstring for why the margin at a risk is
    the ``floor(risk * (n + 1))``-th smallest residual and not the plain sample
    quantile.

    Args:
        residuals: ``delivered - reference``, as the asset actually behaved.
            Positive means it did better than the reference. Use out-of-sample
            residuals, for example from
            :func:`~otwin.forecast.rolling_origin_residuals`. For a quantity
            where lower is better, such as a temperature, negate them.
        reference: The reference curve the margins are measured from, as a
            scalar or one value per point. It is returned with the result so
            that :meth:`MarginRisk.promised` can turn a margin into a curve.
        margins: The margins to evaluate, in the units of the residuals. A
            negative margin is a point below the reference curve.
        risk_levels: The risks at which to report the margin. The default is
            5, 10 and 20 %.
        min_residuals: The fewest residuals to answer from. With fewer, the
            result is a refusal. The default is the fewest at which the
            smallest risk level exists (19 at 5 %). A lower value is raised to
            that number, because below it the margin would be the sample
            minimum with no guarantee behind it.

    Returns:
        A :class:`MarginRisk`. Check :attr:`MarginRisk.answered` before
        reading numbers from it.

    Raises:
        ValueError: If any residual, reference value or margin is NaN or
            infinite, if ``reference``, ``margins`` or ``risk_levels`` is empty,
            or if a risk level is outside (0, 1). These are errors in the call.
            Too few residuals is a refusal, not an error.

    Example:
        >>> import numpy as np
        >>> res = np.arange(-10.0, 90.0)          # 100 residuals, -10 ... 89
        >>> r = margin_risk(res, reference=50.0, margins=[-10.0, 0.0, 10.0])
        >>> r.probabilities.tolist()              # share of residuals below each margin
        [0.0, 0.1, 0.2]
        >>> r.n_short.tolist(), r.n_residuals.tolist()
        ([0, 10, 20], [100, 100, 100])
        >>> r.margin_at_risk.tolist()             # 5th, 10th and 20th smallest
        [-6.0, -1.0, 9.0]
        >>> margin_risk(res[:12], 50.0, [0.0]).refusal
        '12 residuals; at least 19 are needed for a margin at 5 % risk'
    """
    res = np.asarray(residuals, dtype=float).ravel()
    ref = np.atleast_1d(np.asarray(reference, dtype=float)).ravel()
    mar = np.atleast_1d(np.asarray(margins, dtype=float)).ravel()
    levels = tuple(float(r) for r in risk_levels)

    if not np.all(np.isfinite(res)):
        raise ValueError(
            "residuals contain NaN or Inf; drop missing values before the audit "
            "so the count behind each probability is the count actually used"
        )
    if ref.size == 0:
        raise ValueError("reference curve is empty")
    if not np.all(np.isfinite(ref)):
        raise ValueError("reference curve contains NaN or Inf")
    if mar.size == 0:
        raise ValueError("margins is empty; give at least one margin to evaluate")
    if not np.all(np.isfinite(mar)):
        raise ValueError("margins contain NaN or Inf")
    if not levels:
        raise ValueError("risk_levels is empty")
    for r in levels:
        _check_risk(r)

    smallest = min(levels)
    needed_by_risk = min_residuals_for(smallest)
    if min_residuals is None:
        required, stated = needed_by_risk, False
    else:
        required = max(int(min_residuals), needed_by_risk)
        stated = int(min_residuals) >= needed_by_risk

    n = int(res.size)
    if n < required:
        reason = (
            f"the stated minimum is {required}"
            if stated
            else f"at least {required} are needed for a margin at {_pct(smallest)} risk"
        )
        noun = "residual" if n == 1 else "residuals"
        return MarginRisk(
            reference=ref,
            margins=mar,
            risk_levels=levels,
            n_available=n,
            n_required=required,
            refusal=f"{n} {noun}; {reason}",
        )

    ordered = np.sort(res)
    # searchsorted(left) counts the residuals strictly below each margin, so a
    # residual equal to the margin counts as delivered.
    n_short = np.searchsorted(ordered, mar, side="left").astype(int)
    at_risk = np.array([ordered[_rank(r, n) - 1] for r in levels], dtype=float)
    return MarginRisk(
        reference=ref,
        margins=mar,
        risk_levels=levels,
        n_available=n,
        n_required=required,
        probabilities=n_short / n,
        n_residuals=np.full(mar.size, n, dtype=int),
        n_short=n_short,
        margin_at_risk=at_risk,
    )
