# The twin manifest

A prediction is worth what the evidence behind it is worth. The manifest is where
that evidence is written down, in a form another program can read.

{class}`~otwin.interfaces.TwinManifest` is a portable description of a fitted twin:
what the model is, what its parameters are, which of them came from data, how it was
validated, how its intervals were calibrated, and which fitted parameters the data
could actually determine. It is what
{class}`~otwin.advise.Envelope` reads when it decides whether the twin may answer,
and it is the file you keep when the twin outlives the session that built it.

## What it records

| Field | What it holds |
|---|---|
| `name`, `model_class`, `model_kind` | which asset, which structure, which model |
| `n_states`, `n_inputs` | the shape of the model |
| `parameters` | every parameter value |
| `estimated` | the names of the parameters that came from data |
| `validation` | the protocol, the horizon, and whether it was leakage-free |
| `calibration` | the method and the **measured** coverage |
| `identification` | per parameter, whether the data determined it |
| `provenance` | when it was created, with which version, and from what |

The white-box and grey-box distinction is exactly the `estimated` list. Empty means
every number came from first principles.

## Building one

A compiled model starts the record for you.

```{code-block} python
manifest = model.manifest("pump-3A")
```

The three evidence fields are built by their own constructors rather than written by
hand, because each of them has one key that decides everything and getting its name
wrong produces a manifest that looks complete and is refused.

```{code-block} python
from otwin.interfaces import TwinManifest

TwinManifest.validated_by("rolling_origin", horizon=60)
TwinManifest.calibrated_by("horizon_conformal", level=0.9, empirical_coverage=0.91)
TwinManifest.identified_by("collinearity+bootstrap", parameters=report.verdicts)
```

The three keys that matter are `leakage_free` in the validation record,
`empirical_coverage` in the calibration record, and `parameters` in the
identification record.

`leakage_free` is **derived** from the protocol rather than asserted by the caller.
A random split cannot be recorded as leakage-free by writing it down.
`empirical_coverage` is the coverage measured on held-out data, not the nominal
level, and the builder rejects a percentage where a fraction belongs. See
[Validation](validation.md), [Uncertainty](uncertainty.md) and
[Identifiability](identifiability.md) for where each of those numbers comes from.

## Reading it back

```{code-block} python
manifest.is_white_box      # nothing was estimated from data
manifest.is_validated      # a leakage-free protocol is on record
manifest.is_identified     # every estimated parameter is recorded as determined

manifest.save("pump-3A.twin.json")
TwinManifest.load("pump-3A.twin.json")
```

`is_validated` and `is_identified` are strict. A parameter listed in `estimated`
with no identification verdict counts as not identified, because *not yet checked*
is not the same as *fine*.

## Why the format is fussy

The manifest is defined by a JSON Schema in the specification rather than by this
package, because a twin fitted in Python may be read in Julia or in MATLAB. Three
rules in that schema exist because each one has already caused, or would cause, a
silent failure at a language boundary.

**No `NaN` and no `Infinity`.** They are not valid JSON. Python writes them anyway
as bare tokens, and the JSON readers of Julia and MATLAB reject them. A diverged fit
has to fail where it was written, not months later in another language.

**Timestamps are `YYYY-MM-DDTHH:MM:SSZ`.** Julia cannot parse an offset without an
extra package and MATLAB needs an explicit format for microseconds.

**`leakage_free` is a real boolean.** Both other languages will round-trip a boolean
to `1`, `0` or a string under some configurations, and the field that certifies
leakage-free validation must not accept those.

The normative definition is [section 4 of the
specification](https://github.com/otwin-core/otwin-spec/blob/main/spec/SPECIFICATION.md),
and the schema itself is `twin-manifest-1.0.json` in that repository. The
conformance suite has a fixture, `manifest_roundtrip`, that checks a writer against
all three rules. See [Conformance](../specification/conformance.md).
