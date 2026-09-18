# Developer guide

How Otwin is built, and how to extend it. [Architecture](../overview/architecture.md)
is the same picture for a reader who is not going to open the source.

| I want to | Page |
|---|---|
| find my way around the source, layer by layer | [Internals](internals.md) |
| add a physical component or a composite device | [Adding components](components.md) |
| change how systems are compiled, or add a backend | [Compiler development](compiler.md) |
| know what changed from 0.4 and why | [Migration map](migration.md) |

Contributions are welcome, and a new physical component is one of the easiest places
to start: define the component, its ports, its parameters and its constitutive law,
give it a closed-form or reference result, and add the tests. See
[CONTRIBUTING.md](https://github.com/otwin-core/otwin/blob/main/CONTRIBUTING.md).

A contribution to the [specification](../specification/index.md) is a different and
equally useful thing: a new fixture is a physical system with a closed-form answer
that no current fixture covers, plus a mutant that proves its check works. See
[Conformance](../specification/conformance.md).

```{toctree}
:hidden:
:maxdepth: 1

internals
components
compiler
migration
```
