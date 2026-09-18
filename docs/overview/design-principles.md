# Design principles

Six rules decided most of what this library looks like. They are written down
because they also explain the things Otwin refuses to do.

## 1. Physics is structure, not decoration

If a physical relationship is known, it is encoded explicitly and it stays in the
model. Conservation at a node, energy stored in a store, power leaving through a
resistance: these are properties of the compiled equations, not of the solver
settings or of how well the model was fitted. A guarantee that follows from the form
of a model holds at every parameter value, including the ones you have not tried.

## 2. Components compose

A model is built from parts that can be joined without knowing anything about each
other. A composite device is made of the same primitives, with nothing special-cased
inside it, so a battery or a motor is readable as the components an engineer would
draw. The compiler flattens composites before it does anything else. That is what
makes a device you write yourself indistinguishable from one shipped with the
library.

## 3. Physical meaning is explicit

Every port declares its domain and therefore what its two variables are. Every
parameter declares a unit and a validity rule. Every connection means the same thing
in every domain: shared across variable, through variables summing to zero. Nothing
is inferred from a name or from context, so a nonsensical topology is caught at
compile time and reported in the language of the drawing.

## 4. The specification is independent of the implementation

What an Otwin model means is written down in a separate document with its own
version, in a separate repository, in normative language. This Python package is a
reference implementation of that document. Where the two disagree, the document is
right and the code has a bug. See [The specification](../specification/index.md).

## 5. Conformance is executable

A specification nobody can run is a wish. The conformance suite is a set of physical
fixtures with closed-form answers plus the structural and thermodynamic checks that
go with them, run against an implementation as a subprocess in any language. The
suite ships deliberately broken implementations and asserts that each one is caught
by the check meant to catch it. See [Conformance](../specification/conformance.md).

## 6. A model must expose the limits of what it knows

An interval means nothing until its coverage has been measured on held-out data. A
forecast horizon that was validated to sixty steps has not been validated to a
hundred and eighty. A parameter the data could not determine is a parameter chosen
by the noise. Otwin records all three in the twin's manifest and lets a twin refuse
a question that falls outside them, with the boundary that was crossed named in the
answer.

A refusal is not a failure. It is the difference between a calibrated instrument and
a confident one. See [Validity envelopes](../digital-twins/envelopes.md).
