"""Calibrate a home twin to a month of hourly electricity, and say how well it went.

::

    from calibration import HourlyData, calibrate
    result = calibrate(twin, HourlyData(start, kwh, outdoor_c))
    print(result.summary())
    better_twin = result.twin

:func:`calibrate` fits the parameters a month of electricity can see (heat
loss, heat storage, the heating or cooling machine's size, the always-on
load) with :func:`otwin.hybrid.fit_parameters` through the hourly meter of
:mod:`calibration.fit`, then judges every value:

1. **Noise.** A 95 % interval from the sensitivities at the optimum, in the
   heteroscedasticity-robust ("sandwich") form, because a household's
   unexplained use grows with how much it uses.
2. **The unknown start.** The house's temperature when the record begins is
   not measured. The spin-up is repeated 3 K warmer and 3 K colder, and the
   linearised fit says how far each value would move; that shift is added
   to the interval in quadrature.
3. **What the month could not show.** A machine that never reached full
   power has not shown its size. otwin's identifiability check flags a value
   the resampled month does not pin down. A twin that cannot reproduce the
   hourly consumption (ASHRAE Guideline 14: hourly CV(RMSE) ≤ 30 %,
   |NMBE| ≤ 10 %) has not been calibrated, whatever its numbers.

The verdicts and sentences are in :mod:`calibration.report`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
from otwin.hybrid import FitResult

from components import (
    AirConditioner,
    Boiler,
    ElectricHeater,
    HeatPump,
    HomeTwin,
    SpaceMachine,
)

from .data import HourlyData, NotEnoughData
from .fit import (
    ELECTRICITY_SIGMA_KWH,
    GAS_BILL_SIGMA,
    INDOOR_SIGMA_K,
    OFFSET_BASE_K,
    THERMOMETER_OFFSET,
    HourlyMeter,
    ParameterRole,
    calibration_parameters,
    default_bounds,
    fit_hourly,
)
from .report import (
    ASHRAE_CV_RMSE,
    ASHRAE_MONTHLY_CV_RMSE,
    ASHRAE_MONTHLY_NMBE,
    ASHRAE_NMBE,
    GOOD,
    NOT_ENOUGH_DATA,
    USABLE,
    Finding,
    plus_minus,
    verdict_for,
    worst,
)

__all__ = ["Calibration", "calibrate", "START_OFFSET_K", "MIN_FULL_POWER_HOURS"]

#: How much warmer and colder the unknown starting state is tried, K.
START_OFFSET_K = 3.0
#: Hours at (nearly) full power a machine needs before its size counts as seen.
MIN_FULL_POWER_HOURS = 3
_FULL_POWER = 0.9  # an hour averaging 90 % of the rating counts as full power


@dataclass
class Calibration:
    """The outcome of :func:`calibrate`.

    Attributes:
        verdict: overall :data:`~calibration.report.GOOD`, ``USABLE`` or
            ``NOT_ENOUGH_DATA``.
        headline: one or two plain sentences saying how it went.
        findings: one :class:`~calibration.report.Finding` per thing measured.
        values: fitted model parameters, by name.
        twin: the calibrated :class:`~components.HomeTwin`.
        hourly_error: CV(RMSE) of the hourly electricity, a fraction.
        bias: NMBE of the hourly electricity, a fraction (positive: the twin
            predicts more than was used).
        measured_kwh, predicted_kwh: the month's hourly electricity, kWh,
            NaN where the record has no reading.
        fit: the underlying :class:`otwin.hybrid.FitResult`.
    """

    verdict: str
    headline: str
    findings: list[Finding]
    values: dict[str, float]
    twin: HomeTwin
    hourly_error: float
    bias: float
    measured_kwh: np.ndarray
    predicted_kwh: np.ndarray
    fit: FitResult
    uncertainty: dict[str, float] = field(default_factory=dict)
    measured_bills_kwh: np.ndarray = field(default_factory=lambda: np.zeros(0))
    predicted_bills_kwh: np.ndarray = field(default_factory=lambda: np.zeros(0))
    worst_bill_error: float = float("nan")
    given: dict[str, float] = field(default_factory=dict)
    #: The indoor temperature, °C, hour by hour: the thermometer's (NaN where
    #: it read nothing) and the twin's own thermometer's.
    measured_indoor_c: np.ndarray = field(default_factory=lambda: np.zeros(0))
    predicted_indoor_c: np.ndarray = field(default_factory=lambda: np.zeros(0))
    #: Typical hourly mismatch of the indoor temperature, K (RMSE).
    indoor_error: float = float("nan")

    def finding(self, key: str) -> Finding:
        """The finding about ``key`` (a model parameter or derived quantity)."""
        for f in self.findings:
            if f.key == key:
                return f
        raise KeyError(
            f"no finding about {key!r}; findings: {[f.key for f in self.findings]}"
        )

    def summary(self) -> str:
        """The calibration as a householder reads it."""
        lines = [f"Calibration: {self.verdict.upper()}", self.headline, ""]
        lines.append("What the month shows about your home:")
        lines += [f"  • {f.line()}" for f in self.findings]
        return "\n".join(lines)


def _machine_kind(m: SpaceMachine) -> str:
    if isinstance(m, AirConditioner):
        return "air conditioner"
    if isinstance(m, HeatPump):
        return "heat pump"
    if isinstance(m, ElectricHeater):
        return "electric heater"
    if isinstance(m, Boiler):
        return "boiler"
    return "heating"


def _covariance(
    J: np.ndarray, r: np.ndarray, floor: np.ndarray | None = None
) -> np.ndarray:
    """Sandwich covariance of the fitted parameters; inf where undetermined.

    ``floor`` is a per-row minimum residual: with a handful of gas bills the
    residuals alone cannot say how far a bill can be off, and an exact fit
    of three numbers would otherwise claim a perfect answer.
    """
    if floor is not None:
        r = np.sign(r) * np.maximum(np.abs(r), floor) + (r == 0) * floor
    n, k = J.shape
    cov = np.full((k, k), np.inf)
    norms = np.linalg.norm(J, axis=0)
    active = norms > 1e-9 * max(float(norms.max(initial=0.0)), 1e-300)
    if not active.any() or n <= k:
        return cov
    # Columns are scaled to unit length first: parameters differ by orders of
    # magnitude (a heat capacity of 1e7 J/K, a thermometer offset of 0.1 K),
    # and unscaled the normal matrix looks singular when it is not. The
    # covariance is the same either way; only the arithmetic is safer.
    scale = norms[active]
    Ja = J[:, active] / scale
    try:
        A = np.linalg.inv(Ja.T @ Ja)
    except np.linalg.LinAlgError:
        return cov
    if not np.all(np.isfinite(A)) or np.linalg.cond(Ja.T @ Ja) > 1e14:
        return cov
    ca = A @ (Ja.T * r**2) @ Ja @ A * n / (n - k) / np.outer(scale, scale)
    idx = np.flatnonzero(active)
    cov[np.ix_(idx, idx)] = ca
    return cov


def _persistence(r: np.ndarray) -> float:
    """How much to inflate residuals that persist from row to row: the square
    root of (1 + ρ) / (1 − ρ), ρ their lag-one autocorrelation (0 to 0.95)."""
    if r.size < 3 or not np.any(r):
        return 1.0
    c = r - r.mean()
    rho = float(np.dot(c[1:], c[:-1]) / max(np.dot(c, c), 1e-300))
    rho = min(max(rho, 0.0), 0.95)
    return float(np.sqrt((1.0 + rho) / (1.0 - rho)))


def _unstable(fit: FitResult, name: str) -> bool:
    """otwin's bootstrap says the resampled month does not pin ``name`` down."""
    ident = fit.identifiability
    if ident is None:
        return False
    for p in ident.parameters:
        if p.name == name:
            return (p.cv is not None and p.cv > 0.5) or p.sign_stable is False
    return False


def _weights(data: HourlyData) -> tuple[float, float]:
    """The weights fit_hourly gives the electricity hours and the gas bills."""
    w_e = 1.0 / ELECTRICITY_SIGMA_KWH
    if not data.gas_bills:
        return w_e, 0.0
    mean = max(float(np.mean([b.kwh for b in data.gas_bills])), 1.0)
    return w_e, 1.0 / (GAS_BILL_SIGMA * mean)


def calibrate(
    twin: HomeTwin,
    data: HourlyData,
    *,
    guess: Mapping[str, float] | None = None,
    given: Sequence[str] = (),
    substeps: int | None = None,
    spinup_weeks: int | None = None,
    max_evaluations: int = 300,
) -> Calibration:
    """Fit ``twin`` to ``data`` and report in plain language.

    Args:
        twin: the home as the householder described it. Its structure
            (zone form, machines, efficiencies, setpoints and schedules) is
            taken as given; its current parameter values are the starting
            point of the search.
        data: at least 28 days of hourly electricity, or of gas bills, with
            the weather (see :class:`HourlyData`).
        guess: starting values to use instead of the twin's, by parameter.
        given: parameters the householder knows (a heater's power from its
            nameplate): kept as they are, never fitted.
        substeps: simulation steps per hour; automatic by default (four for a
            month, two for a year of bills).
        spinup_weeks: weeks of spin-up; one for one-node zones, six for
            two-node ones by default.
        max_evaluations: cap on simulations in the search.

    Raises:
        NotEnoughData: the record is too short, or nothing in the twin can be
            measured from the meters given.
    """
    obs = data.observed
    has_elec = int(obs.sum()) >= 7 * 24
    ind = data.indoor_observed
    has_indoor = int(ind.sum()) >= 7 * 24
    roles = calibration_parameters(
        twin,
        gas_bills=bool(data.gas_bills),
        electricity=has_elec,
        indoor=has_indoor,
        given=given,
    )
    fitted = [r for r in roles if r.observable]
    if not fitted:
        reason = next((r.why_not for r in roles if r.why_not), "")
        raise NotEnoughData(
            "Nothing in this twin shows on the meters you gave, so they cannot "
            f"calibrate it{': ' + reason if reason else '.'}"
        )
    missing = [
        n
        for n in twin.input_names
        if n != twin.outdoor and n not in twin.schedules and n not in data.measured
    ]
    if missing:
        raise ValueError(
            f"the twin needs {missing}, which have no schedule and are not in the data"
        )
    names = [r.name for r in fitted]
    fit, meter = fit_hourly(
        twin,
        data,
        names,
        guess=guess,
        bounds=default_bounds(fitted),
        substeps=substeps,
        spinup_weeks=spinup_weeks,
        max_evaluations=max_evaluations,
    )
    theta = np.array([fit.values[n] for n in names])

    # the rows that carry information: observed hours, each bill's last hour,
    # the hours the thermometer read (stacked in that order by fit_hourly)
    n_h = data.hours
    bills = data.gas_bills
    w_e, w_g = _weights(data)
    w_i = 1.0 / INDOOR_SIGMA_K
    with_indoor = data.indoor_c is not None
    e_rows = np.flatnonzero(obs)
    g_rows = n_h + np.array([b.end - 1 for b in bills], dtype=int)
    i_rows = n_h * (2 if bills else 1) + np.flatnonzero(ind)
    rows = np.concatenate(
        [e_rows] + ([g_rows] if bills else []) + ([i_rows] if with_indoor else [])
    )
    J = fit.sensitivities[rows]
    r = fit.residuals[rows].copy()
    # Hourly residuals persist from one hour to the next (the sun on the
    # thermometer, a door left open, an evening the twin does not know), so
    # an hour is not an independent observation. Each hourly stream counts
    # for what its effective sample size is worth: AR(1), (1 + ρ) / (1 − ρ).
    n_e = e_rows.size
    r[:n_e] *= _persistence(r[:n_e])
    if with_indoor:
        r[r.size - i_rows.size :] *= _persistence(r[r.size - i_rows.size :])
    floor = (
        np.concatenate(
            [
                np.zeros(e_rows.size),
                w_g * GAS_BILL_SIGMA * np.array([b.kwh for b in bills]),
            ]
            + ([np.zeros(i_rows.size)] if with_indoor else [])
        )
        if bills
        else None
    )
    cov = _covariance(J, r, floor)

    def weighted(m: HourlyMeter) -> np.ndarray:
        elec, gas, indoor = m.readings()
        parts = [w_e * elec[obs]]
        if bills:
            parts.append(w_g * m.bill_totals(gas))
        if with_indoor:
            parts.append(w_i * indoor[ind])
        return np.concatenate(parts)

    # the unknown start: how far would each value move from ±3 K?
    base = weighted(meter)
    shifts = np.zeros_like(theta)
    finite = np.isfinite(np.diag(cov))
    if finite.any():
        Jf = J[:, finite]
        A = np.linalg.pinv(Jf.T @ Jf)
        for off in (-START_OFFSET_K, START_OFFSET_K):
            dp = weighted(meter.variant(spinup_offset_c=off)) - base
            shift = np.zeros_like(theta)
            shift[finite] = -A @ Jf.T @ dp
            shifts = np.maximum(shifts, np.abs(shift))

    def rel(i: int) -> float:
        var = cov[i, i]
        if not np.isfinite(var) or var < 0:
            return float("inf")
        noise = 1.96 * np.sqrt(var) / abs(theta[i])
        start = shifts[i] / abs(theta[i])
        return float(np.hypot(noise, start))

    uncertainty = {n: rel(i) for i, n in enumerate(names)}

    elec_all, gas_all, indoor_all = meter.readings(indoor=True)
    measured = np.where(obs, data.electricity_kwh, np.nan)
    indoor_error = float("nan")
    if with_indoor and ind.any():
        indoor_error = float(
            np.sqrt(np.mean((indoor_all[ind] - data.indoor_c[ind]) ** 2))
        )
    predicted = np.where(obs, elec_all, np.nan)
    cv = nmbe = float("nan")
    if int(obs.sum()) >= 28 * 24 or (obs.any() and not bills):
        y = data.electricity_kwh[obs]
        resid = elec_all[obs] - y
        cv = float(np.sqrt(np.mean(resid**2)) / np.mean(y))
        nmbe = float(np.sum(resid) / np.sum(y))
    bill_kwh = np.array([b.kwh for b in bills])
    bill_pred = meter.bill_totals(gas_all) if bills else np.zeros(0)
    elec_ok = not np.isfinite(cv) or (cv <= ASHRAE_CV_RMSE and abs(nmbe) <= ASHRAE_NMBE)
    bills_ok = True
    worst_bill = float("nan")
    if bills:
        rel_err = (bill_pred - bill_kwh) / np.maximum(bill_kwh, 1.0)
        worst_bill = float(np.max(np.abs(rel_err)))
        b_nmbe = float((bill_pred.sum() - bill_kwh.sum()) / max(bill_kwh.sum(), 1.0))
        b_cv = float(
            np.sqrt(np.mean((bill_pred - bill_kwh) ** 2)) / max(bill_kwh.mean(), 1.0)
        )
        bills_ok = abs(b_nmbe) <= ASHRAE_MONTHLY_NMBE and (
            len(bills) < 3 or b_cv <= ASHRAE_MONTHLY_CV_RMSE
        )

    findings = _findings(twin, meter, fit, roles, names, theta, cov, shifts, uncertainty)
    verdict, headline = _headline(
        findings,
        cv,
        nmbe,
        elec_ok,
        len(bills),
        worst_bill,
        bills_ok,
        fit.success,
        data,
        indoor_error,
    )
    calibrated = replace(twin, model=meter.model)
    return Calibration(
        verdict=verdict,
        headline=headline,
        findings=findings,
        values=dict(fit.values),
        twin=calibrated,
        hourly_error=cv,
        bias=nmbe,
        measured_kwh=measured,
        predicted_kwh=predicted,
        fit=fit,
        uncertainty=uncertainty,
        measured_bills_kwh=bill_kwh,
        predicted_bills_kwh=bill_pred,
        worst_bill_error=worst_bill,
        given={r.name: float(meter.model.parameters[r.name]) for r in roles if r.given},
        measured_indoor_c=(
            np.where(ind, data.indoor_c, np.nan) if with_indoor else np.full(n_h, np.nan)
        ),
        predicted_indoor_c=indoor_all,
        indoor_error=indoor_error,
    )


_NOT_PINNED = "The month does not pin this down; a longer record would."
_LABELS = {
    "heat_loss": "How fast your home loses heat",
    "heat_storage": "How long your home keeps its warmth",
    "fabric_storage": "Heat stored in walls and floors",
    "base_load": "Always-on electricity",
}
_UNSTABLE = (
    "The month does not pin this down: different parts of it point to different values."
)
_NO_STORAGE = (
    "How much heat your home stores shows only when the indoor temperature "
    "changes, and this month it hardly did. A month with a lower thermostat "
    "setting at night would show it."
)


def _findings(
    twin: HomeTwin,
    meter: HourlyMeter,
    fit: FitResult,
    roles: list[ParameterRole],
    names: list[str],
    theta: np.ndarray,
    cov: np.ndarray,
    shifts: np.ndarray,
    uncertainty: dict[str, float],
) -> list[Finding]:
    params = meter.parameters  # the model's, and the thermometer's offset
    index = {n: i for i, n in enumerate(names)}
    zone = twin.zone.name
    ua_name = f"{zone}.envelope.conductance"
    vent = params.get(f"{zone}.ventilation.conductance", 0.0)
    machines = {c.name: c for c in twin.system.components if isinstance(c, SpaceMachine)}
    out: list[Finding] = []

    bill_only = {r.name for r in roles if r.from_bills}

    def judge(name: str, u: float, unseen: str = _NOT_PINNED) -> tuple[str, str]:
        # the stability check resamples hours; a value seen only through a few
        # bill totals has its uncertainty from the bills' own error instead
        if name not in bill_only and _unstable(fit, name):
            return NOT_ENOUGH_DATA, _UNSTABLE
        v = verdict_for(u)
        return v, (unseen if v == NOT_ENOUGH_DATA else "")

    for role in roles:
        value = params[role.name]
        if role.given:
            # The householder told us (a nameplate): kept as given, not fitted,
            # and not weighed in the verdict.
            label = _LABELS.get(role.role, role.name)
            if role.role == "machine":
                label = f"Size of your {_machine_kind(machines[role.component])}"
                shown, unit = value / 1000.0, "kW"
            else:
                shown, unit = value, "W"
            out.append(
                Finding(
                    role.name,
                    label,
                    shown,
                    unit,
                    None,
                    GOOD,
                    f"{label}: {shown:.1f} {unit}, as you told us",
                    "",
                    counted=False,
                )
            )
            continue
        if not role.observable:
            # Nothing was measured: report no number, only why.
            label = _LABELS.get(role.role, role.name)
            if role.role == "machine":
                label = f"Size of your {_machine_kind(machines[role.component])}"
            out.append(
                Finding(
                    role.name,
                    label,
                    float("nan"),
                    "",
                    None,
                    NOT_ENOUGH_DATA,
                    f"{label}: not measured",
                    role.why_not[0].upper() + role.why_not[1:],
                    counted=not role.beyond_bills,
                )
            )
            continue
        u = uncertainty[role.name]
        v, reason = judge(role.name, u)

        if role.role == "heat_loss":
            total = value + vent
            sentence = (
                f"How fast your home loses heat: {value:.0f} W for every °C between "
                f"inside and outside{plus_minus(u)}. On a 5 °C day with 20 °C inside, "
                f"walls, windows and ventilation together let out about "
                f"{total * 15 / 1000:.1f} kW"
            )
            out.append(
                Finding(
                    role.name,
                    "How fast your home loses heat",
                    value,
                    "W per °C",
                    u,
                    v,
                    sentence,
                    reason,
                )
            )

        elif role.role == "heat_storage":
            k_total = params[ua_name] + vent
            tau_h = value / k_total / 3600.0
            if role.observable:
                # the time constant C / (UA + ventilation): delta method on the
                # covariance, start-state shifts of both parts added up
                i, j = index[role.name], index[ua_name]
                if np.isfinite(cov[i, i]) and np.isfinite(cov[j, j]):
                    g = np.zeros(len(names))
                    g[i], g[j] = 1.0 / value, -1.0 / k_total
                    noise = 1.96 * np.sqrt(max(float(g @ cov @ g), 0.0))
                    start = abs(shifts[i]) / value + abs(shifts[j]) / k_total
                    u = float(np.hypot(noise, start))
                else:
                    u = float("inf")
                v = verdict_for(u) if not _unstable(fit, role.name) else NOT_ENOUGH_DATA
                reason = _NO_STORAGE if v == NOT_ENOUGH_DATA else ""
            sentence = (
                f"How long your home keeps its warmth: with the heating off it would "
                f"lose two-thirds of its warmth over the outdoor temperature in about "
                f"{tau_h:.0f} hours{plus_minus(u)}"
            )
            out.append(
                Finding(
                    role.name,
                    "How long your home keeps its warmth",
                    tau_h,
                    "hours",
                    u,
                    v,
                    sentence,
                    reason,
                )
            )

        elif role.role == "fabric_storage":
            sentence = (
                f"Heat stored in your walls and floors: {value / 1e6:.0f} MJ for every "
                f"°C{plus_minus(u)}. It is what keeps the home steady through a cold night"
            )
            out.append(
                Finding(
                    role.name,
                    "Heat stored in walls and floors",
                    value / 1e6,
                    "MJ per °C",
                    u,
                    v,
                    sentence,
                    reason,
                )
            )

        elif role.role == "machine":
            oversized = False
            m = machines[role.component]
            kind = _machine_kind(m)
            what = "cooling" if m.sense == "cool" else "heat"
            if role.observable:
                moved = meter.hourly([f"{m.name}.{m.sense}"])[f"{m.name}.{m.sense}"]
                if int(np.sum(moved >= _FULL_POWER * value)) < MIN_FULL_POWER_HOURS:
                    v = NOT_ENOUGH_DATA
                    oversized = True
                    hint = (
                        "A hotter month would show it."
                        if m.sense == "cool"
                        else "A colder month, or a morning warm-up after a lower "
                        "night setting, would show it."
                    )
                    reason = (
                        f"Your {kind} never ran at full power this month, so its "
                        f"full size never showed: it is bigger than the month "
                        f"needed. {hint}"
                    )
            sentence = (
                f"Size of your {kind}: {value / 1000:.1f} kW of {what} at full power"
                f"{plus_minus(u)}"
            )
            out.append(
                Finding(
                    role.name,
                    f"Size of your {kind}",
                    value / 1000.0,
                    "kW",
                    u,
                    v,
                    sentence,
                    reason,
                    # never needed at full power: the home was kept warm, so
                    # its size, unseen, did not matter to the month
                    counted=not oversized,
                )
            )

        elif role.role == "sensor":
            value -= OFFSET_BASE_K  # carried on a base, see calibration.fit
            i = index[role.name]
            var = cov[i, i]
            u_abs = (
                float(np.hypot(1.96 * np.sqrt(var), shifts[i]))
                if np.isfinite(var) and var >= 0
                else float("inf")
            )
            v = GOOD if u_abs <= 0.2 else USABLE if u_abs <= 0.5 else NOT_ENOUGH_DATA
            pm = f" (±{max(u_abs, 0.05):.1f} °C)" if np.isfinite(u_abs) else ""
            if abs(value) < 0.05:
                sentence = f"Your thermometer: it reads your home's temperature{pm}"
            else:
                where = "warmer" if value > 0 else "cooler"
                sentence = (
                    f"Your thermometer: it reads {abs(value):.1f} °C {where} than your "
                    f"home on average{pm}, from where it hangs or its calibration. "
                    "The twin allows for it"
                )
            out.append(
                Finding(
                    role.name,
                    "Your thermometer",
                    value,
                    "°C",
                    u_abs,
                    v,
                    sentence,
                    "" if v != NOT_ENOUGH_DATA else _NOT_PINNED,
                    counted=False,  # about the sensor, not the home
                )
            )

        elif role.role == "base_load":
            sentence = (
                f"Always-on electricity: {value:.0f} W{plus_minus(u)}, about "
                f"{value * 24 * 30 / 1000:.0f} kWh a month whatever you do"
            )
            out.append(
                Finding(
                    role.name, "Always-on electricity", value, "W", u, v, sentence, reason
                )
            )
    return out


def _headline(
    findings: list[Finding],
    cv: float,
    nmbe: float,
    fits_hours: bool,
    n_bills: int,
    worst_bill: float,
    fits_bills: bool,
    converged: bool,
    data: HourlyData,
    indoor_error: float = float("nan"),
) -> tuple[str, str]:
    parts = []
    if np.isfinite(cv):
        total = max(abs(100 * nmbe), 0.1)
        parts.append(
            f"your electricity (a typical hour within {100 * cv:.0f} % and "
            f"{_total_of(data)} within {total:.1f} %)"
        )
    if n_bills:
        bills = "your gas bill" if n_bills == 1 else f"your {n_bills} gas bills"
        within = max(100 * worst_bill, 0.1)
        parts.append(f"{bills} (within {within:.1f} %)")
    if np.isfinite(indoor_error):
        parts.append(
            f"your indoor temperature (a typical hour within {indoor_error:.1f} °C)"
        )
    match = _join(parts) or "your meters"
    if not converged:
        return NOT_ENOUGH_DATA, (
            "Not enough data: the search did not settle on one answer for this month. "
            "Check the electricity and weather cover the same dates, or try a "
            "longer record."
        )
    if not fits_bills:
        return NOT_ENOUGH_DATA, (
            f"Not enough data: the twin does not yet reproduce your gas bills (the "
            f"furthest is off by {100 * worst_bill:.0f} %). Check the bills' dates and "
            "kWh, and that what runs on gas (heating, hot water, cooking) is right in "
            "step 1."
        )
    if not fits_hours:
        return NOT_ENOUGH_DATA, (
            f"Not enough data: the twin does not yet reproduce your hourly "
            f"electricity (a typical hour is off by {100 * cv:.0f} %, the month by "
            f"{100 * nmbe:+.0f} %). Usually something that uses a lot of electricity "
            "is not in the twin yet: an oven used every day, a car charger, a second "
            "heater. Add it, or measure it with a smart plug."
        )
    counted = [f for f in findings if f.counted]
    overall = worst(f.verdict for f in counted)
    poor = [f.label.lower() for f in counted if f.verdict == NOT_ENOUGH_DATA]
    rough = [f.label.lower() for f in counted if f.verdict == USABLE]
    known = [f.label.lower() for f in counted if f.verdict == GOOD]
    beyond = [_the(f.label.lower()) for f in findings if not f.counted and not f.measured]
    unneeded = [
        _the(f.label.lower())
        for f in findings
        if not f.counted and f.measured and f.key != THERMOMETER_OFFSET
    ]
    cannot = f" Bills cannot show {_join(beyond, 'or')}; see below." if beyond else ""
    if unneeded:
        cannot += (
            f" {_join(unneeded).capitalize()} did not show: it was never needed at "
            "full power, so it is big enough."
        )
    days = f"{data.days:.0f} days"
    if overall == GOOD:
        every = "every number it measured" if beyond else "every number below"
        return GOOD, (
            f"Good: over {days} the twin matches {match}, and "
            f"{every} is well determined.{cannot}"
        )
    if overall == USABLE:
        return USABLE, (
            f"Usable: over {days} the twin matches {match}. "
            f"Known well: {_join(known) or 'nothing yet'}; only roughly: "
            f"{_join(rough)}.{cannot}"
        )
    first = next(f for f in counted if f.verdict == NOT_ENOUGH_DATA)
    rest = known + rough
    why = first.reason[0].lower() + first.reason[1:] if first.reason else ""
    return NOT_ENOUGH_DATA, (
        f"Not enough data for {_join(poor)}: {why} The twin does match "
        f"{match}."
        + (f" What the month does show: {_join(rest)}." if rest else "")
        + cannot
    )


def _total_of(data: HourlyData) -> str:
    """ "the month's total", or the total over what the record covers."""
    n = len(data.spans)
    if n > 1:
        return f"the total over the {n} periods"
    return "the month's total" if data.days <= 35 else "the total"


def _join(items: list[str], word: str = "and") -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {word} " + items[-1]


def _the(label: str) -> str:
    """ "size of your boiler" -> "the size of your boiler", for inside a sentence."""
    return f"the {label}" if label.startswith(("size ", "heat stored")) else label
