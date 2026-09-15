"""The reference systems of :mod:`otwin.model.library`, built from components.

Each function returns a :class:`~otwin.system.System` whose compiled dynamics
reproduce the hand-written port-Hamiltonian model of the same name, and a
regression test in ``tests/engine`` holds the two together. Use them as
starting points and as worked examples of composition.
"""

from __future__ import annotations

from ..system import System
from .composite import DCMotor
from .electrical import Ground, VoltageSource
from .hydraulic import Atmosphere, FlowSource, Orifice, Pipe, Tank
from .mechanical import Damper, Fixed, ForceSource, Mass, Spring

__all__ = [
    "mass_spring_damper",
    "water_tank",
    "dc_motor",
    "pumped_hydro",
]


def mass_spring_damper(
    m: float = 1.0,
    k: float = 1.0,
    c: float = 0.1,
    *,
    position: float = 0.0,
    velocity: float = 0.0,
) -> System:
    """A mass on a spring with a damper and an external force input ``force``.

    States ``spring.extension`` and ``mass.momentum`` match ``x = [q, p]`` of
    :func:`otwin.model.mass_spring_damper`.
    """
    mass = Mass(m, velocity=velocity, name="mass")
    spring = Spring(k, extension=position, name="spring")
    damper = Damper(c, name="damper")
    force = ForceSource(None, name="force")
    wall = Fixed(name="wall")
    s = System(spring, mass, damper, force, wall, name="mass_spring_damper")
    s.connect(mass.flange, spring.a, damper.a, force.flange)
    s.connect(spring.b, damper.b, wall.terminal)
    return s


def water_tank(
    A: float = 1.0,
    a: float = 0.1,
    g: float = 9.81,
    c_d: float = 0.6,
    rho: float = 1000.0,
    *,
    level: float = 1.0,
) -> System:
    """A tank draining through an orifice, filled by an inlet flow input ``inlet``.

    State ``tank.volume`` is ``A h`` for the ``x = [h]`` of
    :func:`otwin.model.water_tank`; the output ``tank.level`` is ``h``.
    """
    tank = Tank(A, level=level, density=rho, gravity=g, name="tank")
    drain = Orifice(a, discharge_coefficient=c_d, density=rho, name="drain")
    inlet = FlowSource(None, name="inlet")
    atm = Atmosphere(name="atmosphere")
    s = System(tank, drain, inlet, atm, name="water_tank")
    s.connect(tank.port, drain.a, inlet.a)
    s.connect(drain.b, inlet.b, atm.terminal)
    return s


def dc_motor(
    L: float = 0.5,
    inertia: float = 0.01,
    Re: float = 1.0,
    b: float = 0.1,
    K: float = 0.5,
) -> System:
    """A DC motor driven by a voltage input ``supply``.

    States ``motor.armature.flux`` and ``motor.rotor.angular_momentum`` match
    ``x = [phi, p]`` of :func:`otwin.model.dc_motor`.
    """
    motor = DCMotor(Re, L, K, inertia, b, name="motor")
    supply = VoltageSource(None, name="supply")
    gnd = Ground(name="ground")
    s = System(motor, supply, gnd, name="dc_motor")
    s.connect(supply.p, motor.p)
    s.connect(motor.n, supply.n, gnd.terminal)
    return s


def pumped_hydro(
    A_u: float = 5.0e4,
    A_l: float = 5.0e6,
    z_u: float = 300.0,
    R_penstock: float = 5.0e8,
    g: float = 9.81,
    rho: float = 1000.0,
    *,
    V_u: float = 1.0e6,
    V_l: float = 1.0e7,
) -> System:
    """Two reservoirs joined by a leaky penstock and a pump-turbine flow input
    ``pump`` (positive pumps water up).

    States ``upper.volume`` and ``lower.volume`` match ``x = [V_u, V_l]`` of
    :func:`otwin.model.pumped_hydro`.
    """
    upper = Tank(
        A_u, level=V_u / A_u, base_elevation=z_u, density=rho, gravity=g, name="upper"
    )
    lower = Tank(A_l, level=V_l / A_l, density=rho, gravity=g, name="lower")
    penstock = Pipe(R_penstock, name="penstock")
    pump = FlowSource(None, name="pump")
    s = System(upper, lower, penstock, pump, name="pumped_hydro")
    s.connect(upper.port, penstock.a, pump.a)
    s.connect(lower.port, penstock.b, pump.b)
    return s
