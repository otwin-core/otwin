"""Health Assessment (ISO 13374 block HA): what the asset is, in equations.

An energy-based model -- a bond graph written in state-space form:

    dx/dt = (J(x) - R(x)) grad_H(x) + g(x) u
        y = g(x)^T grad_H(x)

``J`` routes power between stores without consuming any (the junction
structure: gyrators, transformers). ``R`` removes power and can never add it
(the resistive elements: friction, damping, ohmic loss). ``H`` is the energy
stored (the C and I elements: springs, inertias, tank levels, state of charge).
``g`` is where power crosses the system boundary -- the terminals.

The consequence, with the terminals open: **stored energy cannot increase.**
Not approximately, not for well-chosen parameters, not only inside the range
you fitted. That is an algebraic property of ``J`` and ``R``, so it holds at
any step size and any horizon, and ``otwin-spec`` checks it rather than taking
our word for it.

Two models compose into one model, and the energy balance survives the
composition. That is what lets a bank model be built out of string models
without refitting anything.
"""

from .integrators import implicit_midpoint, integrate_phs, newton_step
from .iphs import IrreversiblePHS
from .library import dc_motor, mass_spring_damper, pumped_hydro, water_tank
from .linalg import check_psd, check_skew_symmetric, numerical_gradient
from .phs import PortHamiltonianSystem
from .solvers import integrate, integrate_with_inputs

__all__ = [
    "PortHamiltonianSystem",
    "IrreversiblePHS",
    "water_tank",
    "mass_spring_damper",
    "dc_motor",
    "pumped_hydro",
    "implicit_midpoint",
    "integrate_phs",
    "newton_step",
    "integrate",
    "integrate_with_inputs",
    "check_skew_symmetric",
    "check_psd",
    "numerical_gradient",
    # Torch-backed, imported lazily by __getattr__ below.
    "PortHamiltonianNN",
    "derivative_loss",
    "passivity_penalty",
]

from otwin import __version__ as __version__  # noqa: E402  (deliberate re-export)

_LAZY = {
    "PortHamiltonianNN": ("phnn", "nn"),
    "derivative_loss": ("losses", "nn"),
    "passivity_penalty": ("losses", "nn"),
}


def __getattr__(name):
    """Import torch-backed objects only when they are actually asked for.

    `import otwin.model` must stay cheap and must not require PyTorch. Asking
    for a learned model without torch installed should say what to install,
    not produce a traceback from three frames down.
    """
    try:
        module_name, extra = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib

    try:
        module = importlib.import_module(f".{module_name}", __name__)
    except ImportError as exc:
        raise ImportError(
            f"otwin.model.{name} needs PyTorch, which is not installed.\n"
            f"    pip install 'otwin[{extra}]'"
        ) from exc
    return getattr(module, name)


def __dir__():
    return sorted(__all__)
