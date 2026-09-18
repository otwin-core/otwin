# Connections

A connection is not a wire between two objects in a drawing program. It is a
physical statement, and it is the statement the compiler turns into an equation. Two
verbs write every connection in Otwin, and this page says exactly what each one
means.

## The rule, once

Where ports meet, they form a **node**. At a node

- the **across** variable is shared by every port: one voltage, one velocity, one
  pressure, one temperature;
- the **through** variables sum to zero: currents, forces, flows and heat flows add
  up to nothing left over.

That single rule is Kirchhoff's two laws, Newton's third law, conservation of mass
at a pipe junction and conservation of heat at a wall. It is what lets one compiler
serve five domains, and it is why joining ports of two different domains is refused
where you write it rather than later.

A component that measures against its domain's reference has one port. The reference
itself is `Ground`, or the same thing under the name of its domain: `Fixed`,
`Housing`, `Atmosphere`.

## Two verbs

```text
a >> b >> c        composition: join them in a line, the way the drawing reads
system.connect(…)  explicit topology: any number of ports meeting at one node
```

`>>` is for the common case, a chain. `mass >> spring >> ceiling` joins the mass to
one end of the spring and the other end of the spring to the ceiling.
`tank >> pipe >> pump >> filter >> outfall` is a pump line, left to right, in the
order the water goes. A chain returns a {class}`otwin.System`, so it is usually the
first line you write.

`connect` is for everything a line cannot say: three things meeting at one point, a
second circuit hanging off a port, a shaft leaving an electrical loop into the
rotational domain. It takes any number of ports and joins them into one node, and it
returns the system so calls can be chained.

```{code-block} python
system = mass >> spring >> ceiling
system.connect(mass.flange, damper.a, weight.flange)   # three at the mass
system.connect(damper.b, ceiling.port)
```

Both verbs produce the same thing. A chain is a shorthand for a sequence of
two-port connections, not a different kind of object.

## Which end is which

A chain follows the path the through variable takes, so it reads the way an engineer
would trace the circuit.

`gnd >> supply >> motor >> gnd` is the electrical loop of a drive, closed on ground,
and it reads as the current does. In the hydraulic domain,
`tank >> pipe >> pump >> filter >> atmosphere` reads as the water does. In the
mechanical domain, `mass >> spring >> wall` reads from the moving part to the
anchored one.

Inside a two-port component the positive direction of its through variable is from
its first port to its second: `p` to `n` for an electrical element, `a` to `b` for a
mechanical or thermal one, `inlet` to `outlet` for a hydraulic one. A spring's
extension is positive when `a` moves away from `b`. Getting a sign backwards does
not break the model, it mirrors the quantity, and the outputs are named clearly
enough to see it in one run.

## What the compiler does with a node

Every node becomes one conservation equation, unless a storage or an across source
already fixes its across variable. That is the whole of the compiler's front end,
and it is described in [Compilation](../physics/compilation.md).

Three consequences are worth knowing before you draw.

**Two storages of the same kind cannot be joined directly.** Two capacitors in
parallel, two masses joined rigidly, two inertias on one shaft: each pair would fix
the same quantity twice, and the compiler refuses with both names. Either merge them
into one store or put the thing that is physically between them into the model: a
resistor, a damper, a stiff spring, a pipe.

**A node needs a path to the reference.** If nothing determines the potential of a
node, there is no equation that can. Connect it to `Ground`, `Fixed`, `Housing` or
`Atmosphere`, which is also what the real system has.

**A nonlinear law needs its across variable pinned.** A nonlinear resistance sitting
on a node that no storage and no source pins is an algebraic loop the compiler will
not solve numerically at run time. Put a small storage on that node, or use the
inverse form of the law where the component offers one. `Pipe`, `Orifice` and `Pump`
carry both forms for exactly this reason.

## Domains meet through two-ports

`Transformer` and `Gyrator` are the only components that may have ports in two
different domains, and they are lossless: they move power, they do not dissipate it.
The compiler puts them into the interconnection part of the structure, never into
the dissipation part.

A gearbox is a transformer between two rotational sides, a lever between two
mechanical ones, an electrical machine a transformer between an electrical and a
rotational side, a hydraulic piston a transformer between a hydraulic and a
mechanical side. `DCMotor` is a composite built exactly that way, and its source is
the template for a device of your own.

## From the drawing to the physics

```text
component  +  port  +  connection
                ↓
     node: one across, through summing to zero
                ↓
   conservation equation per node, constitutive law per branch
                ↓
            dx/dt = f(x, u)
```

The vocabulary is on the [Modeling](index.md) page, what each of those means
physically is in [Physical semantics](../physics/physical-semantics.md), and
[Domains](domains.md) shows both verbs at work in each of the five domains.
