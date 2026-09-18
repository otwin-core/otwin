# Modeling

A model is written from a small vocabulary. This section defines it, then shows it
in each physical domain and in two complete machines.

## The vocabulary

Every element below is a class or a function you will use by name.

**Component.** A physical part: a `Resistor`, a `Mass`, a `Tank`, a `ThermalMass`, a
`Pump`, a `Battery`. You construct it with its parameters, `Spring(20.0)` or
`Battery(capacity=100.0, ocv=[...])`, and it gives them back by name as
`spring.stiffness`. Six things belong to every component.

```text
Component
├── Domain        which pair of physical variables its ports carry
├── Ports         where it can be joined to something else
├── Parameters    the numbers it was built with, each with a unit and a rule
├── States        what it stores, if it stores anything
├── Relations     what it imposes between the quantities at its ports
└── Outputs       what the compiled model will publish under its name
```

**Port.** A point on a component where one pair of physical variables is exposed:
an *across* variable that is shared where ports meet, and a *through* variable that
sums to zero there. Two-port components have ports named `p` and `n`, `a` and `b`,
or `inlet` and `outlet`. One-port components such as a mass, a tank or the
atmosphere measure against their domain's reference and have a single `port`,
`flange` or `shaft`.

**Connection.** Ports joined into a node. One rule holds in every domain: the across
variable is shared by every port at the node, and the through variables of the
branches meeting there sum to zero. Ports of different domains cannot be joined. Two
verbs write every connection, `>>` and `connect`; see
[Connections](connections.md).

**Parameter.** A number a component was built with, such as a resistance, a mass or
a tank area. Parameters stay symbolic through compilation, so the compiled model
names them `spring.stiffness`, `filter.fouling`, `cell.r0.resistance`, changes any
of them without recompiling, and can fit them to measurements.

**Input.** A source whose value is `None`, such as `VoltageSource(None)` or
`FlowSource(None)`. It becomes an input of the compiled model, supplied at run time.
A source with a number is a constant parameter instead, and it is still a port: its
power enters the energy balance.

**State.** What a storage integrates. The compiler chooses the states; you do not.
Charge in a capacitor, momentum of a mass, volume in a tank, stored heat in a
thermal mass. Initial conditions are given in the quantity you think in,
`Mass(velocity=...)` or `Tank(level=...)`, and the component converts them.

**Composite.** A device built from primitives: `DCMotor`, `Pump`, `Battery`. Inside
one there is nothing an engineer would not draw on a whiteboard. Its parts are
ordinary components named `<device>.<part>`, so `cell.r0.power` and
`pump.water.flow_momentum` are outputs like any other. Writing your own is the
recommended way to add a device; see [Adding
components](../developer/components.md).

**System.** The collection of components and connections. `>>` returns one,
`System(...)` builds one explicitly. `system.summary()` lists what it contains and
`system.unconnected()` names any port left dangling.

## The catalogue

Components are grouped by domain, not by class hierarchy. What a component can be
joined to is decided by its domain, so that is the first thing to know about it.

```text
Electrical      Resistor · Capacitor · Inductor · VoltageSource · CurrentSource · Ground
Mechanical      Mass · Spring · Damper · ForceSource · VelocitySource · Fixed
Rotational      Inertia · TorsionSpring · RotationalDamper · TorqueSource · SpeedSource · Housing
Hydraulic       Tank · Pipe · Orifice · Filter · FluidInertance · Pump · FlowSource · PressureSource · Atmosphere
Thermal         ThermalMass · ThermalResistance · Convection · HeatSource · Losses · Ambient
Two-ports       Transformer · Gyrator
Composites      DCMotor · Battery · Pump
```

[Domains](domains.md) shows each of them in use. The [Component
reference](../reference/components.md) is the complete inventory, generated from the
code, with every port, parameter, unit, state and output.

## The pages in this section

| I want to | Page |
|---|---|
| know what a component declares and why | [Components](components.md) |
| join components correctly, including three at a point | [Connections](connections.md) |
| find the right element for a physical part, per domain | [Domains](domains.md) |
| build a battery module or a pump line from a data sheet | [Devices](devices.md) |
| run the compiled model, with inputs, control laws or batches | [Simulation](simulate.md) |

```{toctree}
:hidden:
:maxdepth: 1

components
connections
domains
devices
simulate
```
