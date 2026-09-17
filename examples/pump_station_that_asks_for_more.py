"""The pump that asks for more every month.

The maintenance problem
-----------------------
A feed pump pushes water from a tank through a filter stage into a treatment
process. Month after month the operator turns the pump up to keep the flow at
the setpoint, and the energy bill grows. Nobody has written down how much of
the extra energy is the filter fouling and when cleaning pays for itself.

What you write
--------------
The line, as you would draw it: a tank, a suction pipe, the pump, the filter,
the outfall. Numbers from the data sheets. No equations.

What otwin does
---------------
``otwin.compile`` turns that drawing into a model with two states (the tank
volume and the water momentum in the pump) and every pressure, flow and power
on the line as a named output. ``model.with_parameters`` changes the fouling
without recompiling, so a whole year of fouling is one loop.

Run it:

    python examples/pump_station_that_asks_for_more.py
"""

import otwin
from otwin.components.hydraulic import Atmosphere, Filter, Pipe, Pump, Tank

# ------------------------------------------------------------- the line
tank = Tank(area=5000.0, level=3.0, name="tank")  # a reservoir: 5000 m^2, 3 m deep
suction = Pipe(resistance=5e5, name="suction")  # Pa per m^3/s, from the sheet
pump = Pump(shutoff=4.0e5, max_flow=0.08, name="pump")  # nameplate: 40 m, 288 m^3/h
filt = Filter(resistance=2.0e6, name="filter")  # clean: 2 bar at 0.1 m^3/s
outfall = Atmosphere(name="outfall")

line = tank >> suction >> pump >> filt >> outfall
print(line.summary())

model = otwin.compile(line, dt=1.0)
print(model.summary())

# The pump runs on a variable-speed drive. Speed x s moves a centrifugal
# pump's shut-off pressure by s^2 and leaves the curve's own loss term where
# it is (affinity laws), so the speed is one parameter: pump.head.pressure.
# The plant runs it at 75 % on a clean filter.


def at_speed(m, s, **more):
    return m.with_parameters({"pump.head.pressure": s * s * pump.shutoff, **more})


SPEED_0 = 0.75


def operating_point(m, seconds=900):
    """Run to steady flow and read the line."""
    state = m.initial_state()
    for _ in range(seconds):
        state = m.step(state)
    return m.outputs(state)


# ------------------------------------------------------------- clean line
clean = operating_point(at_speed(model, SPEED_0))
Q0 = clean["pump.flow"]
print(
    f"\nclean line at {SPEED_0:.0%} speed: {Q0 * 3600:.0f} m^3/h at "
    f"{clean['pump.pressure_rise'] / 1e5:.2f} bar, "
    f"{clean['pump.hydraulic_power'] / 1e3:.1f} kW to the water"
)

# ------------------------------------------------------------- a year of fouling
# A clean filter, then 15 % more resistance every month (the site's history).
print("\nleave the pump alone, let the flow fall:")
print(f"{'month':>5} {'fouling':>8} {'flow m3/h':>10} {'rise bar':>9} {'kW':>6}")
for month in range(0, 13, 2):
    out = operating_point(at_speed(model, SPEED_0, **{"filter.fouling": 1.15**month - 1}))
    print(
        f"{month:>5} {1.15**month - 1:>8.2f} {out['pump.flow'] * 3600:>10.0f} "
        f"{out['pump.pressure_rise'] / 1e5:>9.2f} {out['pump.hydraulic_power'] / 1e3:>6.1f}"
    )

# ------------------------------------------------------------- turn the pump up
# What the operator does: raise the speed until the flow is back at Q0. The
# drive stops at 100 %; after that the flow is whatever the fouled line gives.


def speed_for_flow(fouling, target):
    """Bisection on the speed ratio until the flow is back at the target."""
    lo, hi = SPEED_0, 1.0
    if (
        operating_point(at_speed(model, hi, **{"filter.fouling": fouling}))["pump.flow"]
        < target
    ):
        return hi, operating_point(at_speed(model, hi, **{"filter.fouling": fouling}))
    for _ in range(30):
        s = 0.5 * (lo + hi)
        m = at_speed(model, s, **{"filter.fouling": fouling})
        if operating_point(m)["pump.flow"] < target:
            lo = s
        else:
            hi = s
    return hi, operating_point(at_speed(model, hi, **{"filter.fouling": fouling}))


print("\nkeep the flow, turn the pump up:")
print(
    f"{'month':>5} {'speed':>6} {'flow m3/h':>10} {'rise bar':>9} {'kW':>6} {'extra MWh/month':>16}"
)
hours_per_month = 24 * 30
for month in range(0, 13, 2):
    fouling = 1.15**month - 1
    s, out = speed_for_flow(fouling, Q0)
    extra = (
        out["pump.hydraulic_power"] - clean["pump.hydraulic_power"]
    ) * hours_per_month
    flag = "  <- drive at 100 %, flow lost" if out["pump.flow"] < 0.999 * Q0 else ""
    print(
        f"{month:>5} {s:>6.3f} {out['pump.flow'] * 3600:>10.0f} {out['pump.pressure_rise'] / 1e5:>9.2f} "
        f"{out['pump.hydraulic_power'] / 1e3:>6.1f} {extra / 1e6:>16.2f}{flag}"
    )

# ------------------------------------------------------------- the answer
# The energy lost to fouling is the filter's own pressure drop above clean,
# times the flow. Cleaning costs a fixed sum; the model gives the month at
# which the extra energy bought since the last cleaning passes that sum.
price_per_mwh = (
    120.0  # EUR, hydraulic energy at the water (divide by pump efficiency for the meter)
)
cleaning_cost = 1500.0  # EUR per filter cleaning

spent = 0.0
for month in range(1, 25):
    fouling = 1.15**month - 1
    s, out = speed_for_flow(fouling, Q0)
    extra_mwh = (
        (out["pump.hydraulic_power"] - clean["pump.hydraulic_power"])
        * hours_per_month
        / 1e6
    )
    spent += extra_mwh * price_per_mwh
    if spent >= cleaning_cost:
        print(
            f"\ncleaning pays for itself after {month} months: "
            f"{spent:.0f} EUR of extra pumping against {cleaning_cost:.0f} EUR to clean, "
            f"with the drive at {s:.0%}"
        )
        break

# ------------------------------------------------------------- check by hand
# One line of algebra to make sure the model says what the drawing says: at
# steady flow, reservoir head + pump curve = suction loss + filter loss. The
# 80 Pa left over is the 8 mm the reservoir dropped in fifteen minutes.
rho_g_h = 1000 * 9.81 * 3.0
lhs = rho_g_h + SPEED_0**2 * 4.0e5 - 4.0e5 * (Q0 / 0.08) ** 2
rhs = (5e5 + 2.0e6) * Q0
print(f"\nby hand, clean line: head + pump = {lhs:.0f} Pa, losses = {rhs:.0f} Pa")
assert abs(lhs - rhs) < 1000 * 9.81 * 0.01  # within a centimetre of reservoir
