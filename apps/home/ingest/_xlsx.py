"""A minimal, dependency-free reader for the cell values of an .xlsx workbook.

An .xlsx file is a zip of XML parts. Smart-plug apps export plain tables:
strings, numbers and dates stored as numbers. Reading those needs the
workbook part (sheet names), its relationships (which file holds each
sheet), the shared-strings table and the sheets themselves, about a hundred
lines of standard library. That keeps ``openpyxl`` out of the dependency
list and out of the browser bundle. Formulas are read through their cached
values, and styles are ignored.

The file is untrusted input, so member sizes are capped before anything is
decompressed.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

__all__ = ["read_xlsx", "XlsxError", "Cell"]

Cell = str | float | None

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_MAX_MEMBER = 64 * 1024 * 1024
_MAX_TOTAL = 256 * 1024 * 1024
_REF = re.compile(r"^([A-Z]+)(\d+)$")


class XlsxError(ValueError):
    """The bytes are not a readable workbook."""


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _text(el: ET.Element) -> str:
    # <si> and <is> hold either <t> or rich-text runs <r><t>.
    return "".join(t.text or "" for t in el.iter(f"{{{_NS['m']}}}t"))


def read_xlsx(data: bytes) -> dict[str, list[list[Cell]]]:
    """Every sheet of a workbook as rows of cell values, in workbook order.

    Strings come back as ``str``, numbers (dates included) as ``float``,
    booleans as ``1.0``/``0.0`` and empty cells as ``None``. Rows are padded
    so that a cell's position in its row is its column index.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError("not an .xlsx workbook (not a zip archive)") from exc
    with zf:
        infos = {i.filename: i for i in zf.infolist()}
        if sum(i.file_size for i in infos.values()) > _MAX_TOTAL:
            raise XlsxError("workbook too large once decompressed")

        def part(name: str) -> bytes:
            info = infos.get(name)
            if info is None:
                raise XlsxError(f"workbook part {name} is missing")
            if info.file_size > _MAX_MEMBER:
                raise XlsxError(f"workbook part {name} is too large")
            return zf.read(info)

        try:
            wb = ET.fromstring(part("xl/workbook.xml"))
            rels = ET.fromstring(part("xl/_rels/workbook.xml.rels"))
            shared: list[str] = []
            if "xl/sharedStrings.xml" in infos:
                sst = ET.fromstring(part("xl/sharedStrings.xml"))
                shared = [_text(si) for si in sst.findall("m:si", _NS)]
            targets = {
                r.get("Id"): r.get("Target", "")
                for r in rels.findall("pr:Relationship", _NS)
            }
            out: dict[str, list[list[Cell]]] = {}
            for sheet in wb.findall("m:sheets/m:sheet", _NS):
                name = sheet.get("name", "")
                rid = sheet.get(f"{{{_NS['r']}}}id")
                target = targets.get(rid)
                if target is None:
                    raise XlsxError(f"sheet {name!r} has no part")
                path = (
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.normpath(posixpath.join("xl", target))
                )
                out[name] = _read_sheet(ET.fromstring(part(path)), shared)
            return out
        except ET.ParseError as exc:
            raise XlsxError(f"workbook XML is malformed: {exc}") from exc


def _read_sheet(root: ET.Element, shared: list[str]) -> list[list[Cell]]:
    rows: dict[int, dict[int, Cell]] = {}
    next_row = 0
    for row in root.iterfind("m:sheetData/m:row", _NS):
        r_attr = row.get("r")
        r = int(r_attr) - 1 if r_attr else next_row
        next_row = r + 1
        cells: dict[int, Cell] = {}
        next_col = 0
        for c in row.findall("m:c", _NS):
            ref = c.get("r")
            if ref:
                m = _REF.match(ref)
                if not m:
                    raise XlsxError(f"bad cell reference {ref!r}")
                col = _col_index(m.group(1))
            else:
                col = next_col
            next_col = col + 1
            kind = c.get("t", "n")
            v = c.find("m:v", _NS)
            if kind == "inlineStr":
                is_ = c.find("m:is", _NS)
                cells[col] = _text(is_) if is_ is not None else ""
            elif v is None or v.text is None:
                cells[col] = None
            elif kind == "s":
                idx = int(v.text)
                if not 0 <= idx < len(shared):
                    raise XlsxError(f"cell {ref} points at a missing shared string")
                cells[col] = shared[idx]
            elif kind in ("str", "e"):
                cells[col] = v.text
            elif kind == "b":
                cells[col] = 1.0 if v.text.strip() == "1" else 0.0
            else:
                try:
                    cells[col] = float(v.text)
                except ValueError as exc:
                    raise XlsxError(f"cell {ref} holds {v.text!r}, not a number") from exc
        rows[r] = cells
    if not rows:
        return []
    out: list[list[Cell]] = []
    for r in range(max(rows) + 1):
        cells = rows.get(r, {})
        width = max(cells) + 1 if cells else 0
        out.append([cells.get(c) for c in range(width)])
    return out
