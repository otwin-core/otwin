"""Otwin Home ingest: household data files to one checked time-series shape.

Every parser takes the bytes of a file a household can export today and
returns a list of :class:`Series`. Each Series holds one quantity
(electricity imported, plug energy, gas, water, outdoor temperature...) on
one channel (a CUPS, a plug, a bill, a weather cell), as UTC intervals or
instants with values in SI units. See ARCHITECTURE.md for where each file comes
from.

>>> import ingest
>>> csv = "CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion\\n" + "".join(
...     f"ES0000000000000000XX;01/02/2025;{h};0,250;R\\n" for h in range(1, 25))
>>> [s] = ingest.load(csv.encode(), source="consumo.csv")
>>> s.quantity, len(s), float(s.values_in("kWh").sum())
('electricity_import', 24, 6.0)

Nothing here touches the network. The package needs only the standard
library and NumPy, so it runs unchanged under Pyodide.
"""

from __future__ import annotations

from .bills import bills_to_csv, parse_gas_bills, parse_water_bills
from .detect import FORMATS, detect_format, load
from .electricity import parse_datadis_json, parse_distributor_csv, parse_ide_csv
from .errors import IngestError
from .generic import ColumnGuess, ColumnMap, CsvDescription, describe_csv, parse_mapped
from .homeassistant import parse_ha_history, parse_ha_statistics
from .invoice import Invoice, Word, lines_from_words, read_invoice
from .plugs import parse_shelly_csv, parse_tapo_xlsx
from .schema import (
    ESTIMATED,
    INSTANT,
    INTERVAL,
    MEAN,
    QUANTITIES,
    REAL,
    QuantitySpec,
    Series,
    merge,
)
from .weather import parse_open_meteo_csv, parse_open_meteo_json

__all__ = [
    "Invoice",
    "Word",
    "lines_from_words",
    "read_invoice",
    "Series",
    "QuantitySpec",
    "QUANTITIES",
    "INTERVAL",
    "MEAN",
    "INSTANT",
    "REAL",
    "ESTIMATED",
    "IngestError",
    "merge",
    "load",
    "detect_format",
    "FORMATS",
    "parse_datadis_json",
    "parse_distributor_csv",
    "parse_ide_csv",
    "parse_shelly_csv",
    "parse_tapo_xlsx",
    "parse_ha_statistics",
    "parse_ha_history",
    "parse_gas_bills",
    "parse_water_bills",
    "bills_to_csv",
    "parse_open_meteo_json",
    "parse_open_meteo_csv",
    "ColumnMap",
    "parse_mapped",
    "describe_csv",
    "CsvDescription",
    "ColumnGuess",
]
