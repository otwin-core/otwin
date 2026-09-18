# Devices: a battery and a pump line

The question this page answers: can you build the system you maintain
without writing its equations? Two devices from the library, each described
the way its data sheet describes it, each compiled and stepped. Every number
printed here is checked in the test suite against a one-line hand
calculation.

## A battery module

`Battery` is an equivalent-circuit cell or pack: the open-circuit voltage
against state of charge, a series resistance, one RC pair per polarisation
branch and, when you give a heat capacity, a thermal mass that the ohmic
losses warm. You give the numbers; the compiler writes the four state
equations.

```python
import otwin
from otwin.components.battery import Battery
from otwin.components.electrical import CurrentSource, Ground
from otwin.components.thermal import Ambient, Convection

cell = Battery(
    capacity=100.0,                                  # Ah
    ocv=[(0.0, 2.8), (0.05, 3.15), (0.5, 3.3), (0.95, 3.4), (1.0, 3.55)],
    resistance=1e-3,                                 # ohm, the ohmic part
    rc_branches=[(0.5e-3, 20e3), (0.8e-3, 200e3)],   # (ohm, F): 10 s and 160 s
    thermal=1200.0,                                  # J/K
    soc=0.9,
    name="cell",
)
load = CurrentSource(None, name="load")              # amperes; None makes it an input
cooling = Convection(0.5, name="cooling")            # W/K to the container air
air = Ambient(298.15, name="air")
gnd = Ground(name="gnd")

module = gnd >> cell >> load >> gnd                  # the electrical loop, closed on ground
module.connect(cell.thermal, cooling.a)              # the thermal circuit hangs off the cell
module.connect(cooling.b, air.port)
print(module.summary())
```

```text
system: 5 components, 5 connections, domains ['electrical', 'thermal']
  gnd (Ground) ports: port
  cell (Battery) ports: p, n, thermal
  load (CurrentSource) ports: p, n
  cooling (Convection) ports: a, b; conductance=0.5 W/K
  air (Ambient) ports: port
  gnd.port = cell.n
  cell.p = load.n
  load.p = gnd.port
  cell.thermal = cooling.a
  cooling.b = air.port
```

A chain follows the flow a source pushes out, so `gnd >> cell >> load >> gnd`
puts the cell's `p` on the load and a positive load current is a discharge.
Compile with the time step you will run at, then step:

```python
model = otwin.compile(module, dt=10.0)

state = model.initial_state()
for _ in range(360):                                 # one hour at 50 A
    state = model.step(state, {"load": 50.0})

out = model.outputs(state)
print(f"soc {out['cell.soc']:.2f}   voltage {out['cell.voltage']:.3f} V   "
      f"cell {out['cell.temperature'] - 273.15:.1f} °C   heat {out['cell.heat_flow']:.2f} W")
```

```text
soc 0.40   voltage 3.152 V   cell 33.8 °C   heat 5.75 W
```

By hand: 50 A for an hour is 50 Ah, half the capacity, so the state of
charge falls from 0.9 to 0.4. The open-circuit voltage there is 3.267 V from
the table, less 50 A over the 2.3 mΩ of the three resistances once the RC
pairs have charged: 3.152 V. The heat is I²R = 5.75 W, and over 0.5 W/K it
would lift the cell 11.5 K in the long run; after one hour of a 40-minute
time constant it has done 78 % of that: close to 9 K over 25 °C.

`model.outputs(state)` reads the state returned by `step` with the inputs of
that step, which is what a resistor's power needs. Every part of the module
is an output too: `cell.r0.power`, `cell.c1.voltage`, `cell.ocv.voltage`,
`cell.losses.heat_flow`. `print(model.summary())` lists the states and
parameters; every parameter can be changed later with `with_parameters`.

```python
aged = model.with_parameters({"cell.r0.resistance": 1.5e-3})
state = aged.initial_state()
for _ in range(360):
    state = aged.step(state, {"load": 50.0})
print(f"with R0 up 50 %: voltage {aged.outputs(state)['cell.voltage']:.3f} V, "
      f"heat {aged.outputs(state)['cell.heat_flow']:.2f} W")
```

```text
with R0 up 50 %: voltage 3.127 V, heat 7.00 W
```

[`examples/battery_that_runs_hot.py`](https://github.com/otwin-core/otwin/blob/main/examples/battery_that_runs_hot.py)
takes this module through a day of duty and separates aged cells from a
clogged air filter with the two sensors the module already has.

## A pump line

A pump line is a line and nothing else, so `>>` is all it takes. A two-port
component (`a, b`; `p, n`; `inlet, outlet`) is entered at its first port and
left at its second, a source the other way round, following the flow it
pushes; a one-port component (a tank, the atmosphere) joins the node between
its neighbours. So the line reads left to right:

```python
from otwin.components.hydraulic import Atmosphere, Filter, Pipe, Pump, Tank

line = (
    Tank(area=5000.0, level=3.0, name="tank")           # a reservoir
    >> Pipe(resistance=5e5, name="suction")             # Pa s/m^3
    >> Pump(shutoff=4e5, max_flow=0.08, name="pump")    # 40 m, 288 m^3/h at zero head
    >> Filter(resistance=2e6, name="filter")            # Pa s/m^3, clean
    >> Atmosphere(name="outfall")
)
print(line.unconnected())
model = otwin.compile(line, dt=1.0)
print(model.state_names)
print(model.param_names)
```

```text
[]
['tank.volume', 'pump.water.flow_momentum']
['tank.area', 'tank.base_elevation', 'tank.density', 'tank.gravity', 'suction.resistance', 'pump.curve.friction', 'pump.water.inertance', 'filter.resistance', 'filter.fouling', 'pump.head.pressure']
```

Two states: the water in the reservoir and the momentum of the water in the
pump. `print(model.summary())` gives the same with units, initial values and
the component list; every name in `param_names` can be changed with
`with_parameters`.

A pump is three things inside: a pressure source at the shut-off value, a
loss that follows the curve down from it, and the inertia of the water in
the pump. The inertia is real and it is also what lets the compiler make the
flow a state rather than solve the curve against the network at every step.
`Pump(curve=[(flow, pressure_rise), ...])` takes a measured curve instead of
the parabola.

```python
def steady(m, seconds=900):
    state = m.initial_state()
    for _ in range(seconds):
        state = m.step(state)
    return m.outputs(state)

clean = steady(model)
print(f"clean:  {clean['pump.flow'] * 3600:.0f} m³/h, pump rise {clean['pump.pressure_rise'] / 1e5:.2f} bar, "
      f"{clean['pump.hydraulic_power'] / 1e3:.1f} kW to the water")

fouled = steady(model.with_parameters({"filter.fouling": 1.0}))
print(f"fouled: {fouled['pump.flow'] * 3600:.0f} m³/h, pump rise {fouled['pump.pressure_rise'] / 1e5:.2f} bar, "
      f"{fouled['pump.hydraulic_power'] / 1e3:.1f} kW to the water")
```

```text
clean:  235 m³/h, pump rise 1.34 bar, 8.7 kW to the water
fouled: 196 m³/h, pump rise 2.15 bar, 11.7 kW to the water
```

By hand, at steady flow the reservoir head plus the pump curve equals the
losses on the line: 29 430 Pa + 400 000 (1 − (Q/0.08)²) = 2 500 000 Q, whose
root is Q = 0.0653 m³/s = 235 m³/h. `Filter.fouling` is the extra resistance
as a fraction of clean, so `1.0` doubles it and the same equation with
4 500 000 Q gives 196 m³/h. The pump works harder for less water, which is
the whole story of
[`examples/pump_station_that_asks_for_more.py`](https://github.com/otwin-core/otwin/blob/main/examples/pump_station_that_asks_for_more.py).

## What you did not write

No state equation, no pump curve inversion, no heat balance. The compiler
found the states (the charge stores and the water momentum), pinned the
pressures and voltages through them, read the flows off the laws, and wrote
`dx/dt`. `model.ir()` shows the result, and [Compilation](../physics/compilation.md)
explains how it got there; neither is needed to use the model.
