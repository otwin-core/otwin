"""Otwin: digital twins with a compiled physics engine.

Describe a physical system with components and connections. Otwin compiles
the description into a physically consistent model and runs it in its
engine. Simulation, state estimation, forecasting and validation all use
that one compiled model.

Ten seconds:

    >>> import otwin
    >>> from otwin.components.mechanical import Mass, Spring, Damper, Fixed
    >>> mass, spring, damper, wall = Mass(1.0), Spring(20.0, extension=0.5), Damper(0.3), Fixed()
    >>> system = otwin.System(mass, spring, damper, wall)
    >>> system.connect(mass.flange, spring.a, damper.a)      # doctest: +ELLIPSIS
    System(...)
    >>> system.connect(spring.b, damper.b, wall.terminal)    # doctest: +ELLIPSIS
    System(...)
    >>> model = otwin.compile(system)
    >>> trajectory = model.simulate(t_span=(0.0, 20.0), dt=0.05)
    >>> trajectory["energy"][-1] < trajectory["energy"][0]    # the damper did its work
    True
    >>> trajectory.energy_balance()["max_violation"] <= 1e-12  # and no step created energy
    True

The user wrote no equation. The compiler derived the port-Hamiltonian form
``dx/dt = (J - R) grad_H + G u`` from the components and the engine integrated
it with a structure-preserving method.

The layers:

    otwin.components   the physical primitives, one module per domain
    otwin.System       the component graph
    otwin.compile      the model compiler: graph -> IR -> executable model
    otwin.Model        the compiled model: simulate, step, energy, outputs
    otwin.estimate     correct the state from measurements (EKF, MHE, energy observer)
    otwin.forecast     predict and score it, leakage-free, with calibrated bands
    otwin.advise       the validated envelope: an answer, or a refusal with a reason
    otwin.io, otwin.signal   field data acquisition and conditioning
    otwin.model        the advanced API: PortHamiltonianSystem and friends, written by hand

The Rust engine (``pip install otwin[engine]``) runs the numerical loop; without
it the same models run on a NumPy reference backend.
"""

__version__ = "1.0.0"

from otwin import components, expr, hybrid
from otwin.api import compile
from otwin.compiler import CompileError, StructureWarning
from otwin.hybrid import HybridModel, fit_parameters
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
from otwin.runtime import (
    CustomDynamics,
    EngineNotAvailable,
    Model,
    State,
    Trajectory,
    engine_available,
)
from otwin.system import System, chain

__all__ = [
    "__version__",
    "System",
    "chain",
    "compile",
    "Model",
    "State",
    "Trajectory",
    "CustomDynamics",
    "CompileError",
    "StructureWarning",
    "EngineNotAvailable",
    "engine_available",
    "components",
    "expr",
    "hybrid",
    "HybridModel",
    "fit_parameters",
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
