# Components, ports and systems

What you describe. Nothing on this page involves an equation.

## One rule for five domains

Every physical domain otwin models has two variables that multiply to a power
(or, for heat, to something that behaves like one):

| domain | across (shared at a node) | through (sums to zero at a node) |
|---|---|---|
| electrical | voltage [V] | current [A] |
| mechanical | velocity [m/s] | force [N] |
| rotational | angular velocity [rad/s] | torque [N m] |
| hydraulic | pressure [Pa] | volumetric flow [m³/s] |
| thermal | temperature [K] | heat flow [W] |

A **port** is a point on a component where one pair of these variables is
exposed. A **connection** joins ports into a **node**. At a node the across
variable is shared by every port and the through variables of the branches
meeting there sum to zero. That one rule is Kirchhoff's two laws, Newton's
third law, conservation of mass at a pipe junction and conservation of heat at
a wall. It is what lets one compiler serve all five domains, and it is why a
connection between ports of different domains is refused at `connect`.

## What a component declares

A component is a class with ports, parameters and one or more
**branches**, each a constitutive relation between two ports (or one
port and the reference):

| branch | relation | examples |
|---|---|---|
| across storage | state is the integral of the through variable; across = dH/dx | `Capacitor`, `Mass`, `Inertia`, `Tank`, `ThermalMass` |
| through storage | state is the integral of the across variable; through = dH/dx | `Inductor`, `Spring`, `TorsionSpring`, `FluidInertance` |
| resistor | through = law(across) | `Resistor`, `Damper`, `Orifice`, `Pipe`, `ThermalResistance`, `Convection` |
| across source | across imposed | `VoltageSource`, `VelocitySource`, `PressureSource`, `Ambient` |
| through source | through imposed | `CurrentSource`, `ForceSource`, `TorqueSource`, `FlowSource`, `HeatSource` |
| two-port | across₂ = n·across₁ and through₁ = −n·through₂ (transformer), or the crossed pair (gyrator) | `Transformer`, `Gyrator` |

A storage brings an **energy function** of its state: $q^2/2C$ for a
capacitor, $p^2/2m$ for a mass, $\rho g (z V + V^2/2A)$ for a tank. A resistor
brings a **law**, linear by default and anything traceable on request. A source
with `None` for its value becomes an **input** of the compiled model; a source
with a number becomes a constant parameter you can still change afterwards.

The one-port components (`Mass`, `Inertia`, `Tank`, `ThermalMass`,
`ForceSource`, `HeatSource`, `Ambient`) measure their across variable against
the reference, so they have nothing to connect on the other side. Two-port
components must have both ports connected; the compiler names the dangling
one otherwise. The reference itself is `Ground`, or its domain-flavoured
aliases `Fixed`, `Housing`, `Atmosphere`.

## Parameters

Every parameter is declared with a value, a unit and a validity rule (a mass
must be positive, a damping must not be negative), checked at construction.
Parameters stay **symbolic** through compilation: the compiled model carries
`mass.mass`, `spring.stiffness`, `damper.damping` by name, `set_parameters`
changes a value without recompiling, and {func}`otwin.fit_parameters` can
estimate any of them from data.

## Initial conditions

Storages take their initial condition in the quantity you think in:
`Mass(velocity=...)`, `Capacitor(voltage=...)`, `Tank(level=...)`,
`ThermalMass(temperature=...)`. The component converts it to its state
(momentum, charge, volume, stored heat). `model.initial_state()` shows the
result, and `simulate(x0=...)` overrides it by name.

## Composites

A high-level device is a component built from primitives.
{class}`~otwin.components.composite.DCMotor` is a `Resistor`, an `Inductor`, a
`Transformer` from the electrical to the rotational domain, an `Inertia` and a
`RotationalDamper`, wired internally and exposing `p`, `n` and `shaft`.
{class}`~otwin.components.battery.Battery` and
{class}`~otwin.components.hydraulic.Pump` are built the same way. The
compiler flattens composites before it does anything else, so nothing inside
one is special-cased and its states appear as `motor.armature.flux`,
`bat.ocv.charge`, `pump.water.flow_momentum`. Writing your own is the
recommended way to add a heat exchanger or a converter; see
[Adding components](../developer/components.md).

## Systems

{class}`otwin.System` holds components and connections. It checks domains and
names, and does nothing else. `a >> b >> c` chains two-port components in
series when that is the natural picture; `system.connect(...)` joins any number
of ports into one node. A single component can be compiled on its own
(`otwin.compile(Mass(2.0))`) when that is the whole system.
