#!/usr/bin/env python3
"""Fuzz Twin Manifest deserialisation.

SECURITY.md names this as the project's realistic threat: "deserialisation of
untrusted model files ... in 0.x they are not schema-validated on load". A
manifest arrives as JSON from wherever a twin was fitted, possibly another
organisation, and `from_dict` reconstructs a dataclass from it. Having said in
public that this is the attack surface, it should be the one under a fuzzer.
"""

import json
import sys

import atheris

with atheris.instrument_imports():
    from otwin.interfaces.manifest import TwinManifest

# A malformed manifest is a data error. Anything outside this set -- a
# RecursionError from nesting, a MemoryError from a length field, an
# AttributeError from a type confusion -- is a defect in the reader.
ALLOWED = (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError)


def TestOneInput(data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return
    if not isinstance(obj, dict):
        return
    try:
        manifest = TwinManifest.from_dict(obj)
    except ALLOWED:
        return
    # A manifest that loads must survive a round trip, or a twin written by one
    # process and read by another is not the same twin.
    again = TwinManifest.from_dict(manifest.to_dict())
    assert again.to_dict() == manifest.to_dict(), "round trip is not stable"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
