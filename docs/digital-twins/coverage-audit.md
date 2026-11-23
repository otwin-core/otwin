# Coverage audit: `otwin.audit`

A forecast range states a coverage, for example 90 %.
{func}`~otwin.audit.coverage.coverage_audit` checks it against what happened.
The observations, point forecasts and ranges can come from Otwin or from any
other tool. For every row it reports:

- the number of contrasts, meaning observation-forecast pairs, behind it;
- the observed coverage, with a Clopper-Pearson confidence interval;
- the median signed error `observed - prediction`, the bias. Positive means
  the forecast runs low;
- the mean width of the range;
- a verdict: `consistent with stated`, `narrower than stated` or
  `wider than stated`. A range that covers more than it states is reported as
  wider than it needs to be, not as a success.

```{code-block} python
from otwin.audit import coverage_audit

audit = coverage_audit(observed, prediction, lower, upper, level=0.9)
audit.overall.coverage, audit.overall.ci_low, audit.overall.ci_high
```

## By horizon

By default the report is one overall row. A range calibrated on the average
horizon is often too wide early and too narrow late, and the overall number
hides that. Give the horizon of each contrast and a list of boundaries to see
each part:

```{code-block} python
audit = coverage_audit(
    observed, prediction, lower, upper, level=0.9,
    horizons=horizons, tranches=[0, 6, 12, 24],
)
for row in audit.tranches:          # (0, 6], (6, 12], (12, 24]
    print(row.label, row.n_contrasts, row.coverage if row.answered else row.refusal)
```

A tranche holds horizons `lo < h <= hi`. Contrasts that fall outside every
tranche count in the overall row only, and {attr}`~otwin.audit.coverage.CoverageAudit.n_outside`
says how many there are. The overall row is the same with tranches on or off.

## The refusal

A row with fewer contrasts than `min_contrasts` is refused, for example
`"7 contrasts; the minimum is 10"`. All of its numbers are `None`. This
applies to the overall row as well as to each tranche. The default minimum is
`ceil(1 / (1 - level))`, 10 at 90 %. That is the fewest contrasts at which a
range that holds its level exactly is expected to miss at least once. Below
it, 100 % coverage is the likeliest outcome whether the range is right or far
too wide. A minimum you give is used as given.

## What the interval does not cover

Clopper-Pearson treats the contrasts as independent. Contrasts from
overlapping rolling-origin forecasts are not independent: neighbouring
horizons from one origin share most of their error. The true uncertainty on
coverage is therefore wider than the interval shown. The report says so next
to the interval.

## In a report

{meth}`~otwin.audit.coverage.CoverageAudit.to_dict` gives the JSON section.
`tranches` is `null` when tranches are off, so the keys do not change.
{meth}`~otwin.audit.coverage.CoverageAudit.to_html` gives a self-contained
`<section>` with one table.
