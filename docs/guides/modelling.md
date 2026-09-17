# Modelling with components

One page per domain: what each physical element is called, how it connects,
and what the compiler makes of it. Every block runs as written.

The rule that holds everywhere: a connection shares the *across* variable
(voltage, velocity, pressure, temperature) and sums the *through* variables
(current, force, flow, heat) to zero. Components that measure against a
reference have one port; everything else has two, and both must be
connected.

## Electrical

`Resistor`, `Capacitor`, `Inductor` have ports `p` and `n`; current is
positive from `p` to `n` inside the element. `VoltageSource` imposes `v_p − v_n`;
`CurrentSource` delivers current out of `p`. `Ground` is the reference.

```python
import otwin
from otwin.components.electrical import Resistor, Capacitor, Inductor, VoltageSource, Ground

V, R, L, C, g = (VoltageSource(None, name="V"), Resistor(2.0, name="R"),
                 Inductor(0.5, name="L"), Capacitor(1e-3, name="C"), Ground())
s = otwin.System(V, R, L, C, g)
s.connect(V.p, R.p).connect(R.n, L.p).connect(L.n, C.p).connect(C.n, V.n, g.port)

m = otwin.compile(s)
print(m.state_names)
run = m.simulate(t_span=(0, 0.5), dt=1e-4, inputs={"V": 10.0}, solver="rk45")
print(f"capacitor voltage after 0.5 s: {run['C.voltage'][-1]:.3f} V   peak: {run['C.voltage'].max():.3f} V")
```

```text
['L.flux', 'C.charge']
capacitor voltage after 0.5 s: 13.515 V   peak: 18.688 V
```

The states are the flux of the inductor and the charge of the capacitor; the
voltages and currents of every element are outputs (`R.current`, `C.voltage`,
`V.power`, ...). A `Resistor(law=lambda v: ...)` is a nonlinear element such
as a diode, as long as its across variable is pinned by a storage or a source;
see [Compilation](../concepts/compilation.md) for the rule.

## Mechanical, translation and rotation

`Mass` and `Inertia` have one port (`flange`, `shaft`) and measure their
velocity against the inertial frame. `Spring`, `Damper`, `TorsionSpring`,
`RotationalDamper` act between `a` and `b`. `ForceSource` and `TorqueSource`
push on their flange or shaft; `VelocitySource` and `SpeedSource` impose a
motion. `Fixed` and `Housing` are the references.

```{code-block} python
from otwin.components.mechanical import Mass, Spring, Damper, ForceSource, Fixed

mass, spring, damper, wall = Mass(1.0, name="m"), Spring(20.0, name="k"), Damper(0.3, name="c"), Fixed()
weight = ForceSource(9.81, name="weight")          # a constant force: gravity on a 1 kg mass
s = otwin.System(mass, spring, damper, weight, wall)
s.connect(mass.flange, spring.a, damper.a, weight.flange)
s.connect(spring.b, damper.b, wall.port)
```

The spring's state is its extension from the natural length, positive when `a`
moves away from `b`; `Spring(extension=0.1)` starts it stretched. A damper with
`law=lambda v: 0.9 * v * abs(v)` is quadratic drag. Two masses joined directly
are refused as dependent storages; put a stiff `Spring` or a `Damper` between
them, which is also the more truthful model.

## Thermal

`ThermalMass` has one port, `port`. `ThermalResistance` (conduction,
`Q = ΔT / R`) and `Convection` (`Q = hA ΔT`) connect two ports. `HeatSource`
injects heat; `Ambient` holds a temperature. Temperatures are absolute, in
kelvin.

```python
from otwin.components.thermal import ThermalMass, ThermalResistance, HeatSource, Ambient

body = ThermalMass(2000.0, temperature=293.15, name="body")            # 2 kJ/K, starts at 20 degC
wall, amb = ThermalResistance(0.02, name="wall"), Ambient(293.15, name="ambient")
heater = HeatSource(None, name="heater")
s = otwin.System(body, wall, amb, heater)
s.connect(body.port, wall.a, heater.port).connect(wall.b, amb.port)

m = otwin.compile(s)
print(m.representation)
run = m.simulate(t_span=(0, 600), dt=1.0, inputs={"heater": 500.0})
print(f"temperature after 10 min: {run['body.temperature'][-1] - 273.15:.1f} degC "
      f"(steady state {500*0.02:.1f} degC above ambient)")
```

```text
pseudo-port-hamiltonian
temperature after 10 min: 30.0 degC (steady state 10.0 degC above ambient)
```

The representation line is the compiler telling you that temperature times
heat flow is not a power, so the energy audit on this model is a stability
statement rather than a first-law one. The heat balance itself is exact. See
[Compilation](../concepts/compilation.md#thermal-models).

## Hydraulic

`Tank` has one port, `port`, at its base; `base_elevation` lifts it above
the datum. `Orifice` is Torricelli's law, `Pipe` a laminar (`resistance=`) or
turbulent (`friction=`) loss, `Filter` a laminar loss with a `fouling`
parameter, `FluidInertance` the inertia of the water in a pipe. `Pump` is a
centrifugal pump given by its curve, `FlowSource` a fixed flow or a demand,
`PressureSource` a head. `Atmosphere` is the reference. A line of these reads
left to right with `>>`; see [Devices](devices.md).

```python
from otwin.components.hydraulic import Tank, Orifice, Pipe, Atmosphere

upper, lower = Tank(2.0, level=1.5, name="upper"), Tank(3.0, level=0.2, name="lower")
pipe, drain, atm = Pipe(friction=5e5, name="pipe"), Orifice(0.005, name="drain"), Atmosphere()
s = otwin.System(upper, lower, pipe, drain, atm)
s.connect(upper.port, pipe.a).connect(pipe.b, lower.port, drain.a).connect(drain.b, atm.port)

m = otwin.compile(s)
run = m.simulate(t_span=(0, 300), dt=0.5)
print(f"levels after 5 min: upper {run['upper.level'][-1]:.3f} m, lower {run['lower.level'][-1]:.3f} m; "
      f"energy fell from {run.energy[0]:.0f} J to {run.energy[-1]:.0f} J")
```

```text
levels after 5 min: upper 0.206 m, lower 0.206 m; energy fell from 22661 J to 1040 J
```

A tank clamps at empty: a step that overshoots below zero reads a pressure of
zero, so the tank cannot be drained past empty and the energy cannot read back
as an increase.

## Coupling domains

`Transformer` and `Gyrator` are lossless two-ports with ports `p1, n1` on
one side and `p2, n2` on the other, each side in the domain you give it. A
gearbox is a transformer between two rotational sides, a lever between two
mechanical ones, an electric machine a transformer between electrical and
rotational (`ratio = 1 / k`, so back-emf is `k ω` and torque is `k i`), a
hydraulic piston a transformer between hydraulic and mechanical. The
compiler puts them into `J`, never into `R`: they move power, they do not
dissipate it.

`DCMotor` is a composite built exactly that way; read its source as the
template for your own devices.

## Sources: inputs and constants

A source with `None` is an **input**: you supply it at simulation time, per
name. A source with a value is a **constant parameter**: `ForceSource(9.81)` is
a weight, `Ambient(293.15)` an outdoor temperature, `VoltageSource(12.0)` a
battery. Constants are still ports: their power enters the energy balance and
you can change them later with `model.set_parameters({"weight.force": 19.62})`.

## Nonlinear laws

Every dissipative element takes `law=`, a function of its across variable
returning its through variable, written with ordinary arithmetic and the
functions in {mod}`otwin.expr` (`sqrt`, `exp`, `log`, `abs`, `tanh`,
`maximum`, `minimum`, `where`, and `interp` for a measured table). The
compiler traces it into an expression the engine runs, differentiates it for
the Jacobian, and reads its secant into `R`. NumPy functions and Python `if`
do not trace; use `where`.

Some laws are natural the other way round: a pump curve gives the pressure
rise as a function of the flow, turbulent friction is `dp = K Q |Q|`. Such an
element must sit in series with something that sets its flow (an inertance,
an inductor, a spring, a flow source, or another element of its kind); the
compiler then reads the pressure off the flow instead of inverting the law.
`Pipe(friction=)`, `Orifice` and `Pump` carry both forms, so they work either
way. A law of your own goes in as `ResistorBranch(inverse=...)`; see
[Adding components](../developer/components.md).

## Heat from losses

`Losses(r0, r1, ...)` in {mod}`otwin.components.thermal` collects the power
dissipated by the listed components and delivers it as heat flow into its
`port`. Connect that port to the `ThermalMass` that warms up. Nothing about
the power has to be written: the compiler already knows `across * through`
of every resistor, damper and pipe. `Battery(thermal=...)` is built this way.

## What to do when the compiler refuses

The message names the components. The table in
[Compilation](../concepts/compilation.md#what-the-compiler-refuses) lists each
refusal and the fix. The common ones: a loose port on a two-port
component, two storages of the same kind in parallel, a nonlinear element on a
node nothing pins.
