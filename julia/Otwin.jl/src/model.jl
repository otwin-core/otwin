# Build, load, simulate and fit a model. Every call goes to Python's otwin.

"""
    components(domain::Symbol) -> Py

The Python module of Otwin components for `domain`. The domains are
`:hydraulic`, `:electrical`, `:mechanical`, `:rotational`, `:thermal`,
`:twoport`, `:battery`, `:composite` and `:fundamental`. Components are built
by calling them, with Python keyword arguments as Julia keywords:

```julia
hyd = Otwin.components(:hydraulic)
tank = hyd.Tank(20.0; level = 2.0, name = "tank")
```
"""
components(domain::Symbol) = pyimport("otwin.components.$(domain)")

"""
    system(parts...; name = "system") -> Py

An Otwin system holding the components `parts`. Join their ports with
[`connect!`](@ref).
"""
system(parts...; name::AbstractString = "system") = _otwin.System(parts...; name = name)

"""
    connect!(sys, ports...) -> sys

Join `ports` at one node of `sys`, as `sys.connect(ports...)` does in Python.
"""
function connect!(sys::Py, ports...)
    sys.connect(ports...)
    return sys
end

"""
    chain(parts...; name = "system") -> Py

Join `parts` in a line, as the `>>` operator does in Python.
"""
chain(parts...; name::AbstractString = "system") = _otwin.chain(parts...; name = name)

"""
    Model

A compiled Otwin model. The Python object is `m.py`, for anything this package
does not wrap.
"""
struct Model
    py::Py
end

Base.show(io::IO, m::Model) = print(io, "Otwin.Model(", pyconvert(String, pystr(m.py)), ")")

"""
    compile(sys; dt = nothing) -> Model

Compile a system built with [`system`](@ref) or [`chain`](@ref).
"""
compile(sys::Py; dt::Union{Nothing,Real} = nothing) = Model(_otwin.compile(sys; dt = dt))

"""
    load_model(path) -> Model

Load a model written by [`save_model`](@ref), or by `Model.save` in Python.
"""
load_model(path::AbstractString) = Model(_otwin.Model.load(path))

"""
    save_model(m, path) -> String

Write `m` as JSON to `path` and return the path.
"""
function save_model(m::Model, path::AbstractString)
    m.py.save(path)
    return String(path)
end

"Names of the model's parameters, states, inputs and outputs."
parameter_names(m::Model) = pyconvert(Vector{String}, pylist(m.py.param_names))
state_names(m::Model) = pyconvert(Vector{String}, pylist(m.py.state_names))
input_names(m::Model) = pyconvert(Vector{String}, pylist(m.py.input_names))
output_names(m::Model) = pyconvert(Vector{String}, pylist(m.py.output_names))
@doc "Names of the model's parameters." parameter_names
@doc "Names of the model's states." state_names
@doc "Names of the model's inputs." input_names
@doc "Names of the model's outputs." output_names

"""
    parameters(m) -> Dict{String,Float64}

The current value of every parameter.
"""
parameters(m::Model) = _strfloat(m.py.parameters)

"""
    with_parameters(m, "name" => value, ...) -> Model

A copy of `m` with the named parameters changed. `m` is left as it was.
"""
with_parameters(m::Model, changes::Pair...) = Model(m.py.with_parameters(_pydict(collect(changes))))

"""
    Trajectory

What [`simulate`](@ref) returns. `tr.t` holds the times. `tr["tank.level"]`
gives any state, input or output by name as a `Vector{Float64}`.
"""
struct Trajectory
    t::Vector{Float64}
    values::Dict{String,Vector{Float64}}
    py::Py
end

Base.getindex(tr::Trajectory, name::AbstractString) = tr.values[name]
Base.keys(tr::Trajectory) = keys(tr.values)
Base.show(io::IO, tr::Trajectory) = print(
    io, "Otwin.Trajectory(", length(tr.t), " points; ", join(sort!(collect(keys(tr.values))), ", "), ")",
)

"""
    simulate(m, t; x0 = nothing, inputs = nothing, solver = "midpoint", interp = "hold") -> Trajectory

Run `m` over the times `t`.

- `x0`: initial state, as `Dict("tank.volume" => 40.0)` or a vector in state
  order. The default is the initial conditions the components were given.
- `inputs`: per input name, a number, a vector over `t`, or a Julia function
  of time `f(t)`. For example `Dict("pump" => pump_flow)`.
- `solver`: `"midpoint"` (structure-preserving, the default), `"rk45"`,
  `"rk4"` or `"euler"`.
- `interp`: how inputs vary inside a step, `"hold"` (the default) or
  `"linear"`.
"""
function simulate(
    m::Model,
    t::AbstractVector{<:Real};
    x0 = nothing,
    inputs = nothing,
    solver::AbstractString = "midpoint",
    interp::AbstractString = "hold",
)
    tr = m.py.simulate(;
        t = _pyvec(t), x0 = _pyx0(x0), inputs = _pydict(inputs), solver = solver, interp = interp,
    )
    names = vcat(
        pyconvert(Vector{String}, pylist(tr.state_names)),
        pyconvert(Vector{String}, pylist(tr.input_names)),
        pyconvert(Vector{String}, pylist(tr.output_names)),
    )
    values = Dict(n => _vec(tr[n]) for n in unique(names))
    return Trajectory(_vec(tr.t), values, tr)
end

_pyx0(::Nothing) = nothing
_pyx0(x::AbstractVector{<:Real}) = _pyvec(x)
_pyx0(x) = _pydict(x)

"""
    FitResult

What [`fit_parameters`](@ref) returns.

- `values`: the fitted value of each parameter.
- `model`: a copy of the model with those values.
- `identified`: for each fitted parameter, whether the data determined it.
  `nothing` if the check was not run.
- `cost`, `success`, `message`, `n_evaluations`: from the optimiser.
"""
struct FitResult
    values::Dict{String,Float64}
    model::Model
    identified::Union{Nothing,Dict{String,Bool}}
    cost::Float64
    success::Bool
    message::String
    n_evaluations::Int
    py::Py
end

function Base.show(io::IO, f::FitResult)
    vals = join((@sprintf("%s = %.6g", k, v) for (k, v) in sort!(collect(f.values))), ", ")
    print(io, "Otwin.FitResult(", vals, "; cost ", @sprintf("%.4g", f.cost), ", ",
          f.n_evaluations, " evaluations")
    if f.identified !== nothing
        bad = sort!([k for (k, ok) in f.identified if !ok])
        print(io, isempty(bad) ? ", every parameter identified" :
                  ", not identified: " * join(bad, ", "))
    end
    print(io, f.success ? "" : ", optimiser did not converge: " * f.message, ")")
end

"""
    fit_parameters(m, t, measurements, parameters; inputs, x0, bounds, solver, check_identifiability) -> FitResult

Fit the named `parameters` of `m` so that its outputs match `measurements`
over the times `t`.

- `measurements`: `"tank.level" => y`, or a `Dict` of output name to vector.
- `parameters`: names, e.g. `["drain.discharge_coefficient"]`.
- `bounds`: `Dict(name => (low, high))`. Use `nothing` for an open side.
- `inputs`, `x0`, `solver`: as for [`simulate`](@ref).
"""
function fit_parameters(
    m::Model,
    t::AbstractVector{<:Real},
    measurements,
    parameters::AbstractVector{<:AbstractString};
    inputs = nothing,
    x0 = nothing,
    bounds = nothing,
    solver::AbstractString = "midpoint",
    check_identifiability::Bool = true,
)
    pybounds = bounds === nothing ? nothing :
        pydict(Dict(String(k) => pytuple((lo, hi)) for (k, (lo, hi)) in bounds))
    r = _otwin.fit_parameters(
        m.py,
        _pyvec(t),
        _pydict(measurements),
        pylist(String.(parameters));
        inputs = _pydict(inputs),
        x0 = _pyx0(x0),
        bounds = pybounds,
        solver = solver,
        check_identifiability = check_identifiability,
    )
    ident = _isnone(r.identifiability) ? nothing :
        Dict(pyconvert(String, k) => pyconvert(Bool, r.identifiability.verdicts[k])
             for k in r.identifiability.verdicts)
    return FitResult(
        _strfloat(r.values),
        Model(r.model),
        ident,
        pyconvert(Float64, r.cost),
        pyconvert(Bool, r.success),
        pyconvert(String, r.message),
        pyconvert(Int, r.n_evaluations),
        r,
    )
end
