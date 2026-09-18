# Physical semantics

A component in Otwin is not a box with a method on it. It is a statement about
physics, and the compiler is entitled to reason about it. This page says what each
construction means, in the order the meaning is built up.

```text
Component
    ↓
Port
    ↓
Across and through variables
    ↓
Connection
    ↓
Conservation laws
    ↓
Energy storage and dissipation
    ↓
Physical model
```

## The two variables of a domain

Each physical domain has a pair of variables whose product is a power. One of them
is shared where parts meet, the other is conserved there.

| Domain | Across [unit] | Through [unit] | Product |
|---|---|---|---|
| electrical | voltage [V] | current [A] | watt |
| mechanical | velocity [m/s] | force [N] | watt |
| rotational | angular velocity [rad/s] | torque [N m] | watt |
| hydraulic | pressure [Pa] | volumetric flow [m³/s] | watt |
| thermal | temperature [K] | heat flow [W] | not a power |

The thermal row is the exception and it is treated as one throughout. Temperature
times heat flow is not a power, so a model containing a thermal store is reported as
`pseudo-port-hamiltonian` and its energy audit is a stability statement rather than
a first-law one. The heat balances themselves are exact. A model where a real energy
and an entropy are both needed belongs in [Irreversible
systems](irreversible.md).

A **port** exposes one such pair. Because a port declares its domain, what it may be
joined to is decided before any equation exists.

## What a connection asserts

Joining ports asserts two things about the node they form.

The across variables are **equal**. Two points joined by an ideal conductor are at
one voltage. Two parts bolted together move at one velocity. Two pipes meeting at a
tee are at one pressure. Two faces in contact are at one temperature.

The through variables **sum to zero**. Current into a junction leaves it. Forces on
a massless point balance. Flow into a tee leaves it. Heat into a wall leaves it.

Nothing else is asserted, and nothing is inferred from the names of the components.
This is why the same compiler serves five domains and why the rule can be checked
before any number exists.

## What a component asserts

A component declares one or more **branches**. A branch is a constitutive relation
between the two variables, either between two of its ports or between one port and
the domain's reference. There are six kinds, and every component in the library is
built from them.

| Branch | The relation | Meaning | Examples |
|---|---|---|---|
| across storage | state integrates the through variable, across = ∂H/∂state | energy stored by a shared quantity | `Capacitor`, `Mass`, `Inertia`, `Tank`, `ThermalMass` |
| through storage | state integrates the across variable, through = ∂H/∂state | energy stored by a conserved quantity | `Inductor`, `Spring`, `TorsionSpring`, `FluidInertance` |
| resistor | through = law(across) | energy leaves the system | `Resistor`, `Damper`, `Orifice`, `Pipe`, `ThermalResistance`, `Convection` |
| across source | across imposed | the outside world holds a potential | `VoltageSource`, `VelocitySource`, `PressureSource`, `Ambient` |
| through source | through imposed | the outside world drives a flow | `CurrentSource`, `ForceSource`, `TorqueSource`, `FlowSource`, `HeatSource` |
| two-port | a lossless relation between two pairs | energy moves, unchanged in amount | `Transformer`, `Gyrator` |

Two consequences follow immediately, and they are the reason the compiler can be
trusted with the equations.

**The states are not a modelling choice.** They are the storages. A model's state
vector is the list of things that store energy, which is why you never declare one
and why the compiler can tell you that a system with no store has nothing to
integrate.

**Where energy leaves is explicit.** Only resistive branches remove energy. Sources
are the only way in. Two-ports move energy between domains without changing the
total. This separation is what the structure of the compiled model records, and what
lets a check on the model's form say something about every trajectory rather than
about one run.

## Energy, and why it is the organising quantity

Every storage brings an energy function of its state: $q^2/2C$ for a capacitor,
$p^2/2m$ for a mass, $\rho g (z V + V^2 / 2A)$ for a tank. The total is the stored
energy of the system, and the compiler writes the model so that the change in that
total is exactly what crossed the ports minus what the resistive laws removed.

Written out, with $H$ the stored energy, $y^{\mathsf T}u$ the power supplied through
the ports and the second term the power dissipated,

$$\frac{\mathrm{d}H}{\mathrm{d}t} = y^{\mathsf T}u - \nabla H^{\mathsf T}R\,\nabla H .$$

With the sources at zero, stored energy cannot rise. That is **passivity**, and here
it is an algebraic property of the model rather than an observation about a
particular run. A curve fitted to a discharge record can extrapolate to a battery
that generates energy. A model in this form cannot, at any parameter value.

The mathematics of the form, including what $J$ and $R$ are and how the compiler
obtains them, is in [Port-Hamiltonian systems](port-hamiltonian.md). What survives
discretisation, and what does not, is in [Structure-preserving
integration](integration.md).

## Parameters carry units and rules

A parameter is declared with a value, a unit and a validity rule: a mass is
positive, a damping coefficient is not negative, a tank area is positive. The rule
is checked when the component is constructed, not when the model runs, so a typo in
a data sheet is caught in the line where it was typed.

Parameters remain symbolic through compilation. `spring.stiffness` is a name in the
compiled equations, not a number folded into them. That is what makes a parameter
sweep free and what lets an estimator fit a parameter without rebuilding the model.

## What the compiled model therefore means

A compiled Otwin model is a claim with four parts.

1. These are the energy stores of the system, and this is what each one holds.
2. This is how they are interconnected, and the interconnection neither creates nor
   destroys energy.
3. This is where energy leaves, and it can only leave.
4. These are the ports through which the outside world acts, and this is the power
   crossing each of them.

Every one of those is checkable, which is the subject of [Model
validity](validity.md) for a single model and of
[Conformance](../specification/conformance.md) for an implementation.
