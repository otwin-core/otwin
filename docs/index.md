# Otwin

```{image} images/otwin_header.png
:alt: Otwin
:width: 100%
```

**Otwin is an open-source physics engine for engineering systems.** You describe a
machine the way you would draw it, as components joined at ports, and Otwin writes
the equations, compiles them and runs them. Around the compiled model sit the tools
that connect it to a real asset: state estimation, parameter calibration, hybrid
models, forecasting with measured uncertainty, validation, and a record of what the
model has been shown to do.

```{code-block} bash
pip install "otwin[engine]"
```

## The idea in four steps

```{mermaid}
flowchart LR
    A["Describe the system<br/>components · ports · connections"] --> B["Otwin compiles it<br/>equations, not by hand"]
    B --> C["Run executable physics<br/>simulate · step · batch"]
    C --> D["Connect it to the asset<br/>estimate · calibrate · forecast · refuse"]
```

You never write `dx/dt`. The compiler reads the connections, finds the energy
stores, applies the conservation law of each domain and produces a model that runs
in a Rust engine. What it produced is inspectable if you want to see it, and
ignorable if you do not.

## Start here

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} Modeling
:link: modeling/index
:link-type: doc

The vocabulary: components, ports, connections, parameters, domains. How a machine
becomes a `System`.
:::

:::{grid-item-card} Physics
:link: physics/index
:link-type: doc

What a model means, what the compiler does with it, and what the result is
guaranteed to obey.
:::

:::{grid-item-card} Digital twins
:link: digital-twins/index
:link-type: doc

From a model of a machine to a twin of one particular asset, kept in step with its
measurements.
:::

::::

## The parts of the project

| | |
|---|---|
| [Architecture](overview/architecture.md) | The layers: framework, compiler, intermediate representation, engine, twin tools |
| [Physical semantics](physics/physical-semantics.md) | What a component, a port and a connection mean physically |
| [Compilation](physics/compilation.md) | How a drawing becomes `dx/dt = f(x, u)` |
| [The specification](specification/index.md) | What an Otwin model means, written down independently of this code |
| [Conformance](specification/conformance.md) | The executable tests any implementation can be judged by |
| [Component reference](reference/components.md) | Every component, with its ports, parameters, states and outputs |
| [Developer guide](developer/index.md) | Writing components, working on the compiler, adding a backend |

## Three systems, in one line each

A **mass on a spring** under gravity is `mass >> spring >> ceiling`, with a damper
and the weight meeting at the mass. The compiled model settles at
`weight.force / spring.stiffness` and gains no energy on any step.

A **battery module** is a `Battery` with an open-circuit-voltage table, a series
resistance, two RC pairs and a thermal mass, in a loop with a current load. One hour
at 50 A takes it from 0.9 to 0.4 state of charge, 3.152 V and 33.8 °C.

A **pump line** is `Tank >> Pipe >> Pump >> Filter >> Atmosphere`. Clean, it carries
235 m³/h. With the filter fouled to twice its resistance, 196 m³/h at a higher pump
head, which is the whole story of a filter that asks for more.

[Devices](modeling/devices.md) builds the last two from their data sheets.

## Where to go next

[Install](overview/install.md) and the [Quickstart](overview/quickstart.md) get a
motor drive compiled, simulated and estimated in twenty lines. [What is
Otwin](overview/index.md) is the longer answer to what this is for, and
[Architecture](overview/architecture.md) is what it is made of. Questions, ideas and
systems you have built go to
[Discussions](https://github.com/otwin-core/otwin/discussions).

```{toctree}
:hidden:
:maxdepth: 2

overview/index
modeling/index
physics/index
digital-twins/index
specification/index
reference/index
developer/index
```
