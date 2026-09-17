"""The top-level verbs: ``compile``."""

from __future__ import annotations

from collections.abc import Sequence

from .compiler import compile_system
from .components.base import Component
from .runtime.model import Model
from .system import System

__all__ = ["compile"]


def compile(  # noqa: A001 - the public verb is deliberately named compile
    system: System | Component | Sequence[Component],
    *,
    backend: str = "auto",
    name: str | None = None,
    measurements: Sequence[str] | None = None,
    jacobian: bool = True,
    check: bool = True,
    dt: float | None = None,
) -> Model:
    """Compile a physical system into an executable :class:`~otwin.runtime.Model`.

    Args:
        system: a :class:`~otwin.system.System`, or a single component (a
            lone mass, a lone tank) to compile on its own.
        backend: ``"auto"`` (the Rust engine if installed), ``"rust"`` or ``"numpy"``.
        name: a name for the model; defaults to the system's.
        measurements: output names that :meth:`Model.observe` should return.
        jacobian: derive the analytic Jacobian (used by the implicit solver).
        check: evaluate the structural checks at the initial state and warn.
        dt: default time step for :meth:`Model.step`; :meth:`Model.simulate`
            takes its own grid and ignores it.

    Raises:
        CompileError: with a physical explanation of what cannot be compiled.
    """
    if isinstance(system, Component):
        system = System(system, name=name or system.name)
    elif not isinstance(system, System):
        system = System(*system, name=name or "system")
    ir = compile_system(system, name=name, jacobian=jacobian, check=check)
    return Model(ir, backend=backend, measurements=measurements, dt=dt)
