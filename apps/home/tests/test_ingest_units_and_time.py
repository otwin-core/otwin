"""Units, numbers, hour conventions and DST, checked against hand-computed values."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

import ingest
from ingest import timeutil, units
from ingest._table import normalize_header, parse_number, read_table

MADRID = timeutil.zone("Europe/Madrid")


# ---------------------------------------------------------------- units


@pytest.mark.parametrize(
    "text, canonical, si",
    [
        ("kWh", "kWh", 3.6e6),
        ("KWH", "kWh", 3.6e6),
        ("Wh", "Wh", 3600.0),
        ("MWh", "MWh", 3.6e9),
        ("m³", "m^3", 1.0),
        ("m3", "m^3", 1.0),
        ("litros", "L", 1e-3),
        ("°C", "degC", 274.15),
        ("ºC", "degC", 274.15),  # Spanish ordinal sign typed for a degree
        ("°F", "degF", (1 + 459.67) * 5 / 9),
        ("W/m²", "W/m^2", 1.0),
        ("€", "EUR", 1.0),
    ],
)
def test_unit_spellings(text: str, canonical: str, si: float) -> None:
    assert units.parse_unit(text) == canonical
    assert units.to_si(1.0, canonical) == pytest.approx(si, rel=1e-12)
    assert units.from_si(units.to_si(2.5, canonical), canonical) == pytest.approx(2.5)


def test_mwh_and_milli_wh_are_not_confused() -> None:
    with pytest.raises(ValueError, match="unknown unit"):
        units.parse_unit("mWh")  # not a household unit; never read as MWh
    with pytest.raises(ValueError, match="unknown unit"):
        units.parse_unit("mwh")


def test_series_reports_values_in_any_unit_of_its_dimension() -> None:
    s = ingest.Series("gas_energy", "gas", ingest.INTERVAL, [0], [86400], [3.6e6])
    assert s.values_in("kWh").tolist() == [1.0]
    with pytest.raises(ValueError, match="not a unit of energy"):
        s.values_in("m3")


# ---------------------------------------------------------------- numbers


@pytest.mark.parametrize(
    "text, decimal, value",
    [
        ("0,267", ",", 0.267),
        ("1.234,5", ",", 1234.5),
        ("10.412", ",", 10412.0),  # meter reading with a thousands dot
        ("2.5", ".", 2.5),
        ("1,234.5", ".", 1234.5),
        ("-3", ".", -3.0),
    ],
)
def test_numbers(text: str, decimal: str, value: float) -> None:
    assert parse_number(text, decimal) == value


@pytest.mark.parametrize("text", ["0.267", "1.2.3", "12,34.5"])
def test_numbers_that_would_be_misread_in_a_decimal_comma_file(text: str) -> None:
    with pytest.raises(ValueError):
        parse_number(text, ",")


def test_decimal_mark_is_detected_per_file() -> None:
    assert read_table("a;b\n1;0,5\n").decimal == ","
    assert read_table("a;b\n1;0.5\n").decimal == "."
    assert read_table("a;b\n10.412;0,5\n").decimal == ","


def test_windows_1252_headers_are_decoded() -> None:
    raw = "CUPS;Fecha;Hora;Consumo_kWh;Método_obtención\n".encode("cp1252")
    t = read_table(raw)
    assert t.keys[-1] == "metodo_obtencion"
    assert normalize_header("LECTURA REAL/ESTIMADA") == "lectura_real_estimada"


# ---------------------------------------------------------------- time


def test_dst_day_lengths_and_midnights() -> None:
    assert timeutil.day_hours(date(2025, 3, 30), MADRID) == 23
    assert timeutil.day_hours(date(2025, 10, 26), MADRID) == 25
    assert timeutil.day_hours(date(2025, 6, 1), MADRID) == 24
    # 2025-01-01 00:00 CET is 2024-12-31 23:00 UTC.
    assert timeutil.midnight_utc(date(2025, 1, 1), MADRID) == 1735686000
    canary = timeutil.zone("Atlantic/Canary")
    assert timeutil.midnight_utc(date(2025, 1, 1), canary) == 1735689600


def test_skipped_and_repeated_wall_clock_times() -> None:
    with pytest.raises(ValueError, match="never happened"):
        timeutil.local_to_utc(datetime(2025, 3, 30, 2, 30), MADRID)
    folds = timeutil.FoldTracker(MADRID)
    first = folds.utc(datetime(2025, 10, 26, 2, 0))
    second = folds.utc(datetime(2025, 10, 26, 2, 0))
    assert second - first == 3600
    assert first == 1761436800  # 00:00 UTC, still CEST
    with pytest.raises(ValueError, match="more than once"):
        folds.utc(datetime(2025, 10, 26, 2, 0))


def test_parse_datetime_variants() -> None:
    assert timeutil.parse_datetime("2025/03/29 24:00") == (datetime(2025, 3, 30), False)
    assert timeutil.parse_datetime("29.03.2025 13:05") == (
        datetime(2025, 3, 29, 13, 5),
        False,
    )
    assert timeutil.parse_datetime("2025-03-29T13:05:00+01:00") == (
        datetime(2025, 3, 29, 12, 5),
        True,
    )
    with pytest.raises(ValueError, match="four digits"):
        timeutil.parse_date("03/29/25")


# ---------------------------------------------------------------- hour conventions


def _cnmc(rows: list[tuple[str, str]]) -> bytes:
    body = "".join(f"ES00X;{d};{h};0,100;R\n" for d, h in rows)
    return ("CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion\n" + body).encode()


def test_zero_based_hours_mean_hour_starting() -> None:
    [s] = ingest.load(_cnmc([("01/06/2025", str(h)) for h in range(24)]))
    assert s.start[0] == 1748728800  # 2025-06-01 00:00 CEST = 05-31 22:00 UTC


def test_one_based_hours_mean_hour_ending() -> None:
    [s] = ingest.load(_cnmc([("01/06/2025", str(h)) for h in range(1, 25)]))
    assert s.start[0] == 1748728800
    assert s.end[-1] == 1748728800 + 24 * 3600


def test_hhmm_labels_are_hour_numbers() -> None:
    [s] = ingest.load(_cnmc([("01/06/2025", f"{h:02d}:00") for h in range(1, 25)]))
    assert len(s) == 24 and s.start[0] == 1748728800


def test_ambiguous_partial_day_asks_for_the_convention() -> None:
    data = _cnmc([("01/06/2025", str(h)) for h in range(5, 10)])
    with pytest.raises(ingest.IngestError, match="hour_convention") as err:
        ingest.load(data)
    assert err.value.column == "Hora"
    [s] = ingest.load(data, hour_convention="end")
    assert s.start[0] == 1748728800 + 4 * 3600


def test_zero_based_wall_clock_labels_on_dst_days() -> None:
    """0..23 by the clock: 2 is missing in March and repeated in October."""
    march = [h for h in range(24) if h != 2]
    october = list(range(3)) + [2] + list(range(3, 24))
    data = _cnmc(
        [("30/03/2025", str(h)) for h in march]
        + [("26/10/2025", str(h)) for h in october]
    )
    [s] = ingest.load(data)
    assert len(s) == 23 + 25
    m0 = timeutil.midnight_utc(date(2025, 3, 30), MADRID)
    o0 = timeutil.midnight_utc(date(2025, 10, 26), MADRID)
    assert s.start[:23].tolist() == [m0 + 3600 * k for k in range(23)]
    assert s.start[23:].tolist() == [o0 + 3600 * k for k in range(25)]


def test_datadis_hour_starting_labels() -> None:
    recs = ",".join(
        f'{{"cups":"ES00X","date":"2025/06/01","time":"{h:02d}:00",'
        f'"consumptionKWh":0.1,"obtainMethod":"Real"}}'
        for h in range(24)
    )
    [s] = ingest.load(f"[{recs}]".encode())
    assert s.start[0] == 1748728800 and len(s) == 24


# ---------------------------------------------------------------- i-DE labels


def _ide(rows: list[tuple[str, str]]) -> bytes:
    body = "".join(f"ES00X;{t};{f};100;0;\n" for t, f in rows)
    return ("CUPS;FECHA-HORA;INV / VER;CONSUMO Wh;GENERACION Wh;\n" + body).encode()


def test_ide_october_change_accepts_either_label_for_the_extra_hour() -> None:
    """The hour 00:00-01:00 UTC on 26 Oct ends at 01:00 UTC, which reads as
    03:00 in summer time or 02:00 in winter time. Both must decode the same."""
    a = ingest.parse_ide_csv(
        _ide(
            [
                ("2025/10/26 02:00", "1"),
                ("2025/10/26 03:00", "1"),
                ("2025/10/26 03:00", "0"),
            ]
        )
    )
    b = ingest.parse_ide_csv(
        _ide(
            [
                ("2025/10/26 02:00", "1"),
                ("2025/10/26 02:00", "0"),
                ("2025/10/26 03:00", "0"),
            ]
        )
    )
    imp_a = next(s for s in a if s.quantity == "electricity_import")
    imp_b = next(s for s in b if s.quantity == "electricity_import")
    expected = [1761436800 - 3600, 1761436800, 1761436800 + 3600]
    assert imp_a.start.tolist() == expected
    assert imp_b.start.tolist() == expected


def test_ide_midnight_may_be_written_24_00() -> None:
    a = ingest.parse_ide_csv(_ide([("2025/06/01 24:00", "1")]))
    b = ingest.parse_ide_csv(_ide([("2025/06/02 00:00", "1")]))
    assert a[0].end.tolist() == b[0].end.tolist() == [1748815200]


# ---------------------------------------------------------------- schema and merge


def _hourly(values, start=0, quality=None):
    n = len(values)
    return ingest.Series(
        "plug_energy",
        "p",
        ingest.INTERVAL,
        [start + 3600 * k for k in range(n)],
        [start + 3600 * (k + 1) for k in range(n)],
        values,
        quality,
    )


def test_merge_drops_repeats_and_keeps_new_intervals() -> None:
    a = _hourly([1e5, 2e5, 3e5])
    b = _hourly([2e5, 3e5, 4e5], start=3600, quality=[1, 0, 0])
    m = ingest.merge(a, b)
    assert m.value.tolist() == [1e5, 2e5, 3e5, 4e5]
    assert m.quality.tolist() == [0, 0, 0, 0]  # a real reading wins over an estimate


def test_merge_refuses_conflicting_values() -> None:
    with pytest.raises(ValueError, match="conflicting"):
        ingest.merge(_hourly([1e5, 2e5]), _hourly([2.5e5], start=3600))


def test_series_refuses_overlaps_and_negative_energy() -> None:
    with pytest.raises(ingest.schema.SchemaError, match="overlaps"):
        ingest.Series(
            "plug_energy", "p", ingest.INTERVAL, [0, 1800], [3600, 5400], [1, 1]
        )
    with pytest.raises(ingest.schema.SchemaError, match="negative"):
        _hourly([-1.0])


def test_series_is_read_only() -> None:
    s = _hourly([1.0, 2.0])
    with pytest.raises(ValueError):
        s.value[0] = 5.0


# ---------------------------------------------------------------- load and describe


def test_load_rejects_options_the_parser_does_not_take() -> None:
    with pytest.raises(TypeError, match="does not take"):
        ingest.load(_cnmc([("01/06/2025", str(h)) for h in range(24)]), unitz={})


def test_describe_csv_suggests_roles_and_units() -> None:
    d = ingest.describe_csv(
        b"Fecha y hora;Lectura (L);Nota\n01/03/2025 00:00;1520,5;ok\n"
    )
    roles = {c.name: (c.role, c.unit) for c in d.columns}
    assert roles == {
        "Fecha y hora": ("time", None),
        "Lectura (L)": ("number", "L"),
        "Nota": ("text", None),
    }
    assert d.delimiter == ";" and d.decimal == ","


def test_generic_mapper_interval_from_single_column() -> None:
    data = b"time,kwh\n2025-06-01T00:00Z,0.5\n2025-06-01T00:15Z,0.25\n"
    [s] = ingest.parse_mapped(
        data,
        ingest.ColumnMap(
            quantity="electricity_import",
            value="kwh",
            unit="kWh",
            time="time",
            label="end",
        ),
    )
    assert s.start.tolist() == [1748735100, 1748736000]
    assert s.end.tolist() == [1748736000, 1748736900]
    np.testing.assert_allclose(s.values_in("kWh"), [0.5, 0.25])
