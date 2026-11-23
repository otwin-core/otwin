# The storage tank of water_tank.jl, written a second time in ModelingToolkit
# and simulated with OrdinaryDiffEq. Otwin.jl then audits the forecasts of both
# models in the same way.
#
# Run from julia/Otwin.jl (the first run compiles ModelingToolkit, which takes
# several minutes):
#     julia --project=examples examples/mtk_comparison.jl
#
# There are three steps. The two models are the same physics, which is checked
# by running both. The ModelingToolkit model takes the discharge coefficient
# that Otwin fitted. The audit uses only forecasts and readings, so it does not
# depend on which tool made the forecast. Otwin calibrates and audits.
# ModelingToolkit and OrdinaryDiffEq simulate their own model.

using Otwin: Otwin
using ModelingToolkit, OrdinaryDiffEq
using ModelingToolkit: t_nounits as t, D_nounits as D
using DataFrames: DataFrame, select
using Printf: @printf
using Random: Xoshiro, randn

const AREA = 20.0                  # m²
const DT = 600.0                   # s, one reading every ten minutes
const DAY = 144
const H = 36                       # six hours

# The same schedules as water_tank.jl, written so ModelingToolkit can trace them.
pump_flow(τ) = 0.0075 * (1 + 0.5 * sin(2π * τ / 86400))
town_demand(τ) = 0.0005 * (1 + sin(2π * τ / (3.7 * 86400)))

# --------------------------------------------------- the tank in ModelingToolkit
# `town` switches the town's draw on (1) or off (0). The real tank has it. The
# operator's model, like the Otwin one, does not.
@parameters area = AREA outlet_area = 0.002 Cd = 0.60 g = 9.81 town = 0.0
@variables level(t) = 2.0
eqs = [D(level) ~ (pump_flow(t) - town * town_demand(t) -
                   Cd * outlet_area * sqrt(2g * level)) / area]
@mtkcompile tank = System(eqs, t)

# The real tank, for the readings: outlet at 0.63, the town drawing, 5 mm noise.
times = collect(0:(8DAY - 1)) .* DT
real = ODEProblem(tank, [tank.Cd => 0.63, tank.town => 1.0], (0.0, times[end]))
level_true = solve(real, Tsit5(); saveat = times, abstol = 1e-10, reltol = 1e-10)[tank.level]
reading = level_true .+ 0.005 .* randn(Xoshiro(2), length(times))

# ------------------------------------------------------------ the tank in Otwin
hyd = Otwin.components(:hydraulic)
otank = hyd.Tank(AREA; level = 2.0, name = "tank")
outlet = hyd.Orifice(0.002; discharge_coefficient = 0.60, name = "outlet")
pump = hyd.FlowSource(; name = "pump")
air = hyd.Atmosphere(; name = "air")
sys = Otwin.system(otank, outlet, pump, air)
Otwin.connect!(sys, otank.port, outlet.a, pump.a)
Otwin.connect!(sys, outlet.b, pump.b, air.port)
model = Otwin.compile(sys)

# Otwin fits the outlet to the first two days of readings.
fit = Otwin.fit_parameters(
    model, times[1:2DAY], "tank.level" => reading[1:2DAY], ["outlet.discharge_coefficient"];
    inputs = Dict("pump" => pump_flow), x0 = Dict("tank.volume" => AREA * reading[1]),
)
cd = fit.values["outlet.discharge_coefficient"]
println(fit)

# ModelingToolkit takes the same value.
mtk_model = ODEProblem(tank, [tank.Cd => cd, tank.town => 0.0], (0.0, DT))

# ------------------------------------------------- step 1: the same physics?
# One day from 2 m with the pump schedule, both models, on a one-minute grid.
fine = collect(0.0:60.0:86400.0)
a = Otwin.simulate(fit.model, fine; x0 = Dict("tank.volume" => AREA * 2.0),
                   inputs = Dict("pump" => pump_flow), solver = "rk45", interp = "linear")["tank.level"]
b = solve(remake(mtk_model; u0 = [tank.level => 2.0], tspan = (0.0, 86400.0)), Tsit5();
          saveat = fine, abstol = 1e-10, reltol = 1e-10)[tank.level]
@printf("\nstep 1: over one day the two models differ by at most %.2g m (level %.2f to %.2f m)\n\n",
        maximum(abs.(a .- b)), minimum(b), maximum(b))

# ------------------------------------------------------------ two forecasters
# Each starts from the last reading and runs the pump schedule forward.
function otwin_forecast(history, horizon)
    k = length(history)
    tr = Otwin.simulate(fit.model, times[k:(k + horizon)];
                        x0 = Dict("tank.volume" => AREA * history[end]),
                        inputs = Dict("pump" => pump_flow))
    return tr["tank.level"][2:end]
end

function mtk_forecast(history, horizon)
    t0 = times[length(history)]
    p = remake(mtk_model; u0 = [tank.level => history[end]], tspan = (t0, t0 + horizon * DT))
    return solve(p, Tsit5(); saveat = (t0 + DT):DT:(t0 + horizon * DT))[tank.level]
end

# ------------------------------------------------------ step 2: the audit
# The two coverages are close, but not equal, even though the physics agree to
# micrometres. The forecasters differ in one way: Otwin's holds the pump flow
# constant over each ten-minute step, while ModelingToolkit follows the
# continuous schedule. The audit sees the forecasts, so it reports that
# difference too.
"Calibrate on days 1 to 5, then audit the range on days 6 to 8, by horizon."
function audit(forecaster)
    cal = Otwin.rolling_origin_residuals(forecaster, reading[1:5DAY];
                                         step = 6, min_train = DAY, max_horizon = H)
    band = Otwin.calibrate(cal.residuals, cal.horizons; level = 0.9, max_horizon = H)
    obs, pred, lo, up, hor = Float64[], Float64[], Float64[], Float64[], Int[]
    for k in (5DAY):6:(length(times) - H)
        f = Otwin.forecast(forecaster, reading[1:k], H, band)
        append!(obs, reading[(k + 1):(k + H)])
        append!(pred, f.prediction)
        append!(lo, f.lower)
        append!(up, f.upper)
        append!(hor, 1:H)
    end
    return Otwin.coverage_audit(obs, pred, lo, up;
                                level = 0.9, horizons = hor, tranches = [0, 6, 18, 36])
end

by_otwin = audit(otwin_forecast)
by_mtk = audit(mtk_forecast)

println("step 2: the same audit on both models (stated 90 %)")
o, m = DataFrame(by_otwin), DataFrame(by_mtk)       # needs DataFrames, optional
shown(x) = round(x; digits = 3)
table = select(o, :label => :horizon, :n_contrasts => :contrasts)
table.otwin_coverage = shown.(o.coverage)
table.mtk_coverage = shown.(m.coverage)
table.otwin_bias_m = shown.(o.median_error)
table.mtk_bias_m = shown.(m.median_error)
table.mtk_verdict = m.verdict
show(stdout, MIME"text/plain"(), table; allrows = true, eltypes = false, summary = false)
println()
