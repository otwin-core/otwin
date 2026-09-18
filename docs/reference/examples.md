# Examples

Each example is built around an engineering question rather than around an API. Every
notebook opens with the question it answers, what Otwin does, what you write
yourself, and something you can deliberately break to see the check fire.

They live in the [examples
directory](https://github.com/otwin-core/otwin/tree/main/examples) of the repository
and run the first time in the order below.

| # | Notebook | The question | Data |
|---|---|---|---|
| 01 | [A model that cannot invent energy](https://github.com/otwin-core/otwin/blob/main/examples/otwin_01_a_model_that_cannot_invent_energy.ipynb) | Two reservoirs, a pump, a flywheel and a bearing. How do you know the equations obey physics everywhere, not only where you checked? | simulation |
| 02 | [When the process makes entropy](https://github.com/otwin-core/otwin/blob/main/examples/otwin_02_when_the_process_makes_entropy.ipynb) | How do you write a reactor model that cannot violate the second law? | simulation |
| 03 | [Scoring a forecast so it cannot flatter you](https://github.com/otwin-core/otwin/blob/main/examples/otwin_03_scoring_a_forecast.ipynb) | A model forecasts 68 cycles ahead. How good is it, really? | NASA PCoE |
| 04 | [A band whose 90 % means 90 %](https://github.com/otwin-core/otwin/blob/main/examples/otwin_04_a_band_whose_90_means_90.ipynb) | How wide should the interval be, and how do you know? | NASA PCoE |
| 05 | [From a noisy sensor to a state you can trust](https://github.com/otwin-core/otwin/blob/main/examples/otwin_05_from_a_noisy_sensor_to_a_state.ipynb) | The sensor says 106 %. What is the state? | NASA PCoE |
| 06 | [The twin that says no](https://github.com/otwin-core/otwin/blob/main/examples/otwin_06_the_twin_that_says_no.ipynb) | What should a twin say when asked something it was never validated for? | simulation |
| 07 | [All of it, on eight years of field data](https://github.com/otwin-core/otwin/blob/main/examples/otwin_07_field_data.ipynb) | Does the protocol hold on 18 real systems with manual capacity tests as truth? | RWTH field data |
| 08 | [Does the physics earn its place?](https://github.com/otwin-core/otwin/blob/main/examples/otwin_08_does_the_physics_earn_its_place.ipynb) | Would a structured fade law, or a learned residual, narrow that band? | RWTH field data |

## Maintenance problems, as scripts

Three scripts are written the way the questions arrive in a plant rather than the
way a tutorial is written. Each ends in a number checked by hand, and each runs as
part of the test suite.

| Script | The question |
|---|---|
| [battery\_that\_runs\_hot.py](https://github.com/otwin-core/otwin/blob/main/examples/battery_that_runs_hot.py) | The pack runs hot. Is it the cells or the air filter? The voltage step when the current reverses decides it. |
| [pump\_station\_that\_asks\_for\_more.py](https://github.com/otwin-core/otwin/blob/main/examples/pump_station_that_asks_for_more.py) | A year of fouling, the drive climbing to 100 %. Which month does cleaning pay for itself? |
| [bess\_end\_to\_end.py](https://github.com/otwin-core/otwin/blob/main/examples/bess_end_to_end.py) | The whole chain on a battery bank, from a simulated SunSpec device to a refusal, with no hardware. |
