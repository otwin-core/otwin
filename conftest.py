"""Test configuration.

NumPy 2 changed the repr of scalars from ``1.0`` to ``np.float64(1.0)``. Every
doctest in this package was written against the older repr, and rewriting a
hundred of them to say ``float(...)`` would make the documentation worse to
read in order to make the test runner happy. ``legacy="1.25"`` is NumPy's own
supported switch for exactly this, so the docs stay readable and the doctests
stay executable.

This affects printing only. No computation changes.
"""

import numpy as np


def pytest_configure(config):
    np.set_printoptions(legacy="1.25")
