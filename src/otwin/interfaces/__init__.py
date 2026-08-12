"""The Otwin interface specification: types and protocols only.

No algorithms. Nothing here integrates, estimates, calibrates or scores
anything -- ``tests/test_interfaces_has_no_algorithms.py`` fails the build if
that ever stops being true.

These are the shapes a component has to have to take part. They are
*structural*: write a plain class with the right methods and it conforms. Do
not inherit from them, and do not import Otwin to satisfy one.

Real conformance is the type test in ``otwin-spec``. ``isinstance`` checks
method names; the type test checks physics.
"""

from .manifest import MANIFEST_VERSION, TIMESTAMP_FORMAT, Provenance, TwinManifest
from .protocols import (
    Array,
    Baseline,
    EmpiricalLawModel,
    Estimator,
    EvaluationProtocol,
    HasEnergyGradient,
    IndexArray,
    Integrator,
    IrreversibleModel,
    PortHamiltonianModel,
    Splitter,
    TwinModel,
    UncertaintyModel,
)
from .results import Forecast, Interval, MetricSet, Report

__all__ = [
    "TwinModel",
    "PortHamiltonianModel",
    "HasEnergyGradient",
    "IrreversibleModel",
    "EmpiricalLawModel",
    "Integrator",
    "Estimator",
    "UncertaintyModel",
    "Baseline",
    "Splitter",
    "EvaluationProtocol",
    "Forecast",
    "Interval",
    "MetricSet",
    "Report",
    "TwinManifest",
    "Provenance",
    "MANIFEST_VERSION",
    "TIMESTAMP_FORMAT",
    "Array",
    "IndexArray",
]
