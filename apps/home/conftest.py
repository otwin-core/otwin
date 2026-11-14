"""Test setup for Otwin Home.

Puts ``apps/home`` on the import path so tests and doctests import
``ingest`` and ``components``, and runs every component test on each
available backend, as tests/engine does.
"""

import sys
from pathlib import Path

import pytest
from otwin.runtime import engine_available

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

BACKENDS = ["numpy"] + (["rust"] if engine_available() else [])


@pytest.fixture(params=BACKENDS)
def backend(request):
    """The backend name: ``"numpy"``, and ``"rust"`` when the engine is installed."""
    return request.param
