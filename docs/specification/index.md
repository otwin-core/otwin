# The specification

An Otwin model has a defined meaning that does not depend on any particular
implementation.

The specification defines the physical semantics, the model interface, the exchange
format for a fitted twin and the requirements for being correct. The conformance
suite provides executable tests for those requirements. The Python package
documented here is the reference implementation of them.

```{mermaid}
flowchart TD
    S["<b>Specification</b><br/>normative, RFC 2119 language"]
    SEM["Physical semantics<br/>what a model asserts"]
    SCH["Schemas<br/>the twin manifest on disk"]
    REF["Reference models<br/>plain NumPy, no dependencies"]
    CON["<b>Conformance suite</b><br/>fixtures with closed-form answers"]
    PY["Python implementation<br/>this package"]
    OTH["Any other implementation<br/>Julia · MATLAB · Rust · yours"]

    S --> SEM
    S --> SCH
    SEM --> REF
    SCH --> CON
    REF --> CON
    CON --> PY
    CON --> OTH
```

Where the specification and an implementation disagree, the specification is correct
and the implementation has a bug. That includes this one.

## Why it is separate

Otwin is Python first, with bindings to other languages and a reference
implementation of its own. Without a written contract and executable tests, three
things happen, reliably.

Each language grows a slightly different notion of what a model is. A fitted twin
stops moving between them. And "physics-informed" becomes a claim rather than a
property, because nothing checks it.

A model that declares port-Hamiltonian structure is making a **falsifiable claim**:
that its interconnection is lossless, that its dissipation is non-negative, and
therefore that its forecasts cannot create energy at any horizon. That claim is
exactly what makes the model worth using instead of a curve fit. It is also
invisible on a test set, because a model with a subtly wrong structure scores well
on held-out data and then drifts when extrapolated, which is the situation the
structure was supposed to protect against.

So the claim needs a test. That is what the conformance suite is.

## What is in it

| Part | What it defines | Where |
|---|---|---|
| The interface | what a twin model is, and the four verbs it answers to | specification §3 |
| The twin manifest | how a fitted twin is written to disk, and read in another language | specification §4, [manifest](../digital-twins/manifest.md) |
| The conformance suite | what it means to be correct, as runnable tests | specification §5, [conformance](conformance.md) |
| Versioning | how the specification, an implementation and the engine move separately | specification §6, [versioning](versioning.md) |

It deliberately does not specify algorithms. Any integrator, any estimator and any
uncertainty method is permitted, provided the results satisfy the conformance
requirements.

## Normative and informative

The distinction is worth keeping in mind while reading this site.

**Normative.** The specification document, the JSON schemas and the conformance
suite. They define what an implementation must do. They live in
[otwin-spec](https://github.com/otwin-core/otwin-spec) and have their own version.

**Informative.** Everything else in this documentation. Concepts, guides, the
component reference, the API reference and the design rationale. They describe what
this implementation does and how to use it. They are not the contract.

## The documents

- [The specification](https://github.com/otwin-core/otwin-spec/blob/main/spec/SPECIFICATION.md),
  normative, in RFC 2119 language
- [Schemas](https://github.com/otwin-core/otwin-spec/tree/main/src/otwin_spec/schemas),
  JSON Schema, read directly by the bindings in other languages
- [Fixtures](https://github.com/otwin-core/otwin-spec/tree/main/src/otwin_spec/fixtures),
  one JSON file per physical case
- [Reference models](https://github.com/otwin-core/otwin-spec/blob/main/src/otwin_spec/reference.py),
  around two hundred lines of plain NumPy defining what the standard systems *are*

Reference models live in the specification deliberately. A specification that can
only be checked by running the thing it specifies is not a specification.

```{toctree}
:hidden:
:maxdepth: 1

conformance
versioning
```
