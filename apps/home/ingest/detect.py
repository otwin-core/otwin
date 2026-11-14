"""Recognise a household data file by its contents and parse it.

Detection looks at what the file *is*, never at its name: the zip signature
of a workbook, the shape of a JSON document, or the column headers of a CSV.
A file nothing recognises is refused with its columns listed and a pointer
to :class:`ingest.ColumnMap`.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable

from ._table import decode, read_table
from .bills import parse_gas_bills, parse_water_bills
from .electricity import parse_datadis_json, parse_distributor_csv, parse_ide_csv
from .errors import IngestError
from .homeassistant import parse_ha_history, parse_ha_statistics
from .plugs import parse_shelly_csv, parse_tapo_xlsx
from .schema import Series
from .weather import parse_open_meteo_csv, parse_open_meteo_json

__all__ = ["FORMATS", "detect_format", "load"]

#: Format name -> parser. Every parser takes the file bytes and ``source=``.
FORMATS: dict[str, Callable[..., list[Series]]] = {
    "datadis_json": parse_datadis_json,
    "distributor_csv": parse_distributor_csv,
    "ide_csv": parse_ide_csv,
    "shelly_csv": parse_shelly_csv,
    "tapo_xlsx": parse_tapo_xlsx,
    "ha_statistics": parse_ha_statistics,
    "ha_history": parse_ha_history,
    "gas_bills": parse_gas_bills,
    "water_bills": parse_water_bills,
    "open_meteo_json": parse_open_meteo_json,
    "open_meteo_csv": parse_open_meteo_csv,
}


def _detect_json(obj: object) -> str | None:
    if isinstance(obj, dict) and "hourly" in obj:
        return "open_meteo_json"
    probe = obj
    if isinstance(probe, dict):
        for key in ("timeCurve", "response", "data"):
            if key in probe:
                probe = probe[key]
                if isinstance(probe, dict) and "timeCurve" in probe:
                    probe = probe["timeCurve"]
                break
    if (
        isinstance(probe, list)
        and probe
        and isinstance(probe[0], dict)
        and "consumptionKWh" in probe[0]
    ):
        return "datadis_json"
    return None


def _detect_csv(keys: list[str]) -> str | None:
    k = set(keys)
    if {"fecha_hora", "inv_ver"} <= k:
        return "ide_csv"
    if {"statistic_id", "start"} <= k:
        return "ha_statistics"
    if {"entity_id", "state"} <= k and ({"last_changed", "last_updated"} & k):
        return "ha_history"
    # Shelly records are recognised by their timestamp and any active-energy or
    # power key, so a file missing total_act_energy reaches the parser, which
    # then names the missing column.
    if ({"timestamp", "ts"} & k) and any(
        "act_energy" in x or "act_power" in x for x in k
    ):
        return "shelly_csv"
    if "cups" in k:
        # Any per-supply-point file. If its hour or energy column is missing,
        # the parser says which.
        return "distributor_csv"
    bill = {"inicio", "start", "desde", "fecha_inicio"} & k and (
        {"fin", "end", "hasta", "fecha_fin"} & k
    )
    if bill:
        if {
            "fc",
            "factor_conversion",
            "pcs",
            "pcs_kwh_m3",
            "kwh",
            "consumo_kwh",
            "energy_kwh",
        } & k:
            return "gas_bills"
        return "water_bills"
    return None


def detect_format(data: bytes | str) -> str:
    """The :data:`FORMATS` name of a file, or an :class:`IngestError` saying why not."""
    if isinstance(data, bytes) and data[:4] == b"PK\x03\x04":
        return "tapo_xlsx"
    text = decode(data)
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            obj = json.loads(stripped)
        except ValueError as exc:
            raise IngestError(f"looks like JSON but does not parse: {exc}") from None
        name = _detect_json(obj)
        if name is None:
            raise IngestError(
                "JSON that is neither a Datadis consumption download nor an "
                "Open-Meteo response"
            )
        return name
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    if first.lower().startswith("latitude"):
        return "open_meteo_csv"
    table = read_table(text)
    name = _detect_csv(table.keys)
    if name is None:
        raise IngestError(
            f"unrecognised file; its columns are {table.headers}. Describe it with "
            "ingest.ColumnMap and read it with ingest.parse_mapped"
        )
    return name


def load(data: bytes | str, *, source: str = "", **options: object) -> list[Series]:
    """Detect the format of ``data`` and parse it.

    ``options`` go to the parser (``timezone=``, ``units=``, ``channel=``...).
    An option the detected parser does not take is an error, never silently
    ignored.
    """
    try:
        name = detect_format(data)
    except IngestError as exc:
        exc.source = exc.source or source
        raise
    parser = FORMATS[name]
    accepted = set(inspect.signature(parser).parameters)
    unknown = sorted(set(options) - accepted)
    if unknown:
        raise TypeError(
            f"{name} does not take {unknown}; it takes {sorted(accepted - {'data'})}"
        )
    return parser(data, source=source, **options)
