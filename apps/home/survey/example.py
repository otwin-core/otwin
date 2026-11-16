"""Example homes: a hidden "real" home, simulated from the householder's answers.

The wizard's example homes are not fixed recordings. Each is a *truth*: how
the real home differs from what the survey would guess for it (its walls
lose 20 % less heat, it stores 20 % more, its always-on load is 160 W).
Combined with whatever the householder picks in step 1, above all the
thermostat by day and at night, the truth gives a home that
:func:`example_period` simulates over a period's weather. Electricity, gas
and the interior thermometer's readings all come from that one simulation,
so they always agree with each other and with the answers.

The files in ``web/samples/`` are these records for the example's own
answers, written by ``web/samples/make_samples.py`` with the same code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from calibration import SyntheticRecord, synthetic_record
from components import HomeTwin

from .twin import HomeDescription, build_twin

__all__ = [
    "Truth",
    "example_twin",
    "example_period",
    "period_seed",
    "electricity_csv",
    "gas_bill",
    "thermometer_csv",
    "THERMOMETER_HEADER",
]


@dataclass(frozen=True)
class Truth:
    """How an example's real home differs from the survey's typical guess.

    ``scale`` multiplies a typical value (``{"zone.envelope.conductance":
    0.8}``); ``set`` replaces one (``{"base.power": 160.0}``); ``seed`` makes
    the household's noise and the thermometer's error repeatable.
    """

    scale: Mapping[str, float] = field(default_factory=dict)
    set: Mapping[str, float] = field(default_factory=dict)
    seed: int = 0

    @classmethod
    def from_json(cls, data: Mapping) -> Truth:
        """From an example's ``truth.json``."""
        return cls(
            dict(data.get("scale", {})),
            dict(data.get("set", {})),
            int(data.get("seed", 0)),
        )

    def to_json(self) -> dict:
        """As stored next to the example's answers."""
        return {"scale": dict(self.scale), "set": dict(self.set), "seed": self.seed}

    def overrides(self, typical: Mapping[str, float]) -> dict[str, float]:
        """The real home's parameters, given the typical ones of the same answers."""
        out = {k: typical[k] * f for k, f in self.scale.items() if k in typical}
        out.update({k: v for k, v in self.set.items() if k in typical})
        return out


def example_twin(
    desc: HomeDescription, truth: Truth, *, backend: str = "numpy"
) -> HomeTwin:
    """The example's real home, for these answers."""
    typical = build_twin(desc, backend=backend).model.parameters
    return build_twin(desc, backend=backend, overrides=truth.overrides(typical))


def period_seed(truth: Truth, start: datetime) -> int:
    """The noise seed of one period: the same period always gets the same
    noise, whichever example set loaded it."""
    return truth.seed * 100_003 + int(start.timestamp()) // 86400


def example_period(
    desc: HomeDescription,
    truth: Truth,
    *,
    start: datetime,
    outdoor_c: np.ndarray,
    backend: str = "numpy",
) -> SyntheticRecord:
    """One period of the example home under these answers: electricity, gas
    and the interior thermometer, from the period's hourly weather."""
    return synthetic_record(
        example_twin(desc, truth, backend=backend),
        start=start,
        outdoor_c=np.asarray(outdoor_c, dtype=float),
        seed=period_seed(truth, start),
        thermometer_bias_k=thermometer_bias(truth),
    )


def thermometer_bias(truth: Truth) -> float:
    """How far the example home's thermometer reads off, K: one device, the
    same error in every period."""
    return round(float(np.random.default_rng(truth.seed).normal(0.0, 0.2)), 2)


# ------------------------------------------------------------------ the files
# The example's records written as a household's files: the wizard reads them
# back exactly as it reads the files a householder drops.

GAS_EUR_PER_KWH, GAS_TAX_EUR_PER_KWH, GAS_EUR_PER_DAY, VAT_GAS = (
    0.058,
    0.00234,
    0.17,
    0.21,
)


def _comma(x: float, digits: int) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def electricity_csv(cups: str, start: datetime, kwh: np.ndarray) -> bytes:
    """Hourly electricity, CNMC/Datadis shape: hours 1..n of each local day
    (25 on the October day the clocks go back), decimal comma, a few hours
    estimated."""
    from datetime import timedelta, timezone

    tz = start.tzinfo
    lines = ["CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion"]
    t0 = start.astimezone(timezone.utc)
    day_hours: dict[str, int] = {}
    for k, v in enumerate(kwh):
        local = (t0 + timedelta(hours=k)).astimezone(tz)
        day = f"{local:%d/%m/%Y}"
        day_hours[day] = day_hours.get(day, 0) + 1
        method = "E" if k % 97 == 41 else "R"
        lines.append(
            f"{cups};{day};{day_hours[day]};{v:.3f}".replace(".", ",") + f";{method}"
        )
    return ("\r\n".join(lines) + "\r\n").encode()


def gas_bill(
    first: datetime, last: datetime, start_m3: int, gas_kwh: float, fc: float, pcs: float
) -> tuple[bytes, int, int]:
    """The gas bill for gas burned over a period: the meter turns in m³ (``kWh /
    (Fc × PCS)``) and is read in whole m³; the bill charges ``m³ × Fc × PCS``.
    Returns the CSV, the m³ and the kWh billed."""
    m3 = int(round(gas_kwh / (fc * pcs)))
    kwh = round(m3 * fc * pcs)
    days = round((last - first).total_seconds() / 86400)
    eur = (kwh * (GAS_EUR_PER_KWH + GAS_TAX_EUR_PER_KWH) + days * GAS_EUR_PER_DAY) * (
        1 + VAT_GAS
    )
    csv = (
        "inicio;fin;lectura_inicio_m3;lectura_fin_m3;tipo;fc;pcs_kwh_m3;kwh;importe_eur\n"
        f"{first:%d/%m/%Y};{last:%d/%m/%Y};{start_m3};{start_m3 + m3};real;"
        f"{_comma(fc, 2)};{_comma(pcs, 2)};{kwh};{_comma(eur, 2)}\n"
    ).encode()
    return csv, m3, kwh


#: The interior thermometer's export: a logger's CSV, a reading every ten
#: minutes, local time with its UTC offset (unambiguous on the October night).
THERMOMETER_HEADER = "Fecha y hora;Temperatura interior (ºC)"


def thermometer_csv(utc: np.ndarray, celsius: np.ndarray, tz) -> bytes:
    """What an interior thermometer logged, as its app exports it."""
    lines = [THERMOMETER_HEADER]
    for t, c in zip(utc, celsius, strict=True):
        local = datetime.fromtimestamp(int(t), tz)
        lines.append(f"{local.isoformat(timespec='minutes')};{_comma(float(c), 1)}")
    return ("\n".join(lines) + "\n").encode()
