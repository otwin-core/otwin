# The audit: coverage by horizon, margin risk, and leave-one-unit-out transfer.
# Refusals stay refusals. A field Otwin left empty is `nothing` in the struct
# and `missing` in a table, never zero.

"""
    CoverageRow

One row of a coverage audit: every contrast (`label == "all"`) or one horizon
tranche `(lo, hi]`. When `refusal` is set, every numeric field except
`n_contrasts` and `n_required` is `nothing`.
"""
struct CoverageRow
    label::String
    lo::Union{Nothing,Float64}
    hi::Union{Nothing,Float64}
    n_contrasts::Int
    n_required::Int
    n_covered::Union{Nothing,Int}
    coverage::Union{Nothing,Float64}
    ci_low::Union{Nothing,Float64}
    ci_high::Union{Nothing,Float64}
    median_error::Union{Nothing,Float64}
    mean_width::Union{Nothing,Float64}
    verdict::Union{Nothing,String}
    refusal::Union{Nothing,String}
end

_row(r::Py) = CoverageRow(
    pyconvert(String, r.label),
    _opt(r.lo, Float64), _opt(r.hi, Float64),
    pyconvert(Int, r.n_contrasts), pyconvert(Int, r.n_required),
    _opt(r.n_covered, Int), _opt(r.coverage, Float64),
    _opt(r.ci_low, Float64), _opt(r.ci_high, Float64),
    _opt(r.median_error, Float64), _opt(r.mean_width, Float64),
    _opt(r.verdict, String), _opt(r.refusal, String),
)

"""
    CoverageAudit

What [`coverage_audit`](@ref) returns: `overall`, and `tranches` (a
`Vector{CoverageRow}`) when tranches were asked for, else `nothing`.
`n_outside` counts contrasts that fall in no tranche.
"""
struct CoverageAudit
    level::Float64
    confidence::Float64
    min_contrasts::Int
    overall::CoverageRow
    tranches::Union{Nothing,Vector{CoverageRow}}
    boundaries::Union{Nothing,Vector{Float64}}
    n_outside::Union{Nothing,Int}
    py::Py
end

_coverage(a::Py) = CoverageAudit(
    pyconvert(Float64, a.level),
    pyconvert(Float64, a.confidence),
    pyconvert(Int, a.min_contrasts),
    _row(a.overall),
    _isnone(a.tranches) ? nothing : [_row(r) for r in a.tranches],
    _optvec(a.boundaries),
    _opt(a.n_outside, Int),
    a,
)

"""
    coverage_audit(observed, prediction, lower, upper; level, horizons = nothing,
                   tranches = nothing, min_contrasts = nothing, confidence = 0.95) -> CoverageAudit

Whether a forecast range holds the coverage it states. Each row gives the
observed coverage with a Clopper-Pearson interval, the median signed error
(bias), the mean width and the number of contrasts. By default the report is
one row. Pass `horizons` and `tranches = [0, 6, 18, 36]` for one row per
horizon tranche. A row with fewer contrasts than `min_contrasts` is refused,
and the refusal names the count.

Computed by Python's `otwin.audit.coverage_audit`.
"""
function coverage_audit(
    observed::AbstractVector{<:Real},
    prediction::AbstractVector{<:Real},
    lower::AbstractVector{<:Real},
    upper::AbstractVector{<:Real};
    level::Real,
    horizons::Union{Nothing,AbstractVector{<:Real}} = nothing,
    tranches::Union{Nothing,AbstractVector{<:Real}} = nothing,
    min_contrasts::Union{Nothing,Integer} = nothing,
    confidence::Real = 0.95,
)
    audit = _require("otwin.audit", "coverage_audit")
    a = audit.coverage_audit(
        _pyvec(observed), _pyvec(prediction), _pyvec(lower), _pyvec(upper);
        level = Float64(level),
        horizons = _pyvec(horizons),
        tranches = tranches === nothing ? nothing : pylist(Float64.(tranches)),
        min_contrasts = min_contrasts,
        confidence = Float64(confidence),
    )
    return _coverage(a)
end

"""
    MarginRisk

What [`margin_risk`](@ref) returns. If `refusal` is set, `probabilities`,
`n_residuals`, `n_short` and `margin_at_risk` are `nothing`.
"""
struct MarginRisk
    reference::Vector{Float64}
    margins::Vector{Float64}
    risk_levels::Vector{Float64}
    n_available::Int
    n_required::Int
    probabilities::Union{Nothing,Vector{Float64}}
    n_residuals::Union{Nothing,Vector{Int}}
    n_short::Union{Nothing,Vector{Int}}
    margin_at_risk::Union{Nothing,Vector{Float64}}
    refusal::Union{Nothing,String}
    py::Py
end

"""
    margin_risk(residuals, reference, margins; risk_levels = [0.05, 0.10, 0.20],
                min_residuals = nothing) -> MarginRisk

For each margin above the reference curve, the probability of not delivering
it. This is the share of residuals (delivered − reference) below the margin,
with no distribution assumed. The result also gives the margin that can be
promised at each risk level. Too few residuals give a refusal that names the
count.

Computed by Python's `otwin.audit.margin_risk`.
"""
function margin_risk(
    residuals::AbstractVector{<:Real},
    reference,
    margins::AbstractVector{<:Real};
    risk_levels::AbstractVector{<:Real} = [0.05, 0.10, 0.20],
    min_residuals::Union{Nothing,Integer} = nothing,
)
    audit = _require("otwin.audit", "margin_risk")
    r = audit.margin_risk(
        _pyvec(residuals), _pyvec(reference), _pyvec(margins);
        risk_levels = pylist(Float64.(risk_levels)),
        min_residuals = min_residuals,
    )
    optint(x) = _isnone(x) ? nothing : _ivec(x)
    return MarginRisk(
        _vec(r.reference), _vec(r.margins),
        pyconvert(Vector{Float64}, pylist(r.risk_levels)),
        pyconvert(Int, r.n_available), pyconvert(Int, r.n_required),
        _optvec(r.probabilities), optint(r.n_residuals), optint(r.n_short),
        _optvec(r.margin_at_risk), _opt(r.refusal, String),
        r,
    )
end

"""
    TransferValidation

What [`transfer_validation`](@ref) returns.

- `contrasts`: a column table (`NamedTuple` of vectors) with one row per
  contrast. The columns are `unit`, `origin`, `horizon`, `observed`,
  `prediction`, `lower`, `upper`, `error` and `covered`.
- `audit`: the coverage audit on those contrasts, by horizon tranche.
- `overall_coverage`, `tranche_coverage`, `median_bias`: the summary.
  `nothing` where Otwin refused.
- `calibration_units`: for each held-out unit, the units it was calibrated on.
"""
struct TransferValidation
    contrasts::NamedTuple
    audit::CoverageAudit
    overall_coverage::Union{Nothing,Float64}
    tranche_coverage::Vector{Pair{String,Union{Nothing,Float64}}}
    median_bias::Union{Nothing,Float64}
    calibration_units::Dict{Any,Vector{Any}}
    n_contrasts_per_unit::Dict{Any,Int}
    py::Py
end

"Python mapping of unit id to calibration series, as a Julia `Dict`."
_units_from_py(cal::Py) = Dict{Any,Vector{Float64}}(pyconvert(Any, k) => _vec(cal[k]) for k in cal)

"A Julia `fit(units) -> forecaster` as the Python callable `transfer_validation` expects."
function _pyfit(fit)
    return pyfunc(
        cal -> begin
            forecaster = fit(_units_from_py(cal))
            pyfunc(
                (history, horizon) -> begin
                    p, lo, up = forecaster(_vec(history), pyconvert(Int, horizon))
                    pytuple((_pyvec(p), _pyvec(lo), _pyvec(up)))
                end;
                name = "julia_unit_forecaster",
            )
        end;
        name = "julia_fit",
    )
end

_pyunits(units::AbstractDict) = pydict(Dict(k => _pyvec(v) for (k, v) in units))
_pyunits(units::AbstractVector{<:AbstractVector}) = pylist([_pyvec(v) for v in units])

"""
    transfer_validation(units, fit, horizon_levels; level, min_history = 1, step = 1,
                        min_contrasts = nothing, confidence = 0.95) -> TransferValidation

Leave-one-unit-out validation across a fleet. For each unit, Otwin calls
`fit(calibration_units)` with every other unit, as a `Dict` of id to
`Vector{Float64}`, and never the held-out one. `fit` returns
`forecaster(history, horizon) -> (prediction, lower, upper)`. Otwin then
forecasts the held-out unit from rolling origins along its own series and
records every contrast. `horizon_levels` are the tranche boundaries.

`units` is a `Dict` of id to series, or a vector of series, in which case the
ids are `0, 1, …`. The units run one after another.

Computed by Python's `otwin.forecast.transfer_validation`. It checks on every
fold that no unit is in its own calibration set.
"""
function transfer_validation(
    units,
    fit,
    horizon_levels::AbstractVector{<:Real};
    level::Real,
    min_history::Integer = 1,
    step::Integer = 1,
    min_contrasts::Union{Nothing,Integer} = nothing,
    confidence::Real = 0.95,
)
    mod = _require("otwin.forecast.transfer", "transfer_validation")
    tv = mod.transfer_validation(
        _pyunits(units), _pyfit(fit), pylist(Float64.(horizon_levels));
        level = Float64(level),
        min_history = min_history,
        step = step,
        min_contrasts = min_contrasts,
        confidence = Float64(confidence),
    )
    c = tv.contrasts
    contrasts = (
        unit = Any[pyconvert(Any, u) for u in c.unit],
        origin = _ivec(c.origin),
        horizon = _ivec(c.horizon),
        observed = _vec(c.observed),
        prediction = _vec(c.prediction),
        lower = _vec(c.lower),
        upper = _vec(c.upper),
        error = _vec(c.error),
        covered = _bvec(c.covered),
    )
    tc = Pair{String,Union{Nothing,Float64}}[
        pyconvert(String, k) => _opt(tv.tranche_coverage[k], Float64) for k in tv.tranche_coverage
    ]
    cal = Dict{Any,Vector{Any}}(
        pyconvert(Any, k) => Any[pyconvert(Any, u) for u in tv.calibration_units[k]]
        for k in tv.calibration_units
    )
    per = Dict{Any,Int}(pyconvert(Any, k) => pyconvert(Int, tv.n_contrasts_per_unit[k])
                        for k in tv.n_contrasts_per_unit)
    return TransferValidation(
        contrasts, _coverage(tv.audit),
        _opt(tv.overall_coverage, Float64), tc, _opt(tv.median_bias, Float64),
        cal, per, tv,
    )
end

# ------------------------------------------------------------- shared helpers

"""
    answered(x) -> Bool

`true` when Otwin gave numbers, `false` when it refused.
"""
answered(r::CoverageRow) = r.refusal === nothing
answered(m::MarginRisk) = m.refusal === nothing

"""
    to_html(x) -> String

The report section Otwin renders for `x`: a self-contained `<section>` with no
styles or scripts.
"""
to_html(x::Union{CoverageAudit,MarginRisk}) = pyconvert(String, x.py.to_html())
to_html(x::TransferValidation) = to_html(x.audit)

"""
    to_json(x) -> String

The JSON report section Otwin writes for `x`. Refused numbers are `null`.
"""
to_json(x::Union{CoverageAudit,MarginRisk,TransferValidation}) = _json_text(x.py.to_dict())

_m(x) = x === nothing ? missing : x

"""
    table(x) -> NamedTuple of vectors

A column table that `DataFrame(table(x))` or any Tables.jl consumer reads.
Refused numbers are `missing`.

- `CoverageAudit`: one row for the overall audit, plus one per tranche.
- `MarginRisk`: one row per margin.
- `TransferValidation`: the contrasts.
"""
function table(a::CoverageAudit)
    rows = vcat([a.overall], something(a.tranches, CoverageRow[]))
    col(f) = [_m(getfield(r, f)) for r in rows]
    return (
        label = [r.label for r in rows],
        n_contrasts = [r.n_contrasts for r in rows],
        n_covered = col(:n_covered),
        coverage = col(:coverage),
        ci_low = col(:ci_low),
        ci_high = col(:ci_high),
        median_error = col(:median_error),
        mean_width = col(:mean_width),
        verdict = col(:verdict),
        refusal = col(:refusal),
    )
end

function table(m::MarginRisk)
    n = length(m.margins)
    pick(v) = v === nothing ? fill(missing, n) : v
    return (
        margin = m.margins,
        probability = pick(m.probabilities),
        n_short = pick(m.n_short),
        n_residuals = pick(m.n_residuals),
    )
end

table(tv::TransferValidation) = tv.contrasts

# ------------------------------------------------------------------- display

_pct(x) = x === nothing ? "—" : @sprintf("%.1f %%", 100x)

function Base.show(io::IO, ::MIME"text/plain", a::CoverageAudit)
    println(io, "Otwin.CoverageAudit: stated ", _pct(a.level), ", interval at ", _pct(a.confidence))
    for r in vcat([a.overall], something(a.tranches, CoverageRow[]))
        if answered(r)
            @printf(io, "  %-10s %6d contrasts  coverage %s  [%s, %s]  bias %+.4g  width %.4g  %s\n",
                r.label, r.n_contrasts, _pct(r.coverage), _pct(r.ci_low), _pct(r.ci_high),
                r.median_error, r.mean_width, r.verdict)
        else
            @printf(io, "  %-10s %6d contrasts  not computed: %s\n", r.label, r.n_contrasts, r.refusal)
        end
    end
    a.n_outside !== nothing && a.n_outside > 0 &&
        println(io, "  ", a.n_outside, " contrasts fall in no tranche")
end

function Base.show(io::IO, ::MIME"text/plain", m::MarginRisk)
    println(io, "Otwin.MarginRisk: ", m.n_available, " residuals")
    if !answered(m)
        print(io, "  not computed: ", m.refusal)
        return
    end
    for (x, p, k) in zip(m.margins, m.probabilities, m.n_short)
        @printf(io, "  margin %+.4g: P(not delivered) %s  (%d of %d)\n", x, _pct(p), k, m.n_available)
    end
    for (r, x) in zip(m.risk_levels, m.margin_at_risk)
        @printf(io, "  margin at %s risk: %+.4g\n", _pct(r), x)
    end
end

function Base.show(io::IO, ::MIME"text/plain", tv::TransferValidation)
    println(io, "Otwin.TransferValidation: ", length(tv.calibration_units), " units, ",
        length(tv.contrasts.observed), " contrasts")
    show(io, MIME"text/plain"(), tv.audit)
end

for T in (CoverageAudit, MarginRisk, TransferValidation)
    @eval Base.show(io::IO, x::$T) = print(io, "Otwin.", $(string(nameof(T))), "(…)")
end
