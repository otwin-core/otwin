# Physics and semantics

What an Otwin model means, what the compiler makes of it, and what the result is
guaranteed to obey.

You do not need this section to use Otwin. The [Quickstart](../overview/quickstart.md)
and [Modeling](../modeling/index.md) are self-contained. Read these pages when a
model surprises you, or when you need to know why a result can be trusted rather
than only how to obtain it.

| Page | What it answers |
|---|---|
| [Physical semantics](physical-semantics.md) | What a component, a port, a connection and a state mean physically |
| [Port-Hamiltonian systems](port-hamiltonian.md) | The form the compiler targets, and the guarantee that comes with it |
| [Irreversible systems](irreversible.md) | When entropy production has to be part of the model |
| [Structure-preserving integration](integration.md) | How the guarantee survives discretisation |
| [Compilation](compilation.md) | How a drawing becomes `dx/dt = f(x, u)`, and what the compiler refuses |
| [Model validity](validity.md) | What a compiled model promises, and how to check that it kept the promise |
| [Writing models by hand](advanced-api.md) | The layer below the component library, for physics it does not cover yet |

The mathematics on these pages is what the [specification](../specification/index.md)
rests on, and what the [conformance suite](../specification/conformance.md) tests.

```{toctree}
:hidden:
:maxdepth: 1

physical-semantics
port-hamiltonian
irreversible
integration
compilation
validity
advanced-api
```
