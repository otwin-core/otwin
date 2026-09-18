# Compatibility and versioning

Three things in this project have version numbers, and they move for different
reasons. Keeping them apart is what lets an implementation be judged against a
contract rather than against whatever the last release happened to do.

```text
Otwin specification          what a model means, and what an implementation must do
        │
        ├── Python implementation      this package, otwin
        │        └── engine            the compiled runtime, otwin-engine
        │
        └── other conformant implementations
```

## What each number covers

**The specification** uses `MAJOR.MINOR`.

A **minor** release adds fixtures, loosens a tolerance or adds an optional field. An
implementation that was conformant stays conformant. A **major** release changes a
required interface, tightens a tolerance or makes a manifest field required.
Implementations may need work.

**An implementation** has its own version and its own release cadence. This package
follows semantic versioning. The version in the git tag and the version on PyPI are
the same number, always.

**The engine** is distributed as a separate wheel, `otwin-engine`, because it is a
compiled binary with platform wheels while the framework is pure Python. It is
released alongside the framework it belongs to. Both backends execute the same
lowered representation, so a model compiled by one version of the framework is
executed identically with or without the wheel present.

## What conformance is claimed against

A conformance result is always a statement about a pair: an implementation version
and a specification version. The suite prints both.

```text
  otwin conformance suite v0.1.0
  implementation: python (reference)
```

Saying that an implementation is conformant without naming the specification version
it was tested against is saying very little, which is why the runner writes both
into its report and into the badge payload.

## What a model file carries

A saved model and a saved twin manifest both record the version that produced them.
{class}`~otwin.interfaces.Provenance` on a manifest carries the creation timestamp
and the version, so a prediction found in an archive can be traced to the code that
made it.

A manifest may also contain fields a newer specification added. A reader built
against an older version preserves them rather than dropping them, so a round-trip
through an old reader is lossless. That rule is in the schema, not in this package,
which is the point of having the schema.

## Versions in use now

| | Version |
|---|---|
| Specification | 1.0, draft |
| Conformance suite (`otwin-spec`) | 0.1.0 |
| Framework (`otwin`) | see the [changelog](../reference/changelog.md) |
| Engine (`otwin-engine`) | released with the framework |

The framework version is deliberately not repeated on this page. One number in one
place is the whole reason the documentation build reads it from the installed
package instead.
