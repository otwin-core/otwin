# ModelingToolkit model of a storage tank, used by julia_mtk_tank.py.
using ModelingToolkit, OrdinaryDiffEq
using ModelingToolkit: t_nounits as t, D_nounits as D
@parameters area=400.0 inflow=60.0 demand=60.0       # m², m³/h, m³/h (daily mean)
@variables level(t)=3.0                               # m
eqs = [D(level) ~ (inflow - demand * (1 + 0.6 * sin(2pi * t / 24 - pi / 2))) / area]
@mtkcompile tank = System(eqs, t)
prob = ODEProblem(tank, [], (0.0, 24.0))
function forecast(level0, t0, horizon)
    p = remake(prob; u0 = [tank.level => level0], tspan = (t0, t0 + horizon))
    solve(p, Tsit5(); saveat = t0+1:t0+horizon)[tank.level]
end
