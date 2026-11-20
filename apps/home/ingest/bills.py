"""Hand-entered gas and water bills (ARCHITECTURE.md, "Ingest").

A bill is one row: the reading dates, the two meter readings, whether the
reading was real or estimated, and the amount. Gas bills also carry the
conversion factor ``Fc`` and the gross calorific value ``PCS`` printed on the
bill, because Spanish gas is billed in kWh computed as::

    kWh = m³ × Fc × PCS

The parser checks that equality on every bill and points at the kWh column
when it fails, instead of silently picking one of the two numbers.

**Columns** (Spanish or English, any order, case and accents ignored):

==================  =====================================  ==========
meaning             accepted headers                       required
==================  =====================================  ==========
period start        ``inicio``, ``start``, ``desde``       yes
period end          ``fin``, ``end``, ``hasta``            yes
reading at start    ``lectura_inicio_m3``, ``reading_start_m3``  readings or m³
reading at end      ``lectura_fin_m3``, ``reading_end_m3``
volume              ``m3``, ``consumo_m3``, ``volume_m3``
real / estimated    ``tipo``, ``type``                     no (real)
Fc (gas)            ``fc``, ``factor_conversion``          kWh or Fc+PCS
PCS (gas)           ``pcs_kwh_m3``, ``pcs``
energy (gas)        ``kwh``, ``consumo_kwh``, ``energy_kwh``
amount              ``importe_eur``, ``amount_eur``, ``total_eur``  no
==================  =====================================  ==========

**Dates are meter-reading dates.** A bill from 08/01 to 07/03 covers local
``[08/01 00:00, 07/03 00:00)``, and the next bill starts on 07/03. Bills
must not overlap. A gap between bills is allowed: it is a period with no
data. When one bill starts on the day the previous one ended, its start
reading must equal the previous end reading.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ._table import Table, read_table
from .errors import IngestError
from .schema import ESTIMATED, INTERVAL, REAL, Row, Series, series_from_rows
from .timeutil import DEFAULT_TZ, midnight_utc, parse_date, zone
from .units import to_si

__all__ = ["parse_gas_bills", "parse_water_bills", "bills_to_csv"]

_START = ("inicio", "start", "desde", "fecha_inicio")
_END = ("fin", "end", "hasta", "fecha_fin")
_R0 = ("lectura_inicio_m3", "reading_start_m3", "lectura_anterior_m3")
_R1 = ("lectura_fin_m3", "reading_end_m3", "lectura_actual_m3")
_M3 = ("m3", "consumo_m3", "volume_m3")
_TYPE = ("tipo", "type", "tipo_lectura")
_FC = ("fc", "factor_conversion")
_PCS = ("pcs_kwh_m3", "pcs")
_KWH = ("kwh", "consumo_kwh", "energy_kwh")
_EUR = ("importe_eur", "amount_eur", "total_eur", "importe")

_TYPES = {
    "": REAL,
    "real": REAL,
    "r": REAL,
    "estimada": ESTIMATED,
    "estimado": ESTIMATED,
    "estimated": ESTIMATED,
    "e": ESTIMATED,
}

#: Plausible ranges for the bill's gas constants. A PCS outside 9-13 kWh/m³
#: is usually a PCS typed in MJ/m³ (about 42) or a slip of the decimal mark.
FC_RANGE = (0.80, 1.10)
PCS_RANGE = (9.0, 13.0)


def _bills(t: Table, *, gas: bool, timezone: str, channel: str) -> list[Series]:
    tz = zone(timezone)
    src = t.source
    c_s = t.require(*_START, what="period start")
    c_e = t.require(*_END, what="period end")
    c_r0, c_r1, c_m3 = t.find(*_R0), t.find(*_R1), t.find(*_M3)
    if (c_r0 is None) != (c_r1 is None):
        missing = _R1[0] if c_r1 is None else _R0[0]
        raise IngestError(
            "give both meter readings or neither", column=missing, source=src
        )
    if c_r0 is None and c_m3 is None:
        raise IngestError(
            "missing the volume: give the meter readings "
            f"({_R0[0]}, {_R1[0]}) or the volume ({_M3[0]}); the columns are "
            f"{t.headers}",
            column=_M3[0],
            source=src,
        )
    c_type, c_eur = t.find(*_TYPE), t.find(*_EUR)
    c_fc = c_pcs = c_kwh = None
    if gas:
        c_fc, c_pcs, c_kwh = t.find(*_FC), t.find(*_PCS), t.find(*_KWH)
        if c_kwh is None and (c_fc is None or c_pcs is None):
            raise IngestError(
                "a gas bill needs the kWh billed, or both Fc and PCS to compute it; "
                f"the columns are {t.headers}",
                column=_KWH[0],
                source=src,
            )

    vol_rows: list[Row] = []
    kwh_rows: list[Row] = []
    eur_rows: list[Row] = []
    prev: tuple[int, float | None, int] | None = None  # (end, end reading, row)
    for r, cells in enumerate(t.rows):
        line = t.lines[r]
        try:
            d0 = parse_date(cells[c_s])
        except ValueError as exc:
            raise t.error(r, c_s, str(exc)) from None
        try:
            d1 = parse_date(cells[c_e])
        except ValueError as exc:
            raise t.error(r, c_e, str(exc)) from None
        if d1 <= d0:
            raise t.error(r, c_e, f"the period ends on {d1} but starts on {d0}")
        start, end = midnight_utc(d0, tz), midnight_utc(d1, tz)

        kind_txt = cells[c_type].strip().lower() if c_type is not None else ""
        if kind_txt not in _TYPES:
            raise t.error(r, c_type, f"{cells[c_type]!r} is neither real nor estimada")
        quality = _TYPES[kind_txt]

        reading_end: float | None = None
        if c_r0 is not None and c_r1 is not None:
            r0, r1 = t.number(r, c_r0), t.number(r, c_r1)
            if r1 < r0:
                raise t.error(
                    r, c_r1, f"the end reading {r1:g} is below the start reading {r0:g}"
                )
            m3 = r1 - r0
            reading_end = r1
            chained = prev is not None and prev[0] == start and prev[1] is not None
            if chained and abs(r0 - prev[1]) > 1e-6:  # type: ignore[index,operator]
                raise t.error(
                    r,
                    c_r0,
                    f"the start reading {r0:g} differs from the previous bill's "
                    f"end reading {prev[1]:g}",  # type: ignore[index]
                )
            if c_m3 is not None and cells[c_m3].strip():
                stated = t.number(r, c_m3)
                if abs(stated - m3) > 1e-6:
                    raise t.error(
                        r, c_m3, f"{stated:g} m³ but the readings differ by {m3:g} m³"
                    )
        else:
            assert c_m3 is not None
            m3 = t.number(r, c_m3)
        if prev is not None and start < prev[0]:
            raise t.error(r, c_s, "this bill overlaps the previous one")
        prev = (end, reading_end, r)
        vol_rows.append(Row(start, end, float(to_si(m3, "m^3")), quality, line))

        if gas:
            fc = pcs = None
            if c_fc is not None and cells[c_fc].strip():
                fc = t.number(r, c_fc)
                if not FC_RANGE[0] <= fc <= FC_RANGE[1]:
                    raise t.error(
                        r, c_fc, f"Fc {fc:g} is outside the plausible {FC_RANGE}"
                    )
            if c_pcs is not None and cells[c_pcs].strip():
                pcs = t.number(r, c_pcs)
                if not PCS_RANGE[0] <= pcs <= PCS_RANGE[1]:
                    raise t.error(
                        r,
                        c_pcs,
                        f"PCS {pcs:g} kWh/m³ is outside the plausible {PCS_RANGE}; "
                        "is it in MJ/m³?",
                    )
            computed = m3 * fc * pcs if fc is not None and pcs is not None else None
            if c_kwh is not None and cells[c_kwh].strip():
                kwh = t.number(r, c_kwh)
                if computed is not None:
                    tol = max(1.0, 0.005 * computed)
                    if abs(kwh - computed) > tol:
                        raise t.error(
                            r,
                            c_kwh,
                            f"{kwh:g} kWh but m³ × Fc × PCS = {m3:g} × {fc:g} × "
                            f"{pcs:g} = {computed:.1f} kWh",
                        )
            elif computed is not None:
                kwh = computed
            else:
                col = c_kwh if c_kwh is not None else c_fc
                raise t.error(r, col, "no kWh and no Fc and PCS to compute it")
            kwh_rows.append(Row(start, end, float(to_si(kwh, "kWh")), quality, line))

        if c_eur is not None and cells[c_eur].strip():
            eur_rows.append(Row(start, end, t.number(r, c_eur), quality, line))

    if not vol_rows:
        raise IngestError("the file has a header but no bills", source=src)
    prefix = "gas" if gas else "water"
    vol_col = t.headers[c_r1] if c_r1 is not None else t.headers[c_m3]  # type: ignore[index]
    common = {
        "channel": channel,
        "kind": INTERVAL,
        "source": src,
        "time_column": t.headers[c_s],
    }
    out = [
        series_from_rows(
            vol_rows, quantity=f"{prefix}_volume", value_column=vol_col, **common
        )
    ]
    if gas:
        kcol = t.headers[c_kwh] if c_kwh is not None else t.headers[c_pcs]  # type: ignore[index]
        out.append(
            series_from_rows(kwh_rows, quantity="gas_energy", value_column=kcol, **common)
        )
    if eur_rows:
        out.append(
            series_from_rows(
                eur_rows,
                quantity=f"{prefix}_cost",
                value_column=t.headers[c_eur],
                **common,
            )
        )  # type: ignore[index]
    return out


def parse_gas_bills(
    data: bytes | str,
    *,
    source: str = "",
    timezone: str = DEFAULT_TZ,
    channel: str = "gas",
) -> list[Series]:
    """Gas bills (CSV) to ``gas_volume``, ``gas_energy`` and, if given, ``gas_cost``."""
    return _bills(read_table(data, source), gas=True, timezone=timezone, channel=channel)


def parse_water_bills(
    data: bytes | str,
    *,
    source: str = "",
    timezone: str = DEFAULT_TZ,
    channel: str = "water",
) -> list[Series]:
    """Water bills (CSV) to ``water_volume`` and, if given, ``water_cost``."""
    return _bills(read_table(data, source), gas=False, timezone=timezone, channel=channel)


def bills_to_csv(records: Sequence[Mapping[str, object]]) -> str:
    """Bills typed into a form, as the CSV the parsers read.

    ``records`` are dicts keyed by any accepted header. The form and the CSV
    go through the same checks, so a typed bill is validated exactly like an
    uploaded one.
    """
    if not records:
        return ""
    keys: list[str] = []
    for rec in records:
        keys.extend(k for k in rec if k not in keys)
    lines = [";".join(keys)]
    for rec in records:
        cells = []
        for k in keys:
            v = rec.get(k)
            cells.append("" if v is None else str(v))
        lines.append(";".join(cells))
    return "\n".join(lines) + "\n"
