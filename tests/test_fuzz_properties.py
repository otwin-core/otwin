"""The fuzz targets' properties, run deterministically in ordinary CI.

`fuzz/` holds Atheris targets for ClusterFuzzLite. Those need a container and a
time budget, so they run on pull requests and nightly — not on a laptop. The
properties they check are worth having on every `pytest` run regardless, so
they are restated here over a fixed, seeded set of mutations.

This is deliberately not a substitute for coverage-guided fuzzing. It is the
floor: if one of these fails, the corresponding fuzz target would have failed
too, and you find out in eight seconds instead of on the nightly run.

The `_scale` defect these were written after -- an unguarded ``10.0 **
exponent`` that raised ``OverflowError`` out of ``read()`` and lost every model
on the chain -- is caught by ``test_a_mutated_register_image_never_escapes``
on the first mutated input when the fix is reverted.
"""

from __future__ import annotations

import json
import random

import pytest

from otwin.interfaces.manifest import Provenance, TwinManifest
from otwin.io import SunSpecSource
from otwin.io.simulator import SunSpecSimulator
from otwin.io.source import (
    MissingDependencyError,
    TransportError,
    UnknownUnitError,
)
from otwin.io.sunspec import _TYPES, decode_point

#: What the ingest API is documented to raise. Anything else reaching a caller
#: -- OverflowError, IndexError, struct.error, RecursionError -- means a
#: malformed register chain took the reader down with it.
ALLOWED_IO = (
    TransportError,
    LookupError,
    ValueError,
    MissingDependencyError,
    UnknownUnitError,
)

_BASE = 40000
_CORRUPTIONS = (0x0000, 0xFFFF, 0x8000, 0x7FFF, 0x0190, 0xFF9C, 0x0001)


class _ImageTransport:
    """Serves a fixed register image, wrapping on overrun."""

    name = "fuzz://image"

    def __init__(self, words: list[int]) -> None:
        self._words = words or [0]

    def read_registers(
        self, address: int, count: int, register_type: str = "holding"
    ) -> list[int]:
        if not 1 <= count <= 125:
            raise TransportError(f"illegal count {count}")
        offset = address - _BASE
        if offset < 0:
            return [0] * count
        n = len(self._words)
        return [self._words[(offset + i) % n] for i in range(count)]

    def close(self) -> None:
        pass


def _seed_image(soc: float = 0.5) -> list[int]:
    return list(SunSpecSimulator(soc=soc).get_raw(_BASE, 900))


def test_a_mutated_register_image_never_escapes() -> None:
    """read() promises never to raise for a wire-level problem. Hold it to that.

    Every field a SunSpec device publishes -- model ids, block lengths, scale
    factors, not-implemented sentinels -- is attacker-controlled if the bus is.
    Starting from a valid image and corrupting a handful of words per trial is
    the cheapest way to reach the decode paths a hand-written test never
    thinks of.
    """
    rng = random.Random(20260813)
    image = _seed_image()
    escapes: list[str] = []

    for _ in range(400):
        words = list(image)
        for _ in range(rng.randint(1, 6)):
            words[rng.randrange(len(words))] = rng.choice(
                (*_CORRUPTIONS, rng.getrandbits(16))
            )
        src = SunSpecSource(transport=_ImageTransport(words), discover_now=False)
        try:
            src.discover()
            sample = src.read()
            for tag, quality in sample.quality.items():
                assert quality in ("good", "stale", "bad"), (
                    f"{tag} reported unknown quality {quality!r}"
                )
            soc = src.soc(sample)
            assert 0.0 <= soc <= 1.0, f"soc() returned {soc!r}"
        except ALLOWED_IO:
            continue
        except Exception as exc:  # noqa: BLE001 - the whole point is the type
            escapes.append(f"{type(exc).__name__}: {exc}")

    assert not escapes, "undocumented exceptions escaped the ingest path:\n" + "\n".join(
        dict.fromkeys(escapes)
    )


@pytest.mark.parametrize("ptype", sorted(_TYPES) + ["string8", "not-a-type", ""])
def test_decode_point_returns_a_float_or_nothing_for_any_input(ptype: str) -> None:
    """The innermost decoder. Every value the library reads passes through it.

    Its contract is narrow on purpose: a float or None, for any word count and
    any declared type, including types this build has never heard of. A raise
    here is a raise inside the per-model loop of every connector.
    """
    rng = random.Random(hash(ptype) & 0xFFFF)
    for _ in range(500):
        words = [rng.getrandbits(16) for _ in range(rng.randint(0, 6))]
        value = decode_point(words, ptype)
        assert value is None or isinstance(value, float), (
            f"decode_point({words!r}, {ptype!r}) returned {value!r}"
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT: TwinManifest.to_dict() omits fields that loaded as None, "
        'including required ones. A manifest with "model_kind": null loads, '
        "serialises without that key, and the resulting document can no longer "
        "be read back -- TypeError: missing 1 required positional argument. "
        "Two defects of the same family were fixed at load time (non-mapping "
        "provenance, non-string manifest_version); this one needs type "
        "validation of the required fields in __post_init__ and is left for a "
        "separate change. Remove this marker with the fix."
    ),
)
def test_a_manifest_that_loads_survives_a_round_trip() -> None:
    """SECURITY.md names manifest deserialisation as the threat. Test it.

    A manifest is JSON from wherever a twin was fitted -- possibly another
    organisation, on another version of this library. `from_dict` is permissive
    by design: unknown keys are preserved in `extra` rather than rejected, so
    an older reader can still load a newer file. Permissive parsers are where
    type confusion lives, so anything that loads must also round-trip, or a
    twin written by one process is not the twin another process reads.

    Mutations start from a valid manifest rather than from noise, because a
    document that fails the required-field check never reaches the interesting
    code.
    """
    rng = random.Random(4242)
    base = TwinManifest(
        name="bess",
        model_class="port_hamiltonian",
        model_kind="white-box",
        n_states=2,
        n_inputs=1,
        provenance=Provenance(created="2026-01-01T00:00:00Z", otwin_version="0.2.0"),
    ).to_dict()

    mutations = [
        None,
        {},
        [],
        "x",
        1,
        1.5,
        True,
        {"a": [1, 2]},
        ["soc"],
        [[0.0, 1.0]],
        {"horizon": 500},
        {"empirical_coverage": 0.94},
        "\u0000",
        10**20,
        -1,
    ]
    keys = sorted(base) + ["unknown_future_key", "validation", "calibration"]

    loaded = 0
    for _ in range(600):
        doc = json.loads(json.dumps(base))
        for key in rng.sample(keys, rng.randint(1, 4)):
            doc[key] = rng.choice(mutations)
        try:
            manifest = TwinManifest.from_dict(doc)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        loaded += 1
        once = manifest.to_dict()
        twice = TwinManifest.from_dict(once).to_dict()
        assert twice == once, f"round trip changed the manifest: {doc!r}"

    assert loaded > 20, (
        f"only {loaded} of 600 generated manifests loaded; the generator is "
        f"not reaching the parser"
    )
