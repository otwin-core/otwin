"""The two 2.0 example scripts run end to end and their hand checks hold.

The scripts assert their own numbers against one-line hand calculations; this
test only has to run them.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize(
    "script", ["battery_that_runs_hot.py", "pump_station_that_asks_for_more.py"]
)
def test_example_script_runs(script: str, capsys) -> None:
    runpy.run_path(str(EXAMPLES / script), run_name="__main__")
    out = capsys.readouterr().out
    assert "by hand" in out
