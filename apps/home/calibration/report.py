"""Plain language for a calibration: good, usable, or not enough data.

The householder is not an engineer. Every fitted number is turned into a
sentence about the home ("how fast your home loses heat", "how long it
keeps its warmth"), with its uncertainty as a plain "±" and one of three
verdicts:

=================  =================================================================
verdict            meaning
=================  =================================================================
good               known to within ±10 %: use it for decisions
usable             known to within ±30 %: right in size, fine for rough comparisons
not enough data    the month cannot tell; the sentence says why and what would help
=================  =================================================================

The uncertainty behind each verdict is the 95 % interval of the fit (from
the sensitivities, robust to noise that grows with consumption) combined
with how far the value would move if the house had started the month
warmer or colder, which nobody measured.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "GOOD",
    "USABLE",
    "NOT_ENOUGH_DATA",
    "VERDICTS",
    "Finding",
    "verdict_for",
    "worst",
    "GOOD_LIMIT",
    "USABLE_LIMIT",
    "ASHRAE_CV_RMSE",
    "ASHRAE_NMBE",
    "ASHRAE_MONTHLY_CV_RMSE",
    "ASHRAE_MONTHLY_NMBE",
]

GOOD = "good"
USABLE = "usable"
NOT_ENOUGH_DATA = "not enough data"
VERDICTS = (GOOD, USABLE, NOT_ENOUGH_DATA)

#: Relative 95 % uncertainty limits for the verdicts.
GOOD_LIMIT = 0.10
USABLE_LIMIT = 0.30
#: ASHRAE Guideline 14 acceptance for a model calibrated to hourly data.
ASHRAE_CV_RMSE = 0.30
ASHRAE_NMBE = 0.10
#: ASHRAE Guideline 14 acceptance for a model calibrated to monthly bills.
ASHRAE_MONTHLY_CV_RMSE = 0.15
ASHRAE_MONTHLY_NMBE = 0.05


def verdict_for(uncertainty: float | None) -> str:
    """The verdict for a relative 95 % uncertainty (``None``/inf: not enough data)."""
    if uncertainty is None or not uncertainty < float("inf"):
        return NOT_ENOUGH_DATA
    if uncertainty <= GOOD_LIMIT:
        return GOOD
    if uncertainty <= USABLE_LIMIT:
        return USABLE
    return NOT_ENOUGH_DATA


def worst(verdicts) -> str:
    """The least favourable of several verdicts."""
    rank = {v: i for i, v in enumerate(VERDICTS)}
    return max(verdicts, key=lambda v: rank[v], default=GOOD)


@dataclass(frozen=True)
class Finding:
    """One thing the calibration found out about the home.

    Attributes:
        key: the model parameter (or derived quantity) it is about.
        label: what it is, in a few plain words.
        value: the value in ``unit``.
        unit: a plain unit ("W per °C", "hours", "kW", "W").
        uncertainty: relative 95 % uncertainty, or ``None`` if not estimable.
        verdict: :data:`GOOD`, :data:`USABLE` or :data:`NOT_ENOUGH_DATA`.
        sentence: the finding as the householder reads it.
        reason: for "not enough data", why, and what would help.
        counted: whether it weighs in the overall verdict. Something the
            meters given can never show (a boiler's size from monthly gas
            bills) is reported, but does not make the whole calibration
            "not enough data".
    """

    key: str
    label: str
    value: float
    unit: str
    uncertainty: float | None
    verdict: str
    sentence: str
    reason: str = ""
    counted: bool = True

    @property
    def measured(self) -> bool:
        """False when nothing was measured (the value is NaN)."""
        return self.value == self.value

    def line(self) -> str:
        """The finding as one bullet: sentence, verdict, and the reason if any."""
        text = f"{self.sentence} — {self.verdict}."
        if self.reason:
            text += f" {self.reason}"
        return text


def plus_minus(uncertainty: float | None) -> str:
    """``"(±4 %)"``, or an empty string when there is nothing sensible to show."""
    if uncertainty is None or not uncertainty < float("inf") or uncertainty > 1.0:
        return ""
    pct = 100 * uncertainty
    return f" (±{pct:.0f} %)" if pct >= 1 else " (±1 %)"
