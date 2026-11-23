# Forecasts with calibrated intervals. Otwin calibrates. Julia supplies the
# forecaster, which can be an Otwin model, a ModelingToolkit model or any
# function `f(history::Vector{Float64}, horizon::Int) -> Vector{Float64}`.

"""
A Julia forecaster `f(history, horizon) -> Vector` as a Python callable with
Otwin's leakage-free signature. Python passes a NumPy history and an int. The
Julia function receives a `Vector{Float64}` and an `Int`.
"""
function _pyforecaster(f)
    return pyfunc(
        (history, horizon) -> _pyvec(f(_vec(history), pyconvert(Int, horizon)));
        name = "julia_forecaster",
    )
end

"""
    rolling_origin_residuals(forecaster, series; step = 5, min_train = nothing, max_horizon = nothing)
        -> (residuals = Vector{Float64}, horizons = Vector{Int})

Out-of-sample forecast errors for calibration. At each origin inside `series`,
`forecaster(series[1:origin], horizon)` is asked for the next steps, and its
error (observed − forecast) is recorded with its horizon. The forecaster must
not keep anything from earlier calls. See Python's
`otwin.forecast.rolling_origin_residuals` for why in-sample residuals are not
a substitute.
"""
function rolling_origin_residuals(
    forecaster,
    series::AbstractVector{<:Real};
    step::Integer = 5,
    min_train::Union{Nothing,Integer} = nothing,
    max_horizon::Union{Nothing,Integer} = nothing,
)
    py = pyimport("otwin.forecast")
    res, hor = py.rolling_origin_residuals(
        _pyforecaster(forecaster),
        _pyvec(series);
        step = step,
        min_train = min_train,
        max_horizon = max_horizon,
    )
    return (residuals = _vec(res), horizons = _ivec(hor))
end

"""
    Band

A calibrated forecast interval: a half-width per horizon step (or one for all
steps), the level it was calibrated at, and how many residuals it rests on.
`extrapolated[h]` is `true` at steps no calibration residual reached.
"""
struct Band
    half_width::Vector{Float64}
    level::Float64
    method::String
    n_calibration::Int
    extrapolated::Vector{Bool}
    py::Py
end

function Base.show(io::IO, b::Band)
    n = length(b.half_width)
    print(io, "Otwin.Band(", b.method, ", level ", b.level, ", ", n, n == 1 ? " step" : " steps",
        ", ", b.n_calibration, " residuals")
    k = count(b.extrapolated)
    k > 0 && print(io, ", ", k, " extrapolated")
    print(io, ")")
end

"""
    calibrate(residuals, horizons; level, method = :horizon, max_horizon = nothing) -> Band

A conformal band from out-of-sample residuals, such as those from
[`rolling_origin_residuals`](@ref).

- `method = :horizon` (the default) widens with the horizon, using Python's
  `horizon_conformal`. `max_horizon` extends it beyond the calibrated range,
  and those steps are flagged in `extrapolated`.
- `method = :split` gives one half-width for every step, using
  `split_conformal`.

With too few residuals for `level`, the half-width is `Inf`, not a narrow
number.
"""
function calibrate(
    residuals::AbstractVector{<:Real},
    horizons::AbstractVector{<:Integer};
    level::Real,
    method::Symbol = :horizon,
    max_horizon::Union{Nothing,Integer} = nothing,
)
    py = pyimport("otwin.forecast")
    b = if method === :horizon
        py.horizon_conformal(
            _pyvec(residuals), _np.array(collect(Int, horizons));
            level = Float64(level), max_horizon = max_horizon,
        )
    elseif method === :split
        py.split_conformal(_pyvec(residuals); level = Float64(level))
    else
        throw(ArgumentError("method must be :horizon or :split, got :$method"))
    end
    return _band(b)
end

_band(b::Py) = Band(
    _vec(b.half_width),
    pyconvert(Float64, b.level),
    pyconvert(String, b.method),
    pyconvert(Int, b.n_calibration),
    _bvec(b.extrapolated),
    b,
)

"""
    interval(band, prediction) -> (prediction, lower, upper)

The band around a point forecast, computed by Otwin's `ConformalBand.apply`.
"""
function interval(band::Band, prediction::AbstractVector{<:Real})
    lo, up = band.py.apply(_pyvec(prediction))
    return (prediction = collect(Float64, prediction), lower = _vec(lo), upper = _vec(up))
end

"""
    forecast(forecaster, history, horizon, band) -> (prediction, lower, upper, extrapolated)

Forecast `horizon` steps after `history` and put the calibrated band around the
forecast. `extrapolated[h]` is `true` where the band is a model of the
interval rather than a measurement of it.
"""
function forecast(forecaster, history::AbstractVector{<:Real}, horizon::Integer, band::Band)
    pred = collect(Float64, forecaster(collect(Float64, history), Int(horizon)))
    length(pred) == horizon || throw(ArgumentError(
        "the forecaster returned $(length(pred)) steps for a horizon of $horizon"))
    iv = interval(band, pred)
    flags = length(band.extrapolated) >= horizon ? band.extrapolated[1:horizon] :
        fill(false, horizon)
    return (; iv..., extrapolated = flags)
end
