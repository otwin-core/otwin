# Advise — `otwin.advise`

Four names. This is the smallest module in the package and the one that decides
whether anything upstream of it gets to be used.

The reasoning is in [Validity envelopes](../concepts/envelopes.md).

## The objects

{class}`~otwin.advise.Envelope`
: the range over which a twin has been shown to work — state bounds, maximum
  horizon, and whether validation and calibration are required.

{class}`~otwin.advise.Verdict`
: what the twin is willing to say, and why. Truthy when the question is
  answerable; carries `breaches` and `checked` either way.

{class}`~otwin.advise.Breach`
: one reason the request falls outside, naming the field, the value asked for
  and the value validated.

{class}`~otwin.advise.OutsideEnvelope`
: the same refusal as an exception, for call sites where a falsy return value
  would be easy to ignore.

## Using it

```{code-block} python
verdict = envelope.check(
    state=x, horizon=h, manifest=manifest, wants_interval=True,
)
if verdict:
    ...   # answer
else:
    for breach in verdict.breaches:
        log.warning("refused: %s", breach)
```

`requires_identified=True` on the envelope adds a fifth check: every estimated
parameter must be recorded as identified, or the refusal names the one that is
not. See [Identifiability](../concepts/identifiability.md).

`wants_interval=True` is what makes the calibration check apply. Asking for a
point forecast and asking for a band are different questions with different
evidence requirements, and the envelope treats them that way.

## Reading `checked`

{attr}`~otwin.advise.Verdict.checked` lists what was actually examined. It
matters because a passing verdict from an envelope that checked nothing is not
the same as a passing verdict from one that checked four things — and without
this field the two are indistinguishable in a log.

## The failure this exists to prevent

A confident number, produced far outside anything that was ever tested, with
nothing in the output to indicate it. Every other block in this library produces
evidence; this one is what makes the absence of evidence *visible*.

An absent record is a refusal, not a pass. That includes an absent envelope: a
twin with no `state_bounds` does not get a clean verdict for a state of charge
of $10^{12}$.
