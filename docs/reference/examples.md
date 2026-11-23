# Examples and tutorials

Ten tutorials, each a real piece of equipment modelled from the component
library and run end to end. Every tutorial exists twice from one source: as a
page in the [tutorials directory](https://github.com/otwin-core/otwin/tree/main/tutorials)
of the repository, with the output of every step under it, and as a notebook in
the [examples directory](https://github.com/otwin-core/otwin/tree/main/examples)
that runs as part of the test suite. The pages and the notebooks cannot drift:
`tutorials/build.py` writes both.

Each page has a rendered illustration of the asset, a process diagram in the
engineering notation of its domain (ISA-5.1 for process, IEC 60617 for
electrical, free-body schematics for mechanical), the engineering question, and
the steps with their code, their printed output and their plots.

| # | Tutorial | Domain | Components |
|---|---|---|---|
| 1 | [A battery energy storage container](https://github.com/otwin-core/otwin/blob/main/tutorials/01_battery_energy_storage.md) | energy storage, thermal | `Battery`, `CurrentSource`, `Ground`, `Convection`, `ThermalMass`, `HeatSource`, `ThermalResistance`, `Ambient` |
| 2 | [A DC distribution feeder](https://github.com/otwin-core/otwin/blob/main/tutorials/02_dc_distribution_feeder.md) | energy distribution, electrical | `VoltageSource`, `Resistor`, `Inductor`, `Capacitor`, `Transformer`, `CurrentSource`, `Ground` |
| 3 | [A vehicle suspension](https://github.com/otwin-core/otwin/blob/main/tutorials/03_vehicle_suspension.md) | mechanical | `Mass`, `Spring`, `Damper`, `ForceSource`, `VelocitySource`, `Fixed` |
| 4 | [A wind turbine drivetrain](https://github.com/otwin-core/otwin/blob/main/tutorials/04_wind_turbine_drivetrain.md) | mechanical, energy | `Inertia`, `TorsionSpring`, `RotationalDamper`, `TorqueSource`, `SpeedSource`, `Housing`, `Transformer` |
| 5 | [A municipal water supply](https://github.com/otwin-core/otwin/blob/main/tutorials/05_water_supply.md) | hydraulics, civil | `Tank`, `Pump`, `Filter`, `Pipe`, `FluidInertance`, `Orifice`, `FlowSource`, `PressureSource`, `Atmosphere` |
| 6 | [Wastewater disinfection](https://github.com/otwin-core/otwin/blob/main/tutorials/06_wastewater_disinfection.md) | chemical, environmental | `Species`, `Reaction`, `Dose`, `Outflow`, `Accumulator`, `MixedReactor`, `TanksInSeries` |
| 7 | [A heated building](https://github.com/otwin-core/otwin/blob/main/tutorials/07_heated_building.md) | thermal, building services | `ThermalMass`, `ThermalResistance`, `Convection`, `HeatSource`, `Losses`, `Ambient` |
| 8 | [A motor-driven pump](https://github.com/otwin-core/otwin/blob/main/tutorials/08_motor_driven_pump.md) | electromechanical, hydraulic | `DCMotor`, `Gyrator`, `VoltageSource`, `Pipe`, `Tank`, `Atmosphere`, `Housing` |
| 9 | [A flywheel energy store](https://github.com/otwin-core/otwin/blob/main/tutorials/09_flywheel_storage.md) | energy storage | `Storage`, `Dissipator`, `Source`, `Reference`, `Transformer` from `fundamental` |
| 10 | [From a model to a digital twin](https://github.com/otwin-core/otwin/blob/main/tutorials/10_from_model_to_twin.md) | the twin workflow | your own `Component` and `Composite`, `fit_parameters`, conformal forecasting, `coverage_audit`, `Envelope` |

Together they use every component in the library. To run a notebook:

```bash
pip install "otwin[engine,tutorials]"
jupyter lab examples/05_water_supply.ipynb
```

The NASA battery data that earlier examples used still ships in
`examples/data/` and is registered in `otwin.io.load`.
