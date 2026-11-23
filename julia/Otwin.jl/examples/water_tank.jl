# A storage tank fed by a pump and draining through an outlet. Build the model
# in Otwin, fit it to the level readings, forecast the next six hours with a
# calibrated 90 % range, and audit that range on days the model never saw.
#
# Run from julia/Otwin.jl:
#     julia --project=examples examples/water_tank.jl
#
# Every number below is computed by Python's otwin. Julia defines the plant,
# makes the readings, and prints.

using Otwin
using Printf: @printf
using Random: Xoshiro, randn

const AREA = 20.0                  # m², free surface of the tank
const DT = 600.0                   # s, one reading every ten minutes
const DAY = 144                    # readings per day
const H = 36                       # forecast horizon: 36 readings, six hours

"The pump schedule (m³/s). The operator knows it in advance."
pump_flow(t) = 0.0075 * (1 + 0.5 * sin(2π * t / 86400))

"Water drawn by the town (m³/s). It changes slowly and is not in the model."
town_demand(t) = 0.0005 * (1 + sin(2π * t / (3.7 * 86400)))

"""
The tank as Otwin components: a tank, an outlet orifice and the pump. With
`demand = true` it also has the town's draw, which the operator's model does
not know about.
"""
function tank_model(; discharge_coefficient, demand = false)
    hyd = components(:hydraulic)
    tank = hyd.Tank(AREA; level = 2.0, name = "tank")
    outlet = hyd.Orifice(0.002; discharge_coefficient, name = "outlet")
    pump = hyd.FlowSource(; name = "pump")
    air = hyd.Atmosphere(; name = "air")
    parts = Any[tank, outlet, pump, air]
    at_tank, at_air = Any[tank.port, outlet.a, pump.a], Any[outlet.b, pump.b, air.port]
    if demand
        town = hyd.FlowSource(; name = "town")
        push!(parts, town)
        push!(at_tank, town.b)
        push!(at_air, town.a)
    end
    sys = system(parts...)
    connect!(sys, at_tank...)
    connect!(sys, at_air...)
    return compile(sys)
end

# ------------------------------------------------------------------ the plant
# Eight days of level readings from the real tank. Its outlet discharges a
# little more than the data sheet says (0.63, not 0.60), the town draws water
# the model does not know about, and the sensor has 5 mm of noise.
t = collect(0:(8DAY - 1)) .* DT
real_tank = tank_model(; discharge_coefficient = 0.63, demand = true)
level = simulate(real_tank, t; inputs = Dict("pump" => pump_flow, "town" => town_demand))["tank.level"]
reading = level .+ 0.005 .* randn(Xoshiro(1), length(t))

# ------------------------------------------------------------------- the model
# The operator's model: the data-sheet outlet and no town demand. Fit the
# discharge coefficient to the first two days.
model = tank_model(; discharge_coefficient = 0.60)
fit = fit_parameters(
    model, t[1:2DAY], "tank.level" => reading[1:2DAY], ["outlet.discharge_coefficient"];
    inputs = Dict("pump" => pump_flow), x0 = Dict("tank.volume" => AREA * reading[1]),
)
println(fit, "\n")

# Keep the fitted model as a file, the way a twin would be deployed, and load it back.
path = save_model(fit.model, joinpath(mktempdir(), "storage_tank.json"))
twin = load_model(path)

"""
Forecast with the model: start from the last reading and run the pump
schedule forward. `history` is every reading up to now, so its length gives
the time.
"""
function forecaster(history, horizon)
    k = length(history)
    tr = simulate(twin, t[k:(k + horizon)];
                  x0 = Dict("tank.volume" => AREA * history[end]),
                  inputs = Dict("pump" => pump_flow))
    return tr["tank.level"][2:end]
end

# ---------------------------------------------------------------- calibration
# Out-of-sample errors from the first five days, at every horizon up to six
# hours. Calibrating on in-sample residuals would give a band that is too
# narrow.
cal = rolling_origin_residuals(forecaster, reading[1:5DAY]; step = 6, min_train = DAY, max_horizon = H)
band = calibrate(cal.residuals, cal.horizons; level = 0.9, max_horizon = H)
println(band, "\n")

# A forecast with its range, for six hours after the morning reading of day 6.
now = 5DAY + 36
fc = forecast(forecaster, reading[1:now], H, band)
println("six hours from day 6, 06:00 (every hour):")
for h in 6:6:H
    @printf("  +%d h  level %.3f m   90 %% range %.3f to %.3f m\n",
            h ÷ 6, fc.prediction[h], fc.lower[h], fc.upper[h])
end
println()

# ---------------------------------------------------------------------- audit
# Days 6 to 8 were not used to fit or to calibrate. Forecast from every hour
# and audit the range by horizon.
observed, prediction, lower, upper, horizon = Float64[], Float64[], Float64[], Float64[], Int[]
for k in (5DAY):6:(length(t) - H)
    f = forecast(forecaster, reading[1:k], H, band)
    append!(observed, reading[(k + 1):(k + H)])
    append!(prediction, f.prediction)
    append!(lower, f.lower)
    append!(upper, f.upper)
    append!(horizon, 1:H)
end

audit = coverage_audit(observed, prediction, lower, upper;
                       level = 0.9, horizons = horizon, tranches = [0, 6, 18, 36])
display(audit)
println()

# How far below the forecast can the level fall? The margin at 5 % risk is
# the distance below the forecast the operator can count on 95 % of the time.
risk = margin_risk(observed .- prediction, 0.0, [-0.10, -0.05, 0.0])
display(risk)
println()

out = mktempdir()
write(joinpath(out, "audit.html"), to_html(audit) * "\n" * to_html(risk))
write(joinpath(out, "audit.json"), to_json(audit))
println("report sections written to ", out)
