"""Otwin: digital twins whose physics is checked, not claimed.

A twin built here is an energy-based model -- a bond graph in state-space form.
Power is routed by ``J``, dissipated by ``R``, stored by ``H``, and crosses the
boundary through ``g``. With the terminals open, stored energy cannot increase:
not approximately, not for well-chosen parameters, not only inside the range you
fitted. It is an algebraic property, so it holds at any step size and any
horizon.

That is a falsifiable claim, so something checks it. ``otwin-spec`` is a type
test procedure -- reference cases with closed-form answers, and deliberately
broken implementations proving each check catches the fault it was written for.

The package follows the ISO 13374 processing blocks, so the module layout is
the one a condition-monitoring engineer already has in their head:

    otwin.io          DA   Data Acquisition       SunSpec Modbus, Modbus TCP/RTU
    otwin.signal      DM   Data Manipulation      resampling, gaps, units
    otwin.estimate    SD   State Detection        EKF, MHE, energy-consistent observer
    otwin.model       HA   Health Assessment      the energy-based model itself
    otwin.forecast    PA   Prognostic Assessment  forecasts, skill, calibrated bands
    otwin.advise      AG   Advisory Generation    the validity envelope, and refusal

Ten seconds:

    >>> import numpy as np
    >>> from otwin.model import PortHamiltonianSystem, integrate_phs
    >>>
    >>> # A damped oscillator: a spring, a mass, and a damper.
    >>> osc = PortHamiltonianSystem(
    ...     H      = lambda x: 0.5 * 2.0 * x[0]**2 + 0.5 * x[1]**2,
    ...     grad_H = lambda x: np.array([2.0 * x[0], x[1]]),
    ...     J      = lambda x: np.array([[0.0, 1.0], [-1.0, 0.0]]),
    ...     R      = lambda x: np.array([[0.0, 0.0], [0.0, 0.3]]),
    ...     g      = lambda x: np.array([[0.0], [1.0]]),
    ...     n_states=2, n_inputs=1,
    ... )
    >>> t = np.linspace(0, 20, 400)
    >>> sol = integrate_phs(osc, np.array([1.0, 0.0]), t, np.zeros((400, 1)))
    >>> E = np.array([osc.energy(x) for x in sol["x"]])
    >>> bool(np.all(np.diff(E) <= 1e-9))   # holds at every step, by construction
    True
"""

__version__ = "0.3.0"

from otwin.interfaces import (
    MANIFEST_VERSION,
    Array,
    Baseline,
    EmpiricalLawModel,
    Estimator,
    EvaluationProtocol,
    Forecast,
    HasEnergyGradient,
    Integrator,
    Interval,
    IrreversibleModel,
    MetricSet,
    PortHamiltonianModel,
    Provenance,
    Report,
    Splitter,
    TwinManifest,
    TwinModel,
    UncertaintyModel,
)

__all__ = [
    "__version__",
    # The interface specification. Everything else is an implementation of it.
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
    "Array",
]
