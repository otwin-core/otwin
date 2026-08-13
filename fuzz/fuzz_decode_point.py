#!/usr/bin/env python3
"""Fuzz the SunSpec point decoder: raw registers plus a declared wire type.

`decode_point` is the innermost function in the ingest path. Every value the
library ever reads from a device passes through it, carrying a length and a
type that the device declared and nobody verified. It must return a float or
None -- never raise, never return something that poisons arithmetic downstream.
"""

import sys

import atheris

with atheris.instrument_imports():
    from otwin.io.sunspec import _TYPES, decode_point

TYPES = sorted(_TYPES) + ["string8", "not-a-type", ""]


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    ptype = TYPES[fdp.ConsumeIntInRange(0, len(TYPES) - 1)]
    n_words = fdp.ConsumeIntInRange(0, 8)
    words = [fdp.ConsumeIntInRange(0, 0xFFFF) for _ in range(n_words)]
    value = decode_point(words, ptype)
    assert value is None or isinstance(value, float), (
        f"decode_point({words!r}, {ptype!r}) returned {value!r}"
    )


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
