# Margin risk: `otwin.audit`

A reference curve is what the asset is expected to deliver: a pump curve, a
rated capacity, a contracted power, or the model's own forecast. Promising a
*margin* `m` above it means promising at least `reference + m`. The question is
how often that promise breaks.

{func}`~otwin.audit.margin.margin_risk` answers it from the residuals alone,
`residual = delivered - reference`. It fits no normal distribution and no tail
model. A margin is not delivered when the residual falls below it, so the
probability of that is the share of residuals below the margin.

```{code-block} python
from otwin.audit import margin_risk

risk = margin_risk(residuals, reference=rated_curve, margins=[0.0, 0.5, 1.0])
if risk:
    risk.probabilities      # P(not delivering) for each margin
    risk.n_residuals        # how many residuals each probability rests on
    risk.margin_at_risk     # the margin at 5, 10 and 20 % risk
    risk.promised(0.05)     # rated_curve + the 5 % margin
else:
    print(risk.refusal)     # "12 residuals; at least 19 are needed for a margin at 5 % risk"
```

## The margin at a stated risk

The margin returned at risk `α` is the `⌊α(n+1)⌋`-th smallest residual. It is
not the plain `α`-quantile of the sample. For exchangeable residuals, the next
residual falls below it with probability at most `α`. The plain sample quantile
falls short of that by about one residual in `n + 1`. The margin also agrees
with the table: feeding it back in gives a probability no larger than `α`.

A negative margin at a risk means the asset falls short of the reference
curve itself more often than that.

## The refusal

Below `⌈1/α⌉ − 1` residuals, 19 at 5 %, no order statistic carries that
guarantee. The sample minimum is still a number, and returning it is the
silent failure this module avoids. The result then has
{attr}`~otwin.audit.margin.MarginRisk.refusal` set to a sentence with the count
and the requirement. All of its numeric fields are `None`. A `min_residuals`
you state is honoured when it is larger. When it is smaller, it is raised to
that floor.

## In a report

{meth}`~otwin.audit.margin.MarginRisk.to_dict` gives the JSON section and
{meth}`~otwin.audit.margin.MarginRisk.to_html` gives a self-contained
`<section>` with no styles or scripts. A report includes the section only when
a reference curve is given.
