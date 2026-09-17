"""The battery module that runs hotter than last year.

The maintenance problem
-----------------------
A module in a storage container does the same duty every day: one hour of
discharge, one hour of charge, at half a C. Its temperature sensor now reads a
few degrees more than it did at commissioning, at the same ambient. Two
things could do that, and they call for different work orders:

* the cells have aged and their internal resistance has grown, so the same
  current makes more heat;
* the cooling has degraded (a clogged air filter, a tired fan), so the same
  heat raises the temperature more.

What you write
--------------
The module as a data sheet describes it: capacity, the open-circuit voltage
curve, the internal resistance and two polarisation branches, the heat
capacity. Then the cooling: a convection to the container air. No equations.

What otwin does
---------------
``otwin.compile`` gives one model with four states: the charge, the two
polarisation charges, the heat in the cell. Its outputs include the terminal
voltage and the temperature, which is what the two sensors on the module
measure. ``with_parameters`` ages the cells or clogs the filter without
rebuilding anything, so the two suspects are two lines of code.

Run it:

    python examples/battery_that_runs_hot.py
"""

import numpy as np

import otwin
from otwin.components.battery import Battery
from otwin.components.electrical import CurrentSource, Ground
from otwin.components.thermal import Ambient, Convection

# ------------------------------------------------------------- the module
# Data-sheet numbers of an LFP cell, scaled to a 1p module for clarity.
OCV = [
    (0.0, 2.80),
    (0.05, 3.15),
    (0.2, 3.25),
    (0.5, 3.30),
    (0.8, 3.33),
    (0.95, 3.40),
    (1.0, 3.55),
]

cell = Battery(
    capacity=100.0,  # Ah
    ocv=OCV,
    resistance=1.0e-3,  # ohm, the ohmic part
    rc_branches=[(0.5e-3, 20e3), (0.8e-3, 200e3)],  # (ohm, F): seconds and minutes
    thermal=1200.0,  # J/K, about 1.3 kg of cell
    soc=0.9,
    temperature=298.15,
    name="cell",
)
load = CurrentSource(None, name="load")  # the duty, an input in amperes
ground = Ground(name="gnd")
air = Convection(0.5, name="cooling")  # W/K, the fan and the air path
container = Ambient(298.15, name="container")

module = otwin.System(cell, load, ground, air, container, name="module")
# load.p -> load.n is the direction of the source current; discharge is out of cell.p
module.connect(cell.p, load.n).connect(load.p, cell.n, ground.port)
module.connect(cell.thermal, air.a).connect(air.b, container.port)
print(module.summary())

model = otwin.compile(module, dt=10.0)
print(model.summary())

# ------------------------------------------------------------- the duty
# Half a C for an hour out, half a C for an hour in, all day (SOC swings
# between 0.9 and 0.4). Positive is discharge.
I_DUTY = 50.0


def duty(t):
    return I_DUTY if (t // 3600) % 2 == 0 else -I_DUTY


DAY = 24 * 3600


def a_day(m):
    """Run a full day and report what the two sensors see in the last cycle."""
    run = m.simulate(t_span=(0, DAY), dt=10.0, inputs={"load": duty})
    last = run.t >= DAY - 7200
    T = run["cell.temperature"][last] - 273.15
    # the voltage jump when the current reverses from discharge to charge,
    # read five minutes after the switch: 2 I R, the resistance seen live
    switch = DAY - 3600
    before = run["cell.voltage"][np.searchsorted(run.t, switch) - 1]
    after = run["cell.voltage"][np.searchsorted(run.t, switch + 300)]
    return {
        "T max degC": T.max(),
        "T mean degC": T.mean(),
        "V jump mV": 1e3 * (after - before),
        "heat W": run["cell.heat_flow"][last].mean(),
        "soc": run["cell.soc"][-1],
    }


def show(label, r):
    print(
        f"  {label:<22} T mean {r['T mean degC']:5.1f} C   T max {r['T max degC']:5.1f} C   "
        f"V jump at reversal {r['V jump mV']:4.0f} mV   heat {r['heat W']:5.1f} W"
    )


print("\nwhat the module's two sensors see over the last charge/discharge cycle:")
new = a_day(model)
show("commissioning", new)

# ------------------------------------------------------------- two suspects
# Aged cells: every resistance 50 % up.
aged = model.with_parameters(
    {
        "cell.r0.resistance": 1.5e-3,
        "cell.r1.resistance": 0.75e-3,
        "cell.r2.resistance": 1.2e-3,
    }
)
show("aged cells (+50 % R)", a_day(aged))

# Degraded cooling: the air path passes a third less heat per kelvin.
clogged = model.with_parameters({"cooling.conductance": 0.5 / 1.5})
show("clogged filter (-33 %)", a_day(clogged))

# ------------------------------------------------------------- the answer
print(
    "\nBoth suspects raise the temperature by the same amount: the thermometer alone\n"
    "cannot tell them apart. The voltmeter can. When the current reverses, aged\n"
    "cells jump the terminal voltage close to 50 % more than new ones at the same current;\n"
    "a clogged filter leaves that jump exactly where it was. Two sensors the\n"
    "module already has settle which work order to write."
)

# ------------------------------------------------------------- check by hand
# Heat is I^2 R over all three resistances once the branches have settled:
# 50^2 x 2.3e-3 = 5.75 W. Over 0.5 W/K that is a rise of 11.5 K above the
# container. The daily mean is a little under that because the RC pairs give
# part of their charge back to the load after each reversal instead of
# heating. The jump at reversal is 2 I (R0 + R1) plus most of R2 after five
# minutes (its time constant is 160 s): about 2 x 50 x 2.2e-3 = 220 mV.
R_ALL = 1.0e-3 + 0.5e-3 + 0.8e-3
print(
    f"\nby hand: I^2 R = {I_DUTY**2 * R_ALL:.2f} W, steady rise = "
    f"{I_DUTY**2 * R_ALL / 0.5:.1f} K; model mean rise = {new['T mean degC'] - 25.0:.1f} K"
)
assert np.isclose(new["heat W"], I_DUTY**2 * R_ALL, rtol=0.05)
assert 200 < new["V jump mV"] < 230
