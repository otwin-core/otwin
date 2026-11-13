"""Audit: what a model's forecasts can be held to, measured on how it behaved.

:func:`coverage_audit` reports whether a forecast range holds the coverage it
states. It gives the observed coverage with its confidence interval, the bias
and the mean width. This is one overall row by default, or one row per
horizon tranche on request.

:func:`margin_risk` answers how much margin above a reference curve can be
promised, and at what risk of not delivering it. It works from the empirical
distribution of the residuals and assumes no distribution.

Both refuse with the count, not a number, when there is too little data
behind an answer.
"""

from .coverage import CoverageAudit, CoverageRow, coverage_audit, default_min_contrasts
from .margin import DEFAULT_RISK_LEVELS, MarginRisk, margin_risk, min_residuals_for

__all__ = [
    "coverage_audit",
    "CoverageAudit",
    "CoverageRow",
    "default_min_contrasts",
    "margin_risk",
    "MarginRisk",
    "min_residuals_for",
    "DEFAULT_RISK_LEVELS",
]
