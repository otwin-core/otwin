"""Reading delimited text as Spanish utilities and devices write it.

Encoding (UTF-8, with or without BOM, or Windows-1252 from older portals),
delimiter (``;``, ``,`` or tab), decimal mark (``,`` or ``.``) and trailing
empty columns are all detected here, so the format parsers deal only with
named columns.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import IngestError

__all__ = ["Table", "decode", "normalize_header", "read_table", "parse_number"]


def decode(data: bytes | str) -> str:
    """Bytes to text: UTF-8 (BOM stripped) first, then Windows-1252, then Latin-1."""
    if isinstance(data, str):
        return data.lstrip("﻿")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def normalize_header(header: str) -> str:
    """Lower case, accents removed, every run of other characters one ``_``.

    >>> normalize_header("Método_obtención"), normalize_header("INV / VER")
    ('metodo_obtencion', 'inv_ver')
    >>> normalize_header("CONSUMO Wh"), normalize_header("REAL/ESTIMADO")
    ('consumo_wh', 'real_estimado')
    """
    text = unicodedata.normalize("NFKD", header)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")


_NUMERIC = re.compile(r"^[+-]?[\d.,]*\d[\d.,]*$")
_THOUSANDS_DOT = re.compile(r"^[+-]?[1-9]\d{0,2}(\.\d{3})+(,\d*)?$")
_THOUSANDS_COMMA = re.compile(r"^[+-]?[1-9]\d{0,2}(,\d{3})+(\.\d*)?$")


def parse_number(text: str, decimal: str = ".") -> float:
    """A number as written with ``decimal`` as the decimal mark.

    With a decimal comma, a dot is accepted only as a thousands separator in
    its proper place (``1.234,5``). ``0.267`` in a decimal-comma file is
    refused rather than read as 267.

    >>> parse_number("0,267", ","), parse_number("1.234,5", ","), parse_number("2.5")
    (0.267, 1234.5, 2.5)
    """
    t = text.strip().replace(" ", "").replace(" ", "")
    if not t or not _NUMERIC.match(t):
        raise ValueError(f"{text!r} is not a number")
    if decimal == ",":
        if "." in t:
            if not _THOUSANDS_DOT.match(t):
                raise ValueError(
                    f"{text!r} is ambiguous in a file that uses a decimal comma"
                )
            t = t.replace(".", "")
        t = t.replace(",", ".")
    else:
        if "," in t:
            if not _THOUSANDS_COMMA.match(t):
                raise ValueError(
                    f"{text!r} is ambiguous in a file that uses a decimal point"
                )
            t = t.replace(",", "")
    if t.count(".") > 1:
        raise ValueError(f"{text!r} is not a number")
    return float(t)


def _sniff_delimiter(header_line: str) -> str:
    counts = {d: header_line.count(d) for d in (";", "\t", ",")}
    best = max(counts, key=lambda d: (counts[d], d == ";"))
    return best if counts[best] else ","


def _sniff_decimal(cells: Iterable[str], delimiter: str) -> str:
    # Quoted decimal commas can occur even in a comma-delimited file, so the
    # cells are inspected whatever the delimiter.
    comma = dot = 0
    for c in cells:
        c = c.strip()
        if not c or not _NUMERIC.match(c):
            continue
        has_c, has_d = "," in c, "." in c
        if has_c and has_d:
            return "," if c.rfind(",") > c.rfind(".") else "."
        comma += has_c
        dot += has_d and not _THOUSANDS_DOT.match(c)
    if comma and not dot:
        return ","
    return "."


@dataclass
class Table:
    """A delimited file as a header and rows of strings, with file line numbers."""

    headers: list[str]
    keys: list[str]
    rows: list[list[str]]
    lines: list[int]
    delimiter: str
    decimal: str
    source: str

    def find(self, *candidates: str) -> int | None:
        """Index of the first column whose normalised header is one of ``candidates``."""
        for cand in candidates:
            if cand in self.keys:
                return self.keys.index(cand)
        return None

    def require(self, *candidates: str, what: str) -> int:
        """As :meth:`find`, but a missing column is an :class:`IngestError`."""
        i = self.find(*candidates)
        if i is None:
            raise IngestError(
                f"missing the {what} column (expected one of {list(candidates)}); "
                f"the columns are {self.headers}",
                column=candidates[0],
                source=self.source,
            )
        return i

    def number(self, r: int, c: int) -> float:
        """Cell ``(r, c)`` as a number, or an :class:`IngestError` naming it."""
        try:
            return parse_number(self.rows[r][c], self.decimal)
        except ValueError as exc:
            raise self.error(r, c, str(exc)) from None

    def error(self, r: int, c: int | None, message: str) -> IngestError:
        """An :class:`IngestError` located at row ``r`` (0-based) and column ``c``."""
        return IngestError(
            message,
            column=None if c is None else self.headers[c],
            line=self.lines[r],
            source=self.source,
        )


def read_table(
    data: bytes | str,
    source: str = "",
    *,
    delimiter: str | None = None,
    decimal: str | None = None,
    text: str | None = None,
) -> Table:
    """Parse delimited text into a :class:`Table`.

    The first non-blank line is the header. Blank lines are skipped. A row
    shorter than the header names the first missing column. A row longer than
    the header is accepted only if the extra cells are empty, which is the
    trailing ``;`` that i-DE files have.
    """
    body = decode(data) if text is None else text
    lines = body.splitlines()
    first = next((ln for ln in lines if ln.strip()), None)
    if first is None:
        raise IngestError("the file is empty", source=source)
    delim = delimiter or _sniff_delimiter(first)
    reader = csv.reader(io.StringIO(body, newline=""), delimiter=delim)
    headers: list[str] | None = None
    rows: list[list[str]] = []
    line_numbers: list[int] = []
    prev_line = 0
    for cells in reader:
        row_line = prev_line + 1
        prev_line = reader.line_num
        if not any(c.strip() for c in cells):
            continue
        if headers is None:
            headers = [c.strip() for c in cells]
            while headers and not headers[-1]:
                headers.pop()
            continue
        rows.append(cells)
        line_numbers.append(row_line)
    assert headers is not None
    if len(set(headers)) != len(headers):
        dup = next(h for h in headers if headers.count(h) > 1)
        raise IngestError("this column appears twice", column=dup, source=source)
    n = len(headers)
    for k, cells in enumerate(rows):
        if len(cells) < n:
            raise IngestError(
                f"the row has {len(cells)} cells but the header has {n}",
                column=headers[len(cells)],
                line=line_numbers[k],
                source=source,
            )
        if len(cells) > n:
            extra = [c for c in cells[n:] if c.strip()]
            if extra:
                raise IngestError(
                    f"the row has a value {extra[0]!r} beyond the last column",
                    column=headers[-1],
                    line=line_numbers[k],
                    source=source,
                )
            rows[k] = cells[:n]
    dec = decimal or _sniff_decimal((c for r in rows for c in r), delim)
    keys = [normalize_header(h) for h in headers]
    return Table(headers, keys, rows, line_numbers, delim, dec, source)
