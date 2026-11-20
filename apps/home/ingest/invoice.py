"""Read the fields of a Spanish utility bill from the words on its pages.

The page (or the OCR in it) hands over *words with positions*: for a PDF
with a text layer, from pdf.js; for a scan or a photo, from the OCR run in
the browser. Where they came from does not matter here. This module turns
them into the handful of numbers Otwin Home needs from a bill, by rules,
not by any model: which utility it is (electricity, gas, water), who sent
it, the period it covers, the kWh or m³ charged, for gas the conversion
printed on it (Fc, PCS), the meter readings and the amount in euros.

Every field comes back with a confidence and the snippet it was read from,
so the page can show the householder what was read and let them correct it
before the bill is added. Nothing is added silently.

The rules are tolerant of OCR: accents are dropped, ``O``/``l`` inside a
number are read as digits, thousands dots and decimal commas are both
accepted, and labels are matched on normalised text.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

__all__ = ["Word", "Line", "Field", "Invoice", "lines_from_words", "read_invoice"]


@dataclass(frozen=True)
class Word:
    """One word on a page: its text and its box (page pixels, top-left origin)."""

    text: str
    x: float
    y: float
    w: float
    h: float
    conf: float = 1.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Line:
    """Words on one visual line, left to right."""

    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def norm(self) -> str:
        return _norm(self.text)

    @property
    def y(self) -> float:
        return sum(w.cy for w in self.words) / len(self.words)


@dataclass
class Field:
    """A value read from the bill, how sure we are, and where it was read."""

    value: object
    confidence: float
    evidence: str = ""


@dataclass
class Invoice:
    """What was read from a bill. Missing fields are ``None``."""

    kind: str  # "electricity", "gas", "water" or "unknown"
    kind_confidence: float
    supplier: str | None
    start: Field | None = None  # date
    end: Field | None = None  # date
    kwh: Field | None = None
    m3: Field | None = None
    fc: Field | None = None
    pcs: Field | None = None
    eur: Field | None = None
    reading_start: Field | None = None
    reading_end: Field | None = None
    text: str = ""  # the lines, for the record
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        def f(x: Field | None):
            if x is None:
                return None
            v = x.value.isoformat() if isinstance(x.value, date) else x.value
            return {
                "value": v,
                "confidence": round(x.confidence, 2),
                "evidence": x.evidence,
            }

        return {
            "kind": self.kind,
            "kind_confidence": round(self.kind_confidence, 2),
            "supplier": self.supplier,
            "start": f(self.start),
            "end": f(self.end),
            "kwh": f(self.kwh),
            "m3": f(self.m3),
            "fc": f(self.fc),
            "pcs": f(self.pcs),
            "eur": f(self.eur),
            "reading_start": f(self.reading_start),
            "reading_end": f(self.reading_end),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------- text


def _norm(text: str) -> str:
    """Lower case, no accents, one space between words."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("³", "3").replace("€", " eur ")
    return re.sub(r"\s+", " ", t).strip()


def lines_from_words(words: list[Word]) -> list[Line]:
    """Group words into visual lines: a word joins a line when its centre
    lies within the line's height band. Lines come top to bottom, words
    left to right."""
    if not words:
        return []
    order = sorted(words, key=lambda w: (w.cy, w.x))
    lines: list[list[Word]] = []
    for w in order:
        if lines:
            last = lines[-1]
            ly = sum(v.cy for v in last) / len(last)
            lh = sum(v.h for v in last) / len(last)
            if abs(w.cy - ly) <= 0.6 * max(lh, w.h, 1.0):
                last.append(w)
                continue
        lines.append([w])
    return [Line(sorted(ws, key=lambda v: v.x)) for ws in lines]


#: A number as a Spanish bill prints it: thousands dots, decimal comma; or
#: the other way round; OCR may read a 0 as O and a 1 as l or I.
_NUM = r"(?<![\w,.])(?:[0-9OolI]{1,3}(?:\.[0-9OolI]{3})+|[0-9OolI]+)(?:[,.][0-9OolI]{1,4})?(?![\w])"
_NUM_RE = re.compile(_NUM)


def _to_number(token: str) -> float | None:
    if not re.search(r"[0-9]", token):
        return None  # "l" or "O" alone is a letter, not a number
    t = (
        token.strip()
        .replace("O", "0")
        .replace("o", "0")
        .replace("l", "1")
        .replace("I", "1")
    )
    t = t.replace(" ", "")
    if not re.fullmatch(r"[0-9.,]+", t):
        return None
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")  # 1.234,56
        else:
            t = t.replace(",", "")  # 1,234.56
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = (
            f"{head.replace(',', '')}.{tail}"
            if len(tail) != 3 or "," in head
            else t.replace(",", "")
        )
    elif t.count(".") == 1:
        head, _, tail = t.partition(".")
        if len(tail) == 3 and len(head) <= 3:
            t = head + tail  # 1.234 is a thousand
    else:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("enero", "ene", "january", "jan"),
            ("febrero", "feb", "february"),
            ("marzo", "mar", "march"),
            ("abril", "abr", "april", "apr"),
            ("mayo", "may"),
            ("junio", "jun", "june"),
            ("julio", "jul", "july"),
            ("agosto", "ago", "august", "aug"),
            ("septiembre", "setiembre", "sep", "sept", "september"),
            ("octubre", "oct", "october"),
            ("noviembre", "nov", "november"),
            ("diciembre", "dic", "december", "dec"),
        ]
    )
    for m in names
}
_DATE_NUM = re.compile(r"\b([0-3]?\d)[/.\-]([01]?\d)[/.\-](20\d\d|\d\d)\b")
_DATE_WORDS = re.compile(
    r"\b([0-3]?\d)\s*(?:de\s+)?([a-z]{3,10})\.?\s*(?:de\s+|del\s+)?(20\d\d)\b"
)


def _dates_in(norm: str) -> list[tuple[int, date]]:
    """Every date in a normalised line, with where it starts."""
    out: list[tuple[int, date]] = []
    for m in _DATE_NUM.finditer(norm):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            out.append((m.start(), date(y, mo, d)))
        except ValueError:
            continue
    for m in _DATE_WORDS.finditer(norm):
        mo = _MONTHS.get(m.group(2))
        if mo is None:
            continue
        try:
            out.append((m.start(), date(int(m.group(3)), mo, int(m.group(1)))))
        except ValueError:
            continue
    return sorted(out)


# ---------------------------------------------------------------- lexicon

_SUPPLIERS = (
    ("iberdrola", "Iberdrola"),
    ("curenergia", "Iberdrola (Curenergía)"),
    ("endesa", "Endesa"),
    ("naturgy", "Naturgy"),
    ("gas natural fenosa", "Naturgy"),
    ("repsol", "Repsol"),
    ("totalenergies", "TotalEnergies"),
    ("holaluz", "Holaluz"),
    ("octopus", "Octopus"),
    ("edp", "EDP"),
    ("nedgia", "Nedgia"),
    ("canal de isabel", "Canal de Isabel II"),
    ("aigues de barcelona", "Aigües de Barcelona"),
    ("emasesa", "Emasesa"),
    ("emaya", "Emaya"),
    ("aguas de", "Aguas de …"),
    ("hidralia", "Hidralia"),
    ("aqualia", "Aqualia"),
    ("global omnium", "Global Omnium"),
)

_KIND_WORDS = {
    "electricity": (
        ("electricidad", 3),
        ("electrica", 3),
        ("electricity", 3),
        ("luz", 2),
        ("potencia contratada", 3),
        ("cups", 1),
        ("peaje", 1),
        ("kwh", 1),
        ("termino de potencia", 3),
        ("energia consumida", 2),
        ("iberdrola", 1),
        ("endesa", 1),
    ),
    "gas": (
        ("gas natural", 4),
        ("gas", 2),
        ("pcs", 3),
        ("poder calorifico", 3),
        ("factor de conversion", 3),
        ("coeficiente de conversion", 3),
        ("m3", 1),
        ("nedgia", 2),
        ("naturgy", 1),
        ("caldera", 1),
    ),
    "water": (
        ("agua", 4),
        ("water", 3),
        ("saneamiento", 3),
        ("alcantarillado", 3),
        ("depuracion", 3),
        ("canal de isabel", 3),
        ("aigues", 3),
        ("abastecimiento", 2),
        ("m3", 1),
        ("cuota de servicio", 1),
    ),
}

_PERIOD_WORDS = ("periodo", "facturacion", "consumo", "lectura", "del ", "desde", "hasta")
_TOTAL_WORDS = (
    "total factura",
    "importe total",
    "total a pagar",
    "total importe",
    "importe a pagar",
    "total",
)
_KWH_LABELS = (
    "consumo",
    "energia",
    "kwh facturados",
    "energia consumida",
    "total energia",
)
_M3_LABELS = ("consumo", "m3 facturados", "volumen", "agua consumida")


def _score_kind(norm_text: str) -> tuple[str, float]:
    scores = {k: 0 for k in _KIND_WORDS}
    for kind, words in _KIND_WORDS.items():
        for word, weight in words:
            scores[kind] += weight * len(re.findall(rf"\b{re.escape(word)}", norm_text))
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    if scores[best] == 0:
        return "unknown", 0.0
    return best, round(scores[best] / total, 2)


def _supplier(norm_text: str) -> str | None:
    for key, name in _SUPPLIERS:
        if key in norm_text:
            return name
    return None


def _numbers_before(norm: str, unit: str) -> list[float]:
    """Numbers directly followed by ``unit`` on the line ("1.234 kwh")."""
    out = []
    for m in re.finditer(rf"({_NUM})\s*{unit}\b", norm):
        v = _to_number(m.group(1))
        if v is not None:
            out.append(v)
    return out


def _numbers_in(norm: str) -> list[float]:
    out = []
    for m in _NUM_RE.finditer(norm):
        v = _to_number(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _after_label(
    lines: list[Line], labels: tuple[str, ...], lo: float, hi: float
) -> Field | None:
    """The first plausible number on a line with one of ``labels``, or on the
    line below it (tables print the label on one row, the value on the next)."""
    for i, line in enumerate(lines):
        n = line.norm
        hit = next((lbl for lbl in labels if lbl in n), None)
        if hit is None:
            continue
        after = n[n.index(hit) + len(hit) :]  # the value follows its label
        for cand, text in (
            (line, after),
            (lines[i + 1], lines[i + 1].norm) if i + 1 < len(lines) else (None, ""),
        ):
            if cand is None:
                continue
            for v in _numbers_in(text):
                if lo <= v <= hi:
                    return Field(v, 0.8 if cand is line else 0.6, cand.text)
    return None


# ---------------------------------------------------------------- reading


def read_invoice(pages: list[list[Word]], hint: str | None = None) -> Invoice:
    """Read a bill's fields from its pages' words.

    ``hint`` is what the householder said the file is ("gas", "electricity",
    "water", or free text such as "factura gas enero"); it settles the kind
    when the words themselves are not clear, and never overrides a clear one.
    """
    lines = [ln for page in pages for ln in lines_from_words(page)]
    text = "\n".join(ln.text for ln in lines)
    norm_text = _norm(text)
    kind, kind_conf = _score_kind(norm_text)
    hinted = _score_kind(_norm(hint or ""))[0] if hint else "unknown"
    if hinted != "unknown" and (kind == "unknown" or kind_conf < 0.6):
        kind, kind_conf = hinted, max(kind_conf, 0.7)
    inv = Invoice(kind, kind_conf, _supplier(norm_text), text=text)

    # the period: a pair of dates on a line about the period or the consumption;
    # failing that, any pair 20 to 70 days apart
    pairs: list[tuple[date, date, str, float]] = []
    for i, line in enumerate(lines):
        n = line.norm
        dates = [d for _, d in _dates_in(n)]
        if len(dates) < 2 and i + 1 < len(lines) and any(w in n for w in _PERIOD_WORDS):
            dates += [d for _, d in _dates_in(lines[i + 1].norm)]
        for a, b in zip(dates, dates[1:], strict=False):
            days = (b - a).days
            if 15 <= days <= 100:
                labelled = any(w in n for w in _PERIOD_WORDS)
                pairs.append((a, b, line.text, 0.9 if labelled else 0.6))
    if pairs:
        a, b, ev, conf = max(pairs, key=lambda p: p[3])
        inv.start, inv.end = Field(a, conf, ev), Field(b, conf, ev)

    # energy and volume, by unit first, then by label
    kwh_lines = [(ln, _numbers_before(ln.norm, "kwh")) for ln in lines]
    kwh_lines = [(ln, vs) for ln, vs in kwh_lines if vs]
    lo, hi = (30.0, 8000.0) if kind == "gas" else (20.0, 3000.0)
    if kwh_lines:
        # prefer a line about the consumption; among its numbers, the largest plausible
        def rank(item):
            ln, vs = item
            about = any(lbl in ln.norm for lbl in _KWH_LABELS)
            return (about, max((v for v in vs if lo <= v <= hi), default=0.0))

        ln, vs = max(kwh_lines, key=rank)
        plausible = [v for v in vs if lo <= v <= hi]
        if plausible:
            inv.kwh = Field(max(plausible), 0.9 if rank((ln, vs))[0] else 0.7, ln.text)
    if inv.kwh is None and kind != "water":
        inv.kwh = _after_label(lines, _KWH_LABELS, lo, hi)

    m3_lines = [(ln, _numbers_before(ln.norm, "m3")) for ln in lines]
    m3_lines = [(ln, vs) for ln, vs in m3_lines if vs]
    if m3_lines:
        ln, vs = max(
            m3_lines,
            key=lambda it: max(v for v in it[1] if v < 5000)
            if any(v < 5000 for v in it[1])
            else 0,
        )
        plausible = [v for v in vs if 1 <= v <= 2000]
        if plausible:
            inv.m3 = Field(max(plausible), 0.85, ln.text)
    if inv.m3 is None and kind != "electricity":
        inv.m3 = _after_label(lines, _M3_LABELS, 1, 2000)

    # the meter readings ("lectura anterior 4660 / lectura actual 4932")
    r0 = _after_label(
        lines, ("lectura anterior", "lectura inicial", "lectura inicio"), 0, 10_000_000
    )
    r1 = _after_label(
        lines, ("lectura actual", "lectura final", "lectura fin"), 0, 10_000_000
    )
    if r0 and r1 and r1.value >= r0.value:
        inv.reading_start, inv.reading_end = r0, r1
        if inv.m3 is None and 0 < r1.value - r0.value <= 2000:
            inv.m3 = Field(r1.value - r0.value, 0.7, f"{r0.evidence} / {r1.evidence}")

    if kind == "gas":
        inv.fc = _after_label(
            lines, ("factor de conversion", "coeficiente de conversion", "fc"), 0.85, 1.15
        )
        inv.pcs = _after_label(lines, ("pcs", "poder calorifico"), 9.0, 13.5)
        # the conversion printed on the bill explains the kWh; check it
        if inv.kwh and inv.m3 and inv.fc and inv.pcs:
            expected = inv.m3.value * inv.fc.value * inv.pcs.value
            if abs(expected / inv.kwh.value - 1) > 0.03:
                inv.notes.append("kwh_mismatch")
        elif inv.kwh and inv.m3 and not (inv.fc and inv.pcs):
            ratio = inv.kwh.value / inv.m3.value if inv.m3.value else 0
            if 9.5 <= ratio <= 13.5:
                # Fc × PCS as the bill implies; the page shows it as such
                inv.pcs = inv.pcs or Field(
                    round(ratio / (inv.fc.value if inv.fc else 1.0), 3), 0.5, "kWh ÷ m³"
                )
                inv.fc = inv.fc or Field(1.0, 0.4, "kWh ÷ m³")

    # the amount: the largest number on a line about the total, euros preferred
    best: Field | None = None
    for ln in lines:
        n = ln.norm
        if not any(w in n for w in _TOTAL_WORDS):
            continue
        vs = _numbers_before(n, "eur") or _numbers_in(n)
        vs = [
            v
            for v in vs
            if 1 <= v <= 5000 and v != int(v) or (1 <= v <= 5000 and "eur" in n)
        ]
        if not vs:
            continue
        v = max(vs)
        conf = (
            0.9
            if n.startswith(("total factura", "importe total", "total a pagar"))
            else 0.7
        )
        if (
            best is None
            or conf > best.confidence
            or (conf == best.confidence and v > best.value)
        ):
            best = Field(v, conf, ln.text)
    inv.eur = best
    return inv
