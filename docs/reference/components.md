# Component reference

Every component in the library, generated from the code by
`docs/generate_components.py`, so what you read here is what the
compiler sees. For each one: how to construct it, what it means,
its ports, the parameters the compiled model exposes by name (every
one changeable with `with_parameters` or fitted with
`fit_parameters`), the states it creates, the input it becomes when
its value is `None`, and the outputs `model.outputs(state)` returns.

The example instance is named after the class in lower case
(`resistor`, `tank`), so a parameter listed as `tank.area` is
`<your name>.area` in your model. Parameter values in the tables are
the example's, not recommendations.

The one rule behind every table: at a node, the across variable
(voltage, velocity, pressure, temperature) is shared and the through
variables (current, force, flow, heat flow) sum to zero. A component
is a set of relations between those two on its ports; the compiler
does the rest. [Components, ports and systems](../concepts/components.md)
explains the vocabulary; [Modelling](../guides/modelling.md) shows the
components in use.

## Index

- **Electrical**: [`Resistor`](#resistor), [`Capacitor`](#capacitor), [`Inductor`](#inductor), [`VoltageSource`](#voltagesource), [`CurrentSource`](#currentsource), [`Ground`](#ground)
- **Mechanical (translation)**: [`Mass`](#mass), [`Spring`](#spring), [`Damper`](#damper), [`ForceSource`](#forcesource), [`VelocitySource`](#velocitysource), [`Fixed`](#fixed)
- **Rotational**: [`Inertia`](#inertia), [`TorsionSpring`](#torsionspring), [`RotationalDamper`](#rotationaldamper), [`TorqueSource`](#torquesource), [`SpeedSource`](#speedsource), [`Housing`](#housing)
- **Hydraulic**: [`Tank`](#tank), [`Orifice`](#orifice), [`Pipe`](#pipe), [`FluidInertance`](#fluidinertance), [`FlowSource`](#flowsource), [`PressureSource`](#pressuresource), [`Filter`](#filter), [`Pump`](#pump), [`Atmosphere`](#atmosphere)
- **Thermal**: [`ThermalMass`](#thermalmass), [`ThermalResistance`](#thermalresistance), [`Convection`](#convection), [`HeatSource`](#heatsource), [`Losses`](#losses), [`Ambient`](#ambient)
- **Two-ports**: [`Transformer`](#transformer), [`Gyrator`](#gyrator)
- **Composites**: [`DCMotor`](#dcmotor), [`Battery`](#battery)
- **Fundamental (any domain)**: [`Storage`](#storage), [`Dissipator`](#dissipator), [`Source`](#source), [`Reference`](#reference), [`Transformer`](#transformer-any-domain), [`Gyrator`](#gyrator-any-domain)

## Electrical

Voltage across, current through. Ports `p` and `n`.

### Resistor

`otwin.components.electrical.Resistor(resistance=1.0, law=None, name=None)`

Ohm's law, ``v = R i``. Dissipates ``i^2 R``.

Pass ``law`` for a nonlinear element: a function of the voltage returning
the current, e.g. ``law=lambda v: 1e-9 * (exp(v / 0.026) - 1)`` for a diode.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `resistor.resistance` | ohm | 1 | > 0 | v = R i |

**Outputs**

| output | unit |
|---|---|
| `resistor.voltage` | V |
| `resistor.current` | A |
| `resistor.power` | W |

### Capacitor

`otwin.components.electrical.Capacitor(capacitance=1.0, voltage=0.0, name=None)`

Stores charge: ``H = q^2 / (2 C)``, ``v = q / C``.

**Kind:** across storage.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `capacitor.capacitance` | F | 1 | > 0 | q = C v |

**States**

| state | unit | initial |
|---|---|---|
| `capacitor.charge` | C | 0 |

**Outputs**

| output | unit |
|---|---|
| `capacitor.charge` | C |
| `capacitor.energy` | J |
| `capacitor.voltage` | V |
| `capacitor.current` | A |
| `capacitor.power` | W |

### Inductor

`otwin.components.electrical.Inductor(inductance=1.0, current=0.0, name=None)`

Stores flux: ``H = phi^2 / (2 L)``, ``i = phi / L``.

**Kind:** through storage.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `inductor.inductance` | H | 1 | > 0 | flux = L i |

**States**

| state | unit | initial |
|---|---|---|
| `inductor.flux` | Wb | 0 |

**Outputs**

| output | unit |
|---|---|
| `inductor.flux` | Wb |
| `inductor.energy` | J |
| `inductor.voltage` | V |
| `inductor.current` | A |
| `inductor.power` | W |

### VoltageSource

`otwin.components.electrical.VoltageSource(voltage=None, name=None)`

Imposes ``v_p - v_n``. With ``voltage=None`` it is an input of the model.

**Kind:** across source (input). In a `>>` chain it is entered at `n` and left at `p`.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `voltagesource` | V |

**Outputs**

| output | unit |
|---|---|
| `voltagesource.voltage` | V |
| `voltagesource.current` | A |
| `voltagesource.power` | W |

### CurrentSource

`otwin.components.electrical.CurrentSource(current=None, name=None)`

Delivers a current out of ``p``. With ``current=None`` it is an input.

**Kind:** through source (input). In a `>>` chain it is entered at `n` and left at `p`.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `currentsource` | A |

**Outputs**

| output | unit |
|---|---|
| `currentsource.voltage` | V |
| `currentsource.current` | A |
| `currentsource.power` | W |

### Ground

`otwin.components.electrical.Ground(name=None)`

The reference: across variable zero. Electrical ground, a fixed frame,
atmospheric pressure, the temperature datum.

One port, any domain. Connect anything to it that is nailed down.

**Kind:** reference (the zero of its domain).

**Ports**

| port | domain |
|---|---|
| `port` | any |

## Mechanical (translation)

Velocity across, force through. Ports `a`, `b` or a single `flange`.

### Mass

`otwin.components.mechanical.Mass(mass=1.0, velocity=0.0, name=None)`

A rigid mass: ``H = p^2 / (2 m)``, velocity ``v = p / m``.

Extra outputs: ``velocity`` (the across variable) and ``kinetic_energy``.

**Kind:** across storage.

**Ports**

| port | domain |
|---|---|
| `flange` | mechanical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `mass.mass` | kg | 1 | > 0 | p = m v |

**States**

| state | unit | initial |
|---|---|---|
| `mass.momentum` | kg m/s | 0 |

**Outputs**

| output | unit |
|---|---|
| `mass.momentum` | kg m/s |
| `mass.energy` | J |
| `mass.velocity` | m/s |
| `mass.force` | N |
| `mass.power` | W |

### Spring

`otwin.components.mechanical.Spring(stiffness=1.0, extension=0.0, name=None)`

A linear spring: ``H = k x^2 / 2``, force ``F = k x``.

The state is the extension ``x`` from the natural length, positive when
``a`` moves away from ``b``. ``extension`` sets the initial value.

**Kind:** through storage.

**Ports**

| port | domain |
|---|---|
| `a` | mechanical |
| `b` | mechanical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `spring.stiffness` | N/m | 1 | > 0 | F = k x |

**States**

| state | unit | initial |
|---|---|---|
| `spring.extension` | m | 0 |

**Outputs**

| output | unit |
|---|---|
| `spring.extension` | m |
| `spring.energy` | J |
| `spring.velocity` | m/s |
| `spring.force` | N |
| `spring.power` | W |

### Damper

`otwin.components.mechanical.Damper(damping=1.0, law=None, name=None)`

Viscous damping, ``F = c v``.

Pass ``law`` for a nonlinear damper: a function of the relative velocity
returning the force, e.g. ``law=lambda v: 0.9 * v * abs(v)`` for quadratic drag.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `a` | mechanical |
| `b` | mechanical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `damper.damping` | N s/m | 1 | ≥ 0 | F = c v |

**Outputs**

| output | unit |
|---|---|
| `damper.velocity` | m/s |
| `damper.force` | N |
| `damper.power` | W |

### ForceSource

`otwin.components.mechanical.ForceSource(force=None, name=None)`

An external force on ``flange``, positive in the positive direction.

``force=None`` makes it an input of the compiled model. A number makes it
a constant, which is how a weight ``m g`` is applied.

**Kind:** through source (input).

**Ports**

| port | domain |
|---|---|
| `flange` | mechanical |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `forcesource` | N |

**Outputs**

| output | unit |
|---|---|
| `forcesource.velocity` | m/s |
| `forcesource.force` | N |
| `forcesource.power` | W |

### VelocitySource

`otwin.components.mechanical.VelocitySource(velocity=None, name=None)`

Imposes the velocity of ``flange`` (a kinematic drive).

**Kind:** across source (input).

**Ports**

| port | domain |
|---|---|
| `flange` | mechanical |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `velocitysource` | m/s |

**Outputs**

| output | unit |
|---|---|
| `velocitysource.velocity` | m/s |
| `velocitysource.force` | N |
| `velocitysource.power` | W |

### Fixed

`otwin.components.mechanical.Fixed(name=None)`

A point that does not move. The mechanical reference.

**Kind:** reference (the zero of its domain).

**Ports**

| port | domain |
|---|---|
| `port` | any |

## Rotational

Angular velocity across, torque through. Ports `a`, `b` or a single `flange`.

### Inertia

`otwin.components.rotational.Inertia(inertia=1.0, speed=0.0, name=None)`

A rotating mass: ``H = p^2 / (2 I)``, angular velocity ``omega = p / I``.

**Kind:** across storage.

**Ports**

| port | domain |
|---|---|
| `shaft` | rotational |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `inertia.inertia` | kg m^2 | 1 | > 0 | L = I w |

**States**

| state | unit | initial |
|---|---|---|
| `inertia.angular_momentum` | kg m^2/s | 0 |

**Outputs**

| output | unit |
|---|---|
| `inertia.angular_momentum` | kg m^2/s |
| `inertia.energy` | J |
| `inertia.angular_velocity` | rad/s |
| `inertia.torque` | N m |
| `inertia.power` | W |

### TorsionSpring

`otwin.components.rotational.TorsionSpring(stiffness=1.0, twist=0.0, name=None)`

A torsion spring: ``H = k theta^2 / 2``, torque ``tau = k theta``.

**Kind:** through storage.

**Ports**

| port | domain |
|---|---|
| `a` | rotational |
| `b` | rotational |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `torsionspring.stiffness` | N m/rad | 1 | > 0 | T = k theta |

**States**

| state | unit | initial |
|---|---|---|
| `torsionspring.twist` | rad | 0 |

**Outputs**

| output | unit |
|---|---|
| `torsionspring.twist` | rad |
| `torsionspring.energy` | J |
| `torsionspring.angular_velocity` | rad/s |
| `torsionspring.torque` | N m |
| `torsionspring.power` | W |

### RotationalDamper

`otwin.components.rotational.RotationalDamper(damping=1.0, law=None, name=None)`

Viscous friction ``tau = b omega``, or a nonlinear ``law(omega) -> tau``.

A bearing whose loss grows with speed is ``law=lambda w: c1 * w + c2 * w**3``.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `a` | rotational |
| `b` | rotational |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `rotationaldamper.damping` | N m s/rad | 1 | ≥ 0 | T = b w |

**Outputs**

| output | unit |
|---|---|
| `rotationaldamper.angular_velocity` | rad/s |
| `rotationaldamper.torque` | N m |
| `rotationaldamper.power` | W |

### TorqueSource

`otwin.components.rotational.TorqueSource(torque=None, name=None)`

An external torque on ``shaft``. ``torque=None`` makes it an input.

**Kind:** through source (input).

**Ports**

| port | domain |
|---|---|
| `shaft` | rotational |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `torquesource` | N m |

**Outputs**

| output | unit |
|---|---|
| `torquesource.angular_velocity` | rad/s |
| `torquesource.torque` | N m |
| `torquesource.power` | W |

### SpeedSource

`otwin.components.rotational.SpeedSource(speed=None, name=None)`

Imposes the angular velocity of ``shaft``.

**Kind:** across source (input).

**Ports**

| port | domain |
|---|---|
| `shaft` | rotational |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `speedsource` | rad/s |

**Outputs**

| output | unit |
|---|---|
| `speedsource.angular_velocity` | rad/s |
| `speedsource.torque` | N m |
| `speedsource.power` | W |

### Housing

`otwin.components.rotational.Housing(name=None)`

A shaft housing that does not rotate. The rotational reference.

**Kind:** reference (the zero of its domain).

**Ports**

| port | domain |
|---|---|
| `port` | any |

## Hydraulic

Pressure across, volumetric flow through. Ports `a`, `b`, `inlet`/`outlet`, or a single `port`.

### Tank

`otwin.components.hydraulic.Tank(area=1.0, level=0.0, base_elevation=0.0, density=1000.0, gravity=9.81, name=None)`

An open tank with a free surface.

State: stored volume ``V``. Energy: gravitational potential of the column,
``H = rho g (z V + V^2 / (2 A))`` with ``z`` the base elevation over the
datum, so the pressure at the port is ``rho g (z + V / A)``. The volume is
clamped at empty inside ``H``: a step that overshoots below zero reads a
pressure of zero rather than a negative one, so the tank cannot be drained
past empty and the energy cannot read back as an increase.

``level`` sets the initial level above the base. Extra output: ``level``.

**Kind:** across storage.

**Ports**

| port | domain |
|---|---|
| `port` | hydraulic |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `tank.area` | m^2 | 1 | > 0 | free surface area |
| `tank.base_elevation` | m | 0 | any | height of the tank floor |
| `tank.density` | kg/m^3 | 1000 | > 0 | of the liquid |
| `tank.gravity` | m/s^2 | 9.81 | > 0 | gravitational acceleration |

**States**

| state | unit | initial |
|---|---|---|
| `tank.volume` | m^3 | 0 |

**Outputs**

| output | unit |
|---|---|
| `tank.volume` | m^3 |
| `tank.energy` | J |
| `tank.pressure` | Pa |
| `tank.flow` | m^3/s |
| `tank.power` | W |
| `tank.level` | m |

### Orifice

`otwin.components.hydraulic.Orifice(area=0.01, discharge_coefficient=0.6, density=1000.0, name=None)`

Torricelli outflow through a sharp orifice: ``Q = Cd a sqrt(2 dp / rho)``.

Flow is positive from ``a`` to ``b`` when the pressure at ``a`` is higher;
the law is odd in the pressure difference so reversed flow is handled.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `a` | hydraulic |
| `b` | hydraulic |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `orifice.area` | m^2 | 0.01 | > 0 | opening area |
| `orifice.discharge_coefficient` | — | 0.6 | > 0 | Q = Cd A sqrt(2 dp / rho) |
| `orifice.density` | kg/m^3 | 1000 | > 0 | of the liquid |

**Outputs**

| output | unit |
|---|---|
| `orifice.pressure` | Pa |
| `orifice.flow` | m^3/s |
| `orifice.power` | W |

### Pipe

`otwin.components.hydraulic.Pipe(resistance=None, friction=None, law=None, name=None)`

A pipe with laminar (linear) or turbulent (quadratic) loss.

``resistance`` gives ``dp = R Q`` in Pa s/m^3. ``friction`` gives
``dp = K Q |Q|`` in Pa s^2/m^6 instead. Give one or the other.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `a` | hydraulic |
| `b` | hydraulic |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `pipe.resistance` | Pa s/m^3 | 500000 | > 0 | laminar: dp = R Q |

**Outputs**

| output | unit |
|---|---|
| `pipe.pressure` | Pa |
| `pipe.flow` | m^3/s |
| `pipe.power` | W |

### FluidInertance

`otwin.components.hydraulic.FluidInertance(inertance=1.0, flow=0.0, name=None)`

The inertia of the fluid in a pipe: ``dp = I dQ/dt``, ``H = I Q^2 / 2``.

The state is the flow momentum ``I Q``. ``inertance`` is ``rho L / A``.

**Kind:** through storage.

**Ports**

| port | domain |
|---|---|
| `a` | hydraulic |
| `b` | hydraulic |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `fluidinertance.inertance` | kg/m^4 | 1 | > 0 | rho L / A of the liquid column |

**States**

| state | unit | initial |
|---|---|---|
| `fluidinertance.flow_momentum` | Pa s | 0 |

**Outputs**

| output | unit |
|---|---|
| `fluidinertance.flow_momentum` | Pa s |
| `fluidinertance.energy` | J |
| `fluidinertance.pressure` | Pa |
| `fluidinertance.flow` | m^3/s |
| `fluidinertance.power` | W |

### FlowSource

`otwin.components.hydraulic.FlowSource(flow=None, name=None)`

A pump or a demand. Positive flow is drawn from ``b`` and delivered at
``a``; with ``b`` at :class:`Atmosphere` it is an inlet, with ``a`` there a
drain. ``flow=None`` makes it an input.

**Kind:** through source (input). In a `>>` chain it is entered at `b` and left at `a`.

**Ports**

| port | domain |
|---|---|
| `a` | hydraulic |
| `b` | hydraulic |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `flowsource` | m^3/s |

**Outputs**

| output | unit |
|---|---|
| `flowsource.pressure` | Pa |
| `flowsource.flow` | m^3/s |
| `flowsource.power` | W |

### PressureSource

`otwin.components.hydraulic.PressureSource(pressure=None, name=None)`

Imposes the pressure difference ``p_a - p_b``.

**Kind:** across source (input). In a `>>` chain it is entered at `b` and left at `a`.

**Ports**

| port | domain |
|---|---|
| `a` | hydraulic |
| `b` | hydraulic |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `pressuresource` | Pa |

**Outputs**

| output | unit |
|---|---|
| `pressuresource.pressure` | Pa |
| `pressuresource.flow` | m^3/s |
| `pressuresource.power` | W |

### Filter

`otwin.components.hydraulic.Filter(resistance, fouling=0.0, name=None)`

A filter, membrane or strainer: a linear resistance that fouls.

``dp = R Q`` with ``R = resistance * (1 + fouling)``. ``fouling`` is a
parameter (0 when clean) so a maintenance study can raise it with
``model.with_parameters({"<name>.fouling": 0.8})`` or identify it from
measurements. Ports ``a`` (upstream) and ``b`` (downstream).

Extra output: ``<name>.pressure_drop`` in Pa.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `a` | hydraulic |
| `b` | hydraulic |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `filter.resistance` | Pa s/m^3 | 2e+06 | > 0 | when clean |
| `filter.fouling` | — | 0 | ≥ 0 | extra resistance as a fraction of clean |

**Outputs**

| output | unit |
|---|---|
| `filter.pressure` | Pa |
| `filter.flow` | m^3/s |
| `filter.power` | W |
| `filter.pressure_drop` | Pa |

### Pump

`otwin.components.hydraulic.Pump(curve=None, shutoff=None, max_flow=None, inertance=1000000.0, name=None)`

A centrifugal pump given by its curve: pressure rise against flow.

Give either the table ``curve=[(flow, pressure_rise), ...]`` in m^3/s and
Pa, from shut-off (flow 0) to the end of the curve, or the two numbers of
a parabola: ``shutoff`` (pressure rise at zero flow) and ``max_flow`` (flow
at zero pressure rise), giving ``dp = shutoff (1 - (Q / max_flow)^2)``.

Ports ``inlet`` (suction) and ``outlet`` (discharge). Flow is positive from
inlet to outlet. Inside, the pump is a pressure source at the shut-off
value in series with a hydraulic loss that follows the curve and the
inertia of the water in the pump (``inertance``, kg/m^4, by default
that of about ten metres of pipe). The inertia is what every real pump
line has, and it makes the flow a state: the compiler integrates it
instead of solving the curve against the network at every step.

Outputs: ``<name>.flow`` (m^3/s), ``<name>.pressure_rise`` (Pa),
``<name>.hydraulic_power`` (W, the power handed to the water).

**Kind:** composite of `pump.head` (PressureSource), `pump.curve` (Pipe), `pump.water` (FluidInertance).

**Ports**

| port | domain |
|---|---|
| `inlet` | hydraulic |
| `outlet` | hydraulic |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `pump.head.pressure` | Pa | 400000 | any | the imposed pressure; `None` makes it an input |
| `pump.curve.friction` | Pa s^2/m^6 | 6.25e+07 | > 0 | turbulent: dp = K Q \|Q\| |
| `pump.water.inertance` | kg/m^4 | 1e+06 | > 0 | rho L / A of the liquid column |

**States**

| state | unit | initial |
|---|---|---|
| `pump.water.flow_momentum` | Pa s | 0 |

**Outputs**

| output | unit |
|---|---|
| `pump.head.pressure` | Pa |
| `pump.head.flow` | m^3/s |
| `pump.head.power` | W |
| `pump.curve.pressure` | Pa |
| `pump.curve.flow` | m^3/s |
| `pump.curve.power` | W |
| `pump.water.flow_momentum` | Pa s |
| `pump.water.energy` | J |
| `pump.water.pressure` | Pa |
| `pump.water.flow` | m^3/s |
| `pump.water.power` | W |
| `pump.flow` | m^3/s |
| `pump.pressure_rise` | Pa |
| `pump.hydraulic_power` | W |

### Atmosphere

`otwin.components.hydraulic.Atmosphere(name=None)`

Atmospheric pressure. The hydraulic reference.

**Kind:** reference (the zero of its domain).

**Ports**

| port | domain |
|---|---|
| `port` | any |

## Thermal

Temperature across, heat flow through. Ports `a`, `b` or a single `port`.

### ThermalMass

`otwin.components.thermal.ThermalMass(capacity=1.0, temperature=293.15, name=None)`

A lump of material at one temperature: ``C dT/dt = sum of heat flows``.

``temperature`` sets the initial temperature in kelvin. Extra output:
``temperature``.

**Kind:** across storage.

**Ports**

| port | domain |
|---|---|
| `port` | thermal |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `thermalmass.capacity` | J/K | 1 | > 0 | heat = C T |

**States**

| state | unit | initial |
|---|---|---|
| `thermalmass.heat` | J | 293.15 |

**Outputs**

| output | unit |
|---|---|
| `thermalmass.heat` | J |
| `thermalmass.energy` | J |
| `thermalmass.temperature` | K |
| `thermalmass.heat_flow` | W |
| `thermalmass.power` | W |

### ThermalResistance

`otwin.components.thermal.ThermalResistance(resistance=1.0, law=None, name=None)`

Conduction: ``Q = (T_a - T_b) / R``.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `a` | thermal |
| `b` | thermal |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `thermalresistance.resistance` | K/W | 1 | > 0 | dT = R q |

**Outputs**

| output | unit |
|---|---|
| `thermalresistance.temperature` | K |
| `thermalresistance.heat_flow` | W |
| `thermalresistance.power` | W |

### Convection

`otwin.components.thermal.Convection(conductance=1.0, name=None)`

Convection or a heat-exchanger duty: ``Q = h A (T_a - T_b)``.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `a` | thermal |
| `b` | thermal |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `convection.conductance` | W/K | 1 | > 0 | h A: q = hA dT |

**Outputs**

| output | unit |
|---|---|
| `convection.temperature` | K |
| `convection.heat_flow` | W |
| `convection.power` | W |

### HeatSource

`otwin.components.thermal.HeatSource(heat=None, name=None)`

Heat delivered into ``port`` in watts. ``heat=None`` makes it an input.

**Kind:** through source (input).

**Ports**

| port | domain |
|---|---|
| `port` | thermal |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `heatsource` | W |

**Outputs**

| output | unit |
|---|---|
| `heatsource.temperature` | K |
| `heatsource.heat_flow` | W |
| `heatsource.power` | W |

### Losses

`otwin.components.thermal.Losses(*sources, name=None)`

The power dissipated by other components, delivered into ``port`` as heat.

``Losses(r0, r1)`` sums the losses of ``r0`` and ``r1`` (any resistor,
damper, pipe friction ... anything with a dissipative law) at every instant
and injects them as heat flow. Connect ``port`` to the thermal mass that
warms up. Nothing has to be written about the power: the compiler already
knows ``across * through`` of each source.

Output: ``<name>.heat_flow`` in watts.

**Kind:** heat injection.

**Ports**

| port | domain |
|---|---|
| `port` | thermal |

**Outputs**

| output | unit |
|---|---|
| `losses.heat_flow` | W |

### Ambient

`otwin.components.thermal.Ambient(temperature=293.15, name=None)`

A body large enough that its temperature does not change. ``temperature=None``
makes the ambient temperature an input.

**Kind:** across source.

**Ports**

| port | domain |
|---|---|
| `port` | thermal |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `ambient.temperature` | K | 293.15 | any | the imposed temperature; `None` makes it an input |

**Outputs**

| output | unit |
|---|---|
| `ambient.temperature` | K |
| `ambient.heat_flow` | W |
| `ambient.power` | W |

## Two-ports

Lossless couplings between two branches, in one domain or across two.

### Transformer

`otwin.components.twoport.Transformer(ratio=1.0, domain_1='electrical', domain_2='electrical', name=None)`

``across_2 = ratio * across_1`` and ``through_1 = -ratio * through_2``.

Terminals ``p1, n1`` on side 1 and ``p2, n2`` on side 2. Give the domain of
each side; the default is electrical on both.

**Kind:** transformer.

**Ports**

| port | domain |
|---|---|
| `p1` | electrical |
| `n1` | electrical |
| `p2` | electrical |
| `n2` | electrical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `transformer.ratio` | — | 1 | any | across_2 = ratio * across_1 |

**Outputs**

| output | unit |
|---|---|
| `transformer.side1.voltage` | V |
| `transformer.side1.current` | A |
| `transformer.side1.power` | W |
| `transformer.side2.voltage` | V |
| `transformer.side2.current` | A |

### Gyrator

`otwin.components.twoport.Gyrator(ratio=1.0, domain_1='electrical', domain_2='rotational', name=None)`

``across_2 = ratio * through_1`` and ``across_1 = -ratio * through_2``.

**Kind:** gyrator.

**Ports**

| port | domain |
|---|---|
| `p1` | electrical |
| `n1` | electrical |
| `p2` | rotational |
| `n2` | rotational |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `gyrator.ratio` | — | 1 | any | across_2 = ratio * through_1 |

**Outputs**

| output | unit |
|---|---|
| `gyrator.side1.voltage` | V |
| `gyrator.side1.current` | A |
| `gyrator.side1.power` | W |
| `gyrator.side2.angular_velocity` | rad/s |
| `gyrator.side2.torque` | N m |

## Composites

Devices built from the primitives: a motor, a battery (and `Pump`, listed under hydraulic). Their parts are ordinary components named `<device>.<part>`.

### DCMotor

`otwin.components.composite.DCMotor(resistance=1.0, inductance=0.5, torque_constant=0.5, inertia=0.01, friction=0.1, current=0.0, speed=0.0, name=None)`

A permanent-magnet DC motor: armature resistance and inductance, the
electromechanical coupling, rotor inertia and viscous friction.

Terminals: electrical ``p``, ``n``; rotational ``shaft``.

Internally the coupling is a transformer with ratio ``1 / k`` between the
armature branch and the shaft, so that back-emf is ``k omega`` and torque
is ``k i``. States: ``<name>.armature.flux`` and ``<name>.rotor.angular_momentum``.

**Kind:** composite of `dcmotor.armature_resistance` (Resistor), `dcmotor.armature` (Inductor), `dcmotor.coupling` (Transformer), `dcmotor.rotor` (Inertia), `dcmotor.bearing` (RotationalDamper), `dcmotor.housing` (Housing).

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |
| `shaft` | rotational |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `dcmotor.armature_resistance.resistance` | ohm | 1 | > 0 | v = R i |
| `dcmotor.armature.inductance` | H | 0.5 | > 0 | flux = L i |
| `dcmotor.coupling.ratio` | — | 2 | any | across_2 = ratio * across_1 |
| `dcmotor.rotor.inertia` | kg m^2 | 0.01 | > 0 | L = I w |
| `dcmotor.bearing.damping` | N m s/rad | 0.1 | ≥ 0 | T = b w |

**States**

| state | unit | initial |
|---|---|---|
| `dcmotor.armature.flux` | Wb | 0 |
| `dcmotor.rotor.angular_momentum` | kg m^2/s | 0 |

**Outputs**

| output | unit |
|---|---|
| `dcmotor.armature_resistance.voltage` | V |
| `dcmotor.armature_resistance.current` | A |
| `dcmotor.armature_resistance.power` | W |
| `dcmotor.armature.flux` | Wb |
| `dcmotor.armature.energy` | J |
| `dcmotor.armature.voltage` | V |
| `dcmotor.armature.current` | A |
| `dcmotor.armature.power` | W |
| `dcmotor.coupling.side1.voltage` | V |
| `dcmotor.coupling.side1.current` | A |
| `dcmotor.coupling.side1.power` | W |
| `dcmotor.coupling.side2.angular_velocity` | rad/s |
| `dcmotor.coupling.side2.torque` | N m |
| `dcmotor.rotor.angular_momentum` | kg m^2/s |
| `dcmotor.rotor.energy` | J |
| `dcmotor.rotor.angular_velocity` | rad/s |
| `dcmotor.rotor.torque` | N m |
| `dcmotor.rotor.power` | W |
| `dcmotor.bearing.angular_velocity` | rad/s |
| `dcmotor.bearing.torque` | N m |
| `dcmotor.bearing.power` | W |

### Battery

`otwin.components.battery.Battery(capacity, ocv, resistance=0.01, rc_branches=(), thermal=None, soc=1.0, temperature=298.15, ocv_points=21, name=None)`

An equivalent-circuit battery: OCV(soc) + R0 + RC pairs, optional thermal.

**Kind:** composite of `battery.ocv` (_OpenCircuit), `battery.r0` (Resistor), `battery.r1` (Resistor), `battery.c1` (Capacitor), `battery.cell` (ThermalMass), `battery.losses` (Losses). In a `>>` chain it is entered at `n` and left at `p`.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |
| `thermal` | thermal |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `battery.r0.resistance` | ohm | 0.01 | > 0 | v = R i |
| `battery.r1.resistance` | ohm | 0.0005 | > 0 | v = R i |
| `battery.c1.capacitance` | F | 20000 | > 0 | q = C v |
| `battery.cell.capacity` | J/K | 1200 | > 0 | heat = C T |

**States**

| state | unit | initial |
|---|---|---|
| `battery.ocv.charge` | C | 360000 |
| `battery.c1.charge` | C | 0 |
| `battery.cell.heat` | J | 357780 |

**Outputs**

| output | unit |
|---|---|
| `battery.ocv.charge` | C |
| `battery.ocv.energy` | J |
| `battery.ocv.voltage` | V |
| `battery.ocv.current` | A |
| `battery.ocv.power` | W |
| `battery.r0.voltage` | V |
| `battery.r0.current` | A |
| `battery.r0.power` | W |
| `battery.r1.voltage` | V |
| `battery.r1.current` | A |
| `battery.r1.power` | W |
| `battery.c1.charge` | C |
| `battery.c1.energy` | J |
| `battery.c1.voltage` | V |
| `battery.c1.current` | A |
| `battery.c1.power` | W |
| `battery.cell.heat` | J |
| `battery.cell.energy` | J |
| `battery.cell.temperature` | K |
| `battery.cell.heat_flow` | W |
| `battery.cell.power` | W |
| `battery.losses.heat_flow` | W |
| `battery.soc` | — |
| `battery.voltage` | V |
| `battery.current` | A |
| `battery.temperature` | K |
| `battery.heat_flow` | W |

## Fundamental (any domain)

The four primitives every domain-specific component is made of, for a domain the library does not name.

### Storage

`otwin.components.fundamental.Storage(domain, coefficient=1.0, kind='across', initial=0.0, energy=None, name=None)`

An energy store of either kind, in any domain.

**Kind:** across storage.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `storage.coefficient` | F | 1 | > 0 | state = coefficient * effort |

**States**

| state | unit | initial |
|---|---|---|
| `storage.state` | C | 0 |

**Outputs**

| output | unit |
|---|---|
| `storage.state` | C |
| `storage.energy` | J |
| `storage.voltage` | V |
| `storage.current` | A |
| `storage.power` | W |

### Dissipator

`otwin.components.fundamental.Dissipator(domain, resistance=1.0, law=None, name=None)`

``through = law(across)``; by default ``across / resistance``.

**Kind:** resistor.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `dissipator.resistance` | ohm | 1 | > 0 | across = resistance * through |

**Outputs**

| output | unit |
|---|---|
| `dissipator.voltage` | V |
| `dissipator.current` | A |
| `dissipator.power` | W |

### Source

`otwin.components.fundamental.Source(domain, value=None, kind='across', name=None)`

Imposes the across variable (``kind="across"``) or the through variable.

``value=None`` makes the source an input of the compiled model, named after
the component. A number makes it a constant that can still be changed with
``model.set_parameters``.

**Kind:** across source (input). In a `>>` chain it is entered at `n` and left at `p`.

**Ports**

| port | domain |
|---|---|
| `p` | electrical |
| `n` | electrical |

**Inputs** when the value is `None`

| input | unit |
|---|---|
| `source` | V |

**Outputs**

| output | unit |
|---|---|
| `source.voltage` | V |
| `source.current` | A |
| `source.power` | W |

### Reference

`otwin.components.fundamental.Reference(name=None)`

The zero of the across variable, in any domain. Same as ``Ground``.

**Kind:** reference (the zero of its domain).

**Ports**

| port | domain |
|---|---|
| `port` | any |

### Transformer (any domain)

`otwin.components.fundamental.Transformer(ratio=1.0, domain_1='electrical', domain_2='electrical', name=None)`

``across_2 = ratio * across_1`` and ``through_1 = -ratio * through_2``.

Terminals ``p1, n1`` on side 1 and ``p2, n2`` on side 2. Give the domain of
each side; the default is electrical on both.

**Kind:** transformer.

**Ports**

| port | domain |
|---|---|
| `p1` | electrical |
| `n1` | electrical |
| `p2` | electrical |
| `n2` | electrical |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `transformer.ratio` | — | 1 | any | across_2 = ratio * across_1 |

**Outputs**

| output | unit |
|---|---|
| `transformer.side1.voltage` | V |
| `transformer.side1.current` | A |
| `transformer.side1.power` | W |
| `transformer.side2.voltage` | V |
| `transformer.side2.current` | A |

### Gyrator (any domain)

`otwin.components.fundamental.Gyrator(ratio=1.0, domain_1='electrical', domain_2='rotational', name=None)`

``across_2 = ratio * through_1`` and ``across_1 = -ratio * through_2``.

**Kind:** gyrator.

**Ports**

| port | domain |
|---|---|
| `p1` | electrical |
| `n1` | electrical |
| `p2` | rotational |
| `n2` | rotational |

**Parameters** (as the compiled model names them; the value column is the example's)

| parameter | unit | value | valid | meaning |
|---|---|---|---|---|
| `gyrator.ratio` | — | 1 | any | across_2 = ratio * through_1 |

**Outputs**

| output | unit |
|---|---|
| `gyrator.side1.voltage` | V |
| `gyrator.side1.current` | A |
| `gyrator.side1.power` | W |
| `gyrator.side2.angular_velocity` | rad/s |
| `gyrator.side2.torque` | N m |
