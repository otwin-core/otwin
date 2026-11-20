"""Reading a bill's fields from the words on its pages (ingest.invoice).

The words come from a PDF's text layer or from OCR in the browser; here they
are laid out by hand, as a Spanish bill prints them, with the dates in the
two usual forms, thousands dots and decimal commas, and a few OCR slips.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from ingest import Word, lines_from_words, read_invoice

WEB = Path(__file__).resolve().parents[1] / "web"
for extra in (WEB / "py",):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def page(*rows: str, step: float = 20.0) -> list[Word]:
    """Rows of text to words with boxes: each word 8 px per character."""
    words = []
    for i, row in enumerate(rows):
        x = 40.0
        for token in row.split():
            words.append(Word(token, x, 40.0 + i * step, 8.0 * len(token), 12.0))
            x += 8.0 * len(token) + 8.0
    return words


def test_words_become_lines_top_to_bottom_left_to_right():
    words = [Word("b", 50, 10, 8, 12), Word("a", 10, 11, 8, 12), Word("c", 10, 40, 8, 12)]
    lines = lines_from_words(words)
    assert [ln.text for ln in lines] == ["a b", "c"]


def test_a_gas_bill_as_naturgy_prints_it():
    inv = read_invoice(
        [
            page(
                "NATURGY Iberia S.A. Factura de gas natural",
                "Periodo de facturación: del 15/12/2025 al 15/01/2026",
                "Lectura anterior 4.660 m3 Lectura actual 4.932 m3",
                "Consumo 272 m3 Factor de conversión 0,95 PCS 11,66 kWh/m3",
                "Energía consumida 3.013 kWh",
                "TOTAL FACTURA 226,36 €",
            )
        ]
    )
    assert inv.kind == "gas" and inv.supplier == "Naturgy"
    assert (inv.start.value, inv.end.value) == (date(2025, 12, 15), date(2026, 1, 15))
    assert inv.kwh.value == 3013 and inv.m3.value == 272
    assert inv.fc.value == pytest.approx(0.95) and inv.pcs.value == pytest.approx(11.66)
    assert inv.eur.value == pytest.approx(226.36)
    assert inv.reading_start.value == 4660 and inv.reading_end.value == 4932
    assert inv.notes == []  # m³ × Fc × PCS gives the kWh


def test_an_electricity_bill_with_dates_in_words_and_ocr_slips():
    inv = read_invoice(
        [
            page(
                "IBERDROLA CLIENTES Factura de electricidad",
                "Consumo del 1 de enero de 2026 al 31 de enero de 2026",
                "Potencia contratada 4,6 kW",
                "Energía consumida 1.O51 kWh",  # OCR read a zero as an O
                "Importe total 178,40 €",
            )
        ]
    )
    assert inv.kind == "electricity" and inv.supplier == "Iberdrola"
    assert (inv.start.value, inv.end.value) == (date(2026, 1, 1), date(2026, 1, 31))
    assert inv.kwh.value == 1051 and inv.eur.value == pytest.approx(178.40)
    assert inv.m3 is None and inv.fc is None


def test_a_water_bill_and_the_householders_hint():
    words = page(
        "Canal de Isabel II",
        "Periodo 15/12/2025 - 15/01/2026",
        "Consumo 11 m3",
        "Total a pagar 32,10",
    )
    inv = read_invoice([words])
    assert (
        inv.kind == "water"
        and inv.m3.value == 11
        and inv.eur.value == pytest.approx(32.10)
    )
    # a document that says little is placed by what the householder said
    vague = read_invoice(
        [page("Periodo 15/12/2025 - 15/01/2026", "Consumo 11 m3", "Total 32,10")],
        hint="factura agua",
    )
    assert vague.kind == "water"


def test_a_mismatch_between_m3_and_kwh_is_flagged():
    inv = read_invoice(
        [
            page(
                "Gas natural",
                "Consumo 272 m3",
                "Fc 0,95 PCS 11,66",
                "Energía 2.000 kWh",
                "Total 150,00 €",
            )
        ]
    )
    assert "kwh_mismatch" in inv.notes


def test_the_engine_prefills_the_form_and_says_what_it_read():
    import webmain

    webmain.set_language("es")
    words = [
        {"text": t, "x": 40 + 8 * i, "y": 40 + 20 * r, "w": 8 * len(t), "h": 12}
        for r, row in enumerate(
            [
                "NATURGY Factura de gas natural",
                "Periodo de facturación: del 15/12/2025 al 15/01/2026",
                "Consumo 272 m3 Factor de conversión 0,95 PCS 11,66",
                "Energía consumida 3.013 kWh",
                "TOTAL FACTURA 226,36 €",
            ]
        )
        for i, t in enumerate(row.split())
    ]
    out = webmain.read_invoice([words])
    assert out["ok"] and out["kind"] == "gas"
    assert out["form"] == {
        "start": "2025-12-15",
        "end": "2026-01-15",
        "kwh": "3013",
        "m3": "272",
        "fc": "0.95",
        "pcs": "11.66",
        "eur": "226.36",
    }
    assert out["sentence"].startswith(
        "Parece una factura de gas de Naturgy, del 15/12/2025 al 15/01/2026"
    )
    webmain.set_language("en")
    # and an electricity bill, typed in, becomes a file of the session
    webmain.forget()
    s = webmain.add_bill(
        "e1",
        "electricity",
        {"start": "2026-01-01", "end": "2026-02-01", "kwh": "1051", "eur": "178.40"},
    )
    assert (
        s["status"] == "ok"
        and s["message"]
        == "Electricity bill, 1 Jan 2026 to 31 Jan 2026: 1,051 kWh, 178.40 €."
    )
    webmain.forget()
