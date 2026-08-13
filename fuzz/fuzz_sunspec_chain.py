#!/usr/bin/env python3
"""Fuzz the SunSpec model-chain walker with arbitrary register contents.

This is the highest-value target in the package. `SunSpecSource` walks a
device's model chain -- a linked list of (model id, length, payload) blocks --
and decodes every point in it, using length fields, scale-factor registers and
not-implemented sentinels that all come off the wire. Every one of those is
attacker-controlled if the device or the network is.

The contract being fuzzed is the one `read()` documents: it does not raise for
a wire-level problem. Everything it can say about a misbehaving link, it says
through `Sample.quality`. Two real defects in this path were already found by
hand -- an unguarded `10.0 ** exponent` that raised OverflowError out of
`read()` and lost the whole sample, and a state-of-charge fallback that gave up
while the other model was answering cleanly. Finding two by inspection is a
good reason to look harder by machine.
"""

import sys

import atheris

with atheris.instrument_imports():
    from otwin.io import SunSpecSource
    from otwin.io.source import MissingDependencyError, TransportError, UnknownUnitError

# Exceptions the API is documented to raise. Anything else escaping is a bug:
# an OverflowError, IndexError, struct.error or RecursionError reaching the
# caller means a malformed register chain took down the reader.
ALLOWED = (
    TransportError,
    LookupError,
    ValueError,
    MissingDependencyError,
    UnknownUnitError,
)


class FuzzTransport:
    """Serves the fuzzer's bytes as 16-bit registers, wrapping on overrun."""

    name = "fuzz://registers"

    def __init__(self, words: list[int]) -> None:
        self._words = words or [0]

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        if count < 1 or count > 125:
            raise TransportError(f"illegal count {count}")
        n = len(self._words)
        return [self._words[(address + i) % n] for i in range(count)]

    def close(self) -> None:
        pass


def TestOneInput(data: bytes) -> None:
    if len(data) < 8:
        return
    words = [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data) - 1, 2)]
    src = SunSpecSource(transport=FuzzTransport(words), discover_now=False)
    try:
        src.discover()
    except ALLOWED:
        return
    try:
        sample = src.read()
    except ALLOWED:
        return
    # read() promises never to raise for a wire problem, so a quality string is
    # the only legal outcome. Assert the ladder stays well-formed.
    for tag, q in sample.quality.items():
        assert q in ("good", "stale", "bad"), f"{tag}: unknown quality {q!r}"
    try:
        soc = src.soc(sample)
    except ALLOWED:
        return
    assert 0.0 <= soc <= 1.0, f"soc() returned {soc}, outside [0, 1]"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
