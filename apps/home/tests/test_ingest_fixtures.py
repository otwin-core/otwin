"""Every parser round-trips its synthetic fixture.

Each fixture in ``fixtures/data`` is generated from a known truth by
``fixtures/make_fixtures.py``. Three things are checked for each one:
regenerating it gives the committed bytes, so nobody edits a fixture by
hand; format detection recognises it; and parsing it returns exactly the
truth, with the same intervals, the same values to file precision and the
same real/estimated flags. Nothing touches the network.
"""

from __future__ import annotations

import numpy as np
import pytest

import ingest
from fixtures.make_fixtures import DATA, Fixture, build

FIXTURES = build()
IDS = [fx.name for fx in FIXTURES]


def _key(s: ingest.Series):
    return (s.quantity, s.channel, int(s.start[0]) if len(s) else 0, len(s))


def assert_same_series(got: list[ingest.Series], expected: list[ingest.Series]) -> None:
    """Same quantities, channels, kinds, intervals, values and quality, in any order."""
    got, expected = sorted(got, key=_key), sorted(expected, key=_key)
    assert [_key(s) for s in got] == [_key(s) for s in expected]
    for g, e in zip(got, expected, strict=True):
        assert (g.quantity, g.channel, g.kind) == (e.quantity, e.channel, e.kind)
        np.testing.assert_array_equal(g.start, e.start, err_msg=repr(g))
        np.testing.assert_array_equal(g.end, e.end, err_msg=repr(g))
        np.testing.assert_allclose(
            g.value, e.value, rtol=1e-9, atol=1e-6, err_msg=repr(g)
        )
        np.testing.assert_array_equal(g.quality, e.quality, err_msg=repr(g))


def _parse(fx: Fixture, data: bytes) -> list[ingest.Series]:
    if fx.format == "generic":
        return ingest.parse_mapped(data, fx.options["cmap"], source=fx.name)
    return ingest.load(data, source=fx.name, **fx.options)


@pytest.mark.parametrize("fx", FIXTURES, ids=IDS)
def test_committed_fixture_is_reproducible(fx: Fixture) -> None:
    path = DATA / fx.name
    assert path.exists(), f"run make_fixtures.py to create {fx.name}"
    assert path.read_bytes() == fx.data, (
        f"{fx.name} differs from what the generator writes"
    )


@pytest.mark.parametrize("fx", FIXTURES, ids=IDS)
def test_format_is_detected(fx: Fixture) -> None:
    data = (DATA / fx.name).read_bytes()
    if fx.format == "generic":
        with pytest.raises(ingest.IngestError, match="ColumnMap") as err:
            ingest.detect_format(data)
        assert "Lectura (L)" in str(err.value)  # the columns are listed
    else:
        assert ingest.detect_format(data) == fx.format


@pytest.mark.parametrize("fx", FIXTURES, ids=IDS)
def test_parser_round_trips_its_fixture(fx: Fixture) -> None:
    got = _parse(fx, (DATA / fx.name).read_bytes())
    assert_same_series(got, fx.truth)
    for s in got:
        assert s.source.startswith(fx.name)


@pytest.mark.parametrize(
    "fx", [f for f in FIXTURES if f.format == "distributor_csv"], ids=lambda f: f.name
)
def test_hourly_electricity_covers_both_dst_days(fx: Fixture) -> None:
    """Independent anchors, not derived from the parser's own time code."""
    [imp] = [s for s in _parse(fx, fx.data) if s.quantity == "electricity_import"]
    assert len(imp) == 24 + 23 + 24 + 24 + 25 + 24
    # 29 March 2025 starts at 23:00 UTC on the 28th (CET, UTC+1).
    assert imp.start[0] == 1743202800
    # 30 March has 23 hours: 31 March starts 23 hours after 30 March.
    day = np.diff(imp.start[[24, 24 + 23]])
    assert day.tolist() == [23 * 3600]
    # 26 October starts at 22:00 UTC on the 25th (CEST) and has 25 hours.
    assert imp.start[71 + 24] == 1761429600
    assert imp.start[71 + 24 + 25] - imp.start[71 + 24] == 25 * 3600
    # Intervals are contiguous within each window.
    assert set(np.diff(imp.start[:71]).tolist()) == {3600}
