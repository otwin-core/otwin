# Otwin.jl computes nothing itself, so these tests check the boundary: Julia
# values go in, Python's otwin computes, and Julia values come out with the
# right types, the right numbers and refusals intact. Expected numbers come
# from closed forms or from the values pinned in otwin's own docstrings.

using Test
using Otwin
using PythonCall: PyException
using DataFrames: DataFrame, nrow

function drain_tank(; cd = 0.6, level = 2.0, pump = true)
    hyd = components(:hydraulic)
    tank = hyd.Tank(1.0; level = level, name = "tank")
    drain = hyd.Orifice(0.01; discharge_coefficient = cd, name = "drain")
    air = hyd.Atmosphere(; name = "air")
    if pump
        inflow = hyd.FlowSource(; name = "pump")
        s = system(tank, drain, inflow, air)
        connect!(s, tank.port, drain.a, inflow.a)
        connect!(s, drain.b, inflow.b, air.port)
    else
        s = system(tank, drain, air)
        connect!(s, tank.port, drain.a)
        connect!(s, drain.b, air.port)
    end
    return compile(s)
end

@testset "Otwin.jl" begin
    @test otwin_version() isa String

    @testset "model: build, simulate, names" begin
        m = drain_tank(; pump = false)
        @test m isa Model
        @test "tank.level" in output_names(m)
        @test state_names(m) == ["tank.volume"]
        @test parameters(m)["drain.discharge_coefficient"] == 0.6

        # Torricelli: h(t) = (sqrt(h0) - Cd a sqrt(2g) t / (2A))^2
        t = collect(0.0:0.5:20.0)
        tr = simulate(m, t)
        @test tr isa Trajectory
        @test tr.t == t
        k = 0.6 * 0.01 * sqrt(2 * 9.81) / 2
        @test tr["tank.level"][end] ≈ (sqrt(2.0) - k * 20.0)^2 rtol = 1e-3
    end

    @testset "inputs: number, vector and function agree" begin
        m = drain_tank()
        t = collect(0.0:1.0:30.0)
        a = simulate(m, t; inputs = Dict("pump" => 0.02))["tank.level"]
        b = simulate(m, t; inputs = Dict("pump" => fill(0.02, length(t))))["tank.level"]
        c = simulate(m, t; inputs = Dict("pump" => t -> 0.02))["tank.level"]
        @test a == b == c
        d = simulate(m, t; x0 = Dict("tank.volume" => 0.5))["tank.level"]
        @test d[1] == 0.5
    end

    @testset "parameters: copy, fit, save and load" begin
        m = drain_tank()
        m2 = with_parameters(m, "drain.discharge_coefficient" => 0.65)
        @test parameters(m)["drain.discharge_coefficient"] == 0.6   # untouched
        @test parameters(m2)["drain.discharge_coefficient"] == 0.65

        t = collect(0.0:1.0:60.0)
        y = simulate(m2, t; inputs = Dict("pump" => 0.01))["tank.level"]
        f = fit_parameters(m, t, "tank.level" => y, ["drain.discharge_coefficient"];
                           inputs = Dict("pump" => 0.01))
        @test f isa FitResult
        @test f.success
        @test f.values["drain.discharge_coefficient"] ≈ 0.65 rtol = 1e-6
        @test f.identified == Dict("drain.discharge_coefficient" => true)

        path = save_model(f.model, joinpath(mktempdir(), "tank.json"))
        @test parameters(load_model(path)) == parameters(f.model)
    end

    @testset "forecast: residuals, band, interval" begin
        line = collect(1.0 .- 0.002 .* (0:119))
        slope(h) = (h[end] - h[1]) / (length(h) - 1)
        straight(h, n) = h[end] .+ slope(h) .* (1:n)
        r = rolling_origin_residuals(straight, line; step = 10)
        @test r.residuals isa Vector{Float64} && r.horizons isa Vector{Int}
        @test maximum(abs, r.residuals) < 1e-9   # a line, forecast by a line

        band = calibrate(collect(1.0:100.0), ones(Int, 100); level = 0.9, method = :split)
        @test band.half_width == [91.0]          # otwin.forecast.conformal_quantile doc
        iv = interval(band, [1.0, 2.0])
        @test iv.lower == [-90.0, -89.0] && iv.upper == [92.0, 93.0]

        h = repeat(1:10; inner = 40)
        res = repeat(collect(range(-1.0, 1.0; length = 40)), 10) .* sqrt.(h)
        hb = calibrate(res, h; level = 0.9, max_horizon = 15)
        @test length(hb.half_width) == 15
        @test hb.extrapolated == [falses(10); trues(5)]
        fc = forecast((hist, n) -> fill(hist[end], n), [1.0, 2.0], 12, hb)
        @test fc.prediction == fill(2.0, 12)
        @test all(fc.lower .< fc.prediction .< fc.upper)
        @test fc.extrapolated == [falses(10); trues(2)]

        @test_throws ArgumentError calibrate([1.0], [1]; level = 0.9, method = :other)
    end

    @testset "coverage audit: default, tranches, refusal" begin
        h = repeat(1:12, 20)
        y = zeros(length(h))
        half = [k <= 6 ? 1.0 : 0.0 for k in h]
        pred = [k <= 6 ? 0.0 : 0.5 for k in h]
        a = coverage_audit(y, pred, pred .- half, pred .+ half; level = 0.9)
        @test a isa CoverageAudit
        @test a.overall.coverage == 0.5 && a.tranches === nothing
        @test occursin("\"tranches\": null", to_json(a))

        a = coverage_audit(y, pred, pred .- half, pred .+ half; level = 0.9,
                           horizons = h, tranches = [0, 6, 12, 24])
        labels = [r.label for r in a.tranches]
        @test labels == ["(0, 6]", "(6, 12]", "(12, 24]"]
        @test [r.coverage for r in a.tranches] == [1.0, 0.0, nothing]
        @test a.tranches[1].verdict == "wider than stated"
        @test a.tranches[2].median_error == -0.5
        empty = a.tranches[3]
        @test !answered(empty)
        @test empty.refusal == "0 contrasts; the minimum is 10"
        @test empty.ci_low === nothing && empty.mean_width === nothing

        tab = table(a)
        @test tab.label == ["all", "(0, 6]", "(6, 12]", "(12, 24]"]
        @test ismissing(tab.coverage[4]) && tab.coverage[2] == 1.0
        @test startswith(to_html(a), "<section class=\"otwin-coverage\">")
        @test nrow(DataFrame(a)) == 4

        @test_throws PyException coverage_audit(y, pred, pred, pred; level = 1.5)
    end

    @testset "margin risk" begin
        m = margin_risk(collect(1.0:100.0), 0.0, [0.0, 10.0])
        @test answered(m)
        @test m.margin_at_risk == [5.0, 10.0, 20.0]   # floor(risk * 101)-th smallest
        @test m.probabilities == [0.0, 0.09] && m.n_short == [0, 9]
        @test nrow(DataFrame(m)) == 2

        r = margin_risk(collect(1.0:12.0), 50.0, [0.0])
        @test !answered(r)
        @test r.refusal == "12 residuals; at least 19 are needed for a margin at 5 % risk"
        @test r.probabilities === nothing && r.margin_at_risk === nothing
        @test ismissing(table(r).probability[1])
        @test occursin("\"probabilities\": null", to_json(r))
    end

    @testset "transfer validation" begin
        # unit i sits at i^2; the leave-one-out mean is (sum - own) / (K - 1)
        fleet = Dict("u$i" => fill(Float64(i^2), 20) for i in 0:4)
        seen = Vector{Vector{String}}()
        function fit(cal)
            push!(seen, sort!(collect(keys(cal))))
            mu = sum(sum, values(cal)) / sum(length, values(cal))
            return (hist, n) -> (fill(mu, n), fill(mu - 1, n), fill(mu + 1, n))
        end
        tv = transfer_validation(fleet, fit, [0, 2, 4]; level = 0.9, min_history = 10, step = 5)
        @test tv isa TransferValidation
        @test sort(seen) == sort([sort([u for u in keys(fleet) if u != h]) for h in keys(fleet)])
        @test all(!(h in v) for (h, v) in tv.calibration_units)

        c = tv.contrasts
        total = sum(Float64(i^2) for i in 0:4)
        for i in 0:4
            rows = c.unit .== "u$i"
            @test all(c.prediction[rows] .≈ (total - i^2) / 4)
        end
        @test c.error == c.observed .- c.prediction   # Otwin's own column, round-tripped
        @test first.(tv.tranche_coverage) == ["(0, 2]", "(2, 4]"]
        @test tv.overall_coverage == tv.audit.overall.coverage
        @test nrow(DataFrame(tv)) == length(c.observed)

        @test_throws PyException transfer_validation(
            Dict("a" => collect(1.0:20.0)), fit, [0, 2]; level = 0.9)
    end
end
