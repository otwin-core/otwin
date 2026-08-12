# Maintainers

| Name | GitHub | Scope |
|---|---|---|
| Javier Marin | [@Javihaus](https://github.com/Javihaus) | Everything, for now |

## Two open maintainer slots

The type test in [`otwin-spec`](https://github.com/otwin-core/otwin-spec) grades
an implementation over a subprocess boundary, so it can judge a language this
repository knows nothing about. That makes a second-language implementation a
self-contained piece of work with an objective definition of done: **pass the
abstract test suite, unmodified.**

### Julia — open

A minimal native core, not a wrapper. Julia has better tools for this than
Python does — `ForwardDiff` for the energy gradient, `DifferentialEquations.jl`
for the solver — so a wrapper would be worse than the thing it wraps.

Scope is roughly a thousand lines: the energy-based model (`J`, `R`, `H`, `g`,
power balance, structure checks), an energy-consistent integrator, manifest
read and write, and the conformance adapter. Nothing else. Evaluation,
estimation and uncertainty stay Python-only until someone asks, and the
implementation declares that in its conformance statement rather than implying
parity.

### MATLAB — open

Same scope, same test. Pure MATLAB: File Exchange refuses any submission
containing MEX files or compiled binaries, and a toolbox that shells out to
Python is useless to the Simulink and Simscape users who are the reason to ship
MATLAB at all.

### What being a maintainer means here, concretely

- Review pull requests that touch your area. There will not be many.
- Have an opinion when a design decision affects it.
- You do **not** need to write code on a schedule.
- You do **not** need to know the rest of the ecosystem.
- You can stop whenever you like, and we will say so gracefully in this file.

Open an issue titled `Maintainer: <your name>`, or email javier@jmarin.info. A
short yes is enough to start a conversation.

## Governance

There is none yet, deliberately. A steering council of one person is theatre.

When this project has two or more external maintainers we will adopt the
standard NumFOCUS template, the same one [SciML](https://sciml.ai/governance/)
uses.
