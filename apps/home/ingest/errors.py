"""The one error every parser raises, with the place in the file it comes from."""

from __future__ import annotations

__all__ = ["IngestError"]


class IngestError(ValueError):
    """A file that cannot be read as it stands.

    Every rejection names where the problem is, so a non-engineer can open
    the file and find it: the file, the line (or record, for JSON) and the
    column. ``str(err)`` reads, for example::

        consumo.csv: line 14: column 'Consumo_kWh': '0,2x7' is not a number

    Attributes:
        message: what is wrong, without the location.
        column: the column (CSV header or JSON field) as written in the file.
        line: 1-based line number in the file, or record number for JSON.
        line_label: ``"line"`` or ``"record"``.
        source: the file name or a description of where the data came from.
    """

    def __init__(
        self,
        message: str,
        *,
        column: str | None = None,
        line: int | None = None,
        line_label: str = "line",
        source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.column = column
        self.line = line
        self.line_label = line_label
        self.source = source

    def __str__(self) -> str:
        where = []
        if self.source:
            where.append(self.source)
        if self.line is not None:
            where.append(f"{self.line_label} {self.line}")
        if self.column is not None:
            where.append(f"column '{self.column}'")
        prefix = ": ".join(where)
        return f"{prefix}: {self.message}" if prefix else self.message
