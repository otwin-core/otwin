"""
    Otwin

Julia interface to [Otwin](https://github.com/otwin-core/otwin). This package
wraps the Python implementation through PythonCall and computes nothing itself.
Every simulation, fit, calibration and audit runs in Python's `otwin`. This
package converts Julia values in and out:

- `Vector{Float64}` for series;
- `Dict{String,…}` for anything keyed by a model name such as `"tank.level"`;
- `NamedTuple` for small results and column tables;
- small structs whose fields are `nothing` where Otwin refused to give a number.

DataFrames is optional. With it loaded, `DataFrame(x)` works on every audit
result.

CondaPkg installs the Python side the first time the package is loaded.
"""
module Otwin

using PythonCall
using Printf: @printf, @sprintf

export Model, Trajectory, FitResult, Band, CoverageRow, CoverageAudit, MarginRisk,
    TransferValidation
export components, system, connect!, chain, compile, load_model, save_model,
    parameters, parameter_names, state_names, input_names, output_names,
    with_parameters, simulate, fit_parameters
export rolling_origin_residuals, calibrate, interval, forecast
export coverage_audit, margin_risk, transfer_validation, answered, table, to_html,
    to_json, otwin_version

const _otwin = PythonCall.pynew()
const _np = PythonCall.pynew()
const _json = PythonCall.pynew()

function __init__()
    PythonCall.pycopy!(_otwin, pyimport("otwin"))
    PythonCall.pycopy!(_np, pyimport("numpy"))
    PythonCall.pycopy!(_json, pyimport("json"))
    return nothing
end

"""
    otwin_version() -> String

The version of the Python `otwin` this package is talking to.
"""
otwin_version() = pyconvert(String, _otwin.__version__)

"""
    _require(module, what)

Import a Python submodule. If it is missing, raise an error that names the
installed version and the feature that needs a newer one.
"""
function _require(mod::AbstractString, what::AbstractString)
    try
        return pyimport(mod)
    catch err
        err isa PyException || rethrow()
        error(
            "$what needs the Python module `$mod`, which otwin $(otwin_version()) does not " *
            "have. It is in otwin releases after 2.0.1. Upgrade the Python side, or point " *
            "JULIA_PYTHONCALL_EXE at a Python with a newer otwin (see the README).",
        )
    end
end

# ---------------------------------------------------------------- conversion
# Only conversion lives here. No arithmetic is done on the values.

"A Julia vector as a fresh NumPy float array, so Python never holds a view into Julia memory."
_pyvec(x::AbstractVector{<:Real}) = _np.array(collect(Float64, x))
_pyvec(x::Real) = Float64(x)
_pyvec(::Nothing) = nothing

"A NumPy array (or anything array-like) as a `Vector{Float64}`."
_vec(x::Py) = pyconvert(Vector{Float64}, _np.asarray(x; dtype = "float64").ravel())
_ivec(x::Py) = pyconvert(Vector{Int}, _np.asarray(x; dtype = "int64").ravel())
_bvec(x::Py) = pyconvert(Vector{Bool}, _np.asarray(x; dtype = "bool").ravel())

"`true` if `x` is Python's `None`."
_isnone(x::Py) = pyis(x, pybuiltins.None)

"A Python value as `T`, or `nothing` if it is `None`."
_opt(x::Py, ::Type{T}) where {T} = _isnone(x) ? nothing : pyconvert(T, x)

"A Python sequence of floats as a `Vector{Float64}`, or `nothing` if it is `None`."
_optvec(x::Py) = _isnone(x) ? nothing : _vec(x)

"""
A Julia function of time as a Python callable `f(t) -> float`.

The signature is stated explicitly. Otwin counts positional parameters to tell
an input `f(t)` from a feedback law `f(t, x)`, and a bare `pyfunc` exposes
`(*args, **kwargs)`, which Otwin reads as the feedback law.
"""
function _pyfun_t(f)
    inspect = pyimport("inspect")
    sig = inspect.Signature(pylist([inspect.Parameter("t", inspect.Parameter.POSITIONAL_ONLY)]))
    return pyfunc(t -> Float64(f(pyconvert(Float64, t))); name = "julia_input", signature = sig)
end

_pyval(v::Real) = Float64(v)
_pyval(v::AbstractVector{<:Real}) = _pyvec(v)
_pyval(v::Function) = _pyfun_t(v)
_pyval(v::Py) = v

"A `Dict`, `NamedTuple` or `Pair`s keyed by name, as a Python dict with converted values."
_pydict(::Nothing) = nothing
_pydict(d::AbstractDict) = pydict(Dict(String(string(k)) => _pyval(v) for (k, v) in d))
_pydict(d::NamedTuple) = _pydict(Dict(pairs(d)))
_pydict(p::Pair) = _pydict(Dict(p))
_pydict(ps::AbstractVector{<:Pair}) = _pydict(Dict(ps))

"A Python mapping of name to float as a `Dict{String,Float64}`."
_strfloat(d::Py) = Dict(pyconvert(String, k) => pyconvert(Float64, d[k]) for k in d)

"A Python object as JSON-safe text, using Python's `json`."
_json_text(d::Py) = pyconvert(String, _json.dumps(d; allow_nan = false, indent = 1))

include("model.jl")
include("forecast.jl")
include("audit.jl")

end # module
